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
//! ## Sidecar orphan protection
//!
//! The kill-on-exit path (4) only runs on a graceful quit. A shell crash or
//! force-quit would otherwise orphan the backend, and repeated launches would
//! accumulate duplicates. Three layers close that hole:
//!
//! * **Reap on launch** — the shell records the sidecar PID (plus its own) in
//!   ``desktop_backend.pid`` under the workspace dir. On startup a stale entry
//!   from a crashed run is terminated, but only after an identity check that
//!   the PID still belongs to our ``flinttrade-backend`` binary — a reused PID
//!   owned by any other process is never killed.
//! * **Parent-liveness watchdog** — the shell passes its PID via
//!   ``FLINTTRADE_PARENT_PID``; the sidecar entry script
//!   (``packaging/desktop_backend.py``) watches that process from a daemon
//!   thread and exits cleanly when the shell dies.
//! * **Kill on exit** — the original graceful path, kept as-is.
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

/// Workspace-dir file recording the sidecar PID (line 1) and the owning shell
/// PID (line 2) so a later launch can reap an orphan from a crashed run.
const SIDECAR_PID_FILE: &str = "desktop_backend.pid";

/// Substring that must appear in a process's command line / image name before
/// the reaper will treat it as our backend sidecar and terminate it.
const SIDECAR_PROCESS_MARKER: &str = "flinttrade-backend";

/// File name of the platform's bootstrap install/update script inside the
/// source workspace (``scripts/install/``).
#[cfg(windows)]
const INSTALL_SCRIPT_NAME: &str = "flinttrade-install.ps1";
#[cfg(not(windows))]
const INSTALL_SCRIPT_NAME: &str = "flinttrade-install.sh";

/// Log file (under the workspace dir) capturing the detached self-update
/// build's output, since the spawning app exits while the build runs. On
/// Windows the build runs in its own console window instead.
#[cfg(unix)]
const SELF_UPDATE_LOG: &str = "self_update.log";

/// Set to true once the operator chooses "Quit" from the tray, so the window's
/// close handler performs a real exit instead of hiding to tray.
struct QuitRequested(std::sync::atomic::AtomicBool);

/// Holds the spawned backend child so it can be killed on exit.
struct BackendState(Mutex<Option<CommandChild>>);

// ---------------------------------------------------------------------------
// In-app updater (Hermes-style: rebuild from source on this machine).
//
// The bootstrap installers (scripts/install/flinttrade-install.{sh,ps1}) fetch
// the newest GitHub v* tag into a source workspace and rebuild/reinstall the
// app. These two commands let the terminal drive that flow from Settings →
// Updates: report where (and whether) the workspace exists, then run the
// LOCAL script detached so it survives this process exiting. No remote code
// is ever fetched or executed from Rust — only the script already present in
// the workspace on disk.
// ---------------------------------------------------------------------------

/// Payload of the ``updater_state`` command.
#[derive(serde::Serialize)]
struct UpdaterState {
    /// Version of the running app, from the Tauri package metadata.
    app_version: String,
    /// Resolved source workspace containing the install script, or ``None``
    /// when no usable workspace exists (the UI then shows the website
    /// one-liner to copy instead of the in-app rebuild button).
    src_dir: Option<String>,
}

/// Resolve the bootstrap source workspace, mirroring the install scripts:
/// ``FLINTTRADE_SRC_DIR`` when set, else ``~/.flinttrade/src/FlintTrade``
/// (``%USERPROFILE%`` on Windows). Returns it only when the platform's
/// install script actually exists inside it.
fn resolve_source_workspace() -> Option<PathBuf> {
    let dir = match env_nonempty("FLINTTRADE_SRC_DIR") {
        Some(d) => PathBuf::from(d),
        None => {
            #[cfg(windows)]
            let home = env_nonempty("USERPROFILE").or_else(|| env_nonempty("HOME"))?;
            #[cfg(not(windows))]
            let home = env_nonempty("HOME")?;
            PathBuf::from(home).join(".flinttrade").join("src").join("FlintTrade")
        }
    };
    if install_script_path(&dir).is_file() {
        Some(dir)
    } else {
        None
    }
}

/// Path of the platform's install script inside a source workspace.
fn install_script_path(src_dir: &Path) -> PathBuf {
    src_dir.join("scripts").join("install").join(INSTALL_SCRIPT_NAME)
}

