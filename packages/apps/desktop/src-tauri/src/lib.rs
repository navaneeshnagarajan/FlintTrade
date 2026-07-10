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
//! 4. Requests a graceful sidecar shutdown when the app exits, then uses a
//!    bounded hard-kill fallback only if cleanup wedges.
//!
//! ## Sidecar orphan protection
//!
//! The graceful exit path (4) only runs on a normal quit. A shell crash or
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
//! * **Graceful stop on exit** — stdin asks Python to unwind Waitress, flush
//!   tick capture, and close DuckDB before the bounded hard-kill fallback.
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

/// Stdin command understood by ``packaging/desktop_backend.py``. The sidecar
/// unwinds Waitress, flushes pending ticks, and closes DuckDB before exiting.
const SIDECAR_SHUTDOWN_COMMAND: &[u8] = b"FLINTTRADE_SHUTDOWN\n";

/// Maximum wait for graceful sidecar cleanup before the hard-kill fallback.
const SIDECAR_SHUTDOWN_POLLS: usize = 100;

/// Short TERM grace used when reaping a stale sidecar during application boot.
const SIDECAR_TERM_POLLS: usize = 20;

/// Brief confirmation window after a hard kill before retaining recovery data.
const SIDECAR_KILL_CONFIRM_POLLS: usize = 10;

/// File name of the platform's bootstrap install/update script. The same file
/// can live inside a source workspace (``scripts/install/``) or inside the
/// packaged app resources for binary-first updates.
#[cfg(windows)]
const INSTALL_SCRIPT_NAME: &str = "flinttrade-install.ps1";
#[cfg(not(windows))]
const INSTALL_SCRIPT_NAME: &str = "flinttrade-install.sh";

/// Resource-relative fallbacks used by Tauri bundles. The release config maps
/// scripts to ``scripts/install/``; the flat fallback keeps older/dev bundles
/// usable if a platform packager flattens resources.
#[cfg(windows)]
const BUNDLED_INSTALL_SCRIPT_CANDIDATES: &[&str] = &[
    "flinttrade-install.ps1",
    "scripts/install/flinttrade-install.ps1",
];
#[cfg(not(windows))]
const BUNDLED_INSTALL_SCRIPT_CANDIDATES: &[&str] = &[
    "flinttrade-install.sh",
    "scripts/install/flinttrade-install.sh",
];

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
// In-app updater.
//
// Binary-first updates run the installer script bundled as an app resource; the
// script downloads the matching published installer asset. Source rebuilds are
// still supported through the source workspace for operators who choose that
// heavier path explicitly.
// ---------------------------------------------------------------------------

/// Payload of the ``updater_state`` command.
#[derive(serde::Serialize)]
struct UpdaterState {
    /// Version of the running app, from the Tauri package metadata.
    app_version: String,
    /// Normalised OS label used by the desktop release manifest.
    platform_os: String,
    /// Normalised CPU architecture used by the desktop release manifest.
    platform_arch: String,
    /// Resolved source workspace containing the install script, or ``None``
    /// when no usable workspace exists (the UI then shows the website
    /// one-liner to copy instead of the in-app rebuild button).
    src_dir: Option<String>,
    /// Bundled binary installer script, if this build packaged one.
    installer_script: Option<String>,
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
            PathBuf::from(home)
                .join(".flinttrade")
                .join("src")
                .join("FlintTrade")
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
    src_dir
        .join("scripts")
        .join("install")
        .join(INSTALL_SCRIPT_NAME)
}

