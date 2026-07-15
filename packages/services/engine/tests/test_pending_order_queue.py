"""Tests for PendingOrderQueue (DuckDB-backed approval workflow).

Run with:
    python -m pytest packages/services/engine/tests/test_pending_order_queue.py -v --import-mode=importlib
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _queue_module():
    from flinttrade_engine.action_center import (  # noqa: PLC0415
        ActionCenterError,
        ApprovalRequest,
        PendingOrderQueue,
    )
    return PendingOrderQueue, ActionCenterError, ApprovalRequest


def _make_queue(tmp_path: Path) -> object:
    PendingOrderQueue, *_ = _queue_module()
    return PendingOrderQueue(db_path=tmp_path / "test_ac.duckdb")


def _make_order(symbol: str = "NIFTY") -> dict:
    return {
        "symbol": symbol,
        "action": "BUY",
        "quantity": "50",
        "exchange": "NFO",
        "pricetype": "MARKET",
    }


# ---------------------------------------------------------------------------
# Enqueue
# ---------------------------------------------------------------------------


class TestEnqueue:
    """Tests for PendingOrderQueue.enqueue()."""

    def test_enqueue_returns_approval_request(self, tmp_path: Path):
        PendingOrderQueue, _, ApprovalRequest = _queue_module()
        q = PendingOrderQueue(db_path=tmp_path / "ac.duckdb")
        req = q.enqueue(_make_order(), reason="Manual review required")
        assert isinstance(req, ApprovalRequest)
        assert req.status == "pending"
        assert req.reason == "Manual review required"

    def test_enqueue_auto_generates_uuid(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        assert req.id
        assert len(req.id) == 36  # UUID4

    def test_enqueue_custom_request_id(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        custom_id = "my-custom-id-001"
        req = q.enqueue(_make_order(), reason="Test", request_id=custom_id)
        assert req.id == custom_id

    def test_enqueue_sets_created_at(self, tmp_path: Path):
        from datetime import datetime, timezone
        q = _make_queue(tmp_path)
        before = datetime.now(timezone.utc).isoformat()
        req = q.enqueue(_make_order(), reason="Test")
        after = datetime.now(timezone.utc).isoformat()
        assert before <= req.created_at <= after

    def test_enqueue_sets_expires_at(self, tmp_path: Path):
        from datetime import datetime
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test", ttl_minutes=10)
        created = datetime.fromisoformat(req.created_at)
        expires = datetime.fromisoformat(req.expires_at)
        diff = expires - created
        # Allow 1 second tolerance
        assert abs(diff.total_seconds() - 600) < 2

    def test_enqueue_persists_to_duckdb(self, tmp_path: Path):
        PendingOrderQueue, *_ = _queue_module()
        db = tmp_path / "persist.duckdb"
        q1 = PendingOrderQueue(db_path=db)
        q1.enqueue(_make_order(), reason="Persist test")
        q1.close()
        # Reload
        q2 = PendingOrderQueue(db_path=db)
        pending = q2.list_pending()
        assert len(pending) == 1
        assert pending[0].reason == "Persist test"

    def test_enqueue_order_params_preserved(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        params = _make_order("BANKNIFTY")
        q.enqueue(params, reason="Test")
        pending = q.list_pending()
        assert pending[0].order_params["symbol"] == "BANKNIFTY"

    def test_enqueue_persists_selector_origin_and_intent_context(self, tmp_path: Path):
        q = _make_queue(tmp_path)

        q.enqueue(
            _make_order("RELIANCE"),
            reason="Autonomous-agent BUY signal",
            adapter_id="upstox",
            account_id="primary",
            source="autonomous-agent",
            intent_type="entry",
            producer_ref="agent-session-1",
            intent_context={"entry_price": 2500.0, "stop_loss": 2450.0},
        )

        q.close()
        PendingOrderQueue, *_ = _queue_module()
        reopened = PendingOrderQueue(db_path=tmp_path / "test_ac.duckdb")
        persisted = reopened.list_pending()[0]
        assert persisted.adapter_id == "upstox"
        assert persisted.account_id == "primary"
        assert persisted.source == "autonomous-agent"
        assert persisted.intent_type == "entry"
        assert persisted.producer_ref == "agent-session-1"
        assert persisted.intent_context == {"entry_price": 2500.0, "stop_loss": 2450.0}

    def test_enqueue_rejects_auth_or_credential_material(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)

        with pytest.raises(ActionCenterError, match="credential|authentication"):
            q.enqueue(
                {**_make_order(), "access_token": "must-not-be-persisted"},
                reason="Unsafe payload",
            )


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------


class TestApprove:
    """Tests for PendingOrderQueue.approve()."""

    def test_approve_changes_status(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        approved = q.approve(req.id)
        assert approved.status == "approved"

    def test_approve_removes_from_pending(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.approve(req.id)
        assert len(q.list_pending()) == 0

    def test_approve_nonexistent_raises(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        with pytest.raises(ActionCenterError, match="not found"):
            q.approve("ghost-id")

    def test_approve_already_approved_raises(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.approve(req.id)
        with pytest.raises(ActionCenterError, match="not 'pending'"):
            q.approve(req.id)

    def test_approve_appears_in_history(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.approve(req.id)
        history = q.list_history(statuses=["approved"])
        assert len(history) == 1
        assert history[0].id == req.id


class TestDispatchClaim:
    """The durable queue must make approval single-use before broker dispatch."""

    def test_claim_is_atomic_and_cannot_be_replayed(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")

        claimed = q.claim_for_dispatch(req.id)

        assert claimed.status == "dispatching"
        with pytest.raises(ActionCenterError, match="dispatching"):
            q.claim_for_dispatch(req.id)

    def test_expired_request_cannot_be_claimed(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test", ttl_minutes=0)
        time.sleep(0.05)

        with pytest.raises(ActionCenterError, match="expired"):
            q.claim_for_dispatch(req.id)

        assert q.get(req.id).status == "expired"

    def test_mark_approved_records_result_and_resolution_time(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.claim_for_dispatch(req.id)

        approved = q.mark_approved(req.id, broker_order_id="BROKER-1")

        assert approved.status == "approved"
        assert approved.broker_order_id == "BROKER-1"
        assert approved.resolved_at is not None

    def test_mark_failed_is_terminal_and_never_returns_to_pending(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.claim_for_dispatch(req.id)

        failed = q.mark_failed(
            req.id,
            reason="Broker outcome unknown; inspect the order book",
            outcome_uncertain=True,
        )

        assert failed.status == "failed"
        assert failed.outcome_uncertain is True
        assert q.list_pending() == []
        with pytest.raises(ActionCenterError, match="failed"):
            q.claim_for_dispatch(req.id)

    def test_reject_by_producer_closes_only_pending_entries(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        pending = q.enqueue(
            _make_order("A"),
            reason="Test",
            producer_ref="session-a",
        )
        other = q.enqueue(
            _make_order("B"),
            reason="Test",
            producer_ref="session-b",
        )

        count = q.reject_pending_by_producer("session-a", "Agent session ended")

        assert count == 1
        assert q.get(pending.id).status == "rejected"
        assert q.get(other.id).status == "pending"


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------


class TestReject:
    """Tests for PendingOrderQueue.reject()."""

    def test_reject_changes_status(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        rejected = q.reject(req.id, reason="Risk limit exceeded")
        assert rejected.status == "rejected"
        assert rejected.rejection_reason == "Risk limit exceeded"

    def test_reject_without_reason(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        rejected = q.reject(req.id)
        assert rejected.rejection_reason == ""

    def test_reject_nonexistent_raises(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        with pytest.raises(ActionCenterError, match="not found"):
            q.reject("ghost-id")

    def test_reject_already_rejected_raises(self, tmp_path: Path):
        _, ActionCenterError, _ = _queue_module()
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.reject(req.id, reason="First")
        with pytest.raises(ActionCenterError, match="not 'pending'"):
            q.reject(req.id, reason="Second")

    def test_reject_appears_in_history(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        q.reject(req.id, reason="Operator rejected")
        history = q.list_history(statuses=["rejected"])
        assert len(history) == 1
        assert history[0].rejection_reason == "Operator rejected"


# ---------------------------------------------------------------------------
# List pending
# ---------------------------------------------------------------------------


class TestListPending:
    """Tests for PendingOrderQueue.list_pending()."""

    def test_list_pending_empty(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        assert q.list_pending() == []

    def test_list_pending_shows_only_pending(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        r1 = q.enqueue(_make_order("NIFTY"), reason="A")
        r2 = q.enqueue(_make_order("BANKNIFTY"), reason="B")
        q.approve(r1.id)
        pending = q.list_pending()
        assert len(pending) == 1
        assert pending[0].id == r2.id

    def test_list_pending_excludes_expired(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        q.enqueue(_make_order(), reason="Test", ttl_minutes=0)
        # Force expire immediately (ttl=0 means already expired)
        time.sleep(0.05)
        q.expire_stale()
        pending = q.list_pending()
        assert len(pending) == 0


# ---------------------------------------------------------------------------
# Expire stale
# ---------------------------------------------------------------------------


class TestExpireStale:
    """Tests for PendingOrderQueue.expire_stale()."""

    def test_expire_stale_by_expires_at(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        q.enqueue(_make_order(), reason="Test", ttl_minutes=0)
        time.sleep(0.05)
        count = q.expire_stale()
        assert count == 1

    def test_expire_stale_by_minutes(self, tmp_path: Path):
        PendingOrderQueue, *_ = _queue_module()
        q = PendingOrderQueue(db_path=tmp_path / "expire.duckdb")
        q.enqueue(_make_order(), reason="Test", ttl_minutes=60)
        # Override with minutes=0 to force expire
        count = q.expire_stale(minutes=0)
        assert count == 1
        pending = q.list_pending()
        assert len(pending) == 0

    def test_expired_in_history(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        q.enqueue(_make_order(), reason="Test", ttl_minutes=0)
        time.sleep(0.05)
        q.expire_stale()
        history = q.list_history(statuses=["expired"])
        assert len(history) == 1
        assert history[0].status == "expired"

    def test_expire_does_not_touch_approved(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test", ttl_minutes=60)
        q.approve(req.id)
        count = q.expire_stale(minutes=0)
        assert count == 0


# ---------------------------------------------------------------------------
# List history
# ---------------------------------------------------------------------------


class TestListHistory:
    """Tests for PendingOrderQueue.list_history()."""

    def test_history_filters_by_status(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        r1 = q.enqueue(_make_order("A"), reason="Test")
        r2 = q.enqueue(_make_order("B"), reason="Test")
        q.approve(r1.id)
        q.reject(r2.id)
        approved_hist = q.list_history(statuses=["approved"])
        assert len(approved_hist) == 1
        rejected_hist = q.list_history(statuses=["rejected"])
        assert len(rejected_hist) == 1

    def test_history_default_returns_all_resolved(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        r1 = q.enqueue(_make_order("A"), reason="Test")
        r2 = q.enqueue(_make_order("B"), reason="Test")
        q.approve(r1.id)
        q.reject(r2.id)
        history = q.list_history()
        assert len(history) == 2

    def test_history_respects_limit(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        for i in range(5):
            r = q.enqueue(_make_order(f"SYM{i}"), reason="Test")
            q.approve(r.id)
        history = q.list_history(limit=3)
        assert len(history) == 3


# ---------------------------------------------------------------------------
# ApprovalRequest serialisation
# ---------------------------------------------------------------------------


class TestApprovalRequestSerialisation:
    """Tests for ApprovalRequest.to_dict() and from_row()."""

    def test_to_dict_keys(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Serialise test")
        d = req.to_dict()
        for key in ("id", "order_params", "reason", "created_at", "expires_at",
                    "status", "rejection_reason"):
            assert key in d

    def test_to_dict_status_is_pending(self, tmp_path: Path):
        q = _make_queue(tmp_path)
        req = q.enqueue(_make_order(), reason="Test")
        assert req.to_dict()["status"] == "pending"


# ---------------------------------------------------------------------------
# Crash recovery — interrupted dispatches
# ---------------------------------------------------------------------------


class TestInterruptedDispatchRecovery:
    """A dispatch left in flight by a crashed process must fail-close on restart."""

    def test_reopen_fails_close_orphaned_dispatching_row(self, tmp_path: Path):
        PendingOrderQueue, _err, _req = _queue_module()
        db = tmp_path / "recover.duckdb"

        q1 = PendingOrderQueue(db_path=db)
        req = q1.enqueue(_make_order(), reason="Interrupted", request_id="stuck-1")
        # Simulate the process reaching the broker call and then dying: the row
        # is left in 'dispatching' with no surviving context to finalise it.
        q1.claim_for_dispatch(req.id)
        assert q1.get(req.id).status == "dispatching"
        q1._conn.close()  # noqa: SLF001 - emulate an abrupt process exit

        # Reopening the queue reconciles the orphaned row on startup.
        q2 = PendingOrderQueue(db_path=db)
        recovered = q2.get(req.id)
        assert recovered.status == "failed"
        assert recovered.outcome_uncertain is True
        assert recovered.failure_reason
        assert "in flight" in recovered.failure_reason

    def test_reconcile_returns_count_and_leaves_terminal_rows_untouched(self, tmp_path: Path):
        PendingOrderQueue, _err, _req = _queue_module()
        db = tmp_path / "mixed.duckdb"

        q1 = PendingOrderQueue(db_path=db)
        stuck = q1.enqueue(_make_order("A"), reason="stuck", request_id="stuck")
        approved = q1.enqueue(_make_order("B"), reason="approved", request_id="approved")
        pending = q1.enqueue(_make_order("C"), reason="pending", request_id="pending")
        q1.claim_for_dispatch(stuck.id)
        q1.claim_for_dispatch(approved.id)
        q1.mark_approved(approved.id, broker_order_id="OK-1")
        q1._conn.close()  # noqa: SLF001

        q2 = PendingOrderQueue(db_path=db)
        assert q2.get(stuck.id).status == "failed"
        assert q2.get(approved.id).status == "approved"  # terminal — untouched
        assert q2.get(pending.id).status == "pending"  # still actionable
        # A second reopen with nothing in flight reconciles zero rows.
        q3 = PendingOrderQueue(db_path=db)
        assert q3._reconcile_interrupted_dispatches() == 0  # noqa: SLF001
