//! Options strategy: straddle / strangle with Black-Scholes Greeks.
//!
//! Simulates long or short straddle/strangle positions over a historical
//! series.  Each bar supplies the underlying spot price and the call/put
//! premiums for the chosen strikes.  The strategy uses the `Strategy` trait
//! for tick-by-tick operation and exposes a `run()` method for full
//! vectorised backtesting from Python.
//!
//! # Black-Scholes Greeks
//! `delta`, `gamma`, `theta`, `vega`, and `rho` are computed analytically
//! using the standard BSM closed-form formulas.  Implied volatility must
//! be supplied by the caller as implied volatility in the bar data.
//!
//! # Example
//! ```python
//! from tick_engine import OptionsStrategy, OptionsConfig, OptionStrategyType
//!
//! cfg = OptionsConfig(
//!     strategy_type="straddle",
//!     lot_size=50,
//!     strike_interval=50.0,
//!     short=True,        # sell premium
//!     commission=40.0,   # per leg
//! )
//! strat = OptionsStrategy("NIFTY_STRADDLE", cfg)
//! # spot_bars: [[ts, o, h, l, c, v], ...]
//! # call_bars: [[ts, premium, implied_volatility, delta, gamma, theta], ...]
//! # put_bars:  [[ts, premium, implied_volatility, delta, gamma, theta], ...]
//! result = strat.run(spot_bars, call_bars, put_bars, entries, exits, 100_000.0)
//! ```

use std::f64::consts::PI;

use pyo3::prelude::*;

use crate::metrics::{
    avg_win_loss_ratio, max_consecutive_streaks, max_drawdown_frac, omega_ratio, payoff_ratio,
    recovery_factor, sharpe_ratio, sortino_ratio, sqn,
};
use crate::types::{BacktestResult, Signal, Tick};

use super::pairs::Strategy;

// ---------------------------------------------------------------------------
// Greeks
// ---------------------------------------------------------------------------

/// Computed BSM Greeks for one option.
#[pyclass(get_all)]
#[derive(Clone, Debug, Default)]
pub struct Greeks {
    pub delta: f64,
    pub gamma: f64,
    pub theta: f64, // per calendar day
    pub vega: f64,  // per 1% move in IV
    pub rho: f64,
}

#[pymethods]
impl Greeks {
    fn __repr__(&self) -> String {
        format!(
            "Greeks(Δ={:.4} Γ={:.4} Θ={:.4} V={:.4} ρ={:.4})",
            self.delta, self.gamma, self.theta, self.vega, self.rho
        )
    }
}

/// Compute BSM Greeks analytically.
///
/// Args:
///     spot: Underlying price.
///     strike: Option strike price.
///     r: Risk-free rate (annual, e.g. 0.065 = 6.5%).
///     implied_volatility: Implied volatility (annual, e.g. 0.20 = 20%).
///     t: Time to expiry in **years**.
///     is_call: true for call, false for put.
#[pyfunction]
pub fn black_scholes_greeks(
    spot: f64,
    strike: f64,
    r: f64,
    implied_volatility: f64,
    t: f64,
    is_call: bool,
) -> Greeks {
    if t <= 0.0 || implied_volatility <= 0.0 || spot <= 0.0 || strike <= 0.0 {
        return Greeks::default();
    }

    let sqrt_t = t.sqrt();
    let d1 = ((spot / strike).ln() + (r + 0.5 * implied_volatility * implied_volatility) * t)
        / (implied_volatility * sqrt_t);
    let d2 = d1 - implied_volatility * sqrt_t;

    let nd1 = norm_cdf(d1);
    let nd2 = norm_cdf(d2);
    let nd1_neg = norm_cdf(-d1);
    let nd2_neg = norm_cdf(-d2);
    let phi_d1 = norm_pdf(d1);

    let delta = if is_call { nd1 } else { nd1 - 1.0 };
    let gamma = phi_d1 / (spot * implied_volatility * sqrt_t);
    // Theta per calendar day (divide by 365)
    let theta_annual = if is_call {
        -(spot * phi_d1 * implied_volatility) / (2.0 * sqrt_t) - r * strike * (-r * t).exp() * nd2
    } else {
        -(spot * phi_d1 * implied_volatility) / (2.0 * sqrt_t)
            + r * strike * (-r * t).exp() * nd2_neg
    };
    let theta = theta_annual / 365.0;
    // Vega per 1% (multiply by 0.01)
    let vega = spot * phi_d1 * sqrt_t * 0.01;
    let rho = if is_call {
        strike * t * (-r * t).exp() * nd2 * 0.01
    } else {
        -strike * t * (-r * t).exp() * nd2_neg * 0.01
    };

    let _ = nd1_neg; // used indirectly

    Greeks { delta, gamma, theta, vega, rho }
}

