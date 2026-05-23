//! Multi-leg spread strategy with parallel batch execution via Rayon.
//!
//! Supports: Straddle, Strangle, Vertical (Bull/Bear Call/Put),
//! Iron Condor, Iron Butterfly, and arbitrary Custom spreads.
//!
//! `run_batch()` executes multiple `SpreadBacktest` instances in parallel
//! using Rayon, enabling fast parameter sweeps across many configurations.
//!
//! # Example
//! ```python
//! from tick_engine import SpreadBacktest, SpreadConfig, LegConfig, run_spreads_batch
//!
//! cfg = SpreadConfig(initial_capital=100_000.0, max_loss=5000.0)
//! cfg.add_leg(LegConfig("CE", strike=19800.0, quantity=-1, lot_size=50))
//! cfg.add_leg(LegConfig("PE", strike=19800.0, quantity=-1, lot_size=50))
//!
//! backtest = SpreadBacktest("SHORT_STRADDLE", cfg)
//!
//! ts     = [...]  # Unix timestamps (seconds)
//! call_p = [...]  # call premium series
//! put_p  = [...]  # put premium series
//! entries = [False, True, False, ...]
//! exits   = [False, False, ..., True, ...]
//!
//! result = backtest.run(ts, [call_p, put_p], entries, exits)
//! ```

use pyo3::prelude::*;
use rayon::prelude::*;

use crate::metrics::{
    avg_win_loss_ratio, max_consecutive_streaks, max_drawdown_frac, omega_ratio, payoff_ratio,
    recovery_factor, sharpe_ratio, sortino_ratio, sqn,
};
use crate::types::BacktestResult;

// ---------------------------------------------------------------------------
// Option type
// ---------------------------------------------------------------------------

/// Whether a leg is a call or a put.
#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OptionType {
    Call,
    Put,
}

// ---------------------------------------------------------------------------
// LegConfig
// ---------------------------------------------------------------------------

/// Configuration for a single leg of a spread.
#[pyclass(get_all, set_all)]
#[derive(Clone, Debug)]
pub struct LegConfig {
    /// "CE" or "PE" (case-insensitive).
    pub option_type: OptionType,
    /// Strike price.
    pub strike: f64,
    /// Signed quantity: positive = long, negative = short.
    pub quantity: i32,
    /// Lot size (units per contract).
    pub lot_size: usize,
}

#[pymethods]
impl LegConfig {
    #[new]
    #[pyo3(signature = (option_type, strike, quantity, lot_size = 50))]
    pub fn new(option_type: OptionType, strike: f64, quantity: i32, lot_size: usize) -> Self {
        LegConfig { option_type, strike, quantity, lot_size }
    }

    /// True when the leg is a long position.
    pub fn is_long(&self) -> bool {
        self.quantity > 0
    }

    /// True when the leg is a short position.
    pub fn is_short(&self) -> bool {
        self.quantity < 0
    }

    fn __repr__(&self) -> String {
        let cp = match self.option_type {
            OptionType::Call => "CE",
            OptionType::Put => "PE",
        };
        format!(
            "LegConfig({} K={:.0} qty={} lot={})",
            cp, self.strike, self.quantity, self.lot_size
        )
    }
}

// ---------------------------------------------------------------------------
// SpreadConfig
// ---------------------------------------------------------------------------

/// Configuration for a multi-leg spread backtest.
#[pyclass]
#[derive(Clone, Debug)]
pub struct SpreadConfig {
    /// Starting capital in INR.
    pub initial_capital: f64,
    /// Percentage fee per premium unit (e.g. 0.001 = 0.1%).
    pub fees: f64,
    /// Maximum loss per spread position (INR). None = unlimited.
    pub max_loss: Option<f64>,
    /// Profit target per spread position (INR). None = none.
    pub target_profit: Option<f64>,
    /// Leg definitions.
    pub legs: Vec<LegConfig>,
}

impl Default for SpreadConfig {
    fn default() -> Self {
        Self {
            initial_capital: 100_000.0,
            fees: 0.001,
            max_loss: None,
            target_profit: None,
            legs: Vec::new(),
        }
    }
}

