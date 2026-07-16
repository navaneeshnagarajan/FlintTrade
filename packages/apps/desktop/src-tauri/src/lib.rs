//! FlintTrade Desktop — Tauri 2 thin shell.
//!
//! The desktop app is a thin native window around the managed FlintTrade
//! backend payload. On launch it:
//!
//! 1. Provisions the credential-vault master password (first run only) into the
//!    hardened at-rest file the backend reads — honouring locked decision #13
//!    (the *shell* provides the secret; the backend never auto-generates one).
//! 2. Boots the managed ``flinttrade-backend`` payload staged under
//!    ``<workspace>/runtime/backend/<version>/`` on an OS-chosen loopback port
//!    (``--port 0``) and waits for its ``FLINTTRADE_BACKEND_READY port=<n>``
//!    handshake on stdout. The payload is the *only* backend source — the
//!    installer bundles no sidecar. When no payload verifies against its
//!    ``state.json`` sha256 pin (first run, or a demoted broken pin), the
//!    splash phase downloads the hash-verified payload from the rolling
//!    channel release with progress reporting, and any failure lands on the
//!    splash error surface with an explicit Retry — never a crash loop.
//!    Routine daily backend+frontend updates need no installer cycle.
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
//! accumulate duplicates. Five layers close that hole:
//!
//! * **Kernel instance lock** — each workspace has one advisory lock file. The
//!   shell holds the exclusive OS lock for its full process lifetime; the PID
//!   text inside that file is diagnostic only and never decides ownership.
//! * **Fail-closed recovery on launch** — the shell records both the spawned
//!   PyInstaller launcher PID and the real Python application PID (plus its
//!   own) in ``desktop_backend.pid`` with a per-launch token. Python publishes
//!   its PID before backend imports. Current records also carry the OS boot
//!   identity, allowing a pending record from an earlier boot to be cleared
//!   without probing recycled PIDs. Recovery otherwise waits for containment
//!   and only clears after every confirmed process is dead or reused.
//! * **Parent-liveness watchdog** — the shell passes its PID via
//!   ``FLINTTRADE_PARENT_PID``; the sidecar entry script
//!   (``packaging/desktop_backend.py``) watches that process from a daemon
//!   thread and exits cleanly when the shell dies.
//! * **Complete-tree containment** — POSIX keeps an external guardian alive
//!   beyond the Python leader and tracks same-group/new-session descendants;
//!   Windows assigns the application to a non-breakaway kill-on-close Job.
//! * **Graceful stop on exit** — stdin asks Python to unwind Waitress, flush
//!   tick capture, and close DuckDB. If that wedges, a second command on the
//!   same inherited pipe asks containment to hard-stop the complete tree.
//!
//! A small splash window covers steps 1–2 (including the first-run payload
//! download, whose progress it renders) so the user sees immediate feedback.
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

use std::io::{BufRead, BufReader, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command as StdCommand, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
#[cfg(windows)]
use std::sync::OnceLock;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

#[cfg(test)]
use std::process::ExitStatus;

use fs2::FileExt;
use tauri::menu::{Menu, MenuEvent, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_updater::UpdaterExt;

/// Exit status of the contained backend process, mirroring the shape the
/// shell-plugin sidecar API used to report before the bundled sidecar (and
/// with it ``tauri-plugin-shell``) was removed.
struct BackendExit {
    code: Option<i32>,
    signal: Option<i32>,
}

/// Events surfaced by the contained backend's stdio pipes and exit watcher.
enum BackendProcessEvent {
    Stdout(Vec<u8>),
    Stderr(Vec<u8>),
    Terminated(BackendExit),
    Error(String),
}

/// Stdout line the backend prints once its listening socket is bound.
const READY_SENTINEL: &str = "FLINTTRADE_BACKEND_READY";

/// Stdout line the Python application emits before importing the backend.
/// PyInstaller one-file builds may have a short-lived bootloader PID distinct
/// from this process, so recovery ownership is incomplete until this arrives.
const APPLICATION_PID_SENTINEL: &str = "FLINTTRADE_BACKEND_PID";

/// Stdout proof that Python will exit before importing a backend tree, making
/// only this launch's exact pending record safe for guarded cleanup.
const PENDING_RECORD_EXIT_ACK_SENTINEL: &str = "FLINTTRADE_BACKEND_PENDING_EXIT_ACK";

/// Exact-token proof emitted and persisted by the POSIX guardian only after it
/// has confirmed that the complete owned backend process tree is gone.
const CLEANUP_COMPLETE_SENTINEL: &str = "FLINTTRADE_BACKEND_CLEANUP_COMPLETE";

/// Maximum retained stdout tail while waiting for a fragmented handshake.
const MAX_HANDSHAKE_BUFFER_BYTES: usize = 4_096;

/// Stable POSIX shell command/PID/start identity captured before sidecar spawn.
#[cfg(unix)]
const PARENT_IDENTITY_ENV: &str = "FLINTTRADE_PARENT_IDENTITY";

/// Stable OS boot-session identity persisted into every current recovery record.
const BOOT_ID_ENV: &str = "FLINTTRADE_BOOT_ID";

/// Stdout prefix the backend prints to raise a native desktop notification.
/// Format: ``FLINTTRADE_NOTIFY\t<title>\t<body>`` (tab-delimited, one line).
const NOTIFY_SENTINEL: &str = "FLINTTRADE_NOTIFY";

/// Global hotkey (parsed cross-platform) that toggles the main window.
const TOGGLE_SHORTCUT: &str = "CommandOrControl+Shift+F";

/// Workspace-dir file recording the sidecar PID, owning shell PID, and
/// per-launch token so a later launch can reap an orphan from a crashed run.
const SIDECAR_PID_FILE: &str = "desktop_backend.pid";

/// Recovery-record schema carrying both the spawned launcher and real Python
/// application process identities.
const SIDECAR_RECORD_VERSION: &str = "v4";

/// File carrying the process-lifetime kernel lock that prevents two desktop
/// instances from spawning sidecars into the same workspace. Its text is only
/// diagnostic; ownership is established exclusively by the OS lock.
const DESKTOP_INSTANCE_LOCK_FILE: &str = "desktop_instance.lock";

/// Substring that must appear in a process's command line / image name before
/// the reaper will treat it as a still-live backend sidecar.
const SIDECAR_PROCESS_MARKER: &str = "flinttrade-backend";

/// Stdin command understood by ``packaging/desktop_backend.py``. The sidecar
/// unwinds Waitress, flushes pending ticks, and closes DuckDB before exiting.
const SIDECAR_SHUTDOWN_COMMAND: &[u8] = b"FLINTTRADE_SHUTDOWN\n";

/// Exact-pipe hard-stop command handled inside the Python application. Python
/// terminates its contained tree, avoiding signals to PIDs recovered from disk.
const SIDECAR_FORCE_EXIT_COMMAND: &[u8] = b"FLINTTRADE_FORCE_EXIT\n";

/// Python's documented sequential maxima total 297 seconds: smart orders (30),
/// agent (30), four uploaded strategies (28), rotation (30), Ditto (5), router
/// retirement (10), capture (3), request drain (60), the post-drain strategy /
/// Ditto / router pass (43), storage (3), local AI (5), and client close (50).
/// Round that to 300 seconds, then leave separate graceful and force margins.
const SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS: u64 = 300;
const SIDECAR_GRACEFUL_SHUTDOWN_TIMEOUT: Duration =
    Duration::from_secs(SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS + 10);
const SIDECAR_TOTAL_SHUTDOWN_TIMEOUT: Duration =
    Duration::from_secs(SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS + 20);

/// Short window for Python to promote the exact pending recovery record. A
/// pending PID must not consume the 150-second confirmed-application budget.
const SIDECAR_PENDING_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(3);

/// Initial grace before stale-sidecar recovery fails closed. Python may take
/// almost 2s to observe parent death, waits 12s before its complete-tree orphan
/// fallback, then may spend 5s confirming descendants are gone. Twenty-two
/// seconds covers every stage plus scheduling margin.
const SIDECAR_WATCHDOG_GRACE_TIMEOUT: Duration = Duration::from_secs(22);

/// Brief confirmation window after a hard kill before retaining recovery data.
const SIDECAR_KILL_CONFIRM_TIMEOUT: Duration = Duration::from_secs(1);

/// Give Python containment longer than its 5s POSIX descendant-kill pass before
/// retaining the launcher/guardian and recovery record for continued cleanup.
const SIDECAR_FORCE_EXIT_TIMEOUT: Duration = Duration::from_secs(7);

/// Consecutive inconclusive supervisor probes tolerated before recovery state
/// is retained for the next explicit startup repair instead of polling forever.
const SIDECAR_SUPERVISOR_UNKNOWN_POLLS: usize = 50;

#[cfg(any(windows, test))]
const WINDOWS_JOB_OBJECT_LIMIT_BREAKAWAY_OK: u32 = 0x0000_0800;
#[cfg(any(windows, test))]
const WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_CLOSE: u32 = 0x0000_2000;
#[cfg(any(windows, test))]
const WINDOWS_SHELL_JOB_LIMIT_FLAGS: u32 =
    WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_CLOSE | WINDOWS_JOB_OBJECT_LIMIT_BREAKAWAY_OK;
#[cfg(any(windows, test))]
const WINDOWS_CREATE_NEW_CONSOLE: u32 = 0x0000_0010;
#[cfg(any(windows, test))]
const WINDOWS_CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
#[cfg(any(windows, test))]
const WINDOWS_CREATE_BREAKAWAY_FROM_JOB: u32 = 0x0100_0000;
#[cfg(any(windows, test))]
const WINDOWS_CREATE_NO_WINDOW: u32 = 0x0800_0000;
#[cfg(any(windows, test))]
const WINDOWS_BACKEND_CREATION_FLAGS: u32 = WINDOWS_CREATE_NO_WINDOW;
#[cfg(any(windows, test))]
const WINDOWS_DETACHED_UPDATER_FLAGS: u32 = WINDOWS_CREATE_NEW_CONSOLE
    | WINDOWS_CREATE_NEW_PROCESS_GROUP
    | WINDOWS_CREATE_BREAKAWAY_FROM_JOB;

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

/// Set only after an unexpected sidecar termination. It keeps the recovery
/// command unavailable during normal operation and changes window-close from
/// hide-to-tray into a real app exit.
struct BackendFailed(std::sync::atomic::AtomicBool);

/// Open kernel-lock handle retained in managed app state for the process
/// lifetime. Dropping the handle is the only release operation; the lock file
/// is deliberately never unlinked.
#[derive(Debug)]
struct DesktopInstanceLock {
    _file: std::fs::File,
    shell_pid: u32,
    boot_id: String,
    launch_token: String,
}

/// Exact recovery record for the sidecar spawned by one desktop launch.
#[derive(Debug, Clone, PartialEq, Eq)]
struct SidecarRecord {
    /// PID returned by Tauri for the spawned executable. In a PyInstaller
    /// one-file build this can be only the bootloader/launcher process.
    sidecar_pid: u32,
    /// Real Python application PID, confirmed from its stdout handshake.
    /// ``None`` is a fail-closed crash-before-handshake state.
    application_pid: Option<u32>,
    shell_pid: u32,
    boot_id: String,
    launch_token: String,
}

/// PID ownership fields shared by current tokenised records and the legacy
/// two-line format. Legacy records are accepted only by startup reaping; all
/// newly published and runtime-owned records remain tokenised
/// [`SidecarRecord`]s.
#[derive(Debug, Clone, PartialEq, Eq)]
struct ReapRecord {
    sidecar_pid: u32,
    application_pid: Option<u32>,
    shell_pid: u32,
    boot_id: Option<String>,
    spawn_contained: bool,
}

#[derive(Debug)]
enum SpawnContainment {
    #[cfg(unix)]
    PosixGroup { pgid: u32 },
    #[cfg(windows)]
    WindowsShellJob,
}

#[cfg(windows)]
static WINDOWS_SHELL_JOB: OnceLock<Result<WindowsJobHandle, String>> = OnceLock::new();

#[cfg(windows)]
#[derive(Debug)]
struct WindowsJobHandle(usize);

#[cfg(windows)]
impl WindowsJobHandle {
    fn create() -> std::io::Result<Self> {
        use std::ffi::c_void;

        #[repr(C)]
        struct IoCounters {
            read_operations: u64,
            write_operations: u64,
            other_operations: u64,
            read_bytes: u64,
            write_bytes: u64,
            other_bytes: u64,
        }
        #[repr(C)]
        struct BasicLimitInformation {
            per_process_user_time_limit: i64,
            per_job_user_time_limit: i64,
            limit_flags: u32,
            minimum_working_set_size: usize,
            maximum_working_set_size: usize,
            active_process_limit: u32,
            affinity: usize,
            priority_class: u32,
            scheduling_class: u32,
        }
        #[repr(C)]
        struct ExtendedLimitInformation {
            basic_limit_information: BasicLimitInformation,
            io_info: IoCounters,
            process_memory_limit: usize,
            job_memory_limit: usize,
            peak_process_memory_used: usize,
            peak_job_memory_used: usize,
        }
        extern "system" {
            fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> *mut c_void;
            fn SetInformationJobObject(
                job: *mut c_void,
                information_class: i32,
                information: *mut c_void,
                information_length: u32,
            ) -> i32;
            fn CloseHandle(handle: *mut c_void) -> i32;
        }

        let handle = unsafe { CreateJobObjectW(std::ptr::null_mut(), std::ptr::null()) };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error());
        }
        let mut information: ExtendedLimitInformation = unsafe { std::mem::zeroed() };
        // Backend descendants do not request breakaway and remain contained.
        // The updater alone uses CREATE_BREAKAWAY_FROM_JOB so it can survive
        // the shell exit that hands control to the installer.
        information.basic_limit_information.limit_flags = WINDOWS_SHELL_JOB_LIMIT_FLAGS;
        let configured = unsafe {
            SetInformationJobObject(
                handle,
                9,
                std::ptr::addr_of_mut!(information).cast(),
                std::mem::size_of::<ExtendedLimitInformation>() as u32,
            )
        };
        if configured == 0 {
            let error = std::io::Error::last_os_error();
            unsafe {
                CloseHandle(handle);
            }
            return Err(error);
        }
        Ok(Self(handle as usize))
    }

    fn assign_current_process(&self) -> std::io::Result<()> {
        use std::ffi::c_void;

        extern "system" {
            fn AssignProcessToJobObject(job: *mut c_void, process: *mut c_void) -> i32;
            fn GetCurrentProcess() -> *mut c_void;
        }
        let process = unsafe { GetCurrentProcess() };
        if unsafe { AssignProcessToJobObject(self.0 as *mut c_void, process) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }
}

#[cfg(windows)]
fn ensure_windows_shell_job() -> std::io::Result<()> {
    match WINDOWS_SHELL_JOB.get_or_init(|| {
        let job = WindowsJobHandle::create().map_err(|error| error.to_string())?;
        job.assign_current_process()
            .map_err(|error| error.to_string())?;
        Ok(job)
    }) {
        Ok(_) => Ok(()),
        Err(message) => Err(std::io::Error::other(message.clone())),
    }
}

#[cfg(windows)]
impl Drop for WindowsJobHandle {
    fn drop(&mut self) {
        use std::ffi::c_void;
        extern "system" {
            fn CloseHandle(handle: *mut c_void) -> i32;
        }
        unsafe {
            CloseHandle(self.0 as *mut c_void);
        }
    }
}

#[derive(Debug)]
struct ContainedCommandChild {
    child: Arc<Mutex<Child>>,
    leader_reaped: Arc<AtomicBool>,
    stdin: Mutex<Option<ChildStdin>>,
    pid: u32,
    containment: SpawnContainment,
}

impl ContainedCommandChild {
    fn pid(&self) -> u32 {
        self.pid
    }

    fn write(&mut self, bytes: &[u8]) -> std::io::Result<()> {
        let mut stdin = self.stdin.lock().unwrap();
        stdin
            .as_mut()
            .ok_or_else(|| {
                std::io::Error::new(std::io::ErrorKind::BrokenPipe, "backend stdin is closed")
            })?
            .write_all(bytes)
    }

    fn kill(&mut self) -> std::io::Result<()> {
        match &self.containment {
            #[cfg(unix)]
            SpawnContainment::PosixGroup { pgid } => {
                let child = self.child.lock().unwrap();
                if self.leader_reaped.load(Ordering::Acquire) {
                    return Err(std::io::Error::other(
                        "backend process-group authority was reaped before termination",
                    ));
                }
                // The Python guardian deliberately remains in this outer group
                // while the application moves into an inner group. SIGTERM asks
                // that guardian to clean the complete tracked tree; SIGKILL
                // would destroy the cleanup authority and strand descendants.
                // Holding the Child lock prevents the waiter from reaping the
                // group leader, so its PID/PGID cannot be reused at this sink.
                signal_unreaped_posix_group(&child, *pgid, 15)?;
            }
            #[cfg(windows)]
            SpawnContainment::WindowsShellJob => {
                let mut child = self.child.lock().unwrap();
                if child.try_wait()?.is_none() {
                    child.kill()?;
                }
            }
        }
        Ok(())
    }

    #[cfg(test)]
    fn wait_for_test(&mut self) -> std::io::Result<ExitStatus> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let status = {
                let mut child = self.child.lock().unwrap();
                let status = child.try_wait()?;
                if status.is_some() {
                    self.leader_reaped.store(true, Ordering::Release);
                }
                status
            };
            if let Some(status) = status {
                return Ok(status);
            }
            if Instant::now() >= deadline {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    "contained test child did not exit",
                ));
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

#[cfg(unix)]
fn signal_unreaped_posix_group(child: &Child, pgid: u32, signal: i32) -> std::io::Result<()> {
    if child.id() != pgid {
        return Err(std::io::Error::other(
            "backend child no longer owns the recorded process group",
        ));
    }
    let raw_pgid = i32::try_from(pgid).map_err(|_| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, "backend PGID exceeds i32")
    })?;
    extern "C" {
        fn kill(pid: i32, signal: i32) -> i32;
    }
    if unsafe { kill(-raw_pgid, signal) } == 0 {
        return Ok(());
    }
    let error = std::io::Error::last_os_error();
    if error.raw_os_error() == Some(3) {
        Ok(())
    } else {
        Err(error)
    }
}

fn spawn_pipe_event_reader<R, F>(
    reader: R,
    sender: tauri::async_runtime::Sender<BackendProcessEvent>,
    event: F,
) -> std::thread::JoinHandle<()>
where
    R: Read + Send + 'static,
    F: Fn(Vec<u8>) -> BackendProcessEvent + Send + 'static,
{
    std::thread::spawn(move || {
        let mut reader = BufReader::new(reader);
        loop {
            let mut bytes = Vec::new();
            match reader.read_until(b'\n', &mut bytes) {
                Ok(0) => return,
                Ok(_) => {
                    if sender.blocking_send(event(bytes)).is_err() {
                        return;
                    }
                }
                Err(error) => {
                    let _ = sender.blocking_send(BackendProcessEvent::Error(error.to_string()));
                    return;
                }
            }
        }
    })
}

#[cfg(unix)]
fn request_unpublished_posix_cleanup(child: &mut Child, pgid: u32) -> bool {
    if signal_unreaped_posix_group(child, pgid, 15).is_err() {
        let _ = child.kill();
        return wait_for_child_exit_bounded(child, SIDECAR_KILL_CONFIRM_TIMEOUT);
    }
    // The backend may already have forked its guardian. Give that guardian a
    // catchable request so it can clean any inner group instead of killing the
    // cleanup authority itself.
    let mut last_warning = Instant::now();
    let deadline = Instant::now() + SIDECAR_FORCE_EXIT_TIMEOUT;
    loop {
        if spawn_containment_liveness(pgid) == ProcessLiveness::Dead {
            let _ = child.try_wait();
            return true;
        }
        if Instant::now() >= deadline {
            eprintln!(
                "[flinttrade] unrecorded backend containment did not exit within the cleanup budget"
            );
            return false;
        }
        if last_warning.elapsed() >= Duration::from_secs(1) {
            eprintln!(
                "[flinttrade] unrecorded backend containment is still alive; startup remains blocked"
            );
            let _ = signal_unreaped_posix_group(child, pgid, 15);
            last_warning = Instant::now();
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn wait_for_child_exit_bounded(child: &mut Child, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => return true,
            Err(_) => return false,
            Ok(None) => {}
        }
        if Instant::now() >= deadline {
            return false;
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

fn retain_unpublished_cleanup_authority<F, W>(mut cleanup: F, mut wait: W)
where
    F: FnMut() -> bool,
    W: FnMut(),
{
    while !cleanup() {
        eprintln!(
            "[flinttrade] unrecorded backend ownership remains unresolved; retaining the instance lock"
        );
        wait();
    }
}

fn cleanup_failed_spawn(child: &mut Child, containment: &SpawnContainment) -> bool {
    match containment {
        #[cfg(unix)]
        SpawnContainment::PosixGroup { pgid } => request_unpublished_posix_cleanup(child, *pgid),
        #[cfg(windows)]
        SpawnContainment::WindowsShellJob => {
            let _ = child.kill();
            wait_for_child_exit_bounded(child, SIDECAR_KILL_CONFIRM_TIMEOUT)
        }
    }
}

fn terminate_unrecorded_sidecar(child: &mut ContainedCommandChild) -> bool {
    let sidecar_pid = child.pid();
    let _ = child.write(SIDECAR_FORCE_EXIT_COMMAND);
    let mut last_warning = Instant::now();
    let deadline = Instant::now() + SIDECAR_FORCE_EXIT_TIMEOUT;
    loop {
        let _ = child.kill();
        #[cfg(unix)]
        let exited = wait_for_spawn_containment_exit(sidecar_pid, Duration::from_millis(250));
        #[cfg(windows)]
        let exited = wait_for_process_exit(sidecar_pid, Duration::from_millis(250));
        if exited {
            return true;
        }
        if Instant::now() >= deadline {
            eprintln!("[flinttrade] unrecorded backend did not exit within the cleanup budget");
            return false;
        }
        if last_warning.elapsed() >= Duration::from_secs(1) {
            eprintln!("[flinttrade] unrecorded backend is still alive; startup remains blocked");
            last_warning = Instant::now();
        }
    }
}

fn spawn_contained_std_command(
    mut command: StdCommand,
) -> std::io::Result<(
    tauri::async_runtime::Receiver<BackendProcessEvent>,
    ContainedCommandChild,
)> {
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        ensure_windows_shell_job()?;
        // Children of a process in a non-breakaway Job enter that Job as part
        // of process creation, leaving no spawn-to-assignment crash window.
        command.creation_flags(WINDOWS_BACKEND_CREATION_FLAGS);
    }

    let mut child = command.spawn()?;
    let pid = child.id();

    #[cfg(unix)]
    let containment = {
        extern "C" {
            fn getpgid(pid: i32) -> i32;
        }
        let raw_pid = i32::try_from(pid).map_err(|_| {
            std::io::Error::new(std::io::ErrorKind::InvalidInput, "backend PID exceeds i32")
        })?;
        if unsafe { getpgid(raw_pid) } != raw_pid {
            let _ = child.kill();
            let _ = child.wait();
            return Err(std::io::Error::other(
                "backend did not enter its spawn-owned process group",
            ));
        }
        match unix_process_start_token(pid) {
            Ok(Some(_)) => {}
            Ok(None) => {
                retain_unpublished_cleanup_authority(
                    || request_unpublished_posix_cleanup(&mut child, pid),
                    || std::thread::sleep(Duration::from_millis(100)),
                );
                return Err(std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "backend process identity disappeared immediately after spawn",
                ));
            }
            Err(error) => {
                retain_unpublished_cleanup_authority(
                    || request_unpublished_posix_cleanup(&mut child, pid),
                    || std::thread::sleep(Duration::from_millis(100)),
                );
                return Err(error);
            }
        }
        SpawnContainment::PosixGroup { pgid: pid }
    };
    #[cfg(windows)]
    let containment = SpawnContainment::WindowsShellJob;

    let stdin = child.stdin.take();
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            retain_unpublished_cleanup_authority(
                || cleanup_failed_spawn(&mut child, &containment),
                || std::thread::sleep(Duration::from_millis(100)),
            );
            return Err(std::io::Error::new(
                std::io::ErrorKind::BrokenPipe,
                "backend stdout pipe is unavailable",
            ));
        }
    };
    let stderr = match child.stderr.take() {
        Some(stderr) => stderr,
        None => {
            retain_unpublished_cleanup_authority(
                || cleanup_failed_spawn(&mut child, &containment),
                || std::thread::sleep(Duration::from_millis(100)),
            );
            return Err(std::io::Error::new(
                std::io::ErrorKind::BrokenPipe,
                "backend stderr pipe is unavailable",
            ));
        }
    };
    let child = Arc::new(Mutex::new(child));
    let leader_reaped = Arc::new(AtomicBool::new(false));
    let (sender, receiver) = tauri::async_runtime::channel(64);
    let stdout_reader =
        spawn_pipe_event_reader(stdout, sender.clone(), BackendProcessEvent::Stdout);
    let stderr_reader =
        spawn_pipe_event_reader(stderr, sender.clone(), BackendProcessEvent::Stderr);
    let wait_child = Arc::clone(&child);
    let wait_leader_reaped = Arc::clone(&leader_reaped);
    std::thread::spawn(move || {
        let status = loop {
            let wait_result = {
                let mut child = wait_child.lock().unwrap();
                match child.try_wait() {
                    Ok(Some(status)) => {
                        wait_leader_reaped.store(true, Ordering::Release);
                        Some(Ok(status))
                    }
                    Ok(None) => None,
                    Err(error) => Some(Err(error)),
                }
            };
            match wait_result {
                Some(result) => break result,
                None => std::thread::sleep(Duration::from_millis(20)),
            }
        };
        let _ = stdout_reader.join();
        let _ = stderr_reader.join();
        let event = match status {
            Ok(status) => BackendProcessEvent::Terminated(BackendExit {
                code: status.code(),
                #[cfg(unix)]
                signal: {
                    use std::os::unix::process::ExitStatusExt;
                    status.signal()
                },
                #[cfg(windows)]
                signal: None,
            }),
            Err(error) => BackendProcessEvent::Error(error.to_string()),
        };
        let _ = sender.blocking_send(event);
    });

    Ok((
        receiver,
        ContainedCommandChild {
            child,
            leader_reaped,
            stdin: Mutex::new(stdin),
            pid,
            containment,
        },
    ))
}