// ---------------------------------------------------------------------------
// Option strategy types
// ---------------------------------------------------------------------------

/// Which options strategy to backtest.
#[pyclass(eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OptionStrategyType {
    /// ATM call + ATM put (same strike).
    Straddle,
    /// OTM call + OTM put (different strikes).
    Strangle,
}

// ---------------------------------------------------------------------------
// OptionsConfig
// ---------------------------------------------------------------------------

/// Configuration for an options strategy backtest.
#[pyclass(get_all, set_all)]
#[derive(Clone, Debug)]
pub struct OptionsConfig {
    /// Straddle or Strangle.
    pub strategy_type: OptionStrategyType,
    /// Units per contract (e.g. 50 for NIFTY).
    pub lot_size: usize,
    /// Strike spacing (e.g. 50.0 for NIFTY).
    pub strike_interval: f64,
    /// True = sell premium; false = buy premium.
    pub short: bool,
    /// Flat commission per leg per trade in INR.
    pub commission: f64,
    /// One-way slippage fraction.
    pub slippage_pct: f64,
    /// Annual risk-free rate (e.g. 0.065).
    pub risk_free_rate: f64,
}

impl Default for OptionsConfig {
    fn default() -> Self {
        Self {
            strategy_type: OptionStrategyType::Straddle,
            lot_size: 50,
            strike_interval: 50.0,
            short: true,
            commission: 40.0,
            slippage_pct: 0.001,
            risk_free_rate: 0.065,
        }
    }
}

#[pymethods]
impl OptionsConfig {
    #[new]
    #[pyo3(signature = (
        strategy_type = OptionStrategyType::Straddle,
        lot_size = 50,
        strike_interval = 50.0,
        short = true,
        commission = 40.0,
        slippage_pct = 0.001,
        risk_free_rate = 0.065
    ))]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        strategy_type: OptionStrategyType,
        lot_size: usize,
        strike_interval: f64,
        short: bool,
        commission: f64,
        slippage_pct: f64,
        risk_free_rate: f64,
    ) -> Self {
        Self { strategy_type, lot_size, strike_interval, short, commission, slippage_pct, risk_free_rate }
    }

    fn __repr__(&self) -> String {
        format!(
            "OptionsConfig(type={:?}, lot={}, short={}, commission={:.0})",
            self.strategy_type, self.lot_size, self.short, self.commission
        )
    }
}

// ---------------------------------------------------------------------------
// Internal position state
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct OptionPosition {
    entry_call_premium: f64,
    entry_put_premium: f64,
    #[allow(dead_code)]
    call_strike: f64,
    #[allow(dead_code)]
    put_strike: f64,
    #[allow(dead_code)]
    entry_time: i64,
    lots: f64,
}

// ---------------------------------------------------------------------------
// OptionsStrategy
// ---------------------------------------------------------------------------

/// Options strategy (straddle / strangle) with BSM Greeks tracking.
///
/// Supply entry/exit signals as boolean arrays aligned with the bar series.
#[pyclass]
pub struct OptionsStrategy {
    name: String,
    config: OptionsConfig,
    position: Option<OptionPosition>,
}

