//! Performance metrics for backtesting.
//!
//! Computes Sharpe, Sortino, Omega, SQN, payoff ratio, recovery factor,
//! max drawdown, and consecutive win/loss streaks from a completed trade list
//! or equity curve.
//!
//! All ratio functions accept a `returns` slice of **per-trade** fractional
//! returns (e.g. 0.02 for +2%).

// ---------------------------------------------------------------------------
// Risk-adjusted return ratios
// ---------------------------------------------------------------------------

/// Annualised Sharpe ratio (252 trading-day basis, risk-free rate = 0).
///
/// Returns 0.0 when fewer than 2 observations are available or standard
/// deviation is negligible.
///
/// # Example
/// ```
/// use tick_engine::metrics::sharpe_ratio;
/// let r = sharpe_ratio(&[0.01, -0.005, 0.02, 0.008, -0.003]);
/// assert!(r > 0.0);
/// ```
pub fn sharpe_ratio(returns: &[f64]) -> f64 {
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
    mean / std_dev * 252_f64.sqrt()
}

/// Annualised Sortino ratio (252 trading-day basis, MAR = 0).
///
/// Uses only below-threshold returns for the denominator (downside deviation),
/// matching the Van Tharp definition.
///
/// # Example
/// ```
/// use tick_engine::metrics::sortino_ratio;
/// let r = sortino_ratio(&[0.01, -0.005, 0.02, 0.008, -0.003]);
/// assert!(r > 0.0);
/// ```
pub fn sortino_ratio(returns: &[f64]) -> f64 {
    if returns.len() < 2 {
        return 0.0;
    }
    let n = returns.len() as f64;
    let mean = returns.iter().sum::<f64>() / n;
    // Downside deviation: only negative returns contribute
    let downside_var =
        returns.iter().map(|&r| if r < 0.0 { r.powi(2) } else { 0.0 }).sum::<f64>() / (n - 1.0);
    let downside_std = downside_var.sqrt();
    if downside_std < 1e-10 {
        return if mean > 0.0 { f64::INFINITY } else { 0.0 };
    }
    mean / downside_std * 252_f64.sqrt()
}

/// Omega ratio with threshold MAR = 0.
///
/// Omega = (sum of gains above MAR) / |sum of losses below MAR|.
/// A value > 1 indicates net positive expectation.
///
/// Returns `f64::INFINITY` when there are no losing returns, and 0.0 when
/// there are no winning returns.
///
/// # Example
/// ```
/// use tick_engine::metrics::omega_ratio;
/// let r = omega_ratio(&[0.02, -0.01, 0.03, -0.005, 0.01]);
/// assert!(r > 1.0);
/// ```
pub fn omega_ratio(returns: &[f64]) -> f64 {
    let sum_pos: f64 = returns.iter().filter(|&&r| r > 0.0).sum();
    let sum_neg: f64 = returns.iter().filter(|&&r| r < 0.0).map(|r| r.abs()).sum();
    if sum_neg < 1e-10 {
        return if sum_pos > 0.0 { f64::INFINITY } else { 0.0 };
    }
    sum_pos / sum_neg
}

// ---------------------------------------------------------------------------
// Trade-level metrics
// ---------------------------------------------------------------------------

/// SQN (System Quality Number) per Van Tharp.
///
/// SQN = (mean_trade_r / stddev_trade_r) × sqrt(n_trades)
///
/// Interpretation: > 2.5 = good system, > 5 = excellent.
///
/// # Example
/// ```
/// use tick_engine::metrics::sqn;
/// let r = sqn(&[0.01, 0.02, -0.005, 0.015, 0.008]);
/// assert!(r > 0.0);
/// ```
pub fn sqn(returns: &[f64]) -> f64 {
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
    (mean / std_dev) * n.sqrt()
}

/// Payoff ratio: average winning return / average losing return (absolute).
///
/// Returns `f64::INFINITY` when there are no losing trades, 0.0 when there
/// are no winning trades.
///
/// # Example
/// ```
/// use tick_engine::metrics::payoff_ratio;
/// let r = payoff_ratio(&[0.02, -0.01, 0.04, -0.005]);
/// assert!(r > 0.0);
/// ```
pub fn payoff_ratio(returns: &[f64]) -> f64 {
    let wins: Vec<f64> = returns.iter().filter(|&&r| r > 0.0).copied().collect();
    let losses: Vec<f64> = returns.iter().filter(|&&r| r < 0.0).copied().collect();
    if losses.is_empty() {
        return if wins.is_empty() { 0.0 } else { f64::INFINITY };
    }
    if wins.is_empty() {
        return 0.0;
    }
    let avg_win = wins.iter().sum::<f64>() / wins.len() as f64;
    let avg_loss = losses.iter().map(|r| r.abs()).sum::<f64>() / losses.len() as f64;
    if avg_loss < 1e-10 {
        return f64::INFINITY;
    }
    avg_win / avg_loss
}

/// Recovery factor: net_profit / max_drawdown_absolute.
///
/// Both arguments are expressed in the same currency units (e.g. INR).
/// Returns `f64::INFINITY` when `max_drawdown_abs` is zero and
/// `net_profit` is positive.
///
/// # Example
/// ```
/// use tick_engine::metrics::recovery_factor;
/// assert_eq!(recovery_factor(5000.0, 2000.0), 2.5);
/// ```
pub fn recovery_factor(net_profit: f64, max_drawdown_abs: f64) -> f64 {
    if max_drawdown_abs < 1e-10 {
        return if net_profit > 0.0 { f64::INFINITY } else { 0.0 };
    }
    net_profit / max_drawdown_abs
}

