//! Pairs trading strategy with OLS cointegration signal.
//!
//! The strategy tracks the spread between two instruments and generates
//! entry/exit signals based on Z-score thresholds:
//!
//! - Entry long spread (long leg1, short leg2): Z-score < −entry_z
//! - Entry short spread (short leg1, long leg2): Z-score >  entry_z
//! - Exit position:                              |Z-score| < exit_z
//!
//! Hedge ratio is computed by rolling OLS regression of `leg1` on `leg2`.
//!
//! # Example
//! ```python
//! from tick_engine import PairsStrategy
//!
//! strat = PairsStrategy("HDFC_ICICI", entry_z=2.0, exit_z=0.5, lookback=20)
//! ticks_a = [[ts, o, h, l, c, v], ...]
//! ticks_b = [[ts, o, h, l, c, v], ...]
//! result = strat.run(ticks_a, ticks_b)
//! print(result)
//! ```

use pyo3::prelude::*;

use crate::metrics::{
    avg_win_loss_ratio, max_consecutive_streaks, max_drawdown_frac, omega_ratio, payoff_ratio,
    recovery_factor, sharpe_ratio, sortino_ratio, sqn,
};
use crate::types::{BacktestResult, Signal, Tick};

// ---------------------------------------------------------------------------
// Strategy trait
// ---------------------------------------------------------------------------

/// Core strategy interface: receive one tick, emit zero or more signals.
pub trait Strategy {
    fn on_tick(&mut self, tick: &Tick) -> Vec<Signal>;
    fn name(&self) -> &str;
}

// ---------------------------------------------------------------------------
// PairsStrategy
// ---------------------------------------------------------------------------

/// Pairs trading strategy driven by Z-score on the OLS spread.
///
/// Maintains a rolling window of prices for both legs and computes the
/// hedge ratio via simple linear regression. The Z-score of the residual
/// series triggers entries and exits.
#[pyclass]
pub struct PairsStrategy {
    /// Display name / identifier.
    name: String,
    /// Entry Z-score threshold (absolute value).
    entry_z: f64,
    /// Exit Z-score threshold (absolute value, must be < entry_z).
    exit_z: f64,
    /// Lookback window for OLS and Z-score calculation.
    lookback: usize,
    /// Lot size per leg.
    lot_size: f64,
    /// Per-trade commission (INR flat).
    commission: f64,
    /// One-way slippage fraction.
    slippage_pct: f64,

    // ---- internal mutable state ----
    leg1_prices: Vec<f64>,
    leg2_prices: Vec<f64>,
    /// Current open position: 1 = long spread, -1 = short spread, 0 = flat.
    position: i8,
    entry_leg1_price: f64,
    entry_leg2_price: f64,
    entry_time: i64,
    /// Accumulated hedge ratio for position sizing.
    hedge_ratio: f64,
}

#[pymethods]
impl PairsStrategy {
    #[new]
    #[pyo3(signature = (name, entry_z=2.0, exit_z=0.5, lookback=20, lot_size=1.0, commission=20.0, slippage_pct=0.001))]
    pub fn new(
        name: String,
        entry_z: f64,
        exit_z: f64,
        lookback: usize,
        lot_size: f64,
        commission: f64,
        slippage_pct: f64,
    ) -> Self {
        PairsStrategy {
            name,
            entry_z,
            exit_z,
            lookback,
            lot_size,
            commission,
            slippage_pct,
            leg1_prices: Vec::with_capacity(lookback + 1),
            leg2_prices: Vec::with_capacity(lookback + 1),
            position: 0,
            entry_leg1_price: 0.0,
            entry_leg2_price: 0.0,
            entry_time: 0,
            hedge_ratio: 1.0,
        }
    }

