"""Repair the managed Kotak Neo SDK before runtime attestation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
KOTAK_REPO = "https://github.com/Kotak-Neo/kotak-neo-python.git"
_PROBE = """
import importlib.metadata as md
import json
import re

result = {}
for dist in md.distributions():
    name = re.sub(r"[-_.]+", "-", str(dist.metadata.get("Name", "")).lower())
    if name in {"kotakneoapi", "neo-api-client"}:
        direct = dist.read_text("direct_url.json")
        try:
            direct = json.loads(direct) if direct else None
        except ValueError:
            direct = None
        result[name] = {"version": dist.version, "direct_url": direct}
    top_level = (dist.read_text("top_level.txt") or "").splitlines()
    record_owns = any(str(file).replace("\\\\", "/").split("/")[0] == "neo_api_client" for file in (dist.files or ()))
    if "neo_api_client" in top_level or record_owns:
        result.setdefault("namespace_owners", []).append(name)
print(json.dumps(result))
"""


def _pin() -> tuple[str, str]:
    data = tomllib.loads((REPO / "brokers.lock").read_text(encoding="utf-8"))
    for entry in data.get("broker", []):
        if entry.get("name") == "kotakneoapi":
            return str(entry["version"]), str(entry["source_commit"])
    raise RuntimeError("Kotak Neo is missing from brokers.lock")


def _invoke(run: Callable[..., subprocess.CompletedProcess], args: list[str]) -> subprocess.CompletedProcess:
    result = run(args, cwd=REPO, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Kotak Neo environment command failed: {args[0]} {args[1]} "
                           f"(exit {result.returncode}): {result.stderr.strip()}")
    return result


def _probe(python: Path, run: Callable[..., subprocess.CompletedProcess]) -> dict[str, Any]:
    result = _invoke(run, [str(python), "-c", _PROBE])
    try:
        state = json.loads(result.stdout)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Kotak Neo distribution probe returned invalid JSON") from exc
    if not isinstance(state, dict):
        raise RuntimeError("Kotak Neo distribution probe returned invalid state")
    return state


def _healthy(state: dict[str, Any], version: str, commit: str) -> bool:
    if "neo-api-client" in state:
        return False
    owners = state.get("namespace_owners")
    if owners != ["kotakneoapi"]:
        return False
    installed = state.get("kotakneoapi")
    if not isinstance(installed, dict) or installed.get("version") != version:
        return False
    direct = installed.get("direct_url")
    if not isinstance(direct, dict):
        return False
    vcs = direct.get("vcs_info")
    if not isinstance(vcs, dict):
        return False
    try:
        url = urlsplit(direct.get("url", ""))
        return (
            url.scheme == "https" and url.hostname == "github.com"
            and url.path == "/Kotak-Neo/kotak-neo-python.git" and not url.query and not url.fragment
            and url.username is None and url.password is None and url.port is None
            and vcs.get("vcs") == "git" and vcs.get("commit_id") == commit
            and vcs.get("requested_revision", commit) == commit
        )
    except (TypeError, ValueError, AttributeError):
        return False


def remove_kotak_distributions(
    python: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Remove both overlapping Kotak distributions from a pip-only environment."""
    state = _probe(python, run)
    if "kotakneoapi" in state or "neo-api-client" in state:
        if shutil.which("uv"):
            _invoke(run, ["uv", "pip", "uninstall", "--python", str(python), "kotakneoapi", "neo-api-client"])
        else:
            _invoke(run, [str(python), "-m", "pip", "uninstall", "-y", "kotakneoapi", "neo-api-client"])


def repair_kotakneo_environment(
    python: Path, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Replace a stale v2/PyPI-v3 install and require exact Git provenance.

    A healthy environment is only probed; repeated setup is therefore safe.
    """
    version, commit = _pin()
    if _healthy(_probe(python, run), version, commit):
        return
    _invoke(run, ["uv", "pip", "uninstall", "--python", str(python), "kotakneoapi", "neo-api-client"])
    _invoke(run, ["uv", "sync", "--frozen", "--all-packages", "--reinstall-package", "kotakneoapi"])
    if not _healthy(_probe(python, run), version, commit):
        raise RuntimeError("Kotak Neo sync did not produce the pinned Git distribution with exclusive namespace")


def main(argv: list[str] | None = None) -> int:
    """Run repair/removal for the interpreter that launched this script."""
    args = argv if argv is not None else sys.argv[1:]
    if args == ["repair"]:
        repair_kotakneo_environment(Path(sys.executable))
    elif args == ["remove"]:
        remove_kotak_distributions(Path(sys.executable))
    else:
        raise SystemExit("usage: broker_sdk_environment.py repair|remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