// ---------------------------------------------------------------------------
// Streak metrics
// ---------------------------------------------------------------------------

/// Maximum consecutive winning and losing trades.
///
/// Returns `(max_wins, max_losses)`.
///
/// # Example
/// ```
/// use tick_engine::metrics::max_consecutive_streaks;
/// // W L W W L
/// let pnls = [10.0_f64, -5.0, 8.0, 12.0, -3.0];
/// let (w, l) = max_consecutive_streaks(&pnls);
/// assert_eq!(w, 2);
/// assert_eq!(l, 1);
/// ```
pub fn max_consecutive_streaks(pnls: &[f64]) -> (usize, usize) {
    let mut max_wins = 0usize;
    let mut max_losses = 0usize;
    let mut cur_wins = 0usize;
    let mut cur_losses = 0usize;

    for &p in pnls {
        if p > 0.0 {
            cur_wins += 1;
            cur_losses = 0;
            max_wins = max_wins.max(cur_wins);
        } else if p < 0.0 {
            cur_losses += 1;
            cur_wins = 0;
            max_losses = max_losses.max(cur_losses);
        }
        // breakeven resets nothing
    }
    (max_wins, max_losses)
}

/// Average win / average loss ratio (count-based, not monetary).
///
/// Returns the number of winning trades divided by the number of losing trades.
/// Returns 0.0 when there are no losing trades.
pub fn avg_win_loss_ratio(pnls: &[f64]) -> f64 {
    let n_wins = pnls.iter().filter(|&&p| p > 0.0).count();
    let n_losses = pnls.iter().filter(|&&p| p < 0.0).count();
    if n_losses == 0 {
        return if n_wins > 0 { f64::INFINITY } else { 0.0 };
    }
    n_wins as f64 / n_losses as f64
}

// ---------------------------------------------------------------------------
// Drawdown
// ---------------------------------------------------------------------------

/// Maximum peak-to-trough drawdown as a fraction (0.0–1.0).
///
/// # Example
/// ```
/// use tick_engine::metrics::max_drawdown_frac;
/// let eq = [100.0_f64, 110.0, 105.0, 90.0, 95.0, 112.0];
/// let dd = max_drawdown_frac(&eq);
/// assert!((dd - (110.0 - 90.0) / 110.0).abs() < 1e-10);
/// ```
pub fn max_drawdown_frac(equity: &[f64]) -> f64 {
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
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sharpe_positive() {
        let returns = [0.01, 0.02, -0.005, 0.015, 0.008];
        assert!(sharpe_ratio(&returns) > 0.0);
    }

    #[test]
    fn test_sharpe_empty() {
        assert_eq!(sharpe_ratio(&[]), 0.0);
        assert_eq!(sharpe_ratio(&[0.01]), 0.0);
    }

    #[test]
    fn test_sortino_ignores_upside() {
        let all_pos = [0.01, 0.02, 0.005];
        // No downside: should return INFINITY (mean > 0, no losses)
        assert_eq!(sortino_ratio(&all_pos), f64::INFINITY);
    }

    #[test]
    fn test_omega_balanced() {
        let returns = [0.02, -0.01, 0.03, -0.005, 0.01];
        let o = omega_ratio(&returns);
        // gains = 0.06, losses = 0.015 → omega = 4.0
        assert!((o - 4.0).abs() < 1e-10);
    }

    #[test]
    fn test_sqn_positive() {
        let returns = [0.01, 0.02, -0.005, 0.015, 0.008];
        assert!(sqn(&returns) > 0.0);
    }

    #[test]
    fn test_payoff_ratio_known_value() {
        // avg win = (0.02 + 0.04) / 2 = 0.03
        // avg loss = (0.01 + 0.005) / 2 = 0.0075
        let returns = [0.02, -0.01, 0.04, -0.005];
        let pr = payoff_ratio(&returns);
        assert!((pr - 4.0).abs() < 1e-10);
    }

    #[test]
    fn test_recovery_factor() {
        assert_eq!(recovery_factor(5000.0, 2000.0), 2.5);
        assert_eq!(recovery_factor(100.0, 0.0), f64::INFINITY);
    }

    #[test]
    fn test_max_consecutive_streaks() {
        // W L W W L
        let pnls = [10.0_f64, -5.0, 8.0, 12.0, -3.0];
        let (w, l) = max_consecutive_streaks(&pnls);
        assert_eq!(w, 2);
        assert_eq!(l, 1);
    }

    #[test]
    fn test_max_drawdown_frac_known_value() {
        let eq = [100.0_f64, 110.0, 105.0, 90.0, 95.0, 112.0];
        let dd = max_drawdown_frac(&eq);
        // peak=110, trough=90 → dd = 20/110
        let expected = 20.0 / 110.0;
        assert!((dd - expected).abs() < 1e-10);
    }

    #[test]
    fn test_avg_win_loss_ratio() {
        let pnls = [10.0_f64, -5.0, 8.0, -3.0, 12.0];
        // 3 wins, 2 losses → ratio = 1.5
        let r = avg_win_loss_ratio(&pnls);
        assert!((r - 1.5).abs() < 1e-10);
    }
}