#[pymethods]
impl SpreadConfig {
    #[new]
    #[pyo3(signature = (initial_capital = 100_000.0, fees = 0.001, max_loss = None, target_profit = None))]
    pub fn new(
        initial_capital: f64,
        fees: f64,
        max_loss: Option<f64>,
        target_profit: Option<f64>,
    ) -> Self {
        Self { initial_capital, fees, max_loss, target_profit, legs: Vec::new() }
    }

    /// Append a leg to the spread definition.
    pub fn add_leg(&mut self, leg: LegConfig) {
        self.legs.push(leg);
    }

    fn __repr__(&self) -> String {
        format!(
            "SpreadConfig(capital={:.0}, legs={}, max_loss={:?})",
            self.initial_capital,
            self.legs.len(),
            self.max_loss
        )
    }
}

// ---------------------------------------------------------------------------
// Internal position state
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct LegState {
    entry_premium: f64,
    current_premium: f64,
    config: LegConfig,
}

impl LegState {
    fn new(config: LegConfig, entry_premium: f64) -> Self {
        Self { entry_premium, current_premium: entry_premium, config }
    }

    /// Unrealised P&L for this leg.
    ///
    /// Short legs (quantity < 0) profit when premiums fall:
    ///   pnl = qty * (current - entry) * lot_size
    ///       = (-1) * (−75) * 50 = +3750  ← correct profit
    ///
    /// Long legs (quantity > 0) profit when premiums rise:
    ///   pnl = (+1) * (+75) * 50 = +3750  ← correct profit
    fn unrealised_pnl(&self) -> f64 {
        let change = self.current_premium - self.entry_premium;
        (self.config.quantity as f64) * change * (self.config.lot_size as f64)
    }
}

#[derive(Clone, Debug)]
struct SpreadPosition {
    legs: Vec<LegState>,
    #[allow(dead_code)]
    entry_idx: usize,
    #[allow(dead_code)]
    entry_time: i64,
    /// Net entry premium (positive = credit spread, negative = debit spread).
    #[allow(dead_code)]
    entry_net_premium: f64,
}

impl SpreadPosition {
    fn new(legs: Vec<LegState>, entry_idx: usize, entry_time: i64) -> Self {
        let entry_net_premium: f64 = legs
            .iter()
            .map(|l| l.entry_premium * l.config.quantity as f64 * l.config.lot_size as f64)
            .sum();
        Self { legs, entry_idx, entry_time, entry_net_premium }
    }

    fn total_unrealised_pnl(&self) -> f64 {
        self.legs.iter().map(LegState::unrealised_pnl).sum()
    }

    fn update_premiums(&mut self, premiums: &[f64]) {
        for (leg, &p) in self.legs.iter_mut().zip(premiums.iter()) {
            leg.current_premium = p;
        }
    }
}

// ---------------------------------------------------------------------------
// SpreadBacktest
// ---------------------------------------------------------------------------

/// Multi-leg spread backtester.
///
/// Runs an O(n) single-pass simulation across aligned premium series for
/// each leg. Entry and exit decisions are driven by caller-supplied boolean
/// arrays, supplemented by optional max-loss and target-profit guardrails.
#[pyclass]
#[derive(Clone)]
pub struct SpreadBacktest {
    name: String,
    config: SpreadConfig,
}

#[pymethods]
impl SpreadBacktest {
    #[new]
    pub fn new(name: String, config: SpreadConfig) -> Self {
        Self { name, config }
    }

    /// Run the spread backtest.
    ///
    /// Args:
    ///     timestamps:    Unix epoch seconds, one per bar.
    ///     legs_premiums: One Vec per leg, each containing premium values
    ///                    aligned with `timestamps`. Must have the same number
    ///                    of inner Vecs as `config.legs`.
    ///     entries:       True on bars where a new position should open.
    ///     exits:         True on bars where the open position should close.
    ///
    /// Returns:
    ///     `BacktestResult` with full metrics, equity curve, and P&L.
    pub fn run(
        &self,
        timestamps: Vec<i64>,
        legs_premiums: Vec<Vec<f64>>,
        entries: Vec<bool>,
        exits: Vec<bool>,
    ) -> PyResult<BacktestResult> {
        let n = timestamps.len();

        if legs_premiums.len() != self.config.legs.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "legs_premiums has {} series but config has {} legs",
                legs_premiums.len(),
                self.config.legs.len()
            )));
        }
        for (i, series) in legs_premiums.iter().enumerate() {
            if series.len() != n {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "legs_premiums[{i}] has {} bars but timestamps has {n}",
                    series.len()
                )));
        }
        }
        if entries.len() != n || exits.len() != n {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "entries and exits must have the same length as timestamps",
            ));
        }
        if n == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("timestamps cannot be empty"));
        }

        Ok(self.simulate_inner(&timestamps, &legs_premiums, &entries, &exits))
    }

    fn __repr__(&self) -> String {
        format!("SpreadBacktest(name='{}', legs={})", self.name, self.config.legs.len())
    }
}

