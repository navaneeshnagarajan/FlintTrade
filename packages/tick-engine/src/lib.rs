//! FlintTrade tick-engine — high-performance tick-level backtesting simulator.
//!
//! Exposed to Python via PyO3. Simulates order execution bar-by-bar with
//! configurable slippage, commission, and lot size. Includes a built-in
//! EMA crossover strategy for quick experimentation.
//!
//! # Example (Python)
//! ```python
//! from tick_engine import TickSimulator
//!
//! sim = TickSimulator(initial_capital=100_000, slippage_pct=0.001, commission=20.0)
//! bars = [[t, o, h, l, c, v], ...]   # [timestamp, open, high, low, close, volume]
//! result = sim.run_ema_crossover(bars, fast_period=9, slow_period=21)
//! print(result)
//! ```

use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// Data types
// ---------------------------------------------------------------------------

/// A single OHLCV bar.
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
        format!(
            "Trade({} entry={:.2} exit={:.2} pnl={:.2})",
            dir, self.entry_price, self.exit_price, self.pnl
        )
    }
}

/// Full simulation output.
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
// TickSimulator
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

        // Position state
        let mut in_trade = false;
        let mut entry_price = 0.0f64;
        let mut entry_time = 0i64;
        let mut direction = 0i8;

        let mut trades: Vec<Trade> = Vec::new();
        let mut trade_returns: Vec<f64> = Vec::new();

        for i in 0..n - 1 {
            let signal = signals[i];
            let next_bar = &bars[i + 1];
            let next_open = next_bar[1]; // open
            let next_time = next_bar[0] as i64; // timestamp

            if !in_trade && signal != 0 {
                // Enter new position (long for +1, short for -1)
                let fill_price = if signal > 0 {
                    next_open * (1.0 + self.slippage_pct) // buy at ask
                } else {
                    next_open * (1.0 - self.slippage_pct) // sell at bid
                };
                capital -= self.commission;
                entry_price = fill_price;
                entry_time = next_time;
                direction = signal;
                in_trade = true;
            } else if in_trade && signal != 0 && signal != direction {
                // Close the current position (opposite signal = exit only, no reversal)
                let exit_price = if direction > 0 {
                    next_open * (1.0 - self.slippage_pct) // long exit: sell at bid
                } else {
                    next_open * (1.0 + self.slippage_pct) // short exit: buy at ask
                };
                capital -= self.commission;
                let pnl = (exit_price - entry_price) * (direction as f64) * self.lot_size;
                capital += pnl;

                let prev_equity = *equity_curve.last().unwrap_or(&self.initial_capital);
                let ret = if prev_equity > 0.0 {
                    (capital - prev_equity) / prev_equity
                } else {
                    0.0
                };
                trade_returns.push(ret);

                trades.push(Trade {
                    entry_time,
                    exit_time: next_time,
                    entry_price,
                    exit_price,
                    qty: self.lot_size,
                    pnl,
                    direction,
                });
                in_trade = false;
                direction = 0;
            }
            equity_curve.push(capital);
        }

        // Force-close open position at last bar's close
        if in_trade {
            let last_bar = &bars[n - 1];
            let exit_price = last_bar[4]; // close
            let exit_time = last_bar[0] as i64;
            capital -= self.commission;
            let pnl = (exit_price - entry_price) * (direction as f64) * self.lot_size;
            capital += pnl;

            let prev_equity = *equity_curve.last().unwrap_or(&self.initial_capital);
            let ret = if prev_equity > 0.0 {
                (capital - prev_equity) / prev_equity
            } else {
                0.0
            };
            trade_returns.push(ret);

            trades.push(Trade {
                entry_time,
                exit_time,
                entry_price,
                exit_price,
                qty: self.lot_size,
                pnl,
                direction,
            });
        }
        equity_curve.push(capital);

        // Compute aggregate metrics
        let total_pnl = capital - self.initial_capital;
        let total_trades = trades.len();
        let win_count = trades.iter().filter(|t| t.pnl > 0.0).count();
        let win_rate = if total_trades > 0 {
            win_count as f64 / total_trades as f64
        } else {
            0.0
        };
        let sharpe_ratio = compute_sharpe(&trade_returns);
        let max_drawdown = compute_max_drawdown(&equity_curve);

        Ok(SimulationResult {
            total_pnl,
            sharpe_ratio,
            max_drawdown,
            win_rate,
            total_trades,
            trades,
            equity_curve,
        })
    }

    /// Run a built-in EMA crossover strategy.
    ///
    /// Generates signals when fast EMA crosses slow EMA:
    ///   fast > slow (golden cross) → BUY signal
    ///   fast < slow (death cross)  → SELL signal
    ///
    /// Args:
    ///     bars: List of [timestamp, open, high, low, close, volume] sub-lists.
    ///     fast_period: Fast EMA period (default 9).
    ///     slow_period: Slow EMA period (default 21).
    ///
    /// Returns:
    ///     SimulationResult from executing the EMA crossover signals.
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
// Pure Rust helpers (not exposed to Python)
// ---------------------------------------------------------------------------

/// Compute EMA series. Returns None for insufficient data.
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

/// Generate EMA crossover signals for a bar slice.
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
                    signals[i] = 1; // golden cross
                } else if f < s && pf >= ps {
                    signals[i] = -1; // death cross
                }
            }
            _ => {}
        }
    }
    signals
}

/// Annualised Sharpe ratio (252-day basis) from per-trade returns.
fn compute_sharpe(returns: &[f64]) -> f64 {
    if returns.len() < 2 {
        return 0.0;
    }
    let n = returns.len() as f64;
    let mean = returns.iter().sum::<f64>() / n;
    let variance = returns.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / (n - 1.0);
    let std_dev = variance.sqrt();
    if std_dev < 1e-10 {
        return 0.0;
    }
    mean / std_dev * (252.0_f64).sqrt()
}

/// Maximum peak-to-trough drawdown as a fraction (0.0–1.0).
fn compute_max_drawdown(equity: &[f64]) -> f64 {
    if equity.is_empty() {
        return 0.0;
    }
    let mut peak = equity[0];
    let mut max_dd = 0.0f64;
    for &e in equity {
        if e > peak {
            peak = e;
        }
        if peak > 0.0 {
            let dd = (peak - e) / peak;
            if dd > max_dd {
                max_dd = dd;
            }
        }
    }
    max_dd
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

#[pymodule]
fn tick_engine(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Bar>()?;
    m.add_class::<Trade>()?;
    m.add_class::<SimulationResult>()?;
    m.add_class::<TickSimulator>()?;
    Ok(())
}
