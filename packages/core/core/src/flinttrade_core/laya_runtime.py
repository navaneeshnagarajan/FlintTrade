"""Opt-in sidecar for the Laya decision model.

The sidecar is a separate virtual environment so torch stays out of the
FlintTrade environment. The default install puts CPU torch in that
environment, from the PyTorch CPU index, before the pinned ``laya[serve]``
package. CUDA and ROCm builds stay opt-in. It binds ``127.0.0.1`` (the
upstream default binds every interface with no authentication), mints a
fresh API key on each boot, and pins the checkpoint revision, the
weight digest, and every other file that launcher reads. A verified boot
starts the sidecar on the hashed weights file, with hub lookups switched
off. After the first successful load,
later boots stay offline. CPU is the only device this runtime starts.

Run ``python -m flinttrade_core.laya_runtime install|start|stop|status``
with the FlintTrade interpreter.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .owner_file_lock import OwnerSafeFileLock
from .secure_file import harden, harden_directory

_LOG = logging.getLogger("flinttrade.laya")

# laya-serve 0.3.21 only preloads a checkpoint name. A verified boot does not
# pass a repo id or revision: the child reads LAYA_WEIGHTS_PATH and loads
# that file's directory, with hub lookups switched off.
LAYA_WEIGHTS_LOG = "laya weights path=%s sha256=%s"
LAYA_WEIGHTS_DRIFT_LOG = "laya weights path=%s changed=%s"
LAYA_WATCH_INTERVAL_SECONDS = 1.5
LAYA_PINNED_WEIGHT_BOOTSTRAP = textwrap.dedent(
    """\
    import os
    import sys

    path = os.environ.get("LAYA_WEIGHTS_PATH", "")
    if not path or not os.path.isfile(path):
        sys.stderr.write("laya weights path is not a file\\n")
        raise SystemExit(1)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ.pop("LAYA_REVISION", None)
    directory = os.path.dirname(os.path.abspath(path))
    weight = os.path.join(directory, "model.safetensors")
    if os.path.abspath(weight) != os.path.abspath(path):
        sys.stderr.write("laya weights path is not the checkpoint file\\n")
        raise SystemExit(1)
    from laya.router import Router
    from laya.serve import create_app
    import uvicorn

    router = Router(
        models={"english": directory},
        device=os.environ.get("LAYA_DEVICE") or "cpu",
        auto_task_detection=False,
        max_loaded=1,
    )
    router.preload(["english"])
    uvicorn.run(
        create_app(router),
        host=os.environ.get("LAYA_HOST", "127.0.0.1"),
        port=int(os.environ.get("LAYA_PORT", "8000")),
        log_level=os.environ.get("LAYA_LOG_LEVEL", "info"),
    )
    """
)
_WEIGHT_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth", ".gguf")

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


def sidecar_constraints_path() -> Path:
    """Constraints file that pins CPU torch and ``laya`` together.

    The install requirement still asks for the ``serve`` extra. The
    constraints line does not: pip rejects extras in a constraints file.
    """
    return Path(__file__).resolve().with_name("laya_sidecar_constraints.txt")


def constraint_lines_with_extras(text: str) -> list[str]:
    """Return constraint lines that name an extra.

    Comments and blank lines are ignored. A requirement marker such as
    ``name[extra]==1`` is an extra. Environment markers after ``;`` are not.
    """
    found: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = line.split(";", 1)[0]
        if "[" in requirement:
            found.append(line)
    return found


def assert_constraints_have_no_extras(path: Path | None = None) -> None:
    """Refuse a constraints file pip cannot apply."""
    target = path or sidecar_constraints_path()
    extras = constraint_lines_with_extras(target.read_text(encoding="utf-8"))
    if extras:
        raise LayaRuntimeError("Constraints cannot have extras")


def install_command(venv_dir: Path, *, constraints: Path | None = None) -> list[str]:
    """Pip command that pins ``laya[serve]`` inside the sidecar environment."""
    command = [
        str(venv_python(venv_dir)),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--upgrade-strategy",
        "only-if-needed",
    ]
    if constraints is not None:
        command.extend(["-c", str(constraints)])
    command.append(LAYA_SERVE_REQUIREMENT)
    return command


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
        "-c",
        str(sidecar_constraints_path()),
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
    if accelerator == "cpu":
        constraints = sidecar_constraints_path()
        assert_constraints_have_no_extras(constraints)
        return [cpu_torch_command(venv_dir), install_command(venv_dir, constraints=constraints)]
    pinned = install_command(venv_dir)
    if accelerator == "cuda":
        return [_accelerator_torch_command(venv_dir, None), pinned]
    index = os.environ.get("LAYA_TORCH_INDEX", "").strip()
    if not index.startswith("https://"):
        raise LayaRuntimeError("ROCm install needs LAYA_TORCH_INDEX set to an https PyTorch ROCm wheel index")
    return [_accelerator_torch_command(venv_dir, index), pinned]


def resolve_laya_port(port: int | None = None) -> int:
    """Return ``port``, or ``LAYA_PORT`` when ``port`` is omitted. Default 8000."""
    if port is None:
        text = os.environ.get("LAYA_PORT", "").strip()
        if not text:
            return _DEFAULT_PORT
        try:
            port = int(text)
        except ValueError as exc:
            raise LayaRuntimeError("Laya sidecar port is invalid") from exc
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise LayaRuntimeError("Laya sidecar port is invalid")
    return port


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
    runtime = process_runtime()
    if runtime is not None:
        runtime.stop_watch()
    set_process_runtime(None)
    from flinttrade_engine.laya_decision import set_decision_log_path  # noqa: PLC0415

    set_decision_log_path(None)


def refresh_process_laya_status() -> None:
    """Apply sidecar health to process Laya.

    No sidecar leaves the stored status. When ``LAYA_API_KEY_FILE`` is set,
    an already-running backend attaches to that loopback sidecar first.
    A dead child is reaped here and recorded Down.
    """
    runtime = process_runtime()
    if runtime is None:
        runtime = attach_from_environment()
    if runtime is None:
        return
    runtime.reap_children()
    runtime.publish_status()


def start_managed_sidecar() -> str:
    """Start or restart the sidecar this process supervises.

    Returns the loopback origin. An existing child is replaced. Raises
    ``LayaRuntimeError`` when the sidecar cannot be spawned.
    """
    runtime = process_runtime()
    if runtime is None:
        from flinttrade_core.workspace import workspace_dir  # noqa: PLC0415

        runtime = LayaRuntime(workspace_dir())
    return runtime.start()


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
        _record_attach_down(port)
        return None
    runtime.attach(key_path)
    return runtime


@dataclass(frozen=True, slots=True)
class PinnedFile:
    """One companion file the launcher reads, with the identity recorded at hash time."""

    name: str
    path: str
    sha256: str
    inode: int = 0
    size: int = 0
    mtime_ns: int = 0


@dataclass(frozen=True, slots=True)
class ArtifactCheck:
    """Result of hashing the pinned weight file for one sidecar run.

    ``pid`` and ``token`` bind the result to the process that was started.
    A record without them, or from an earlier run, is not accepted.
    """

    ok: bool
    reason: str | None
    revision: str
    sha256: str
    pid: int = 0
    token: str = ""
    weights_path: str = ""
    inode: int = 0
    size: int = 0
    mtime_ns: int = 0
    files: tuple[PinnedFile, ...] = ()


def huggingface_cache_roots() -> list[Path]:
    """Cache directories the sidecar and this process share.

    An explicit ``HUGGINGFACE_HUB_CACHE`` or ``HF_HOME`` replaces the
    default user cache so a test can point at an empty directory.
    """
    hub = os.environ.get("HUGGINGFACE_HUB_CACHE", "").strip()
    if hub:
        return [Path(hub).expanduser()]
    home = os.environ.get("HF_HOME", "").strip()
    if home:
        return [Path(home).expanduser() / "hub"]
    return [Path.home() / ".cache" / "huggingface" / "hub"]


def snapshot_weight_path(root: Path, *, repo: str, revision: str, filename: str) -> Path:
    """Hugging Face snapshot path for one pinned revision."""
    folder = "models--" + repo.replace("/", "--")
    return root / folder / "snapshots" / revision / filename


def _checkpoint_digests(policy: Any) -> dict[str, str]:
    """Weight digest plus the companion manifest, for the sidecar's own check."""
    mapped = {str(policy.weight_file): str(policy.sha256)}
    for name, digest in policy.manifest:
        mapped[str(name)] = str(digest)
    return mapped


