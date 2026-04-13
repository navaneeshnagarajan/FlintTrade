//! FlintTrade tick-engine — high-performance tick-level backtesting simulator.
//!
//! Exposed to Python via PyO3. Provides:
//! - Bar-by-bar simulation with configurable slippage, commission, lot size
//! - Built-in EMA crossover strategy
//! - Pairs trading with OLS cointegration signal
//! - Options strategy (straddle / strangle) with Black-Scholes Greeks
//! - Multi-leg spread backtesting with parallel batch execution (Rayon)
//! - Enhanced metrics: Sharpe, Sortino, Omega, SQN, Payoff, Recovery Factor
//! - Indian market session tracker (NSE/MCX/CDS)
//! - Monte Carlo GBM simulation with Cholesky correlated paths
//!
//! # Example (Python)
//! ```python
//! from tick_engine import TickSimulator
//!
//! sim = TickSimulator(initial_capital=100_000, slippage_pct=0.001, commission=20.0)
//! bars = [[t, o, h, l, c, v], ...]   # [timestamp, open, high, low, close, volume]
//! result = sim.run_ema_crossover(bars, fast_period=9, slow_period=21)
//! print(result)
//!
//! from tick_engine import SessionTracker, SessionConfig
//! tracker = SessionTracker(SessionConfig.nse_equity())
//!
//! from tick_engine import simulate, confidence_intervals
//! paths = simulate(returns, n_paths=1000, n_steps=252)
//! ci = confidence_intervals(paths, [0.05, 0.50, 0.95])
//! ```

// Suppress warning from PyO3 macro expansion (fixed in newer PyO3 versions)
#![allow(non_local_definitions)]

use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// Sub-modules
// ---------------------------------------------------------------------------

pub mod errors;
pub mod metrics;
pub mod monte_carlo;
pub mod session;
pub mod strategies;
pub mod types;

// Convenience re-exports
pub use session::{SessionConfig, SessionState, SessionTracker};
pub use strategies::{
    options::{black_scholes_greeks, Greeks, OptionStrategyType, OptionsConfig, OptionsStrategy},
    pairs::PairsStrategy,
    spreads::{
        iron_condor_config, run_batch, run_spreads_batch, straddle_config, strangle_config,
        LegConfig, OptionType, SpreadBacktest, SpreadConfig,
    },
};
pub use types::{BacktestResult, Signal, Tick};

// ---------------------------------------------------------------------------
// Legacy types (kept for backward compatibility with v0.1 API)
// ---------------------------------------------------------------------------

/// A single OHLCV bar (legacy v0.1 type — use `Tick` for new code).
#[pyclass(get_all, set_all)]
#[derive(Clone, Debug)]
pub struct Bar {
    pub timestamp: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[pymethods]
impl Bar {
    #[new]
    pub fn new(timestamp: i64, open: f64, high: f64, low: f64, close: f64, volume: f64) -> Self {
        Bar { timestamp, open, high, low, close, volume }
    }

    fn __repr__(&self) -> String {
        format!(
            "Bar(ts={}, o={:.2}, h={:.2}, l={:.2}, c={:.2}, v={:.0})",
            self.timestamp, self.open, self.high, self.low, self.close, self.volume
        )
    }
}

/// A completed trade record.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct Trade {
    /// Bar timestamp at entry.
    pub entry_time: i64,
    /// Bar timestamp at exit.
    pub exit_time: i64,
    /// Fill price at entry (including slippage).
    pub entry_price: f64,
    /// Fill price at exit (including slippage).
    pub exit_price: f64,
    /// Quantity (lot_size units).
    pub qty: f64,
    /// Realised P&L for this trade (in INR).
    pub pnl: f64,
    /// Direction: 1 = long, -1 = short.
    pub direction: i8,
}

#[pymethods]
impl Trade {
    fn __repr__(&self) -> String {
        let dir = if self.direction > 0 { "LONG" } else { "SHORT" };
        format!("Trade({} entry={:.2} exit={:.2} pnl={:.2})", dir, self.entry_price, self.exit_price, self.pnl)
    }
}

