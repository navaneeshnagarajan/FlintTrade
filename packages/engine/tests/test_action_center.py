"""Tests for ActionCenter order approval queue.

Run with:
    python -m pytest packages/engine/tests/test_action_center.py -v --import-mode=importlib
"""

from __future__ import annotations

import threading
import time

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order_data(symbol: str = "NIFTY") -> dict:
    return {"symbol": symbol, "action": "BUY", "quantity": "50", "exchange": "NFO"}


def _ac_module():
    """Lazy import to avoid circular-import on module collection."""
    from packages.engine.src.action_center import (  # noqa: PLC0415
        ActionCenter,
        ActionCenterError,
        OrderApprovalStatus,
        PendingOrder,
    )
    return ActionCenter, ActionCenterError, OrderApprovalStatus, PendingOrder


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


class TestSubmit:
    """Tests for ActionCenter.submit()."""

    def test_submit_returns_pending_order(self):
        ActionCenter, ActionCenterError, OrderApprovalStatus, PendingOrder = _ac_module()
        ac = ActionCenter()
        po = ac.submit("ord-1", "acct-1", _make_order_data())
        assert isinstance(po, PendingOrder)
        assert po.order_id == "ord-1"
        assert po.account_id == "acct-1"
        assert po.status == OrderApprovalStatus.PENDING

    def test_submit_auto_generates_order_id(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        po = ac.submit(None, "acct-1", _make_order_data())
        assert po.order_id  # non-empty string
        assert len(po.order_id) == 36  # UUID4 length

    def test_submit_duplicate_order_id_raises(self):
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("dup", "acct-1", _make_order_data())
        with pytest.raises(ActionCenterError, match="already exists"):
            ac.submit("dup", "acct-1", _make_order_data())

    def test_submit_records_created_at(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        before = time.time()
        po = ac.submit("t1", "acct-1", _make_order_data())
        after = time.time()
        assert before <= po.created_at <= after

    def test_submit_resolved_at_is_none(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        po = ac.submit("t2", "acct-1", _make_order_data())
        assert po.resolved_at is None


# ---------------------------------------------------------------------------
# Approve / Reject
# ---------------------------------------------------------------------------


class TestApproveReject:
    """Tests for approve() and reject()."""

    def test_approve_sets_status_approved(self):
        ActionCenter, _, OrderApprovalStatus, _ = _ac_module()
        ac = ActionCenter()
        ac.submit("a1", "acct-1", _make_order_data())
        po = ac.approve("a1")
        assert po.status == OrderApprovalStatus.APPROVED
        assert po.resolved_at is not None

    def test_reject_sets_status_rejected(self):
        ActionCenter, _, OrderApprovalStatus, _ = _ac_module()
        ac = ActionCenter()
        ac.submit("r1", "acct-1", _make_order_data())
        po = ac.reject("r1")
        assert po.status == OrderApprovalStatus.REJECTED
        assert po.resolved_at is not None

    def test_approve_nonexistent_order_raises(self):
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        with pytest.raises(ActionCenterError, match="not found"):
            ac.approve("ghost")

    def test_reject_nonexistent_order_raises(self):
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        with pytest.raises(ActionCenterError, match="not found"):
            ac.reject("ghost")

    def test_approve_already_approved_raises(self):
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("aa", "acct-1", _make_order_data())
        ac.approve("aa")
        with pytest.raises(ActionCenterError, match="not PENDING"):
            ac.approve("aa")

    def test_reject_already_rejected_raises(self):
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("rr", "acct-1", _make_order_data())
        ac.reject("rr")
        with pytest.raises(ActionCenterError, match="not PENDING"):
            ac.reject("rr")


# ---------------------------------------------------------------------------
# Approve all
# ---------------------------------------------------------------------------


class TestApproveAll:
    """Tests for approve_all()."""

    def test_approve_all_returns_approved_list(self):
        ActionCenter, _, OrderApprovalStatus, _ = _ac_module()
        ac = ActionCenter()
        ac.submit("b1", "acct-1", _make_order_data())
        ac.submit("b2", "acct-1", _make_order_data())
        approved = ac.approve_all()
        assert len(approved) == 2
        for po in approved:
            assert po.status == OrderApprovalStatus.APPROVED

    def test_approve_all_empty_queue_returns_empty_list(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        approved = ac.approve_all()
        assert approved == []

    def test_approve_all_skips_already_resolved(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("x1", "acct-1", _make_order_data())
        ac.submit("x2", "acct-1", _make_order_data())
        ac.reject("x2")
        approved = ac.approve_all()
        assert len(approved) == 1
        assert approved[0].order_id == "x1"


# ---------------------------------------------------------------------------
# Get pending / get all
# ---------------------------------------------------------------------------


class TestGetters:
    """Tests for get_pending() and get_all()."""

    def test_get_pending_excludes_resolved(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("p1", "acct-1", _make_order_data())
        ac.submit("p2", "acct-1", _make_order_data())
        ac.approve("p2")
        pending = ac.get_pending()
        assert len(pending) == 1
        assert pending[0].order_id == "p1"

    def test_get_all_includes_all_statuses(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("g1", "acct-1", _make_order_data())
        ac.submit("g2", "acct-1", _make_order_data())
        ac.approve("g1")
        ac.reject("g2")
        all_orders = ac.get_all()
        assert len(all_orders) == 2


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    """Tests for automatic order expiry via TTL.

    The two tests below previously used `time.sleep(1.05)` to wait for the
    1-second TTL window to elapse. The 2026-05-19 multi-agent audit flagged
    the sleeps as wasted CI wall-time and a flake risk. Replaced with a
    `monkeypatch` over the `time.time` reference inside the action_center
    module so the TTL logic sees an artificially advanced clock without any
    real wait.
    """

    def test_expired_order_removed_from_pending(self, monkeypatch):
        from packages.engine.src import action_center as ac_mod  # noqa: PLC0415

        # PendingOrder.created_at uses `default_factory=time.time` which was
        # captured at class-definition time, so it always pulls the REAL wall
        # clock. Our mock only affects the cutoff comparison in `cleanup()`.
        # To make the expiry math work we seed the mocked clock at
        # `real_now + 100` so cutoff (mocked_now - ttl) is comfortably ahead
        # of `created_at` (real_now) once we advance past the TTL.
        clock = {"t": time.time() + 100.0}
        monkeypatch.setattr(ac_mod.time, "time", lambda: clock["t"])

        ActionCenter, *_ = _ac_module()
        ac = ActionCenter(ttl_seconds=1)
        ac.submit("e1", "acct-1", _make_order_data())
        clock["t"] += 1.05  # advance past the 1-second TTL
        pending = ac.get_pending()
        assert len(pending) == 0

    def test_expired_order_present_in_get_all_with_expired_status(self, monkeypatch):
        from packages.engine.src import action_center as ac_mod  # noqa: PLC0415

        clock = {"t": time.time() + 100.0}
        monkeypatch.setattr(ac_mod.time, "time", lambda: clock["t"])

        ActionCenter, _, OrderApprovalStatus, _ = _ac_module()
        ac = ActionCenter(ttl_seconds=1)
        ac.submit("e2", "acct-1", _make_order_data())
        clock["t"] += 1.05
        all_orders = ac.get_all()
        assert len(all_orders) == 1
        assert all_orders[0].status == OrderApprovalStatus.EXPIRED

    def test_ttl_setter_rejects_zero(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        with pytest.raises(ValueError):
            ac.ttl_seconds = 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Concurrency stress test for ActionCenter."""

    def test_concurrent_submit_all_succeed(self):
        """100 threads each submit a unique order — no duplicates, no crashes."""
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        errors: list[Exception] = []

        def _submit(i: int) -> None:
            try:
                ac.submit(f"t-{i}", "acct-1", _make_order_data())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_submit, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(ac.get_all()) == 100

    def test_concurrent_approve_only_one_succeeds(self):
        """Two threads racing to approve the same order — exactly one succeeds."""
        ActionCenter, ActionCenterError, *_ = _ac_module()
        ac = ActionCenter()
        ac.submit("race", "acct-1", _make_order_data())
        successes: list[int] = []
        failures: list[int] = []

        def _try_approve() -> None:
            try:
                ac.approve("race")
                successes.append(1)
            except ActionCenterError:
                failures.append(1)

        t1 = threading.Thread(target=_try_approve)
        t2 = threading.Thread(target=_try_approve)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(successes) == 1
        assert len(failures) == 1


# ---------------------------------------------------------------------------
# Enabled flag
# ---------------------------------------------------------------------------


class TestEnabledFlag:
    """Tests for the enabled property."""

    def test_disabled_by_default(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        assert not ac.enabled

    def test_can_be_toggled(self):
        ActionCenter, *_ = _ac_module()
        ac = ActionCenter()
        ac.enabled = True
        assert ac.enabled
        ac.enabled = False
        assert not ac.enabled