/// Report the running app version and the resolved source workspace (if any)
/// to the terminal's Settings → Updates section.
#[tauri::command]
fn updater_state(app: AppHandle) -> UpdaterState {
    UpdaterState {
        app_version: app.package_info().version.to_string(),
        src_dir: resolve_source_workspace().map(|d| d.display().to_string()),
    }
}

/// Kick off a self-update: spawn the LOCAL bootstrap script detached (so the
/// rebuild survives this app exiting), then schedule a graceful exit ~2s
/// later so the build can replace the installed bundle. The script itself
/// relaunches the app once the new build is installed (no ``--no-launch``).
#[tauri::command]
fn run_self_update(app: AppHandle) -> Result<(), String> {
    let Some(src_dir) = resolve_source_workspace() else {
        return Err(
            "No source workspace found on this machine — run the bootstrap installer from the website first."
                .to_string(),
        );
    };
    let script = install_script_path(&src_dir);
    spawn_detached_updater(&script, &src_dir)
        .map_err(|e| format!("Could not start the update script: {e}"))?;

    // Mark the quit as deliberate (close-to-tray must not intercept it), then
    // exit shortly so the updater can replace the bundle underneath us.
    if let Some(q) = app.try_state::<QuitRequested>() {
        q.0.store(true, std::sync::atomic::Ordering::SeqCst);
    }
    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(2));
        let h = handle.clone();
        let _ = handle.run_on_main_thread(move || h.exit(0));
    });
    Ok(())
}

/// Open (create/append) the self-update log file under the workspace dir.
#[cfg(unix)]
fn self_update_log_file() -> Option<std::fs::File> {
    let dir = flinttrade_home()?;
    std::fs::create_dir_all(&dir).ok()?;
    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(dir.join(SELF_UPDATE_LOG))
        .ok()
}

/// PATH for the detached build, extended with the standard user-local tool
/// directories. GUI-launched apps on macOS/Linux inherit a minimal PATH
/// (no shell profile), which would hide the very toolchain (cargo, uv, pnpm,
/// node) the install script needs.
#[cfg(unix)]
fn augmented_path() -> String {
    let mut parts: Vec<String> = std::env::var("PATH")
        .unwrap_or_default()
        .split(':')
        .filter(|p| !p.is_empty())
        .map(str::to_string)
        .collect();
    let mut extras = vec![PathBuf::from("/usr/local/bin"), PathBuf::from("/opt/homebrew/bin")];
    if let Some(home) = std::env::var_os("HOME") {
        let home = PathBuf::from(home);
        extras.push(home.join(".cargo").join("bin"));
        extras.push(home.join(".local").join("bin"));
    }
    for extra in extras {
        let candidate = extra.display().to_string();
        if !parts.iter().any(|p| p == &candidate) {
            parts.push(candidate);
        }
    }
    parts.join(":")
}

/// Spawn the update script fully detached from this process (unix): its own
/// process group, no inherited stdio pipes, output appended to the workspace
/// log file. ``--update`` WITHOUT ``--no-launch`` — the script relaunches the
/// freshly built app itself. ``FLINTTRADE_YES=1`` consents to user-local tool
/// installs (uv/pnpm) since the detached script has no TTY to ask on.
#[cfg(unix)]
fn spawn_detached_updater(script: &Path, src_dir: &Path) -> std::io::Result<()> {
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;

    let (out, err) = match self_update_log_file() {
        Some(f) => {
            let clone = f.try_clone();
            (Stdio::from(f), clone.map(Stdio::from).unwrap_or_else(|_| Stdio::null()))
        }
        None => (Stdio::null(), Stdio::null()),
    };
    let mut cmd = std::process::Command::new("bash");
    cmd.arg(script)
        .arg("--update")
        .env("FLINTTRADE_YES", "1")
        .env("PATH", augmented_path())
        .current_dir(src_dir)
        .stdin(Stdio::null())
        .stdout(out)
        .stderr(err)
        // New process group: the script survives this app's exit and any
        // group-targeted signals sent to us on the way down.
        .process_group(0);
    cmd.spawn().map(|_| ())
}

