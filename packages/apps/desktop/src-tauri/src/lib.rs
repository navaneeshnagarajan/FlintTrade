//! FlintTrade Desktop — Tauri 2 shell.
//!
//! The desktop app is a thin native window around the bundled FlintTrade
//! backend. On launch it:
//!
//! 1. Provisions the credential-vault master password (first run only) into the
//!    hardened at-rest file the backend reads — honouring locked decision #13
//!    (the *shell* provides the secret; the backend never auto-generates one).
//! 2. Spawns the ``flinttrade-backend`` sidecar on an OS-chosen loopback port
//!    (``--port 0``) and waits for its ``FLINTTRADE_BACKEND_READY port=<n>``
//!    handshake on stdout.
//! 3. Opens the main window pointed at ``http://127.0.0.1:<n>`` — the backend
//!    serves both the React terminal and the API from that one origin, so the
//!    app's same-origin requests resolve without any in-app configuration.
//! 4. Kills the sidecar when the app exits.
//!
//! A small splash window covers steps 1–2 so the user sees immediate feedback.
//!
//! ## Background runtime (AI-trading desktop)
//!
//! FlintTrade runs an autonomous AI agent and live position monitoring, so the
//! backend must keep working when the window is closed. Closing the window
//! therefore HIDES it to the system tray instead of quitting; the sidecar (and
//! the agent) keep running. The app quits only from the tray "Quit" item. A
//! global hotkey (``CommandOrControl+Shift+F``) toggles the window, and the
//! backend can raise native OS notifications for fills / safety blocks / agent
//! turns by printing ``FLINTTRADE_NOTIFY\t<title>\t<body>`` on stdout — so
//! alerts reach the operator even while the window is hidden.

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::menu::{Menu, MenuEvent, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Stdout line the backend prints once its listening socket is bound.
const READY_SENTINEL: &str = "FLINTTRADE_BACKEND_READY";

/// Stdout prefix the backend prints to raise a native desktop notification.
/// Format: ``FLINTTRADE_NOTIFY\t<title>\t<body>`` (tab-delimited, one line).
const NOTIFY_SENTINEL: &str = "FLINTTRADE_NOTIFY";

/// Global hotkey (parsed cross-platform) that toggles the main window.
const TOGGLE_SHORTCUT: &str = "CommandOrControl+Shift+F";

/// Set to true once the operator chooses "Quit" from the tray, so the window's
/// close handler performs a real exit instead of hiding to tray.
struct QuitRequested(std::sync::atomic::AtomicBool);

/// Holds the spawned backend child so it can be killed on exit.
struct BackendState(Mutex<Option<CommandChild>>);

/// Build and run the FlintTrade desktop application.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .manage(BackendState(Mutex::new(None)))
        .manage(QuitRequested(std::sync::atomic::AtomicBool::new(false)))
        .setup(|app| {
            // First-run secret provisioning (best-effort; never blocks launch).
            provision_master_password();

            // Tray + global hotkey: the app lives in the background (agent +
            // monitoring keep running) and the operator can summon it anytime.
            if let Err(e) = build_tray(app.handle()) {
                eprintln!("[flinttrade] tray setup failed: {e}");
            }
            register_toggle_shortcut(app.handle());

            let handle = app.handle().clone();

            // Spawn the backend sidecar on an OS-chosen loopback port so the app
            // never collides with another local FlintTrade or service.
            // FLINTTRADE_DESKTOP=1 tells the backend it is running under the
            // desktop shell, so it may emit FLINTTRADE_NOTIFY stdout lines for
            // native notifications (a no-op under plain CLI/`make start`).
            let command = app
                .shell()
                .sidecar("flinttrade-backend")?
                .args(["--port", "0"])
                .env("FLINTTRADE_DESKTOP", "1");
            let (mut rx, child) = command.spawn()?;
            if let Some(state) = app.try_state::<BackendState>() {
                *state.0.lock().unwrap() = Some(child);
            }

            // Drain the sidecar's output: parse the ready handshake, surface
            // failures, and keep reading afterwards so the pipe never blocks the
            // backend's own logging.
            tauri::async_runtime::spawn(async move {
                let mut buffer = String::new();
                let mut shown = false;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let chunk = String::from_utf8_lossy(&bytes);
                            // Backend-emitted native notifications (fills, safety
                            // blocks, agent turns) — dispatched even while the
                            // window is hidden in the tray.
                            for line in chunk.lines() {
                                if let Some((title, body)) = parse_notify_line(line) {
                                    raise_notification(&handle, &title, &body);
                                }
                            }
                            if !shown {
                                buffer.push_str(&chunk);
                                if let Some(port) = parse_ready_port(&buffer) {
                                    shown = true;
                                    let h = handle.clone();
                                    let _ = handle.run_on_main_thread(move || show_main_window(&h, port));
                                }
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprint!("{}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[flinttrade] backend terminated: {payload:?}");
                            if !shown {
                                let h = handle.clone();
                                let _ = handle.run_on_main_thread(move || show_backend_error(&h));
                            }
                            break;
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[flinttrade] backend error: {err}");
                        }
                        _ => {}
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the FlintTrade desktop app")
        .run(|app_handle, event| match event {
            RunEvent::ExitRequested { .. } => {
                kill_backend(app_handle);
            }
            // macOS: clicking the dock icon while the window is hidden in the
            // tray brings it back, matching close-to-tray expectations.
            #[cfg(target_os = "macos")]
            RunEvent::Reopen { .. } => {
                show_and_focus_main(app_handle);
            }
            _ => {}
        });
}

/// Extract the bound port from an accumulated stdout buffer, if the ready
/// sentinel has been printed.
fn parse_ready_port(buffer: &str) -> Option<u16> {
    for line in buffer.lines() {
        if let Some(idx) = line.find(READY_SENTINEL) {
            if let Some(after) = line[idx..].split("port=").nth(1) {
                let digits: String = after.chars().take_while(|c| c.is_ascii_digit()).collect();
                if let Ok(port) = digits.parse::<u16>() {
                    return Some(port);
                }
            }
        }
    }
    None
}

/// Create the main window pointed at the backend, then close the splash.
fn show_main_window(app: &AppHandle, port: u16) {
    if app.get_webview_window("main").is_some() {
        return;
    }
    let url_str = format!("http://127.0.0.1:{port}/");
    let url = match tauri::Url::parse(&url_str) {
        Ok(u) => u,
        Err(e) => {
            eprintln!("[flinttrade] invalid backend url {url_str}: {e}");
            return;
        }
    };
    let result = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
        .title("FlintTrade")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .center()
        .build();
    match result {
        Ok(win) => {
            // Close-to-tray: hide the window instead of exiting so the backend —
            // and the autonomous AI agent + live position monitoring it runs —
            // keeps working in the background. A real quit only happens from the
            // tray "Quit" item (which sets QuitRequested).
            let app_for_close = app.clone();
            win.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    let quitting = app_for_close
                        .try_state::<QuitRequested>()
                        .map(|q| q.0.load(std::sync::atomic::Ordering::SeqCst))
                        .unwrap_or(false);
                    if !quitting {
                        api.prevent_close();
                        if let Some(w) = app_for_close.get_webview_window("main") {
                            let _ = w.hide();
                        }
                    }
                }
            });
            if let Some(splash) = app.get_webview_window("splash") {
                let _ = splash.close();
            }
        }
        Err(e) => eprintln!("[flinttrade] failed to create main window: {e}"),
    }
}

/// Show and focus the main window (create it lazily is not needed here — it is
/// built once the backend is ready; before that the tray/hotkey are no-ops for
/// the main window).
fn show_and_focus_main(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

/// Toggle the main window's visibility (global hotkey + tray double-click).
fn toggle_main_window(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        if win.is_visible().unwrap_or(false) {
            let _ = win.hide();
        } else {
            show_and_focus_main(app);
        }
    }
}

/// Build the system tray icon + menu (Show / Quit). Reuses the app's own icon.
fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "show", "Show FlintTrade", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit FlintTrade", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

    let mut builder = TrayIconBuilder::with_id("flinttrade-tray")
        .tooltip("FlintTrade")
        .menu(&menu)
        // Left-click toggles the window; the menu stays reachable via right-click.
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event: MenuEvent| match event.id().as_ref() {
            "show" => show_and_focus_main(app),
            "quit" => {
                if let Some(q) = app.try_state::<QuitRequested>() {
                    q.0.store(true, std::sync::atomic::Ordering::SeqCst);
                }
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                toggle_main_window(tray.app_handle());
            }
        });

    if let Some(icon) = app.default_window_icon().cloned() {
        builder = builder.icon(icon);
    }
    builder.build(app)?;
    Ok(())
}