#[pymethods]
impl OptionsStrategy {
    #[new]
    pub fn new(name: String, config: OptionsConfig) -> Self {
        Self { name, config, position: None }
    }

    /// Run a full options strategy backtest.
    ///
    /// Args:
    ///     spot_bars:  `[ts, open, high, low, close, volume]` per bar.
    ///     call_bars:  `[ts, premium, implied_volatility, dte_years, _unused, _unused]` per bar.
    ///     put_bars:   `[ts, premium, implied_volatility, dte_years, _unused, _unused]` per bar.
    ///     entries:    Boolean list aligned with bars (true = enter at this bar).
    ///     exits:      Boolean list aligned with bars (true = exit at this bar).
    ///     initial_capital: Starting capital in INR.
    pub fn run(
        &mut self,
        spot_bars: Vec<[f64; 6]>,
        call_bars: Vec<[f64; 6]>,
        put_bars: Vec<[f64; 6]>,
        entries: Vec<bool>,
        exits: Vec<bool>,
        initial_capital: f64,
    ) -> PyResult<BacktestResult> {
        let n = spot_bars.len();
        if call_bars.len() != n || put_bars.len() != n || entries.len() != n || exits.len() != n
        {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "All input arrays must have equal length",
            ));
        }
        if n == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("bar arrays cannot be empty"));
        }

        let mut capital = initial_capital;
        let mut equity_curve = Vec::with_capacity(n + 1);
        equity_curve.push(capital);

        let mut trade_pnls: Vec<f64> = Vec::new();
        let mut trade_returns: Vec<f64> = Vec::new();

        self.position = None;

        // For a short position: P&L = entry_premium - exit_premium (profit from decay)
        // For a long  position: P&L = exit_premium  - entry_premium (profit from rise)
        // sign_pnl = +1 for short (entry - exit), -1 for long (entry - exit reversed)
        // The formula: pnl = sign_pnl * (entry - exit) * lots * lot_size
        let sign_pnl = if self.config.short { 1.0_f64 } else { -1.0 };

        for i in 0..n {
            let spot = spot_bars[i][4]; // close
            let call_prem = call_bars[i][1];
            let put_prem = put_bars[i][1];
            let call_implied_volatility = call_bars[i][2];
            let dte = call_bars[i][3]; // time to expiry in years
            let put_implied_volatility = put_bars[i][2];

            // Compute Greeks for monitoring (not used in simple P&L simulation)
            let call_greeks = black_scholes_greeks(
                spot,
                self.call_strike(spot),
                self.config.risk_free_rate,
                call_implied_volatility,
                dte,
                true,
            );
            let put_greeks = black_scholes_greeks(
                spot,
                self.put_strike(spot),
                self.config.risk_free_rate,
                put_implied_volatility,
                dte,
                false,
            );
            let _ = (call_greeks, put_greeks); // stored for future streaming Greeks output

            // Check exit
            if exits[i] {
                if let Some(ref pos) = self.position.take() {
                    let lots = pos.lots;
                    let lot_size = self.config.lot_size as f64;

                    let call_exit = self.exit_price(call_prem, true);
                    let put_exit = self.exit_price(put_prem, false);

                    let call_pnl = sign_pnl
                        * (pos.entry_call_premium - call_exit)
                        * lots
                        * lot_size;
                    let put_pnl = sign_pnl
                        * (pos.entry_put_premium - put_exit)
                        * lots
                        * lot_size;
                    let pnl = call_pnl + put_pnl - self.config.commission * 2.0 * lots;

                    capital += pnl;
                    let ret = pnl / initial_capital;
                    trade_pnls.push(pnl);
                    trade_returns.push(ret);
                }
            }

            // Check entry
            if entries[i] && self.position.is_none() {
                let lots = 1.0;
                capital -= self.config.commission * 2.0 * lots;

                self.position = Some(OptionPosition {
                    entry_call_premium: self.entry_price(call_prem, true),
                    entry_put_premium: self.entry_price(put_prem, false),
                    call_strike: self.call_strike(spot),
                    put_strike: self.put_strike(spot),
                    entry_time: spot_bars[i][0] as i64,
                    lots,
                });
            }

            // Mark-to-market equity
            let unrealised = if let Some(ref pos) = self.position {
                let lot_size = self.config.lot_size as f64;
                sign_pnl * (pos.entry_call_premium - call_prem) * pos.lots * lot_size
                    + sign_pnl * (pos.entry_put_premium - put_prem) * pos.lots * lot_size
            } else {
                0.0
            };
            equity_curve.push(capital + unrealised);
        }

        // Force-close at end
        if let Some(pos) = self.position.take() {
            let last = n - 1;
            let lot_size = self.config.lot_size as f64;
            let call_exit = self.exit_price(call_bars[last][1], true);
            let put_exit = self.exit_price(put_bars[last][1], false);
            let pnl = sign_pnl * (pos.entry_call_premium - call_exit) * pos.lots * lot_size
                + sign_pnl * (pos.entry_put_premium - put_exit) * pos.lots * lot_size
                - self.config.commission * 2.0 * pos.lots;
            capital += pnl;
            trade_pnls.push(pnl);
            trade_returns.push(pnl / initial_capital);
        }
        equity_curve.push(capital);

        let total_pnl = capital - initial_capital;
        let total_trades = trade_pnls.len();
        let win_count = trade_pnls.iter().filter(|&&p| p > 0.0).count();
        let win_rate = if total_trades > 0 { win_count as f64 / total_trades as f64 } else { 0.0 };
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
            recovery_factor: recovery_factor(total_pnl, max_dd * initial_capital),
            max_consecutive_wins: mcw,
            max_consecutive_losses: mcl,
            avg_win_loss_ratio: avg_win_loss_ratio(&trade_pnls),
        })
    }

    fn __repr__(&self) -> String {
        format!("OptionsStrategy(name='{}', config={:?})", self.name, self.config.strategy_type)
    }
}