def _recorded_identities(check: ArtifactCheck) -> tuple[tuple[str, int, int, int], ...]:
    """Paths whose inode, size, and mtime were stored when they were hashed."""
    rows: list[tuple[str, int, int, int]] = []
    if check.weights_path and (check.inode or check.size or check.mtime_ns):
        rows.append((check.weights_path, check.inode, check.size, check.mtime_ns))
    for item in check.files:
        if item.path and (item.inode or item.size or item.mtime_ns):
            rows.append((item.path, item.inode, item.size, item.mtime_ns))
    return tuple(rows)


def _identity_drift(path: str, inode: int, size: int, mtime_ns: int) -> str | None:
    """Return the identity fields that no longer match. Does not hash."""
    try:
        current_inode, current_size, current_mtime = _file_identity(Path(path))
    except OSError:
        return "inode,size,mtime"
    changed: list[str] = []
    if current_inode != inode:
        changed.append("inode")
    if current_size != size:
        changed.append("size")
    if current_mtime != mtime_ns:
        changed.append("mtime")
    if not changed:
        return None
    return ",".join(changed)


def _read_pinned_files(raw: object) -> tuple[PinnedFile, ...]:
    """Companion identities stored beside the weights record."""
    if not isinstance(raw, list):
        return ()
    files: list[PinnedFile] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        path = item.get("path")
        digest = item.get("sha256")
        if not isinstance(name, str) or not isinstance(path, str) or not isinstance(digest, str):
            continue
        files.append(
            PinnedFile(
                name=name,
                path=path,
                sha256=digest,
                inode=_record_int(item.get("inode")),
                size=_record_int(item.get("size")),
                mtime_ns=_record_int(item.get("mtime_ns")),
            )
        )
    return tuple(files)


def _file_identity(path: Path) -> tuple[int, int, int]:
    """Inode, size, and mtime in nanoseconds. Symlinks are followed. Does not hash."""
    stat = path.stat()
    return stat.st_ino, stat.st_size, stat.st_mtime_ns


