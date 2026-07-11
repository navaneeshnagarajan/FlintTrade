//! Indian market session tracker.
//!
//! Tracks NSE/BSE intraday session boundaries, pre-market, post-market,
//! and squareoff windows using nanosecond-precision Unix timestamps with a
//! fixed IST offset (UTC+5:30). No external date/time libraries are required.
//!
//! # Example
//! ```
//! use tick_engine::session::{SessionConfig, SessionTracker};
//!
//! let mut tracker = SessionTracker::new(SessionConfig::nse_equity());
//!
//! // 2024-01-15 09:15:00 IST = 2024-01-15 03:45:00 UTC = 1705290300 seconds since epoch
//! let ts_ns: i64 = 1705290300_i64 * 1_000_000_000;
//! let state = tracker.update(0, ts_ns, 100.0, 101.0, 99.0, 100.5, None, None);
//! assert!(state.is_market_hours);
//! ```

use pyo3::prelude::*;

// ---------------------------------------------------------------------------
// IST offset: UTC+5:30 = 19800 seconds
// ---------------------------------------------------------------------------
const IST_OFFSET_SECS: i64 = 5 * 3600 + 30 * 60;

// ---------------------------------------------------------------------------
// SessionConfig
// ---------------------------------------------------------------------------

/// Market session configuration.
///
/// Defaults to NSE equity hours (09:15–15:30 IST, squareoff at 15:25).
#[pyclass(get_all, set_all)]
#[derive(Clone, Debug)]
pub struct SessionConfig {
    /// Market open in minutes from midnight (IST). NSE = 9*60+15 = 555.
    pub market_open_minutes: u32,
    /// Market close in minutes from midnight (IST). NSE = 15*60+30 = 930.
    pub market_close_minutes: u32,
    /// Pre-market start in minutes from midnight. NSE = 9*60 = 540.
    pub pre_market_start_minutes: u32,
    /// Post-market end in minutes from midnight. NSE = 15*60+45 = 945.
    pub post_market_end_minutes: u32,
    /// Minutes before close at which squareoff is triggered. Default = 5.
    pub squareoff_buffer_minutes: u32,
}

impl Default for SessionConfig {
    fn default() -> Self {
        Self::nse_equity()
    }
}

#[pymethods]
impl SessionConfig {
    #[new]
    #[pyo3(signature = (
        market_open_minutes = 555,
        market_close_minutes = 930,
        pre_market_start_minutes = 540,
        post_market_end_minutes = 945,
        squareoff_buffer_minutes = 5
    ))]
    pub fn new(
        market_open_minutes: u32,
        market_close_minutes: u32,
        pre_market_start_minutes: u32,
        post_market_end_minutes: u32,
        squareoff_buffer_minutes: u32,
    ) -> Self {
        Self {
            market_open_minutes,
            market_close_minutes,
            pre_market_start_minutes,
            post_market_end_minutes,
            squareoff_buffer_minutes,
        }
    }

    fn __repr__(&self) -> String {
        let open_h = self.market_open_minutes / 60;
        let open_m = self.market_open_minutes % 60;
        let close_h = self.market_close_minutes / 60;
        let close_m = self.market_close_minutes % 60;
        format!(
            "SessionConfig({:02}:{:02}–{:02}:{:02} IST)",
            open_h, open_m, close_h, close_m
        )
    }
}

impl SessionConfig {
    /// NSE equity (09:15–15:30 IST, squareoff at 15:25).
    pub fn nse_equity() -> Self {
        Self {
            market_open_minutes: 9 * 60 + 15,
            market_close_minutes: 15 * 60 + 30,
            pre_market_start_minutes: 9 * 60,
            post_market_end_minutes: 15 * 60 + 45,
            squareoff_buffer_minutes: 5,
        }
    }

    /// MCX commodity (09:00–23:30 IST, squareoff at 23:25).
    pub fn mcx_commodity() -> Self {
        Self {
            market_open_minutes: 9 * 60,
            market_close_minutes: 23 * 60 + 30,
            pre_market_start_minutes: 8 * 60 + 45,
            post_market_end_minutes: 23 * 60 + 45,
            squareoff_buffer_minutes: 5,
        }
    }

    /// CDS currency derivatives (09:00–17:00 IST).
    pub fn cds_currency() -> Self {
        Self {
            market_open_minutes: 9 * 60,
            market_close_minutes: 17 * 60,
            pre_market_start_minutes: 8 * 60 + 45,
            post_market_end_minutes: 17 * 60 + 15,
            squareoff_buffer_minutes: 5,
        }
    }