struct ManagedSidecar {
    child: ContainedCommandChild,
    record: SidecarRecord,
    pending_exit_acknowledged: Arc<AtomicBool>,
    cleanup_complete_acknowledged: Arc<AtomicBool>,
    shutdown_identity_tracker: ShutdownProcessIdentityTracker,
}

/// Holds the spawned backend child and its exact recovery record so cleanup
/// cannot remove a replacement process's record.
struct BackendState(Mutex<Option<ManagedSidecar>>);

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

/// Payload of the ``check_native_update`` command.
#[derive(serde::Serialize)]
struct NativeUpdateCheck {
    /// Whether the signed updater feed offers a newer build for this platform.
    available: bool,
    /// Version offered by the feed, when an update is available.
    version: Option<String>,
    /// Release notes from the feed, when an update is available.
    notes: Option<String>,
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

/// Rolling Tauri-updater manifest URL for this build's release channel: beta
/// when the compiled version carries a pre-release suffix, stable otherwise.
/// Chosen at runtime so one binary follows exactly its own channel.
fn native_update_endpoint() -> String {
    let channel = if env!("CARGO_PKG_VERSION").contains('-') {
        "beta"
    } else {
        "stable"
    };
    format!(
        "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/updater-{channel}/latest.json"
    )
}

/// Build a signed-updater handle pinned to this build's release channel.
///
/// Errors are logged in full but returned redacted — updater failures can
/// embed URLs and transport detail that do not belong in the Settings UI.
fn build_native_updater(app: &AppHandle) -> Result<tauri_plugin_updater::Updater, String> {
    let endpoint = native_update_endpoint()
        .parse::<tauri::Url>()
        .map_err(|e| {
            eprintln!("[flinttrade] invalid native updater endpoint: {e}");
            "The update endpoint compiled into this build is invalid.".to_string()
        })?;
    app.updater_builder()
        .endpoints(vec![endpoint])
        .map_err(|e| {
            eprintln!("[flinttrade] native updater endpoint rejected: {e}");
            "The native updater is unavailable in this build.".to_string()
        })?
        .build()
        .map_err(|e| {
            eprintln!("[flinttrade] native updater unavailable: {e}");
            "The native updater is unavailable in this build.".to_string()
        })
}

/// Redacted, user-safe message for a failed updater feed check.
fn native_check_failed(e: tauri_plugin_updater::Error) -> String {
    eprintln!("[flinttrade] native update check failed: {e}");
    "Could not check for a native update — the update feed is unreachable or this build cannot verify it."
        .to_string()
}

/// Check the signed updater feed for a newer desktop build. The terminal
/// falls back to the installer-script flow when this command fails
/// (unsigned or dev builds, older shells, unsupported package formats).
#[tauri::command]
async fn check_native_update(app: AppHandle) -> Result<NativeUpdateCheck, String> {
    let updater = build_native_updater(&app)?;
    match updater.check().await {
        Ok(Some(update)) => Ok(NativeUpdateCheck {
            available: true,
            version: Some(update.version.clone()),
            notes: update.body.clone(),
        }),
        Ok(None) => Ok(NativeUpdateCheck {
            available: false,
            version: None,
            notes: None,
        }),
        Err(e) => Err(native_check_failed(e)),
    }
}

/// Download, signature-verify, and install the native update in place, then
/// restart the app. ``restart`` marks the quit as deliberate first so the
/// close-to-tray handler cannot intercept the swap; it never returns.
#[tauri::command]
async fn apply_native_update(app: AppHandle) -> Result<(), String> {
    let updater = build_native_updater(&app)?;
    let update = match updater.check().await {
        Ok(Some(update)) => update,
        Ok(None) => return Err("No update is available.".to_string()),
        Err(e) => return Err(native_check_failed(e)),
    };
    update
        .download_and_install(|_chunk_len, _content_len| {}, || {})
        .await
        .map_err(|e| {
            eprintln!("[flinttrade] native update install failed: {e}");
            "The update could not be downloaded and verified — nothing was changed. Please try again."
                .to_string()
        })?;
    mark_quit_requested(&app);
    app.restart()
}

// ---------------------------------------------------------------------------
// Managed backend payload runtime.
//
// Daily releases publish one frozen backend payload (which embeds the built
// terminal) per target triple next to the rolling channel manifest. The shell
// stages a downloaded payload under ``<workspace>/runtime/backend/<version>/``,
// pins its sha256 in ``state.json``, and boots that binary — it is the ONLY
// backend source; the installer bundles no sidecar. Routine backend+frontend
// updates therefore need no installer cycle. When nothing verifies at boot
// (first run, or a broken pin that gets demoted), the splash-phase bootstrap
// below downloads a fresh payload with progress reporting. A bad payload can
// never crash-loop the app: any mismatch, spawn failure, or pre-ready exit
// demotes the pin and lands on the splash error surface with a Retry action.
// ---------------------------------------------------------------------------

/// Target triple this shell was compiled for, as emitted by ``tauri-build``.
/// The channel manifest keys its backend payloads by exactly this string.
const PAYLOAD_TARGET_TRIPLE: &str = env!("TAURI_ENV_TARGET_TRIPLE");

/// State file inside the payload runtime dir pinning the active version and
/// the sha256 its binary must still hash to at boot.
const PAYLOAD_STATE_FILE: &str = "state.json";

/// Staging directory (inside the payload runtime dir) for in-flight
/// downloads, so a torn download can never be mistaken for an installed
/// payload.
const PAYLOAD_STAGING_DIR: &str = ".staging";

/// File name of the frozen backend binary inside a per-version payload dir.
#[cfg(windows)]
const PAYLOAD_BINARY_NAME: &str = "flinttrade-backend.exe";
#[cfg(not(windows))]
const PAYLOAD_BINARY_NAME: &str = "flinttrade-backend";

/// Pinned managed-payload state (``runtime/backend/state.json``).
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
struct PayloadState {
    active_version: String,
    sha256: String,
}

/// One per-triple backend payload entry from the channel release manifest.
#[derive(Debug, Clone, serde::Deserialize)]
struct PayloadManifestEntry {
    name: String,
    size: u64,
    url: String,
    sha256: String,
}

/// The slice of ``flinttrade-desktop-manifest.json`` the payload updater
/// reads (unknown fields are ignored).
#[derive(Debug, serde::Deserialize)]
struct PayloadManifest {
    version: String,
    #[serde(default)]
    payloads: std::collections::HashMap<String, PayloadManifestEntry>,
}

/// Payload of the ``check_payload_update`` command.
#[derive(serde::Serialize)]
struct PayloadUpdateCheck {
    /// Whether the channel manifest offers a payload differing from the
    /// currently active backend version.
    available: bool,
    /// Version offered by the channel, when an update is available.
    version: Option<String>,
    /// Download size in bytes, when an update is available.
    size: Option<u64>,
}

/// Accept only version strings safe to use as a payload directory name (the
/// manifest version, e.g. ``0.7.0`` or ``0.7.0-beta.2``). Rejects anything
/// that could traverse out of the runtime dir or hide as a dotfile.
fn valid_payload_version(version: &str) -> bool {
    !version.is_empty()
        && version.len() <= 64
        && !version.starts_with('.')
        && !version.starts_with('-')
        && version
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '+')
}

/// Accept only a 64-character hex sha256 digest.
fn valid_payload_sha256(digest: &str) -> bool {
    digest.len() == 64 && digest.chars().all(|c| c.is_ascii_hexdigit())
}

/// Root of the managed payload runtime inside the workspace dir.
fn payload_runtime_dir() -> Option<PathBuf> {
    flinttrade_home().map(|d| d.join("runtime").join("backend"))
}

/// Parse and validate ``state.json`` contents. ``None`` covers both malformed
/// JSON and a version/digest that fails the directory-safety pins.
fn parse_payload_state(contents: &str) -> Option<PayloadState> {
    let state: PayloadState = serde_json::from_str(contents).ok()?;
    if !valid_payload_version(&state.active_version) || !valid_payload_sha256(&state.sha256) {
        return None;
    }
    Some(state)
}

/// The payload version currently pinned active, if a valid pin exists.
fn active_payload_version() -> Option<String> {
    let runtime_dir = payload_runtime_dir()?;
    let contents = std::fs::read_to_string(runtime_dir.join(PAYLOAD_STATE_FILE)).ok()?;
    parse_payload_state(&contents).map(|state| state.active_version)
}

/// Streaming sha256 of a file, hex-encoded lowercase.
fn sha256_file(path: &Path) -> std::io::Result<String> {
    use sha2::{Digest, Sha256};

    let mut file = std::fs::File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(to_hex(hasher.finalize().as_slice()))
}

/// Resolve the staged payload binary named by ``state.json`` after verifying
/// its on-disk sha256 still matches the pinned digest.
///
/// ``Ok(None)`` means no managed payload is installed (first run — the
/// splash bootstrap downloads one); ``Err`` means a payload was pinned but
/// failed verification, which the caller demotes before re-downloading.
fn verified_active_payload_binary_at(
    runtime_dir: &Path,
) -> std::io::Result<Option<(String, PathBuf)>> {
    let state_path = runtime_dir.join(PAYLOAD_STATE_FILE);
    if !state_path.is_file() {
        return Ok(None);
    }
    let contents = std::fs::read_to_string(&state_path)?;
    let Some(state) = parse_payload_state(&contents) else {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "managed payload state is invalid",
        ));
    };
    let binary = runtime_dir
        .join(&state.active_version)
        .join(PAYLOAD_BINARY_NAME);
    if !binary.is_file() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!(
                "managed payload binary for v{} is missing",
                state.active_version
            ),
        ));
    }
    let digest = sha256_file(&binary)?;
    if !digest.eq_ignore_ascii_case(&state.sha256) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!(
                "managed payload binary for v{} failed its sha256 pin",
                state.active_version
            ),
        ));
    }
    Ok(Some((state.active_version, binary)))
}

/// [`verified_active_payload_binary_at`] rooted at the workspace runtime dir.
fn verified_active_payload_binary() -> std::io::Result<Option<(String, PathBuf)>> {
    let Some(runtime_dir) = payload_runtime_dir() else {
        return Ok(None);
    };
    verified_active_payload_binary_at(&runtime_dir)
}

/// Remove the managed-payload pin so the next boot attempt re-runs the
/// splash bootstrap and downloads a fresh channel payload. Returns whether a
/// pin was actually removed.
fn demote_active_payload() -> bool {
    let Some(runtime_dir) = payload_runtime_dir() else {
        return false;
    };
    match std::fs::remove_file(runtime_dir.join(PAYLOAD_STATE_FILE)) {
        Ok(()) => true,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => {
            eprintln!("[flinttrade] could not demote the managed backend payload: {error}");
            false
        }
    }
}

/// Atomically publish ``state.json``: write a temp file, flush it to disk,
/// then rename over the previous state so a crash can never leave a torn pin.
fn write_payload_state_at(runtime_dir: &Path, state: &PayloadState) -> std::io::Result<()> {
    let serialised = serde_json::to_string_pretty(state).map_err(std::io::Error::other)?;
    let temp_path = runtime_dir.join(format!("{PAYLOAD_STATE_FILE}.tmp"));
    {
        let mut file = std::fs::File::create(&temp_path)?;
        file.write_all(serialised.as_bytes())?;
        file.write_all(b"\n")?;
        file.sync_all()?;
    }
    std::fs::rename(&temp_path, runtime_dir.join(PAYLOAD_STATE_FILE))
}

/// Remove every directory under the runtime dir except the retained versions
/// (this also clears the staging dir). Failures are logged, never fatal —
/// pruning is housekeeping, not correctness.
fn prune_payload_versions_at(runtime_dir: &Path, retained: &[&str]) {
    let Ok(entries) = std::fs::read_dir(runtime_dir) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if retained.contains(&name) {
            continue;
        }
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        if let Err(error) = std::fs::remove_dir_all(&path) {
            eprintln!("[flinttrade] could not prune old backend payload {name}: {error}");
        }
    }
}

/// Rolling channel manifest URL for this build's release channel — the same
/// beta/stable split as the native updater feed.
fn payload_manifest_endpoint() -> String {
    let channel = if env!("CARGO_PKG_VERSION").contains('-') {
        "beta"
    } else {
        "stable"
    };
    format!(
        "https://github.com/navaneeshnagarajan/FlintTrade/releases/download/updater-{channel}/flinttrade-desktop-manifest.json"
    )
}

fn parse_payload_manifest(contents: &str) -> Result<PayloadManifest, serde_json::Error> {
    serde_json::from_str(contents)
}

/// HTTP client for payload downloads, sharing the rustls stack (and its ring
/// crypto-provider bootstrap) with the updater plugin already in this binary.
fn payload_http_client() -> Result<reqwest::Client, String> {
    if rustls::crypto::CryptoProvider::get_default().is_none() {
        // Failure means a provider was installed concurrently, which is fine.
        let _ = rustls::crypto::ring::default_provider().install_default();
    }
    reqwest::Client::builder()
        .user_agent(concat!("flinttrade-desktop/", env!("CARGO_PKG_VERSION")))
        .connect_timeout(Duration::from_secs(30))
        .read_timeout(Duration::from_secs(60))
        .build()
        .map_err(|e| {
            eprintln!("[flinttrade] payload HTTP client unavailable: {e}");
            "The backend payload updater is unavailable in this build.".to_string()
        })
}

/// Fetch and parse the rolling channel manifest. Errors are logged in full
/// but returned redacted, matching the native updater commands.
async fn fetch_payload_manifest(client: &reqwest::Client) -> Result<PayloadManifest, String> {
    let unreachable = || {
        "Could not check for a backend update — the update feed is unreachable or returned an unexpected response."
            .to_string()
    };
    let response = client
        .get(payload_manifest_endpoint())
        .send()
        .await
        .map_err(|e| {
            eprintln!("[flinttrade] payload manifest fetch failed: {e}");
            unreachable()
        })?;
    if !response.status().is_success() {
        eprintln!(
            "[flinttrade] payload manifest fetch returned HTTP {}",
            response.status()
        );
        return Err(unreachable());
    }
    let body = response.text().await.map_err(|e| {
        eprintln!("[flinttrade] payload manifest read failed: {e}");
        unreachable()
    })?;
    parse_payload_manifest(&body).map_err(|e| {
        eprintln!("[flinttrade] payload manifest parse failed: {e}");
        unreachable()
    })
}

/// Select and validate this build's target-triple payload entry from a
/// channel manifest. Shared by the Settings updater (``apply_payload_update``)
/// and the first-run splash bootstrap.
fn resolve_manifest_payload(
    manifest: &PayloadManifest,
) -> Result<(String, &PayloadManifestEntry), String> {
    let Some(entry) = manifest.payloads.get(PAYLOAD_TARGET_TRIPLE) else {
        eprintln!(
            "[flinttrade] channel manifest carries no backend payload for {PAYLOAD_TARGET_TRIPLE}"
        );
        return Err("No backend payload is published for this platform.".to_string());
    };
    if !valid_payload_version(&manifest.version) || !valid_payload_sha256(&entry.sha256) {
        eprintln!(
            "[flinttrade] channel manifest payload entry is malformed (version {:?})",
            manifest.version
        );
        return Err(
            "The published backend payload is malformed — nothing was changed.".to_string(),
        );
    }
    Ok((manifest.version.clone(), entry))
}

/// Download a payload entry into a fresh staging dir with a streaming sha256
/// check. Returns the staged file path; any failure removes the staging dir.
/// ``on_progress`` is called with the running byte count after every accepted
/// chunk so callers can render download progress.
async fn stage_payload_download(
    client: &reqwest::Client,
    runtime_dir: &Path,
    entry: &PayloadManifestEntry,
    mut on_progress: impl FnMut(u64),
) -> Result<PathBuf, String> {
    use sha2::{Digest, Sha256};

    let failed = || {
        "The backend update could not be downloaded and verified — nothing was changed. Please try again."
            .to_string()
    };
    let staging_dir = runtime_dir.join(PAYLOAD_STAGING_DIR);
    // A fresh staging dir per attempt: a torn earlier download must never
    // contaminate this one.
    if staging_dir.exists() {
        std::fs::remove_dir_all(&staging_dir).map_err(|e| {
            eprintln!("[flinttrade] could not clear the payload staging dir: {e}");
            failed()
        })?;
    }
    std::fs::create_dir_all(&staging_dir).map_err(|e| {
        eprintln!("[flinttrade] could not create the payload staging dir: {e}");
        failed()
    })?;
    let staged = staging_dir.join(PAYLOAD_BINARY_NAME);
    let result = async {
        let mut response = client.get(&entry.url).send().await.map_err(|e| {
            eprintln!("[flinttrade] payload download failed to start: {e}");
            failed()
        })?;
        if !response.status().is_success() {
            eprintln!(
                "[flinttrade] payload download returned HTTP {}",
                response.status()
            );
            return Err(failed());
        }
        let mut file = std::fs::File::create(&staged).map_err(|e| {
            eprintln!("[flinttrade] could not create the staged payload file: {e}");
            failed()
        })?;
        let mut hasher = Sha256::new();
        let mut downloaded: u64 = 0;
        while let Some(chunk) = response.chunk().await.map_err(|e| {
            eprintln!("[flinttrade] payload download stream failed: {e}");
            failed()
        })? {
            downloaded = downloaded.saturating_add(chunk.len() as u64);
            if downloaded > entry.size {
                eprintln!(
                    "[flinttrade] payload download exceeded its declared size of {} bytes",
                    entry.size
                );
                return Err(failed());
            }
            hasher.update(&chunk);
            file.write_all(&chunk).map_err(|e| {
                eprintln!("[flinttrade] could not write the staged payload: {e}");
                failed()
            })?;
            on_progress(downloaded);
        }
        if downloaded != entry.size {
            eprintln!(
                "[flinttrade] payload download was {downloaded} bytes, expected {}",
                entry.size
            );
            return Err(failed());
        }
        let digest = to_hex(hasher.finalize().as_slice());
        if !digest.eq_ignore_ascii_case(&entry.sha256) {
            eprintln!("[flinttrade] payload {} failed its sha256 pin", entry.name);
            return Err(failed());
        }
        file.sync_all().map_err(|e| {
            eprintln!("[flinttrade] could not flush the staged payload: {e}");
            failed()
        })?;
        Ok(staged.clone())
    }
    .await;
    if result.is_err() {
        let _ = std::fs::remove_dir_all(&staging_dir);
    }
    result
}

/// Move a verified staged payload into its per-version dir, make it
/// executable, pin it in ``state.json``, and prune superseded versions —
/// keeping exactly the new payload and its immediate predecessor.
fn install_staged_payload(
    runtime_dir: &Path,
    version: &str,
    staged: &Path,
    sha256: &str,
    previous_version: Option<&str>,
) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(staged, std::fs::Permissions::from_mode(0o755))?;
    }
    let version_dir = runtime_dir.join(version);
    std::fs::create_dir_all(&version_dir)?;
    let binary = version_dir.join(PAYLOAD_BINARY_NAME);
    // Windows cannot rename over an existing file; a same-version reinstall
    // replaces the previous binary explicitly.
    if binary.exists() {
        std::fs::remove_file(&binary)?;
    }
    std::fs::rename(staged, &binary)?;
    write_payload_state_at(
        runtime_dir,
        &PayloadState {
            active_version: version.to_string(),
            sha256: sha256.to_ascii_lowercase(),
        },
    )?;
    let mut retained = vec![version, PAYLOAD_STATE_FILE];
    if let Some(previous) = previous_version {
        retained.push(previous);
    }
    prune_payload_versions_at(runtime_dir, &retained);
    Ok(())
}

/// Check the rolling channel manifest for a backend payload differing from
/// the currently active one (the pinned managed payload, else this shell's
/// own version while no payload is installed yet).
#[tauri::command]
async fn check_payload_update(app: AppHandle) -> Result<PayloadUpdateCheck, String> {
    let client = payload_http_client()?;
    let manifest = fetch_payload_manifest(&client).await?;
    let none = PayloadUpdateCheck {
        available: false,
        version: None,
        size: None,
    };
    let Some(entry) = manifest.payloads.get(PAYLOAD_TARGET_TRIPLE) else {
        eprintln!(
            "[flinttrade] channel manifest carries no backend payload for {PAYLOAD_TARGET_TRIPLE}"
        );
        return Ok(none);
    };
    let active = active_payload_version().unwrap_or_else(|| app.package_info().version.to_string());
    if manifest.version == active {
        return Ok(none);
    }
    Ok(PayloadUpdateCheck {
        available: true,
        version: Some(manifest.version),
        size: Some(entry.size),
    })
}

/// Download, hash-verify, and stage the channel's backend payload, pin it in
/// ``state.json``, prune superseded versions, then restart the app onto it.
/// ``restart`` marks the quit as deliberate first (mirroring
/// ``apply_native_update``) so close-to-tray cannot intercept the swap; it
/// never returns.
#[tauri::command]
async fn apply_payload_update(app: AppHandle) -> Result<(), String> {
    let client = payload_http_client()?;
    let manifest = fetch_payload_manifest(&client).await?;
    let (version, entry) = resolve_manifest_payload(&manifest)?;
    let previous = active_payload_version();
    let active = previous
        .clone()
        .unwrap_or_else(|| app.package_info().version.to_string());
    if version == active {
        return Err("No backend update is available.".to_string());
    }
    let runtime_dir = payload_runtime_dir()
        .ok_or_else(|| "Could not resolve the FlintTrade workspace directory.".to_string())?;
    let staged = stage_payload_download(&client, &runtime_dir, entry, |_| {}).await?;
    install_staged_payload(
        &runtime_dir,
        &version,
        &staged,
        &entry.sha256,
        previous.as_deref(),
    )
    .map_err(|e| {
        eprintln!("[flinttrade] managed payload install failed: {e}");
        "The backend update could not be installed — nothing was changed. Please try again."
            .to_string()
    })?;
    mark_quit_requested(&app);
    app.restart()
}

// ---------------------------------------------------------------------------
// First-run bootstrap.
//
// The installer ships only this shell. The first boot (and any boot whose
// payload no longer verifies) downloads the channel's hash-verified backend
// payload INSIDE the splash phase, streaming ``bootstrap://status`` progress
// events to the splash webview. Every failure — offline, HTTP error, hash
// mismatch, spawn failure, pre-ready exit — parks the app on the splash
// error surface with a Retry action; nothing here can crash-loop.
// ---------------------------------------------------------------------------

/// Splash event channel carrying bootstrap progress and errors.
const BOOTSTRAP_STATUS_EVENT: &str = "bootstrap://status";

/// One ``bootstrap://status`` event payload rendered by the splash page.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
struct BootstrapStatus {
    /// ``resolving-manifest`` → ``downloading`` → ``verifying`` →
    /// ``installing`` → ``starting``, or ``error``.
    phase: &'static str,
    /// Percentage complete, present only while it is meaningful
    /// (the downloading/verifying phases with a known total).
    pct: Option<u8>,
    /// Human-readable status line (British English) for the splash.
    message: String,
}

/// Coarse bootstrap lifecycle guarding the splash Retry action.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BootstrapStage {
    /// A bootstrap attempt (payload download and/or backend start) is in
    /// flight.
    Running,
    /// The last attempt failed; the splash Retry action may begin another.
    Failed,
    /// A backend spawned and its supervision task owns the lifecycle.
    Started,
}

/// Bootstrap lifecycle stage plus the most recent status event, kept so the
/// splash can pull a status it missed (events emitted before its listener
/// registered are otherwise lost).
struct BootstrapState {
    stage: Mutex<BootstrapStage>,
    last_status: Mutex<Option<BootstrapStatus>>,
}

impl BootstrapState {
    fn new() -> Self {
        Self {
            stage: Mutex::new(BootstrapStage::Running),
            last_status: Mutex::new(None),
        }
    }
}

/// The only admissible Retry transition is ``Failed -> Running``: a retry
/// during a live attempt would race the download, and one after a successful
/// start would spawn a second backend.
fn bootstrap_retry_transition(current: BootstrapStage) -> Result<BootstrapStage, &'static str> {
    match current {
        BootstrapStage::Failed => Ok(BootstrapStage::Running),
        BootstrapStage::Running => Err("a bootstrap attempt is already running"),
        BootstrapStage::Started => Err("the backend has already started"),
    }
}

fn set_bootstrap_stage(app: &AppHandle, stage: BootstrapStage) {
    if let Some(state) = app.try_state::<BootstrapState>() {
        *state.stage.lock().unwrap() = stage;
    }
}

/// Admit (or refuse) a splash Retry request.
fn begin_bootstrap_retry(app: &AppHandle) -> Result<(), String> {
    let state = app
        .try_state::<BootstrapState>()
        .ok_or_else(|| "bootstrap state is unavailable".to_string())?;
    let mut stage = state.stage.lock().unwrap();
    *stage = bootstrap_retry_transition(*stage).map_err(str::to_string)?;
    Ok(())
}

