"""Repair the two source-pinned broker SDKs before runtime attestation.

Standalone/stdlib-only: Docker and pip-only setup run this before workspace
packages are importable. The compatibility Kotak entry point stays available.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parents[1]
BUILD_REQUIREMENTS_LOCK = REPO / "broker-sdk-build.lock"
KOTAK_REPO = "https://github.com/Kotak-Neo/kotak-neo-python.git"
_KOTAK_HOMEPAGE = KOTAK_REPO.removesuffix(".git")
_FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_IDENTITIES = {
    "kotakneoapi": ("neo_api_client", KOTAK_REPO),
    "upstox-python-sdk": ("upstox_client", "https://github.com/upstox/upstox-python.git"),
}
# Run inside the target interpreter. Never import an unverified SDK to decide
# whether its bytes are healthy. RECORD supplies ownership, not file authority.
_PROBE = r"""
import contextlib
import hashlib
import importlib
import importlib.metadata as md
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys

pins = json.load(sys.stdin)
identities = {"kotakneoapi": "neo_api_client", "upstox-python-sdk": "upstox_client"}
result = {"owners": {module: [] for module in identities.values()}}
dists = list(md.distributions())
for dist in dists:
    name = re.sub(r"[-_.]+", "-", str(dist.metadata.get("Name", "")).lower())
    paths = [str(file).replace("\\", "/") for file in (dist.files or ())]
    for module in identities.values():
        if module in (dist.read_text("top_level.txt") or "").splitlines() or any(p.split("/")[0] == module for p in paths):
            result["owners"][module].append(name)
    if name not in {*identities, "neo-api-client"}:
        continue
    if name in result:
        result[name]["duplicate"] = True
        continue
    try:
        direct = json.loads(dist.read_text("direct_url.json") or "null")
    except ValueError:
        direct = None
    root = Path(str(dist.locate_file(""))).resolve()
    safe_remove = bool(paths) and all(not Path(p).is_absolute() and ".." not in Path(p).parts
                                    and (root/p).resolve().is_relative_to(root) for p in paths)
    row = {"version": dist.version, "direct_url": direct, "safe_remove": safe_remove,
           "physical_ok": False, "import_ok": False, "root": str(root)}
    result[name] = row
    pin = pins.get(name)
    if not pin:
        continue
    module = identities[name]
    package = root/module
    files = pin["build_files"]
    try:
        expected = {p for p in files if p.startswith(module + "/")}
        actual = {p.relative_to(root).as_posix() for p in package.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
        links = [p for p in package.rglob("*") if p.is_symlink()]
        hashes = {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files
                  if (root/p).is_file() and not (root/p).is_symlink()
                  and (root/p).resolve().is_relative_to(root)}
        row["physical_ok"] = not package.is_symlink() and not links and actual == expected and hashes == files
        spec = importlib.util.find_spec(module)
        row["origin"] = spec.origin if spec else None
        if row["physical_ok"] and spec and spec.origin and Path(spec.origin).resolve() == package/"__init__.py":
            # Verified official modules can print banners; never let that turn
            # the JSON protocol into a successful-looking partial observation.
            # Health probes must not create the SDK's default rotating log.
            # Only this disposable child environment changes, never the caller.
            os.environ["NEO_LOG_FILE_ENABLED"] = "false"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                imported = importlib.import_module(module)
            row["import_ok"] = Path(imported.__file__).resolve() == package/"__init__.py"
    except (OSError, ValueError, TypeError, ImportError, AttributeError) as exc:
        row["probe_error"] = type(exc).__name__
result["namespace_owners"] = result["owners"]["neo_api_client"]
print(json.dumps(result))
"""


def _pin() -> tuple[str, str]:
    """Compatibility metadata accessor; repair uses the complete source pin."""
    data = tomllib.loads((REPO / "brokers.lock").read_text(encoding="utf-8"))
    for entry in data.get("broker", []):
        if entry.get("name") == "kotakneoapi":
            version = str(entry.get("version", ""))
            commit = str(entry.get("source_commit", ""))
            if not version or entry.get("homepage") != _KOTAK_HOMEPAGE:
                raise RuntimeError("Kotak Neo brokers.lock entry does not identify the official repository")
            if _FULL_GIT_SHA.fullmatch(commit) is None:
                raise RuntimeError("Kotak Neo source_commit must be a full lowercase Git commit")
            return version, commit
    raise RuntimeError("Kotak Neo is missing from brokers.lock")


def _pins(names: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    entries = tomllib.loads((REPO / "brokers.lock").read_text(encoding="utf-8")).get("broker", [])
    pins = {}
    for name in names:
        selected = [p for p in entries if p.get("name") == name]
        if len(selected) != 1:
            raise RuntimeError(f"Expected one source pin for {name}")
        pin = selected[0]
        module, url = _IDENTITIES[name]
        if (
            pin.get("source_kind") != "git"
            or pin.get("source_url") != url
            or pin.get("homepage") != url.removesuffix(".git")
            or pin.get("source_module") != module
            or not pin.get("version")
        ):
            raise RuntimeError(f"{name} does not identify the official repository/source module")
        if any(_FULL_GIT_SHA.fullmatch(str(pin.get(k, ""))) is None for k in ("source_commit", "source_tree")):
            raise RuntimeError(f"{name} requires a full lowercase Git commit and tree")
        files = pin.get("build_files")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", str(pin.get("build_wheel_sha256", "")))
            or type(files) is not dict
            or f"{module}/__init__.py" not in files
        ):
            raise RuntimeError(f"{name} has no locked physical build identity")
        for relative, digest in files.items():
            if (
                type(relative) is not str
                or not relative
                or "\\" in relative
                or PurePosixPath(relative).is_absolute()
                or ".." in PurePosixPath(relative).parts
                or PurePosixPath(relative).as_posix() != relative
                or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
            ):
                raise RuntimeError(f"{name} has an invalid locked build resource")
        pins[name] = pin
    # Consume the exact resolver export, not an independently invented VCS line.
    requirements = [
        line
        for line in (REPO / "broker-sdk-git-requirements.txt").read_text().splitlines()
        if line and not line.startswith("#")
    ]
    all_pins = {p.get("name"): p for p in entries if p.get("name") in _IDENTITIES}
    expected = [
        f"{name} @ git+{url}@{all_pins.get(name, {}).get('source_commit', '')}"
        for name, (_, url) in _IDENTITIES.items()
    ]
    if sorted(requirements) != sorted(expected):
        raise RuntimeError("Git requirements must contain exactly the two official full-commit pins")
    return pins


def _invoke(
    run: Callable[..., subprocess.CompletedProcess], args: list[str], *, input_text: str | None = None,
) -> subprocess.CompletedProcess:
    options = {"input": input_text} if input_text is not None else {}
    result = run(args, cwd=REPO, capture_output=True, text=True, check=False, **options)
    if result.returncode != 0:
        raise RuntimeError(
            f"Broker SDK environment command failed: {args[0]} {args[1]} "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    return result


def _probe(
    python: Path, run: Callable[..., subprocess.CompletedProcess], pins: dict[str, dict[str, Any]] | None = None
) -> dict[str, Any]:
    result = _invoke(run, [str(python), "-I", "-B", "-c", _PROBE], input_text=json.dumps(pins or {}))
    try:
        state = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Broker SDK distribution probe returned invalid JSON") from exc
    if not isinstance(state, dict):
        raise RuntimeError("Broker SDK distribution probe returned invalid state")
    return state


def _healthy_source(state: dict[str, Any], name: str, version: str, commit: str) -> bool:
    module, url = _IDENTITIES[name]
    owners = state.get("owners", {}).get(module)
    if name == "kotakneoapi":
        owners = state.get("namespace_owners", owners)
        if "neo-api-client" in state:
            return False
    installed = state.get(name)
    if (
        owners != [name]
        or not isinstance(installed, dict)
        or installed.get("version") != version
        or installed.get("duplicate")
        or installed.get("physical_ok") is not True
        or installed.get("import_ok") is not True
    ):
        return False
    direct = installed.get("direct_url")
    if not isinstance(direct, dict) or direct.get("url") != url:
        return False
    vcs = direct.get("vcs_info")
    return (
        isinstance(vcs, dict)
        and vcs.get("vcs") == "git"
        and vcs.get("commit_id") == commit
        and vcs.get("requested_revision") == commit
    )


def _healthy(state: dict[str, Any], version: str, commit: str) -> bool:
    return _healthy_source(state, "kotakneoapi", version, commit)


def _check_owners(state: dict[str, Any], names: tuple[str, ...]) -> None:
    for name in names:
        module = _IDENTITIES[name][0]
        allowed = {name, "neo-api-client"} if name == "kotakneoapi" else {name}
        owners = state.get("owners", {}).get(module, state.get("namespace_owners", []) if name == "kotakneoapi" else [])
        if not isinstance(owners, list) or set(owners) - allowed:
            raise RuntimeError(f"Refusing unrelated owner of {module}; no distributions changed")
        for selected in allowed:
            if selected in state and (
                state[selected].get("duplicate") or state[selected].get("safe_remove") is not True
            ):
                raise RuntimeError(f"Refusing ambiguous/unsafe removal of {selected}; no distributions changed")


def _commands(python: Path) -> tuple[list[str], list[str], str]:
    uv = shutil.which("uv")
    if uv:
        return (
            [uv, "pip", "install", "--python", str(python), "--break-system-packages"],
            [uv, "pip", "uninstall", "--python", str(python), "--break-system-packages"],
            "--reinstall",
        )
    return (
        [str(python), "-m", "pip", "install", "--break-system-packages"],
        [str(python), "-m", "pip", "uninstall", "-y", "--break-system-packages"],
        "--force-reinstall",
    )


def remove_kotak_distributions(
    python: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    """Legacy explicit removal; never uninstall an unrelated namespace owner."""
    state = _probe(python, run)
    _check_owners(state, ("kotakneoapi",))
    present = [name for name in ("kotakneoapi", "neo-api-client") if name in state]
    if present:
        _invoke(run, [*_commands(python)[1], *present])


def _repair(python: Path, names: tuple[str, ...], run: Callable[..., subprocess.CompletedProcess]) -> None:
    pins = _pins(names)
    state = _probe(python, run, pins)
    stale = [
        name for name, pin in pins.items() if not _healthy_source(state, name, pin["version"], pin["source_commit"])
    ]
    if not stale:
        return  # Healthy repeat is strictly probe-only.
    _check_owners(state, names)  # Preflight the whole requested union before writes.
    install, uninstall, reinstall = _commands(python)
    _invoke(run, [*install, "--require-hashes", "--only-binary=:all:", "--no-deps", "-r", str(BUILD_REQUIREMENTS_LOCK)])
    for name in stale:
        removable = (name, "neo-api-client") if name == "kotakneoapi" else (name,)
        present = [n for n in removable if n in state]
        if present:
            _invoke(run, [*uninstall, *present])
        pin = pins[name]
        requirement = f"{name} @ git+{pin['source_url']}@{pin['source_commit']}"
        _invoke(run, [*install, "--no-build-isolation", "--no-deps", reinstall, requirement])
    final = _probe(python, run, pins)
    if any(not _healthy_source(final, name, pin["version"], pin["source_commit"]) for name, pin in pins.items()):
        raise RuntimeError(
            "Broker SDK repair did not produce the pinned Git distribution with exclusive namespace and physical/import proof"
        )


def repair_broker_sdk_environment(
    python: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    """Repair BOTH exact Git SDKs with hashed build tools and no dependency solve."""
    _repair(python, tuple(_IDENTITIES), run)


def repair_kotakneo_environment(
    python: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    """Backward-compatible Kotak-only API, with the same physical source checks."""
    _repair(python, ("kotakneoapi",), run)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args == ["repair"]:
        repair_broker_sdk_environment(Path(sys.executable))
    elif args == ["remove"]:
        remove_kotak_distributions(Path(sys.executable))
    else:
        raise SystemExit("usage: broker_sdk_environment.py repair|remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