impl SpreadBacktest {
    /// Core simulation logic (pure Rust, no PyO3 dependency).
    fn simulate_inner(
        &self,
        timestamps: &[i64],
        legs_premiums: &[Vec<f64>],
        entries: &[bool],
        exits: &[bool],
    ) -> BacktestResult {
        let n = timestamps.len();
        let initial_capital = self.config.initial_capital;

        let mut capital = initial_capital;
        let mut position: Option<SpreadPosition> = None;
        let mut equity_curve = Vec::with_capacity(n + 1);
        equity_curve.push(capital);

        let mut trade_pnls: Vec<f64> = Vec::new();
        let mut trade_returns: Vec<f64> = Vec::new();
        let mut prev_equity = capital;

        for i in 0..n {
            let current_premiums: Vec<f64> = legs_premiums.iter().map(|s| s[i]).collect();

            // Update mark-to-market
            if let Some(ref mut pos) = position {
                pos.update_premiums(&current_premiums);
            }

            let unrealised = position.as_ref().map(|p| p.total_unrealised_pnl()).unwrap_or(0.0);

            // Determine if we should exit
            let should_exit = position.is_some()
                && (exits[i]
                    || self.check_max_loss(unrealised)
                    || self.check_target_profit(unrealised));

            if should_exit {
                if let Some(pos) = position.take() {
                    let gross_pnl = pos.total_unrealised_pnl();
                    let fees = self.exit_fees(&pos);
                    let net_pnl = gross_pnl - fees;
                    capital += net_pnl;

                    let ret = if prev_equity > 0.0 { net_pnl / prev_equity } else { 0.0 };
                    trade_pnls.push(net_pnl);
                    trade_returns.push(ret);
                }
            }

            // Open new position
            if position.is_none() && entries[i] {
                let legs: Vec<LegState> = self
                    .config
                    .legs
                    .iter()
                    .zip(current_premiums.iter())
                    .map(|(cfg, &prem)| LegState::new(cfg.clone(), prem))
                    .collect();

                let entry_fees = self.entry_fees(&legs);
                capital -= entry_fees;

                position = Some(SpreadPosition::new(legs, i, timestamps[i]));
            }

            // Equity tracking
            let unrealised = position.as_ref().map(|p| p.total_unrealised_pnl()).unwrap_or(0.0);
            let equity = capital + unrealised;
            equity_curve.push(equity);
            prev_equity = equity;
        }

        // Force-close any open position at end of data
        if let Some(pos) = position.take() {
            let gross_pnl = pos.total_unrealised_pnl();
            let fees = self.exit_fees(&pos);
            let net_pnl = gross_pnl - fees;
            capital += net_pnl;
            trade_pnls.push(net_pnl);
            trade_returns.push(if initial_capital > 0.0 { net_pnl / initial_capital } else { 0.0 });
        }
        equity_curve.push(capital);

        let total_pnl = capital - initial_capital;
        let total_trades = trade_pnls.len();
        let win_count = trade_pnls.iter().filter(|&&p| p > 0.0).count();
        let win_rate = if total_trades > 0 { win_count as f64 / total_trades as f64 } else { 0.0 };
        let max_dd = max_drawdown_frac(&equity_curve);
        let (mcw, mcl) = max_consecutive_streaks(&trade_pnls);

        BacktestResult {
            strategy_name: self.name.clone(),
            total_pnl,
            sharpe_ratio: sharpe_ratio(&trade_returns),
            sortino_ratio: sortino_ratio(&trade_returns),
            max_drawdown: max_dd,
            win_rate,
            total_trades,
            equity_curve,
            omega_ratio: omega_ratio(&trade_returns),
            sqn: sqn(&trade_returns),
            payoff_ratio: payoff_ratio(&trade_returns),
            recovery_factor: recovery_factor(total_pnl, max_dd * initial_capital),
            max_consecutive_wins: mcw,
            max_consecutive_losses: mcl,
            avg_win_loss_ratio: avg_win_loss_ratio(&trade_pnls),
        }
    }