    /// Squareoff time in minutes from midnight.
    #[inline]
    pub fn squareoff_minutes(&self) -> u32 {
        self.market_close_minutes
            .saturating_sub(self.squareoff_buffer_minutes)
    }
}

// ---------------------------------------------------------------------------
// SessionState — snapshot returned per update
// ---------------------------------------------------------------------------

/// Per-bar session state snapshot.
#[pyclass(get_all)]
#[derive(Clone, Debug, Default)]
pub struct SessionState {
    /// True on the first bar of a new session.
    pub session_open: bool,
    /// True when market closes (last bar of a session).
    pub session_close: bool,
    /// True while within regular market hours.
    pub is_market_hours: bool,
    /// True during pre-market window.
    pub is_pre_market: bool,
    /// True during post-market window.
    pub is_post_market: bool,
    /// True on the first bar that crosses the squareoff threshold.
    pub squareoff_triggered: bool,
    /// Intraday high tracked since session open.
    pub session_high: f64,
    /// Intraday low tracked since session open.
    pub session_low: f64,
    /// First price of the session.
    pub session_open_price: f64,
}

#[pymethods]
impl SessionState {
    fn __repr__(&self) -> String {
        format!(
            "SessionState(market={}, pre={}, post={}, sq={}, high={:.2}, low={:.2})",
            self.is_market_hours,
            self.is_pre_market,
            self.is_post_market,
            self.squareoff_triggered,
            self.session_high,
            self.session_low,
        )
    }
}

// ---------------------------------------------------------------------------
// SessionTracker
// ---------------------------------------------------------------------------

/// Stateful session tracker for Indian market hours.
///
/// Feed each bar's timestamp and OHLC through `update()`. The returned
/// `SessionState` reflects whether the bar falls within market hours,
/// pre-market, post-market, or triggers squareoff.
///
/// All timestamps are Unix epoch **nanoseconds**.
///
/// # Example
/// ```
/// use tick_engine::session::{SessionConfig, SessionTracker};
///
/// let mut tracker = SessionTracker::new(SessionConfig::nse_equity());
/// // 2024-01-15 09:15:00 IST = 2024-01-15 03:45:00 UTC = 1705290300 seconds since epoch
/// let ts_ns = 1705290300_i64 * 1_000_000_000;
/// let state = tracker.update(0, ts_ns, 19500.0, 19520.0, 19490.0, 19510.0, None, None);
/// assert!(state.is_market_hours);
/// assert!(state.session_open);
/// ```
#[pyclass]
#[derive(Debug)]
pub struct SessionTracker {
    config: SessionConfig,
    /// IST day index (local epoch-days) of the current session.
    current_day: i64,
    /// Session high (reset each day).
    session_high: f64,
    /// Session low (reset each day).
    session_low: f64,
    /// First price of the session.
    session_open_price: f64,
    /// Whether squareoff was already triggered today.
    squareoff_triggered_today: bool,
    /// Whether we are inside market hours for the current bar.
    in_session: bool,
}

#[pymethods]
impl SessionTracker {
    #[new]
    pub fn new(config: SessionConfig) -> Self {
        Self {
            config,
            current_day: -1,
            session_high: f64::NEG_INFINITY,
            session_low: f64::INFINITY,
            session_open_price: 0.0,
            squareoff_triggered_today: false,
            in_session: false,
        }
    }

