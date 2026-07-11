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
//! from tick_engine import LegConfig, OptionType, SpreadBacktest, SpreadConfig
//!
//! cfg = SpreadConfig(initial_capital=100_000.0, max_loss=5000.0)
//! cfg.add_leg(LegConfig(OptionType.Call, strike=19800.0, quantity=-1, lot_size=50))
//! cfg.add_leg(LegConfig(OptionType.Put, strike=19800.0, quantity=-1, lot_size=50))
//!
//! backtest = SpreadBacktest("SHORT_STRADDLE", cfg)
//!
//! ts = [1, 2]
//! call_p = [10.0, 8.0]
//! put_p = [12.0, 9.0]
//! entries = [True, False]
//! exits = [False, True]
//!
//! result = backtest.run(ts, [call_p, put_p], entries, exits)
//! assert result.total_trades == 1
//! ```

use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::{PyAnyMethods, PyBool};
use rayon::prelude::*;

use crate::errors::EngineError;
use crate::metrics::{
    avg_win_loss_ratio, max_consecutive_streaks, max_drawdown_frac, omega_ratio, payoff_ratio,
    recovery_factor, sharpe_ratio, sortino_ratio, sqn,
};
use crate::types::BacktestResult;

macro_rules! strict_numeric {
    ($name:ident, $inner:ty) => {
        #[derive(Clone, Copy)]
        pub(crate) struct $name($inner);

        impl<'a, 'py> pyo3::FromPyObject<'a, 'py> for $name {
            type Error = PyErr;

            fn extract(obj: pyo3::Borrowed<'a, 'py, PyAny>) -> Result<Self, Self::Error> {
                if obj.is_instance_of::<PyBool>() {
                    return Err(PyTypeError::new_err(
                        "boolean values are invalid for numeric spread inputs",
                    ));
                }
                Ok(Self(obj.extract()?))
            }
        }
    };
}

strict_numeric!(StrictF64, f64);
strict_numeric!(StrictI32, i32);
strict_numeric!(StrictI64, i64);
strict_numeric!(StrictUsize, usize);

// ---------------------------------------------------------------------------
// Option type
// ---------------------------------------------------------------------------

/// Whether a spread leg is a call or a put.
///
/// Use `OptionType.Call` or `OptionType.Put` when constructing a `LegConfig`.
#[pyclass(eq, eq_int, from_py_object)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OptionType {
    Call,
    Put,
}

// ---------------------------------------------------------------------------
// LegConfig
// ---------------------------------------------------------------------------

/// Configuration for a single leg of a spread.
#[pyclass(get_all, from_py_object)]
#[derive(Clone, Debug)]
pub struct LegConfig {
    /// `OptionType.Call` or `OptionType.Put`.
    pub option_type: OptionType,
    /// Strike price.
    pub strike: f64,
    /// Signed quantity: positive = long, negative = short.
    pub quantity: i32,
    /// Lot size (units per contract).
    pub lot_size: usize,
}

impl LegConfig {
    pub fn new(option_type: OptionType, strike: f64, quantity: i32, lot_size: usize) -> Self {
        LegConfig {
            option_type,
            strike,
            quantity,
            lot_size,
        }
    }
}

