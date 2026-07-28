"""The backend writes ``<workspace>/logs/flinttrade.log`` for the admin panel.

Pins the writer behind ``operations_routes.get_recent_logs`` (the
``/api/v1/logs/recent`` view): ``flinttrade_core.app._attach_log_file_handler``
must land emitted log records in ``flinttrade.log`` inside the resolved
workspace log directory, must not double-write when the app factory runs twice
in one process, and must never break startup when the log directory is
unwritable.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated workspace with a seeded master password (no API key)."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    master_password = tmp_path / "master_password"
    master_password.write_text("backend-log-file-test-password", encoding="utf-8")
    master_password.chmod(0o600)
    return tmp_path


@pytest.fixture(autouse=True)
def _detach_file_handlers_after():
    """Remove and close any workspace file handler left on the root logger.

    The factory attaches a ``RotatingFileHandler`` pointing inside the pytest
    ``tmp_path`` workspace; leaving it attached would write later tests' log
    records into a stale directory and (on Windows) hold the file open so
    pytest's tmp-path cleanup cannot delete it.
    """
    yield
    from flinttrade_core.app import _LOG_FILE_SENTINEL

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _LOG_FILE_SENTINEL, False):
            root.removeHandler(handler)
            handler.close()


def _log_file(workspace: Path) -> Path:
    return workspace / "logs" / "flinttrade.log"


def test_emitted_log_line_lands_in_flinttrade_log(workspace: Path) -> None:
    """Creating the app then logging writes a JSON line into flinttrade.log."""
    from flinttrade_core.app import create_flask_app

    create_flask_app()

    marker = f"backend-log-file-{uuid.uuid4().hex}"
    logging.getLogger("flinttrade").info(marker)

    log_file = _log_file(workspace)
    assert log_file.exists(), "flinttrade.log was not created in the workspace log dir"
    lines = [line for line in log_file.read_text(encoding="utf-8").splitlines() if marker in line]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == marker
    assert entry["level"] == "info"


def test_factory_twice_does_not_double_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second create_flask_app() run must not leave two file handlers writing.

    The second run uses a fresh workspace (rebuilding twice inside one
    workspace trips unrelated SQLite reopen failures on Windows); if the first
    run's handler survived the factory's root-handler sweep, the marker would
    land in BOTH workspaces' log files instead of exactly once in the second.
    """
    from flinttrade_core.app import create_flask_app

    workspaces: list[Path] = []
    for name in ("first", "second"):
        ws = tmp_path / name
        ws.mkdir()
        master_password = ws / "master_password"
        master_password.write_text("backend-log-file-test-password", encoding="utf-8")
        master_password.chmod(0o600)
        workspaces.append(ws)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(ws))
        monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
        create_flask_app()

    marker = f"backend-log-file-once-{uuid.uuid4().hex}"
    logging.getLogger("flinttrade").info(marker)

    first_log, second_log = (_log_file(ws) for ws in workspaces)
    assert second_log.exists()
    assert second_log.read_text(encoding="utf-8").count(marker) == 1
    if first_log.exists():
        assert marker not in first_log.read_text(encoding="utf-8")


def test_unwritable_log_dir_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unwritable log directory degrades to a warning, never an exception."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    # Block the log directory: a FILE named "logs" makes mkdir raise OSError
    # on every platform (no POSIX-only chmod tricks needed).
    (tmp_path / "logs").write_text("not a directory", encoding="utf-8")

    from flinttrade_core.app import _LOG_FILE_SENTINEL, _attach_log_file_handler

    scratch_logger = logging.Logger("flinttrade-log-file-scratch")
    _attach_log_file_handler(scratch_logger, [])

    assert not any(getattr(h, _LOG_FILE_SENTINEL, False) for h in scratch_logger.handlers)
    assert not (tmp_path / "logs" / "flinttrade.log").exists()