/// Find the packaged installer script under a Tauri resource directory.
fn find_bundled_install_script(resource_dir: &Path) -> Option<PathBuf> {
    for relative in BUNDLED_INSTALL_SCRIPT_CANDIDATES {
        let candidate = resource_dir.join(relative);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Resolve the packaged installer script for binary-first updates.
fn resolve_bundled_install_script(app: &AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    find_bundled_install_script(&resource_dir)
}

/// OS label matching the site release manifest.
fn desktop_os() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else if cfg!(target_os = "linux") {
        "linux"
    } else {
        "unknown"
    }
}

/// Architecture label matching the site release manifest.
fn desktop_arch() -> String {
    match std::env::consts::ARCH {
        "aarch64" | "arm64" => "arm64".to_string(),
        "x86_64" | "amd64" => "x64".to_string(),
        other => other.to_string(),
    }
}

/// Accept only release tags understood by the installer API (`v1.2.3` plus an
/// optional ASCII prerelease suffix). The shell must not pass arbitrary strings
/// through to the spawned script command line.
fn valid_release_tag(tag: &str) -> bool {
    let trimmed = tag.trim();
    if trimmed.is_empty() || trimmed != tag || trimmed.len() > 80 {
        return false;
    }
    let body = trimmed.strip_prefix('v').unwrap_or(trimmed);
    let (core, prerelease) = body
        .split_once('-')
        .map_or((body, None), |(core, pre)| (core, Some(pre)));
    let parts: Vec<&str> = core.split('.').collect();
    if parts.len() != 3
        || parts
            .iter()
            .any(|part| part.is_empty() || !part.chars().all(|c| c.is_ascii_digit()))
    {
        return false;
    }
    match prerelease {
        None => true,
        Some(pre) => {
            !pre.is_empty()
                && pre
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
        }
    }
}

/// Report the running app version and the resolved source workspace (if any)
/// to the terminal's Settings → Updates section.
#[tauri::command]
fn updater_state(app: AppHandle) -> UpdaterState {
    UpdaterState {
        app_version: app.package_info().version.to_string(),
        platform_os: desktop_os().to_string(),
        platform_arch: desktop_arch(),
        src_dir: resolve_source_workspace().map(|d| d.display().to_string()),
        installer_script: resolve_bundled_install_script(&app).map(|p| p.display().to_string()),
    }
}

/// Kick off the binary-first update path: run the packaged installer script
/// detached. The script downloads and installs the matching release asset for
/// this OS/arch, so no source checkout or build toolchain is required.
#[tauri::command]
fn run_binary_update(app: AppHandle, tag: Option<String>) -> Result<(), String> {
    let release_tag = tag
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if let Some(value) = release_tag {
        if !valid_release_tag(value) {
            return Err(format!("Refusing invalid release tag: {value}"));
        }
    }
    let Some(script) = resolve_bundled_install_script(&app) else {
        return Err("No packaged installer script found in this desktop build.".to_string());
    };
    let current_dir = script
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    launch_binary_update(&app, &script, &current_dir, release_tag)
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
    // Detached rebuild: the returned handle is kept only to detach from — a
    // dropped `Child` is never signalled or waited, so the process survives our
    // exit. Source rebuilds keep the timed exit (the built installer owns the
    // relaunch and does not hand a "download verified" signal back to us).
    let _child = spawn_detached_updater(&script, &src_dir, true, None, None)
        .map_err(|e| format!("Could not start the update script: {e}"))?;

    schedule_update_exit(&app);
    Ok(())
}

fn schedule_update_exit(app: &AppHandle) {
    // Mark the quit as deliberate (close-to-tray must not intercept it), then
    // exit shortly so the updater can replace the bundle underneath us. Used by
    // the source-rebuild path and the Windows binary path, whose installers own
    // the relaunch and do not signal a verified download back to us.
    if let Some(q) = app.try_state::<QuitRequested>() {
        q.0.store(true, std::sync::atomic::Ordering::SeqCst);
    }
    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(2));
        do_deliberate_exit(&handle);
    });
}

/// Mark the quit as deliberate (so the close-to-tray handler steps aside) and
/// exit on the main thread.
fn do_deliberate_exit(app: &AppHandle) {
    if let Some(q) = app.try_state::<QuitRequested>() {
        q.0.store(true, std::sync::atomic::Ordering::SeqCst);
    }
    let handle = app.clone();
    let h = handle.clone();
    let _ = handle.run_on_main_thread(move || h.exit(0));
}

/// Environment variable naming the file the installer touches once it has
/// downloaded + verified the release and is about to replace the running
/// bundle. The desktop shell waits for that file before quitting, so a failed
/// or slow download can never leave the app gone with nothing installed.
#[cfg(unix)]
const UPDATE_HANDOFF_ENV: &str = "FLINTTRADE_UPDATE_HANDOFF";

/// A fresh, not-yet-existing path (under the workspace dir) for the installer's
/// download-verified handoff marker. ``None`` when no workspace dir resolves,
/// in which case the caller falls back to the timed exit.
#[cfg(unix)]
fn update_handoff_path() -> Option<PathBuf> {
    let dir = flinttrade_home()?;
    if std::fs::create_dir_all(&dir).is_err() {
        return None;
    }
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let path = dir.join(format!("update_handoff_{}_{}", std::process::id(), nonce));
    // A stale marker from a prior run would trigger an instant false handoff.
    let _ = std::fs::remove_file(&path);
    Some(path)
}