    /// Process one bar and return the current `SessionState`.
    ///
    /// Args:
    ///     idx: Bar index (for bookkeeping; not used internally).
    ///     timestamp_ns: Unix nanosecond timestamp of the bar.
    ///     open/high/low/close: OHLC prices used for session high/low tracking.
    ///     prev_timestamp_ns: Preceding bar's timestamp (optional).
    ///     next_timestamp_ns: Following bar's timestamp (optional, used to
    ///                        detect session end on the last intraday bar).
    #[pyo3(signature = (idx, timestamp_ns, open, high, low, close, prev_timestamp_ns=None, next_timestamp_ns=None))]
    pub fn update(
        &mut self,
        idx: usize,
        timestamp_ns: i64,
        open: f64,
        high: f64,
        low: f64,
        close: f64,
        prev_timestamp_ns: Option<i64>,
        next_timestamp_ns: Option<i64>,
    ) -> SessionState {
        let _ = (idx, close); // idx and close accepted for API compatibility

        let (day, minutes_from_midnight) = Self::to_ist_components(timestamp_ns);

        let is_market = minutes_from_midnight >= self.config.market_open_minutes
            && minutes_from_midnight < self.config.market_close_minutes;

        let is_pre = minutes_from_midnight >= self.config.pre_market_start_minutes
            && minutes_from_midnight < self.config.market_open_minutes;

        // Post-market: from market close until post_market_end
        let is_post = minutes_from_midnight >= self.config.market_close_minutes
            && minutes_from_midnight < self.config.post_market_end_minutes;

        // Detect new session: different calendar day OR same day but crossed open threshold
        let session_open = if day != self.current_day {
            // New date — session starts if we are in market hours
            if is_market {
                self.reset_session(day, open);
                true
            } else {
                // Out of market hours on a new day — reset tracking but don't open session
                if !self.in_session {
                    self.current_day = day;
                }
                false
            }
        } else if let Some(prev_ts) = prev_timestamp_ns {
            let (_, prev_min) = Self::to_ist_components(prev_ts);
            let was_pre_or_before = prev_min < self.config.market_open_minutes;
            if was_pre_or_before && is_market && !self.in_session {
                self.reset_session(day, open);
                true
            } else {
                false
            }
        } else if is_market && !self.in_session {
            // Very first bar
            self.reset_session(day, open);
            true
        } else {
            false
        };

        // Track intraday high/low only while in session
        if self.in_session {
            if high > self.session_high {
                self.session_high = high;
            }
            if low < self.session_low {
                self.session_low = low;
            }
        }

        // Squareoff check
        let squareoff_triggered =
            if is_market && minutes_from_midnight >= self.config.squareoff_minutes() {
                if !self.squareoff_triggered_today {
                    self.squareoff_triggered_today = true;
                    true
                } else {
                    false
                }
            } else {
                false
            };

        // Detect session close:
        // - Current bar is past market close, OR
        // - Next bar exists and is on a different day or outside market hours.
        // NOTE: When next_timestamp_ns is None we cannot determine if this is
        //       the last bar, so we do NOT close the session eagerly. Callers
        //       that need end-of-data close should pass a synthetic out-of-hours
        //       next timestamp or use force-close logic in their own loop.
        let session_close = if self.in_session && !is_market {
            // Bar itself is already past market close
            self.in_session = false;
            true
        } else if self.in_session && is_market {
            // Close only if the next bar is provably outside this session
            let next_outside_session = match next_timestamp_ns {
                None => false, // unknown — don't close
                Some(nts) => {
                    let (nday, nmin) = Self::to_ist_components(nts);
                    let next_in_session = nday == day
                        && nmin >= self.config.market_open_minutes
                        && nmin < self.config.market_close_minutes;
                    !next_in_session
                }
            };
            if next_outside_session {
                self.in_session = false;
                true
            } else {
                false
            }
        } else {
            false
        };

        // Snapshot with safe fallbacks for non-session bars
        let (sh, sl, sop) = if self.session_high == f64::NEG_INFINITY {
            (0.0, 0.0, 0.0)
        } else {
            (self.session_high, self.session_low, self.session_open_price)
        };

        SessionState {
            session_open,
            session_close,
            is_market_hours: is_market,
            is_pre_market: is_pre,
            is_post_market: is_post,
            squareoff_triggered,
            session_high: sh,
            session_low: sl,
            session_open_price: sop,
        }
    }

    /// Whether currently inside a session.
    pub fn in_session(&self) -> bool {
        self.in_session
    }

    /// Current session high (0.0 if no session started).
    pub fn session_high(&self) -> f64 {
        if self.session_high == f64::NEG_INFINITY {
            0.0
        } else {
            self.session_high
        }
    }

    /// Current session low (0.0 if no session started).
    pub fn session_low(&self) -> f64 {
        if self.session_low == f64::INFINITY {
            0.0
        } else {
            self.session_low
        }
    }

    /// First price of the current session.
    pub fn session_open_price(&self) -> f64 {
        self.session_open_price
    }
}

impl SessionTracker {
    /// Convert nanosecond timestamp to (IST day index, minutes from midnight).
    fn to_ist_components(timestamp_ns: i64) -> (i64, u32) {
        let ts_secs = timestamp_ns / 1_000_000_000;
        let local_secs = ts_secs + IST_OFFSET_SECS;
        let day = local_secs.div_euclid(86400);
        let time_in_day = local_secs.rem_euclid(86400) as u32;
        let minutes = time_in_day / 60;
        (day, minutes)
    }