/// Spawn the update script detached (Windows): its own console + process
/// group, so the PowerShell build keeps running — and shows progress — after
/// this app exits. ``FLINTTRADE_YES=1`` consents to user-local tool installs.
#[cfg(windows)]
fn spawn_detached_updater(script: &Path, src_dir: &Path) -> std::io::Result<()> {
    use std::os::windows::process::CommandExt;
    const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

    std::process::Command::new("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(script)
        .env("FLINTTRADE_YES", "1")
        .current_dir(src_dir)
        .creation_flags(CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP)
        .spawn()
        .map(|_| ())
}

/// Build and run the FlintTrade desktop application.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        // System-browser opener for broker OAuth approval pages — the main
        // window's remote (loopback HTTP) origin is granted exactly the
        // ``opener:allow-open-url`` permission, scoped to https URLs, in
        // ``capabilities/main-remote.json``.
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        // In-app updater commands (Settings → Updates). Like the opener above,
        // the remote main window only reaches these via the explicit
        // ``allow-updater-state`` / ``allow-run-self-update`` entries in
        // ``capabilities/main-remote.json`` (autogenerated by build.rs).
        .invoke_handler(tauri::generate_handler![updater_state, run_self_update])
        .manage(BackendState(Mutex::new(None)))
        .manage(QuitRequested(std::sync::atomic::AtomicBool::new(false)))
        .setup(|app| {
            // First-run secret provisioning (best-effort; never blocks launch).
            provision_master_password();

            // Orphan-protection layer 1: terminate an identity-checked stale
            // sidecar left behind by a crashed or force-quit previous run.
            reap_stale_sidecar();

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
                .env("FLINTTRADE_DESKTOP", "1")
                // Orphan-protection layer 2: the sidecar entry script watches
                // this PID and exits cleanly when the shell dies.
                .env("FLINTTRADE_PARENT_PID", std::process::id().to_string());
            let (mut rx, child) = command.spawn()?;
            // Orphan-protection layer 3: record the sidecar PID so the *next*
            // launch can reap it if this shell dies without running its
            // kill-on-exit cleanup.
            write_sidecar_pid_file(child.pid());
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
                            // The recorded PID is now dead — drop the file so a
                            // later launch never inspects a reused PID.
                            remove_sidecar_pid_file();
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

/// Whether an in-webview navigation target may load in the privileged main
/// window.
///
/// Only the backend's own http(s) origin (scheme + host + port) is allowed —
/// that is the origin the `main-remote` capability scopes the privileged
/// desktop commands to. Non-http schemes (`blob:`, `data:`, `about:`) never
/// match the capability's `http://127.0.0.1:*` allowlist, so they carry no
/// privileged commands and stay permitted (SPA downloads, workers, PDF views).
/// Any cross-origin http(s) navigation is refused.
fn navigation_allowed(
    target: &tauri::Url,
    backend_scheme: &str,
    backend_host: Option<&str>,
    backend_port: Option<u16>,
) -> bool {
    let same_origin = target.scheme() == backend_scheme
        && target.host_str() == backend_host
        && target.port() == backend_port;
    let privileged_scheme = matches!(target.scheme(), "http" | "https");
    same_origin || !privileged_scheme
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
    // Capture the backend's exact origin so in-webview navigation can be
    // confined to it (see the on_navigation guard below).
    let backend_scheme = url.scheme().to_string();
    let backend_host = url.host_str().map(str::to_string);
    let backend_port = url.port();
    let result = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.clone()))
        .title("FlintTrade")
        .inner_size(1440.0, 900.0)
        .min_inner_size(960.0, 640.0)
        .center()
        .on_navigation(move |target| {
            // Confine the webview to the backend's OWN loopback origin. The main
            // window carries the `main-remote` capability, which grants the
            // privileged desktop commands (run_self_update, updater_state) plus
            // the opener to any `http://127.0.0.1:*` origin. Without this guard a
            // navigation or redirect to a DIFFERENT loopback origin (a second
            // local HTTP service) would inherit those commands and could trigger
            // an unattended local build/exec. External links (broker OAuth) open
            // in the system browser via the opener, not in-webview, so this does
            // not break them.
            let allow = navigation_allowed(
                target,
                &backend_scheme,
                backend_host.as_deref(),
                backend_port,
            );
            if !allow {
                eprintln!("[flinttrade] blocked in-webview navigation to non-backend origin: {target}");
            }
            allow
        })
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
    remove_sidecar_pid_file();
}

// ---------------------------------------------------------------------------
// Sidecar orphan protection (PID file + identity-checked reaping).
// ---------------------------------------------------------------------------

/// Path of the sidecar PID file inside the workspace dir.
fn sidecar_pid_file() -> Option<PathBuf> {
    flinttrade_home().map(|d| d.join(SIDECAR_PID_FILE))
}

/// Serialise the PID file: line 1 = sidecar PID, line 2 = owning shell PID.
fn format_pid_file(sidecar_pid: u32, shell_pid: u32) -> String {
    format!("{sidecar_pid}\n{shell_pid}\n")
}

/// Parse a PID file written by [`format_pid_file`].
///
/// Returns ``(sidecar_pid, shell_pid)``; the shell PID is ``None`` for a
/// single-line file. Any malformed first line yields ``None``.
fn parse_pid_file(contents: &str) -> Option<(u32, Option<u32>)> {
    let mut lines = contents.lines();
    let sidecar = lines.next()?.trim().parse::<u32>().ok().filter(|p| *p > 0)?;
    let shell = lines
        .next()
        .and_then(|l| l.trim().parse::<u32>().ok())
        .filter(|p| *p > 0);
    Some((sidecar, shell))
}

/// True when a process command line / image name identifies our sidecar.
fn looks_like_backend_sidecar(command_line: &str) -> bool {
    command_line.contains(SIDECAR_PROCESS_MARKER)
}

/// Return the command line (unix `ps`) for a PID, or ``None`` when no such
/// process exists.
#[cfg(unix)]
fn process_command_line(pid: u32) -> Option<String> {
    let out = std::process::Command::new("ps")
        .args(["-p", &pid.to_string(), "-o", "args="])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if text.is_empty() {
        None
    } else {
        Some(text)
    }
}

/// Return the `tasklist` CSV row (image name + PID) for a PID, or ``None``
/// when no such process exists.
#[cfg(windows)]
fn process_command_line(pid: u32) -> Option<String> {
    let out = std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&out.stdout).to_string();
    // A match prints a quoted CSV row; a miss prints an ``INFO:`` line.
    let needle = format!("\"{pid}\"");
    text.lines().find(|l| l.contains(&needle)).map(str::to_string)
}