/// One poll's worth of decision for the binary-update handoff watcher.
#[cfg(unix)]
#[derive(Debug, PartialEq, Eq)]
enum HandoffDecision {
    /// The installer signalled it has downloaded + verified and is replacing the
    /// bundle — quit so the freshly installed build can relaunch.
    Proceed,
    /// The updater exited before signalling — it could not proceed. Keep the app
    /// running and surface the failure rather than vanishing.
    Failed,
    /// The updater exited cleanly without ever needing us to step aside (e.g. a
    /// package-manager install that replaces files in place). Nothing to do.
    Done,
    /// The updater is still working (download in progress) — keep waiting.
    KeepWaiting,
}

/// Decide what the handoff watcher should do from the marker's presence and the
/// child's exit state (``None`` = still running, ``Some(success)`` = exited).
/// A present marker always wins: once the installer is replacing the bundle we
/// must step aside even if the child has also just exited.
#[cfg(unix)]
fn handoff_decision(handoff_present: bool, exited_success: Option<bool>) -> HandoffDecision {
    if handoff_present {
        return HandoffDecision::Proceed;
    }
    match exited_success {
        None => HandoffDecision::KeepWaiting,
        Some(true) => HandoffDecision::Done,
        Some(false) => HandoffDecision::Failed,
    }
}

/// Kick off the binary-first update (unix). The detached installer touches the
/// handoff marker once the download is verified and it is about to replace the
/// bundle; only then do we quit, so a failed or slow download can never leave
/// the app gone with nothing installed. Falls back to the timed exit when no
/// workspace dir (hence no marker path) is available.
#[cfg(unix)]
fn launch_binary_update(
    app: &AppHandle,
    script: &Path,
    current_dir: &Path,
    release_tag: Option<&str>,
) -> Result<(), String> {
    match update_handoff_path() {
        Some(handoff) => {
            let child = spawn_detached_updater(
                script,
                current_dir,
                false,
                release_tag,
                Some(handoff.as_path()),
            )
            .map_err(|e| format!("Could not start the installer update: {e}"))?;
            wait_for_handoff_then_exit(app, child, handoff);
        }
        None => {
            let _child = spawn_detached_updater(script, current_dir, false, release_tag, None)
                .map_err(|e| format!("Could not start the installer update: {e}"))?;
            schedule_update_exit(app);
        }
    }
    Ok(())
}

/// Kick off the binary-first update (non-unix, i.e. Windows). The NSIS setup.exe
/// owns the relaunch and does not signal a verified download back to us, so the
/// existing timed exit is kept. The failed-download-vanish hardening is the unix
/// handoff path above; the Windows script staging (running the .ps1 from a temp
/// dir outside $INSTDIR) lives in ``spawn_detached_updater``.
#[cfg(not(unix))]
fn launch_binary_update(
    app: &AppHandle,
    script: &Path,
    current_dir: &Path,
    release_tag: Option<&str>,
) -> Result<(), String> {
    let _child = spawn_detached_updater(script, current_dir, false, release_tag, None)
        .map_err(|e| format!("Could not start the installer update: {e}"))?;
    schedule_update_exit(app);
    Ok(())
}

/// Watch the detached installer: quit once it signals the verified-download
/// handoff, or surface a failure (and stay running) if it exits before it can
/// proceed. Preserves the detached-spawn + installer-driven relaunch design.
#[cfg(unix)]
fn wait_for_handoff_then_exit(app: &AppHandle, mut child: std::process::Child, handoff: PathBuf) {
    let handle = app.clone();
    std::thread::spawn(move || loop {
        let handoff_present = handoff.exists();
        let exited_success = match child.try_wait() {
            Ok(Some(status)) => Some(status.success()),
            Ok(None) => None,
            Err(_) => Some(false),
        };
        match handoff_decision(handoff_present, exited_success) {
            HandoffDecision::Proceed => {
                let _ = std::fs::remove_file(&handoff);
                do_deliberate_exit(&handle);
                return;
            }
            HandoffDecision::Failed => {
                let _ = std::fs::remove_file(&handoff);
                surface_update_failure(&handle);
                return;
            }
            HandoffDecision::Done => {
                let _ = std::fs::remove_file(&handoff);
                return;
            }
            HandoffDecision::KeepWaiting => {
                std::thread::sleep(std::time::Duration::from_millis(200));
            }
        }
    });
}

