"""The uploaded status, the monitor label, and runner ownership agree.

The monitor mirror below matches ``projectUploadedStrategy``. A paused
lifecycle is paused. Unknown stays unknown. An unknown or ownership-retained
runner is not a free stop.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.scheduler import StrategyRunner, TimeScheduler
from flinttrade_engine.strategy import BaseStrategy
from flinttrade_engine.strategy_execution import StrategyExecutionContract, StrategyExecutionMode


POSIX_RESOURCE_LIMITS = os.name != "nt"
NO_POSIX_RESOURCE_REASON = (
    "the autouse fixture pins platform.system() to Linux, whose hard uploaded-strategy limits "
    "require the POSIX resource module"
)

SAFE_CODE = """\
def on_tick(ltp):
    pass
"""


def monitor_label(status: dict) -> str:
    """Mirror the Strategy Monitor mapping. Keep this in step with the widget."""
    raw_state = status.get("state")
    state = raw_state.strip().lower() if isinstance(raw_state, str) else ""
    if state not in {"running", "stopped", "crashed"}:
        return "unknown"
    raw_lifecycle = status.get("lifecycle")
    lifecycle = raw_lifecycle.strip().upper() if isinstance(raw_lifecycle, str) else ""
    if lifecycle == "PAUSED" and state in {"running", "stopped"}:
        return "paused"
    if state == "running":
        return "running"
    if state == "stopped":
        return "stopped"
    if state == "crashed":
        return "error"
    return "unknown"


def _assert_not_free_when_unknown(status: dict, *, live: bool, quarantined: bool) -> None:
    """Unknown or retained ownership is never a free stop."""
    retained = status.get("ownership_retained") is True or status.get("state") == "unknown"
    if not retained:
        return
    assert live is True
    assert status["state"] != "stopped"
    assert monitor_label(status) != "stopped"
    if quarantined:
        assert status["state"] == "unknown"
        assert status.get("ownership_retained") is True


class _Strategy(BaseStrategy):
    supported_execution_modes = frozenset({StrategyExecutionMode.READ_ONLY})

    def __init__(self, name: str = "projection") -> None:
        super().__init__(
            name=name,
            exchange="NSE",
            execution_contract=StrategyExecutionContract.read_only(),
        )

    def on_tick(self, quote: Quote) -> None:
        del quote

    def on_bar(self, bar: OHLCV) -> None:
        del bar

    def on_signal(self, signal: dict) -> None:
        del signal

    def generate_orders(self) -> list[Order]:
        return []


def _native_runner(strategy: _Strategy) -> StrategyRunner:
    client = MagicMock()
    client.quotes = AsyncMock(return_value=None)
    scheduler = TimeScheduler()
    scheduler.session_active = MagicMock(return_value=False)
    scheduler.should_square_off = MagicMock(return_value=False)
    return StrategyRunner(
        strategy=strategy,
        client=client,
        scheduler=scheduler,
        tick_interval_seconds=30.0,
    )


@pytest.fixture()
def uploaded(tmp_path, monkeypatch):
    import flinttrade_engine.strategy_runner as module

    monkeypatch.setattr(module, "_find_bwrap_executable", lambda: None)
    monkeypatch.setattr(module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(module, "_read_process_identity", lambda pid: float(pid), raising=False)
    monkeypatch.setattr(module.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(module.os, "killpg", lambda _pgid, _signal: None, raising=False)
    return module.UserStrategyRunner(strategies_dir=tmp_path / "strategies")


def _mock_process(pid: int, returncode: int | None = None) -> MagicMock:
    process = MagicMock(spec=subprocess.Popen)
    process.pid = pid
    process.poll.return_value = returncode
    process.wait.return_value = returncode
    return process


def _replace_tree(uploaded, strategy_id: str, *, alive: bool | None = True, error: Exception | None = None):
    tree = MagicMock()
    if error is not None:
        tree.is_alive.side_effect = error
    else:
        tree.is_alive.return_value = alive
    tree.wait_gone.return_value = True
    uploaded._running[strategy_id].tree = tree
    return tree


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_running_status_monitor_and_owner_agree(uploaded) -> None:
    strategy_id = uploaded.upload("running", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(4242)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, alive=True)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "running"
    assert status["reason"] == "running"
    assert status.get("ownership_retained") is not True
    assert "lifecycle" not in status
    assert monitor_label(status) == "running"
    assert strategy_id in uploaded._running


@pytest.mark.asyncio
async def test_native_running_projection_is_owned_and_not_quarantined() -> None:
    strategy = _Strategy(name="native-running")
    runner = _native_runner(strategy)
    await runner.start()
    try:
        status = runner.project_status()
        assert status["state"] == "running"
        assert status["reason"] == "running"
        assert status["lifecycle"] == "ACTIVE"
        assert status.get("ownership_retained") is not True
        assert monitor_label(status) == "running"
        assert runner.has_live_owner is True
        assert runner.is_quarantined is False
    finally:
        await runner.stop()


def test_idle_status_is_a_free_stop(uploaded) -> None:
    strategy_id = uploaded.upload("idle", SAFE_CODE)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "stopped"
    assert status["reason"] == "idle"
    assert status.get("ownership_retained") is not True
    assert "lifecycle" not in status
    assert monitor_label(status) == "stopped"
    assert strategy_id not in uploaded._running


def test_native_idle_runner_is_free_and_not_quarantined() -> None:
    runner = _native_runner(_Strategy(name="native-idle"))

    status = runner.project_status()

    assert status["state"] == "stopped"
    assert status["reason"] == "idle"
    assert status["lifecycle"] == "STOPPED"
    assert status.get("ownership_retained") is not True
    assert monitor_label(status) == "stopped"
    assert runner.has_live_owner is False
    assert runner.is_quarantined is False


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_crashed_exit_nonzero_is_not_a_stop_and_not_owned(uploaded) -> None:
    strategy_id = uploaded.upload("crashed", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(111, returncode=1)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, alive=False)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "crashed"
    assert status["reason"] == "exit_nonzero"
    assert status["exit_code"] == 1
    assert status.get("ownership_retained") is not True
    assert monitor_label(status) == "error"
    assert monitor_label(status) != "stopped"
    assert strategy_id not in uploaded._running


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_clean_exit_is_stopped_without_ownership(uploaded) -> None:
    strategy_id = uploaded.upload("clean", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(112, returncode=0)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, alive=False)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "stopped"
    assert status["reason"] == "exit_clean"
    assert status["exit_code"] == 0
    assert status.get("ownership_retained") is not True
    assert monitor_label(status) == "stopped"
    assert strategy_id not in uploaded._running


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_missing_exit_code_is_named_and_stopped(uploaded) -> None:
    strategy_id = uploaded.upload("missing_exit", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(113, returncode=None)):
        uploaded.start(strategy_id)
    process = uploaded._running[strategy_id].process
    process.poll.return_value = None
    process.wait.return_value = None
    _replace_tree(uploaded, strategy_id, alive=False)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "stopped"
    assert status["reason"] == "exit_missing"
    assert strategy_id not in uploaded._running


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_leader_exit_with_a_live_tree_stays_running(uploaded) -> None:
    strategy_id = uploaded.upload("leader", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(114, returncode=0)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, alive=True)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "running"
    assert status["leader_exited"] is True
    assert status["reason"] == "leader_exited"
    assert monitor_label(status) == "running"
    assert strategy_id in uploaded._running


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_unreadable_tree_stays_unknown_and_owned(uploaded) -> None:
    strategy_id = uploaded.upload("unread", SAFE_CODE)
    held = _Strategy(name="unread-held")
    uploaded.strategy = held
    with patch("subprocess.Popen", return_value=_mock_process(808)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, error=OSError("job query failed"))

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "unknown"
    assert status["reason"] == "tree_unreadable"
    assert status["ownership_retained"] is True
    assert status["lifecycle"] == "STOPPED"
    assert monitor_label(status) == "unknown"
    assert strategy_id in uploaded._running
    _assert_not_free_when_unknown(status, live=True, quarantined=True)


def test_quarantined_native_runner_is_unknown_and_not_free() -> None:
    strategy = _Strategy(name="quarantined")
    runner = _native_runner(strategy)
    with runner._ownership_lock:
        runner._quarantined = True

    status = runner.project_status()

    assert status["state"] == "unknown"
    assert status["reason"] == "cleanup_unproven"
    assert status["ownership_retained"] is True
    assert status["lifecycle"] == "STOPPED"
    assert monitor_label(status) == "unknown"
    assert runner.has_live_owner is True
    assert runner.is_quarantined is True
    _assert_not_free_when_unknown(status, live=runner.has_live_owner, quarantined=runner.is_quarantined)


def test_stop_failure_retains_ownership_without_claiming_quarantine() -> None:
    runner = _native_runner(_Strategy(name="stop-failed"))
    with runner._ownership_lock:
        runner._stop_failed = True

    status = runner.project_status()

    assert status["state"] == "unknown"
    assert status["reason"] == "cleanup_unproven"
    assert status["ownership_retained"] is True
    assert monitor_label(status) != "stopped"
    assert runner.has_live_owner is True
    assert runner.is_quarantined is False


@pytest.mark.asyncio
async def test_paused_lifecycle_is_paused_and_still_owned() -> None:
    strategy = _Strategy(name="paused")
    runner = _native_runner(strategy)
    await runner.start()
    try:
        runner.pause()
        status = runner.project_status()
        assert strategy.state.value == "PAUSED"
        assert status["lifecycle"] == "PAUSED"
        assert status["state"] == "running"
        assert status["reason"] == "running"
        assert status.get("ownership_retained") is not True
        assert monitor_label(status) == "paused"
        assert monitor_label(status) not in {"running", "stopped"}
        assert runner.has_live_owner is True
        assert runner.is_quarantined is False
    finally:
        await runner.stop()


@pytest.mark.skipif(not POSIX_RESOURCE_LIMITS, reason=NO_POSIX_RESOURCE_REASON)
def test_uploaded_status_includes_paused_lifecycle_when_a_strategy_is_held(uploaded) -> None:
    strategy = _Strategy(name="held-paused")
    strategy.start()
    strategy.pause()
    uploaded.strategy = strategy
    strategy_id = uploaded.upload("held", SAFE_CODE)
    with patch("subprocess.Popen", return_value=_mock_process(5150)):
        uploaded.start(strategy_id)
    _replace_tree(uploaded, strategy_id, alive=True)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "running"
    assert status["reason"] == "running"
    assert status["lifecycle"] == "PAUSED"
    assert monitor_label(status) == "paused"


def test_idle_uploaded_status_includes_lifecycle_when_a_strategy_is_held(uploaded) -> None:
    uploaded.strategy = _Strategy(name="held_idle")
    strategy_id = uploaded.upload("held_idle", SAFE_CODE)

    status = uploaded.get_status(strategy_id)

    assert status["state"] == "stopped"
    assert status["reason"] == "idle"
    assert status["lifecycle"] == "STOPPED"
    assert monitor_label(status) == "stopped"