/// Record and emit one bootstrap status event to the splash webview.
fn emit_bootstrap_status(app: &AppHandle, status: BootstrapStatus) {
    if let Some(state) = app.try_state::<BootstrapState>() {
        *state.last_status.lock().unwrap() = Some(status.clone());
    }
    let _ = app.emit_to("splash", BOOTSTRAP_STATUS_EVENT, status);
}

/// One-decimal-place decimal-megabyte label for download progress.
fn format_megabytes(bytes: u64) -> String {
    format!("{:.1} MB", bytes as f64 / 1_000_000.0)
}

/// Shape the downloading-phase splash status for ``downloaded`` of ``total``
/// bytes. ``pct`` is ``None`` when the total is unknown (zero).
fn download_progress_status(downloaded: u64, total: u64) -> BootstrapStatus {
    if total == 0 {
        return BootstrapStatus {
            phase: "downloading",
            pct: None,
            message: format!(
                "Downloading the trading engine — {}",
                format_megabytes(downloaded)
            ),
        };
    }
    let capped = downloaded.min(total);
    let pct = ((capped as u128 * 100) / total as u128) as u8;
    BootstrapStatus {
        phase: "downloading",
        pct: Some(pct),
        message: format!(
            "Downloading the trading engine — {} of {}",
            format_megabytes(capped),
            format_megabytes(total)
        ),
    }
}

/// Ensure a verified managed backend payload is installed, downloading this
/// channel's payload when none is (first run) or when the installed one no
/// longer verifies (broken pin, demoted first). Streams progress to the
/// splash while it works; reuses the exact manifest/download/verify/install
/// helpers behind Settings → ``apply_payload_update``.
async fn ensure_bootstrap_payload(app: &AppHandle) -> Result<(), String> {
    match verified_active_payload_binary() {
        Ok(Some(_)) => return Ok(()),
        Ok(None) => {}
        Err(error) => {
            eprintln!(
                "[flinttrade] managed backend payload verification failed: {error}; downloading a fresh payload"
            );
            demote_active_payload();
        }
    }
    emit_bootstrap_status(
        app,
        BootstrapStatus {
            phase: "resolving-manifest",
            pct: None,
            message: "Finding the latest trading engine...".to_string(),
        },
    );
    let client = payload_http_client()?;
    let manifest = fetch_payload_manifest(&client).await?;
    let (version, entry) = resolve_manifest_payload(&manifest)?;
    let runtime_dir = payload_runtime_dir()
        .ok_or_else(|| "Could not resolve the FlintTrade workspace directory.".to_string())?;
    emit_bootstrap_status(app, download_progress_status(0, entry.size));
    let progress_app = app.clone();
    let total = entry.size;
    // Re-emit only when the rendered percentage moves, so a large download
    // does not flood the splash with per-chunk IPC events.
    let mut last_key: Option<(&'static str, Option<u8>)> = None;
    let staged = stage_payload_download(&client, &runtime_dir, entry, move |downloaded| {
        let status = if total > 0 && downloaded >= total {
            // The final digest comparison and flush are all that remain
            // inside the staging helper once the last chunk has landed.
            BootstrapStatus {
                phase: "verifying",
                pct: Some(100),
                message: "Verifying the download...".to_string(),
            }
        } else {
            download_progress_status(downloaded, total)
        };
        let key = (status.phase, status.pct);
        if last_key != Some(key) {
            last_key = Some(key);
            emit_bootstrap_status(&progress_app, status);
        }
    })
    .await?;
    emit_bootstrap_status(
        app,
        BootstrapStatus {
            phase: "installing",
            pct: None,
            message: format!("Installing engine v{version}..."),
        },
    );
    install_staged_payload(
        &runtime_dir,
        &version,
        &staged,
        &entry.sha256,
        active_payload_version().as_deref(),
    )
    .map_err(|e| {
        eprintln!("[flinttrade] managed payload install failed: {e}");
        "The trading engine could not be installed — nothing was changed. Please try again."
            .to_string()
    })?;
    Ok(())
}

/// Drive one boot attempt end-to-end: install the payload if missing (with
/// splash progress), then spawn and supervise it. Failures land in the
/// splash error state — never a crash loop; the operator retries explicitly.
async fn run_bootstrap(app: AppHandle) {
    let result = match ensure_bootstrap_payload(&app).await {
        Ok(()) => {
            emit_bootstrap_status(
                &app,
                BootstrapStatus {
                    phase: "starting",
                    pct: None,
                    message: "Starting the trading engine...".to_string(),
                },
            );
            start_managed_backend(&app)
        }
        Err(message) => Err(message),
    };
    if let Err(message) = result {
        fail_bootstrap(&app, message);
    }
}

/// Park the bootstrap in its failed state and surface the splash error UI.
fn fail_bootstrap(app: &AppHandle, message: String) {
    set_bootstrap_stage(app, BootstrapStage::Failed);
    emit_bootstrap_status(
        app,
        BootstrapStatus {
            phase: "error",
            pct: None,
            message,
        },
    );
}

/// Return the splash to its actionable error state after a freshly booted
/// payload died before its ready handshake. The main window only exists after
/// the handshake, so the splash is still on screen; its pin has already been
/// demoted, so a Retry downloads a fresh payload instead of relaunching the
/// broken one (there is no bundled backend to restart onto).
fn surface_bootstrap_retry(app: &AppHandle) {
    if quit_was_requested(app) {
        return;
    }
    fail_bootstrap(
        app,
        "The trading engine stopped before it finished starting. Retry to download a fresh copy."
            .to_string(),
    );
}

/// Splash Retry action: re-run the bootstrap after a failed attempt.
#[tauri::command]
async fn retry_bootstrap(app: AppHandle) -> Result<(), String> {
    begin_bootstrap_retry(&app)?;
    run_bootstrap(app).await;
    Ok(())
}

/// Splash pull of the latest bootstrap status, covering the race where a
/// status event fired before the splash page registered its listener.
#[tauri::command]
fn bootstrap_status(app: AppHandle) -> Option<BootstrapStatus> {
    app.try_state::<BootstrapState>()
        .and_then(|state| state.last_status.lock().unwrap().clone())
}

fn schedule_update_exit(app: &AppHandle) {
    // Mark the quit as deliberate (close-to-tray must not intercept it), then
    // exit shortly so the updater can replace the bundle underneath us. Used by
    // the source-rebuild path and the Windows binary path, whose installers own
    // the relaunch and do not signal a verified download back to us.
    mark_quit_requested(app);
    let handle = app.clone();
    std::thread::spawn(move || {
        std::thread::sleep(std::time::Duration::from_secs(2));
        do_deliberate_exit(&handle);
    });
}

/// Mark the quit as deliberate (so the close-to-tray handler steps aside) and
/// exit on the main thread.
fn do_deliberate_exit(app: &AppHandle) {
    mark_quit_requested(app);
    let handle = app.clone();
    let h = handle.clone();
    let _ = handle.run_on_main_thread(move || h.exit(0));
}

fn mark_quit_requested(app: &AppHandle) {
    if let Some(q) = app.try_state::<QuitRequested>() {
        q.0.store(true, std::sync::atomic::Ordering::SeqCst);
    }
}

fn quit_was_requested(app: &AppHandle) -> bool {
    app.try_state::<QuitRequested>()
        .map(|q| q.0.load(std::sync::atomic::Ordering::SeqCst))
        .unwrap_or(false)
}

fn mark_backend_failed(app: &AppHandle) {
    if let Some(failed) = app.try_state::<BackendFailed>() {
        failed.0.store(true, std::sync::atomic::Ordering::SeqCst);
    }
}

fn backend_has_failed(app: &AppHandle) -> bool {
    app.try_state::<BackendFailed>()
        .map(|failed| failed.0.load(std::sync::atomic::Ordering::SeqCst))
        .unwrap_or(false)
}

/// Native exit action exposed only to the recovery surface through Tauri's
/// explicit command ACL.
#[tauri::command]
fn quit_after_backend_failure(app: AppHandle) -> Result<(), String> {
    if !backend_has_failed(&app) {
        return Err("backend recovery is not active".to_string());
    }
    mark_quit_requested(&app);
    app.exit(0);
    Ok(())
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
        .creation_flags(WINDOWS_DETACHED_UPDATER_FLAGS);
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

/// Apply the backend launch arguments and environment shared by every
/// managed payload spawn attempt (the initial boot and bootstrap retries).
/// All spawn paths must stay identical apart from the executable itself.
/// ``FLINTTRADE_DESKTOP=1`` tells the backend it is running under the desktop
/// shell, so it may emit ``FLINTTRADE_NOTIFY`` stdout lines for native
/// notifications (a no-op under plain CLI/`make start`).
fn configure_backend_command(
    command: &mut StdCommand,
    sidecar_record_path: &Path,
    boot_id: &str,
    launch_token: &str,
) {
    command
        .args(["--port", "0"])
        .env("FLINTTRADE_DESKTOP", "1")
        // The sidecar entry script watches this PID and exits cleanly when
        // the shell dies.
        .env("FLINTTRADE_PARENT_PID", std::process::id().to_string())
        // Python promotes this exact tokenised pending record itself before
        // announcing its real application PID on stdout.
        .env("FLINTTRADE_SIDECAR_RECORD_PATH", sidecar_record_path)
        .env(BOOT_ID_ENV, boot_id)
        .env("FLINTTRADE_LAUNCH_TOKEN", launch_token);
}

/// Boot inputs captured once at setup and reused by every backend spawn
/// attempt (the initial boot and splash bootstrap retries).
struct BootContext {
    /// Workspace path of the sidecar recovery record.
    sidecar_record_path: PathBuf,
    /// OS boot-session identity persisted into every recovery record.
    boot_id: String,
    /// This desktop shell's PID (the recovery record's owner column).
    shell_pid: u32,
    /// The instance lock's launch token, consumed by the first spawn attempt.
    /// Retries mint a fresh token instead: cleanup-complete proofs are keyed
    /// by launch token, so reusing one across attempts could let an earlier
    /// attempt's guardian proof vouch for a later attempt's process tree.
    initial_launch_token: Mutex<Option<String>>,
    /// Stable POSIX shell identity handed to the sidecar watchdog.
    #[cfg(unix)]
    parent_identity: String,
}

/// Take the instance lock's token for the first spawn attempt; mint a fresh
/// one for every retry (see [`BootContext::initial_launch_token`]).
fn next_launch_token(context: &BootContext) -> std::io::Result<String> {
    if let Some(token) = context.initial_launch_token.lock().unwrap().take() {
        return Ok(token);
    }
    generate_launch_token()
}

/// Spawn the verified managed backend payload on an OS-chosen loopback port
/// and hand its pipes to the supervision task. ``Err`` leaves the splash
/// bootstrap surface in charge — the thin shell has no bundled fallback, so
/// an unusable payload is demoted and the operator retries the download.
fn start_managed_backend(app: &AppHandle) -> Result<(), String> {
    let context = app.state::<BootContext>();
    let (version, binary) = match verified_active_payload_binary() {
        Ok(Some(pair)) => pair,
        Ok(None) => {
            return Err("No trading engine is installed yet. Retry to download it.".to_string());
        }
        Err(error) => {
            eprintln!("[flinttrade] managed backend payload verification failed: {error}");
            demote_active_payload();
            return Err(
                "The installed engine failed its integrity check. Retry to download a fresh copy."
                    .to_string(),
            );
        }
    };
    let launch_token = next_launch_token(&context).map_err(|error| {
        eprintln!("[flinttrade] could not mint a backend launch token: {error}");
        "Could not prepare a secure engine launch. Please retry.".to_string()
    })?;
    let mut command = StdCommand::new(&binary);
    configure_backend_command(
        &mut command,
        &context.sidecar_record_path,
        &context.boot_id,
        &launch_token,
    );
    #[cfg(unix)]
    command.env(PARENT_IDENTITY_ENV, &context.parent_identity);
    let (rx, mut child) = spawn_contained_std_command(command).map_err(|error| {
        eprintln!("[flinttrade] managed backend payload v{version} failed to spawn: {error}");
        demote_active_payload();
        "The trading engine could not be started. Retry to download a fresh copy.".to_string()
    })?;
    eprintln!("[flinttrade] booting managed backend payload v{version}");
    let sidecar_pid = child.pid();
    let sidecar_record = SidecarRecord {
        sidecar_pid,
        application_pid: None,
        shell_pid: context.shell_pid,
        boot_id: context.boot_id.clone(),
        launch_token,
    };
    let pending_exit_acknowledged = Arc::new(AtomicBool::new(false));
    let cleanup_complete_acknowledged = Arc::new(AtomicBool::new(false));
    // Record the sidecar identity so the *next* launch can reap it if this
    // shell dies without running its kill-on-exit cleanup.
    if let Err(error) = write_sidecar_record(&sidecar_record) {
        retain_unpublished_cleanup_authority(
            || terminate_unrecorded_sidecar(&mut child),
            || std::thread::sleep(Duration::from_millis(100)),
        );
        eprintln!("[flinttrade] could not atomically record the backend sidecar: {error}");
        return Err(
            "Could not record the engine for crash recovery — nothing was started. Please retry."
                .to_string(),
        );
    }
    if let Some(state) = app.try_state::<BackendState>() {
        *state.0.lock().unwrap() = Some(ManagedSidecar {
            child,
            record: sidecar_record.clone(),
            pending_exit_acknowledged: Arc::clone(&pending_exit_acknowledged),
            cleanup_complete_acknowledged: Arc::clone(&cleanup_complete_acknowledged),
            shutdown_identity_tracker: ShutdownProcessIdentityTracker::default(),
        });
    }
    // Mark the stage BEFORE supervision starts so a near-instant termination
    // event cannot have its Failed transition clobbered by this Started one.
    set_bootstrap_stage(app, BootstrapStage::Started);
    spawn_backend_supervision(
        app.clone(),
        rx,
        sidecar_record,
        version,
        pending_exit_acknowledged,
        cleanup_complete_acknowledged,
    );
    Ok(())
}

/// Supervise a spawned backend: parse the ready handshake, surface failures,
/// relay native notifications, and keep draining the pipes so they never
/// block the backend's own logging. On a pre-handshake exit the payload pin
/// is demoted and the splash Retry surface takes over; a post-handshake exit
/// keeps the existing recovery-window flow.
fn spawn_backend_supervision(
    handle: AppHandle,
    mut rx: tauri::async_runtime::Receiver<BackendProcessEvent>,
    sidecar_record: SidecarRecord,
    payload_version: String,
    pending_exit_acknowledged: Arc<AtomicBool>,
    cleanup_complete_acknowledged: Arc<AtomicBool>,
) {
    tauri::async_runtime::spawn(async move {
        let mut buffer = String::new();
        let mut pid_buffer = String::new();
        let mut cleanup_buffer = String::new();
        let mut sidecar_record = sidecar_record;
        let mut application_identity = None;
        let mut ready_port = None;
        let mut shown = false;
        while let Some(event) = rx.recv().await {
            match event {
                BackendProcessEvent::Stdout(bytes) => {
                    let chunk = String::from_utf8_lossy(&bytes);
                    if !cleanup_complete_acknowledged.load(Ordering::Acquire) {
                        append_bounded_handshake_output(&mut cleanup_buffer, &chunk);
                        if output_has_cleanup_complete_ack(
                            &cleanup_buffer,
                            &sidecar_record.launch_token,
                        ) {
                            cleanup_complete_acknowledged.store(true, Ordering::Release);
                            cleanup_buffer.clear();
                        }
                    }
                    if sidecar_record.application_pid.is_none() {
                        append_bounded_handshake_output(&mut pid_buffer, &chunk);
                        if output_has_pending_record_exit_ack(
                            &pid_buffer,
                            &sidecar_record.launch_token,
                        ) {
                            pending_exit_acknowledged.store(true, Ordering::Release);
                        }
                        if let Some(application_pid) = parse_application_pid(&pid_buffer) {
                            match confirm_application_process(application_pid).and_then(
                                |identity| {
                                    promote_sidecar_record(&sidecar_record, application_pid)
                                        .map(|promoted| (promoted, identity))
                                },
                            ) {
                                Ok((promoted, identity)) => {
                                    if let Some(state) = handle.try_state::<BackendState>() {
                                        let mut active = state.0.lock().unwrap();
                                        if let Some(managed) = active.as_mut() {
                                            if managed.record == sidecar_record {
                                                managed.record = promoted.clone();
                                                managed
                                                    .shutdown_identity_tracker
                                                    .application
                                                    .bind(application_pid, identity.clone());
                                                if application_pid == sidecar_record.sidecar_pid {
                                                    managed
                                                        .shutdown_identity_tracker
                                                        .launcher
                                                        .bind(application_pid, identity.clone());
                                                }
                                            }
                                        }
                                    }
                                    sidecar_record = promoted;
                                    application_identity = Some(identity);
                                    pid_buffer.clear();
                                }
                                Err(error) => {
                                    eprintln!(
                                        "[flinttrade] could not confirm backend application pid {application_pid}: {error}"
                                    );
                                }
                            }
                        }
                    }
                    // Backend-emitted native notifications (fills, safety
                    // blocks, agent turns) — dispatched even while the
                    // window is hidden in the tray.
                    for line in chunk.lines() {
                        if let Some((title, body)) = parse_notify_line(line) {
                            raise_notification(&handle, &title, &body);
                        }
                    }
                    if !shown {
                        if ready_port.is_none() {
                            append_bounded_handshake_output(&mut buffer, &chunk);
                            ready_port = parse_ready_port(&buffer);
                            if ready_port.is_some() {
                                buffer.clear();
                            }
                        }
                        if let (Some(port), Some(_)) = (ready_port, sidecar_record.application_pid)
                        {
                            shown = true;
                            let h = handle.clone();
                            let _ = handle.run_on_main_thread(move || show_main_window(&h, port));
                        }
                    }
                }
                BackendProcessEvent::Stderr(bytes) => {
                    eprint!("{}", String::from_utf8_lossy(&bytes));
                }
                BackendProcessEvent::Terminated(exit) => {
                    eprintln!(
                        "[flinttrade] backend terminated: code={:?} signal={:?}",
                        exit.code, exit.signal
                    );
                    // A payload that dies before its ready handshake is
                    // demoted on the spot, and — once this launch's record is
                    // confirmed clean — the splash switches to its Retry
                    // surface so the operator can download a fresh payload.
                    // There is no bundled backend to restart onto.
                    let bootstrap_failed = ready_port.is_none() && !quit_was_requested(&handle);
                    if bootstrap_failed {
                        eprintln!(
                            "[flinttrade] managed backend payload v{payload_version} exited before its ready handshake; demoting it"
                        );
                        demote_active_payload();
                    }
                    if pending_record_cleanup_allowed(
                        &sidecar_record,
                        if pending_exit_acknowledged.load(Ordering::Acquire) {
                            PendingRecordExitProof::ApplicationAcknowledged
                        } else {
                            PendingRecordExitProof::None
                        },
                        ProcessLiveness::Dead,
                    ) {
                        clear_terminated_backend(&handle, &sidecar_record);
                        let _ = remove_sidecar_record(&sidecar_record);
                        if bootstrap_failed {
                            surface_bootstrap_retry(&handle);
                        } else {
                            surface_backend_recovery(&handle);
                        }
                        break;
                    }
                    let cleanup_acknowledged =
                        cleanup_complete_acknowledged.load(Ordering::Acquire);
                    match process_tree_liveness(&sidecar_record) {
                        ProcessLiveness::Dead => {
                            if bootstrap_failed {
                                clear_terminated_backend(&handle, &sidecar_record);
                                let _ = remove_sidecar_record_after_cleanup(
                                    &sidecar_record,
                                    cleanup_acknowledged,
                                );
                                surface_bootstrap_retry(&handle);
                            } else {
                                finalise_terminated_backend(
                                    &handle,
                                    &sidecar_record,
                                    cleanup_acknowledged,
                                );
                            }
                        }
                        ProcessLiveness::Alive => {
                            // Even after a pre-handshake demotion, a live
                            // process tree must fully resolve before any
                            // retry could spawn over it — keep supervising
                            // and fail closed to the recovery surface.
                            eprintln!(
                                "[flinttrade] sidecar launcher exited while the Python application remains alive; continuing supervision"
                            );
                            supervise_terminated_application(
                                &handle,
                                &sidecar_record,
                                Arc::clone(&cleanup_complete_acknowledged),
                                application_identity.clone(),
                            );
                        }
                        ProcessLiveness::Unknown => {
                            eprintln!(
                                "[flinttrade] sidecar launcher exited with unresolved process-tree ownership; retaining recovery state"
                            );
                            surface_backend_recovery(&handle);
                            if sidecar_record.application_pid.is_some() {
                                supervise_terminated_application(
                                    &handle,
                                    &sidecar_record,
                                    Arc::clone(&cleanup_complete_acknowledged),
                                    application_identity.clone(),
                                );
                            }
                        }
                    }
                    break;
                }
                BackendProcessEvent::Error(err) => {
                    eprintln!("[flinttrade] backend error: {err}");
                }
            }
        }
    });
}

/// Build and run the FlintTrade desktop application.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        // System-browser opener for broker OAuth approval pages — the main
        // window's remote (loopback HTTP) origin is granted exactly the
        // ``opener:allow-open-url`` permission, scoped to https URLs, in
        // ``capabilities/main-remote.json``.
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        // Signed one-click updates. The plugin exposes no IPC to the webview
        // here — the page reaches it only through the ``check_native_update``
        // and ``apply_native_update`` commands below.
        .plugin(tauri_plugin_updater::Builder::new().build())
        // In-app updater commands (Settings → Updates). Like the opener above,
        // the remote main window only reaches these via the explicit
        // ``allow-updater-state`` / ``allow-run-binary-update`` /
        // ``allow-run-self-update`` / ``allow-check-native-update`` /
        // ``allow-apply-native-update`` / ``allow-check-payload-update`` /
        // ``allow-apply-payload-update`` entries in
        // ``capabilities/main-remote.json`` (autogenerated by build.rs). The
        // splash window reaches only ``retry_bootstrap`` / ``bootstrap_status``
        // via ``capabilities/default.json``.
        .invoke_handler(tauri::generate_handler![
            updater_state,
            run_binary_update,
            run_self_update,
            check_native_update,
            apply_native_update,
            check_payload_update,
            apply_payload_update,
            retry_bootstrap,
            bootstrap_status,
            quit_after_backend_failure
        ])
        .manage(BackendState(Mutex::new(None)))
        .manage(QuitRequested(std::sync::atomic::AtomicBool::new(false)))
        .manage(BackendFailed(std::sync::atomic::AtomicBool::new(false)))
        .setup(|app| {
            let instance_lock = claim_desktop_instance().map_err(|error| {
                let message = if error.kind() == std::io::ErrorKind::WouldBlock {
                    "another FlintTrade desktop instance owns this workspace".to_string()
                } else {
                    format!("could not claim the FlintTrade desktop instance lock: {error}")
                };
                std::io::Error::new(error.kind(), message)
            })?;
            let shell_pid = instance_lock.shell_pid;
            let boot_id = instance_lock.boot_id.clone();
            let launch_token = instance_lock.launch_token.clone();
            if !app.manage(instance_lock) {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::AlreadyExists,
                    "desktop instance lock state was already registered",
                )
                .into());
            }
            // First-run secret provisioning (best-effort; never blocks launch).
            provision_master_password();

            // Give a stale sidecar time to finish its own watchdog shutdown.
            // Recovery never signals a PID loaded from disk: if the process
            // remains live, startup fails closed instead of risking PID reuse.
            reap_stale_sidecar(&boot_id).map_err(|error| {
                std::io::Error::other(format!(
                    "refusing to spawn a backend while stale sidecar state is unresolved: {error}"
                ))
            })?;

            // Tray + global hotkey: the app lives in the background (agent +
            // monitoring keep running) and the operator can summon it anytime.
            if let Err(e) = build_tray(app.handle()) {
                eprintln!("[flinttrade] tray setup failed: {e}");
            }
            register_toggle_shortcut(app.handle());

            let sidecar_record_path = sidecar_pid_file().ok_or_else(|| {
                std::io::Error::new(
                    std::io::ErrorKind::NotFound,
                    "could not resolve workspace directory for sidecar record",
                )
            })?;
            #[cfg(unix)]
            let parent_identity = required_parent_identity_with(shell_pid, process_command_line)
                .map_err(|error| {
                    std::io::Error::new(
                        error.kind(),
                        format!("could not confirm desktop shell identity for watchdog: {error}"),
                    )
                })?;

            app.manage(BootContext {
                sidecar_record_path,
                boot_id,
                shell_pid,
                initial_launch_token: Mutex::new(Some(launch_token)),
                #[cfg(unix)]
                parent_identity,
            });
            app.manage(BootstrapState::new());

            // Boot the managed backend payload — downloading it first on a
            // fresh install — without blocking setup, so the splash window
            // paints immediately and can render bootstrap progress. Any
            // failure lands on the splash Retry surface, never in a crash
            // loop or a setup abort.
            tauri::async_runtime::spawn(run_bootstrap(app.handle().clone()));

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the FlintTrade desktop app")
        .run(|app_handle, event| match event {
            RunEvent::ExitRequested { .. } => {
                // Mark OS/app-menu exits before stopping the sidecar so its
                // termination event cannot be mistaken for a crash.
                mark_quit_requested(app_handle);
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

fn append_bounded_handshake_output(buffer: &mut String, chunk: &str) {
    buffer.push_str(chunk);
    if buffer.len() <= MAX_HANDSHAKE_BUFFER_BYTES {
        return;
    }
    let mut start = buffer.len() - MAX_HANDSHAKE_BUFFER_BYTES;
    while !buffer.is_char_boundary(start) {
        start += 1;
    }
    buffer.drain(..start);
}

/// Extract the real Python application PID from its earliest stdout line.
fn parse_application_pid(buffer: &str) -> Option<u32> {
    for line in buffer.lines() {
        if let Some(idx) = line.find(APPLICATION_PID_SENTINEL) {
            if let Some(after) = line[idx..].split("pid=").nth(1) {
                let digits: String = after.chars().take_while(|c| c.is_ascii_digit()).collect();
                if let Ok(pid) = digits.parse::<u32>() {
                    if pid > 0 {
                        return Some(pid);
                    }
                }
            }
        }
    }
    None
}

/// Accept only a complete application-level pending-record acknowledgement for
/// this launch. Tokens are compared byte-for-byte and trailing fields fail.
fn parse_pending_record_exit_ack(line: &str, expected_token: &str) -> bool {
    let mut fields = line.split_whitespace();
    if fields.next() != Some(PENDING_RECORD_EXIT_ACK_SENTINEL) {
        return false;
    }
    if fields.next().and_then(|field| field.strip_prefix("token=")) != Some(expected_token) {
        return false;
    }
    if !matches!(
        fields
            .next()
            .and_then(|field| field.strip_prefix("reason=")),
        Some("promotion-failed" | "force-exit")
    ) {
        return false;
    }
    fields.next().is_none()
}

fn output_has_pending_record_exit_ack(buffer: &str, expected_token: &str) -> bool {
    buffer
        .lines()
        .any(|line| parse_pending_record_exit_ack(line, expected_token))
}

/// Accept only the guardian's complete, exact-token cleanup acknowledgement.
fn parse_cleanup_complete_ack(line: &str, expected_token: &str) -> bool {
    let mut fields = line.split_whitespace();
    fields.next() == Some(CLEANUP_COMPLETE_SENTINEL)
        && fields.next().and_then(|field| field.strip_prefix("token=")) == Some(expected_token)
        && fields.next().is_none()
}

fn output_has_cleanup_complete_ack(buffer: &str, expected_token: &str) -> bool {
    buffer
        .lines()
        .any(|line| parse_cleanup_complete_ack(line, expected_token))
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

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum MainWindowCloseAction {
    HideToTray,
    AllowClose,
    ExitApp,
}

fn main_window_close_action(quit_requested: bool, backend_failed: bool) -> MainWindowCloseAction {
    if backend_failed {
        MainWindowCloseAction::ExitApp
    } else if quit_requested {
        MainWindowCloseAction::AllowClose
    } else {
        MainWindowCloseAction::HideToTray
    }
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
                    match main_window_close_action(
                        quit_was_requested(&app_for_close),
                        backend_has_failed(&app_for_close),
                    ) {
                        MainWindowCloseAction::HideToTray => {
                            api.prevent_close();
                            if let Some(w) = app_for_close.get_webview_window("main") {
                                let _ = w.hide();
                            }
                        }
                        MainWindowCloseAction::AllowClose => {}
                        MainWindowCloseAction::ExitApp => {
                            mark_quit_requested(&app_for_close);
                            app_for_close.exit(0);
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
                mark_quit_requested(app);
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

const BACKEND_RECOVERY_SCRIPT: &str = r#"
(() => {
  const renderRecovery = () => {
    document.title = 'FlintTrade - Backend stopped';
    document.body.innerHTML = `
      <main style="min-height:100vh;display:grid;place-items:center;background:#111318;color:#f7f7f8;font-family:system-ui;padding:24px;box-sizing:border-box">
        <section style="width:min(100%,34rem)">
          <p style="margin:0 0 10px;color:#ff7a59;font-size:13px;font-weight:700">BACKEND STOPPED</p>
          <h1 style="margin:0;font-size:24px;line-height:1.25">FlintTrade needs to close</h1>
          <p style="margin:14px 0 24px;color:#b8bbc2;font-size:15px;line-height:1.6">The desktop backend ended unexpectedly. Your workspace data remains on disk.</p>
          <button id="flinttrade-recovery-quit" type="button" style="min-height:42px;padding:0 16px;border:0;border-radius:6px;background:#f7f7f8;color:#111318;font:600 14px system-ui;cursor:pointer">Quit FlintTrade</button>
          <p id="flinttrade-recovery-status" aria-live="polite" style="min-height:20px;margin:12px 0 0;color:#ff9b82;font-size:13px"></p>
        </section>
      </main>`;
    const button = document.getElementById('flinttrade-recovery-quit');
    const status = document.getElementById('flinttrade-recovery-status');
    button.addEventListener('click', async () => {
      button.disabled = true;
      button.style.cursor = 'wait';
      status.textContent = 'Quitting FlintTrade...';
      try {
        await window.__TAURI_INTERNALS__.invoke('quit_after_backend_failure');
      } catch (error) {
        button.disabled = false;
        button.style.cursor = 'pointer';
        status.textContent = 'Could not quit automatically. Use the tray Quit action.';
      }
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', renderRecovery, { once: true });
  } else {
    renderRecovery();
  }
})();
"#;

fn should_show_backend_recovery(quit_requested: bool) -> bool {
    !quit_requested
}

/// Replace the main window with an actionable recovery surface. If the
/// backend dies before the normal main window exists, create a trusted local
/// main window from the bundled splash asset so the same ACL-gated native Quit
/// command remains available.
fn show_backend_recovery(app: &AppHandle) {
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.eval(BACKEND_RECOVERY_SCRIPT);
        let _ = main.show();
        let _ = main.set_focus();
        return;
    }

    let recovery =
        WebviewWindowBuilder::new(app, "main", WebviewUrl::App(PathBuf::from("index.html")))
            .title("FlintTrade - Backend stopped")
            .inner_size(620.0, 420.0)
            .min_inner_size(520.0, 360.0)
            .center()
            .initialization_script(BACKEND_RECOVERY_SCRIPT)
            .build();

    match recovery {
        Ok(window) => {
            let app_for_close = app.clone();
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { .. } = event {
                    mark_quit_requested(&app_for_close);
                    app_for_close.exit(0);
                }
            });
            if let Some(splash) = app.get_webview_window("splash") {
                let _ = splash.close();
            }
            let _ = window.show();
            let _ = window.set_focus();
        }
        Err(error) => {
            eprintln!("[flinttrade] could not create backend recovery window: {error}");
            if let Some(splash) = app.get_webview_window("splash") {
                let _ = splash.eval(
                    "var s=document.getElementById('status');\
                     if(s){s.textContent='Backend stopped. Use the tray Quit action.';s.style.color='#ff6a3d';}",
                );
            }
        }
    }
}

fn clear_terminated_backend(app: &AppHandle, record: &SidecarRecord) {
    let Some(state) = app.try_state::<BackendState>() else {
        return;
    };
    let mut active = state.0.lock().unwrap();
    if active
        .as_ref()
        .map(|managed| &managed.record)
        .is_some_and(|active_record| active_record == record)
    {
        active.take();
    }
}

fn surface_backend_recovery(app: &AppHandle) {
    if should_show_backend_recovery(quit_was_requested(app)) && !backend_has_failed(app) {
        mark_backend_failed(app);
        let handle = app.clone();
        let h = handle.clone();
        let _ = handle.run_on_main_thread(move || {
            if should_show_backend_recovery(quit_was_requested(&h)) {
                show_backend_recovery(&h);
            }
        });
    }
}

fn finalise_terminated_backend(
    app: &AppHandle,
    record: &SidecarRecord,
    cleanup_acknowledged: bool,
) {
    clear_terminated_backend(app, record);
    // Remove only this launch's exact record. The instance lock prevents a
    // successor shell from replacing it while this process remains alive.
    let _ = remove_sidecar_record_after_cleanup(record, cleanup_acknowledged);
    surface_backend_recovery(app);
}

fn supervise_terminated_application(
    app: &AppHandle,
    record: &SidecarRecord,
    cleanup_complete_acknowledged: Arc<AtomicBool>,
    application_identity: Option<String>,
) {
    let monitor_app = app.clone();
    let monitor_record = record.clone();
    if let Err(error) = std::thread::Builder::new()
        .name("flinttrade-backend-supervisor".to_string())
        .spawn(move || {
            match wait_for_recorded_application_exit(
                &monitor_record,
                application_identity.as_deref(),
            ) {
                RecordedApplicationExit::ConfirmedDead
                | RecordedApplicationExit::ConfirmedReused => {
                    if wait_for_spawn_containment_exit(
                        monitor_record.sidecar_pid,
                        SIDECAR_FORCE_EXIT_TIMEOUT,
                    ) {
                        finalise_terminated_backend(
                            &monitor_app,
                            &monitor_record,
                            cleanup_complete_acknowledged.load(Ordering::Acquire),
                        );
                    } else {
                        eprintln!(
                            "[flinttrade] backend application exited before its containment guardian; retaining recovery state"
                        );
                        surface_backend_recovery(&monitor_app);
                    }
                }
                RecordedApplicationExit::Unresolved => {
                    eprintln!(
                        "[flinttrade] backend application identity could not be confirmed; retaining recovery state"
                    );
                    surface_backend_recovery(&monitor_app);
                }
            }
        })
    {
        eprintln!(
            "[flinttrade] could not start backend application supervision: {error}; retaining recovery state"
        );
        surface_backend_recovery(app);
    }
}

fn wait_for_spawn_containment_exit(pgid: u32, timeout: Duration) -> bool {
    #[cfg(windows)]
    {
        let _ = (pgid, timeout);
        true
    }
    #[cfg(unix)]
    {
        let deadline = Instant::now() + timeout;
        loop {
            if spawn_containment_liveness(pgid) == ProcessLiveness::Dead {
                return true;
            }
            let now = Instant::now();
            if now >= deadline {
                return false;
            }
            std::thread::sleep((deadline - now).min(Duration::from_millis(100)));
        }
    }
}

fn shutdown_phase_deadlines(started: Instant) -> (Instant, Instant, Instant) {
    let shutdown = started + SIDECAR_TOTAL_SHUTDOWN_TIMEOUT;
    let force = shutdown - SIDECAR_KILL_CONFIRM_TIMEOUT;
    let graceful = force - SIDECAR_FORCE_EXIT_TIMEOUT;
    (graceful, force, shutdown)
}

/// Gracefully stop the backend sidecar, with a bounded hard-kill fallback.
fn kill_backend(app: &AppHandle) {
    if let Some(state) = app.try_state::<BackendState>() {
        if let Some(mut managed) = state.0.lock().unwrap().take() {
            let (graceful_deadline, force_phase_deadline, shutdown_deadline) =
                shutdown_phase_deadlines(Instant::now());
            let record_path = sidecar_pid_file();
            if managed.child.write(SIDECAR_SHUTDOWN_COMMAND).is_ok()
                && wait_for_sidecar_shutdown(
                    &mut managed.record,
                    SIDECAR_PENDING_HANDSHAKE_TIMEOUT,
                    SIDECAR_GRACEFUL_SHUTDOWN_TIMEOUT,
                    graceful_deadline,
                    record_path.as_deref(),
                    &mut managed.shutdown_identity_tracker,
                )
            {
                let _ = remove_sidecar_record_after_cleanup(
                    &managed.record,
                    managed
                        .cleanup_complete_acknowledged
                        .load(Ordering::Acquire),
                );
                return;
            }
            match process_tree_liveness(&managed.record) {
                ProcessLiveness::Alive => {
                    if managed.record.application_pid.is_some() {
                        eprintln!(
                            "[flinttrade] backend did not stop within the shared graceful deadline; forcing exit"
                        );
                    } else {
                        eprintln!(
                            "[flinttrade] backend PID handshake did not complete; forcing exact-pipe exit"
                        );
                    }
                }
                ProcessLiveness::Unknown => {
                    eprintln!(
                        "[flinttrade] backend exit could not be confirmed; requesting hard kill"
                    );
                }
                ProcessLiveness::Dead => {}
            }
            let force_exit_written = match managed.child.write(SIDECAR_FORCE_EXIT_COMMAND) {
                Ok(()) => true,
                Err(error) => {
                    eprintln!("[flinttrade] backend force-exit pipe request failed: {error}");
                    false
                }
            };
            if force_exit_written
                && wait_for_sidecar_shutdown(
                    &mut managed.record,
                    SIDECAR_FORCE_EXIT_TIMEOUT,
                    SIDECAR_FORCE_EXIT_TIMEOUT,
                    force_phase_deadline,
                    record_path.as_deref(),
                    &mut managed.shutdown_identity_tracker,
                )
            {
                let _ = remove_sidecar_record_after_cleanup(
                    &managed.record,
                    managed
                        .cleanup_complete_acknowledged
                        .load(Ordering::Acquire),
                );
                return;
            }
            // A successful pipe write proves only that bytes entered the pipe,
            // not that Python or its guardian consumed them. Always activate
            // the OS containment fallback after the force deadline. POSIX sends
            // catchable SIGTERM to the outer guardian; Windows relies on the
            // shell Job closing when this process exits.
            if let Err(error) = managed.child.kill() {
                eprintln!("[flinttrade] backend containment fallback failed: {error}");
            }
            if wait_for_sidecar_shutdown(
                &mut managed.record,
                SIDECAR_KILL_CONFIRM_TIMEOUT,
                SIDECAR_KILL_CONFIRM_TIMEOUT,
                shutdown_deadline,
                record_path.as_deref(),
                &mut managed.shutdown_identity_tracker,
            ) {
                let _ = remove_sidecar_record_after_cleanup(
                    &managed.record,
                    managed
                        .cleanup_complete_acknowledged
                        .load(Ordering::Acquire),
                );
            } else if pending_record_cleanup_allowed(
                &managed.record,
                if managed.pending_exit_acknowledged.load(Ordering::Acquire) {
                    PendingRecordExitProof::ApplicationAcknowledged
                } else {
                    PendingRecordExitProof::None
                },
                process_liveness(managed.record.sidecar_pid),
            ) {
                // Python acknowledged only after removing this exact pending
                // record before backend import. The launcher is also dead, so
                // no untracked PyInstaller application tree can remain.
                let _ = remove_sidecar_record(&managed.record);
            } else {
                eprintln!(
                    "[flinttrade] backend process tree is unresolved after hard stop; retaining recovery record"
                );
            }
        }
    }
}

fn wait_for_sidecar_shutdown_with<R, L, N, W>(
    record: &mut SidecarRecord,
    pending_timeout: Duration,
    confirmed_timeout: Duration,
    overall_deadline: Instant,
    mut refresh: R,
    mut liveness: L,
    mut now: N,
    mut wait: W,
) -> bool
where
    R: FnMut(&SidecarRecord) -> Option<SidecarRecord>,
    L: FnMut(&SidecarRecord) -> ProcessLiveness,
    N: FnMut() -> Instant,
    W: FnMut(Duration),
{
    let started_at = now();
    let mut phase_deadline = if record.application_pid.is_some() {
        (started_at + confirmed_timeout).min(overall_deadline)
    } else {
        (started_at + pending_timeout).min(overall_deadline)
    };
    loop {
        if now() >= phase_deadline {
            return false;
        }
        let was_pending = record.application_pid.is_none();
        if let Some(refreshed) = refresh(record) {
            *record = refreshed;
            if was_pending && record.application_pid.is_some() {
                phase_deadline = (now() + confirmed_timeout).min(overall_deadline);
            }
        }
        if now() >= phase_deadline {
            return false;
        }
        if liveness(record) == ProcessLiveness::Dead {
            return true;
        }
        let current = now();
        if current >= phase_deadline {
            return false;
        }
        wait((phase_deadline - current).min(Duration::from_millis(100)));
    }
}

fn wait_for_sidecar_shutdown(
    record: &mut SidecarRecord,
    pending_timeout: Duration,
    confirmed_timeout: Duration,
    overall_deadline: Instant,
    record_path: Option<&Path>,
    identity_tracker: &mut ShutdownProcessIdentityTracker,
) -> bool {
    wait_for_sidecar_shutdown_with(
        record,
        pending_timeout,
        confirmed_timeout,
        overall_deadline,
        |expected| record_path.and_then(|path| refresh_sidecar_record_at(path, expected)),
        |current| identity_tracker.process_tree_liveness(current),
        Instant::now,
        std::thread::sleep,
    )
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum PendingRecordExitProof {
    None,
    ApplicationAcknowledged,
}

fn pending_record_cleanup_allowed(
    record: &SidecarRecord,
    proof: PendingRecordExitProof,
    launcher_liveness: ProcessLiveness,
) -> bool {
    record.application_pid.is_none()
        && proof == PendingRecordExitProof::ApplicationAcknowledged
        && launcher_liveness == ProcessLiveness::Dead
}

// ---------------------------------------------------------------------------
// Sidecar orphan protection (PID file + fail-closed startup recovery).
// ---------------------------------------------------------------------------

/// Path of the sidecar PID file inside the workspace dir.
fn sidecar_pid_file() -> Option<PathBuf> {
    flinttrade_home().map(|d| d.join(SIDECAR_PID_FILE))
}

fn cleanup_complete_proof_path(record_path: &Path) -> std::io::Result<PathBuf> {
    let file_name = record_path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "sidecar record path has no valid file name",
            )
        })?;
    Ok(record_path.with_file_name(format!(".{file_name}.cleanup-complete")))
}

fn format_cleanup_complete_proof(launch_token: &str) -> String {
    format!("{CLEANUP_COMPLETE_SENTINEL} token={launch_token}\n")
}

fn cleanup_complete_proof_matches_at(record_path: &Path, launch_token: &str) -> bool {
    if !valid_launch_token(launch_token) {
        return false;
    }
    let Ok(proof_path) = cleanup_complete_proof_path(record_path) else {
        return false;
    };
    let Ok(metadata) = std::fs::symlink_metadata(&proof_path) else {
        return false;
    };
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;

        if metadata.permissions().mode() & 0o077 != 0 {
            return false;
        }
    }
    std::fs::read_to_string(proof_path)
        .is_ok_and(|contents| contents == format_cleanup_complete_proof(launch_token))
}

fn cleanup_complete_proven(record: &SidecarRecord, acknowledged: bool) -> bool {
    #[cfg(windows)]
    {
        let _ = (record, acknowledged);
        true
    }
    #[cfg(unix)]
    {
        let Some(path) = sidecar_pid_file() else {
            return false;
        };
        // The durable token-bound proof is authoritative across shell crashes;
        // the stdout acknowledgement is retained as immediate runtime evidence.
        let durable = cleanup_complete_proof_matches_at(&path, &record.launch_token);
        if acknowledged && !durable {
            eprintln!(
                "[flinttrade] cleanup acknowledgement lacked its durable proof; retaining recovery state"
            );
        }
        durable
    }
}

fn startup_cleanup_complete_proven_at(record_path: &Path, record: Option<&SidecarRecord>) -> bool {
    let Some(record) = record else {
        return false;
    };
    #[cfg(windows)]
    {
        let _ = (record_path, record);
        true
    }
    #[cfg(unix)]
    {
        cleanup_complete_proof_matches_at(record_path, &record.launch_token)
    }
}

fn instance_lock_file() -> Option<PathBuf> {
    flinttrade_home().map(|d| d.join(DESKTOP_INSTANCE_LOCK_FILE))
}

fn instance_lock_contended(error: &std::io::Error) -> bool {
    let expected = fs2::lock_contended_error();
    expected.raw_os_error().is_some() && error.raw_os_error() == expected.raw_os_error()
}

impl DesktopInstanceLock {
    fn acquire_at(path: &Path, shell_pid: u32, launch_token: String) -> std::io::Result<Self> {
        if shell_pid == 0 || !valid_launch_token(&launch_token) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "desktop instance identity is invalid",
            ));
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        if let Err(error) = file.try_lock_exclusive() {
            return Err(if instance_lock_contended(&error) {
                std::io::Error::new(
                    std::io::ErrorKind::WouldBlock,
                    "desktop instance lock is already held",
                )
            } else {
                error
            });
        }

        // Diagnostic text is written only after the kernel grants ownership.
        // A partial or stale value never affects future lock claims.
        file.set_len(0)?;
        file.seek(SeekFrom::Start(0))?;
        writeln!(file, "{shell_pid}")?;
        file.sync_all()?;

        Ok(Self {
            _file: file,
            shell_pid,
            boot_id: boot_session_identity()?,
            launch_token,
        })
    }
}

fn generate_launch_token() -> std::io::Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).map_err(|error| {
        std::io::Error::other(format!("could not generate launch token: {error}"))
    })?;
    Ok(to_hex(&bytes))
}

fn claim_desktop_instance() -> std::io::Result<DesktopInstanceLock> {
    let path = instance_lock_file().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "could not resolve the FlintTrade workspace directory",
        )
    })?;
    DesktopInstanceLock::acquire_at(&path, std::process::id(), generate_launch_token()?)
}