    fn reset_session(&mut self, day: i64, open_price: f64) {
        self.current_day = day;
        self.session_high = open_price;
        self.session_low = open_price;
        self.session_open_price = open_price;
        self.in_session = true;
        self.squareoff_triggered_today = false;
    }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    /// Build a nanosecond timestamp for a given UTC time, then apply IST offset
    /// so the local time equals the requested IST hour/minute.
    ///
    /// We use 2024-01-15 as a base date.
    fn make_ts_ns(ist_hour: u32, ist_minute: u32) -> i64 {
        // Seconds since 1970-01-01 at 00:00 UTC for 2024-01-15
        // 2024-01-15: days since epoch = 54 years approx, use a known value.
        // 2024-01-15 00:00:00 UTC = 1705276800
        let midnight_utc: i64 = 1_705_276_800;
        let ist_secs = ist_hour as i64 * 3600 + ist_minute as i64 * 60;
        // IST = UTC + 5:30 → UTC = IST - 5:30
        let utc_secs = midnight_utc + ist_secs - IST_OFFSET_SECS;
        utc_secs * 1_000_000_000
    }

    #[test]
    fn test_session_opens_at_market_open() {
        let mut tracker = SessionTracker::new(SessionConfig::nse_equity());
        let ts = make_ts_ns(9, 15);
        let state = tracker.update(0, ts, 100.0, 101.0, 99.0, 100.5, None, None);
        assert!(state.is_market_hours, "9:15 IST should be market hours");
        assert!(
            state.session_open,
            "First market bar should open the session"
        );
        assert!(!state.is_pre_market);
    }

    #[test]
    fn test_pre_market_detection() {
        let mut tracker = SessionTracker::new(SessionConfig::nse_equity());
        let ts = make_ts_ns(9, 5); // 09:05 IST
        let state = tracker.update(0, ts, 100.0, 100.5, 99.5, 100.0, None, None);
        assert!(state.is_pre_market, "09:05 should be pre-market");
        assert!(!state.is_market_hours);
    }

    #[test]
    fn test_squareoff_triggers_once() {
        let mut tracker = SessionTracker::new(SessionConfig::nse_equity());

        // Open the session first
        let ts_open = make_ts_ns(9, 15);
        tracker.update(0, ts_open, 100.0, 101.0, 99.0, 100.5, None, None);

        // 15:25 — squareoff threshold (930 - 5 = 925 minutes)
        let ts_sq = make_ts_ns(15, 25);
        let state1 = tracker.update(1, ts_sq, 100.0, 100.5, 99.5, 100.2, Some(ts_open), None);
        assert!(
            state1.squareoff_triggered,
            "First bar at squareoff time should trigger"
        );

        // Second bar at 15:26 — should NOT trigger again
        let ts_sq2 = make_ts_ns(15, 26);
        let state2 = tracker.update(2, ts_sq2, 100.2, 100.3, 99.8, 100.1, Some(ts_sq), None);
        assert!(
            !state2.squareoff_triggered,
            "Squareoff should only trigger once"
        );
    }

    #[test]
    fn test_session_high_low_tracking() {
        let mut tracker = SessionTracker::new(SessionConfig::nse_equity());

        let ts1 = make_ts_ns(9, 15);
        tracker.update(0, ts1, 100.0, 105.0, 95.0, 102.0, None, None);

        let ts2 = make_ts_ns(9, 30);
        tracker.update(1, ts2, 102.0, 110.0, 100.0, 108.0, Some(ts1), None);

        assert_eq!(tracker.session_high(), 110.0);
        assert_eq!(tracker.session_low(), 95.0);
    }

    #[test]
    fn test_mcx_session_config() {
        let cfg = SessionConfig::mcx_commodity();
        assert_eq!(cfg.market_open_minutes, 9 * 60);
        assert_eq!(cfg.market_close_minutes, 23 * 60 + 30);
        assert_eq!(cfg.squareoff_minutes(), 23 * 60 + 25);
    }

    #[test]
    fn test_after_hours_not_market() {
        let mut tracker = SessionTracker::new(SessionConfig::nse_equity());
        // 15:35 IST — after market close (15:30) but before post_market_end (15:45)
        let ts = make_ts_ns(15, 35);
        let state = tracker.update(0, ts, 100.0, 100.5, 99.5, 100.2, None, None);
        assert!(!state.is_market_hours, "15:35 should not be market hours");
        assert!(!state.is_pre_market, "15:35 should not be pre-market");
        assert!(state.is_post_market, "15:35 should be post-market");

        // 16:00 IST — after post_market_end (15:45)
        let ts2 = make_ts_ns(16, 0);
        let mut tracker2 = SessionTracker::new(SessionConfig::nse_equity());
        let state2 = tracker2.update(0, ts2, 100.0, 100.5, 99.5, 100.2, None, None);
        assert!(!state2.is_market_hours);
        assert!(!state2.is_pre_market);
        assert!(
            !state2.is_post_market,
            "16:00 should be after post-market window"
        );
    }
}