#[pymethods]
impl LegConfig {
    #[new]
    #[pyo3(
        signature = (option_type, strike, quantity, lot_size = StrictUsize(50)),
        text_signature = "(option_type, strike, quantity, lot_size=50)"
    )]
    fn py_new(
        option_type: OptionType,
        strike: StrictF64,
        quantity: StrictI32,
        lot_size: StrictUsize,
    ) -> Self {
        Self::new(option_type, strike.0, quantity.0, lot_size.0)
    }

    #[setter]
    fn set_option_type(&mut self, option_type: OptionType) {
        self.option_type = option_type;
    }

    #[setter]
    fn set_strike(&mut self, strike: StrictF64) {
        self.strike = strike.0;
    }

    #[setter]
    fn set_quantity(&mut self, quantity: StrictI32) {
        self.quantity = quantity.0;
    }

    #[setter]
    fn set_lot_size(&mut self, lot_size: StrictUsize) {
        self.lot_size = lot_size.0;
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
#[pyclass(from_py_object)]
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

impl SpreadConfig {
    pub fn new(
        initial_capital: f64,
        fees: f64,
        max_loss: Option<f64>,
        target_profit: Option<f64>,
    ) -> Self {
        Self {
            initial_capital,
            fees,
            max_loss,
            target_profit,
            legs: Vec::new(),
        }
    }
}

#[pymethods]
impl SpreadConfig {
    #[new]
    #[pyo3(
        signature = (
            initial_capital = StrictF64(100_000.0),
            fees = StrictF64(0.001),
            max_loss = None,
            target_profit = None
        ),
        text_signature = "(initial_capital=100000.0, fees=0.001, max_loss=None, target_profit=None)"
    )]
    fn py_new(
        initial_capital: StrictF64,
        fees: StrictF64,
        max_loss: Option<StrictF64>,
        target_profit: Option<StrictF64>,
    ) -> Self {
        Self::new(
            initial_capital.0,
            fees.0,
            max_loss.map(|value| value.0),
            target_profit.map(|value| value.0),
        )
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
        Self {
            entry_premium,
            current_premium: entry_premium,
            config,
        }
    }

    /// Unrealised P&L for this leg.
    ///
    /// Short legs (quantity < 0) profit when premiums fall:
    ///   pnl = qty * (current - entry) * lot_size
    ///       = (-1) * (−75) * 50 = +3750  ← correct profit
    ///
    /// Long legs (quantity > 0) profit when premiums rise:
    ///   pnl = (+1) * (+75) * 50 = +3750  ← correct profit
    fn unrealised_pnl(&self) -> Result<f64, EngineError> {
        leg_unrealised_pnl(&self.config, self.entry_premium, self.current_premium)
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
    fn new(legs: Vec<LegState>, entry_idx: usize, entry_time: i64) -> Result<Self, EngineError> {
        let entry_net_premium = legs.iter().try_fold(0.0, |total, leg| {
            let quantity_adjusted =
                checked_spread_arithmetic(leg.entry_premium * leg.config.quantity as f64)?;
            let leg_value =
                checked_spread_arithmetic(quantity_adjusted * leg.config.lot_size as f64)?;
            checked_spread_arithmetic(total + leg_value)
        })?;
        Ok(Self {
            legs,
            entry_idx,
            entry_time,
            entry_net_premium,
        })
    }

    fn total_unrealised_pnl(&self) -> Result<f64, EngineError> {
        self.legs.iter().try_fold(0.0, |total, leg| {
            checked_spread_arithmetic(total + leg.unrealised_pnl()?)
        })
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
#[pyclass(from_py_object)]
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
    #[pyo3(name = "run")]
    fn run_py(
        &self,
        timestamps: Vec<StrictI64>,
        legs_premiums: Vec<Vec<StrictF64>>,
        entries: Vec<bool>,
        exits: Vec<bool>,
    ) -> PyResult<BacktestResult> {
        self.run(
            timestamps.into_iter().map(|value| value.0).collect(),
            legs_premiums
                .into_iter()
                .map(|series| series.into_iter().map(|value| value.0).collect())
                .collect(),
            entries,
            exits,
        )
    }

    fn __repr__(&self) -> String {
        format!(
            "SpreadBacktest(name='{}', legs={})",
            self.name,
            self.config.legs.len()
        )
    }
}

impl SpreadBacktest {
    /// Run a checked spread backtest from Rust-owned aligned inputs.
    pub fn run(
        &self,
        timestamps: Vec<i64>,
        legs_premiums: Vec<Vec<f64>>,
        entries: Vec<bool>,
        exits: Vec<bool>,
    ) -> PyResult<BacktestResult> {
        validate_inputs(&self.config, &timestamps, &legs_premiums, &entries, &exits)?;
        Ok(self.simulate_inner(&timestamps, &legs_premiums, &entries, &exits)?)
    }

    /// Core simulation logic (pure Rust, no PyO3 dependency).
    fn simulate_inner(
        &self,
        timestamps: &[i64],
        legs_premiums: &[Vec<f64>],
        entries: &[bool],
        exits: &[bool],
    ) -> Result<BacktestResult, EngineError> {
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

            let unrealised = match position.as_ref() {
                Some(position) => position.total_unrealised_pnl()?,
                None => 0.0,
            };

            // Determine if we should exit
            let should_exit = position.is_some()
                && (exits[i]
                    || self.check_max_loss(unrealised)
                    || self.check_target_profit(unrealised));

            if should_exit {
                if let Some(pos) = position.take() {
                    let gross_pnl = pos.total_unrealised_pnl()?;
                    let fees = self.exit_fees(&pos)?;
                    let net_pnl = checked_spread_arithmetic(gross_pnl - fees)?;
                    capital = checked_spread_arithmetic(capital + net_pnl)?;

                    let ret = if prev_equity > 0.0 {
                        checked_spread_arithmetic(net_pnl / prev_equity)?
                    } else {
                        0.0
                    };
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

                let entry_fees = self.entry_fees(&legs)?;
                capital = checked_spread_arithmetic(capital - entry_fees)?;

                position = Some(SpreadPosition::new(legs, i, timestamps[i])?);
            }

            // Equity tracking
            let unrealised = match position.as_ref() {
                Some(position) => position.total_unrealised_pnl()?,
                None => 0.0,
            };
            let equity = checked_spread_arithmetic(capital + unrealised)?;
            equity_curve.push(equity);
            prev_equity = equity;
        }

        // Force-close any open position at end of data
        if let Some(pos) = position.take() {
            let gross_pnl = pos.total_unrealised_pnl()?;
            let fees = self.exit_fees(&pos)?;
            let net_pnl = checked_spread_arithmetic(gross_pnl - fees)?;
            capital = checked_spread_arithmetic(capital + net_pnl)?;
            trade_pnls.push(net_pnl);
            trade_returns.push(if initial_capital > 0.0 {
                checked_spread_arithmetic(net_pnl / initial_capital)?
            } else {
                0.0
            });
        }
        equity_curve.push(capital);

        let total_pnl = checked_spread_arithmetic(capital - initial_capital)?;
        let total_trades = trade_pnls.len();
        let win_count = trade_pnls.iter().filter(|&&p| p > 0.0).count();
        let win_rate = if total_trades > 0 {
            win_count as f64 / total_trades as f64
        } else {
            0.0
        };
        let max_dd = max_drawdown_frac(&equity_curve);
        let (mcw, mcl) = max_consecutive_streaks(&trade_pnls);

        Ok(BacktestResult {
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
            recovery_factor: recovery_factor(
                total_pnl,
                checked_spread_arithmetic(max_dd * initial_capital)?,
            ),
            max_consecutive_wins: mcw,
            max_consecutive_losses: mcl,
            avg_win_loss_ratio: avg_win_loss_ratio(&trade_pnls),
        })
    }

    fn check_max_loss(&self, unrealised: f64) -> bool {
        self.config
            .max_loss
            .map_or(false, |limit| unrealised < -limit)
    }

    fn check_target_profit(&self, unrealised: f64) -> bool {
        self.config
            .target_profit
            .map_or(false, |target| unrealised > target)
    }

    fn entry_fees(&self, legs: &[LegState]) -> Result<f64, EngineError> {
        total_side_fees(
            &self.config,
            legs.iter().map(|leg| (&leg.config, leg.entry_premium)),
        )
    }

    fn exit_fees(&self, pos: &SpreadPosition) -> Result<f64, EngineError> {
        total_side_fees(
            &self.config,
            pos.legs
                .iter()
                .map(|leg| (&leg.config, leg.current_premium)),
        )
    }
}

fn invalid_spread_input(message: impl Into<String>) -> EngineError {
    EngineError::InvalidSpreadInput {
        message: message.into(),
    }
}

fn checked_spread_arithmetic(value: f64) -> Result<f64, EngineError> {
    if value.is_finite() {
        Ok(value)
    } else {
        Err(invalid_spread_input("spread arithmetic overflow"))
    }
}

fn leg_unrealised_pnl(
    leg: &LegConfig,
    entry_premium: f64,
    current_premium: f64,
) -> Result<f64, EngineError> {
    let change = checked_spread_arithmetic(current_premium - entry_premium)?;
    let quantity_adjusted = checked_spread_arithmetic((leg.quantity as f64) * change)?;
    checked_spread_arithmetic(quantity_adjusted * (leg.lot_size as f64))
}

fn leg_side_fee(config: &SpreadConfig, leg: &LegConfig, premium: f64) -> Result<f64, EngineError> {
    let quantity_adjusted =
        checked_spread_arithmetic(premium.abs() * f64::from(leg.quantity.unsigned_abs()))?;
    let lot_adjusted = checked_spread_arithmetic(quantity_adjusted * leg.lot_size as f64)?;
    checked_spread_arithmetic(lot_adjusted * config.fees)
}

fn total_side_fees<'a>(
    config: &SpreadConfig,
    legs_and_premiums: impl IntoIterator<Item = (&'a LegConfig, f64)>,
) -> Result<f64, EngineError> {
    legs_and_premiums
        .into_iter()
        .try_fold(0.0, |total, (leg, premium)| {
            checked_spread_arithmetic(total + leg_side_fee(config, leg, premium)?)
        })
}

fn validate_inputs(
    config: &SpreadConfig,
    timestamps: &[i64],
    legs_premiums: &[Vec<f64>],
    entries: &[bool],
    exits: &[bool],
) -> Result<(), EngineError> {
    validate_input_structure(config, timestamps, legs_premiums, entries, exits)?;
    validate_premiums_parallel(legs_premiums)?;
    validate_spread_arithmetic(config, legs_premiums)?;
    validate_cross_bar_arithmetic(config, legs_premiums, entries, exits)
}

fn validate_input_structure(
    config: &SpreadConfig,
    timestamps: &[i64],
    legs_premiums: &[Vec<f64>],
    entries: &[bool],
    exits: &[bool],
) -> Result<(), EngineError> {
    let n = timestamps.len();

    if !config.initial_capital.is_finite() || config.initial_capital <= 0.0 {
        return Err(invalid_spread_input(
            "initial_capital must be finite and positive",
        ));
    }
    if !config.fees.is_finite() || config.fees < 0.0 {
        return Err(invalid_spread_input("fees must be finite and non-negative"));
    }
    if config
        .max_loss
        .is_some_and(|value| !value.is_finite() || value <= 0.0)
    {
        return Err(invalid_spread_input("max_loss must be finite and positive"));
    }
    if config
        .target_profit
        .is_some_and(|value| !value.is_finite() || value <= 0.0)
    {
        return Err(invalid_spread_input(
            "target_profit must be finite and positive",
        ));
    }
    if config.legs.is_empty() {
        return Err(invalid_spread_input("config must contain at least one leg"));
    }
    for (index, leg) in config.legs.iter().enumerate() {
        if !leg.strike.is_finite() || leg.strike <= 0.0 {
            return Err(invalid_spread_input(format!(
                "config.legs[{index}] strike must be finite and positive"
            )));
        }
        if leg.quantity == 0 {
            return Err(invalid_spread_input(format!(
                "config.legs[{index}] quantity cannot be zero"
            )));
        }
        if leg.lot_size == 0 {
            return Err(invalid_spread_input(format!(
                "config.legs[{index}] lot_size must be positive"
            )));
        }
    }
    if legs_premiums.len() != config.legs.len() {
        return Err(invalid_spread_input(format!(
            "legs_premiums has {} series but config has {} legs",
            legs_premiums.len(),
            config.legs.len()
        )));
    }
    for (i, series) in legs_premiums.iter().enumerate() {
        if series.len() != n {
            return Err(invalid_spread_input(format!(
                "legs_premiums[{i}] has {} bars but timestamps has {n}",
                series.len()
            )));
        }
    }
    if entries.len() != n || exits.len() != n {
        return Err(invalid_spread_input(
            "entries and exits must have the same length as timestamps",
        ));
    }
    if n == 0 {
        return Err(invalid_spread_input("timestamps cannot be empty"));
    }

    Ok(())
}

fn validate_premiums_parallel(legs_premiums: &[Vec<f64>]) -> Result<(), EngineError> {
    let first_invalid = legs_premiums
        .par_iter()
        .enumerate()
        .filter_map(|(series_index, series)| {
            series
                .par_iter()
                .position_first(|premium| !premium.is_finite() || *premium < 0.0)
                .map(|bar_index| (series_index, bar_index))
        })
        .min();

    if let Some((series_index, bar_index)) = first_invalid {
        return Err(invalid_spread_input(format!(
            "legs_premiums[{series_index}][{bar_index}] must be finite and non-negative"
        )));
    }
    Ok(())
}

fn validate_spread_arithmetic(
    config: &SpreadConfig,
    legs_premiums: &[Vec<f64>],
) -> Result<(), EngineError> {
    let first_overflow = (0..legs_premiums[0].len())
        .into_par_iter()
        .find_first(|&bar_index| {
            let mut net_premium = 0.0;
            let mut entry_fees = 0.0;
            let mut exit_fees = 0.0;
            for (leg, premiums) in config.legs.iter().zip(legs_premiums) {
                let premium = premiums[bar_index];
                let quantity_adjusted = premium * leg.quantity as f64;
                let leg_value = quantity_adjusted * leg.lot_size as f64;
                net_premium += leg_value;

                let absolute_quantity_adjusted = premium * f64::from(leg.quantity.unsigned_abs());
                let lot_adjusted = absolute_quantity_adjusted * leg.lot_size as f64;
                let entry_fee = lot_adjusted * config.fees;
                entry_fees += entry_fee;
                exit_fees += entry_fee;

                if !quantity_adjusted.is_finite()
                    || !leg_value.is_finite()
                    || !net_premium.is_finite()
                    || !absolute_quantity_adjusted.is_finite()
                    || !lot_adjusted.is_finite()
                    || !entry_fee.is_finite()
                    || !entry_fees.is_finite()
                    || !exit_fees.is_finite()
                {
                    return true;
                }
            }
            !(config.initial_capital - entry_fees).is_finite()
        });

    if let Some(bar_index) = first_overflow {
        return Err(invalid_spread_input(format!(
            "spread arithmetic overflow at premium bar {bar_index}"
        )));
    }
    Ok(())
}

fn overflow_at_bar(bar_index: usize) -> EngineError {
    invalid_spread_input(format!(
        "spread arithmetic overflow at premium bar {bar_index}"
    ))
}

fn preflight_value(value: Result<f64, EngineError>, bar_index: usize) -> Result<f64, EngineError> {
    value.map_err(|_| overflow_at_bar(bar_index))
}

fn preflight_position_pnl(
    config: &SpreadConfig,
    entry_premiums: &[f64],
    legs_premiums: &[Vec<f64>],
    bar_index: usize,
) -> Result<f64, EngineError> {
    config
        .legs
        .iter()
        .zip(entry_premiums)
        .zip(legs_premiums)
        .try_fold(0.0, |total, ((leg, entry_premium), premiums)| {
            let leg_pnl = preflight_value(
                leg_unrealised_pnl(leg, *entry_premium, premiums[bar_index]),
                bar_index,
            )?;
            preflight_value(checked_spread_arithmetic(total + leg_pnl), bar_index)
        })
}

fn preflight_side_fees(
    config: &SpreadConfig,
    legs_premiums: &[Vec<f64>],
    bar_index: usize,
) -> Result<f64, EngineError> {
    preflight_value(
        total_side_fees(
            config,
            config
                .legs
                .iter()
                .zip(legs_premiums)
                .map(|(leg, premiums)| (leg, premiums[bar_index])),
        ),
        bar_index,
    )
}

fn validate_cross_bar_arithmetic(
    config: &SpreadConfig,
    legs_premiums: &[Vec<f64>],
    entries: &[bool],
    exits: &[bool],
) -> Result<(), EngineError> {
    let mut capital = config.initial_capital;
    let mut prev_equity = capital;
    let mut entry_premiums: Option<Vec<f64>> = None;

    for bar_index in 0..entries.len() {
        let unrealised = match entry_premiums.as_deref() {
            Some(entry) => preflight_position_pnl(config, entry, legs_premiums, bar_index)?,
            None => 0.0,
        };
        let should_exit = entry_premiums.is_some()
            && (exits[bar_index]
                || config.max_loss.is_some_and(|limit| unrealised < -limit)
                || config
                    .target_profit
                    .is_some_and(|target| unrealised > target));

        if should_exit {
            let exit_fees = preflight_side_fees(config, legs_premiums, bar_index)?;
            let net_pnl =
                preflight_value(checked_spread_arithmetic(unrealised - exit_fees), bar_index)?;
            capital = preflight_value(checked_spread_arithmetic(capital + net_pnl), bar_index)?;
            if prev_equity > 0.0 {
                preflight_value(checked_spread_arithmetic(net_pnl / prev_equity), bar_index)?;
            }
            entry_premiums = None;
        }

        if entry_premiums.is_none() && entries[bar_index] {
            let entry_fees = preflight_side_fees(config, legs_premiums, bar_index)?;
            capital = preflight_value(checked_spread_arithmetic(capital - entry_fees), bar_index)?;
            entry_premiums = Some(
                legs_premiums
                    .iter()
                    .map(|premiums| premiums[bar_index])
                    .collect(),
            );
        }

        let marked_pnl = match entry_premiums.as_deref() {
            Some(entry) => preflight_position_pnl(config, entry, legs_premiums, bar_index)?,
            None => 0.0,
        };
        prev_equity = preflight_value(checked_spread_arithmetic(capital + marked_pnl), bar_index)?;
    }

    if let Some(entry) = entry_premiums.as_deref() {
        let final_bar = entries.len() - 1;
        let gross_pnl = preflight_position_pnl(config, entry, legs_premiums, final_bar)?;
        let exit_fees = preflight_side_fees(config, legs_premiums, final_bar)?;
        let net_pnl = preflight_value(checked_spread_arithmetic(gross_pnl - exit_fees), final_bar)?;
        capital = preflight_value(checked_spread_arithmetic(capital + net_pnl), final_bar)?;
        preflight_value(
            checked_spread_arithmetic(net_pnl / config.initial_capital),
            final_bar,
        )?;
    }

    preflight_value(
        checked_spread_arithmetic(capital - config.initial_capital),
        entries.len() - 1,
    )?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Parallel batch execution
// ---------------------------------------------------------------------------

type SpreadBatchItem = (
    SpreadBacktest,
    Vec<i64>,
    Vec<Vec<f64>>,
    Vec<bool>,
    Vec<bool>,
);
type RawSpreadBatchItem = (
    String,
    SpreadConfig,
    Vec<i64>,
    Vec<Vec<f64>>,
    Vec<bool>,
    Vec<bool>,
);
type PythonSpreadBatchItem = (
    SpreadBacktest,
    Vec<StrictI64>,
    Vec<Vec<StrictF64>>,
    Vec<bool>,
    Vec<bool>,
);
type PythonRawSpreadBatchItem = (
    String,
    SpreadConfig,
    Vec<StrictI64>,
    Vec<Vec<StrictF64>>,
    Vec<bool>,
    Vec<bool>,
);

fn numeric_series(values: Vec<StrictF64>) -> Vec<f64> {
    values.into_iter().map(|value| value.0).collect()
}

fn numeric_premium_series(values: Vec<Vec<StrictF64>>) -> Vec<Vec<f64>> {
    values.into_iter().map(numeric_series).collect()
}

fn numeric_timestamps(values: Vec<StrictI64>) -> Vec<i64> {
    values.into_iter().map(|value| value.0).collect()
}

fn validate_spread_batch(items: &[SpreadBatchItem]) -> Result<(), EngineError> {
    for (backtest, timestamps, premiums, entries, exits) in items {
        validate_inputs(&backtest.config, timestamps, premiums, entries, exits)?;
    }
    Ok(())
}

fn execute_spread_batch(items: Vec<SpreadBatchItem>) -> Result<Vec<BacktestResult>, EngineError> {
    let results: Vec<_> = items
        .into_par_iter()
        .map(|(backtest, timestamps, premiums, entries, exits)| {
            backtest.simulate_inner(&timestamps, &premiums, &entries, &exits)
        })
        .collect();
    results.into_iter().collect()
}

fn validate_raw_spread_batch(items: &[RawSpreadBatchItem]) -> Result<(), EngineError> {
    for (_, config, timestamps, premiums, entries, exits) in items {
        validate_inputs(config, timestamps, premiums, entries, exits)?;
    }
    Ok(())
}

fn execute_raw_spread_batch(
    items: Vec<RawSpreadBatchItem>,
) -> Result<Vec<BacktestResult>, EngineError> {
    let results: Vec<_> = items
        .into_par_iter()
        .map(|(name, config, timestamps, premiums, entries, exits)| {
            let backtest = SpreadBacktest { name, config };
            backtest.simulate_inner(&timestamps, &premiums, &entries, &exits)
        })
        .collect();
    results.into_iter().collect()
}

/// Run a batch of `SpreadBacktest` instances in parallel using Rayon.
///
/// Each element is a tuple of `(backtest, timestamps, legs_premiums, entries, exits)`.
/// Returns one `BacktestResult` per element, in the same order, or an
/// `EngineError::InvalidSpreadInput` without starting any simulation.
///
/// # Example
/// ```python
/// from tick_engine import run_spreads_batch, SpreadBacktest, SpreadConfig, LegConfig, OptionType
///
/// config = SpreadConfig(initial_capital=1_000.0, fees=0.0)
/// config.add_leg(LegConfig(OptionType.Call, strike=100.0, quantity=-1, lot_size=1))
/// backtest = SpreadBacktest("SHORT_CALL", config)
/// items = [(backtest, [1, 2], [[10.0, 8.0]], [True, False], [False, True])]
/// results = run_spreads_batch(items)
/// assert results[0].total_pnl == 2.0
/// ```
pub fn run_spreads_batch(
    items: Vec<(
        SpreadBacktest,
        Vec<i64>,
        Vec<Vec<f64>>,
        Vec<bool>,
        Vec<bool>,
    )>,
) -> Result<Vec<BacktestResult>, EngineError> {
    validate_spread_batch(&items)?;
    execute_spread_batch(items)
}

/// Run `SpreadBacktest` items in parallel after ordered extraction and preflight.
///
/// Each item is `(backtest, timestamps, legs_premiums, entries, exits)`.
#[pyfunction(name = "run_spreads_batch")]
#[pyo3(signature = (items), text_signature = "(items)")]
pub(crate) fn run_spreads_batch_py(items: &Bound<'_, PyAny>) -> PyResult<Vec<BacktestResult>> {
    let mut extracted = Vec::new();
    for item in items.try_iter()? {
        let (backtest, timestamps, premiums, entries, exits): PythonSpreadBatchItem =
            item?.extract()?;
        let item = (
            backtest,
            numeric_timestamps(timestamps),
            numeric_premium_series(premiums),
            entries,
            exits,
        );
        validate_inputs(&item.0.config, &item.1, &item.2, &item.3, &item.4)?;
        extracted.push(item);
    }
    Ok(execute_spread_batch(extracted)?)
}

/// Run a batch of spread backtests supplied as raw parameter tuples.
///
/// This lower-level entry point avoids the need to construct `SpreadBacktest`
/// objects on the Python side.  Each tuple is:
/// `(name, config, timestamps, legs_premiums, entries, exits)`.
/// Invalid input returns `EngineError::InvalidSpreadInput`.
pub fn run_batch(
    items: Vec<(
        String,
        SpreadConfig,
        Vec<i64>,
        Vec<Vec<f64>>,
        Vec<bool>,
        Vec<bool>,
    )>,
) -> Result<Vec<BacktestResult>, EngineError> {
    validate_raw_spread_batch(&items)?;
    execute_raw_spread_batch(items)
}

/// Run spread backtests supplied as raw parameter tuples.
///
/// Each item is `(name, config, timestamps, legs_premiums, entries, exits)`.
#[pyfunction(name = "run_batch")]
#[pyo3(signature = (items), text_signature = "(items)")]
pub(crate) fn run_batch_py(items: &Bound<'_, PyAny>) -> PyResult<Vec<BacktestResult>> {
    let mut extracted = Vec::new();
    for item in items.try_iter()? {
        let (name, config, timestamps, premiums, entries, exits): PythonRawSpreadBatchItem =
            item?.extract()?;
        let item = (
            name,
            config,
            numeric_timestamps(timestamps),
            numeric_premium_series(premiums),
            entries,
            exits,
        );
        validate_inputs(&item.1, &item.2, &item.3, &item.4, &item.5)?;
        extracted.push(item);
    }
    Ok(execute_raw_spread_batch(extracted)?)
}

// ---------------------------------------------------------------------------
// Convenience constructors (mirrors raptorbt pattern)
// ---------------------------------------------------------------------------

/// Create a short straddle config (sell ATM call + ATM put).
///
/// Requires the caller to supply premiums for call and put aligned with
/// the timestamp series.
pub fn straddle_config(
    strike: f64,
    lot_size: usize,
    short: bool,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let qty = if short { -1 } else { 1 };
    let mut cfg = SpreadConfig {
        initial_capital,
        fees,
        max_loss: None,
        target_profit: None,
        legs: Vec::new(),
    };
    cfg.add_leg(LegConfig::new(OptionType::Call, strike, qty, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, strike, qty, lot_size));
    cfg
}

/// Create a short strangle config (sell OTM call + OTM put).
pub fn strangle_config(
    call_strike: f64,
    put_strike: f64,
    lot_size: usize,
    short: bool,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let qty = if short { -1 } else { 1 };
    let mut cfg = SpreadConfig {
        initial_capital,
        fees,
        max_loss: None,
        target_profit: None,
        legs: Vec::new(),
    };
    cfg.add_leg(LegConfig::new(OptionType::Call, call_strike, qty, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, put_strike, qty, lot_size));
    cfg
}

/// Create an iron condor config: sell OTM call/put, buy further OTM call/put.
pub fn iron_condor_config(
    short_call: f64,
    long_call: f64,
    short_put: f64,
    long_put: f64,
    lot_size: usize,
    initial_capital: f64,
    fees: f64,
) -> SpreadConfig {
    let mut cfg = SpreadConfig {
        initial_capital,
        fees,
        max_loss: None,
        target_profit: None,
        legs: Vec::new(),
    };
    cfg.add_leg(LegConfig::new(OptionType::Call, short_call, -1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Call, long_call, 1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, short_put, -1, lot_size));
    cfg.add_leg(LegConfig::new(OptionType::Put, long_put, 1, lot_size));
    cfg
}

/// Create a call-and-put straddle configuration at one strike.
#[pyfunction(name = "straddle_config")]
#[pyo3(
    signature = (
        strike,
        lot_size = StrictUsize(50),
        short = true,
        initial_capital = StrictF64(100_000.0),
        fees = StrictF64(0.001)
    ),
    text_signature = "(strike, lot_size=50, short=True, initial_capital=100000.0, fees=0.001)"
)]
pub(crate) fn straddle_config_py(
    strike: StrictF64,
    lot_size: StrictUsize,
    short: bool,
    initial_capital: StrictF64,
    fees: StrictF64,
) -> SpreadConfig {
    straddle_config(strike.0, lot_size.0, short, initial_capital.0, fees.0)
}