/// Full simulation output (legacy v0.1 type).
///
/// For new code use `BacktestResult` from `types.rs`.
#[pyclass(get_all)]
pub struct SimulationResult {
    /// Net P&L = final_capital - initial_capital.
    pub total_pnl: f64,
    /// Annualised Sharpe ratio (252 trading days).
    pub sharpe_ratio: f64,
    /// Maximum peak-to-trough drawdown as a fraction (0–1).
    pub max_drawdown: f64,
    /// Fraction of trades that were profitable (0–1).
    pub win_rate: f64,
    /// Total number of completed trades.
    pub total_trades: usize,
    /// List of individual trade records.
    pub trades: Vec<Trade>,
    /// Capital at each bar (length = n_bars + 1, starts with initial_capital).
    pub equity_curve: Vec<f64>,
}

#[pymethods]
impl SimulationResult {
    fn __repr__(&self) -> String {
        format!(
            "SimulationResult(pnl={:.2}, sharpe={:.3}, dd={:.2}%, wr={:.1}%, trades={})",
            self.total_pnl,
            self.sharpe_ratio,
            self.max_drawdown * 100.0,
            self.win_rate * 100.0,
            self.total_trades,
        )
    }
}

// ---------------------------------------------------------------------------
// TickSimulator (legacy v0.1 entry point, fully retained)
// ---------------------------------------------------------------------------

/// Bar-by-bar backtesting simulator written in Rust.
///
/// Executes signals at the *next bar's open* (realistic fill model):
/// a signal at bar i is filled at `open[i+1]` with slippage applied.
///
/// Args:
///     initial_capital: Starting capital in INR (default 100,000).
///     slippage_pct: One-way slippage as a fraction (default 0.001 = 0.1%).
///     commission: Per-trade flat commission in INR (default 20.0).
///     lot_size: Units per trade (default 1.0).
#[pyclass]
pub struct TickSimulator {
    initial_capital: f64,
    slippage_pct: f64,
    commission: f64,
    lot_size: f64,
}

#[pymethods]
impl TickSimulator {
    #[new]
    #[pyo3(signature = (initial_capital=100_000.0, slippage_pct=0.001, commission=20.0, lot_size=1.0))]
    pub fn new(
        initial_capital: f64,
        slippage_pct: f64,
        commission: f64,
        lot_size: f64,
    ) -> Self {
        TickSimulator { initial_capital, slippage_pct, commission, lot_size }
    }

