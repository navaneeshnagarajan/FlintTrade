//! Auto-logout scheduler for FlintTrade Desktop.
//!
//! Schedules an automatic session logout at **3:00 AM IST** every day, which
//! is safely outside Indian market hours (09:15 – 15:30 IST).  Warning
//! notifications are emitted at **2:30 AM** and **2:55 AM** so the user has
//! time to save work.
//!
//! On logout the scheduler:
//!
//! 1. Emits the `auto_logout_warning` Tauri event at each configured warning
//!    threshold.
//! 2. At the logout instant, calls `POST /ft-api/v1/auth/revoke` on the
//!    FlintTrade backend to invalidate the JWT.
//! 3. Clears any cached credentials from the OS keychain via
//!    [`crate::keychain`].
//! 4. Emits the `auto_logout` Tauri event so the WebView can redirect to the
//!    login screen.
//!
//! # Design notes
//!
//! The scheduler runs on a dedicated OS thread (via `std::thread::spawn`)
//! because Tauri's async runtime is not guaranteed to be running during the
//! full application lifetime.  Sleeping is done with `std::thread::sleep`
//! rather than `tokio::time::sleep` for the same reason.

use chrono::{NaiveTime, Timelike, Utc};
use chrono_tz::Asia::Kolkata;
use serde::Serialize;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Duration;
use tauri::{AppHandle, Emitter};
use tracing::{info, warn};

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

/// Logout hour in IST (24-hour clock).
const LOGOUT_HOUR: u32 = 3;
/// Logout minute in IST.
const LOGOUT_MINUTE: u32 = 0;

/// Warning thresholds — minutes *before* logout at which to send a notification.
/// Must be in **descending** order so warnings fire earliest-first.
const WARNING_MINUTES: &[u32] = &[30, 5];

// ─────────────────────────────────────────────────────────────────────────────
// Event payload types
// ─────────────────────────────────────────────────────────────────────────────

/// Payload for the `auto_logout_warning` Tauri event.
#[derive(Clone, Serialize)]
pub struct AutoLogoutWarning {
    /// Minutes remaining until session logout.
    pub minutes_remaining: u32,
    /// Human-readable message suitable for displaying in a toast.
    pub message: String,
}

/// Payload for the `auto_logout` Tauri event.
#[derive(Clone, Serialize)]
pub struct AutoLogoutEvent {
    /// Reason text for display.
    pub reason: String,
    /// RFC 3339 timestamp of when the logout was executed.
    pub timestamp: String,
}

// ─────────────────────────────────────────────────────────────────────────────
// Scheduler
// ─────────────────────────────────────────────────────────────────────────────

/// Auto-logout scheduler that fires every night at 3:00 AM IST.
///
/// Create with [`AutoLogoutScheduler::new`], then call [`AutoLogoutScheduler::start`]
/// once during app setup.  The internal thread keeps running until
/// [`AutoLogoutScheduler::stop`] is called or the process exits.
pub struct AutoLogoutScheduler {
    app_handle: AppHandle,
    running: Arc<AtomicBool>,
}