    /// Run a full backtest across two aligned bar series.
    ///
    /// Each bar is `[timestamp, open, high, low, close, volume]`.
    /// Both lists must have the same length.
    pub fn run(
        &mut self,
        leg1_bars: Vec<[f64; 6]>,
        leg2_bars: Vec<[f64; 6]>,
        initial_capital: f64,
    ) -> PyResult<BacktestResult> {
        if leg1_bars.len() != leg2_bars.len() {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "leg1_bars ({}) and leg2_bars ({}) must have equal length",
                leg1_bars.len(),
                leg2_bars.len()
            )));
        }
        if leg1_bars.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "bar lists cannot be empty",
            ));
        }

        let n = leg1_bars.len();
        let mut capital = initial_capital;
        let mut equity_curve = Vec::with_capacity(n + 1);
        equity_curve.push(capital);

        // Trade-level tracking
        let mut trade_pnls: Vec<f64> = Vec::new();
        let mut trade_returns: Vec<f64> = Vec::new();

        // Reset strategy state
        self.reset_state();

        for i in 0..n {
            let b1 = &leg1_bars[i];
            let b2 = &leg2_bars[i];

            let t1 = Tick::new(b1[0] as i64, b1[1], b1[2], b1[3], b1[4], b1[5]);
            let t2 = Tick::new(b2[0] as i64, b2[1], b2[2], b2[3], b2[4], b2[5]);

            // Update internal price buffers
            self.push_prices(t1.close, t2.close);

            // Get the signal from the strategy core
            let signal = self.compute_signal(&t1, &t2);

            match signal {
                // Flat → open long spread
                (0, 1) => {
                    capital -= self.commission * 2.0; // both legs
                    self.position = 1;
                    self.entry_leg1_price = t1.close * (1.0 + self.slippage_pct);
                    self.entry_leg2_price = t2.close * (1.0 - self.slippage_pct);
                    self.entry_time = t1.timestamp;
                }
                // Flat → open short spread
                (0, -1) => {
                    capital -= self.commission * 2.0;
                    self.position = -1;
                    self.entry_leg1_price = t1.close * (1.0 - self.slippage_pct);
                    self.entry_leg2_price = t2.close * (1.0 + self.slippage_pct);
                    self.entry_time = t1.timestamp;
                }
                // Any open position → close on reversion
                (_, 0) if self.position != 0 => {
                    let pnl = self.close_position(t1.close, t2.close, &mut capital);
                    let ret = if initial_capital > 0.0 {
                        pnl / initial_capital
                    } else {
                        0.0
                    };
                    trade_pnls.push(pnl);
                    trade_returns.push(ret);
                }
                _ => {}
            }

            equity_curve.push(capital);
        }

        // Force-close at the end
        if self.position != 0 {
            let last = n - 1;
            let pnl = self.close_position(leg1_bars[last][4], leg2_bars[last][4], &mut capital);
            let ret = if initial_capital > 0.0 {
                pnl / initial_capital
            } else {
                0.0
            };
            trade_pnls.push(pnl);
            trade_returns.push(ret);
        }
        equity_curve.push(capital);

        let total_pnl = capital - initial_capital;
        let total_trades = trade_pnls.len();
        let win_count = trade_pnls.iter().filter(|&&p| p > 0.0).count();
        let win_rate = if total_trades > 0 {
            win_count as f64 / total_trades as f64
        } else {
            0.0
        };

        let max_dd = max_drawdown_frac(&equity_curve);
        let max_dd_abs = max_dd * initial_capital;

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
            recovery_factor: recovery_factor(total_pnl, max_dd_abs),
            max_consecutive_wins: mcw,
            max_consecutive_losses: mcl,
            avg_win_loss_ratio: avg_win_loss_ratio(&trade_pnls),
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "PairsStrategy(name='{}', entry_z={:.1}, exit_z={:.1}, lookback={})",
            self.name, self.entry_z, self.exit_z, self.lookback
        )
    }
}

impl PairsStrategy {
    fn reset_state(&mut self) {
        self.leg1_prices.clear();
        self.leg2_prices.clear();
        self.position = 0;
        self.entry_leg1_price = 0.0;
        self.entry_leg2_price = 0.0;
        self.entry_time = 0;
        self.hedge_ratio = 1.0;
    }

    /// Append close prices to the rolling window.
    fn push_prices(&mut self, p1: f64, p2: f64) {
        self.leg1_prices.push(p1);
        self.leg2_prices.push(p2);
        if self.leg1_prices.len() > self.lookback {
            self.leg1_prices.remove(0);
            self.leg2_prices.remove(0);
        }
    }

    /// Compute desired position change.
    /// Returns `(current_position, desired_position)`.
    fn compute_signal(&mut self, t1: &Tick, t2: &Tick) -> (i8, i8) {
        if self.leg1_prices.len() < self.lookback {
            return (self.position, self.position); // warm-up period
        }

        let (hedge, residuals) = self.ols_residuals();
        self.hedge_ratio = hedge;

        let z = zscore(&residuals);
        let last_z = *residuals.last().map(|_| &z).unwrap_or(&0.0);

        // Compute the actual z-score of the last residual using rolling stats
        let n = residuals.len() as f64;
        let mean_r = residuals.iter().sum::<f64>() / n;
        let std_r = (residuals.iter().map(|r| (r - mean_r).powi(2)).sum::<f64>()
            / (n - 1.0).max(1.0))
        .sqrt();
        let current_spread = t1.close - hedge * t2.close;
        let z_score = if std_r > 1e-10 {
            (current_spread - mean_r) / std_r
        } else {
            0.0
        };

        let _ = last_z; // suppress warning

        let desired = if self.position == 0 {
            if z_score < -self.entry_z {
                1 // spread below mean → buy spread (long leg1, short leg2)
            } else if z_score > self.entry_z {
                -1 // spread above mean → sell spread (short leg1, long leg2)
            } else {
                0
            }
        } else {
            // Exit when spread reverts to mean
            if z_score.abs() < self.exit_z {
                0
            } else {
                self.position as i32 as i8
            }
        };

        (self.position, desired)
    }