    /// Run a simulation with pre-computed signals.
    ///
    /// Args:
    ///     bars: List of [timestamp, open, high, low, close, volume] sub-lists.
    ///           Each element must have exactly 6 float values.
    ///     signals: List of i8 values aligned with bars:
    ///              1 = enter long (or exit short + enter long),
    ///             -1 = enter short (or exit long + enter short),
    ///              0 = hold current position.
    ///              Signal at index i → fill at open of bar i+1.
    ///
    /// Returns:
    ///     SimulationResult containing P&L, metrics, trade list, equity curve.
    fn run(&self, bars: Vec<[f64; 6]>, signals: Vec<i8>) -> PyResult<SimulationResult> {
        if bars.len() != signals.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "bars ({}) and signals ({}) must have the same length",
                bars.len(),
                signals.len()
            )));
        }
        if bars.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err("bars cannot be empty"));
        }

        let n = bars.len();
        let mut capital = self.initial_capital;
        let mut equity_curve: Vec<f64> = Vec::with_capacity(n + 1);
        equity_curve.push(capital);

        let mut in_trade = false;
        let mut entry_price = 0.0f64;
        let mut entry_time = 0i64;
        let mut direction = 0i8;

        let mut trades: Vec<Trade> = Vec::new();
        let mut trade_returns: Vec<f64> = Vec::new();

        for i in 0..n - 1 {
            let signal = signals[i];
            let next_bar = &bars[i + 1];
            let next_open = next_bar[1];
            let next_time = next_bar[0] as i64;

            if !in_trade && signal != 0 {
                let fill_price = if signal > 0 {
                    next_open * (1.0 + self.slippage_pct)
                } else {
                    next_open * (1.0 - self.slippage_pct)
                };
                capital -= self.commission;
                entry_price = fill_price;
                entry_time = next_time;
                direction = signal;
                in_trade = true;
            } else if in_trade && signal != 0 && signal != direction {
                let exit_price = if direction > 0 {
                    next_open * (1.0 - self.slippage_pct)
                } else {
                    next_open * (1.0 + self.slippage_pct)
                };
                capital -= self.commission;
                let pnl = (exit_price - entry_price) * (direction as f64) * self.lot_size;
                capital += pnl;

                let prev_equity = *equity_curve.last().unwrap_or(&self.initial_capital);
                let ret = if prev_equity > 0.0 { (capital - prev_equity) / prev_equity } else { 0.0 };
                trade_returns.push(ret);

                trades.push(Trade { entry_time, exit_time: next_time, entry_price, exit_price, qty: self.lot_size, pnl, direction });
                in_trade = false;
                direction = 0;
            }
            equity_curve.push(capital);
        }

        if in_trade {
            let last_bar = &bars[n - 1];
            let exit_price = last_bar[4];
            let exit_time = last_bar[0] as i64;
            capital -= self.commission;
            let pnl = (exit_price - entry_price) * (direction as f64) * self.lot_size;
            capital += pnl;

            let prev_equity = *equity_curve.last().unwrap_or(&self.initial_capital);
            let ret = if prev_equity > 0.0 { (capital - prev_equity) / prev_equity } else { 0.0 };
            trade_returns.push(ret);

            trades.push(Trade { entry_time, exit_time, entry_price, exit_price, qty: self.lot_size, pnl, direction });
        }
        equity_curve.push(capital);

        let total_pnl = capital - self.initial_capital;
        let total_trades = trades.len();
        let win_count = trades.iter().filter(|t| t.pnl > 0.0).count();
        let win_rate = if total_trades > 0 { win_count as f64 / total_trades as f64 } else { 0.0 };

        Ok(SimulationResult {
            total_pnl,
            sharpe_ratio: metrics::sharpe_ratio(&trade_returns),
            max_drawdown: metrics::max_drawdown_frac(&equity_curve),
            win_rate,
            total_trades,
            trades,
            equity_curve,
        })
    }

    /// Run a built-in EMA crossover strategy.
    #[pyo3(signature = (bars, fast_period=9, slow_period=21))]
    fn run_ema_crossover(
        &self,
        bars: Vec<[f64; 6]>,
        fast_period: usize,
        slow_period: usize,
    ) -> PyResult<SimulationResult> {
        if fast_period == 0 || slow_period == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "fast_period and slow_period must be > 0",
            ));
        }
        if fast_period >= slow_period {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "fast_period must be less than slow_period",
            ));
        }
        let signals = ema_crossover_signals(&bars, fast_period, slow_period);
        self.run(bars, signals)
    }

    fn __repr__(&self) -> String {
        format!(
            "TickSimulator(capital={:.0}, slippage={:.3}%, commission={:.0}, lot={})",
            self.initial_capital,
            self.slippage_pct * 100.0,
            self.commission,
            self.lot_size,
        )
    }
}

// ---------------------------------------------------------------------------
// Pure Rust helpers
// ---------------------------------------------------------------------------

fn compute_ema(values: &[f64], period: usize) -> Vec<Option<f64>> {
    let mut result = vec![None; values.len()];
    if values.is_empty() || period == 0 || values.len() < period {
        return result;
    }
    let k = 2.0 / (period as f64 + 1.0);
    let seed: f64 = values[..period].iter().sum::<f64>() / period as f64;
    result[period - 1] = Some(seed);
    let mut prev = seed;
    for i in period..values.len() {
        let ema = values[i] * k + prev * (1.0 - k);
        result[i] = Some(ema);
        prev = ema;
    }
    result
}

fn ema_crossover_signals(bars: &[[f64; 6]], fast: usize, slow: usize) -> Vec<i8> {
    let closes: Vec<f64> = bars.iter().map(|b| b[4]).collect();
    let fast_ema = compute_ema(&closes, fast);
    let slow_ema = compute_ema(&closes, slow);
    let n = bars.len();
    let mut signals = vec![0i8; n];
    for i in 1..n {
        match (fast_ema[i], slow_ema[i], fast_ema[i - 1], slow_ema[i - 1]) {
            (Some(f), Some(s), Some(pf), Some(ps)) => {
                if f > s && pf <= ps {
                    signals[i] = 1;
                } else if f < s && pf >= ps {
                    signals[i] = -1;
                }
            }
            _ => {}
        }
    }
    signals
}