def _record_int(value: object) -> int:
    """Non-negative integer from a runtime record, or zero when it is absent."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _has_weight_identity(check: ArtifactCheck | None) -> bool:
    """True when ``check`` remembers an inode, size, and mtime for a hashed file."""
    if check is None or not check.ok:
        return False
    if check.weights_path and (check.inode or check.size or check.mtime_ns):
        return True
    return any(item.path and (item.inode or item.size or item.mtime_ns) for item in check.files)


# Files the sidecar can read when pointed at a checkpoint directory, other than
# the pinned weights file. Sibling checkpoints, pictures, and README files are
# not in this set: the launcher does not open them.
_LOADABLE_ROOT_NAMES = frozenset(
    {
        "rl_agent_config.json",
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.json",
        "merges.txt",
        "chat_template.jinja",
        "preprocessor_config.json",
    }
)
_LOADABLE_DIRS = ("tokenizer", "encoder")


def sha256_file(path: Path) -> str:
    """Hex digest of a file. Symlinks are followed."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def snapshot_has_extra_weights(directory: Path, pinned_name: str) -> bool:
    """True when ``directory`` holds a shard index or another weights file.

    The pinned file named in ``laya_policy.toml`` is the only weight the
    snapshot may contain. A shard index, or any other ``.safetensors``,
    ``.bin``, ``.pt``, ``.pth``, or ``.gguf`` file, cannot be verified.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.is_file() or entry.name == pinned_name:
            continue
        name = entry.name
        if name.endswith(".safetensors.index.json") or name == "pytorch_model.bin.index.json":
            return True
        if name.endswith(_WEIGHT_SUFFIXES):
            return True
    return False


def huggingface_cache_root_for(weight: Path) -> Path | None:
    """Cache root that contains this Hugging Face snapshot file."""
    revision_dir = weight.parent
    snapshots = revision_dir.parent
    repo_dir = snapshots.parent
    if snapshots.name == "snapshots" and repo_dir.name.startswith("models--"):
        return repo_dir.parent
    return None


def verify_weight_file(
    path: Path,
    *,
    revision: str,
    expected_revision: str,
    expected_sha256: str,
) -> ArtifactCheck:
    """Hash ``path`` and compare it with the pin.

    A shard index or any other weights file in the same snapshot is
    unverified, before the digest is compared. A readable file whose
    digest is not the pin is a real mismatch.
    """
    resolved = str(path.resolve()) if path.exists() else str(path)
    if snapshot_has_extra_weights(path.parent, path.name):
        return ArtifactCheck(
            ok=False,
            reason="unverified",
            revision=revision,
            sha256="",
            weights_path=resolved,
        )
    if revision != expected_revision:
        return ArtifactCheck(
            ok=False,
            reason="wrong_revision",
            revision=revision,
            sha256="",
            weights_path=resolved,
        )
    try:
        actual = sha256_file(path)
    except OSError:
        return ArtifactCheck(
            ok=False,
            reason="unverified",
            revision=revision,
            sha256="",
            weights_path=resolved,
        )
    if actual != expected_sha256:
        return ArtifactCheck(
            ok=False,
            reason="wrong_revision",
            revision=revision,
            sha256=actual,
            weights_path=resolved,
        )
    try:
        inode, size, mtime_ns = _file_identity(path)
    except OSError:
        return ArtifactCheck(
            ok=False,
            reason="unverified",
            revision=revision,
            sha256=actual,
            weights_path=resolved,
        )
    return ArtifactCheck(
        ok=True,
        reason=None,
        revision=revision,
        sha256=actual,
        weights_path=resolved,
        inode=inode,
        size=size,
        mtime_ns=mtime_ns,
    )


def snapshot_weight_file(
    *,
    repo: str,
    revision: str,
    filename: str,
    cache_roots: list[Path] | None = None,
) -> Path | None:
    """Return the pinned filename when it is already on disk.

    This still returns the file when the snapshot also holds other weights.
    :func:`find_pinned_weight` is the check that refuses that snapshot.
    """
    roots = huggingface_cache_roots() if cache_roots is None else cache_roots
    for root in roots:
        candidate = snapshot_weight_path(root, repo=repo, revision=revision, filename=filename)
        if candidate.is_file():
            return candidate
    return None


def find_pinned_weight(
    *,
    repo: str,
    revision: str,
    filename: str,
    cache_roots: list[Path] | None = None,
) -> Path | None:
    """Return the pinned snapshot file only when it is the only weight there.

    A shard index or any other weights file means the snapshot cannot be
    verified, so this returns ``None`` rather than the extra file.
    """
    candidate = snapshot_weight_file(repo=repo, revision=revision, filename=filename, cache_roots=cache_roots)
    if candidate is None:
        return None
    if snapshot_has_extra_weights(candidate.parent, filename):
        return None
    return candidate


def extra_loadable_file(directory: Path, allowed: set[str]) -> str | None:
    """Return a relative path the launcher could read that is not in ``allowed``.

    ``allowed`` is the weights file plus the manifest. A file under
    ``tokenizer/`` or ``encoder/``, or a root file the loader opens, is
    loadable. Anything else in the snapshot is left alone.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    for entry in entries:
        if entry.name in _LOADABLE_DIRS and entry.is_dir():
            for child in entry.rglob("*"):
                if not child.is_file():
                    continue
                relative = child.relative_to(directory).as_posix()
                if relative not in allowed:
                    return relative
            continue
        if entry.is_file() and entry.name in _LOADABLE_ROOT_NAMES and entry.name not in allowed:
            return entry.name
    return None


def verify_installed_model(
    *,
    repo: str,
    revision: str,
    filename: str,
    expected_sha256: str,
    manifest: tuple[tuple[str, str], ...] = (),
    cache_roots: list[Path] | None = None,
) -> ArtifactCheck:
    """Verify the pinned revision, the weight file, and the companion manifest.

    A missing weight file is unverified and may still be downloaded on first
    boot. A snapshot that also holds a shard index, another weights file, or
    any other file the launcher could read is unverified and must not be
    launched. A file whose digest is not the pin is a real mismatch.
    """
    path = snapshot_weight_file(repo=repo, revision=revision, filename=filename, cache_roots=cache_roots)
    if path is None:
        return ArtifactCheck(ok=False, reason="unverified", revision=revision, sha256="")
    directory = path.parent
    allowed = {filename, *(name for name, _digest in manifest)}
    if snapshot_has_extra_weights(directory, filename):
        return ArtifactCheck(
            ok=False,
            reason="unverified",
            revision=revision,
            sha256="",
            weights_path=str(path),
        )
    extra = extra_loadable_file(directory, allowed)
    if extra is not None:
        return ArtifactCheck(
            ok=False,
            reason="unverified",
            revision=revision,
            sha256="",
            weights_path=str(directory / extra),
        )
    check = verify_weight_file(
        path,
        revision=revision,
        expected_revision=revision,
        expected_sha256=expected_sha256,
    )
    if not check.ok or not manifest:
        return check
    files: list[PinnedFile] = []
    for name, digest in manifest:
        companion = directory / name
        if not companion.is_file():
            return ArtifactCheck(
                ok=False,
                reason="unverified",
                revision=revision,
                sha256="",
                weights_path=str(companion),
            )
        try:
            actual = sha256_file(companion)
            inode, size, mtime_ns = _file_identity(companion)
        except OSError:
            return ArtifactCheck(
                ok=False,
                reason="unverified",
                revision=revision,
                sha256="",
                weights_path=str(companion),
            )
        if actual != digest:
            return ArtifactCheck(
                ok=False,
                reason="wrong_revision",
                revision=revision,
                sha256=actual,
                weights_path=str(companion),
            )
        files.append(
            PinnedFile(
                name=name,
                path=str(companion),
                sha256=actual,
                inode=inode,
                size=size,
                mtime_ns=mtime_ns,
            )
        )
    return replace(check, files=tuple(files))