/// Best-effort liveness probe for an arbitrary PID.
#[cfg(unix)]
fn process_alive(pid: u32) -> bool {
    std::process::Command::new("kill")
        .args(["-0", &pid.to_string()])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Best-effort liveness probe for an arbitrary PID.
#[cfg(windows)]
fn process_alive(pid: u32) -> bool {
    process_command_line(pid).is_some()
}

/// Terminate a process: graceful TERM first, escalating to a hard kill only
/// if it lingers past a short grace window.
#[cfg(unix)]
fn terminate_process(pid: u32) {
    let pid_s = pid.to_string();
    let _ = std::process::Command::new("kill").args(["-TERM", &pid_s]).status();
    for _ in 0..20 {
        if !process_alive(pid) {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    let _ = std::process::Command::new("kill").args(["-KILL", &pid_s]).status();
}

/// Terminate a process (Windows `taskkill`, including its child tree).
#[cfg(windows)]
fn terminate_process(pid: u32) {
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status();
}

/// Startup layer of orphan protection.
///
/// If a previous shell run crashed or was force-quit, its kill-on-exit path
/// never ran and the sidecar keeps serving. Read the PID file it left behind
/// and terminate that sidecar — but only after two safety checks:
///
/// * the shell recorded as its owner is no longer alive (a live shell means a
///   second FlintTrade instance is running; killing its backend would be far
///   worse than tolerating a duplicate), and
/// * the PID's current command line still identifies our
///   ``flinttrade-backend`` binary — a reused PID belonging to any other
///   process is never killed.
fn reap_stale_sidecar() {
    let Some(path) = sidecar_pid_file() else { return };
    let Ok(contents) = std::fs::read_to_string(&path) else { return };
    let Some((sidecar_pid, shell_pid)) = parse_pid_file(&contents) else {
        let _ = std::fs::remove_file(&path);
        return;
    };
    if let Some(owner) = shell_pid {
        if owner != std::process::id() && process_alive(owner) {
            eprintln!(
                "[flinttrade] sidecar pid file is owned by a live shell (pid {owner}); skipping reap"
            );
            return;
        }
    }
    match process_command_line(sidecar_pid) {
        Some(cmd) if looks_like_backend_sidecar(&cmd) => {
            eprintln!(
                "[flinttrade] terminating stale backend sidecar (pid {sidecar_pid}) from a previous run"
            );
            terminate_process(sidecar_pid);
        }
        Some(_) => {
            eprintln!(
                "[flinttrade] pid {sidecar_pid} from a previous run was reused by another process; leaving it alone"
            );
        }
        None => {} // already gone — just clean up the file
    }
    let _ = std::fs::remove_file(&path);
}

/// Record the freshly spawned sidecar (and this shell) in the PID file so the
/// next launch can reap it if this shell crashes without cleanup.
fn write_sidecar_pid_file(sidecar_pid: u32) {
    let Some(path) = sidecar_pid_file() else {
        eprintln!("[flinttrade] could not resolve workspace dir; sidecar pid not recorded");
        return;
    };
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Err(e) = std::fs::write(&path, format_pid_file(sidecar_pid, std::process::id())) {
        eprintln!("[flinttrade] could not write sidecar pid file: {e}");
    }
}

/// Remove the PID file once the sidecar has been stopped deliberately.
fn remove_sidecar_pid_file() {
    if let Some(path) = sidecar_pid_file() {
        let _ = std::fs::remove_file(&path);
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

    #[test]
    fn pid_file_round_trips() {
        assert_eq!(parse_pid_file(&format_pid_file(1234, 99)), Some((1234, Some(99))));
    }

    #[test]
    fn pid_file_tolerates_a_missing_shell_line() {
        assert_eq!(parse_pid_file("4321\n"), Some((4321, None)));
        assert_eq!(parse_pid_file("4321"), Some((4321, None)));
        assert_eq!(parse_pid_file("4321\nnot-a-pid\n"), Some((4321, None)));
    }

    #[test]
    fn rejects_malformed_pid_files() {
        assert_eq!(parse_pid_file(""), None);
        assert_eq!(parse_pid_file("not-a-pid\n77\n"), None);
        assert_eq!(parse_pid_file("0\n77\n"), None);
        assert_eq!(parse_pid_file("-5\n77\n"), None);
    }

    #[test]
    fn install_script_lives_under_scripts_install() {
        let path = install_script_path(Path::new("/home/op/.flinttrade/src/FlintTrade"));
        let expected: PathBuf = ["/home/op/.flinttrade/src/FlintTrade", "scripts", "install", INSTALL_SCRIPT_NAME]
            .iter()
            .collect();
        assert_eq!(path, expected);
        // The updater must always target the platform's bootstrap script.
        assert!(path.to_string_lossy().contains("flinttrade-install."));
    }

    #[test]
    fn sidecar_identity_matches_only_our_binary() {
        // macOS/Linux `ps -o args=` output for the bundled sidecar.
        assert!(looks_like_backend_sidecar(
            "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
        ));
        // Windows `tasklist /FO CSV /NH` row.
        assert!(looks_like_backend_sidecar(
            "\"flinttrade-backend.exe\",\"1234\",\"Console\",\"1\",\"120,000 K\""
        ));
        // A reused PID belonging to anything else must never match.
        assert!(!looks_like_backend_sidecar("/usr/bin/python3 some_other_server.py"));
        assert!(!looks_like_backend_sidecar("\"notepad.exe\",\"1234\",\"Console\",\"1\",\"9,000 K\""));
    }

    #[test]
    fn navigation_confined_to_backend_origin() {
        let backend_scheme = "http";
        let backend_host = Some("127.0.0.1");
        let backend_port = Some(56576u16);
        let allow = |u: &str| {
            navigation_allowed(
                &tauri::Url::parse(u).unwrap(),
                backend_scheme,
                backend_host,
                backend_port,
            )
        };

        // The backend's own origin — permitted (SPA client-side routes).
        assert!(allow("http://127.0.0.1:56576/"));
        assert!(allow("http://127.0.0.1:56576/setup?tab=native"));

        // A DIFFERENT loopback port is a foreign origin that would otherwise
        // inherit the privileged main-remote commands — refused.
        assert!(!allow("http://127.0.0.1:5000/"));
        // Different host, and an https loopback — both refused.
        assert!(!allow("http://localhost:56576/"));
        assert!(!allow("https://127.0.0.1:56576/"));
        // Any external site — refused (broker OAuth uses the system browser).
        assert!(!allow("https://api.upstox.com/v2/login/authorization/dialog"));

        // Non-http schemes carry no capability, so SPA downloads/workers/views
        // stay permitted.
        assert!(allow("about:blank"));
        assert!(allow("data:text/html,hello"));
        assert!(allow("blob:http://127.0.0.1:56576/uuid"));
    }
}