// ---------------------------------------------------------------------------
// Monte Carlo Python wrappers
// ---------------------------------------------------------------------------

/// Simulate GBM paths for a single asset.
///
/// Args:
///     historical_returns: List of fractional per-period returns.
///     n_paths: Number of paths.
///     n_steps: Steps per path.
///
/// Returns:
///     List of lists, each inner list is one simulated price path.
#[pyfunction]
#[pyo3(signature = (historical_returns, n_paths, n_steps))]
pub fn simulate(
    historical_returns: Vec<f64>,
    n_paths: usize,
    n_steps: usize,
) -> PyResult<Vec<Vec<f64>>> {
    monte_carlo::simulate(&historical_returns, n_paths, n_steps).map_err(pyo3::PyErr::from)
}

/// Compute confidence-interval terminal values from simulated paths.
///
/// Args:
///     paths: Output from `simulate()`.
///     levels: Quantile levels, e.g. [0.05, 0.50, 0.95].
///
/// Returns:
///     Dict mapping "p{pct}" keys to terminal-value quantiles.
#[pyfunction]
pub fn confidence_intervals(
    paths: Vec<Vec<f64>>,
    levels: Vec<f64>,
) -> std::collections::HashMap<String, f64> {
    monte_carlo::confidence_intervals(&paths, &levels)
}

/// Simulate correlated multi-asset GBM paths using Cholesky decomposition.
///
/// Args:
///     asset_returns: One list per asset of historical fractional returns.
///     correlation_matrix: Flat row-major n×n correlation matrix.
///     n_paths: Number of paths.
///     n_steps: Steps per path.
///
/// Returns:
///     List of length n_assets, each containing n_paths paths of n_steps values.
#[pyfunction]
#[pyo3(signature = (asset_returns, correlation_matrix, n_paths, n_steps))]
pub fn simulate_correlated(
    asset_returns: Vec<Vec<f64>>,
    correlation_matrix: Vec<f64>,
    n_paths: usize,
    n_steps: usize,
) -> PyResult<Vec<Vec<Vec<f64>>>> {
    monte_carlo::simulate_correlated(&asset_returns, &correlation_matrix, n_paths, n_steps)
        .map_err(pyo3::PyErr::from)
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn tick_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // ---- Legacy v0.1 classes (backward compatible) ----
    m.add_class::<Bar>()?;
    m.add_class::<Trade>()?;
    m.add_class::<SimulationResult>()?;
    m.add_class::<TickSimulator>()?;

    // ---- New shared types ----
    m.add_class::<Tick>()?;
    m.add_class::<Signal>()?;
    m.add_class::<BacktestResult>()?;

    // ---- Session tracker ----
    m.add_class::<SessionConfig>()?;
    m.add_class::<SessionState>()?;
    m.add_class::<SessionTracker>()?;

    // ---- Options strategy ----
    m.add_class::<OptionStrategyType>()?;
    m.add_class::<OptionsConfig>()?;
    m.add_class::<OptionsStrategy>()?;
    m.add_class::<Greeks>()?;
    m.add_function(wrap_pyfunction!(black_scholes_greeks, m)?)?;

    // ---- Pairs strategy ----
    m.add_class::<PairsStrategy>()?;

    // ---- Spread / multi-leg strategy ----
    m.add_class::<OptionType>()?;
    m.add_class::<LegConfig>()?;
    m.add_class::<SpreadConfig>()?;
    m.add_class::<SpreadBacktest>()?;

    // Convenience constructors
    m.add_function(wrap_pyfunction!(straddle_config, m)?)?;
    m.add_function(wrap_pyfunction!(strangle_config, m)?)?;
    m.add_function(wrap_pyfunction!(iron_condor_config, m)?)?;

    // Parallel batch functions
    m.add_function(wrap_pyfunction!(run_spreads_batch, m)?)?;
    m.add_function(wrap_pyfunction!(run_batch, m)?)?;

    // ---- Monte Carlo ----
    m.add_function(wrap_pyfunction!(simulate, m)?)?;
    m.add_function(wrap_pyfunction!(confidence_intervals, m)?)?;
    m.add_function(wrap_pyfunction!(simulate_correlated, m)?)?;

    Ok(())
}
