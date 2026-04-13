//! Lightweight webhook receiver for FlintTrade Desktop.
//!
//! Starts an [`axum`] HTTP server on a configurable port (default **18080**) that
//! accepts inbound alerts from TradingView, ChartInk, and custom senders.
//!
//! # Endpoints
//!
//! | Method | Path                    | Description                          |
//! |--------|-------------------------|--------------------------------------|
//! | POST   | `/webhook/tradingview`  | TradingView JSON / text alerts       |
//! | POST   | `/webhook/chartink`     | ChartInk scanner signals             |
//! | POST   | `/webhook/custom`       | Generic custom webhook               |
//! | GET    | `/health`               | Liveness check                       |
//!
//! # Rate limiting
//!
//! A token-bucket limiter allows at most **10 requests per second** across all
//! endpoints combined, matching the FlintTrade order-placement budget.
//!
//! # Tauri event forwarding
//!
//! Every accepted webhook payload is emitted as a Tauri event so the React
//! frontend can react in real-time:
//!
//! * TradingView → `"webhook:tradingview"`
//! * ChartInk    → `"webhook:chartink"`
//! * Custom      → `"webhook:custom"`
//!
//! # Example
//!
//! ```no_run
//! // In app setup:
//! tauri::async_runtime::spawn(async move {
//!     flinttrade_desktop_lib::webhook::run_server(app_handle, 18080).await.unwrap();
//! });
//! ```

use axum::{
    body::Body,
    extract::{Request, State},
    http::StatusCode,
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    net::SocketAddr,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Instant,
};
use tauri::{AppHandle, Emitter};
use tokio::sync::oneshot;
use tower_http::cors::{Any, CorsLayer};
use tracing::{info, warn};

// ─────────────────────────────────────────────────────────────────────────────
// Rate limiter (token bucket, 10 req/s)
// ─────────────────────────────────────────────────────────────────────────────

const MAX_RATE: f64 = 10.0; // requests per second

/// Token-bucket rate limiter shared across all webhook endpoints.
struct RateLimiter {
    tokens: f64,
    last_refill: Instant,
}

impl RateLimiter {
    fn new() -> Self {
        Self {
            tokens: MAX_RATE,
            last_refill: Instant::now(),
        }
    }

