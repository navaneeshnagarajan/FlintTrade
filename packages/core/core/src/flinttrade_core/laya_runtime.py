"""Opt-in sidecar for the Laya decision model.

The sidecar is a separate virtual environment so torch stays out of the
FlintTrade environment. It binds ``127.0.0.1`` (the upstream default binds
every interface with no authentication), mints a fresh API key on each boot,
and pins the checkpoint revision and weight digest. After the first successful
load, later boots stay offline. CPU is the only device this runtime starts.
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .owner_file_lock import OwnerSafeFileLock
from .secure_file import harden, harden_directory

LAYA_SERVE_REQUIREMENT = "laya[serve]==0.3.21"
LAYA_BIND_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000
_HEALTH_TIMEOUT_SECONDS = 0.5

_process_runtime: Any = None
_process_runtime_lock = threading.Lock()


class LayaRuntimeError(RuntimeError):
    """The managed sidecar could not be installed or started."""


def venv_python(venv_dir: Path) -> Path:
    """Return the interpreter inside a sidecar virtual environment."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def serve_executable(venv_dir: Path) -> Path:
    """Return the ``laya-serve`` entry point inside the sidecar environment."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "laya-serve.exe"
    return venv_dir / "bin" / "laya-serve"


def install_command(venv_dir: Path) -> list[str]:
    """Pip command that pins the sidecar. It never targets the main interpreter."""
    return [
        str(venv_python(venv_dir)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        LAYA_SERVE_REQUIREMENT,
    ]


def set_process_runtime(runtime: LayaRuntime | None) -> None:
    """Register the sidecar the health probe should read."""
    global _process_runtime
    with _process_runtime_lock:
        _process_runtime = runtime


def process_runtime() -> LayaRuntime | None:
    """Return the registered sidecar, if the operator started one."""
    with _process_runtime_lock:
        return _process_runtime


def reset_process_runtime_for_tests() -> None:
    """Drop the registered sidecar. Does not stop a process the test did not start."""
    set_process_runtime(None)


def refresh_process_laya_status() -> None:
    """Apply sidecar health to process Laya. No sidecar leaves the stored status."""
    runtime = process_runtime()
    if runtime is None:
        return
    runtime.publish_status()


class LayaRuntime:
    """Install and supervise one loopback ``laya-serve`` process."""

    def __init__(
        self,
        workspace_dir: Path,
        *,
        host: str = LAYA_BIND_HOST,
        port: int = _DEFAULT_PORT,
        device: str = "cpu",
        process_factory: Callable[[list[str], dict[str, str]], Any] | None = None,
        installer: Callable[[Path, list[str]], None] | None = None,
        health_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
    ) -> None:
        if host != LAYA_BIND_HOST:
            raise LayaRuntimeError("Laya sidecar must bind 127.0.0.1")
        if device != "cpu":
            raise LayaRuntimeError("Laya runs on CPU until an accelerator runtime is qualified")
        if not 1 <= port <= 65535:
            raise LayaRuntimeError("Laya sidecar port is invalid")
        self.workspace_dir = workspace_dir.expanduser().resolve()
        self.runtime_root = self.workspace_dir / "runtime" / "laya"
        self.venv_dir = self.runtime_root / "venv"
        self._port = port
        self._device = device
        self._process_factory = process_factory or self._spawn
        self._installer = installer
        self._health_reader = health_reader
        self._process: Any | None = None
        self._api_key = ""
        self._lock = threading.RLock()

    @property
    def base_url(self) -> str:
        """Loopback origin of this sidecar."""
        return f"http://{LAYA_BIND_HOST}:{self._port}"

    def install(self) -> Path:
        """Create the sidecar environment and install the pinned package.

        Returns:
            The virtual environment directory. Torch is installed there, not
            into the interpreter that is running FlintTrade.
        """
        self._ensure_dirs()
        with self._file_lock():
            command = install_command(self.venv_dir)
            if self._installer is not None:
                self._installer(self.venv_dir, command)
            else:
                _default_install(self.venv_dir, command)
            _write_json(self.runtime_root / "install.json", {"requirement": LAYA_SERVE_REQUIREMENT})
        return self.venv_dir

    def start(self) -> str:
        """Start ``laya-serve`` with a new API key. Returns the loopback origin."""
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import SystemOneClient, load_policy  # noqa: PLC0415

        policy = load_policy()
        self._ensure_dirs()
        with self._lock, self._file_lock():
            if self._process is not None:
                _terminate(self._process)
                self._process = None
            api_key = secrets.token_urlsafe(32)
            _write_private(self.runtime_root / "api.key", api_key)
            cached = self._weights_cached()
            threads = _thread_budget()
            env = os.environ.copy()
            env.update(
                {
                    "LAYA_HOST": LAYA_BIND_HOST,
                    "LAYA_PORT": str(self._port),
                    "LAYA_DEVICE": "cpu",
                    "LAYA_PRELOAD": "1",
                    "LAYA_MODELS": policy.checkpoint,
                    "LAYA_MAX_LOADED": "1",
                    "LAYA_API_KEY": api_key,
                    "LAYA_REVISION": policy.revision,
                    "LAYA_SHA256_DIGESTS": json.dumps({policy.weight_file: policy.sha256}),
                    "LAYA_THREADS": str(threads),
                    "HF_HUB_OFFLINE": "1" if cached else "0",
                }
            )
            if cached:
                env["TRANSFORMERS_OFFLINE"] = "1"
            else:
                env.pop("TRANSFORMERS_OFFLINE", None)
            argv = [str(serve_executable(self.venv_dir))]
            process = self._process_factory(argv, env)
            self._process = process
            self._api_key = api_key
            process_laya().set_decision_client(
                SystemOneClient(
                    self.base_url,
                    api_key=api_key,
                    expected_revision=policy.revision,
                    expected_sha256=policy.sha256,
                )
            )
            set_process_runtime(self)
        return self.base_url

    def stop(self) -> None:
        """Stop the sidecar and record Down. The API key from this boot is dropped."""
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

        with self._lock, self._file_lock():
            process = self._process
            self._process = None
            self._api_key = ""
            if process is not None:
                _terminate(process)
            engine = process_laya()
            engine.set_decision_client(None)
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)

    def publish_status(self) -> Any:
        """Read ``/health`` and record Ready, Degraded, or Down."""
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import publish_probe  # noqa: PLC0415

        try:
            payload = self.read_health()
        except Exception:
            payload = None
        status = publish_probe(process_laya(), payload, requested_device=self._device)
        if status is not DecisionStatus.DOWN and isinstance(payload, Mapping):
            self._mark_weights_cached()
        return status

    def read_health(self) -> Mapping[str, Any] | None:
        """Return the sidecar health document, or ``None`` when it cannot be read."""
        if self._health_reader is not None:
            return self._health_reader(self.base_url)
        return _read_loopback_health(self.base_url)

    def _weights_cached(self) -> bool:
        path = self.runtime_root / "state.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return isinstance(payload, dict) and payload.get("weights_cached") is True

    def _mark_weights_cached(self) -> None:
        self._ensure_dirs()
        _write_json(self.runtime_root / "state.json", {"weights_cached": True})

    def _ensure_dirs(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        harden_directory(self.runtime_root)

    def _file_lock(self) -> OwnerSafeFileLock:
        return OwnerSafeFileLock(str(self.runtime_root / "laya.lock"), timeout=10)

    def _spawn(self, argv: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
        log_path = self.runtime_root / "laya-serve.log"
        log_file = log_path.open("ab")
        try:
            return subprocess.Popen(  # noqa: S603
                argv,
                env=env,
                cwd=self.runtime_root,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            log_file.close()
            raise


def _default_install(venv_dir: Path, command: list[str]) -> None:
    if Path(command[0]).resolve() == Path(sys.executable).resolve():
        raise LayaRuntimeError("Laya install must not use the FlintTrade interpreter")
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)  # noqa: S603
    if Path(command[0]).resolve() == Path(sys.executable).resolve():
        raise LayaRuntimeError("Laya install must not use the FlintTrade interpreter")
    subprocess.run(command, check=True)  # noqa: S603


def _thread_budget() -> int:
    logical = os.cpu_count() or 2
    return max(1, min(8, logical // 2 or 1))


def _write_private(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, text.encode("utf-8"))
    finally:
        os.close(descriptor)
    harden(path)


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    _write_private(path, json.dumps(payload, sort_keys=True))


def _read_loopback_health(base_url: str) -> Mapping[str, Any] | None:
    from urllib.parse import urlsplit

    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname != LAYA_BIND_HOST or parsed.port is None:
        raise LayaRuntimeError("Laya health probe must use the loopback sidecar")
    request = urllib.request.Request(f"{base_url}/health", method="GET")
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=_HEALTH_TIMEOUT_SECONDS) as response:  # noqa: S310
            raw = response.read(1_000_001)
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _terminate(process: Any) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix" and getattr(process, "pid", None):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            process.terminate()
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "posix" and getattr(process, "pid", None):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                process.kill()
        else:
            process.kill()
        process.wait(timeout=5)