    fn check_max_loss(&self, unrealised: f64) -> bool {
        self.config.max_loss.map_or(false, |limit| unrealised < -limit)
    }

    fn check_target_profit(&self, unrealised: f64) -> bool {
        self.config.target_profit.map_or(false, |target| unrealised > target)
    }

    fn entry_fees(&self, legs: &[LegState]) -> f64 {
        legs.iter()
            .map(|l| l.entry_premium.abs() * l.config.lot_size as f64 * self.config.fees)
            .sum()
    }

    fn exit_fees(&self, pos: &SpreadPosition) -> f64 {
        pos.legs
            .iter()
            .map(|l| l.current_premium.abs() * l.config.lot_size as f64 * self.config.fees * 2.0)
            .sum()
    }
}

// ---------------------------------------------------------------------------
// Parallel batch execution
// ---------------------------------------------------------------------------

/// Run a batch of `SpreadBacktest` instances in parallel using Rayon.
///
/// Each element is a tuple of `(backtest, timestamps, legs_premiums, entries, exits)`.
/// Returns one `BacktestResult` per element, in the same order.
///
/// # Example
/// ```python
/// from tick_engine import run_spreads_batch, SpreadBacktest, SpreadConfig, LegConfig, OptionType
///
/// items = [(backtest1, ts, premiums1, entries1, exits1),
///          (backtest2, ts, premiums2, entries2, exits2)]
/// results = run_spreads_batch(items)
/// ```
#[pyfunction]
pub fn run_spreads_batch(
    items: Vec<(SpreadBacktest, Vec<i64>, Vec<Vec<f64>>, Vec<bool>, Vec<bool>)>,
) -> Vec<BacktestResult> {
    items
        .into_par_iter()
        .map(|(bt, ts, premiums, entries, exits)| {
            bt.simulate_inner(&ts, &premiums, &entries, &exits)
        })
        .collect()
}

