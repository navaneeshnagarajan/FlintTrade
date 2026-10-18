"""Managed source setup must select exact runtime and both broker sources."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_probe_import_does_not_enable_vendor_file_logging(tmp_path, monkeypatch):
    """A verified synthetic resource models the vendor's import-time log sink."""
    from scripts import broker_sdk_environment as env

    package = tmp_path / "neo_api_client"
    package.mkdir()
    body = (
        "import os\nfrom pathlib import Path\n"
        "if os.environ.get('NEO_LOG_FILE_ENABLED', 'true') == 'true':\n"
        "    Path(os.environ['VENDOR_LOG_SENTINEL']).write_text('unexpected import write')\n"
    )
    (package / "__init__.py").write_text(body)
    dist = tmp_path / "kotakneoapi-3.0.9.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Name: kotakneoapi\nVersion: 3.0.9\n")
    (dist / "RECORD").write_text("neo_api_client/__init__.py,,\n")
    marker = tmp_path / "vendor-import-write"
    monkeypatch.setenv("NEO_LOG_FILE_ENABLED", "true")
    monkeypatch.setenv("VENDOR_LOG_SENTINEL", str(marker))

    def run(args, **kwargs):
        index = args.index("-c")
        return subprocess.run(
            [sys.executable, "-S", "-c", args[index + 1]],
            env=os.environ | {"PYTHONPATH": str(tmp_path)},
            **kwargs,
        )

    pin = {"build_files": {"neo_api_client/__init__.py": hashlib.sha256(body.encode()).hexdigest()}}
    state = env._probe(Path(sys.executable), run, {"kotakneoapi": pin})
    assert state["kotakneoapi"]["physical_ok"] and state["kotakneoapi"]["import_ok"]
    assert not marker.exists()
    assert os.environ["NEO_LOG_FILE_ENABLED"] == "true"


def test_probe_uses_stdin_for_large_locked_resource_inventory():
    """Full source pins must not exceed the Windows process command-line limit."""
    from scripts import broker_sdk_environment as env

    pin = {"kotakneoapi": {"build_files": {"x" * 40000: "f" * 64}}}

    def run(args, **kwargs):
        assert "input" in kwargs
        assert len(kwargs["input"]) > 40000
        assert all(len(arg) < 30000 for arg in args)
        return subprocess.CompletedProcess(args, 0, "{}", "")

    assert env._probe(Path(sys.executable), run, pin) == {}


def test_groww_install_paths_require_its_wheel_only():
    root = Path(__file__).resolve().parents[2]
    assert '"--only-binary=growwapi"' in (root / "scripts/ft.py").read_text()
    shell = (root / "packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.sh").read_text()
    powershell = (root / "packages/apps/desktop/resources/bootstrap/flinttrade-bootstrap.ps1").read_text()
    assert "--no-build-package growwapi" in shell
    assert '"--no-build-package",' in powershell and '"growwapi",' in powershell


def test_metadata_only_kotak_is_not_healthy():
    from scripts import broker_sdk_environment as env

    version, commit = env._pin()
    state = {
        "kotakneoapi": {
            "version": version,
            "direct_url": {
                "url": env.KOTAK_REPO,
                "vcs_info": {"vcs": "git", "commit_id": commit, "requested_revision": commit},
            },
        },
        "namespace_owners": ["kotakneoapi"],
    }
    assert not env._healthy(state, version, commit)


@pytest.mark.parametrize("uv_available", [True, False])
def test_native_setup_calls_two_sdk_repair_before_workspace(monkeypatch, uv_available):
    from scripts import ft

    calls = []

    class Reached(Exception):
        pass

    def repair(_python):
        calls.append("two-sdk-repair")
        raise Reached

    monkeypatch.setattr(ft, "repair_broker_sdk_environment", repair, raising=False)
    monkeypatch.setattr(ft, "repair_kotakneo_environment", lambda _python: calls.append("old-only"))
    monkeypatch.setattr(ft, "IS_WINDOWS", True)
    monkeypatch.setattr(ft, "resolve_python", lambda: "/fixture/python")
    monkeypatch.setattr(ft.shutil, "which", lambda name: "/fixture/uv" if name == "uv" and uv_available else None)
    monkeypatch.setattr(ft, "run", lambda *args, **kwargs: calls.append("install") or 0)
    monkeypatch.setattr(ft, "pnpm_argv", lambda: None)
    monkeypatch.setattr(ft, "missing_workspace_modules", lambda *args: ["not reached"])
    with pytest.raises(Reached):
        ft.cmd_setup([])
    assert calls[-1] == "two-sdk-repair"


@pytest.mark.parametrize(
    "script, snippets",
    [
        (
            "flinttrade-bootstrap.sh",
            ["export UV_PYTHON=3.14.8", "python install 3.14.8", "--python 3.14.8", "python3.14"],
        ),
        ("flinttrade-bootstrap.ps1", ['$env:UV_PYTHON = "3.14.8"', '"3.14.8"']),
    ],
)
def test_packaged_managed_runtime_selector_is_exact(script, snippets):
    root = Path(__file__).resolve().parents[2]
    text = (root / "packages/apps/desktop/resources/bootstrap" / script).read_text()
    for snippet in snippets:
        assert snippet in text
    assert "python3.14.8" not in text