/// Register the global hotkey that toggles the window from anywhere.
fn register_toggle_shortcut(app: &AppHandle) {
    use tauri_plugin_global_shortcut::GlobalShortcutExt;
    let shortcut: tauri_plugin_global_shortcut::Shortcut = match TOGGLE_SHORTCUT.parse() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[flinttrade] invalid toggle shortcut {TOGGLE_SHORTCUT:?}: {e}");
            return;
        }
    };
    let result = app.global_shortcut().on_shortcut(shortcut, |app, _sc, event| {
        if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
            toggle_main_window(app);
        }
    });
    if let Err(e) = result {
        eprintln!("[flinttrade] could not register global toggle shortcut: {e}");
    }
}

/// Raise a native OS notification.
fn raise_notification(app: &AppHandle, title: &str, body: &str) {
    let _ = app
        .notification()
        .builder()
        .title(title)
        .body(body)
        .show();
}

/// Parse a ``FLINTTRADE_NOTIFY\t<title>\t<body>`` stdout line into (title, body).
/// Returns ``None`` for any line that is not a well-formed notify sentinel.
fn parse_notify_line(line: &str) -> Option<(String, String)> {
    let rest = line.strip_prefix(NOTIFY_SENTINEL)?.strip_prefix('\t')?;
    let (title, body) = rest.split_once('\t')?;
    let title = title.trim();
    if title.is_empty() {
        return None;
    }
    Some((title.to_string(), body.trim().to_string()))
}