fn valid_launch_token(token: &str) -> bool {
    token.len() == 64 && token.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn valid_boot_id(boot_id: &str) -> bool {
    (16..=512).contains(&boot_id.len())
        && boot_id.len() % 2 == 0
        && boot_id.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn normalise_boot_identity(raw: &[u8]) -> std::io::Result<String> {
    let trimmed = String::from_utf8_lossy(raw).trim().as_bytes().to_vec();
    if trimmed.is_empty() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "OS boot-session identity was empty",
        ));
    }
    let boot_id = to_hex(&trimmed);
    if !valid_boot_id(&boot_id) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "OS boot-session identity was invalid",
        ));
    }
    Ok(boot_id)
}

/// Return an identity that remains stable only for the current OS boot session.
fn boot_session_identity() -> std::io::Result<String> {
    #[cfg(target_os = "linux")]
    {
        return normalise_boot_identity(
            std::fs::read("/proc/sys/kernel/random/boot_id")?.as_slice(),
        );
    }
    #[cfg(target_os = "macos")]
    {
        let output = std::process::Command::new("sysctl")
            .args(["-n", "kern.bootsessionuuid"])
            .output()?;
        if !output.status.success() {
            return Err(std::io::Error::other(format!(
                "sysctl kern.bootsessionuuid exited with status {}",
                output.status
            )));
        }
        return normalise_boot_identity(&output.stdout);
    }
    #[cfg(windows)]
    {
        use std::ffi::c_void;

        #[repr(C)]
        struct SystemTimeOfDayInformation {
            boot_time: i64,
            current_time: i64,
            time_zone_bias: i64,
            time_zone_id: u32,
            reserved: u32,
            boot_time_bias: u64,
            sleep_time_bias: u64,
        }
        #[link(name = "ntdll")]
        extern "system" {
            fn NtQuerySystemInformation(
                information_class: u32,
                information: *mut c_void,
                information_length: u32,
                return_length: *mut u32,
            ) -> i32;
        }

        let mut information: SystemTimeOfDayInformation = unsafe { std::mem::zeroed() };
        let mut returned = 0u32;
        let status = unsafe {
            NtQuerySystemInformation(
                3, // SystemTimeOfDayInformation
                std::ptr::addr_of_mut!(information).cast(),
                std::mem::size_of::<SystemTimeOfDayInformation>() as u32,
                std::ptr::addr_of_mut!(returned),
            )
        };
        if status < 0 || information.boot_time <= 0 {
            return Err(std::io::Error::other(format!(
                "native Windows boot identity query failed with NTSTATUS {status:#x}"
            )));
        }
        return normalise_boot_identity(information.boot_time.to_string().as_bytes());
    }
    #[allow(unreachable_code)]
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "OS boot-session identity is unsupported",
    ))
}

/// Serialise the versioned process-tree recovery record. ``pending`` is a
/// deliberate fail-closed state until Python announces its real PID.
fn format_sidecar_record(record: &SidecarRecord) -> String {
    let application_pid = record
        .application_pid
        .map(|pid| pid.to_string())
        .unwrap_or_else(|| "pending".to_string());
    format!(
        "{SIDECAR_RECORD_VERSION}\n{}\n{}\n{}\n{}\n{}\n",
        record.sidecar_pid, application_pid, record.shell_pid, record.boot_id, record.launch_token
    )
}

fn parse_sidecar_record(contents: &str) -> Option<SidecarRecord> {
    let mut lines = contents.lines();
    if lines.next()?.trim() != SIDECAR_RECORD_VERSION {
        return None;
    }
    let sidecar_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let raw_application_pid = lines.next()?.trim();
    let application_pid = if raw_application_pid == "pending" {
        None
    } else {
        Some(
            raw_application_pid
                .parse::<u32>()
                .ok()
                .filter(|pid| *pid > 0)?,
        )
    };
    let shell_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let boot_id = lines.next()?.to_string();
    let launch_token = lines.next()?.to_string();
    if lines.next().is_some() || !valid_boot_id(&boot_id) || !valid_launch_token(&launch_token) {
        return None;
    }
    Some(SidecarRecord {
        sidecar_pid,
        application_pid,
        shell_pid,
        boot_id,
        launch_token,
    })
}

fn parse_v3_sidecar_record(contents: &str) -> Option<ReapRecord> {
    let mut lines = contents.lines();
    if lines.next()?.trim() != "v3" {
        return None;
    }
    let sidecar_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let raw_application_pid = lines.next()?.trim();
    let application_pid = if raw_application_pid == "pending" {
        None
    } else {
        Some(
            raw_application_pid
                .parse::<u32>()
                .ok()
                .filter(|pid| *pid > 0)?,
        )
    };
    let shell_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let boot_id = lines.next()?.to_string();
    let launch_token = lines.next()?;
    if lines.next().is_some() || !valid_boot_id(&boot_id) || !valid_launch_token(launch_token) {
        return None;
    }
    Some(ReapRecord {
        sidecar_pid,
        application_pid,
        shell_pid,
        boot_id: Some(boot_id),
        spawn_contained: false,
    })
}