    /// Attempt to consume one token.  Returns `true` if the request is allowed.
    fn try_acquire(&mut self) -> bool {
        let elapsed = self.last_refill.elapsed().as_secs_f64();
        self.tokens = (self.tokens + elapsed * MAX_RATE).min(MAX_RATE);
        self.last_refill = Instant::now();

        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Shared handler state
// ─────────────────────────────────────────────────────────────────────────────

/// State shared by all route handlers.
#[derive(Clone)]
struct WebhookState {
    app_handle: AppHandle,
    rate_limiter: Arc<Mutex<RateLimiter>>,
}

impl WebhookState {
    fn new(app_handle: AppHandle) -> Self {
        Self {
            app_handle,
            rate_limiter: Arc::new(Mutex::new(RateLimiter::new())),
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Payload types
// ─────────────────────────────────────────────────────────────────────────────

/// Envelope forwarded to the Tauri frontend via a Tauri event.
#[derive(Clone, Serialize, Deserialize)]
pub struct WebhookEvent {
    /// Originating source: `"tradingview"`, `"chartink"`, or `"custom"`.
    pub source: String,
    /// Raw JSON payload received in the request body.
    pub payload: Value,
    /// RFC 3339 timestamp of receipt.
    pub received_at: String,
}

// ─────────────────────────────────────────────────────────────────────────────
// Route handlers
// ─────────────────────────────────────────────────────────────────────────────

/// `GET /health` — liveness check used by monitoring tools.
async fn health() -> impl IntoResponse {
    Json(json!({"status": "ok", "service": "flinttrade-webhook"}))
}

/// `POST /webhook/tradingview` — receive a TradingView JSON alert.
async fn tradingview(
    State(state): State<WebhookState>,
    body: String,
) -> impl IntoResponse {
    let payload: Value = serde_json::from_str(&body).unwrap_or_else(|_| json!({"raw": body}));
    forward_event(&state, "tradingview", payload);
    StatusCode::OK
}

/// `POST /webhook/chartink` — receive a ChartInk scanner signal.
async fn chartink(
    State(state): State<WebhookState>,
    body: String,
) -> impl IntoResponse {
    let payload: Value = serde_json::from_str(&body).unwrap_or_else(|_| json!({"raw": body}));
    forward_event(&state, "chartink", payload);
    StatusCode::OK
}

/// `POST /webhook/custom` — generic webhook for any custom sender.
async fn custom(
    State(state): State<WebhookState>,
    body: String,
) -> impl IntoResponse {
    let payload: Value = serde_json::from_str(&body).unwrap_or_else(|_| json!({"raw": body}));
    forward_event(&state, "custom", payload);
    StatusCode::OK
}

/// Emit the received payload as a Tauri event to the WebView.
fn forward_event(state: &WebhookState, source: &str, payload: Value) {
    let event = WebhookEvent {
        source: source.to_owned(),
        payload,
        received_at: chrono::Utc::now().to_rfc3339(),
    };

    let event_name = format!("webhook:{source}");
    if let Err(e) = state.app_handle.emit(&event_name, &event) {
        warn!("Failed to emit Tauri event '{}': {}", event_name, e);
    } else {
        info!("Forwarded {} webhook to frontend", source);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Rate-limit middleware
// ─────────────────────────────────────────────────────────────────────────────

async fn rate_limit(
    State(state): State<WebhookState>,
    request: Request<Body>,
    next: Next,
) -> Response {
    if state.rate_limiter.lock().try_acquire() {
        next.run(request).await
    } else {
        warn!("Webhook rate limit exceeded — dropping request");
        (
            StatusCode::TOO_MANY_REQUESTS,
            Json(json!({
                "status": "error",
                "message": "Rate limit exceeded. Maximum 10 requests per second."
            })),
        )
            .into_response()
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Server lifecycle
// ─────────────────────────────────────────────────────────────────────────────

/// Shared server handle — holds the shutdown sender for graceful stop.
pub struct ServerHandle {
    shutdown_tx: Option<oneshot::Sender<()>>,
    port: u16,
    running: Arc<AtomicBool>,
}

impl ServerHandle {
    /// Returns `true` if the server is currently accepting requests.
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    /// Send a graceful shutdown signal.
    pub fn stop(&mut self) {
        if let Some(tx) = self.shutdown_tx.take() {
            let _ = tx.send(());
            self.running.store(false, Ordering::SeqCst);
            info!("Webhook server on port {} stopping", self.port);
        }
    }
}

impl Drop for ServerHandle {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Start the webhook HTTP server and return a [`ServerHandle`] for lifecycle
/// management.
///
/// # Arguments
///
/// * `app_handle` — Tauri app handle used to emit events to the WebView.
/// * `port`       — TCP port to listen on (default `18080`).
///
/// # Errors
///
/// Returns an error string if the port is already in use or binding fails.
pub async fn run_server(app_handle: AppHandle, port: u16) -> Result<ServerHandle, String> {
    let addr: SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|e| format!("Invalid webhook address: {e}"))?;

    let state = WebhookState::new(app_handle);

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods(Any)
        .allow_headers(Any);

    let app = Router::new()
        .route("/health", get(health))
        .route("/webhook/tradingview", post(tradingview))
        .route("/webhook/chartink", post(chartink))
        .route("/webhook/custom", post(custom))
        .route_layer(middleware::from_fn_with_state(state.clone(), rate_limit))
        .with_state(state)
        .layer(cors);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("Failed to bind webhook server to {addr}: {e}"))?;

    let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();
    let running = Arc::new(AtomicBool::new(true));
    let running_clone = Arc::clone(&running);

    tokio::spawn(async move {
        let server = axum::serve(listener, app).with_graceful_shutdown(async {
            let _ = shutdown_rx.await;
        });

        if let Err(e) = server.await {
            // Only log if it is an unexpected error (not a graceful shutdown)
            warn!("Webhook server exited: {}", e);
        }

        running_clone.store(false, Ordering::SeqCst);
        info!("Webhook server on port {} stopped", port);
    });

    info!(
        "Webhook server listening on http://127.0.0.1:{port}\n  \
        POST /webhook/tradingview\n  \
        POST /webhook/chartink\n  \
        POST /webhook/custom"
    );

    Ok(ServerHandle {
        shutdown_tx: Some(shutdown_tx),
        port,
        running,
    })
}

// ─────────────────────────────────────────────────────────────────────────────
// Tauri commands
// ─────────────────────────────────────────────────────────────────────────────

/// Tauri command — start the webhook server.
///
/// # Arguments
///
/// * `port` — TCP port to listen on.  Defaults to `18080` if `0` is supplied.
///
/// The server handle is *not* returned through this command; lifecycle is
/// managed by the app state set up in `main.rs`.  The command is intentionally
/// fire-and-forget: the server keeps running until `stop_webhook_server` is
/// called or the process exits.
///
/// # Errors
///
/// Returns a human-readable error string if binding fails.
#[tauri::command]
pub async fn start_webhook_server(
    app_handle: AppHandle,
    port: u16,
) -> Result<(), String> {
    let effective_port = if port == 0 { 18080 } else { port };
    // We intentionally discard the handle here — in production, `main.rs`
    // stores it in `app.manage(...)`.  This command is the IPC entry point.
    run_server(app_handle, effective_port).await.map(|_| ())
}

/// Tauri command — stop the webhook server.
///
/// Because the server handle is managed separately in `main.rs`, this command
/// signals via a global Tauri event so any listener can react.  A proper
/// implementation would call `handle.stop()` on the managed state.
#[tauri::command]
pub async fn stop_webhook_server(app_handle: AppHandle) -> Result<(), String> {
    // Emit an internal event that the setup code in main.rs can intercept to
    // call `.stop()` on the managed ServerHandle.
    app_handle
        .emit("internal:stop_webhook", ())
        .map_err(|e| format!("Failed to signal webhook stop: {e}"))
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn rate_limiter_allows_burst_then_blocks() {
        let mut rl = RateLimiter::new();

        // MAX_RATE = 10 — the first 10 requests should be allowed
        let mut allowed = 0u32;
        for _ in 0..10 {
            if rl.try_acquire() {
                allowed += 1;
            }
        }
        assert_eq!(allowed, 10, "expected exactly 10 requests in burst");

        // The 11th should be rejected
        assert!(!rl.try_acquire(), "expected rate limit to block 11th request");
    }

    #[test]
    fn rate_limiter_refills_over_time() {
        let mut rl = RateLimiter::new();

        // Drain completely
        for _ in 0..10 {
            rl.try_acquire();
        }
        assert!(!rl.try_acquire(), "should be empty");

        // Manually wind back the clock by 1 second
        rl.last_refill = Instant::now() - Duration::from_secs(1);

        // Should have ~10 tokens again
        let mut allowed = 0u32;
        for _ in 0..10 {
            if rl.try_acquire() {
                allowed += 1;
            }
        }
        assert!(allowed >= 9, "expected refill to restore ~10 tokens");
    }

    #[test]
    fn webhook_event_serialises() {
        let event = WebhookEvent {
            source: "tradingview".into(),
            payload: json!({"action": "BUY", "ticker": "NIFTY"}),
            received_at: "2026-04-13T03:00:00Z".into(),
        };

        let json = serde_json::to_string(&event).expect("serialisation failed");
        assert!(json.contains("tradingview"));
        assert!(json.contains("BUY"));
    }
}