/// Update the splash to report that the backend failed to come up.
fn show_backend_error(app: &AppHandle) {
    if let Some(splash) = app.get_webview_window("splash") {
        let _ = splash.eval(
            "var s=document.getElementById('status');\
             if(s){s.textContent='Backend failed to start \\u2014 see logs.';s.style.color='#ff6a3d';}",
        );
    }
}

/// Kill the backend sidecar, if still running.
fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Some(child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

// ---------------------------------------------------------------------------
// Credential-vault master-password provisioning (first run only).
// ---------------------------------------------------------------------------

/// Resolve the FlintTrade workspace directory, mirroring
/// ``flinttrade_core.workspace._default_home`` so the secret lands where the
/// backend looks for it.
fn flinttrade_home() -> Option<PathBuf> {
    if let Some(d) = env_nonempty("FLINTTRADE_WORKSPACE_DIR") {
        return Some(PathBuf::from(d));
    }
    if let Some(d) = env_nonempty("FLINTTRADE_HOME") {
        return Some(PathBuf::from(d));
    }
    #[cfg(target_os = "windows")]
    {
        return env_nonempty("APPDATA").map(|a| PathBuf::from(a).join("flinttrade"));
    }
    #[cfg(target_os = "macos")]
    {
        return std::env::var_os("HOME")
            .map(|h| PathBuf::from(h).join("Library").join("Application Support").join("flinttrade"));
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        return std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".flinttrade"));
    }
    #[allow(unreachable_code)]
    None
}