fn parse_v2_sidecar_record(contents: &str) -> Option<ReapRecord> {
    let mut lines = contents.lines();
    if lines.next()?.trim() != "v2" {
        return None;
    }
    let sidecar_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let raw_application_pid = lines.next()?.trim();
    let application_pid = if raw_application_pid == "pending" {
        None
    } else {
        Some(
            raw_application_pid
                .parse::<u32>()
                .ok()
                .filter(|pid| *pid > 0)?,
        )
    };
    let shell_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let launch_token = lines.next()?;
    if lines.next().is_some() || !valid_launch_token(launch_token) {
        return None;
    }
    Some(ReapRecord {
        sidecar_pid,
        application_pid,
        shell_pid,
        boot_id: None,
        spawn_contained: false,
    })
}

fn parse_v1_sidecar_record(contents: &str) -> Option<ReapRecord> {
    let mut lines = contents.lines();
    let sidecar_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let shell_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let launch_token = lines.next()?;
    if lines.next().is_some() || !valid_launch_token(launch_token) {
        return None;
    }
    Some(ReapRecord {
        sidecar_pid,
        application_pid: None,
        shell_pid,
        boot_id: None,
        spawn_contained: false,
    })
}

fn parse_legacy_sidecar_record(contents: &str) -> Option<ReapRecord> {
    let mut lines = contents.lines();
    let sidecar_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    let shell_pid = lines
        .next()?
        .trim()
        .parse::<u32>()
        .ok()
        .filter(|pid| *pid > 0)?;
    if lines.next().is_some() {
        return None;
    }
    Some(ReapRecord {
        sidecar_pid,
        application_pid: None,
        shell_pid,
        boot_id: None,
        spawn_contained: false,
    })
}

fn parse_reap_record(contents: &str) -> Option<ReapRecord> {
    parse_sidecar_record(contents)
        .map(|record| ReapRecord {
            sidecar_pid: record.sidecar_pid,
            application_pid: record.application_pid,
            shell_pid: record.shell_pid,
            boot_id: Some(record.boot_id),
            spawn_contained: true,
        })
        .or_else(|| parse_v3_sidecar_record(contents))
        .or_else(|| parse_v2_sidecar_record(contents))
        .or_else(|| parse_v1_sidecar_record(contents))
        .or_else(|| parse_legacy_sidecar_record(contents))
}

/// True when a process command line / image name identifies our sidecar.
fn looks_like_backend_sidecar(command_line: &str) -> bool {
    command_line.contains(SIDECAR_PROCESS_MARKER)
}

/// Conservatively identify a FlintTrade desktop shell. False positives only
/// refuse startup; they never result in terminating a process.
fn looks_like_desktop_shell(command_line: &str) -> bool {
    let lower = command_line.to_ascii_lowercase();
    if lower.contains(SIDECAR_PROCESS_MARKER) {
        return false;
    }
    let executable = if let Some(quoted) = lower.strip_prefix('"') {
        quoted.split('"').next()
    } else {
        lower.split_whitespace().next()
    };
    let Some(executable) = executable else {
        return false;
    };
    let image_name = executable.rsplit(['/', '\\']).next().unwrap_or_default();
    matches!(
        image_name,
        "flinttrade" | "flinttrade.exe" | "flinttrade-desktop" | "flinttrade-desktop.exe"
    )
}

#[cfg(test)]
fn parse_unix_ps_identity(text: &str, expected_pid: u32, start_token: &str) -> Option<String> {
    let mut fields = text.trim().splitn(2, char::is_whitespace);
    let pid = fields.next()?.parse::<u32>().ok()?;
    let command = fields.next()?.trim();
    if pid != expected_pid || command.is_empty() || start_token.is_empty() {
        return None;
    }
    Some(format!("{command}\t{pid}\t{start_token}"))
}

#[cfg(target_os = "linux")]
fn unix_process_start_token(pid: u32) -> std::io::Result<Option<String>> {
    let stat = match std::fs::read_to_string(format!("/proc/{pid}/stat")) {
        Ok(stat) => stat,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let closing_paren = stat.rfind(')').ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("could not parse /proc/{pid}/stat"),
        )
    })?;
    let fields: Vec<&str> = stat[closing_paren + 2..].split_whitespace().collect();
    let start_ticks = fields
        .get(19)
        .filter(|value| !value.is_empty() && value.bytes().all(|byte| byte.is_ascii_digit()));
    let Some(start_ticks) = start_ticks else {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("could not read process start ticks for pid {pid}"),
        ));
    };
    Ok(Some(format!("linux-start-ticks:{start_ticks}")))
}

#[cfg(target_os = "macos")]
fn unix_process_start_token(pid: u32) -> std::io::Result<Option<String>> {
    use std::ffi::{c_int, c_void};

    #[repr(C)]
    struct ProcBsdInfo {
        pbi_flags: u32,
        pbi_status: u32,
        pbi_xstatus: u32,
        pbi_pid: u32,
        pbi_ppid: u32,
        pbi_uid: u32,
        pbi_gid: u32,
        pbi_ruid: u32,
        pbi_rgid: u32,
        pbi_svuid: u32,
        pbi_svgid: u32,
        rfu_1: u32,
        pbi_comm: [i8; 16],
        pbi_name: [i8; 32],
        pbi_nfiles: u32,
        pbi_pgid: u32,
        pbi_pjobc: u32,
        e_tdev: u32,
        e_tpgid: u32,
        pbi_nice: i32,
        pbi_start_tvsec: u64,
        pbi_start_tvusec: u64,
    }

    #[link(name = "proc")]
    extern "C" {
        fn proc_pidinfo(
            pid: c_int,
            flavor: c_int,
            arg: u64,
            buffer: *mut c_void,
            buffer_size: c_int,
        ) -> c_int;
    }

    let raw_pid = i32::try_from(pid).map_err(|_| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, "process PID exceeds i32")
    })?;
    let mut info: ProcBsdInfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<ProcBsdInfo>();
    let read = unsafe {
        proc_pidinfo(
            raw_pid,
            3, // PROC_PIDTBSDINFO
            0,
            std::ptr::addr_of_mut!(info).cast(),
            i32::try_from(size).expect("proc_bsdinfo size fits i32"),
        )
    };
    if read == 0 {
        let error = std::io::Error::last_os_error();
        return if error.raw_os_error() == Some(3) {
            Ok(None)
        } else {
            Err(error)
        };
    }
    if usize::try_from(read).ok() != Some(size) || info.pbi_pid != pid || info.pbi_start_tvsec == 0
    {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("proc_pidinfo returned incomplete identity for pid {pid}"),
        ));
    }
    Ok(Some(format!(
        "macos-start-time:{}:{}",
        info.pbi_start_tvsec, info.pbi_start_tvusec
    )))
}

#[cfg(all(unix, not(any(target_os = "linux", target_os = "macos"))))]
fn unix_process_start_token(_pid: u32) -> std::io::Result<Option<String>> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "high-resolution Unix process identity is unsupported",
    ))
}

#[cfg(target_os = "linux")]
fn unix_process_command(pid: u32) -> std::io::Result<Option<String>> {
    let bytes = match std::fs::read(format!("/proc/{pid}/cmdline")) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    let command = String::from_utf8_lossy(&bytes)
        .replace('\0', " ")
        .trim()
        .to_string();
    if command.is_empty() {
        Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("process {pid} has no readable command line"),
        ))
    } else {
        Ok(Some(command))
    }
}

#[cfg(target_os = "macos")]
fn unix_process_command(pid: u32) -> std::io::Result<Option<String>> {
    use std::ffi::c_void;

    extern "C" {
        fn proc_pidpath(pid: i32, buffer: *mut c_void, buffer_size: u32) -> i32;
    }
    let raw_pid = i32::try_from(pid).map_err(|_| {
        std::io::Error::new(std::io::ErrorKind::InvalidInput, "process PID exceeds i32")
    })?;
    let mut buffer = vec![0u8; 4_096];
    let read = unsafe {
        proc_pidpath(
            raw_pid,
            buffer.as_mut_ptr().cast(),
            u32::try_from(buffer.len()).expect("process path buffer fits u32"),
        )
    };
    if read <= 0 {
        let error = std::io::Error::last_os_error();
        return if error.raw_os_error() == Some(3) {
            Ok(None)
        } else {
            Err(error)
        };
    }
    buffer.truncate(usize::try_from(read).map_err(|_| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "proc_pidpath returned an invalid path length",
        )
    })?);
    let command = String::from_utf8_lossy(&buffer).trim().to_string();
    if command.is_empty() {
        Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("process {pid} has no readable executable path"),
        ))
    } else {
        Ok(Some(command))
    }
}

#[cfg(all(unix, not(any(target_os = "linux", target_os = "macos"))))]
fn unix_process_command(_pid: u32) -> std::io::Result<Option<String>> {
    Err(std::io::Error::new(
        std::io::ErrorKind::Unsupported,
        "native Unix process command lookup is unsupported",
    ))
}

/// Return a stable native command + PID + kernel process-start identity, or
/// ``None`` when no such process exists. Probe errors remain distinct from
/// absence so startup and shutdown retain recovery state on uncertainty.
#[cfg(unix)]
fn process_command_line(pid: u32) -> std::io::Result<Option<String>> {
    let Some(before) = unix_process_start_token(pid)? else {
        return Ok(None);
    };
    let Some(command) = unix_process_command(pid)? else {
        return Ok(None);
    };
    let Some(after) = unix_process_start_token(pid)? else {
        return Ok(None);
    };
    if after != before {
        return Ok(None);
    }
    Ok(Some(format!("{command}\t{pid}\t{before}")))
}

#[cfg(test)]
fn parse_windows_process_identity(text: &str, expected_pid: u32) -> Option<String> {
    let line = text
        .lines()
        .find(|line| !line.trim().is_empty())?
        .trim_start_matches('\u{feff}')
        .trim();
    let mut fields = line.split('\t');
    let image_name = fields.next()?.trim();
    let pid = fields.next()?.trim().parse::<u32>().ok()?;
    let started_at = fields.next()?.trim().parse::<u64>().ok()?;
    if fields.next().is_some() || image_name.is_empty() || pid != expected_pid || started_at == 0 {
        return None;
    }
    Some(format!(
        "{}\t{pid}\t{started_at}",
        image_name.to_ascii_lowercase()
    ))
}

#[cfg(any(windows, test))]
fn classify_windows_process_wait(
    open_error: Option<u32>,
    wait_result: Option<u32>,
) -> ProcessLiveness {
    if let Some(error) = open_error {
        return if error == 87 {
            ProcessLiveness::Dead
        } else {
            ProcessLiveness::Unknown
        };
    }
    match wait_result {
        Some(0x0000_0000) => ProcessLiveness::Dead,
        Some(0x0000_0102) => ProcessLiveness::Alive,
        _ => ProcessLiveness::Unknown,
    }
}

#[cfg(windows)]
#[derive(Debug)]
struct WindowsProcessHandle(usize);

#[cfg(windows)]
impl WindowsProcessHandle {
    fn open(pid: u32, access: u32) -> std::io::Result<Option<Self>> {
        use std::ffi::c_void;
        extern "system" {
            fn OpenProcess(access: u32, inherit: i32, pid: u32) -> *mut c_void;
        }
        let handle = unsafe { OpenProcess(access, 0, pid) };
        if !handle.is_null() {
            return Ok(Some(Self(handle as usize)));
        }
        let error = std::io::Error::last_os_error();
        if error.raw_os_error() == Some(87) {
            Ok(None)
        } else {
            Err(error)
        }
    }

    fn wait_result(&self) -> u32 {
        use std::ffi::c_void;
        extern "system" {
            fn WaitForSingleObject(handle: *mut c_void, milliseconds: u32) -> u32;
        }
        unsafe { WaitForSingleObject(self.0 as *mut c_void, 0) }
    }
}

#[cfg(windows)]
impl Drop for WindowsProcessHandle {
    fn drop(&mut self) {
        use std::ffi::c_void;
        extern "system" {
            fn CloseHandle(handle: *mut c_void) -> i32;
        }
        unsafe {
            CloseHandle(self.0 as *mut c_void);
        }
    }
}

/// Return a stable image + PID + native creation-time identity for a Windows
/// process, or ``None`` when that process has exited.
#[cfg(windows)]
fn process_command_line(pid: u32) -> std::io::Result<Option<String>> {
    use std::ffi::c_void;

    #[repr(C)]
    struct FileTime {
        low: u32,
        high: u32,
    }
    extern "system" {
        fn QueryFullProcessImageNameW(
            process: *mut c_void,
            flags: u32,
            image: *mut u16,
            size: *mut u32,
        ) -> i32;
        fn GetProcessTimes(
            process: *mut c_void,
            creation: *mut FileTime,
            exit: *mut FileTime,
            kernel: *mut FileTime,
            user: *mut FileTime,
        ) -> i32;
    }

    let Some(handle) = WindowsProcessHandle::open(pid, 0x0010_0000 | 0x0000_1000)? else {
        return Ok(None);
    };
    if classify_windows_process_wait(None, Some(handle.wait_result())) == ProcessLiveness::Dead {
        return Ok(None);
    }
    let mut image = vec![0u16; 32_768];
    let mut image_len = image.len() as u32;
    if unsafe {
        QueryFullProcessImageNameW(
            handle.0 as *mut c_void,
            0,
            image.as_mut_ptr(),
            std::ptr::addr_of_mut!(image_len),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error());
    }
    let mut creation: FileTime = unsafe { std::mem::zeroed() };
    let mut exit: FileTime = unsafe { std::mem::zeroed() };
    let mut kernel: FileTime = unsafe { std::mem::zeroed() };
    let mut user: FileTime = unsafe { std::mem::zeroed() };
    if unsafe {
        GetProcessTimes(
            handle.0 as *mut c_void,
            std::ptr::addr_of_mut!(creation),
            std::ptr::addr_of_mut!(exit),
            std::ptr::addr_of_mut!(kernel),
            std::ptr::addr_of_mut!(user),
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error());
    }
    let created_at = (u64::from(creation.high) << 32) | u64::from(creation.low);
    if created_at == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "Windows process creation time is zero",
        ));
    }
    let image = String::from_utf16_lossy(&image[..image_len as usize]).to_ascii_lowercase();
    Ok(Some(format!("{image}\t{pid}\t{created_at}")))
}

#[cfg(any(unix, test))]
fn required_parent_identity_with<I>(pid: u32, identity: I) -> std::io::Result<String>
where
    I: FnOnce(u32) -> std::io::Result<Option<String>>,
{
    identity(pid)?.ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("desktop shell pid {pid} disappeared during identity lookup"),
        )
    })
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

/// Tri-state liveness probe backed only by a native process handle.
#[cfg(windows)]
fn process_liveness(pid: u32) -> ProcessLiveness {
    match WindowsProcessHandle::open(pid, 0x0010_0000) {
        Ok(Some(handle)) => classify_windows_process_wait(None, Some(handle.wait_result())),
        Ok(None) => classify_windows_process_wait(Some(87), None),
        Err(error) => classify_windows_process_wait(
            error
                .raw_os_error()
                .and_then(|code| u32::try_from(code).ok()),
            None,
        ),
    }
}

/// Wait until one monotonic wall-clock deadline for a process to disappear.
fn wait_for_process_exit(pid: u32, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    loop {
        match process_liveness(pid) {
            ProcessLiveness::Dead => return true,
            ProcessLiveness::Alive | ProcessLiveness::Unknown => {}
        }
        let now = Instant::now();
        if now >= deadline {
            return false;
        }
        std::thread::sleep((deadline - now).min(Duration::from_millis(100)));
    }
}

/// Aggregate the current launch's recorded launcher and application states.
/// A pending application PID is always unknown: launcher death alone cannot
/// prove that PyInstaller did not leave an unreported child alive.
fn process_tree_liveness(record: &SidecarRecord) -> ProcessLiveness {
    #[cfg(unix)]
    let containment = spawn_containment_liveness(record.sidecar_pid);
    #[cfg(windows)]
    let containment = ProcessLiveness::Dead;
    if containment == ProcessLiveness::Alive {
        return ProcessLiveness::Alive;
    }
    let Some(application_pid) = record.application_pid else {
        let launcher = process_liveness(record.sidecar_pid);
        return if launcher == ProcessLiveness::Dead && containment == ProcessLiveness::Dead {
            ProcessLiveness::Dead
        } else if launcher == ProcessLiveness::Alive {
            ProcessLiveness::Alive
        } else {
            ProcessLiveness::Unknown
        };
    };
    let mut saw_unknown = containment == ProcessLiveness::Unknown;
    for pid in [record.sidecar_pid, application_pid] {
        match process_liveness(pid) {
            ProcessLiveness::Alive => return ProcessLiveness::Alive,
            ProcessLiveness::Unknown => saw_unknown = true,
            ProcessLiveness::Dead => {}
        }
        if application_pid == record.sidecar_pid {
            break;
        }
    }
    if saw_unknown {
        ProcessLiveness::Unknown
    } else {
        ProcessLiveness::Dead
    }
}

#[derive(Debug, Default)]
struct TrackedProcessIdentity {
    pid: Option<u32>,
    identity: Option<String>,
}

impl TrackedProcessIdentity {
    fn bind(&mut self, pid: u32, identity: String) {
        self.pid = Some(pid);
        self.identity = Some(identity);
    }

    fn observe_with<L, I>(
        &mut self,
        pid: u32,
        liveness: &mut L,
        identity: &mut I,
    ) -> ProcessLiveness
    where
        L: FnMut(u32) -> ProcessLiveness,
        I: FnMut(u32) -> std::io::Result<Option<String>>,
    {
        if self.pid != Some(pid) {
            self.pid = Some(pid);
            self.identity = None;
        }
        if liveness(pid) == ProcessLiveness::Dead {
            return ProcessLiveness::Dead;
        }
        match identity(pid) {
            Ok(Some(current)) => match self.identity.as_ref() {
                Some(expected) if expected == &current => ProcessLiveness::Alive,
                Some(_) => ProcessLiveness::Dead,
                None if looks_like_backend_sidecar(&current) => {
                    self.identity = Some(current);
                    ProcessLiveness::Alive
                }
                None => ProcessLiveness::Dead,
            },
            Ok(None) | Err(_) => match liveness(pid) {
                ProcessLiveness::Dead => ProcessLiveness::Dead,
                ProcessLiveness::Alive | ProcessLiveness::Unknown => ProcessLiveness::Unknown,
            },
        }
    }
}

#[derive(Debug, Default)]
struct ShutdownProcessIdentityTracker {
    launcher: TrackedProcessIdentity,
    application: TrackedProcessIdentity,
}

impl ShutdownProcessIdentityTracker {
    fn process_tree_liveness_with<L, I>(
        &mut self,
        record: &SidecarRecord,
        mut liveness: L,
        mut identity: I,
    ) -> ProcessLiveness
    where
        L: FnMut(u32) -> ProcessLiveness,
        I: FnMut(u32) -> std::io::Result<Option<String>>,
    {
        let launcher = self
            .launcher
            .observe_with(record.sidecar_pid, &mut liveness, &mut identity);
        #[cfg(unix)]
        let containment = spawn_containment_liveness(record.sidecar_pid);
        #[cfg(windows)]
        let containment = ProcessLiveness::Dead;
        if containment == ProcessLiveness::Alive {
            return ProcessLiveness::Alive;
        }
        let Some(application_pid) = record.application_pid else {
            return if launcher == ProcessLiveness::Dead && containment == ProcessLiveness::Dead {
                ProcessLiveness::Dead
            } else if launcher == ProcessLiveness::Alive {
                ProcessLiveness::Alive
            } else {
                ProcessLiveness::Unknown
            };
        };
        let application = if application_pid == record.sidecar_pid {
            launcher
        } else {
            self.application
                .observe_with(application_pid, &mut liveness, &mut identity)
        };
        if matches!(launcher, ProcessLiveness::Alive)
            || matches!(application, ProcessLiveness::Alive)
        {
            ProcessLiveness::Alive
        } else if matches!(launcher, ProcessLiveness::Unknown)
            || matches!(application, ProcessLiveness::Unknown)
            || containment == ProcessLiveness::Unknown
        {
            ProcessLiveness::Unknown
        } else {
            ProcessLiveness::Dead
        }
    }