class LayaRuntime:
    """Install and supervise one loopback ``laya-serve`` process."""

    def __init__(
        self,
        workspace_dir: Path,
        *,
        host: str = LAYA_BIND_HOST,
        port: int | None = None,
        device: str = "cpu",
        process_factory: Callable[[list[str], dict[str, str]], Any] | None = None,
        installer: Callable[[Path, list[str]], None] | None = None,
        health_reader: Callable[[str], Mapping[str, Any] | None] | None = None,
        port_probe: Callable[[int], bool] | None = None,
        artifact_checker: Callable[[], ArtifactCheck] | None = None,
        watch: bool = True,
        watch_interval: float | None = None,
    ) -> None:
        if host != LAYA_BIND_HOST:
            raise LayaRuntimeError("Laya sidecar must bind 127.0.0.1")
        if device != "cpu":
            raise LayaRuntimeError("Laya runs on CPU until an accelerator runtime is qualified")
        self.workspace_dir = workspace_dir.expanduser().resolve()
        self.runtime_root = self.workspace_dir / "runtime" / "laya"
        self.venv_dir = self.runtime_root / "venv"
        self._port = resolve_laya_port(port)
        self._device = device
        self._process_factory = process_factory or self._spawn
        self._installer = installer
        self._health_reader = health_reader
        self._port_probe = port_probe
        self._artifact_checker = artifact_checker
        self._process: Any | None = None
        self._attached = False
        self._api_key = ""
        self._watched_key: Path | None = None
        self._key_rejected = False
        self._artifact_check: ArtifactCheck | None = None
        self._launch_refusal: ArtifactCheck | None = None
        self._weight_drift: tuple[str, str] | None = None
        self._start_token = ""
        self._watch = watch
        self._watch_interval = LAYA_WATCH_INTERVAL_SECONDS if watch_interval is None else watch_interval
        self._watch_stop: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None
        self._watch_signature: tuple[object, ...] | None = None
        self._watch_had_pid = False
        self._generation = 0
        self._loaded_once = False
        self._child_stopped = False
        self._last_health: Mapping[str, Any] | None = None
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
        from flinttrade_engine.laya_decision import load_policy  # noqa: PLC0415

        policy = load_policy()
        self._ensure_dirs()
        self.stop_watch()
        spawned: Any | None = None
        with self._lock, self._file_lock():
            self._loaded_once = False
            self._child_stopped = False
            _reap_runtimes.add(self)
            if self._process is not None:
                _terminate(self._process)
                self._process = None
            self._attached = False
            _unlink_quiet(self._key_path)
            _unlink_quiet(self._pid_path)
            self._clear_run_record()
            self._launch_refusal = None
            self._weight_drift = None
            weighed = self._weigh_before_launch(policy)
            if self._weights_block_launch(weighed):
                _reap_runtimes.discard(self)
                self._record_launch_refusal(weighed)
                raise LayaRuntimeError(_launch_refusal_message(weighed))
            if weighed.ok and weighed.weights_path:
                _LOG.info(LAYA_WEIGHTS_LOG, weighed.weights_path, weighed.sha256)
            api_key = secrets.token_urlsafe(32)
            token = secrets.token_urlsafe(32)
            try:
                _write_private(self._key_path, api_key)
                offline = weighed.ok or self._weights_cached()
                pinned = weighed.ok and bool(weighed.weights_path)
                threads = _thread_budget()
                env = os.environ.copy()
                env.update(
                    {
                        "LAYA_HOST": LAYA_BIND_HOST,
                        "LAYA_PORT": str(self._port),
                        "LAYA_DEVICE": "cpu",
                        "LAYA_PRELOAD": "1",
                        "LAYA_MAX_LOADED": "1",
                        "LAYA_API_KEY": api_key,
                        "LAYA_SHA256_DIGESTS": json.dumps(_checkpoint_digests(policy)),
                        "LAYA_THREADS": str(threads),
                        "HF_HUB_OFFLINE": "1" if offline else "0",
                    }
                )
                if pinned:
                    env["LAYA_WEIGHTS_PATH"] = weighed.weights_path
                    env["HF_HUB_OFFLINE"] = "1"
                    env["TRANSFORMERS_OFFLINE"] = "1"
                    for name in (
                        "LAYA_REVISION",
                        "LAYA_MODELS",
                        "HUGGINGFACE_HUB_CACHE",
                        "HF_HUB_CACHE",
                        "HF_HOME",
                        "HF_TOKEN",
                    ):
                        env.pop(name, None)
                    argv = [str(venv_python(self.venv_dir)), "-c", LAYA_PINNED_WEIGHT_BOOTSTRAP]
                else:
                    env["LAYA_MODELS"] = policy.checkpoint
                    env["LAYA_REVISION"] = policy.revision
                    if offline:
                        env["TRANSFORMERS_OFFLINE"] = "1"
                    else:
                        env.pop("TRANSFORMERS_OFFLINE", None)
                    argv = [str(serve_executable(self.venv_dir))]
                spawned = self._process_factory(argv, env)
                self._process = spawned
                pid = getattr(spawned, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    _write_private(self._pid_path, str(pid))
                    self._watch_had_pid = True
                self._api_key = api_key
                self._watched_key = self._key_path
                self._key_rejected = False
                self._start_token = token
                client = self._decision_client(api_key, policy)
                if weighed.ok:
                    self._stamp_weighed(weighed, token)
                else:
                    self._remember_artifact(self.ensure_artifact_check(force=True))
                self._note_client_verification(client)
                process_laya().set_decision_client(client)
                set_process_runtime(self)
                self._bind_decision_log()
                self.start_watch()
            except Exception:
                self._process = None
                self._api_key = ""
                self._attached = False
                self.stop_watch()
                _reap_runtimes.discard(self)
                _unlink_quiet(self._key_path)
                _unlink_quiet(self._pid_path)
                self._clear_run_record()
                _clear_decision_client()
                if spawned is not None:
                    _terminate(spawned)
                raise
        return self.base_url

    def attach(self, key_path: Path) -> str:
        """Use an existing loopback sidecar. Does not spawn a process.

        The client is pinned to the policy revision and weight digest. A health
        document that omits the digest is Ready only after the weight file on
        disk matches the pin. A real mismatch stays Down.
        """
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415
        from flinttrade_engine.laya_decision import load_policy  # noqa: PLC0415

        try:
            api_key = key_path.expanduser().read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LayaRuntimeError("Laya API key file cannot be read") from exc
        if not api_key:
            _record_attach_down(self._port)
            raise LayaRuntimeError("Laya API key file is empty")
        policy = load_policy()
        self._watched_key = key_path.expanduser()
        self._key_rejected = False
        self._start_token = ""
        client = self._decision_client(api_key, policy)
        self._remember_artifact(self.ensure_artifact_check())
        self._note_client_verification(client)
        with self._lock:
            self._attached = True
            self._api_key = api_key
            process_laya().set_decision_client(client)
            set_process_runtime(self)
            self._bind_decision_log()
            self._watch_had_pid = self._pid_path.is_file()
            self.start_watch()
        return self.base_url

    def stop(self) -> None:
        """Stop the sidecar and record Down before any in-flight probe can publish.

        The API key from this boot is deleted, including when start failed
        after writing it. A health read that started earlier is ignored once
        this generation moves on.
        """
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

        self.stop_watch()
        with self._lock, self._file_lock():
            self._generation += 1
            self._launch_refusal = None
            self._weight_drift = None
            self._watch_had_pid = False
            engine = process_laya()
            engine.set_decision_client(None)
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            engine.set_runtime_reason("not_started", self._port)
            self._loaded_once = False
            self._child_stopped = False
            self._key_rejected = False
            process = self._process
            pid = _read_pid_file(self._pid_path)
            self._process = None
            self._attached = False
            self._api_key = ""
            _unlink_quiet(self._key_path)
            _unlink_quiet(self._pid_path)
            self._clear_run_record()
            _reap_runtimes.discard(self)
        if process is not None:
            _terminate(process)
        elif pid is not None:
            _signal_recorded_pid(pid)
            _reap_recorded_pid(pid)

    def publish_status(self) -> Any:
        """Read ``/health`` and record Ready, Degraded, or Down.

        A result from a generation that ``stop`` has already closed is discarded.
        The first load stays Down for admission and records ``still_loading``.
        A port held by something else records ``port_in_use``.
        """
        from flinttrade_engine.laya import (  # noqa: PLC0415
            LAYA_REASON_KEY_REJECTED,
            LAYA_REASON_UNVERIFIED,
            DecisionStatus,
            process_laya,
        )
        from flinttrade_engine.laya_decision import health_identity_failure, publish_probe  # noqa: PLC0415

        self._sync_watched_key()
        if self._launch_refusal is not None:
            engine = process_laya()
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            engine.set_runtime_reason(self._launch_refusal.reason or LAYA_REASON_UNVERIFIED, self._port)
            return engine.status
        if self._key_rejected:
            engine = process_laya()
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            engine.set_runtime_reason(LAYA_REASON_KEY_REJECTED, self._port)
            return engine.status
        artifact = self.ensure_artifact_check()
        drift = self._weight_drift_now()
        if drift is not None:
            self._refuse_weight_drift(*drift)
            return process_laya().status
        self._weight_drift = None
        verified = (artifact.revision, artifact.sha256) if artifact.ok else None
        self._note_client_verification(process_laya()._decision_client)  # noqa: SLF001
        with self._lock:
            generation = self._generation
            managed = self._managed_locked()
        port_open = True if managed else self._port_is_open()
        payload = self._safe_health() if managed or port_open else None
        self._last_health = payload if isinstance(payload, Mapping) else None
        with self._lock:
            if generation != self._generation:
                return process_laya().status
            managed_now = self._managed_locked()
            if managed and not managed_now:
                return process_laya().status
            reason = self._reason_code(
                payload,
                managed=managed_now,
                port_open=port_open or managed_now,
                identity_failure=health_identity_failure,
                verified=verified,
                artifact_reason=None if artifact.ok else artifact.reason,
            )
            engine = process_laya()
            if reason is None:
                status = publish_probe(
                    engine,
                    payload,
                    requested_device=self._device,
                    verified=verified,
                )
                if status is not DecisionStatus.DOWN:
                    self._loaded_once = True
                    engine.set_runtime_reason(None, self._port)
                    if isinstance(payload, Mapping):
                        self._mark_weights_cached()
                return status
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            engine.set_runtime_reason(reason, self._port)
            return engine.status

    def status(self) -> dict[str, Any]:
        """Report the sidecar. Does not include the API key.

        ``reason`` is a machine-readable code. ``detail`` is the plain words
        the desk shows. A clash or a non-Laya listener is Down with
        ``port_in_use``.
        """
        from flinttrade_engine.laya import laya_reason_detail, laya_reason_tooltip, process_laya  # noqa: PLC0415

        self.publish_status()
        with self._lock:
            attached = self._attached
            process = self._process
            in_process = process is not None and _process_alive(process)
        pid = _read_pid_file(self._pid_path)
        running = in_process or attached or _pid_alive(pid)
        reason, port = process_laya().runtime_reason()
        health = self._last_health
        return {
            "running": running,
            "host": LAYA_BIND_HOST,
            "port": self._port,
            "base_url": self.base_url,
            "venv": str(self.venv_dir),
            "pid": pid,
            "health": dict(health) if isinstance(health, Mapping) else None,
            "reason": reason,
            "detail": laya_reason_detail(reason, port),
            "tooltip": laya_reason_tooltip(reason, port),
        }

    def reap_children(self) -> None:
        """Collect a dead child so it does not stay defunct.

        A live sidecar is left running. ``stop`` is what terminates it.
        """
        with self._lock:
            self._reap_locked()

    def _reap_locked(self) -> None:
        """Reap a zombie. Caller holds ``_lock``. A live child is not signalled."""
        process = self._process
        if process is not None:
            if not _process_alive(process):
                self._child_stopped = True
            return
        pid = _read_pid_file(self._pid_path)
        if pid is not None and _reap_recorded_pid(pid):
            self._child_stopped = True

    def _managed_locked(self) -> bool:
        """True when this runtime owns the sidecar. Caller holds ``_lock``."""
        self._reap_locked()
        if self._attached:
            return True
        if self._process is not None and _process_alive(self._process):
            return True
        return _pid_alive(_read_pid_file(self._pid_path))

    def _port_is_open(self) -> bool:
        if self._port_probe is not None:
            return self._port_probe(self._port)
        return _tcp_open(self._port)

    def _safe_health(self) -> Mapping[str, Any] | None:
        try:
            payload = self.read_health()
        except Exception:
            return None
        return payload if isinstance(payload, Mapping) else None

    def _reason_code(
        self,
        payload: Mapping[str, Any] | None,
        *,
        managed: bool,
        port_open: bool,
        identity_failure: Callable[..., bool],
        verified: tuple[str, str] | None,
        artifact_reason: str | None,
    ) -> str | None:
        """Return a Down reason, or ``None`` when a managed sidecar is up."""
        from flinttrade_engine.laya import (  # noqa: PLC0415
            LAYA_REASON_NOT_STARTED,
            LAYA_REASON_PORT_IN_USE,
            LAYA_REASON_STILL_LOADING,
            LAYA_REASON_STOPPED,
            LAYA_REASON_UNREACHABLE,
            LAYA_REASON_UNVERIFIED,
            LAYA_REASON_WRONG_REVISION,
            DecisionStatus,
        )
        from flinttrade_engine.laya_decision import (  # noqa: PLC0415
            health_needs_recorded_verification,
            interpret_health,
        )

        if artifact_reason == LAYA_REASON_WRONG_REVISION:
            return LAYA_REASON_WRONG_REVISION
        if self._launch_refusal is not None and self._launch_refusal.reason == LAYA_REASON_UNVERIFIED:
            return LAYA_REASON_UNVERIFIED
        if identity_failure(payload, requested_device=self._device):
            return LAYA_REASON_WRONG_REVISION
        if not managed:
            if port_open:
                return LAYA_REASON_PORT_IN_USE
            if self._child_stopped:
                return LAYA_REASON_STOPPED
            return LAYA_REASON_NOT_STARTED
        status = interpret_health(payload, requested_device=self._device, verified=verified)
        if status is not DecisionStatus.DOWN:
            return None
        if verified is None and health_needs_recorded_verification(payload):
            return LAYA_REASON_UNVERIFIED
        if self._loaded_once:
            return LAYA_REASON_UNREACHABLE
        return LAYA_REASON_STILL_LOADING

    def ensure_artifact_check(self, *, force: bool = False) -> ArtifactCheck:
        """Return this run's weight check.

        ``force`` hashes the files again and stamps the result with this
        start's pid and token. A probe does not hash. It accepts a record
        only when that token matches the running sidecar. Anything else,
        including a leftover from an earlier run, is unverified.
        """
        from flinttrade_engine.laya_decision import load_policy  # noqa: PLC0415

        policy = load_policy()
        if force:
            token = self._start_token or secrets.token_urlsafe(32)
            self._start_token = token
            check = self._recompute_artifact(policy, token)
            self._write_run_record(token, check.pid)
            self._write_recorded_verification(check)
            self._remember_artifact(check)
            return check
        cached = self._artifact_check
        if cached is not None and self._record_belongs_to_running_sidecar(cached, policy):
            return cached
        recorded = self._read_recorded_verification()
        if recorded is not None and self._record_belongs_to_running_sidecar(recorded, policy):
            self._remember_artifact(recorded)
            return recorded
        return ArtifactCheck(ok=False, reason="unverified", revision=policy.revision, sha256="")

    def _recompute_artifact(self, policy: Any, token: str) -> ArtifactCheck:
        """Hash the pinned weight file and stamp it for this start."""
        if self._artifact_checker is not None:
            raw = self._artifact_checker()
        else:
            raw = verify_installed_model(
                repo=policy.repo,
                revision=policy.revision,
                filename=policy.weight_file,
                expected_sha256=policy.sha256,
                manifest=tuple(policy.manifest),
            )
        return ArtifactCheck(
            ok=raw.ok,
            reason=raw.reason,
            revision=raw.revision,
            sha256=raw.sha256,
            pid=self._sidecar_pid(),
            token=token,
            weights_path=raw.weights_path,
            inode=raw.inode,
            size=raw.size,
            mtime_ns=raw.mtime_ns,
            files=raw.files,
        )

    def _sidecar_pid(self) -> int:
        """Pid of the process this runtime started, or the pid file."""
        process = self._process
        if process is not None:
            pid = getattr(process, "pid", None)
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
                return pid
        recorded = _read_pid_file(self._pid_path)
        return recorded if recorded is not None else 0

    def _record_belongs_to_running_sidecar(self, check: ArtifactCheck, policy: Any) -> bool:
        """True when ``check`` was stamped for the sidecar that is alive now."""
        if not check.token or check.pid <= 0 or not _pid_alive(check.pid):
            return False
        if self._sidecar_pid() != check.pid:
            return False
        if check.ok:
            if check.revision != policy.revision or check.sha256 != policy.sha256:
                return False
        elif check.reason != "wrong_revision":
            return False
        run = self._read_run_record()
        if run != (check.token, check.pid):
            return False
        if self._start_token and self._start_token != check.token:
            return False
        return True

    def _remember_artifact(self, check: ArtifactCheck) -> None:
        self._artifact_check = check

    def _note_client_verification(self, client: Any) -> None:
        from flinttrade_engine.laya_decision import load_policy  # noqa: PLC0415

        note = getattr(client, "note_verification", None)
        clear = getattr(client, "clear_verification", None)
        check = self._artifact_check
        if client is None:
            return
        if (
            check is not None
            and check.ok
            and self._record_belongs_to_running_sidecar(check, load_policy())
            and callable(note)
        ):
            note(check.revision, check.sha256, token=check.token)
            return
        if callable(clear):
            clear()

    def _decision_client(self, api_key: str, policy: Any) -> Any:
        from flinttrade_engine.laya_decision import SystemOneClient  # noqa: PLC0415

        return SystemOneClient(
            self.base_url,
            api_key=api_key,
            expected_revision=policy.revision,
            expected_sha256=policy.sha256,
            key_loader=self._load_watched_key,
            on_key_refreshed=self._remember_key,
            on_key_rejected=self._mark_key_rejected,
        )

    def _load_watched_key(self) -> str:
        path = self._watched_key
        if path is None:
            return self._api_key
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return self._api_key

    def _remember_key(self, key: str) -> None:
        self._api_key = key
        self._key_rejected = False

    def _weigh_before_launch(self, policy: Any) -> ArtifactCheck:
        """Hash the pinned file before the sidecar process exists."""
        if self._artifact_checker is not None:
            return self._artifact_checker()
        return verify_installed_model(
            repo=policy.repo,
            revision=policy.revision,
            filename=policy.weight_file,
            expected_sha256=policy.sha256,
            manifest=tuple(policy.manifest),
        )

    @staticmethod
    def _weights_block_launch(check: ArtifactCheck) -> bool:
        """A mismatch, or a snapshot that is not the single pinned file, does not launch."""
        if check.reason == "wrong_revision":
            return True
        return check.reason == "unverified" and bool(check.weights_path)

    def _record_launch_refusal(self, check: ArtifactCheck) -> None:
        """Keep the chip on the pre-launch result. No sidecar is running."""
        from flinttrade_engine.laya import DecisionStatus, process_laya  # noqa: PLC0415

        self._launch_refusal = check
        self._remember_artifact(check)
        engine = process_laya()
        engine.set_decision_client(None)
        engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        engine.set_runtime_reason(check.reason or "unverified", self._port)

    def _stamp_weighed(self, weighed: ArtifactCheck, token: str) -> ArtifactCheck:
        """Bind a hash taken before launch to the process that just started."""
        check = ArtifactCheck(
            ok=weighed.ok,
            reason=weighed.reason,
            revision=weighed.revision,
            sha256=weighed.sha256,
            pid=self._sidecar_pid(),
            token=token,
            weights_path=weighed.weights_path,
            inode=weighed.inode,
            size=weighed.size,
            mtime_ns=weighed.mtime_ns,
            files=weighed.files,
        )
        self._write_run_record(token, check.pid)
        self._write_recorded_verification(check)
        self._remember_artifact(check)
        return check

    def _bind_decision_log(self) -> None:
        from flinttrade_engine.laya_decision import set_decision_log_path  # noqa: PLC0415

        self._ensure_dirs()
        set_decision_log_path(self.runtime_root / "decisions.jsonl")

    def start_watch(self) -> None:
        """Notice a CLI stop, start, or key change without waiting for the health poll."""
        if not self._watch or self._watch_interval <= 0:
            return
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_signature = self._watched_signature()
        self._watch_stop = threading.Event()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            name="laya-runtime-watch",
            daemon=True,
        )
        self._watch_thread.start()

    def stop_watch(self) -> None:
        """Stop the file watch. Safe to call when it is not running."""
        event = self._watch_stop
        thread = self._watch_thread
        self._watch_stop = None
        self._watch_thread = None
        if event is not None:
            event.set()
        if thread is None or thread is threading.current_thread():
            return
        if self._lock._is_owned():
            return
        thread.join(timeout=2)

    def reconcile_watched_state(self) -> None:
        """Apply a pid, key, or runtime-record change to the chip immediately."""
        from flinttrade_engine.laya import LAYA_REASON_STOPPED, DecisionStatus, process_laya  # noqa: PLC0415

        signature = self._watched_signature()
        changed = signature != self._watch_signature
        self._watch_signature = signature
        pid_present = self._pid_path.is_file()
        pid = _read_pid_file(self._pid_path)
        with self._lock:
            process = self._process
        process_alive = process is not None and _process_alive(process)
        pid_alive = _pid_alive(pid)
        running = process_alive or pid_alive
        stopped = self._watch_had_pid and not process_alive and (not pid_present or not pid_alive)
        if stopped:
            self._watch_had_pid = False
            with self._lock:
                self._child_stopped = True
                self._process = None
            engine = process_laya()
            engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
            engine.set_runtime_reason(LAYA_REASON_STOPPED, self._port)
            self._artifact_check = None
            return
        key_path = self._watched_key
        if key_path is not None and self._api_key and not key_path.is_file() and running:
            self._mark_key_rejected()
            return
        drift = self._weight_drift_now()
        if drift is not None:
            if changed:
                self._sync_watched_key()
            self._refuse_weight_drift(*drift)
            self._watch_had_pid = pid_present
            return
        if self._weight_drift is not None:
            self._weight_drift = None
            if changed:
                self._artifact_check = None
                self._sync_watched_key()
            self.publish_status()
            self._watch_had_pid = pid_present
            return
        if not changed and running:
            return
        if changed:
            self._artifact_check = None
            self._sync_watched_key()
            self.publish_status()
        self._watch_had_pid = pid_present

    def _watch_loop(self) -> None:
        event = self._watch_stop
        while event is not None and not event.wait(self._watch_interval):
            if process_runtime() is not self and not self._attached and self._process is None:
                return
            try:
                self.reconcile_watched_state()
            except Exception:
                _LOG.exception("laya runtime watch failed")

    def _watched_signature(self) -> tuple[object, ...]:
        """Contents that a CLI stop, start, or key rotation changes."""
        return (
            _file_signature(self._pid_path),
            _file_signature(self._key_path if self._watched_key is None else self._watched_key),
            _file_signature(self._verification_path()),
            _file_signature(self._run_path()),
        )

    def _mark_key_rejected(self) -> None:
        from flinttrade_engine.laya import LAYA_REASON_KEY_REJECTED, DecisionStatus, process_laya  # noqa: PLC0415

        self._key_rejected = True
        engine = process_laya()
        engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        engine.set_runtime_reason(LAYA_REASON_KEY_REJECTED, self._port)

    def _sync_watched_key(self) -> bool:
        """Re-read the key file when its contents change. True when they did."""
        path = self._watched_key
        if path is None:
            return False
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if not text or text == self._api_key:
            return False
        self._api_key = text
        self._key_rejected = False
        from flinttrade_engine.laya import process_laya  # noqa: PLC0415

        client = process_laya()._decision_client  # noqa: SLF001
        replace = getattr(client, "replace_api_key", None)
        if callable(replace):
            replace(text)
        return True

    def _verification_path(self) -> Path:
        return self.runtime_root / "verification.json"

    def _run_path(self) -> Path:
        return self.runtime_root / "run.json"

    def _clear_run_record(self) -> None:
        """Drop the verification that belonged to a sidecar run."""
        _unlink_quiet(self._verification_path())
        _unlink_quiet(self._run_path())
        self._artifact_check = None
        self._start_token = ""

    def _read_run_record(self) -> tuple[str, int] | None:
        try:
            payload = json.loads(self._run_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        token = payload.get("token")
        pid = payload.get("pid")
        if not isinstance(token, str) or not token:
            return None
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        return token, pid

    def _write_run_record(self, token: str, pid: int) -> None:
        self._ensure_dirs()
        _write_json(self._run_path(), {"token": token, "pid": pid})

    def _read_recorded_verification(self) -> ArtifactCheck | None:
        try:
            payload = json.loads(self._verification_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        pid = payload.get("pid")
        token = payload.get("token")
        revision = payload.get("revision")
        digest = payload.get("sha256")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return None
        if not isinstance(token, str) or not token:
            return None
        if not isinstance(revision, str) or not isinstance(digest, str):
            return None
        weights_path = payload.get("weights_path")
        if not isinstance(weights_path, str):
            weights_path = ""
        inode = _record_int(payload.get("inode"))
        size = _record_int(payload.get("size"))
        mtime_ns = _record_int(payload.get("mtime_ns"))
        files = _read_pinned_files(payload.get("files"))
        if payload.get("ok") is True:
            return ArtifactCheck(
                ok=True,
                reason=None,
                revision=revision,
                sha256=digest,
                pid=pid,
                token=token,
                weights_path=weights_path,
                inode=inode,
                size=size,
                mtime_ns=mtime_ns,
                files=files,
            )
        if payload.get("reason") == "wrong_revision":
            return ArtifactCheck(
                ok=False,
                reason="wrong_revision",
                revision=revision,
                sha256=digest,
                pid=pid,
                token=token,
                weights_path=weights_path,
                inode=inode,
                size=size,
                mtime_ns=mtime_ns,
                files=files,
            )
        return None

    def _write_recorded_verification(self, check: ArtifactCheck) -> None:
        self._ensure_dirs()
        _write_json(
            self._verification_path(),
            {
                "ok": check.ok,
                "reason": check.reason,
                "revision": check.revision,
                "sha256": check.sha256,
                "pid": check.pid,
                "token": check.token,
                "weights_path": check.weights_path,
                "inode": check.inode,
                "size": check.size,
                "mtime_ns": check.mtime_ns,
                "files": [
                    {
                        "name": item.name,
                        "path": item.path,
                        "sha256": item.sha256,
                        "inode": item.inode,
                        "size": item.size,
                        "mtime_ns": item.mtime_ns,
                    }
                    for item in check.files
                ],
            },
        )

    def _weight_drift_now(self) -> tuple[str, str] | None:
        """Return a hashed path and which identity field changed.

        Compares inode, size, and mtime in nanoseconds for the weights file
        and every companion the launcher reads. Does not hash.
        """
        check = self._identity_record()
        if check is None:
            return None
        for path, inode, size, mtime_ns in _recorded_identities(check):
            drifted = _identity_drift(path, inode, size, mtime_ns)
            if drifted is not None:
                return path, drifted
        return None

    def _identity_record(self) -> ArtifactCheck | None:
        """The hashed file's inode, size, and mtime, from memory or the record."""
        check = self._artifact_check
        if not _has_weight_identity(check):
            check = self._read_recorded_verification()
        if not _has_weight_identity(check):
            return None
        return check

    def _refuse_weight_drift(self, path: str, changed: str) -> None:
        """Mark the sidecar unverified. New orders stay paused."""
        from flinttrade_engine.laya import LAYA_REASON_UNVERIFIED, DecisionStatus, process_laya  # noqa: PLC0415

        marker = (path, changed)
        if marker != self._weight_drift:
            _LOG.info(LAYA_WEIGHTS_DRIFT_LOG, path, changed)
            self._weight_drift = marker
        engine = process_laya()
        engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
        engine.set_runtime_reason(LAYA_REASON_UNVERIFIED, self._port)

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


def _record_attach_down(port: int = _DEFAULT_PORT) -> None:
    from flinttrade_engine.laya import LAYA_REASON_NOT_STARTED, DecisionStatus, process_laya  # noqa: PLC0415

    engine = process_laya()
    engine.set_decision_client(None)
    engine.apply_runtime_status(DecisionStatus.DOWN, live_qualified=False)
    engine.set_runtime_reason(LAYA_REASON_NOT_STARTED, port)


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


_reap_runtimes: set[LayaRuntime] = set()


def reap_managed_children() -> None:
    """Collect dead sidecar children. Does not stop a process that is still running."""
    for runtime in list(_reap_runtimes):
        try:
            runtime.reap_children()
        except Exception:
            continue


atexit.register(reap_managed_children)


def _process_alive(process: Any) -> bool:
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return False
    return poll() is None


def _tcp_open(port: int) -> bool:
    """True when something accepts TCP on the loopback sidecar port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex((LAYA_BIND_HOST, port)) == 0
    except OSError:
        return False


def _reap_recorded_pid(pid: int) -> bool:
    """Reap ``pid`` when it is our zombie. True only when it was collected.

    ``os.kill(pid, 0)`` still succeeds for a defunct child, so a probe that
    only checks that signal treats a dead sidecar as alive and never waits.
    """
    if os.name != "posix":
        return False
    try:
        waited, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return False
    except OSError:
        return False
    return waited == pid


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


def _launch_refusal_message(check: ArtifactCheck) -> str:
    """Chip words for a sidecar that was not started."""
    if check.reason == "wrong_revision":
        return "Wrong model version"
    return "Can't verify the model"


def _file_signature(path: Path) -> tuple[object, ...]:
    """File contents, or a missing marker. Used to notice CLI stop and key rotation."""
    try:
        return ("present", path.read_bytes())
    except OSError:
        return ("missing",)


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