/// Return an environment variable's value only when set and non-empty.
fn env_nonempty(key: &str) -> Option<String> {
    match std::env::var(key) {
        Ok(v) if !v.is_empty() => Some(v),
        _ => None,
    }
}

/// Provision the credential-vault master password on first run.
///
/// Generates a 256-bit random secret and writes it to the backend's supported
/// hardened at-rest file. Never overwrites an existing secret (e.g. one a CLI
/// `make start` provisioned via TTY). This honours locked decision #13: the
/// secret is supplied by the operator-controlled shell, not auto-generated by
/// the backend, and lives only in the owner-only workspace file.
fn provision_master_password() {
    let Some(dir) = flinttrade_home() else {
        eprintln!("[flinttrade] could not resolve workspace dir; backend may prompt for a master password");
        return;
    };
    if let Err(e) = std::fs::create_dir_all(&dir) {
        eprintln!("[flinttrade] could not create {}: {e}", dir.display());
        return;
    }
    let pw_file = dir.join("master_password");
    if let Ok(meta) = std::fs::metadata(&pw_file) {
        if meta.len() > 0 {
            return; // already provisioned — never clobber
        }
    }
    let mut bytes = [0u8; 32];
    if let Err(e) = getrandom::getrandom(&mut bytes) {
        eprintln!("[flinttrade] RNG failure provisioning master password: {e}");
        return;
    }
    if let Err(e) = std::fs::write(&pw_file, to_hex(&bytes).as_bytes()) {
        eprintln!("[flinttrade] could not write master_password: {e}");
        return;
    }
    harden_file(&pw_file);
}

/// Lower-case hex encoding (no external crate).
fn to_hex(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        s.push_str(&format!("{b:02x}"));
    }
    s
}

#[cfg(unix)]
fn harden_file(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn harden_file(_path: &Path) {
    // On Windows the file lives under the user-scoped %APPDATA%\flinttrade; the
    // backend's secure_file.harden tightens the ACL further on first use.
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_ready_handshake() {
        let buf = "starting...\nFLINTTRADE_BACKEND_READY port=56576\nmore logs\n";
        assert_eq!(parse_ready_port(buf), Some(56576));
    }

    #[test]
    fn ignores_partial_buffer_without_sentinel() {
        assert_eq!(parse_ready_port("still booting, no handshake yet\n"), None);
    }

    #[test]
    fn parses_default_port() {
        assert_eq!(parse_ready_port("FLINTTRADE_BACKEND_READY port=5100"), Some(5100));
    }

    #[test]
    fn handles_trailing_text_after_port() {
        assert_eq!(parse_ready_port("FLINTTRADE_BACKEND_READY port=8080 extra"), Some(8080));
    }

    #[test]
    fn hex_encoding_is_lowercase_and_fixed_width() {
        assert_eq!(to_hex(&[0x00, 0x0f, 0xff, 0xa0]), "000fffa0");
    }

    #[test]
    fn parses_well_formed_notify_line() {
        let line = "FLINTTRADE_NOTIFY\tOrder filled\tRELIANCE BUY 10 @ 2900";
        assert_eq!(
            parse_notify_line(line),
            Some(("Order filled".to_string(), "RELIANCE BUY 10 @ 2900".to_string()))
        );
    }

    #[test]
    fn notify_line_allows_empty_body() {
        assert_eq!(
            parse_notify_line("FLINTTRADE_NOTIFY\tKill switch armed\t"),
            Some(("Kill switch armed".to_string(), String::new()))
        );
    }

    #[test]
    fn rejects_non_notify_or_malformed_lines() {
        assert_eq!(parse_notify_line("FLINTTRADE_BACKEND_READY port=5100"), None);
        assert_eq!(parse_notify_line("FLINTTRADE_NOTIFY no tabs here"), None);
        assert_eq!(parse_notify_line("FLINTTRADE_NOTIFY\t\tbody only"), None);
        assert_eq!(parse_notify_line("random log line"), None);
    }
}