    fn process_tree_liveness(&mut self, record: &SidecarRecord) -> ProcessLiveness {
        self.process_tree_liveness_with(record, process_liveness, process_command_line)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RecordedApplicationExit {
    ConfirmedDead,
    ConfirmedReused,
    Unresolved,
}

fn wait_for_recorded_application_exit_with<L, I, W>(
    record: &SidecarRecord,
    max_unknown_polls: usize,
    expected_identity: Option<&str>,
    mut liveness: L,
    mut identity: I,
    mut wait: W,
) -> RecordedApplicationExit
where
    L: FnMut(u32) -> ProcessLiveness,
    I: FnMut(u32) -> std::io::Result<Option<String>>,
    W: FnMut(),
{
    let Some(application_pid) = record.application_pid else {
        return RecordedApplicationExit::Unresolved;
    };
    let initial_identity = match identity(application_pid) {
        Ok(Some(value)) if expected_identity.is_some_and(|expected| expected == value) => value,
        Ok(Some(_)) if expected_identity.is_some() => {
            return RecordedApplicationExit::ConfirmedReused
        }
        Ok(Some(value)) if looks_like_backend_sidecar(&value) => value,
        Ok(Some(_)) => return RecordedApplicationExit::ConfirmedReused,
        Ok(None) | Err(_) => {
            return if liveness(application_pid) == ProcessLiveness::Dead {
                RecordedApplicationExit::ConfirmedDead
            } else {
                RecordedApplicationExit::Unresolved
            };
        }
    };
    let mut unknown_polls = 0;
    loop {
        match liveness(application_pid) {
            ProcessLiveness::Dead => return RecordedApplicationExit::ConfirmedDead,
            ProcessLiveness::Alive | ProcessLiveness::Unknown => {
                match identity(application_pid) {
                    Ok(Some(value)) if value == initial_identity => {
                        unknown_polls = 0;
                    }
                    Ok(Some(_)) => return RecordedApplicationExit::ConfirmedReused,
                    Ok(None) | Err(_) => {
                        unknown_polls += 1;
                        if unknown_polls >= max_unknown_polls.max(1) {
                            return RecordedApplicationExit::Unresolved;
                        }
                    }
                }
                wait();
            }
        }
    }
}

fn wait_for_recorded_application_exit(
    record: &SidecarRecord,
    expected_identity: Option<&str>,
) -> RecordedApplicationExit {
    wait_for_recorded_application_exit_with(
        record,
        SIDECAR_SUPERVISOR_UNKNOWN_POLLS,
        expected_identity,
        process_liveness,
        process_command_line,
        || std::thread::sleep(std::time::Duration::from_millis(100)),
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ReapOutcome {
    NoRecord,
    RemovedEarlierBoot,
    RemovedConfirmedDead,
    RemovedConfirmedReused,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum LiveSidecarIdentity {
    Backend(String),
    Reused,
    Dead,
}

fn pending_record_repair_allowed(
    spawn_contained: bool,
    launcher: LiveSidecarIdentity,
    containment: ProcessLiveness,
) -> bool {
    spawn_contained && launcher == LiveSidecarIdentity::Dead && containment == ProcessLiveness::Dead
}

#[cfg(unix)]
fn spawn_containment_liveness(pgid: u32) -> ProcessLiveness {
    let Ok(raw_pgid) = i32::try_from(pgid) else {
        return ProcessLiveness::Unknown;
    };
    extern "C" {
        fn kill(pid: i32, signal: i32) -> i32;
    }
    if unsafe { kill(-raw_pgid, 0) } == 0 {
        return ProcessLiveness::Alive;
    }
    match std::io::Error::last_os_error().raw_os_error() {
        Some(3) => ProcessLiveness::Dead,
        Some(1) => ProcessLiveness::Alive,
        _ => ProcessLiveness::Unknown,
    }
}

#[cfg(windows)]
fn spawn_containment_liveness(launcher_pid: u32) -> ProcessLiveness {
    // The previous shell was the only owner of the outer kill-on-close Job.
    // Once its instance lock is available, a dead launcher means that Job has
    // closed and Windows has terminated every non-breakaway member.
    process_liveness(launcher_pid)
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum ReapError {
    WorkspaceUnavailable,
    RecordRead { message: String },
    InvalidRecord,
    ShellLivenessUnknown { pid: u32 },
    ShellIdentityLookupFailed { pid: u32 },
    ShellIdentityUnconfirmed { pid: u32 },
    ShellStillAlive { pid: u32 },
    ApplicationPidPending { launcher_pid: u32 },
    SidecarLivenessUnknown { pid: u32 },
    SidecarIdentityLookupFailed { pid: u32 },
    SidecarIdentityUnconfirmed { pid: u32 },
    SidecarStillAlive { pid: u32 },
    CleanupUnconfirmed,
    RecordChanged,
    RecordRemoval { message: String },
}

impl std::fmt::Display for ReapError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::WorkspaceUnavailable => write!(formatter, "workspace directory is unavailable"),
            Self::RecordRead { message } => {
                write!(
                    formatter,
                    "sidecar recovery record could not be read: {message}"
                )
            }
            Self::InvalidRecord => write!(
                formatter,
                "sidecar recovery record is incomplete or invalid"
            ),
            Self::ShellLivenessUnknown { pid } => {
                write!(formatter, "owning shell pid {pid} liveness is unknown")
            }
            Self::ShellIdentityLookupFailed { pid } => {
                write!(formatter, "owning shell pid {pid} identity lookup failed")
            }
            Self::ShellIdentityUnconfirmed { pid } => {
                write!(
                    formatter,
                    "owning shell pid {pid} identity could not be confirmed"
                )
            }
            Self::ShellStillAlive { pid } => {
                write!(
                    formatter,
                    "recorded FlintTrade shell pid {pid} is still alive"
                )
            }
            Self::ApplicationPidPending { launcher_pid } => write!(
                formatter,
                "backend launcher pid {launcher_pid} exited before the Python application PID was confirmed"
            ),
            Self::SidecarLivenessUnknown { pid } => {
                write!(formatter, "sidecar pid {pid} liveness is unknown")
            }
            Self::SidecarIdentityLookupFailed { pid } => {
                write!(formatter, "sidecar pid {pid} identity lookup failed")
            }
            Self::SidecarIdentityUnconfirmed { pid } => {
                write!(
                    formatter,
                    "sidecar pid {pid} identity could not be confirmed"
                )
            }
            Self::SidecarStillAlive { pid } => write!(
                formatter,
                "sidecar pid {pid} is still a FlintTrade backend after watchdog grace"
            ),
            Self::CleanupUnconfirmed => write!(
                formatter,
                "backend processes appear gone but guardian cleanup completion is unproven"
            ),
            Self::RecordChanged => write!(formatter, "sidecar recovery record changed during reap"),
            Self::RecordRemoval { message } => {
                write!(
                    formatter,
                    "sidecar recovery record could not be removed: {message}"
                )
            }
        }
    }
}

impl std::error::Error for ReapError {}

fn remove_reaped_record(
    path: &Path,
    expected_contents: &str,
    outcome: ReapOutcome,
) -> Result<ReapOutcome, ReapError> {
    with_sidecar_record_transition_guard(path, || {
        match std::fs::read_to_string(path) {
            Ok(contents) if contents == expected_contents => {}
            Ok(_) => return Err(ReapError::RecordChanged),
            Err(error) => {
                return Err(ReapError::RecordRemoval {
                    message: error.to_string(),
                });
            }
        }
        let current = parse_sidecar_record(expected_contents);
        std::fs::remove_file(path).map_err(|error| ReapError::RecordRemoval {
            message: error.to_string(),
        })?;
        if let Some(record) = current {
            if cleanup_complete_proof_matches_at(path, &record.launch_token) {
                if let Ok(proof_path) = cleanup_complete_proof_path(path) {
                    let _ = std::fs::remove_file(proof_path);
                }
            }
        }
        Ok(outcome)
    })
    .map_err(|error| ReapError::RecordRemoval {
        message: error.to_string(),
    })?
}

fn inspect_live_sidecar<L, I>(
    pid: u32,
    liveness: &L,
    identity: &I,
) -> Result<LiveSidecarIdentity, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
{
    match identity(pid) {
        Ok(Some(command)) if looks_like_backend_sidecar(&command) => {
            Ok(LiveSidecarIdentity::Backend(command))
        }
        Ok(Some(_)) => Ok(LiveSidecarIdentity::Reused),
        Ok(None) => match liveness(pid) {
            ProcessLiveness::Dead => Ok(LiveSidecarIdentity::Dead),
            ProcessLiveness::Unknown => Err(ReapError::SidecarLivenessUnknown { pid }),
            ProcessLiveness::Alive => Err(ReapError::SidecarIdentityUnconfirmed { pid }),
        },
        Err(_) => match liveness(pid) {
            ProcessLiveness::Dead => Ok(LiveSidecarIdentity::Dead),
            ProcessLiveness::Alive | ProcessLiveness::Unknown => {
                Err(ReapError::SidecarIdentityLookupFailed { pid })
            }
        },
    }
}

fn inspect_sidecar_after_watchdog_grace<L, I, G>(
    pid: u32,
    liveness: &L,
    identity: &I,
    await_watchdog_exit: &G,
) -> Result<LiveSidecarIdentity, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
    G: Fn(u32) -> bool,
{
    match liveness(pid) {
        ProcessLiveness::Dead => return Ok(LiveSidecarIdentity::Dead),
        ProcessLiveness::Unknown => {
            return Err(ReapError::SidecarLivenessUnknown { pid });
        }
        ProcessLiveness::Alive => {}
    }

    match inspect_live_sidecar(pid, liveness, identity)? {
        LiveSidecarIdentity::Backend(_) => {
            eprintln!(
                "[flinttrade] waiting for stale backend process pid {pid} to finish watchdog shutdown"
            );
            let _ = await_watchdog_exit(pid);
            match liveness(pid) {
                ProcessLiveness::Dead => Ok(LiveSidecarIdentity::Dead),
                ProcessLiveness::Unknown => Err(ReapError::SidecarLivenessUnknown { pid }),
                ProcessLiveness::Alive => inspect_live_sidecar(pid, liveness, identity),
            }
        }
        state => Ok(state),
    }
}

/// Startup layer of orphan protection. Every ambiguous process state is an
/// error so setup cannot overwrite an unresolved record and spawn a duplicate.
fn reap_stale_sidecar_at_for_boot_with_grace<L, I, G, C>(
    path: &Path,
    current_shell_pid: u32,
    current_boot_id: &str,
    liveness: L,
    identity: I,
    await_watchdog_exit: G,
    cleanup_complete: C,
) -> Result<ReapOutcome, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
    G: Fn(u32) -> bool,
    C: Fn(Option<&SidecarRecord>) -> bool,
{
    if !valid_boot_id(current_boot_id) {
        return Err(ReapError::InvalidRecord);
    }
    let contents = match std::fs::read_to_string(path) {
        Ok(contents) => contents,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Ok(ReapOutcome::NoRecord);
        }
        Err(error) => {
            return Err(ReapError::RecordRead {
                message: error.to_string(),
            });
        }
    };
    let record = parse_reap_record(&contents).ok_or(ReapError::InvalidRecord)?;
    let current_sidecar_record = parse_sidecar_record(&contents);
    let current_cleanup_confirmed = cleanup_complete(current_sidecar_record.as_ref());
    if record
        .boot_id
        .as_deref()
        .is_some_and(|recorded| recorded != current_boot_id)
    {
        return remove_reaped_record(path, &contents, ReapOutcome::RemovedEarlierBoot);
    }

    // If the OS reused the previous shell PID for this process, the held
    // kernel lock proves the old owner is gone. Otherwise a live process must
    // be identified before its PID can be classified as reused.
    if record.shell_pid != current_shell_pid {
        match liveness(record.shell_pid) {
            ProcessLiveness::Dead => {}
            ProcessLiveness::Unknown => {
                return Err(ReapError::ShellLivenessUnknown {
                    pid: record.shell_pid,
                });
            }
            ProcessLiveness::Alive => match identity(record.shell_pid) {
                Ok(Some(command)) if looks_like_desktop_shell(&command) => {
                    return Err(ReapError::ShellStillAlive {
                        pid: record.shell_pid,
                    });
                }
                Ok(Some(_)) => {}
                Ok(None) => match liveness(record.shell_pid) {
                    ProcessLiveness::Dead => {}
                    ProcessLiveness::Unknown => {
                        return Err(ReapError::ShellLivenessUnknown {
                            pid: record.shell_pid,
                        });
                    }
                    ProcessLiveness::Alive => {
                        return Err(ReapError::ShellIdentityUnconfirmed {
                            pid: record.shell_pid,
                        });
                    }
                },
                Err(_) => match liveness(record.shell_pid) {
                    ProcessLiveness::Dead => {}
                    ProcessLiveness::Alive | ProcessLiveness::Unknown => {
                        return Err(ReapError::ShellIdentityLookupFailed {
                            pid: record.shell_pid,
                        });
                    }
                },
            },
        }
    }

    let Some(application_pid) = record.application_pid else {
        // The shell may have crashed while PyInstaller was extracting or
        // before Rust received Python's first stdout line. A dead launcher is
        // not proof that no application child survived, so this record is
        // deliberately retained for operator-visible recovery.
        let launcher = inspect_sidecar_after_watchdog_grace(
            record.sidecar_pid,
            &liveness,
            &identity,
            &await_watchdog_exit,
        )?;
        match launcher.clone() {
            LiveSidecarIdentity::Backend(_) => {
                return Err(ReapError::SidecarStillAlive {
                    pid: record.sidecar_pid,
                });
            }
            LiveSidecarIdentity::Dead | LiveSidecarIdentity::Reused => {
                if pending_record_repair_allowed(
                    record.spawn_contained,
                    launcher,
                    spawn_containment_liveness(record.sidecar_pid),
                ) {
                    if !current_cleanup_confirmed {
                        return Err(ReapError::CleanupUnconfirmed);
                    }
                    return remove_reaped_record(
                        path,
                        &contents,
                        ReapOutcome::RemovedConfirmedDead,
                    );
                }
                return Err(ReapError::ApplicationPidPending {
                    launcher_pid: record.sidecar_pid,
                });
            }
        }
    };

    let mut outcome = ReapOutcome::RemovedConfirmedDead;
    let mut launcher_reused = false;
    let process_pids = if application_pid == record.sidecar_pid {
        vec![application_pid]
    } else {
        // Check the real application first: this is the process that can
        // survive a dead PyInstaller one-file launcher.
        vec![application_pid, record.sidecar_pid]
    };
    for pid in process_pids {
        match inspect_sidecar_after_watchdog_grace(pid, &liveness, &identity, &await_watchdog_exit)?
        {
            LiveSidecarIdentity::Backend(_) => {
                return Err(ReapError::SidecarStillAlive { pid });
            }
            LiveSidecarIdentity::Reused => {
                eprintln!(
                    "[flinttrade] recorded backend pid {pid} was reused; leaving the process alone"
                );
                outcome = ReapOutcome::RemovedConfirmedReused;
                if pid == record.sidecar_pid {
                    launcher_reused = true;
                }
            }
            LiveSidecarIdentity::Dead => {}
        }
    }

    #[cfg(unix)]
    if record.spawn_contained && !launcher_reused {
        match spawn_containment_liveness(record.sidecar_pid) {
            ProcessLiveness::Dead => {}
            ProcessLiveness::Alive => {
                return Err(ReapError::SidecarStillAlive {
                    pid: record.sidecar_pid,
                });
            }
            ProcessLiveness::Unknown => {
                return Err(ReapError::SidecarLivenessUnknown {
                    pid: record.sidecar_pid,
                });
            }
        }
    }

    if !current_cleanup_confirmed {
        return Err(ReapError::CleanupUnconfirmed);
    }
    remove_reaped_record(path, &contents, outcome)
}

#[cfg(test)]
fn test_record_boot_id(path: &Path) -> String {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|contents| parse_reap_record(&contents))
        .and_then(|record| record.boot_id)
        .unwrap_or_else(|| "c".repeat(64))
}

#[cfg(test)]
fn reap_stale_sidecar_at_with_grace<L, I, G>(
    path: &Path,
    current_shell_pid: u32,
    liveness: L,
    identity: I,
    await_watchdog_exit: G,
) -> Result<ReapOutcome, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
    G: Fn(u32) -> bool,
{
    reap_stale_sidecar_at_for_boot_with_grace(
        path,
        current_shell_pid,
        &test_record_boot_id(path),
        liveness,
        identity,
        await_watchdog_exit,
        |_| true,
    )
}

#[cfg(test)]
fn reap_stale_sidecar_at<L, I>(
    path: &Path,
    current_shell_pid: u32,
    liveness: L,
    identity: I,
) -> Result<ReapOutcome, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
{
    reap_stale_sidecar_at_for_boot_with_grace(
        path,
        current_shell_pid,
        &test_record_boot_id(path),
        liveness,
        identity,
        |_| false,
        |_| true,
    )
}

#[cfg(test)]
fn reap_stale_sidecar_at_for_boot<L, I>(
    path: &Path,
    current_shell_pid: u32,
    current_boot_id: &str,
    liveness: L,
    identity: I,
) -> Result<ReapOutcome, ReapError>
where
    L: Fn(u32) -> ProcessLiveness,
    I: Fn(u32) -> std::io::Result<Option<String>>,
{
    reap_stale_sidecar_at_for_boot_with_grace(
        path,
        current_shell_pid,
        current_boot_id,
        liveness,
        identity,
        |_| false,
        |_| true,
    )
}

fn reap_stale_sidecar(current_boot_id: &str) -> Result<ReapOutcome, ReapError> {
    let path = sidecar_pid_file().ok_or(ReapError::WorkspaceUnavailable)?;
    reap_stale_sidecar_at_for_boot_with_grace(
        &path,
        std::process::id(),
        current_boot_id,
        process_liveness,
        process_command_line,
        |pid| wait_for_process_exit(pid, SIDECAR_WATCHDOG_GRACE_TIMEOUT),
        |record| startup_cleanup_complete_proven_at(&path, record),
    )
}

/// Atomically publish the pending process-tree record. The destination must be
/// absent after stale-state recovery; replacing an existing record is refused.
fn write_sidecar_record_at(path: &Path, record: &SidecarRecord) -> std::io::Result<()> {
    let serialised = format_sidecar_record(record);
    if parse_sidecar_record(&serialised).as_ref() != Some(record) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar record is invalid",
        ));
    }
    let parent = path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar record path has no parent directory",
        )
    })?;
    std::fs::create_dir_all(parent)?;
    if path.try_exists()? {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "sidecar recovery record already exists",
        ));
    }

    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "sidecar record path has no valid file name",
            )
        })?;
    let temporary = parent.join(format!(".{file_name}.{}.tmp", record.launch_token));
    let result = (|| -> std::io::Result<()> {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(serialised.as_bytes())?;
        file.sync_all()?;
        harden_file(&temporary);
        std::fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

#[cfg(unix)]
fn replace_path_atomically(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::rename(source, destination)
}

#[cfg(windows)]
fn replace_path_atomically(source: &Path, destination: &Path) -> std::io::Result<()> {
    use std::os::windows::ffi::OsStrExt;

    const MOVEFILE_REPLACE_EXISTING: u32 = 0x0000_0001;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x0000_0008;
    extern "system" {
        fn MoveFileExW(
            existing_file_name: *const u16,
            new_file_name: *const u16,
            flags: u32,
        ) -> i32;
    }

    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let destination_wide: Vec<u16> = destination
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    if unsafe {
        MoveFileExW(
            source_wide.as_ptr(),
            destination_wide.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    } == 0
    {
        Err(std::io::Error::last_os_error())
    } else {
        Ok(())
    }
}

fn sync_record_parent(_path: &Path) -> std::io::Result<()> {
    #[cfg(unix)]
    {
        let parent = _path.parent().ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "sidecar record path has no parent directory",
            )
        })?;
        std::fs::File::open(parent)?.sync_all()?;
    }
    Ok(())
}

fn atomically_replace_sidecar_record_with<F>(
    path: &Path,
    expected: &str,
    replacement: &str,
    launch_token: &str,
    replace: F,
) -> std::io::Result<()>
where
    F: FnOnce(&Path, &Path) -> std::io::Result<()>,
{
    if !valid_launch_token(launch_token) {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar launch token is invalid",
        ));
    }
    if std::fs::read_to_string(path)? != expected {
        return Err(std::io::Error::new(
            std::io::ErrorKind::AlreadyExists,
            "sidecar recovery record changed before atomic replacement",
        ));
    }
    let parent = path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar record path has no parent directory",
        )
    })?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "sidecar record path has no valid file name",
            )
        })?;
    let temporary = parent.join(format!(
        ".{file_name}.{launch_token}.{}.tmp",
        std::process::id()
    ));
    let result = (|| -> std::io::Result<()> {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(replacement.as_bytes())?;
        file.sync_all()?;
        harden_file(&temporary);
        if std::fs::read_to_string(path)? != expected {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "sidecar recovery record changed before atomic replacement",
            ));
        }
        replace(&temporary, path)?;
        sync_record_parent(path)
    })();
    if temporary.exists() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}

fn atomically_replace_sidecar_record(
    path: &Path,
    expected: &str,
    replacement: &str,
    launch_token: &str,
) -> std::io::Result<()> {
    atomically_replace_sidecar_record_with(
        path,
        expected,
        replacement,
        launch_token,
        replace_path_atomically,
    )
}

fn confirm_application_process(pid: u32) -> std::io::Result<String> {
    match process_liveness(pid) {
        ProcessLiveness::Dead => {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("announced backend application pid {pid} is not alive"),
            ));
        }
        ProcessLiveness::Unknown => {
            return Err(std::io::Error::other(format!(
                "announced backend application pid {pid} liveness is unknown"
            )));
        }
        ProcessLiveness::Alive => {}
    }
    match process_command_line(pid)? {
        Some(identity) if looks_like_backend_sidecar(&identity) => Ok(identity),
        Some(_) => Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            format!("announced pid {pid} is not the FlintTrade backend"),
        )),
        None => Err(std::io::Error::new(
            std::io::ErrorKind::NotFound,
            format!("announced backend application pid {pid} disappeared"),
        )),
    }
}

/// Promote an exact pending record to the confirmed Python application PID.
/// The old or new complete record is always visible across a crash boundary.
fn promote_sidecar_record_at(
    path: &Path,
    expected: &SidecarRecord,
    application_pid: u32,
) -> std::io::Result<SidecarRecord> {
    if expected.application_pid.is_some() || application_pid == 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar application PID promotion is invalid",
        ));
    }
    let promoted = SidecarRecord {
        application_pid: Some(application_pid),
        ..expected.clone()
    };
    with_sidecar_record_transition_guard(path, || {
        let serialised = format_sidecar_record(&promoted);
        let current = std::fs::read_to_string(path)?;
        if current == serialised {
            return Ok(promoted.clone());
        }
        if current != format_sidecar_record(expected) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::AlreadyExists,
                "sidecar recovery record changed before application PID promotion",
            ));
        }
        atomically_replace_sidecar_record(path, &current, &serialised, &expected.launch_token)?;
        Ok(promoted.clone())
    })?
}

fn write_sidecar_record(record: &SidecarRecord) -> std::io::Result<()> {
    let path = sidecar_pid_file().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "could not resolve workspace directory for sidecar record",
        )
    })?;
    write_sidecar_record_at(&path, record)
}

fn promote_sidecar_record(
    expected: &SidecarRecord,
    application_pid: u32,
) -> std::io::Result<SidecarRecord> {
    let path = sidecar_pid_file().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::NotFound,
            "could not resolve workspace directory for sidecar record",
        )
    })?;
    promote_sidecar_record_at(&path, expected, application_pid)
}

/// Re-read an exact launch record, accepting only its one-way pending-to-PID
/// promotion. Any other field change belongs to unrelated or corrupted state.
fn refresh_sidecar_record_at(path: &Path, expected: &SidecarRecord) -> Option<SidecarRecord> {
    let current = parse_sidecar_record(&std::fs::read_to_string(path).ok()?)?;
    if current.sidecar_pid != expected.sidecar_pid
        || current.shell_pid != expected.shell_pid
        || current.boot_id != expected.boot_id
        || current.launch_token != expected.launch_token
    {
        return None;
    }
    match (expected.application_pid, current.application_pid) {
        (Some(expected_pid), Some(current_pid)) if expected_pid == current_pid => Some(current),
        (None, None | Some(_)) => Some(current),
        _ => None,
    }
}

/// Compare every identity field before deleting. The process-lifetime
/// instance lock prevents a successor shell from replacing the record between
/// comparison and removal.
fn remove_sidecar_record_at(path: &Path, expected: &SidecarRecord) -> std::io::Result<bool> {
    with_sidecar_record_transition_guard(path, || {
        let contents = match std::fs::read_to_string(path) {
            Ok(contents) => contents,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(error),
        };
        if parse_sidecar_record(&contents).as_ref() != Some(expected) {
            return Ok(false);
        }
        std::fs::remove_file(path)?;
        if cleanup_complete_proof_matches_at(path, &expected.launch_token) {
            if let Ok(proof_path) = cleanup_complete_proof_path(path) {
                let _ = std::fs::remove_file(proof_path);
            }
        }
        Ok(true)
    })?
}

fn sidecar_record_transition_guard_path(path: &Path) -> std::io::Result<PathBuf> {
    let parent = path.parent().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "sidecar record path has no parent directory",
        )
    })?;
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "sidecar record path has no valid file name",
            )
        })?;
    Ok(parent.join(format!(".{file_name}.lock")))
}

fn with_sidecar_record_transition_guard<T, F>(path: &Path, operation: F) -> std::io::Result<T>
where
    F: FnOnce() -> T,
{
    let guard_path = sidecar_record_transition_guard_path(path)?;
    let mut guard = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(&guard_path)?;
    if guard.metadata()?.len() == 0 {
        guard.write_all(&[0])?;
        guard.sync_all()?;
        guard.seek(SeekFrom::Start(0))?;
    }
    harden_file(&guard_path);
    guard.lock_exclusive()?;
    let result = operation();
    FileExt::unlock(&guard)?;
    Ok(result)
}

fn remove_sidecar_record(expected: &SidecarRecord) -> bool {
    let Some(path) = sidecar_pid_file() else {
        eprintln!("[flinttrade] could not resolve workspace dir; retaining sidecar record");
        return false;
    };
    match remove_sidecar_record_at(&path, expected) {
        Ok(true) => true,
        Ok(false) => {
            eprintln!(
                "[flinttrade] sidecar recovery record no longer matches this launch; retaining it"
            );
            false
        }
        Err(error) => {
            eprintln!("[flinttrade] could not remove sidecar recovery record: {error}");
            false
        }
    }
}