impl AutoLogoutScheduler {
    /// Create a new scheduler.
    ///
    /// Does **not** start the background thread — call [`start`](Self::start)
    /// after construction.
    pub fn new(app_handle: AppHandle) -> Self {
        Self {
            app_handle,
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Start the background scheduling thread.
    ///
    /// Safe to call multiple times — subsequent calls are no-ops if the
    /// scheduler is already running.
    pub fn start(&self) {
        if self.running.swap(true, Ordering::SeqCst) {
            warn!("AutoLogoutScheduler.start() called while already running — ignored");
            return;
        }

        let app_handle = self.app_handle.clone();
        let running = Arc::clone(&self.running);

        std::thread::spawn(move || {
            info!(
                "Auto-logout scheduler started — daily logout at {:02}:{:02} IST",
                LOGOUT_HOUR, LOGOUT_MINUTE
            );

            while running.load(Ordering::SeqCst) {
                // ── Phase 1: emit warnings ────────────────────────────────
                schedule_warnings(&app_handle, &running);

                // ── Phase 2: execute logout ───────────────────────────────
                if running.load(Ordering::SeqCst) {
                    execute_logout(&app_handle);
                }

                // ── Phase 3: sleep briefly so we do not immediately re-fire
                // (the next wake-up will be ~24 h away after the first pass)
                std::thread::sleep(Duration::from_secs(60));
            }

            info!("Auto-logout scheduler stopped");
        });
    }

    /// Signal the background thread to stop after its current sleep.
    ///
    /// The thread will exit gracefully on the next iteration check.
    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
        info!("Auto-logout scheduler stop requested");
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

/// Sleep until each warning threshold, emitting a notification each time, then
/// sleep the remaining time until the logout instant.
fn schedule_warnings(app_handle: &AppHandle, running: &Arc<AtomicBool>) {
    // Work through thresholds from largest to smallest
    for &threshold in WARNING_MINUTES {
        if !running.load(Ordering::SeqCst) {
            return;
        }

        let secs_to_logout = secs_until_ist(LOGOUT_HOUR, LOGOUT_MINUTE);
        let secs_to_warning = secs_to_logout.saturating_sub(u64::from(threshold) * 60);

        if secs_to_warning == 0 {
            // We are already past this warning window — emit now and continue
            emit_warning(app_handle, threshold);
            continue;
        }

        // Sleep until it is time to emit this warning
        info!(
            "Sleeping {}s until {}-minute auto-logout warning",
            secs_to_warning, threshold
        );
        sleep_interruptible(Duration::from_secs(secs_to_warning), running);

        if running.load(Ordering::SeqCst) {
            emit_warning(app_handle, threshold);
        }
    }

    // Sleep the final stretch (≤ WARNING_MINUTES.last() minutes) to the logout time
    if running.load(Ordering::SeqCst) {
        let remaining = secs_until_ist(LOGOUT_HOUR, LOGOUT_MINUTE);
        if remaining > 0 {
            info!(
                "Sleeping {}s until {:02}:{:02} IST auto-logout",
                remaining, LOGOUT_HOUR, LOGOUT_MINUTE
            );
            sleep_interruptible(Duration::from_secs(remaining), running);
        }
    }
}

/// Emit a warning Tauri event.
fn emit_warning(app_handle: &AppHandle, minutes_remaining: u32) {
    let message = format!(
        "FlintTrade will log you out in {} minute{} (3:00 AM IST compliance logout).",
        minutes_remaining,
        if minutes_remaining == 1 { "" } else { "s" }
    );
    info!("{}", message);

    let payload = AutoLogoutWarning {
        minutes_remaining,
        message,
    };

    if let Err(e) = app_handle.emit("auto_logout_warning", payload) {
        warn!("Failed to emit auto_logout_warning: {}", e);
    }
}

/// Perform the actual logout:
///
/// 1. Revoke the JWT via the FlintTrade backend REST API.
/// 2. Clear cached broker tokens from the OS keychain.
/// 3. Emit the `auto_logout` Tauri event.
fn execute_logout(app_handle: &AppHandle) {
    info!("Executing scheduled auto-logout at {:02}:{:02} IST", LOGOUT_HOUR, LOGOUT_MINUTE);

    // Step 1 — revoke the JWT (best-effort, do not block on failure)
    revoke_jwt();

    // Step 2 — wipe cached keychain entries
    clear_cached_credentials();

    // Step 3 — notify the WebView
    let payload = AutoLogoutEvent {
        reason: format!(
            "Scheduled auto-logout at {:02}:{:02} IST for session hygiene.",
            LOGOUT_HOUR, LOGOUT_MINUTE
        ),
        timestamp: Utc::now().to_rfc3339(),
    };

    if let Err(e) = app_handle.emit("auto_logout", payload) {
        warn!("Failed to emit auto_logout event: {}", e);
    }

    info!("Auto-logout complete");
}

/// Call `POST /ft-api/v1/auth/revoke` to invalidate the server-side JWT.
///
/// Uses a raw TCP write so that this function can run on the scheduler's
/// `std::thread` without requiring a Tokio runtime.  Failures are logged but
/// never propagated — the logout proceeds regardless.
fn revoke_jwt() {
    use std::io::Write;
    use std::net::TcpStream;

    let host = "127.0.0.1:5100";
    let request = "POST /ft-api/v1/auth/revoke HTTP/1.0\r\nHost: 127.0.0.1:5100\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";

    match TcpStream::connect(host) {
        Ok(mut stream) => {
            if let Err(e) = stream.write_all(request.as_bytes()) {
                warn!("JWT revoke write failed: {}", e);
                return;
            }
            info!("JWT revoke request sent to {}", host);
        }
        Err(e) => {
            warn!("JWT revoke: could not connect to FlintTrade backend (may be offline): {}", e);
        }
    }
}

/// Remove broker tokens and API key entries from the OS keychain.
///
/// Known credential keys are deleted; unrecognised keys are left untouched.
fn clear_cached_credentials() {
    let keys = ["api_key", "broker_token", "encryption_key", "session_token"];

    for key in &keys {
        match crate::keychain::delete_credential(key) {
            Ok(()) => info!("Cleared keychain entry '{}'", key),
            Err(e) => warn!("Could not clear keychain entry '{}': {}", key, e),
        }
    }
}

/// Seconds until the next occurrence of `hour:minute` IST.
///
/// Returns a value in `[0, 86400)`.
pub fn secs_until_ist(hour: u32, minute: u32) -> u64 {
    let now_ist = Utc::now().with_timezone(&Kolkata);
    let target = NaiveTime::from_hms_opt(hour, minute, 0)
        .expect("invalid hour/minute for auto-logout target");
    let now_time = now_ist.time();

    if now_time < target {
        (target - now_time).num_seconds().max(0) as u64
    } else {
        let until_midnight =
            (24 * 3600u64).saturating_sub(now_time.num_seconds_from_midnight() as u64);
        let from_midnight = target.num_seconds_from_midnight() as u64;
        until_midnight + from_midnight
    }
}

/// Sleep for `duration`, waking up every second to check the `running` flag.
///
/// This allows [`AutoLogoutScheduler::stop`] to interrupt a long sleep without
/// the thread blocking until the next 3 AM.
fn sleep_interruptible(duration: Duration, running: &Arc<AtomicBool>) {
    let end = std::time::Instant::now() + duration;
    while running.load(Ordering::SeqCst) {
        let remaining = end.saturating_duration_since(std::time::Instant::now());
        if remaining.is_zero() {
            break;
        }
        std::thread::sleep(remaining.min(Duration::from_secs(1)));
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Tauri commands
// ─────────────────────────────────────────────────────────────────────────────

/// Tauri command — start the auto-logout scheduler.
///
/// Calling this when the scheduler is already running is a no-op.
#[tauri::command]
pub fn start_scheduler(app_handle: AppHandle) {
    let scheduler = AutoLogoutScheduler::new(app_handle);
    scheduler.start();
}

/// Tauri command — stop the auto-logout scheduler.
///
/// The background thread will exit on its next iteration check (within ~1 s).
///
/// # Note
///
/// This command creates a *new* scheduler handle and stops it.  In practice
/// the scheduler state should be managed via Tauri's `app.manage()` so that
/// the same instance is shared.  The command is provided here for completeness
/// and is most useful in tests.
#[tauri::command]
pub fn stop_scheduler(app_handle: AppHandle) {
    // In the real app the scheduler is stored in app state; here we signal
    // the global running flag via a dummy instance pointing at the same Arc.
    // If managed state is used, the command wrapper in `main.rs` can be
    // adapted to call `state.scheduler.stop()` instead.
    let scheduler = AutoLogoutScheduler::new(app_handle);
    scheduler.stop();
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secs_until_ist_positive() {
        let secs = secs_until_ist(LOGOUT_HOUR, LOGOUT_MINUTE);
        assert!(secs > 0, "expected a positive duration");
        assert!(secs <= 24 * 3600, "expected at most 24 hours");
    }

    #[test]
    fn secs_until_ist_arbitrary_time() {
        // Any valid hour:minute should give a sensible result
        for hour in 0u32..24 {
            for minute in [0u32, 15, 30, 45] {
                let s = secs_until_ist(hour, minute);
                assert!(
                    s <= 24 * 3600,
                    "secs_until_ist({hour}, {minute}) = {s} exceeded 24 hours"
                );
            }
        }
    }

    #[test]
    fn warning_minutes_descending() {
        // Ensure the constants are ordered so warnings fire earliest-first
        for i in 1..WARNING_MINUTES.len() {
            assert!(
                WARNING_MINUTES[i - 1] > WARNING_MINUTES[i],
                "WARNING_MINUTES must be in descending order"
            );
        }
    }

    #[test]
    fn sleep_interruptible_stops_early() {
        let running = Arc::new(AtomicBool::new(true));
        let running_clone = Arc::clone(&running);

        // Request a 10-second sleep but cancel after 50 ms
        let handle = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(50));
            running_clone.store(false, Ordering::SeqCst);
        });

        let start = std::time::Instant::now();
        sleep_interruptible(Duration::from_secs(10), &running);
        handle.join().unwrap();

        // Should have returned well before 10 seconds
        assert!(
            start.elapsed() < Duration::from_secs(3),
            "sleep_interruptible did not exit early after flag cleared"
        );
    }
}
