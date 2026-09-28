"""Opt-in sidecar for the Laya decision model.

The sidecar is a separate virtual environment so torch stays out of the
FlintTrade environment. The default install puts CPU torch in that
environment, from the PyTorch CPU index, before the pinned ``laya[serve]``
package. CUDA and ROCm builds stay opt-in. It binds ``127.0.0.1`` (the
upstream default binds every interface with no authentication), mints a
fresh API key on each boot, and pins the checkpoint revision and weight
digest. After the first successful load, later boots stay offline. CPU is
the only device this runtime starts.

Run ``python -m flinttrade_core.laya_runtime install|start|stop|status``
with the FlintTrade interpreter.
"""

from __future__ import annotations

import argparse
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
CPU_TORCH_INDEX = "https://download.pytorch.org/whl/cpu"
_DEFAULT_PORT = 8000
_HEALTH_TIMEOUT_SECONDS = 0.5
_ACCELERATORS = frozenset({"cpu", "cuda", "rocm"})

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
    """Pip command that pins ``laya[serve]`` inside the sidecar environment."""
    return [
        str(venv_python(venv_dir)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade-strategy",
        "only-if-needed",
        LAYA_SERVE_REQUIREMENT,
    ]


def cpu_torch_command(venv_dir: Path) -> list[str]:
    """Pip command that installs CPU-only torch into the sidecar environment."""
    return [
        str(venv_python(venv_dir)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--index-url",
        CPU_TORCH_INDEX,
        "torch",
    ]


def install_commands(venv_dir: Path, *, accelerator: str = "cpu") -> list[list[str]]:
    """Pip commands for one sidecar install.

    ``cpu`` installs torch from the PyTorch CPU index first, then the pinned
    package, so a later resolve does not replace that wheel with a CUDA build.
    ``cuda`` installs torch from PyPI. ``rocm`` installs torch from the https
    index in ``LAYA_TORCH_INDEX``.
    """
    if accelerator not in _ACCELERATORS:
        raise LayaRuntimeError("Laya accelerator must be cpu, cuda, or rocm")
    pinned = install_command(venv_dir)
    if accelerator == "cpu":
        return [cpu_torch_command(venv_dir), pinned]
    if accelerator == "cuda":
        return [_accelerator_torch_command(venv_dir, None), pinned]
    index = os.environ.get("LAYA_TORCH_INDEX", "").strip()
    if not index.startswith("https://"):
        raise LayaRuntimeError("ROCm install needs LAYA_TORCH_INDEX set to an https PyTorch ROCm wheel index")
    return [_accelerator_torch_command(venv_dir, index), pinned]


def venv_prefix(python: Path) -> Path:
    """Return a virtual environment prefix without resolving the interpreter symlink.

    A sidecar ``bin/python`` often points at the same base executable as the
    FlintTrade environment. The prefix is the environment directory.
    """
    parent = python.parent
    if parent.name in {"bin", "Scripts"}:
        return parent.parent
    return parent


def install_uses_flinttrade_interpreter(python: Path, flint_prefix: Path) -> bool:
    """True when ``python`` would install into the FlintTrade environment."""
    return venv_prefix(python).expanduser().resolve() == Path(flint_prefix).expanduser().resolve()


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
    """Apply sidecar health to process Laya.

    No sidecar leaves the stored status. When ``LAYA_API_KEY_FILE`` is set,
    an already-running backend attaches to that loopback sidecar first.
    """
    runtime = process_runtime()
    if runtime is None:
        runtime = attach_from_environment()
    if runtime is None:
        return
    runtime.publish_status()


def attach_from_environment(workspace: Path | None = None) -> LayaRuntime | None:
    """Attach this process to a sidecar that was started separately.

    ``LAYA_API_KEY_FILE`` selects the key file. ``LAYA_HOST`` and ``LAYA_PORT``
    select the origin and must stay on ``127.0.0.1``. A missing key records
    Down and does not attach. The decision client still requires the policy
    revision and weight digest.
    """
    key_file = os.environ.get("LAYA_API_KEY_FILE", "").strip()
    if not key_file:
        return None
    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    host = os.environ.get("LAYA_HOST", LAYA_BIND_HOST).strip() or LAYA_BIND_HOST
    port_text = os.environ.get("LAYA_PORT", str(_DEFAULT_PORT)).strip()
    try:
        port = int(port_text)
    except ValueError as exc:
        raise LayaRuntimeError("Laya sidecar port is invalid") from exc
    root = workspace if workspace is not None else workspace_dir()
    runtime = LayaRuntime(root, host=host, port=port)
    key_path = Path(key_file).expanduser()
    if not key_path.is_file():
        _record_attach_down()
        return None
    runtime.attach(key_path)
    return runtime


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
        self._attached = False
        self._api_key = ""
        self._generation = 0
        self._lock = threading.RLock()

    @property
    def base_url(self) -> str:
        """Loopback origin of this sidecar."""
        return f"http://{LAYA_BIND_HOST}:{self._port}"

    def install(self, *, accelerator: str = "cpu") -> Path:
        """Create the sidecar environment and install the pinned package.

        Args:
            accelerator: ``cpu`` (default) installs CPU torch first. ``cuda``
                and ``rocm`` are opt-in and are not used by :meth:`start`.

        Returns:
            The virtual environment directory. Torch is installed there, not
            into the interpreter that is running FlintTrade.
        """
        self._ensure_dirs()
        commands = install_commands(self.venv_dir, accelerator=accelerator)
        with self._file_lock():
            if self._installer is not None:
                for command in commands:
                    self._installer(self.venv_dir, command)
            else:
                _default_install(self.venv_dir, commands)
            _write_json(
                self.runtime_root / "install.json",
                {"requirement": LAYA_SERVE_REQUIREMENT, "accelerator": accelerator},
            )
        return self.venv_dir

    def start(self) -> str:
        """Start ``laya-serve`` with a new API key. Returns the loopback origin."""
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import SystemOneClient, load_policy  # noqa: PLC0415

        policy = load_policy()
        self._ensure_dirs()
        spawned: Any | None = None
        with self._lock, self._file_lock():
            if self._process is not None:
                _terminate(self._process)
                self._process = None
            self._attached = False
            _unlink_quiet(self._key_path)
            _unlink_quiet(self._pid_path)
            api_key = secrets.token_urlsafe(32)
            try:
                _write_private(self._key_path, api_key)
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
                spawned = self._process_factory(argv, env)
                self._process = spawned
                pid = getattr(spawned, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    _write_private(self._pid_path, str(pid))
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
            except Exception:
                self._process = None
                self._api_key = ""
                self._attached = False
                _unlink_quiet(self._key_path)
                _unlink_quiet(self._pid_path)
                _clear_decision_client()
                if spawned is not None:
                    _terminate(spawned)
                raise
        return self.base_url

    def attach(self, key_path: Path) -> str:
        """Use an existing loopback sidecar. Does not spawn a process.

        The client is pinned to the policy revision and weight digest. A later
        health document that omits or mismatches that digest stays Down.
        """
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import SystemOneClient, load_policy  # noqa: PLC0415

        try:
            api_key = key_path.expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LayaRuntimeError("Laya API key file cannot be read") from exc
        if not api_key:
            _record_attach_down()
            raise LayaRuntimeError("Laya API key file is empty")
        policy = load_policy()
        client = SystemOneClient(
            self.base_url,
            api_key=api_key,
            expected_revision=policy.revision,
            expected_sha256=policy.sha256,
        )
        with self._lock:
            self._attached = True
            self._api_key = api_key
            process_laya().set_decision_client(client)
            set_process_runtime(self)
        return self.base_url

    def stop(self) -> None:
        """Stop the sidecar and record Down before any in-flight probe can publish.

        The API key from this boot is deleted, including when start failed
        after writing it. A health read that started earlier is ignored once
        this generation moves on.
        """
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

        with self._lock, self._file_lock():
            self._generation += 1
            engine = process_laya()
            engine.set_decision_client(None)
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            process = self._process
            pid = _read_pid_file(self._pid_path)
            self._process = None
            self._attached = False
            self._api_key = ""
            _unlink_quiet(self._key_path)
            _unlink_quiet(self._pid_path)
        if process is not None:
            _terminate(process)
        elif pid is not None:
            _signal_recorded_pid(pid)

    def publish_status(self) -> Any:
        """Read ``/health`` and record Ready, Degraded, or Down.

        A result from a generation that ``stop`` has already closed is discarded.
        """
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import publish_probe  # noqa: PLC0415

        with self._lock:
            generation = self._generation
            running = self._process is not None or self._attached
        if not running:
            return process_laya().status
        try:
            payload = self.read_health()
        except Exception:
            payload = None
        with self._lock:
            if generation != self._generation or not (self._process is not None or self._attached):
                return process_laya().status
            status = publish_probe(process_laya(), payload, requested_device=self._device)
            if status is not DecisionStatus.DOWN and isinstance(payload, Mapping):
                self._mark_weights_cached()
            return status

    def status(self) -> dict[str, Any]:
        """Report whether a sidecar process is up. Does not include the API key."""
        with self._lock:
            attached = self._attached
            in_process = self._process is not None
        pid = _read_pid_file(self._pid_path)
        running = in_process or attached or _pid_alive(pid)
        health: Mapping[str, Any] | None = None
        if running:
            try:
                health = self.read_health()
            except Exception:
                health = None
        return {
            "running": running,
            "host": LAYA_BIND_HOST,
            "port": self._port,
            "base_url": self.base_url,
            "venv": str(self.venv_dir),
            "pid": pid,
            "health": dict(health) if isinstance(health, Mapping) else None,
        }

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

    @property
    def _key_path(self) -> Path:
        return self.runtime_root / "api.key"

    @property
    def _pid_path(self) -> Path:
        return self.runtime_root / "sidecar.pid"

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


def _default_install(venv_dir: Path, commands: list[list[str]]) -> None:
    if not commands:
        raise LayaRuntimeError("Laya install command is empty")
    for command in commands:
        _reject_flinttrade_interpreter(Path(command[0]), venv_dir)
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)  # noqa: S603
    for command in commands:
        _reject_flinttrade_interpreter(Path(command[0]), venv_dir)
        subprocess.run(command, check=True)  # noqa: S603


def _reject_flinttrade_interpreter(python: Path, venv_dir: Path) -> None:
    """Refuse an install whose prefix is the FlintTrade environment.

    Compares virtual-environment directories. Resolving ``python`` itself is
    wrong on Linux: the sidecar and FlintTrade environments can share one
    base interpreter symlink.
    """
    flint = Path(sys.prefix).resolve()
    target = venv_dir.expanduser().resolve()
    command_prefix = venv_prefix(python).expanduser().resolve()
    if command_prefix == flint or target == flint:
        raise LayaRuntimeError("Laya install must not use the FlintTrade interpreter")
    if command_prefix != target:
        raise LayaRuntimeError("Laya install must target the sidecar virtual environment")


def _accelerator_torch_command(venv_dir: Path, index_url: str | None) -> list[str]:
    command = [
        str(venv_python(venv_dir)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    if index_url is not None:
        command.extend(["--index-url", index_url])
    command.append("torch")
    return command


def _record_attach_down() -> None:
    from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

    process_laya().set_decision_client(None)
    process_laya().apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)


def _clear_decision_client() -> None:
    try:
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415

        process_laya().set_decision_client(None)
    except Exception:
        return


def _unlink_quiet(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _read_pid_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.isdigit():
        return None
    pid = int(text)
    return pid if pid > 0 else None


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _signal_recorded_pid(pid: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return


def main(argv: list[str] | None = None) -> int:
    """Install, start, stop, or report the Laya sidecar.

    Uses the FlintTrade interpreter (the project environment after
    ``uv sync``). The sidecar virtual environment is
    ``<workspace>/runtime/laya/venv``.
    """
    parser = argparse.ArgumentParser(description="Install and supervise the Laya decision sidecar.")
    parser.add_argument("command", choices=("install", "start", "stop", "status"))
    parser.add_argument("--accelerator", choices=tuple(sorted(_ACCELERATORS)), default="cpu")
    args = parser.parse_args(argv)
    from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

    runtime = LayaRuntime(workspace_dir())
    if args.command == "install":
        print(runtime.install(accelerator=args.accelerator))
        return 0
    if args.command == "start":
        print(runtime.start())
        return 0
    if args.command == "stop":
        runtime.stop()
        print("stopped")
        return 0
    print(json.dumps(runtime.status(), sort_keys=True, default=str))
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