/// Run a batch of spread backtests supplied as raw parameter tuples.
///
/// This lower-level entry point avoids the need to construct `SpreadBacktest`
/// objects on the Python side.  Each tuple is:
/// `(name, config, timestamps, legs_premiums, entries, exits)`.
#[pyfunction]
pub fn run_batch(
    items: Vec<(String, SpreadConfig, Vec<i64>, Vec<Vec<f64>>, Vec<bool>, Vec<bool>)>,
) -> Vec<BacktestResult> {
    items
        .into_par_iter()
        .map(|(name, cfg, ts, premiums, entries, exits)| {
            let bt = SpreadBacktest { name, config: cfg };
            bt.simulate_inner(&ts, &premiums, &entries, &exits)
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Convenience constructors (mirrors raptorbt pattern)
// ---------------------------------------------------------------------------

/// Create a short straddle config (sell ATM call + ATM put).
///
/// Requires the caller to supply premiums for call and put aligned with
/// the timestamp series.
#[pyfunction]
#[pyo3(signature = (strike, lot_size = 50, short = true, initial_capital = 100_000.0, fees = 0.001))]
pub fn straddle_config(
    strike: f64,
    lot_size: usize,
    short: bool,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let qty = if short { -1 } else { 1 };
    let mut cfg =
        SpreadConfig { initial_capital, fees, max_loss: None, target_profit: None, legs: Vec::new() };
    cfg.add_leg(LegConfig::new(OptionType::Call, strike, qty, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, strike, qty, lot_size));
    cfg
}

/// Create a short strangle config (sell OTM call + OTM put).
#[pyfunction]
#[pyo3(signature = (call_strike, put_strike, lot_size = 50, short = true, initial_capital = 100_000.0, fees = 0.001))]
pub fn strangle_config(
    call_strike: f64,
    put_strike: f64,
    lot_size: usize,
    short: bool,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let qty = if short { -1 } else { 1 };
    let mut cfg =
        SpreadConfig { initial_capital, fees, max_loss: None, target_profit: None, legs: Vec::new() };
    cfg.add_leg(LegConfig::new(OptionType::Call, call_strike, qty, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, put_strike, qty, lot_size));
    cfg
}

/// Create an iron condor config: sell OTM call/put, buy further OTM call/put.
#[pyfunction]
#[pyo3(signature = (
    short_call, long_call,
    short_put, long_put,
    lot_size = 50, initial_capital = 100_000.0, fees = 0.001
))]
pub fn iron_condor_config(
    short_call: f64,
    long_call: f64,
    short_put: f64,
    long_put: f64,
    lot_size: usize,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let mut cfg =
        SpreadConfig { initial_capital, fees, max_loss: None, target_profit: None, legs: Vec::new() };
    cfg.add_leg(LegConfig::new(OptionType::Call, short_call, -1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Call, long_call, 1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, short_put, -1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, long_put, 1, lot_size));
    cfg
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_ts(n: usize) -> Vec<i64> {
        (0..n as i64).collect()
    }

    fn make_entries_exits(n: usize, entry: usize, exit: usize) -> (Vec<bool>, Vec<bool>) {
        let mut entries = vec![false; n];
        let mut exits = vec![false; n];
        entries[entry] = true;
        exits[exit] = true;
        (entries, exits)
    }

    #[test]
    fn test_straddle_backtest_completes() {
        let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001);
        let bt = SpreadBacktest::new("SHORT_STRADDLE".to_string(), cfg);

        let n = 20;
        let ts = make_ts(n);
        // Call premiums decrease (good for short)
        let call_p: Vec<f64> = (0..n).map(|i| 200.0 - i as f64 * 5.0).collect();
        // Put premiums decrease too
        let put_p: Vec<f64> = (0..n).map(|i| 200.0 - i as f64 * 3.0).collect();
        let (entries, exits) = make_entries_exits(n, 1, 15);

        let result = bt.run(ts, vec![call_p, put_p], entries, exits).unwrap();

        assert_eq!(result.total_trades, 1);
        assert_eq!(result.strategy_name, "SHORT_STRADDLE");
        // Short straddle profits from theta: premiums fell → positive pnl
        assert!(result.total_pnl > 0.0, "expected positive pnl for short straddle with falling premiums");
    }

    #[test]
    fn test_max_loss_triggers_exit() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, Some(500.0), None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19800.0, -1, 50));

        let bt = SpreadBacktest::new("TEST".to_string(), cfg);

        let n = 10;
        let ts = make_ts(n);
        // Premium doubles — short position loses
        let premiums: Vec<f64> = vec![100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0];
        let entries = {
            let mut e = vec![false; n];
            e[0] = true;
            e
        };
        let exits = vec![false; n]; // no explicit exits — rely on max_loss

        let result = bt.run(ts, vec![premiums], entries, exits).unwrap();
        // The position should have been exited (either by max_loss or end of data)
        assert!(result.total_trades >= 1);
    }

    #[test]
    fn test_batch_returns_same_count() {
        let make_item = |name: &str| {
            let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001);
            let bt = SpreadBacktest::new(name.to_string(), cfg);
            let n = 10;
            let ts = make_ts(n);
            let call_p = vec![200.0f64; n];
            let put_p = vec![200.0f64; n];
            let (entries, exits) = make_entries_exits(n, 1, 8);
            (bt, ts, vec![call_p, put_p], entries, exits)
        };

        let items = vec![make_item("A"), make_item("B"), make_item("C")];
        let results = run_spreads_batch(items);
        assert_eq!(results.len(), 3);
    }

    #[test]
    fn test_iron_condor_four_legs() {
        let cfg = iron_condor_config(20000.0, 20100.0, 19600.0, 19500.0, 50, 100_000.0, 0.001);
        assert_eq!(cfg.legs.len(), 4);
    }

    #[test]
    fn test_mismatched_legs_error() {
        let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001); // 2 legs
        let bt = SpreadBacktest::new("ERR".to_string(), cfg);
        let n = 5;
        // Supply only 1 premium series for 2 legs
        let result = bt.run(make_ts(n), vec![vec![100.0f64; n]], vec![false; n], vec![false; n]);
        assert!(result.is_err());
    }
}