impl OptionsStrategy {
    /// ATM strike rounded to the nearest interval.
    fn atm_strike(&self, spot: f64) -> f64 {
        (spot / self.config.strike_interval).round() * self.config.strike_interval
    }

    fn call_strike(&self, spot: f64) -> f64 {
        match self.config.strategy_type {
            OptionStrategyType::Straddle => self.atm_strike(spot),
            // Strangle: call is one interval OTM
            OptionStrategyType::Strangle => self.atm_strike(spot) + self.config.strike_interval,
        }
    }

    fn put_strike(&self, spot: f64) -> f64 {
        match self.config.strategy_type {
            OptionStrategyType::Straddle => self.atm_strike(spot),
            // Strangle: put is one interval OTM
            OptionStrategyType::Strangle => self.atm_strike(spot) - self.config.strike_interval,
        }
    }

    fn entry_price(&self, premium: f64, is_call: bool) -> f64 {
        // Short = we sell; buyer pays ask (we receive ask = premium * (1 + slip))
        // Long  = we buy;  we pay ask
        if self.config.short {
            if is_call {
                premium * (1.0 - self.config.slippage_pct) // we receive bid
            } else {
                premium * (1.0 - self.config.slippage_pct)
            }
        } else {
            premium * (1.0 + self.config.slippage_pct) // we pay ask
        }
    }

    fn exit_price(&self, premium: f64, _is_call: bool) -> f64 {
        // On exit, direction reverses
        if self.config.short {
            premium * (1.0 + self.config.slippage_pct) // buy back at ask
        } else {
            premium * (1.0 - self.config.slippage_pct)
        }
    }
}