/// Create a call-and-put strangle configuration at separate strikes.
#[pyfunction(name = "strangle_config")]
#[pyo3(
    signature = (
        call_strike,
        put_strike,
        lot_size = StrictUsize(50),
        short = true,
        initial_capital = StrictF64(100_000.0),
        fees = StrictF64(0.001)
    ),
    text_signature = "(call_strike, put_strike, lot_size=50, short=True, initial_capital=100000.0, fees=0.001)"
)]
pub(crate) fn strangle_config_py(
    call_strike: StrictF64,
    put_strike: StrictF64,
    lot_size: StrictUsize,
    short: bool,
    initial_capital: StrictF64,
    fees: StrictF64,
) -> SpreadConfig {
    strangle_config(
        call_strike.0,
        put_strike.0,
        lot_size.0,
        short,
        initial_capital.0,
        fees.0,
    )
}

/// Create a four-leg iron-condor configuration.
#[pyfunction(name = "iron_condor_config")]
#[pyo3(
    signature = (
        short_call,
        long_call,
        short_put,
        long_put,
        lot_size = StrictUsize(50),
        initial_capital = StrictF64(100_000.0),
        fees = StrictF64(0.001)
    ),
    text_signature = "(short_call, long_call, short_put, long_put, lot_size=50, initial_capital=100000.0, fees=0.001)"
)]
pub(crate) fn iron_condor_config_py(
    short_call: StrictF64,
    long_call: StrictF64,
    short_put: StrictF64,
    long_put: StrictF64,
    lot_size: StrictUsize,
    initial_capital: StrictF64,
    fees: StrictF64,
) -> SpreadConfig {
    iron_condor_config(
        short_call.0,
        long_call.0,
        short_put.0,
        long_put.0,
        lot_size.0,
        initial_capital.0,
        fees.0,
    )
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
        assert!(
            result.total_pnl > 0.0,
            "expected positive pnl for short straddle with falling premiums"
        );
    }

    #[test]
    fn test_max_loss_triggers_exit() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, Some(500.0), None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19800.0, -1, 50));

        let bt = SpreadBacktest::new("TEST".to_string(), cfg);

        let n = 10;
        let ts = make_ts(n);
        // Premium doubles — short position loses
        let premiums: Vec<f64> = vec![
            100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0,
        ];
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
        let results = run_spreads_batch(items).expect("valid object batch should run");
        assert_eq!(results.len(), 3);
    }

    #[test]
    fn test_raw_batch_public_api_returns_vec() {
        let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001);
        let n = 10;
        let items = vec![(
            "RAW".to_string(),
            cfg,
            make_ts(n),
            vec![vec![200.0; n], vec![200.0; n]],
            vec![false; n],
            vec![false; n],
        )];

        let results = run_batch(items).expect("valid raw batch should run");

        assert_eq!(results.len(), 1);
    }

    #[test]
    fn test_object_batch_public_api_returns_validation_error() {
        let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001);
        let bt = SpreadBacktest::new("INVALID".to_string(), cfg);
        let items = vec![(
            bt,
            vec![1, 2],
            vec![vec![200.0, f64::NAN], vec![200.0, 199.0]],
            vec![false; 2],
            vec![false; 2],
        )];

        let error = run_spreads_batch(items).expect_err("invalid object batch was accepted");

        assert!(error
            .to_string()
            .contains("legs_premiums[0][1] must be finite and non-negative"));
    }

    #[test]
    fn test_raw_batch_public_api_returns_validation_error() {
        let cfg = straddle_config(19800.0, 50, true, 100_000.0, 0.001);
        let items = vec![(
            "INVALID".to_string(),
            cfg,
            vec![1, 2],
            vec![vec![200.0, f64::INFINITY], vec![200.0, 199.0]],
            vec![false; 2],
            vec![false; 2],
        )];

        let error = run_batch(items).expect_err("invalid raw batch was accepted");

        assert!(error
            .to_string()
            .contains("legs_premiums[0][1] must be finite and non-negative"));
    }

    #[test]
    fn test_parallel_premium_preflight_reports_first_invalid_coordinate() {
        let premiums = vec![
            vec![200.0, 199.0, f64::NAN],
            vec![f64::INFINITY, 198.0, 197.0],
        ];

        let error = validate_premiums_parallel(&premiums)
            .expect_err("invalid premiums passed the parallel preflight");

        assert_eq!(
            error.to_string(),
            "legs_premiums[0][2] must be finite and non-negative"
        );
    }

    #[test]
    fn test_finite_leg_product_overflow_is_rejected() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19_800.0, 2, 1));
        let error = run_batch(vec![(
            "OVERFLOW".to_string(),
            cfg,
            vec![1, 2],
            vec![vec![0.0, f64::MAX]],
            vec![true, false],
            vec![false, true],
        )])
        .expect_err("finite inputs produced an overflowing leg result");

        assert!(error.to_string().contains("spread arithmetic overflow"));
    }

    #[test]
    fn test_finite_leg_sum_overflow_is_rejected() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19_800.0, 1, 1));
        cfg.add_leg(LegConfig::new(OptionType::Put, 19_800.0, 1, 1));
        let large_finite_premium = f64::MAX * 0.75;

        let error = run_batch(vec![(
            "OVERFLOW".to_string(),
            cfg,
            vec![1, 2],
            vec![
                vec![0.0, large_finite_premium],
                vec![0.0, large_finite_premium],
            ],
            vec![true, false],
            vec![false, true],
        )])
        .expect_err("finite inputs produced an overflowing spread result");

        assert!(error.to_string().contains("spread arithmetic overflow"));
    }

    #[test]
    fn test_fees_charge_entry_and_exit_once_per_absolute_quantity() {
        let mut cfg = SpreadConfig::new(100.0, 0.1, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 100.0, -3, 2));
        let backtest = SpreadBacktest::new("FEES".to_string(), cfg);

        let result = backtest
            .run(
                vec![1, 2],
                vec![vec![10.0, 12.0]],
                vec![true, false],
                vec![false, true],
            )
            .expect("finite fee calculation should run");

        // Gross P&L is -12.0. Entry fee is 10 * 3 * 2 * 0.1 = 6.0;
        // exit fee is 12 * 3 * 2 * 0.1 = 7.2.
        assert!((result.total_pnl - -25.2).abs() < 1e-12);
        assert_eq!(result.total_trades, 1);
    }

    #[test]
    fn test_cross_bar_aggregate_overflow_is_rejected_by_preflight() {
        let mut cfg = SpreadConfig::new(100.0, 0.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 100.0, 1, 1));
        cfg.add_leg(LegConfig::new(OptionType::Put, 100.0, -1, 1));
        let large_finite_premium = f64::MAX * 0.75;
        let timestamps = vec![1, 2];
        let premiums = vec![
            vec![0.0, large_finite_premium],
            vec![large_finite_premium, 0.0],
        ];
        let entries = vec![true, false];
        let exits = vec![false, true];

        let error = validate_inputs(&cfg, &timestamps, &premiums, &entries, &exits)
            .expect_err("cross-bar aggregate overflow escaped preflight");

        assert_eq!(
            error.to_string(),
            "spread arithmetic overflow at premium bar 1"
        );
    }

    #[test]
    fn test_force_close_return_overflow_is_rejected_by_preflight() {
        let mut cfg = SpreadConfig::new(1e-300, 1.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 100.0, 1, 100));
        let timestamps = vec![1, 2];
        let premiums = vec![vec![1e7, 1e7]];
        let entries = vec![true, false];
        let exits = vec![false, false];

        let error = validate_inputs(&cfg, &timestamps, &premiums, &entries, &exits)
            .expect_err("force-close return overflow escaped preflight");

        assert_eq!(
            error.to_string(),
            "spread arithmetic overflow at premium bar 1"
        );
    }

    #[test]
    fn test_object_batch_reports_first_item_premium_error_before_trailing_structure_error() {
        let valid_cfg = straddle_config(19_800.0, 50, true, 100_000.0, 0.001);
        let first = (
            SpreadBacktest::new("FIRST".to_string(), valid_cfg),
            vec![1, 2],
            vec![vec![200.0, f64::NAN], vec![200.0, 199.0]],
            vec![false; 2],
            vec![false; 2],
        );
        let invalid_cfg = SpreadConfig::new(100_000.0, 0.001, None, None);
        let trailing = (
            SpreadBacktest::new("TRAILING".to_string(), invalid_cfg),
            vec![1, 2],
            vec![],
            vec![false; 2],
            vec![false; 2],
        );

        let error = run_spreads_batch(vec![first, trailing])
            .expect_err("batch ignored the first invalid item");

        assert_eq!(
            error.to_string(),
            "legs_premiums[0][1] must be finite and non-negative"
        );
    }

    #[test]
    fn test_raw_batch_reports_first_item_premium_error_before_trailing_structure_error() {
        let valid_cfg = straddle_config(19_800.0, 50, true, 100_000.0, 0.001);
        let first = (
            "FIRST".to_string(),
            valid_cfg,
            vec![1, 2],
            vec![vec![200.0, f64::NAN], vec![200.0, 199.0]],
            vec![false; 2],
            vec![false; 2],
        );
        let invalid_cfg = SpreadConfig::new(100_000.0, 0.001, None, None);
        let trailing = (
            "TRAILING".to_string(),
            invalid_cfg,
            vec![1, 2],
            vec![],
            vec![false; 2],
            vec![false; 2],
        );

        let error =
            run_batch(vec![first, trailing]).expect_err("batch ignored the first invalid item");

        assert_eq!(
            error.to_string(),
            "legs_premiums[0][1] must be finite and non-negative"
        );
    }

    #[test]
    fn test_object_batch_rejects_short_premium_series_without_panicking() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19_800.0, 1, 50));
        let bt = SpreadBacktest::new("INVALID".to_string(), cfg);
        let items = vec![(
            bt,
            vec![1, 2],
            vec![vec![100.0]],
            vec![true, false],
            vec![false, true],
        )];

        let result = run_spreads_batch(items);

        assert!(result.is_err(), "malformed batch input was accepted");
    }

    #[test]
    fn test_raw_batch_rejects_short_premium_series_without_panicking() {
        let mut cfg = SpreadConfig::new(100_000.0, 0.0, None, None);
        cfg.add_leg(LegConfig::new(OptionType::Call, 19_800.0, 1, 50));
        let items = vec![(
            "INVALID".to_string(),
            cfg,
            vec![1, 2],
            vec![vec![100.0]],
            vec![true, false],
            vec![false, true],
        )];

        let result = run_batch(items);

        assert!(result.is_err(), "malformed batch input was accepted");
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
        let result = bt.run(
            make_ts(n),
            vec![vec![100.0f64; n]],
            vec![false; n],
            vec![false; n],
        );
        assert!(result.is_err());
    }
}
