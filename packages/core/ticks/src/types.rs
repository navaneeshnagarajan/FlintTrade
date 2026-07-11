//! Shared data types for tick-engine.
//!
//! Defines the core `Tick`, `Signal`, and `BacktestResult` types used by all
//! strategies and the Python bindings.

use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// Tick — single price event
// ---------------------------------------------------------------------------

/// A single price tick with OHLCV fields.
///
/// Timestamps are Unix epoch **seconds** (i64). Strategies receive ticks
/// one at a time via `Strategy::on_tick`.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct Tick {
    /// Unix timestamp in seconds.
    pub timestamp: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
}

#[pymethods]
impl Tick {
    #[new]
    pub fn new(timestamp: i64, open: f64, high: f64, low: f64, close: f64, volume: f64) -> Self {
        Tick {
            timestamp,
            open,
            high,
            low,
            close,
            volume,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Tick(ts={}, o={:.2}, h={:.2}, l={:.2}, c={:.2}, v={:.0})",
            self.timestamp, self.open, self.high, self.low, self.close, self.volume
        )
    }
}

// ---------------------------------------------------------------------------
// Signal — output of Strategy::on_tick
// ---------------------------------------------------------------------------

/// Trading signal produced by a strategy.
///
/// Positive `qty` means buy/long; negative `qty` means sell/short.
/// A `qty` of `0` with `close_position = true` exits the current position.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct Signal {
    /// Symbol this signal applies to (e.g. "NIFTY", "RELIANCE").
    pub symbol: String,
    /// Signed quantity. Positive = buy; negative = sell.
    pub qty: f64,
    /// Price hint (0.0 = use market).
    pub price: f64,
    /// If true, flatten the current position before applying `qty`.
    pub close_position: bool,
}

#[pymethods]
impl Signal {
    #[new]
    #[pyo3(signature = (symbol, qty, price = 0.0, close_position = false))]
    pub fn new(symbol: String, qty: f64, price: f64, close_position: bool) -> Self {
        Signal {
            symbol,
            qty,
            price,
            close_position,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Signal({} qty={:.2} price={:.2})",
            self.symbol, self.qty, self.price
        )
    }
}

// ---------------------------------------------------------------------------
// BacktestResult — full run output
// ---------------------------------------------------------------------------

/// Outcome of a complete strategy backtest run.
#[pyclass(get_all)]
#[derive(Clone, Debug)]
pub struct BacktestResult {
    /// Strategy identifier supplied at construction time.
    pub strategy_name: String,
    /// Final net P&L (INR).
    pub total_pnl: f64,
    /// Annualised Sharpe ratio (252 trading-day basis).
    pub sharpe_ratio: f64,
    /// Annualised Sortino ratio.
    pub sortino_ratio: f64,
    /// Maximum peak-to-trough drawdown as a fraction (0–1).
    pub max_drawdown: f64,
    /// Fraction of profitable trades (0–1).
    pub win_rate: f64,
    /// Total completed trades.
    pub total_trades: usize,
    /// Capital at each bar.
    pub equity_curve: Vec<f64>,
    /// Omega ratio (gains / losses above the 0-return threshold).
    pub omega_ratio: f64,
    /// System Quality Number (Van Tharp).
    pub sqn: f64,
    /// Payoff ratio (avg_win / avg_loss).
    pub payoff_ratio: f64,
    /// Recovery factor (net_profit / max_drawdown_absolute).
    pub recovery_factor: f64,
    /// Max consecutive winning trades.
    pub max_consecutive_wins: usize,
    /// Max consecutive losing trades.
    pub max_consecutive_losses: usize,
    /// Average win / average loss (count ratio, not monetary).
    pub avg_win_loss_ratio: f64,
}

#[pymethods]
impl BacktestResult {
    fn __repr__(&self) -> String {
        format!(
            "BacktestResult({} pnl={:.2}, sharpe={:.3}, dd={:.2}%, wr={:.1}%, trades={})",
            self.strategy_name,
            self.total_pnl,
            self.sharpe_ratio,
            self.max_drawdown * 100.0,
            self.win_rate * 100.0,
            self.total_trades,
        )
    }
}