impl Strategy for OptionsStrategy {
    fn on_tick(&mut self, _tick: &Tick) -> Vec<Signal> {
        Vec::new()
    }

    fn name(&self) -> &str {
        &self.name
    }
}

// ---------------------------------------------------------------------------
// BSM math helpers
// ---------------------------------------------------------------------------

/// Cumulative standard normal CDF (Abramowitz & Stegun approximation).
fn norm_cdf(x: f64) -> f64 {
    let t = 1.0 / (1.0 + 0.2316419 * x.abs());
    let poly = t
        * (0.319_381_53
            + t * (-0.356_563_782
                + t * (1.781_477_937 + t * (-1.821_255_978 + t * 1.330_274_429))));
    let approx = 1.0 - norm_pdf(x) * poly;
    if x >= 0.0 { approx } else { 1.0 - approx }
}

/// Standard normal PDF.
fn norm_pdf(x: f64) -> f64 {
    (-0.5 * x * x).exp() / (2.0 * PI).sqrt()
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_norm_cdf_symmetry() {
        assert!((norm_cdf(0.0) - 0.5).abs() < 1e-6);
        assert!((norm_cdf(1.96) - 0.975).abs() < 0.001);
        assert!((norm_cdf(-1.96) - 0.025).abs() < 0.001);
    }

    #[test]
    fn test_greeks_call_delta_range() {
        let g = black_scholes_greeks(19500.0, 19500.0, 0.065, 0.15, 0.1, true);
        // ATM call delta is around 0.5
        assert!(g.delta > 0.4 && g.delta < 0.6, "ATM delta={}", g.delta);
    }

    #[test]
    fn test_greeks_put_delta_range() {
        let g = black_scholes_greeks(19500.0, 19500.0, 0.065, 0.15, 0.1, false);
        // ATM put delta is around -0.5
        assert!(g.delta > -0.6 && g.delta < -0.4, "ATM put delta={}", g.delta);
    }

    #[test]
    fn test_greeks_gamma_positive() {
        let g = black_scholes_greeks(19500.0, 19500.0, 0.065, 0.15, 0.1, true);
        assert!(g.gamma > 0.0);
    }

    #[test]
    fn test_greeks_theta_negative_long_call() {
        // Theta should be negative for a long call (time decay)
        let g = black_scholes_greeks(19500.0, 19500.0, 0.065, 0.15, 0.25, true);
        assert!(g.theta < 0.0, "Long call theta should be negative, got {}", g.theta);
    }

    #[test]
    fn test_options_run_shape() {
        let cfg = OptionsConfig::default();
        let mut strat = OptionsStrategy::new("NIFTY_STRADDLE".to_string(), cfg);

        let n = 30;
        let spot: Vec<[f64; 6]> = (0..n)
            .map(|i| [i as f64, 19500.0, 19520.0, 19480.0, 19500.0, 100.0])
            .collect();
        let call: Vec<[f64; 6]> = (0..n)
            .map(|i| [i as f64, 200.0 - i as f64, 0.15, 0.1, 0.0, 0.0])
            .collect();
        let put: Vec<[f64; 6]> = (0..n)
            .map(|i| [i as f64, 200.0 - i as f64 * 0.5, 0.15, 0.1, 0.0, 0.0])
            .collect();

        let mut entries = vec![false; n];
        entries[5] = true;
        let mut exits = vec![false; n];
        exits[20] = true;

        let result = strat.run(spot, call, put, entries, exits, 100_000.0).unwrap();
        assert_eq!(result.strategy_name, "NIFTY_STRADDLE");
        assert!(result.total_trades >= 1);
    }

    #[test]
    fn test_atm_strike_rounding() {
        let cfg = OptionsConfig::default(); // strike_interval = 50
        let strat = OptionsStrategy::new("X".to_string(), cfg);
        assert_eq!(strat.atm_strike(19834.0), 19850.0);
        assert_eq!(strat.atm_strike(19810.0), 19800.0);
    }
}