    /// OLS regression of leg1 on leg2. Returns (beta, residuals).
    fn ols_residuals(&self) -> (f64, Vec<f64>) {
        let x = &self.leg2_prices;
        let y = &self.leg1_prices;
        let n = x.len() as f64;

        let sum_x: f64 = x.iter().sum();
        let sum_y: f64 = y.iter().sum();
        let sum_xy: f64 = x.iter().zip(y.iter()).map(|(xi, yi)| xi * yi).sum();
        let sum_x2: f64 = x.iter().map(|xi| xi * xi).sum();

        let denom = n * sum_x2 - sum_x * sum_x;
        let beta = if denom.abs() > 1e-10 {
            (n * sum_xy - sum_x * sum_y) / denom
        } else {
            1.0
        };
        let alpha = (sum_y - beta * sum_x) / n;

        let residuals: Vec<f64> = y
            .iter()
            .zip(x.iter())
            .map(|(yi, xi)| yi - alpha - beta * xi)
            .collect();

        (beta.max(0.01), residuals)
    }

    /// Close current position and return realised P&L.
    fn close_position(&mut self, leg1_exit: f64, leg2_exit: f64, capital: &mut f64) -> f64 {
        let (l1_exit, l2_exit) = if self.position > 0 {
            // Long spread exit: sell leg1, buy leg2
            (
                leg1_exit * (1.0 - self.slippage_pct),
                leg2_exit * (1.0 + self.slippage_pct),
            )
        } else {
            // Short spread exit: buy leg1, sell leg2
            (
                leg1_exit * (1.0 + self.slippage_pct),
                leg2_exit * (1.0 - self.slippage_pct),
            )
        };

        let leg1_pnl = (l1_exit - self.entry_leg1_price) * (self.position as f64) * self.lot_size;
        let leg2_pnl = (l2_exit - self.entry_leg2_price)
            * (-self.position as f64)
            * self.lot_size
            * self.hedge_ratio;
        let pnl = leg1_pnl + leg2_pnl - self.commission * 2.0;

        *capital += pnl;
        self.position = 0;
        pnl
    }
}

impl Strategy for PairsStrategy {
    fn on_tick(&mut self, tick: &Tick) -> Vec<Signal> {
        // Single-leg interface: not the primary entry point for pairs;
        // use `run()` for the full simulation. This method is provided for
        // completeness with the `Strategy` trait.
        self.push_prices(tick.close, tick.close);
        Vec::new()
    }

    fn name(&self) -> &str {
        &self.name
    }
}

/// Z-score of the last element of a series.
fn zscore(series: &[f64]) -> f64 {
    if series.len() < 2 {
        return 0.0;
    }
    let n = series.len() as f64;
    let mean = series.iter().sum::<f64>() / n;
    let std = (series.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / (n - 1.0)).sqrt();
    if std < 1e-10 {
        return 0.0;
    }
    let last = *series.last().unwrap();
    (last - mean) / std
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_bars(prices: &[f64]) -> Vec<[f64; 6]> {
        prices
            .iter()
            .enumerate()
            .map(|(i, &p)| [i as f64, p, p + 1.0, p - 1.0, p, 1000.0])
            .collect()
    }

    #[test]
    fn test_pairs_run_shape() {
        let mut strat = PairsStrategy::new("TEST_PAIR".to_string(), 2.0, 0.5, 10, 1.0, 20.0, 0.001);

        let leg1: Vec<f64> = (0..50).map(|i| 100.0 + (i as f64) * 0.1).collect();
        let leg2: Vec<f64> = (0..50).map(|i| 50.0 + (i as f64) * 0.05).collect();

        let result = strat
            .run(make_bars(&leg1), make_bars(&leg2), 100_000.0)
            .unwrap();
        assert_eq!(result.equity_curve.len(), leg1.len() + 2);
        assert_eq!(result.strategy_name, "TEST_PAIR");
    }

    #[test]
    fn test_zscore_zero_on_constant() {
        let series = vec![1.0, 1.0, 1.0, 1.0, 1.0];
        assert_eq!(zscore(&series), 0.0);
    }

    #[test]
    fn test_ols_residuals_returns_hedge() {
        let mut strat = PairsStrategy::new("P".to_string(), 2.0, 0.5, 5, 1.0, 0.0, 0.0);
        // Perfect linear relationship: leg1 = 2 * leg2
        for i in 0..5 {
            strat.push_prices(2.0 * i as f64, i as f64);
        }
        let (beta, _) = strat.ols_residuals();
        assert!((beta - 2.0).abs() < 0.01, "expected beta≈2, got {beta}");
    }

    #[test]
    fn test_mismatched_bar_lengths_error() {
        let mut strat = PairsStrategy::new("P".to_string(), 2.0, 0.5, 10, 1.0, 20.0, 0.001);
        let r = strat.run(make_bars(&[1.0, 2.0]), make_bars(&[1.0]), 100_000.0);
        assert!(r.is_err());
    }
}