fn remove_sidecar_record_after_cleanup(expected: &SidecarRecord, acknowledged: bool) -> bool {
    if !cleanup_complete_proven(expected, acknowledged) {
        eprintln!("[flinttrade] backend cleanup completion is unproven; retaining recovery state");
        return false;
    }
    remove_sidecar_record(expected)
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

    /// Claim an instance lock that this process has just released.
    ///
    /// flock ownership belongs to the open file description, and a child
    /// forked by ANY concurrent test thread while the fd was open briefly
    /// inherits a reference to it until exec's O_CLOEXEC sweep — so for a few
    /// milliseconds after `drop` the kernel can still report the lock as
    /// held. Production never re-acquires after a same-process release (the
    /// shell claims once at startup and holds for life), so this transient
    /// window is a test-only concern; every acquire-after-release site must
    /// tolerate it with this bounded retry.
    fn acquire_released_instance_lock(
        path: &Path,
        shell_pid: u32,
        launch_token: String,
    ) -> DesktopInstanceLock {
        let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            match DesktopInstanceLock::acquire_at(path, shell_pid, launch_token.clone()) {
                Ok(lock) => return lock,
                Err(error)
                    if error.kind() == std::io::ErrorKind::WouldBlock
                        && std::time::Instant::now() < deadline =>
                {
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
                Err(error) => panic!("could not claim released instance lock: {error}"),
            }
        }
    }

    #[test]
    fn parses_ready_handshake() {
        let buf = "starting...\nFLINTTRADE_BACKEND_READY port=56576\nmore logs\n";
        assert_eq!(parse_ready_port(buf), Some(56576));
    }

    #[test]
    fn parses_real_python_application_pid_handshake() {
        let buf = "FLINTTRADE_BACKEND_PID pid=5678\nstarting...\n";
        assert_eq!(parse_application_pid(buf), Some(5678));
        assert_eq!(parse_application_pid("FLINTTRADE_BACKEND_PID pid=0"), None);
        assert_eq!(
            parse_application_pid("FLINTTRADE_BACKEND_PID pid=nope"),
            None
        );
    }

    #[test]
    fn handshake_output_buffer_keeps_a_bounded_utf8_tail() {
        let mut buffer = "old".repeat(2_000);
        append_bounded_handshake_output(&mut buffer, "\nπFLINTTRADE_BACKEND_PID pid=5678\n");

        assert!(buffer.len() <= MAX_HANDSHAKE_BUFFER_BYTES);
        assert!(buffer.is_char_boundary(0));
        assert_eq!(parse_application_pid(&buffer), Some(5678));
    }

    #[test]
    fn pending_record_exit_ack_requires_the_exact_launch_token() {
        let token = "a".repeat(64);
        let exact =
            format!("FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={token} reason=promotion-failed");

        assert!(parse_pending_record_exit_ack(&exact, &token));
        assert!(!parse_pending_record_exit_ack(&exact, &"b".repeat(64)));
        assert!(!parse_pending_record_exit_ack(
            &format!("{exact} trailing"),
            &token
        ));
        assert!(!parse_pending_record_exit_ack(
            &format!(
                "FLINTTRADE_BACKEND_PENDING_EXIT_ACK token={} reason=promotion-failed",
                token.to_ascii_uppercase()
            ),
            &token
        ));
    }

    #[test]
    fn pending_record_exit_ack_waits_for_a_complete_fragmented_line() {
        let token = "a".repeat(64);
        let mut buffer = "FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=".to_string();

        assert!(!output_has_pending_record_exit_ack(&buffer, &token));
        buffer.push_str(&format!("{token} reason=promotion-failed\n"));
        assert!(output_has_pending_record_exit_ack(&buffer, &token));
    }

    #[test]
    fn cleanup_complete_ack_requires_the_exact_launch_token_and_complete_line() {
        let token = "a".repeat(64);
        let exact = format!("FLINTTRADE_BACKEND_CLEANUP_COMPLETE token={token}");
        let mut fragmented = "FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=".to_string();

        assert!(parse_cleanup_complete_ack(&exact, &token));
        assert!(!parse_cleanup_complete_ack(&exact, &"b".repeat(64)));
        assert!(!parse_cleanup_complete_ack(
            &format!("{exact} trailing"),
            &token
        ));
        assert!(!output_has_cleanup_complete_ack(&fragmented, &token));
        fragmented.push_str(&format!("{token}\n"));
        assert!(output_has_cleanup_complete_ack(&fragmented, &token));
    }

    #[test]
    fn durable_cleanup_proof_is_exact_token_bound_and_owner_only() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-cleanup-proof-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);
        let token = "a".repeat(64);
        let proof_path = cleanup_complete_proof_path(&path).unwrap();
        std::fs::write(&proof_path, format_cleanup_complete_proof(&token)).unwrap();
        harden_file(&proof_path);

        assert!(cleanup_complete_proof_matches_at(&path, &token));
        assert!(!cleanup_complete_proof_matches_at(&path, &"b".repeat(64)));
        std::fs::write(
            &proof_path,
            format!("{}trailing", format_cleanup_complete_proof(&token)),
        )
        .unwrap();
        assert!(!cleanup_complete_proof_matches_at(&path, &token));

        let _ = std::fs::remove_dir_all(root);
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
    fn sidecar_record_round_trips() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 99,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };

        assert_eq!(
            parse_sidecar_record(&format_sidecar_record(&record)),
            Some(record)
        );

        let pending = SidecarRecord {
            sidecar_pid: 4321,
            application_pid: None,
            shell_pid: 99,
            boot_id: "c".repeat(64),
            launch_token: "b".repeat(64),
        };
        assert_eq!(
            parse_sidecar_record(&format_sidecar_record(&pending)),
            Some(pending)
        );
    }

    #[test]
    fn rejects_incomplete_or_malformed_sidecar_records() {
        assert_eq!(parse_sidecar_record(""), None);
        assert_eq!(parse_sidecar_record("1234\n99\n"), None);
        assert_eq!(parse_sidecar_record("1234\n99\nshort-token\n"), None);
        assert_eq!(
            parse_sidecar_record(&format!("0\n99\n{}\n", "a".repeat(64))),
            None
        );
        assert_eq!(
            parse_sidecar_record(&format!("1234\n0\n{}\n", "a".repeat(64))),
            None
        );
        assert_eq!(
            parse_sidecar_record(&format!("1234\n99\n{}\nextra\n", "a".repeat(64))),
            None
        );
    }

    #[test]
    fn frozen_application_survives_dead_launcher_and_blocks_relaunch() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-frozen-child-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let contents = format!("v2\n1234\n5678\n77\n{}\n", "a".repeat(64));
        std::fs::write(&path, &contents).unwrap();

        let result = reap_stale_sidecar_at(
            &path,
            99,
            |pid| match pid {
                77 | 1234 => ProcessLiveness::Dead,
                5678 => ProcessLiveness::Alive,
                _ => panic!("unexpected pid {pid}"),
            },
            |pid| {
                assert_eq!(pid, 5678);
                Ok(Some(
                    "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
                        .to_string(),
                ))
            },
        );

        assert_eq!(result, Err(ReapError::SidecarStillAlive { pid: 5678 }));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), contents);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn current_contained_crash_before_application_pid_handshake_is_repairable() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-pending-child-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let contents = format_sidecar_record(&pending);
        std::fs::write(&path, &contents).unwrap();

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |_| ProcessLiveness::Dead,
                |_| panic!("identity lookup must not run for dead processes"),
            ),
            Ok(ReapOutcome::RemovedConfirmedDead)
        );
        assert!(!path.exists());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn pending_record_repair_requires_dead_spawn_containment() {
        assert!(pending_record_repair_allowed(
            true,
            LiveSidecarIdentity::Dead,
            ProcessLiveness::Dead,
        ));
        assert!(!pending_record_repair_allowed(
            true,
            LiveSidecarIdentity::Dead,
            ProcessLiveness::Alive,
        ));
        assert!(!pending_record_repair_allowed(
            false,
            LiveSidecarIdentity::Dead,
            ProcessLiveness::Dead,
        ));
        assert!(!pending_record_repair_allowed(
            true,
            LiveSidecarIdentity::Reused,
            ProcessLiveness::Dead,
        ));
    }

    #[cfg(unix)]
    #[test]
    fn sidecar_spawn_enters_its_own_process_group_before_exec() {
        use std::os::unix::process::ExitStatusExt;

        let mut command = std::process::Command::new("sh");
        command.args(["-c", "sleep 30"]);
        let (_events, mut child) = spawn_contained_std_command(command).unwrap();
        let pid = child.pid();
        extern "C" {
            fn getpgid(pid: i32) -> i32;
        }

        assert_eq!(unsafe { getpgid(pid as i32) }, pid as i32);
        child.kill().unwrap();
        let status = child.wait_for_test().unwrap();
        assert!(status.signal().is_some());
    }

    #[cfg(unix)]
    #[test]
    fn contained_kill_refuses_a_group_after_its_validated_leader_was_reaped() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-contained-group-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let descendant_path = root.join("descendant.pid");
        let mut command = std::process::Command::new("sh");
        command
            .args(["-c", "sleep 2 & printf '%s' \"$!\" > \"$1\"", "sh"])
            .arg(&descendant_path);
        let (_events, mut child) = spawn_contained_std_command(command).unwrap();
        let launcher_pid = child.pid();

        assert!(child.wait_for_test().unwrap().success());
        let deadline = Instant::now() + Duration::from_secs(2);
        while !descendant_path.exists() && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        let descendant_pid = std::fs::read_to_string(&descendant_path)
            .unwrap()
            .parse::<u32>()
            .unwrap();
        assert_eq!(process_liveness(descendant_pid), ProcessLiveness::Alive);
        let record = SidecarRecord {
            sidecar_pid: launcher_pid,
            application_pid: Some(launcher_pid),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        assert_eq!(process_tree_liveness(&record), ProcessLiveness::Alive);
        let record_path = root.join("desktop-backend.pid");
        let record_contents = format_sidecar_record(&record);
        std::fs::write(&record_path, &record_contents).unwrap();
        assert_eq!(
            reap_stale_sidecar_at(
                &record_path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    pid if pid == launcher_pid => ProcessLiveness::Dead,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Ok(None),
            ),
            Err(ReapError::SidecarStillAlive { pid: launcher_pid })
        );
        assert_eq!(
            std::fs::read_to_string(&record_path).unwrap(),
            record_contents
        );
        assert!(!wait_for_spawn_containment_exit(
            launcher_pid,
            Duration::ZERO
        ));

        let kill_result = child.kill();
        let exited = wait_for_process_exit(descendant_pid, Duration::from_millis(100));
        let containment_exited = wait_for_spawn_containment_exit(launcher_pid, Duration::ZERO);

        assert!(kill_result.is_err());
        assert!(
            !exited,
            "the signal sink targeted a group whose leader could have been reused"
        );
        assert!(
            !containment_exited,
            "the reused numeric group identifier was treated as stable authority"
        );
        assert!(wait_for_process_exit(
            descendant_pid,
            Duration::from_secs(3)
        ));
        assert!(wait_for_spawn_containment_exit(
            launcher_pid,
            Duration::from_secs(1)
        ));
        let _ = std::fs::remove_dir_all(root);
    }

    #[cfg(unix)]
    #[test]
    fn unrecorded_sidecar_cleanup_waits_for_complete_group_death() {
        let mut command = std::process::Command::new("sh");
        command.args(["-c", "sleep 30 & wait"]);
        let (_events, mut child) = spawn_contained_std_command(command).unwrap();
        let pgid = child.pid();

        assert!(terminate_unrecorded_sidecar(&mut child));

        assert!(wait_for_spawn_containment_exit(pgid, Duration::ZERO));
    }

    #[test]
    fn earlier_boot_pending_record_is_removed_without_pid_probes() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-earlier-boot-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "a".repeat(64),
            launch_token: "b".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&pending)).unwrap();

        assert_eq!(
            reap_stale_sidecar_at_for_boot(
                &path,
                99,
                &"c".repeat(64),
                |_| panic!("an earlier-boot PID must never be probed"),
                |_| panic!("an earlier-boot identity must never be queried"),
            ),
            Ok(ReapOutcome::RemovedEarlierBoot)
        );
        assert!(!path.exists());
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn legacy_record_without_application_pid_stays_fail_closed() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-legacy-dead-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        std::fs::write(&path, "1234\n77\n").unwrap();

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |_| ProcessLiveness::Dead,
                |_| panic!("identity lookup must not run for dead processes"),
            ),
            Err(ReapError::ApplicationPidPending { launcher_pid: 1234 })
        );
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "1234\n77\n");

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn live_legacy_backend_after_grace_is_retained_as_ambiguous() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-legacy-ambiguous-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let legacy_contents = "1234\n77\n";
        std::fs::write(&path, legacy_contents).unwrap();
        let grace_elapsed = std::cell::Cell::new(false);

        assert_eq!(
            reap_stale_sidecar_at_with_grace(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| {
                    let started_at = if grace_elapsed.get() {
                        "Fri Jul 11 10:11:13 2026"
                    } else {
                        "Fri Jul 11 10:11:12 2026"
                    };
                    Ok(Some(format!(
                        "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0\t1234\t{started_at}"
                    )))
                },
                |_| {
                    grace_elapsed.set(true);
                    false
                },
            ),
            Err(ReapError::SidecarStillAlive { pid: 1234 })
        );
        assert_eq!(std::fs::read_to_string(&path).unwrap(), legacy_contents);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn legacy_record_pid_reuse_still_cannot_prove_application_absence() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-legacy-reused-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        std::fs::write(&path, "1234\n77\n").unwrap();
        let pid_reused = std::cell::Cell::new(false);

        assert_eq!(
            reap_stale_sidecar_at_with_grace(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| {
                    if pid_reused.get() {
                        Ok(Some("/usr/bin/python3 unrelated.py".to_string()))
                    } else {
                        Ok(Some(
                            "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
                                .to_string(),
                        ))
                    }
                },
                |_| {
                    pid_reused.set(true);
                    false
                },
            ),
            Err(ReapError::ApplicationPidPending { launcher_pid: 1234 })
        );
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "1234\n77\n");

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn competing_kernel_lock_claimants_block_until_owner_drops() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-instance-compete-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-instance.lock");

        let first = DesktopInstanceLock::acquire_at(&path, 77, "a".repeat(64)).unwrap();
        let error = DesktopInstanceLock::acquire_at(&path, 99, "b".repeat(64)).unwrap_err();
        assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);

        drop(first);
        let successor = acquire_released_instance_lock(&path, 99, "b".repeat(64));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "99\n");
        drop(successor);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn unpublished_cleanup_retains_instance_lock_until_death_is_proven() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-instance-cleanup-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-instance.lock");
        let owner = DesktopInstanceLock::acquire_at(&path, 77, "a".repeat(64)).unwrap();
        let mut attempts = 0;

        retain_unpublished_cleanup_authority(
            || {
                attempts += 1;
                let error = DesktopInstanceLock::acquire_at(&path, 99, "b".repeat(64))
                    .expect_err("a successor claimed the lock before cleanup was proven");
                assert_eq!(error.kind(), std::io::ErrorKind::WouldBlock);
                attempts == 3
            },
            || {},
        );

        assert_eq!(attempts, 3);
        assert_eq!(
            DesktopInstanceLock::acquire_at(&path, 99, "b".repeat(64))
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::WouldBlock
        );
        drop(owner);
        let successor = acquire_released_instance_lock(&path, 99, "b".repeat(64));
        drop(successor);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn fs2_contention_error_is_recognised_cross_platform() {
        assert!(instance_lock_contended(&fs2::lock_contended_error()));
        assert!(!instance_lock_contended(&std::io::Error::new(
            std::io::ErrorKind::PermissionDenied,
            "not lock contention",
        )));
    }

    #[test]
    fn stale_or_empty_diagnostics_do_not_control_kernel_lock_ownership() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-instance-diagnostic-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-instance.lock");
        std::fs::write(&path, "stale or malformed diagnostic text\n").unwrap();

        let stale = DesktopInstanceLock::acquire_at(&path, 99, "a".repeat(64)).unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "99\n");
        drop(stale);

        std::fs::write(&path, "").unwrap();
        let empty = acquire_released_instance_lock(&path, 100, "b".repeat(64));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "100\n");
        drop(empty);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn unknown_sidecar_owner_refuses_reap_and_retains_record() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-unknown-owner-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();

        let result = reap_stale_sidecar_at(
            &path,
            99,
            |_| ProcessLiveness::Unknown,
            |_| panic!("identity lookup must not run for unknown liveness"),
        );

        assert_eq!(result, Err(ReapError::ShellLivenessUnknown { pid: 77 }));
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn live_tokenised_sidecar_refuses_reap_and_retains_record() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-live-sidecar-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();

        let result = reap_stale_sidecar_at(
            &path,
            99,
            |pid| match pid {
                77 => ProcessLiveness::Dead,
                1234 => ProcessLiveness::Alive,
                _ => panic!("unexpected pid {pid}"),
            },
            |pid| {
                assert_eq!(pid, 1234);
                Ok(Some(
                    "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
                        .to_string(),
                ))
            },
        );

        assert_eq!(result, Err(ReapError::SidecarStillAlive { pid: 1234 }));
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn immediate_relaunch_allows_watchdog_and_tick_flush_to_finish() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-watchdog-grace-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();
        let graceful_exit_finished = std::cell::Cell::new(false);

        assert_eq!(
            reap_stale_sidecar_at_with_grace(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 if graceful_exit_finished.get() => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    Ok(Some(
                        "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
                            .to_string(),
                    ))
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    graceful_exit_finished.set(true);
                    true
                },
            ),
            Ok(ReapOutcome::RemovedConfirmedDead)
        );
        assert!(!path.exists());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn live_sidecar_waits_full_grace_then_fails_closed() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-force-order-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();
        let order = std::cell::RefCell::new(Vec::new());

        assert_eq!(
            reap_stale_sidecar_at_with_grace(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    order.borrow_mut().push("identity");
                    Ok(Some(
                        "/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0"
                            .to_string(),
                    ))
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    order.borrow_mut().push("grace");
                    false
                },
            ),
            Err(ReapError::SidecarStillAlive { pid: 1234 })
        );
        assert_eq!(order.into_inner(), vec!["identity", "grace", "identity"]);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn same_name_pid_reuse_during_grace_fails_closed() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-grace-pid-reuse-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();
        let pid_reused = std::cell::Cell::new(false);

        assert_eq!(
            reap_stale_sidecar_at_with_grace(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    if pid_reused.get() {
                        Ok(Some("/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0\t1234\tFri Jul 11 10:11:13 2026".to_string()))
                    } else {
                        Ok(Some("/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0\t1234\tFri Jul 11 10:11:12 2026".to_string()))
                    }
                },
                |pid| {
                    assert_eq!(pid, 1234);
                    pid_reused.set(true);
                    false
                },
            ),
            Err(ReapError::SidecarStillAlive { pid: 1234 })
        );
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn ambiguous_liveness_or_identity_lookup_refuses_reap() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-ambiguous-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Unknown,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| panic!("identity lookup must not run for unknown liveness"),
            ),
            Err(ReapError::SidecarLivenessUnknown { pid: 1234 })
        );

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Err(std::io::Error::other("lookup failed")),
            ),
            Err(ReapError::ShellIdentityLookupFailed { pid: 77 })
        );

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Err(std::io::Error::other("lookup failed")),
            ),
            Err(ReapError::SidecarIdentityLookupFailed { pid: 1234 })
        );

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Ok(None),
            ),
            Err(ReapError::SidecarIdentityUnconfirmed { pid: 1234 })
        );
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn sidecar_record_is_published_atomically_without_overwrite() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-publish-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };

        write_sidecar_record_at(&path, &record).unwrap();
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);

        let replacement = SidecarRecord {
            sidecar_pid: 4321,
            launch_token: "b".repeat(64),
            ..record.clone()
        };
        let error = write_sidecar_record_at(&path, &replacement).unwrap_err();
        assert_eq!(error.kind(), std::io::ErrorKind::AlreadyExists);
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&record)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn application_pid_promotion_accepts_exact_python_prepublish() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-python-promotion-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        std::fs::write(&path, format_sidecar_record(&promoted)).unwrap();

        assert_eq!(
            promote_sidecar_record_at(&path, &pending, 5678).unwrap(),
            promoted
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn application_pid_promotion_replace_failure_keeps_a_complete_pending_record() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-promotion-fault-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        let pending_text = format_sidecar_record(&pending);
        std::fs::write(&path, &pending_text).unwrap();

        let error = atomically_replace_sidecar_record_with(
            &path,
            &pending_text,
            &format_sidecar_record(&promoted),
            &pending.launch_token,
            |_temporary, _destination| Err(std::io::Error::other("injected replace failure")),
        )
        .unwrap_err();

        assert_eq!(error.kind(), std::io::ErrorKind::Other);
        assert_eq!(std::fs::read_to_string(&path).unwrap(), pending_text);
        assert_eq!(
            parse_sidecar_record(&std::fs::read_to_string(&path).unwrap()),
            Some(pending)
        );
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn application_pid_promotion_post_replace_failure_leaves_a_complete_promoted_record() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-promotion-post-replace-fault-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        let pending_text = format_sidecar_record(&pending);
        let promoted_text = format_sidecar_record(&promoted);
        std::fs::write(&path, &pending_text).unwrap();

        let error = atomically_replace_sidecar_record_with(
            &path,
            &pending_text,
            &promoted_text,
            &pending.launch_token,
            |temporary, destination| {
                replace_path_atomically(temporary, destination)?;
                Err(std::io::Error::other("injected post-replace failure"))
            },
        )
        .unwrap_err();

        assert_eq!(error.kind(), std::io::ErrorKind::Other);
        assert_eq!(std::fs::read_to_string(&path).unwrap(), promoted_text);
        assert_eq!(
            parse_sidecar_record(&std::fs::read_to_string(&path).unwrap()),
            Some(promoted)
        );
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn sidecar_record_removal_requires_token_and_shell_match() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-removal-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let actual = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&actual)).unwrap();

        let wrong_shell = SidecarRecord {
            shell_pid: 88,
            ..actual.clone()
        };
        assert!(!remove_sidecar_record_at(&path, &wrong_shell).unwrap());
        assert!(path.exists());

        let wrong_token = SidecarRecord {
            launch_token: "b".repeat(64),
            ..actual.clone()
        };
        assert!(!remove_sidecar_record_at(&path, &wrong_token).unwrap());
        assert!(path.exists());

        assert!(remove_sidecar_record_at(&path, &actual).unwrap());
        assert!(!path.exists());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn sidecar_record_cleanup_waits_for_promotion_guard_and_rechecks_contents() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-removal-race-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        std::fs::write(&path, format_sidecar_record(&pending)).unwrap();

        let guard_path = sidecar_record_transition_guard_path(&path).unwrap();
        let guard = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(guard_path)
            .unwrap();
        guard.lock_exclusive().unwrap();

        let (started_tx, started_rx) = std::sync::mpsc::channel();
        let (result_tx, result_rx) = std::sync::mpsc::channel();
        let cleanup_path = path.clone();
        let cleanup_record = pending.clone();
        let cleanup = std::thread::spawn(move || {
            started_tx.send(()).unwrap();
            result_tx
                .send(remove_sidecar_record_at(&cleanup_path, &cleanup_record))
                .unwrap();
        });
        started_rx.recv().unwrap();
        assert!(result_rx
            .recv_timeout(std::time::Duration::from_millis(250))
            .is_err());

        std::fs::write(&path, format_sidecar_record(&promoted)).unwrap();
        FileExt::unlock(&guard).unwrap();
        assert!(!result_rx.recv().unwrap().unwrap());
        cleanup.join().unwrap();
        assert_eq!(
            std::fs::read_to_string(&path).unwrap(),
            format_sidecar_record(&promoted)
        );

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn record_transition_guard_initialises_the_shared_lock_byte() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-record-guard-byte-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);

        with_sidecar_record_transition_guard(&path, || ()).unwrap();

        let guard_path = sidecar_record_transition_guard_path(&path).unwrap();
        assert!(std::fs::metadata(guard_path).unwrap().len() >= 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn backend_recovery_is_only_shown_for_unexpected_termination() {
        assert!(!should_show_backend_recovery(true));
        assert!(should_show_backend_recovery(false));
    }

    #[test]
    fn main_window_close_exits_recovery_instead_of_hiding_to_tray() {
        assert_eq!(
            main_window_close_action(false, false),
            MainWindowCloseAction::HideToTray
        );
        assert_eq!(
            main_window_close_action(true, false),
            MainWindowCloseAction::AllowClose
        );
        assert_eq!(
            main_window_close_action(false, true),
            MainWindowCloseAction::ExitApp
        );
    }

    #[test]
    fn confirmed_dead_or_reused_sidecar_records_are_removed() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-safe-removal-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join("desktop-backend.pid");
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        std::fs::write(&path, format_sidecar_record(&record)).unwrap();

        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |_| ProcessLiveness::Dead,
                |_| panic!("identity lookup must not run for a dead process"),
            ),
            Ok(ReapOutcome::RemovedConfirmedDead)
        );
        assert!(!path.exists());

        std::fs::write(&path, format_sidecar_record(&record)).unwrap();
        assert_eq!(
            reap_stale_sidecar_at(
                &path,
                99,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Ok(Some("/usr/bin/python3 unrelated.py".to_string())),
            ),
            Ok(ReapOutcome::RemovedConfirmedReused)
        );
        assert!(!path.exists());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn current_boot_recovery_retains_a_dead_tree_without_guardian_cleanup_proof() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-cleanup-proof-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let contents = format_sidecar_record(&record);
        std::fs::write(&path, &contents).unwrap();

        assert_eq!(
            reap_stale_sidecar_at_for_boot_with_grace(
                &path,
                99,
                &record.boot_id,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Ok(Some("/usr/bin/python3 unrelated.py".to_string())),
                |_| false,
                |_| false,
            ),
            Err(ReapError::CleanupUnconfirmed)
        );
        assert_eq!(std::fs::read_to_string(&path).unwrap(), contents);

        let proof_path = cleanup_complete_proof_path(&path).unwrap();
        std::fs::write(
            &proof_path,
            format_cleanup_complete_proof(&record.launch_token),
        )
        .unwrap();
        harden_file(&proof_path);
        assert_eq!(
            reap_stale_sidecar_at_for_boot_with_grace(
                &path,
                99,
                &record.boot_id,
                |pid| match pid {
                    77 => ProcessLiveness::Dead,
                    1234 => ProcessLiveness::Alive,
                    _ => panic!("unexpected pid {pid}"),
                },
                |_| Ok(Some("/usr/bin/python3 unrelated.py".to_string())),
                |_| false,
                |current| {
                    current.is_some_and(|record| {
                        cleanup_complete_proof_matches_at(&path, &record.launch_token)
                    })
                },
            ),
            Ok(ReapOutcome::RemovedConfirmedReused)
        );
        assert!(!path.exists());
        assert!(!proof_path.exists());

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn same_boot_legacy_record_without_guardian_proof_is_retained() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-reap-legacy-proof-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);
        let boot_id = "c".repeat(64);
        let contents = format!("v3\n1234\n5678\n77\n{boot_id}\n{}\n", "a".repeat(64));
        std::fs::write(&path, &contents).unwrap();

        assert_eq!(
            reap_stale_sidecar_at_for_boot_with_grace(
                &path,
                99,
                &boot_id,
                |_| ProcessLiveness::Dead,
                |_| panic!("identity lookup must not run for a dead process"),
                |_| false,
                |_| false,
            ),
            Err(ReapError::CleanupUnconfirmed)
        );
        assert_eq!(std::fs::read_to_string(&path).unwrap(), contents);

        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn exit_confirmation_never_claims_the_current_process_is_dead() {
        assert_eq!(process_liveness(std::process::id()), ProcessLiveness::Alive);
        assert!(!wait_for_process_exit(std::process::id(), Duration::ZERO));
    }

    #[test]
    fn terminated_launcher_polls_recorded_application_until_confirmed_dead() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let states = std::cell::RefCell::new(std::collections::VecDeque::from([
            ProcessLiveness::Alive,
            ProcessLiveness::Unknown,
            ProcessLiveness::Alive,
            ProcessLiveness::Dead,
        ]));
        let probed = std::cell::RefCell::new(Vec::new());
        let waits = std::cell::Cell::new(0);

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |pid| {
                    probed.borrow_mut().push(pid);
                    states
                        .borrow_mut()
                        .pop_front()
                        .expect("test liveness sequence exhausted")
                },
                |_| Ok(Some("flinttrade-backend\t5678\tstable-start".to_string())),
                || waits.set(waits.get() + 1),
            ),
            RecordedApplicationExit::ConfirmedDead
        );
        assert_eq!(probed.into_inner(), vec![5678, 5678, 5678, 5678]);
        assert_eq!(waits.get(), 3);
    }

    #[test]
    fn terminated_launcher_with_pending_application_pid_fails_closed() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |_| panic!("pending application PID must not be probed"),
                |_| panic!("pending application identity must not be probed"),
                || panic!("pending application PID must not be polled"),
            ),
            RecordedApplicationExit::Unresolved
        );
    }

    #[test]
    fn terminated_launcher_stops_supervising_when_application_pid_is_reused() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let identities = std::cell::RefCell::new(std::collections::VecDeque::from([
            Ok(Some("flinttrade-backend\t5678\tfirst-start".to_string())),
            Ok(Some("flinttrade-backend\t5678\tfirst-start".to_string())),
            Ok(Some("unrelated-process\t5678\tsecond-start".to_string())),
        ]));
        let waits = std::cell::Cell::new(0);

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |_| ProcessLiveness::Alive,
                |_| identities
                    .borrow_mut()
                    .pop_front()
                    .expect("identity sequence exhausted"),
                || waits.set(waits.get() + 1),
            ),
            RecordedApplicationExit::ConfirmedReused
        );
        assert_eq!(waits.get(), 1);
    }

    #[test]
    fn terminated_launcher_rejects_reused_backend_identity_on_first_sample() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let expected = "flinttrade-backend\t5678\toriginal-start";
        let waits = std::cell::Cell::new(0);

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                Some(expected),
                |_| ProcessLiveness::Alive,
                |_| Ok(Some("flinttrade-backend\t5678\treused-start".to_string())),
                || waits.set(waits.get() + 1),
            ),
            RecordedApplicationExit::ConfirmedReused
        );
        assert_eq!(waits.get(), 0);
    }

    #[test]
    fn terminated_launcher_bounds_persistently_unknown_application_identity() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let first = std::cell::Cell::new(true);
        let waits = std::cell::Cell::new(0);

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                2,
                None,
                |_| ProcessLiveness::Unknown,
                |_| {
                    if first.replace(false) {
                        Ok(Some("flinttrade-backend\t5678\tstable-start".to_string()))
                    } else {
                        Err(std::io::Error::other("identity unavailable"))
                    }
                },
                || waits.set(waits.get() + 1),
            ),
            RecordedApplicationExit::Unresolved
        );
        assert_eq!(waits.get(), 1);
    }

    #[test]
    fn terminated_launcher_identity_error_after_exit_is_confirmed_dead() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |_| ProcessLiveness::Dead,
                |_| Err(std::io::Error::other(
                    "process exited during identity lookup"
                )),
                || panic!("a confirmed-dead process must not be polled"),
            ),
            RecordedApplicationExit::ConfirmedDead
        );
    }

    #[test]
    fn terminated_launcher_none_identity_requires_a_fresh_dead_liveness_probe() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };

        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |_| ProcessLiveness::Alive,
                |_| Ok(None),
                || panic!("an unconfirmed initial identity must not enter the poll loop"),
            ),
            RecordedApplicationExit::Unresolved
        );
        assert_eq!(
            wait_for_recorded_application_exit_with(
                &record,
                3,
                None,
                |_| ProcessLiveness::Dead,
                |_| Ok(None),
                || panic!("a confirmed-dead application must not be polled"),
            ),
            RecordedApplicationExit::ConfirmedDead
        );
    }

    #[test]
    fn pending_shutdown_uses_short_handshake_budget() {
        assert!(SIDECAR_PENDING_HANDSHAKE_TIMEOUT < SIDECAR_GRACEFUL_SHUTDOWN_TIMEOUT);
    }

    #[test]
    fn shutdown_refresh_accepts_only_this_launchs_pid_promotion() {
        let root = std::env::temp_dir().join(format!(
            "flinttrade-shutdown-refresh-{}",
            generate_launch_token().unwrap()
        ));
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(SIDECAR_PID_FILE);
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        std::fs::write(&path, format_sidecar_record(&promoted)).unwrap();

        assert_eq!(refresh_sidecar_record_at(&path, &pending), Some(promoted));

        let unrelated = SidecarRecord {
            launch_token: "b".repeat(64),
            ..pending.clone()
        };
        assert_eq!(refresh_sidecar_record_at(&path, &unrelated), None);
        let unrelated_boot = SidecarRecord {
            boot_id: "d".repeat(64),
            ..pending.clone()
        };
        assert_eq!(refresh_sidecar_record_at(&path, &unrelated_boot), None);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn shutdown_wait_extends_from_pending_to_confirmed_budget_after_promotion() {
        let mut pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };
        let refreshes = std::cell::RefCell::new(std::collections::VecDeque::from([
            Some(pending.clone()),
            Some(promoted.clone()),
            Some(promoted.clone()),
        ]));
        let promoted_polls = std::cell::Cell::new(0);

        assert!(wait_for_sidecar_shutdown_with(
            &mut pending,
            Duration::from_secs(1),
            Duration::from_secs(3),
            Instant::now() + Duration::from_secs(3),
            |_| refreshes.borrow_mut().pop_front().flatten(),
            |record| {
                if record.application_pid.is_none() {
                    ProcessLiveness::Unknown
                } else if promoted_polls.replace(promoted_polls.get() + 1) == 0 {
                    ProcessLiveness::Alive
                } else {
                    ProcessLiveness::Dead
                }
            },
            Instant::now,
            |_| {},
        ));
        assert_eq!(pending, promoted);
        assert_eq!(promoted_polls.get(), 2);
    }

    #[test]
    fn shutdown_wait_obeys_a_monotonic_wall_clock_deadline() {
        let mut record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let started = std::time::Instant::now();
        let deadline = started + std::time::Duration::from_millis(55);

        assert!(!wait_for_sidecar_shutdown_with(
            &mut record,
            std::time::Duration::from_millis(55),
            std::time::Duration::from_millis(55),
            deadline,
            |_| None,
            |_| ProcessLiveness::Alive,
            Instant::now,
            |duration| std::thread::sleep(duration.min(std::time::Duration::from_millis(30))),
        ));
        assert!(started.elapsed() < std::time::Duration::from_millis(110));
    }

    #[test]
    fn shutdown_wait_allows_the_complete_valid_sequential_python_cleanup() {
        let mut record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(5678),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let started = Instant::now();
        let clock = std::rc::Rc::new(std::cell::Cell::new(started));
        let liveness_clock = std::rc::Rc::clone(&clock);
        let now_clock = std::rc::Rc::clone(&clock);
        let wait_clock = std::rc::Rc::clone(&clock);
        let complete_at = started + Duration::from_secs(SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS);

        assert!(wait_for_sidecar_shutdown_with(
            &mut record,
            SIDECAR_PENDING_HANDSHAKE_TIMEOUT,
            SIDECAR_GRACEFUL_SHUTDOWN_TIMEOUT,
            started + SIDECAR_TOTAL_SHUTDOWN_TIMEOUT,
            |_| None,
            |_| {
                if liveness_clock.get() >= complete_at {
                    ProcessLiveness::Dead
                } else {
                    ProcessLiveness::Alive
                }
            },
            move || now_clock.get(),
            move |duration| wait_clock.set(wait_clock.get() + duration),
        ));
        assert!(clock.get() >= complete_at);
        assert!(clock.get() < started + SIDECAR_GRACEFUL_SHUTDOWN_TIMEOUT);
    }

    #[test]
    fn shutdown_identity_tracker_treats_pid_reuse_as_owned_process_exit() {
        let record = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: Some(1234),
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let identities = std::cell::RefCell::new(std::collections::VecDeque::from([
            Ok(Some(
                "flinttrade-backend\t1234\tFri Jul 11 10:11:12 2026".to_string(),
            )),
            Ok(Some(
                "flinttrade-backend\t1234\tFri Jul 11 10:11:13 2026".to_string(),
            )),
        ]));
        let mut tracker = ShutdownProcessIdentityTracker::default();

        assert_eq!(
            tracker.process_tree_liveness_with(
                &record,
                |_| ProcessLiveness::Alive,
                |_| identities.borrow_mut().pop_front().unwrap(),
            ),
            ProcessLiveness::Alive
        );
        assert_eq!(
            tracker.process_tree_liveness_with(
                &record,
                |_| ProcessLiveness::Alive,
                |_| identities.borrow_mut().pop_front().unwrap(),
            ),
            ProcessLiveness::Dead
        );
    }

    #[test]
    fn bound_process_identity_rejects_pid_reuse_on_first_shutdown_probe() {
        let mut tracked = TrackedProcessIdentity::default();
        tracked.bind(
            5678,
            "flinttrade-backend\t5678\tFri Jul 11 10:11:12 2026".to_string(),
        );

        assert_eq!(
            tracked.observe_with(5678, &mut |_| ProcessLiveness::Alive, &mut |_| {
                Ok(Some(
                    "flinttrade-backend\t5678\tFri Jul 11 10:11:13 2026".to_string(),
                ))
            },),
            ProcessLiveness::Dead
        );
    }

    #[test]
    fn pending_record_cleanup_requires_application_ack_and_dead_launcher() {
        let pending = SidecarRecord {
            sidecar_pid: 1234,
            application_pid: None,
            shell_pid: 77,
            boot_id: "c".repeat(64),
            launch_token: "a".repeat(64),
        };
        let promoted = SidecarRecord {
            application_pid: Some(5678),
            ..pending.clone()
        };

        assert!(pending_record_cleanup_allowed(
            &pending,
            PendingRecordExitProof::ApplicationAcknowledged,
            ProcessLiveness::Dead
        ));
        assert!(!pending_record_cleanup_allowed(
            &pending,
            PendingRecordExitProof::None,
            ProcessLiveness::Dead
        ));
        assert!(!pending_record_cleanup_allowed(
            &pending,
            PendingRecordExitProof::ApplicationAcknowledged,
            ProcessLiveness::Unknown
        ));
        assert!(!pending_record_cleanup_allowed(
            &promoted,
            PendingRecordExitProof::ApplicationAcknowledged,
            ProcessLiveness::Dead
        ));
    }

    #[test]
    fn force_cleanup_budget_exceeds_the_guardians_kill_confirmation() {
        assert!(SIDECAR_FORCE_EXIT_TIMEOUT > Duration::from_secs(5));
    }

    #[test]
    fn shared_shutdown_budget_includes_strategy_and_force_cleanup() {
        assert_eq!(
            SIDECAR_TOTAL_SHUTDOWN_TIMEOUT,
            Duration::from_secs(SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS + 20)
        );
        let started = Instant::now();
        let (graceful, force, shutdown) = shutdown_phase_deadlines(started);
        assert_eq!(force - graceful, SIDECAR_FORCE_EXIT_TIMEOUT);
        assert_eq!(shutdown - force, SIDECAR_KILL_CONFIRM_TIMEOUT);
        assert_eq!(shutdown - started, SIDECAR_TOTAL_SHUTDOWN_TIMEOUT);
        assert!(
            graceful - started
                >= Duration::from_secs(SIDECAR_PYTHON_SEQUENTIAL_SHUTDOWN_SECONDS + 10)
        );
    }

    #[test]
    fn stale_reap_grace_covers_python_watchdog_and_orphan_fallback() {
        // Python may poll for 2s, wait 12s, then spend up to 5s confirming
        // complete descendant cleanup in its external guardian.
        assert!(SIDECAR_WATCHDOG_GRACE_TIMEOUT > Duration::from_secs(19));
    }

    #[test]
    fn windows_wait_results_are_classified_without_process_commands() {
        assert_eq!(
            classify_windows_process_wait(Some(87), None),
            ProcessLiveness::Dead
        );
        assert_eq!(
            classify_windows_process_wait(None, Some(0x0000_0102)),
            ProcessLiveness::Alive
        );
        assert_eq!(
            classify_windows_process_wait(None, Some(0x0000_0000)),
            ProcessLiveness::Dead
        );
        assert_eq!(
            classify_windows_process_wait(Some(5), None),
            ProcessLiveness::Unknown
        );
    }

    #[test]
    fn windows_job_breakaway_is_reserved_for_the_detached_updater() {
        assert_ne!(
            WINDOWS_SHELL_JOB_LIMIT_FLAGS & WINDOWS_JOB_OBJECT_LIMIT_KILL_ON_CLOSE,
            0
        );
        assert_ne!(
            WINDOWS_SHELL_JOB_LIMIT_FLAGS & WINDOWS_JOB_OBJECT_LIMIT_BREAKAWAY_OK,
            0
        );
        assert_ne!(
            WINDOWS_DETACHED_UPDATER_FLAGS & WINDOWS_CREATE_BREAKAWAY_FROM_JOB,
            0
        );
        assert_eq!(
            WINDOWS_BACKEND_CREATION_FLAGS & WINDOWS_CREATE_BREAKAWAY_FROM_JOB,
            0
        );
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
    fn payload_version_strings_are_validated_for_directory_safety() {
        assert!(valid_payload_version("0.7.0"));
        assert!(valid_payload_version("0.7.0-beta.2"));
        assert!(valid_payload_version("1.2.3+build.5"));

        assert!(!valid_payload_version(""));
        assert!(!valid_payload_version("."));
        assert!(!valid_payload_version(".."));
        assert!(!valid_payload_version("../escape"));
        assert!(!valid_payload_version("0.7.0/evil"));
        assert!(!valid_payload_version("0.7.0\\evil"));
        assert!(!valid_payload_version(".hidden"));
        assert!(!valid_payload_version("-flag"));
        assert!(!valid_payload_version(&"9".repeat(65)));
    }

    #[test]
    fn payload_state_parsing_rejects_malformed_pins() {
        let sha = "a".repeat(64);
        let state = parse_payload_state(&format!(
            r#"{{"active_version": "0.7.0", "sha256": "{sha}"}}"#
        ))
        .unwrap();
        assert_eq!(state.active_version, "0.7.0");
        assert_eq!(state.sha256, sha);

        assert!(parse_payload_state("").is_none());
        assert!(parse_payload_state("not json").is_none());
        assert!(parse_payload_state(r#"{"active_version": "0.7.0"}"#).is_none());
        assert!(parse_payload_state(&format!(
            r#"{{"active_version": "../up", "sha256": "{sha}"}}"#
        ))
        .is_none());
        assert!(parse_payload_state(r#"{"active_version": "0.7.0", "sha256": "short"}"#).is_none());
    }

    #[test]
    fn payload_manifest_parses_the_published_shape() {
        let manifest = parse_payload_manifest(
            r#"{
                "tag": "v0.7.0",
                "version": "0.7.0",
                "channel": "beta",
                "prerelease": true,
                "assets": [],
                "payloads": {
                    "aarch64-apple-darwin": {
                        "name": "flinttrade-payload-aarch64-apple-darwin",
                        "size": 123,
                        "url": "https://example.invalid/payload",
                        "sha256": "aaaa"
                    }
                }
            }"#,
        )
        .unwrap();
        assert_eq!(manifest.version, "0.7.0");
        let entry = manifest.payloads.get("aarch64-apple-darwin").unwrap();
        assert_eq!(entry.name, "flinttrade-payload-aarch64-apple-darwin");
        assert_eq!(entry.size, 123);
        assert_eq!(entry.url, "https://example.invalid/payload");
        assert_eq!(entry.sha256, "aaaa");
        assert!(manifest.payloads.get("x86_64-pc-windows-msvc").is_none());

        assert!(parse_payload_manifest("not json").is_err());
        assert!(parse_payload_manifest(r#"{"payloads": {}}"#).is_err());
    }

    #[test]
    fn manifest_payload_resolution_pins_the_target_triple_and_validates_shape() {
        let good = parse_payload_manifest(&format!(
            r#"{{
                "version": "0.7.0",
                "payloads": {{
                    "{PAYLOAD_TARGET_TRIPLE}": {{
                        "name": "flinttrade-payload",
                        "size": 123,
                        "url": "https://example.invalid/payload",
                        "sha256": "{}"
                    }}
                }}
            }}"#,
            "a".repeat(64)
        ))
        .unwrap();
        let (version, entry) = resolve_manifest_payload(&good).unwrap();
        assert_eq!(version, "0.7.0");
        assert_eq!(entry.size, 123);

        // No entry for this build's triple.
        let missing = parse_payload_manifest(
            r#"{"version": "0.7.0", "payloads": {"made-up-triple": {
                "name": "n", "size": 1, "url": "u", "sha256": "aaaa"}}}"#,
        )
        .unwrap();
        assert!(resolve_manifest_payload(&missing)
            .unwrap_err()
            .contains("this platform"));

        // Malformed version and digest are both refused.
        let bad_version = parse_payload_manifest(&format!(
            r#"{{"version": "../escape", "payloads": {{"{PAYLOAD_TARGET_TRIPLE}": {{
                "name": "n", "size": 1, "url": "u", "sha256": "{}"}}}}}}"#,
            "a".repeat(64)
        ))
        .unwrap();
        assert!(resolve_manifest_payload(&bad_version)
            .unwrap_err()
            .contains("malformed"));
        let bad_digest = parse_payload_manifest(&format!(
            r#"{{"version": "0.7.0", "payloads": {{"{PAYLOAD_TARGET_TRIPLE}": {{
                "name": "n", "size": 1, "url": "u", "sha256": "short"}}}}}}"#,
        ))
        .unwrap();
        assert!(resolve_manifest_payload(&bad_digest)
            .unwrap_err()
            .contains("malformed"));
    }

    #[test]
    fn bootstrap_retry_is_admissible_only_from_the_failed_stage() {
        assert_eq!(
            bootstrap_retry_transition(BootstrapStage::Failed),
            Ok(BootstrapStage::Running)
        );
        assert!(bootstrap_retry_transition(BootstrapStage::Running).is_err());
        assert!(bootstrap_retry_transition(BootstrapStage::Started).is_err());
    }

    #[test]
    fn download_progress_status_shapes_percentages_and_megabyte_counts() {
        let status = download_progress_status(12_300_000, 48_600_000);
        assert_eq!(status.phase, "downloading");
        assert_eq!(status.pct, Some(25));
        assert_eq!(
            status.message,
            "Downloading the trading engine — 12.3 MB of 48.6 MB"
        );

        // Progress is capped at the declared total.
        let capped = download_progress_status(50_000_000, 48_600_000);
        assert_eq!(capped.pct, Some(100));
        assert_eq!(
            capped.message,
            "Downloading the trading engine — 48.6 MB of 48.6 MB"
        );

        // Unknown total: no percentage, running byte count only.
        let unknown = download_progress_status(1_000_000, 0);
        assert_eq!(unknown.pct, None);
        assert_eq!(unknown.message, "Downloading the trading engine — 1.0 MB");

        assert_eq!(download_progress_status(0, 48_600_000).pct, Some(0));
        assert_eq!(format_megabytes(0), "0.0 MB");
        assert_eq!(format_megabytes(48_600_000), "48.6 MB");
    }

    #[test]
    fn bootstrap_status_serialises_the_splash_event_contract() {
        let status = BootstrapStatus {
            phase: "downloading",
            pct: Some(42),
            message: "Downloading the trading engine — 1.0 MB of 2.0 MB".to_string(),
        };
        let value = serde_json::to_value(&status).unwrap();
        assert_eq!(value["phase"], "downloading");
        assert_eq!(value["pct"], 42);
        assert_eq!(
            value["message"],
            "Downloading the trading engine — 1.0 MB of 2.0 MB"
        );

        let error = BootstrapStatus {
            phase: "error",
            pct: None,
            message: "The update feed is unreachable.".to_string(),
        };
        let value = serde_json::to_value(&error).unwrap();
        assert_eq!(value["pct"], serde_json::Value::Null);
    }

    #[test]
    fn payload_endpoint_follows_the_compiled_release_channel() {
        let endpoint = payload_manifest_endpoint();
        let expected_channel = if env!("CARGO_PKG_VERSION").contains('-') {
            "updater-beta"
        } else {
            "updater-stable"
        };
        assert!(endpoint.contains(expected_channel));
        assert!(endpoint.ends_with("flinttrade-desktop-manifest.json"));
        assert!(!PAYLOAD_TARGET_TRIPLE.is_empty());
    }

    #[test]
    fn sha256_file_matches_the_reference_digest() {
        let path = std::env::temp_dir().join(format!(
            "flinttrade-payload-sha-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::write(&path, b"abc").unwrap();
        assert_eq!(
            sha256_file(&path).unwrap(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn verified_payload_boot_requires_a_matching_sha256_pin() {
        let dir = std::env::temp_dir().join(format!(
            "flinttrade-payload-verify-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).unwrap();

        // No state file: no managed payload, so the first-run bootstrap
        // downloads one.
        assert!(matches!(verified_active_payload_binary_at(&dir), Ok(None)));

        // A valid pin over the exact staged binary resolves it for boot.
        let version_dir = dir.join("0.7.0");
        std::fs::create_dir_all(&version_dir).unwrap();
        let binary = version_dir.join(PAYLOAD_BINARY_NAME);
        std::fs::write(&binary, b"payload-bytes").unwrap();
        let digest = sha256_file(&binary).unwrap();
        write_payload_state_at(
            &dir,
            &PayloadState {
                active_version: "0.7.0".to_string(),
                sha256: digest,
            },
        )
        .unwrap();
        let (version, path) = verified_active_payload_binary_at(&dir).unwrap().unwrap();
        assert_eq!(version, "0.7.0");
        assert_eq!(path, binary);

        // Tampering with the staged binary invalidates the pin.
        std::fs::write(&binary, b"tampered").unwrap();
        assert!(verified_active_payload_binary_at(&dir).is_err());

        // A missing binary and a malformed state file are errors (logged and
        // fallen back from), never a silent managed boot.
        std::fs::remove_file(&binary).unwrap();
        assert!(verified_active_payload_binary_at(&dir).is_err());
        std::fs::write(dir.join(PAYLOAD_STATE_FILE), "not json").unwrap();
        assert!(verified_active_payload_binary_at(&dir).is_err());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn pruning_retains_only_the_named_payload_versions() {
        let dir = std::env::temp_dir().join(format!(
            "flinttrade-payload-prune-test-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        for version in ["0.5.0", "0.6.0", "0.7.0", PAYLOAD_STAGING_DIR] {
            std::fs::create_dir_all(dir.join(version)).unwrap();
        }
        std::fs::write(dir.join(PAYLOAD_STATE_FILE), "{}").unwrap();

        prune_payload_versions_at(&dir, &["0.7.0", PAYLOAD_STATE_FILE, "0.6.0"]);

        assert!(!dir.join("0.5.0").exists());
        assert!(!dir.join(PAYLOAD_STAGING_DIR).exists());
        assert!(dir.join("0.6.0").is_dir());
        assert!(dir.join("0.7.0").is_dir());
        assert!(dir.join(PAYLOAD_STATE_FILE).is_file());

        let _ = std::fs::remove_dir_all(&dir);
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
        assert_eq!(
            handoff_decision(true, Some(false)),
            HandoffDecision::Proceed
        );
        // No marker, still running -> keep waiting (a slow download must not
        // make the app vanish).
        assert_eq!(handoff_decision(false, None), HandoffDecision::KeepWaiting);
        // No marker, exited with failure -> the update could not proceed; stay
        // alive and surface it.
        assert_eq!(
            handoff_decision(false, Some(false)),
            HandoffDecision::Failed
        );
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
        // macOS/Linux `ps -o args=` output for the managed backend payload.
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
    fn unix_ps_identity_uses_kernel_resolution_process_start_time() {
        let command =
            "1234 /Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0";

        assert_eq!(
            parse_unix_ps_identity(command, 1234, "macos-start-time:100:1"),
            Some("/Applications/FlintTrade.app/Contents/MacOS/flinttrade-backend --port 0\t1234\tmacos-start-time:100:1".to_string())
        );
        assert_ne!(
            parse_unix_ps_identity(command, 1234, "macos-start-time:100:2"),
            parse_unix_ps_identity(command, 1234, "macos-start-time:100:1")
        );
    }

    #[cfg(unix)]
    #[test]
    fn unix_process_identity_is_stable_and_kernel_bound() {
        let first = process_command_line(std::process::id())
            .unwrap()
            .expect("current process identity");
        let second = process_command_line(std::process::id())
            .unwrap()
            .expect("current process identity");

        assert_eq!(first, second);
        assert!(first.contains("\tlinux-start-ticks:") || first.contains("\tmacos-start-time:"));
    }

    #[test]
    fn boot_session_identity_is_stable_and_record_safe() {
        let first = boot_session_identity().expect("boot identity");
        let second = boot_session_identity().expect("boot identity");

        assert_eq!(first, second);
        assert!(valid_boot_id(&first));
    }

    #[test]
    fn windows_process_identity_includes_creation_time() {
        let before = "flinttrade-backend\t1234\t134126574720000000";
        let after = "flinttrade-backend\t1234\t134126574730000000";

        assert_eq!(
            parse_windows_process_identity(before, 1234),
            Some(before.to_string())
        );
        assert_ne!(
            parse_windows_process_identity(after, 1234),
            parse_windows_process_identity(before, 1234)
        );
    }

    #[test]
    fn desktop_shell_identity_covers_packaged_platform_names() {
        assert!(looks_like_desktop_shell(
            "/opt/FlintTrade/flinttrade --some-runtime-flag"
        ));
        assert!(looks_like_desktop_shell(
            "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade"
        ));
        assert!(looks_like_desktop_shell(
            "\"FlintTrade.exe\",\"1234\",\"Console\",\"1\",\"120,000 K\""
        ));
        assert!(!looks_like_desktop_shell(
            "/opt/FlintTrade/flinttrade-backend --port 0"
        ));
        assert!(!looks_like_desktop_shell("/usr/bin/python3 unrelated.py"));
    }

    #[test]
    fn posix_watchdog_parent_identity_must_be_confirmed_before_spawn() {
        let identity = "/Applications/FlintTrade.app/Contents/MacOS/FlintTrade\t77\tstable-start";

        assert_eq!(
            required_parent_identity_with(77, |_| Ok(Some(identity.to_string()))).unwrap(),
            identity
        );
        assert_eq!(
            required_parent_identity_with(77, |_| Ok(None))
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::NotFound
        );
        assert_eq!(
            required_parent_identity_with(77, |_| Err(std::io::Error::other("lookup failed")))
                .unwrap_err()
                .kind(),
            std::io::ErrorKind::Other
        );
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
