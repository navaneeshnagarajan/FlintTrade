//! FlintTrade Desktop — Tauri backend library.
//!
//! Exposes the three core native capabilities:
//!
//! * [`keychain`]  — OS credential storage (Windows Credential Manager /
//!                   macOS Keychain / libsecret).
//! * [`scheduler`] — Daily 3:00 AM IST auto-logout scheduler.
//! * [`webhook`]   — Lightweight HTTP server that receives TradingView,
//!                   ChartInk, and custom webhook alerts.
//!
//! The [`run`] function is the single entry-point called from `main.rs`.

pub mod keychain;
pub mod scheduler;
pub mod webhook;

use scheduler::AutoLogoutScheduler;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

/// Initialise and run the Tauri application.
///
/// Called from `main.rs`.  Registers all Tauri IPC commands, starts the
/// auto-logout scheduler, and optionally starts the webhook server.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Initialise structured logging.  Respects the `RUST_LOG` env variable;
    // defaults to `info` for the app and `warn` for Tauri internals.
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "flinttrade_desktop_lib=info,tauri=warn".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    tracing::info!("Starting FlintTrade Desktop v{}", env!("CARGO_PKG_VERSION"));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        // ── App lifecycle ────────────────────────────────────────────────────
        .setup(|app| {
            let handle = app.handle().clone();

            // Start the daily 3:00 AM IST auto-logout scheduler.
            let scheduler = AutoLogoutScheduler::new(handle.clone());
            scheduler.start();
            tracing::info!("Auto-logout scheduler started");

            // Start the webhook server on the default port.
            // The ServerHandle is stored in Tauri managed state so that
            // `stop_webhook_server` can shut it down gracefully.
            let handle_for_webhook = handle.clone();
            tauri::async_runtime::spawn(async move {
                match webhook::run_server(handle_for_webhook, 18080).await {
                    Ok(server_handle) => {
                        // Make the handle available to other parts of the app.
                        // Using a Mutex<Option<...>> so the stop command can take it.
                        // (In a production app, define a proper AppState struct.)
                        drop(server_handle); // TODO: store in managed state
                        tracing::info!("Webhook server started on port 18080");
                    }
                    Err(e) => {
                        tracing::warn!("Webhook server failed to start: {}", e);
                    }
                }
            });

            Ok(())
        })
        // ── IPC command handlers ─────────────────────────────────────────────
        .invoke_handler(tauri::generate_handler![
            // Keychain
            keychain::cmd_store_credential,
            keychain::cmd_get_credential,
            keychain::cmd_delete_credential,
            // Scheduler
            scheduler::start_scheduler,
            scheduler::stop_scheduler,
            // Webhook server
            webhook::start_webhook_server,
            webhook::stop_webhook_server,
        ])
        .run(tauri::generate_context!())
        .expect("error while running FlintTrade Desktop");
}
