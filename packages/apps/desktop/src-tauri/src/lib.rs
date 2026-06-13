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

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Stdout line the backend prints once its listening socket is bound.
const READY_SENTINEL: &str = "FLINTTRADE_BACKEND_READY";

/// Holds the spawned backend child so it can be killed on exit.
struct BackendState(Mutex<Option<CommandChild>>);

/// Build and run the FlintTrade desktop application.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(BackendState(Mutex::new(None)))
        .setup(|app| {
            // First-run secret provisioning (best-effort; never blocks launch).
            provision_master_password();

            let handle = app.handle().clone();

            // Spawn the backend sidecar on an OS-chosen loopback port so the app
            // never collides with another local FlintTrade or service.
            let command = app.shell().sidecar("flinttrade-backend")?.args(["--port", "0"]);
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
                            if !shown {
                                buffer.push_str(&String::from_utf8_lossy(&bytes));
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
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                kill_backend(app_handle);
            }
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
            // Closing the main window quits the app (and so kills the backend),
            // matching single-window desktop expectations on macOS too.
            let app_for_close = app.clone();
            win.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { .. } = event {
                    app_for_close.exit(0);
                }
            });
            if let Some(splash) = app.get_webview_window("splash") {
                let _ = splash.close();
            }
        }
        Err(e) => eprintln!("[flinttrade] failed to create main window: {e}"),
    }
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
}