/// Tell the operator the update could not start, keeping the app alive.
#[cfg(unix)]
fn surface_update_failure(app: &AppHandle) {
    eprintln!("[flinttrade] update could not proceed; keeping the app running");
    raise_notification(
        app,
        "Update could not start",
        "FlintTrade could not download the update and is still running. Please try again.",
    );
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
    let mut extras = vec![
        PathBuf::from("/usr/local/bin"),
        PathBuf::from("/opt/homebrew/bin"),
    ];
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
fn spawn_detached_updater(
    script: &Path,
    current_dir: &Path,
    build_from_source: bool,
    release_tag: Option<&str>,
    handoff: Option<&Path>,
) -> std::io::Result<std::process::Child> {
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;

    let (out, err) = match self_update_log_file() {
        Some(f) => {
            let clone = f.try_clone();
            (
                Stdio::from(f),
                clone.map(Stdio::from).unwrap_or_else(|_| Stdio::null()),
            )
        }
        None => (Stdio::null(), Stdio::null()),
    };
    let mut cmd = std::process::Command::new("bash");
    cmd.arg(script).arg("--update");
    if build_from_source {
        cmd.arg("--build-from-source");
    } else if let Some(tag) = release_tag {
        cmd.arg("--ref").arg(tag);
    }
    cmd.env("FLINTTRADE_YES", "1")
        .env("PATH", augmented_path())
        .current_dir(current_dir)
        .stdin(Stdio::null())
        .stdout(out)
        .stderr(err)
        // New process group: the script survives this app's exit and any
        // group-targeted signals sent to us on the way down.
        .process_group(0);
    if let Some(marker) = handoff {
        cmd.env(UPDATE_HANDOFF_ENV, marker);
    }
    cmd.spawn()
}

/// Spawn the update script detached (Windows): its own console + process
/// group, so the PowerShell build keeps running — and shows progress — after
/// this app exits. ``FLINTTRADE_YES=1`` consents to user-local tool installs.
#[cfg(windows)]
fn spawn_detached_updater(
    script: &Path,
    current_dir: &Path,
    build_from_source: bool,
    release_tag: Option<&str>,
    handoff: Option<&Path>,
) -> std::io::Result<std::process::Child> {
    use std::os::windows::process::CommandExt;
    const CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;

    // Binary-first updates run the script bundled in the app's resource dir
    // ($INSTDIR). The NSIS updater it launches replaces $INSTDIR wholesale,
    // which would pull the running .ps1 — and its working directory — out from
    // under it mid-run. Stage the script (and cwd) to a temp dir OUTSIDE
    // $INSTDIR so the running script cannot be deleted by the install it
    // triggers. Source builds run from the separate source workspace, which the
    // build never replaces, so they run in place.
    let staged = if build_from_source {
        None
    } else {
        stage_updater_script_in_temp(script)
    };
    let (run_script, run_dir): (&Path, &Path) = match staged.as_ref() {
        Some((staged_script, staged_dir)) => (staged_script.as_path(), staged_dir.as_path()),
        None => (script, current_dir),
    };

    let mut cmd = std::process::Command::new("powershell");
    cmd.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"])
        .arg(run_script);
    if build_from_source {
        cmd.arg("-BuildFromSource");
    } else if let Some(tag) = release_tag {
        cmd.arg("-Ref").arg(tag);
    }
    cmd.env("FLINTTRADE_YES", "1")
        .current_dir(run_dir)
        .creation_flags(CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP);
    if let Some(marker) = handoff {
        cmd.env("FLINTTRADE_UPDATE_HANDOFF", marker);
    }
    cmd.spawn()
}

/// Copy the updater script to a fresh temp dir OUTSIDE the app's install dir and
/// return ``(staged_script, staged_dir)``. Used on Windows so an in-app binary
/// update — whose NSIS installer replaces $INSTDIR — cannot delete the running
/// .ps1 (or its working directory) mid-run. The temp dir is deliberately left
/// in place: the OS reclaims %TEMP% and the still-running script needs it.
/// Returns ``None`` if staging fails, in which case the caller runs in place.
#[cfg(any(windows, test))]
fn stage_updater_script_in_temp(script: &Path) -> Option<(PathBuf, PathBuf)> {
    let name = script.file_name()?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let dir = std::env::temp_dir().join(format!(
        "flinttrade-update-{}-{}",
        std::process::id(),
        nonce
    ));
    std::fs::create_dir_all(&dir).ok()?;
    let dest = dir.join(name);
    std::fs::copy(script, &dest).ok()?;
    Some((dest, dir))
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
        // ``allow-updater-state`` / ``allow-run-binary-update`` /
        // ``allow-run-self-update`` entries in
        // ``capabilities/main-remote.json`` (autogenerated by build.rs).
        .invoke_handler(tauri::generate_handler![
            updater_state,
            run_binary_update,
            run_self_update
        ])
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
                                    let _ = handle
                                        .run_on_main_thread(move || show_main_window(&h, port));
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
                eprintln!(
                    "[flinttrade] blocked in-webview navigation to non-backend origin: {target}"
                );
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
    let result = app
        .global_shortcut()
        .on_shortcut(shortcut, |app, _sc, event| {
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
    let _ = app.notification().builder().title(title).body(body).show();
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

/// Gracefully stop the backend sidecar, with a bounded hard-kill fallback.
fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Some(mut child) = state.0.lock().unwrap().take() {
            let pid = child.pid();
            if child.write(SIDECAR_SHUTDOWN_COMMAND).is_ok()
                && wait_for_process_exit(pid, SIDECAR_SHUTDOWN_POLLS)
            {
                remove_sidecar_pid_file();
                return;
            }
            match process_liveness(pid) {
                ProcessLiveness::Alive => {
                    eprintln!(
                        "[flinttrade] backend did not stop gracefully within 10s; forcing exit"
                    );
                }
                ProcessLiveness::Unknown => {
                    eprintln!(
                        "[flinttrade] backend exit could not be confirmed; requesting hard kill"
                    );
                }
                ProcessLiveness::Dead => {}
            }
            if let Err(error) = child.kill() {
                eprintln!("[flinttrade] backend hard-kill request failed: {error}");
            }
            if wait_for_process_exit(pid, SIDECAR_KILL_CONFIRM_POLLS) {
                remove_sidecar_pid_file();
            } else {
                eprintln!(
                    "[flinttrade] backend pid {pid} is still alive after hard kill; retaining recovery record"
                );
            }
        }
    }
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
    let sidecar = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|p| *p > 0)?;
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
    text.lines()
        .find(|l| l.contains(&needle))
        .map(str::to_string)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ProcessLiveness {
    Alive,
    Dead,
    Unknown,
}

/// Tri-state liveness probe that never treats an OS error as confirmed death.
#[cfg(unix)]
fn process_liveness(pid: u32) -> ProcessLiveness {
    let Ok(raw_pid) = i32::try_from(pid) else {
        return ProcessLiveness::Unknown;
    };
    extern "C" {
        fn kill(pid: i32, signal: i32) -> i32;
    }

    // Signal 0 performs permission/existence checks without delivering a signal.
    if unsafe { kill(raw_pid, 0) } == 0 {
        return ProcessLiveness::Alive;
    }
    match std::io::Error::last_os_error().raw_os_error() {
        Some(3) => ProcessLiveness::Dead,  // POSIX ESRCH
        Some(1) => ProcessLiveness::Alive, // POSIX EPERM proves the process exists
        _ => ProcessLiveness::Unknown,
    }
}

/// Tri-state liveness probe that never treats a tasklist failure as death.
#[cfg(windows)]
fn process_liveness(pid: u32) -> ProcessLiveness {
    let Ok(output) = std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/FO", "CSV", "/NH"])
        .output()
    else {
        return ProcessLiveness::Unknown;
    };
    if !output.status.success() {
        return ProcessLiveness::Unknown;
    }
    let text = String::from_utf8_lossy(&output.stdout);
    let needle = format!("\"{pid}\"");
    if text.lines().any(|line| line.contains(&needle)) {
        ProcessLiveness::Alive
    } else {
        ProcessLiveness::Dead
    }
}

/// Wait a bounded number of 100 ms polls for one process to disappear.
fn wait_for_process_exit(pid: u32, polls: usize) -> bool {
    for _ in 0..polls {
        match process_liveness(pid) {
            ProcessLiveness::Dead => return true,
            ProcessLiveness::Alive | ProcessLiveness::Unknown => {}
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
    process_liveness(pid) == ProcessLiveness::Dead
}

/// Terminate a process: graceful TERM first, escalating to a hard kill only
/// if it lingers past a short grace window.
#[cfg(unix)]
fn terminate_process(pid: u32) -> bool {
    let pid_s = pid.to_string();
    let _ = std::process::Command::new("kill")
        .args(["-TERM", &pid_s])
        .status();
    if wait_for_process_exit(pid, SIDECAR_TERM_POLLS) {
        return true;
    }
    let _ = std::process::Command::new("kill")
        .args(["-KILL", &pid_s])
        .status();
    wait_for_process_exit(pid, SIDECAR_KILL_CONFIRM_POLLS)
}

/// Terminate a process (Windows `taskkill`, including its child tree).
#[cfg(windows)]
fn terminate_process(pid: u32) -> bool {
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &pid.to_string(), "/T", "/F"])
        .status();
    wait_for_process_exit(pid, SIDECAR_KILL_CONFIRM_POLLS)
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
    let Some(path) = sidecar_pid_file() else {
        return;
    };
    let Ok(contents) = std::fs::read_to_string(&path) else {
        return;
    };
    let Some((sidecar_pid, shell_pid)) = parse_pid_file(&contents) else {
        let _ = std::fs::remove_file(&path);
        return;
    };
    if let Some(owner) = shell_pid {
        if owner != std::process::id() {
            match process_liveness(owner) {
                ProcessLiveness::Alive => {
                    eprintln!(
                        "[flinttrade] sidecar pid file is owned by a live shell (pid {owner}); skipping reap"
                    );
                    return;
                }
                ProcessLiveness::Unknown => {
                    eprintln!(
                        "[flinttrade] shell pid {owner} liveness is unknown; retaining sidecar recovery record"
                    );
                    return;
                }
                ProcessLiveness::Dead => {}
            }
        }
    }
    let remove_recovery_record = match process_liveness(sidecar_pid) {
        ProcessLiveness::Dead => true,
        ProcessLiveness::Unknown => false,
        ProcessLiveness::Alive => match process_command_line(sidecar_pid) {
            Some(cmd) if looks_like_backend_sidecar(&cmd) => {
                eprintln!(
                    "[flinttrade] terminating stale backend sidecar (pid {sidecar_pid}) from a previous run"
                );
                terminate_process(sidecar_pid)
            }
            Some(_) => {
                eprintln!(
                    "[flinttrade] pid {sidecar_pid} from a previous run was reused by another process; leaving it alone"
                );
                true
            }
            None => false,
        },
    };
    if remove_recovery_record {
        let _ = std::fs::remove_file(&path);
    } else {
        eprintln!(
            "[flinttrade] stale backend pid {sidecar_pid} could not be confirmed stopped; retaining recovery record"
        );
    }
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
        return std::env::var_os("HOME").map(|h| {
            PathBuf::from(h)
                .join("Library")
                .join("Application Support")
                .join("flinttrade")
        });
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
        assert_eq!(
            parse_ready_port("FLINTTRADE_BACKEND_READY port=5100"),
            Some(5100)
        );
    }

    #[test]
    fn handles_trailing_text_after_port() {
        assert_eq!(
            parse_ready_port("FLINTTRADE_BACKEND_READY port=8080 extra"),
            Some(8080)
        );
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
            Some((
                "Order filled".to_string(),
                "RELIANCE BUY 10 @ 2900".to_string()
            ))
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
        assert_eq!(
            parse_notify_line("FLINTTRADE_BACKEND_READY port=5100"),
            None
        );
        assert_eq!(parse_notify_line("FLINTTRADE_NOTIFY no tabs here"), None);
        assert_eq!(parse_notify_line("FLINTTRADE_NOTIFY\t\tbody only"), None);
        assert_eq!(parse_notify_line("random log line"), None);
    }

    #[test]
    fn pid_file_round_trips() {
        assert_eq!(
            parse_pid_file(&format_pid_file(1234, 99)),
            Some((1234, Some(99)))
        );
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
    fn exit_confirmation_never_claims_the_current_process_is_dead() {
        assert_eq!(process_liveness(std::process::id()), ProcessLiveness::Alive);
        assert!(!wait_for_process_exit(std::process::id(), 0));
    }

    #[cfg(unix)]
    #[test]
    fn invalid_unix_pid_is_unknown_not_dead() {
        assert_eq!(process_liveness(u32::MAX), ProcessLiveness::Unknown);
    }

    #[test]
    fn install_script_lives_under_scripts_install() {
        let path = install_script_path(Path::new("/home/op/.flinttrade/src/FlintTrade"));
        let expected: PathBuf = [
            "/home/op/.flinttrade/src/FlintTrade",
            "scripts",
            "install",
            INSTALL_SCRIPT_NAME,
        ]
        .iter()
        .collect();
        assert_eq!(path, expected);
        // The updater must always target the platform's bootstrap script.
        assert!(path.to_string_lossy().contains("flinttrade-install."));
    }

    #[test]
    fn release_tag_validation_accepts_semver_refs_only() {
        assert!(valid_release_tag("v0.6.0-beta.1"));
        assert!(valid_release_tag("0.7.0"));
        assert!(valid_release_tag("v1.2.3-rc.4"));

        assert!(!valid_release_tag(""));
        assert!(!valid_release_tag(" latest "));
        assert!(!valid_release_tag("main"));
        assert!(!valid_release_tag("v1.2"));
        assert!(!valid_release_tag("v1.2.3 && open /Applications"));
        assert!(!valid_release_tag("v1.2.3/beta"));
    }

    #[test]
    fn bundled_install_script_resolver_accepts_mapped_or_flat_resources() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-resource-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(root.join("scripts").join("install")).unwrap();

        let nested = root
            .join("scripts")
            .join("install")
            .join(INSTALL_SCRIPT_NAME);
        std::fs::write(&nested, "echo ok\n").unwrap();
        assert_eq!(find_bundled_install_script(&root), Some(nested.clone()));

        std::fs::remove_file(&nested).unwrap();
        let flat = root.join(INSTALL_SCRIPT_NAME);
        std::fs::write(&flat, "echo ok\n").unwrap();
        assert_eq!(find_bundled_install_script(&root), Some(flat));

        let _ = std::fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn handoff_decision_prioritises_marker_then_reports_failure() {
        // Marker present -> step aside regardless of the child's exit state.
        assert_eq!(handoff_decision(true, None), HandoffDecision::Proceed);
        assert_eq!(handoff_decision(true, Some(true)), HandoffDecision::Proceed);
        assert_eq!(handoff_decision(true, Some(false)), HandoffDecision::Proceed);
        // No marker, still running -> keep waiting (a slow download must not
        // make the app vanish).
        assert_eq!(handoff_decision(false, None), HandoffDecision::KeepWaiting);
        // No marker, exited with failure -> the update could not proceed; stay
        // alive and surface it.
        assert_eq!(handoff_decision(false, Some(false)), HandoffDecision::Failed);
        // No marker, exited cleanly -> nothing to step aside for.
        assert_eq!(handoff_decision(false, Some(true)), HandoffDecision::Done);
    }

    #[test]
    fn staged_updater_script_lives_outside_the_source_dir() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-stage-src-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let script = root.join("flinttrade-install.ps1");
        std::fs::write(&script, "echo staged\n").unwrap();

        let (staged_script, staged_dir) =
            stage_updater_script_in_temp(&script).expect("staging should succeed");

        assert!(staged_script.is_file());
        assert_eq!(
            std::fs::read_to_string(&staged_script).unwrap(),
            "echo staged\n"
        );
        assert_eq!(staged_script.file_name(), script.file_name());
        // Crucially, the staged copy must NOT live under the source (install)
        // dir the NSIS updater would replace.
        assert!(!staged_script.starts_with(&root));
        assert!(staged_dir.starts_with(std::env::temp_dir()));

        let _ = std::fs::remove_dir_all(&root);
        let _ = std::fs::remove_dir_all(&staged_dir);
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
        assert!(!looks_like_backend_sidecar(
            "/usr/bin/python3 some_other_server.py"
        ));
        assert!(!looks_like_backend_sidecar(
            "\"notepad.exe\",\"1234\",\"Console\",\"1\",\"9,000 K\""
        ));
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
        assert!(!allow(
            "https://api.upstox.com/v2/login/authorization/dialog"
        ));

        // Non-http schemes carry no capability, so SPA downloads/workers/views
        // stay permitted.
        assert!(allow("about:blank"));
        assert!(allow("data:text/html,hello"));
        assert!(allow("blob:http://127.0.0.1:56576/uuid"));
    }
}
