"""Tests for the three new mirror.py capabilities:

1. Multiplier-based allocation (AllocationMode.MULTIPLIER + MirrorConfig)
2. WebSocket-based position change detection (PositionWatcher)
3. Broker cost metadata (BrokerCostMetadata + MirrorConfig.cheapest_account)

All tests are unit-level — no live OpenAlgo or network calls.
"""

from __future__ import annotations

import logging
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from flinttrade_ditto.account_manager import BrokerAccount
from flinttrade_ditto.mirror import (
    AllocationMode,
    BrokerCostMetadata,
    MirrorConfig,
    PositionMirror,
    PositionWatcher,
    compute_multiplier_allocation,
)
from flinttrade_core.models import Order
from flinttrade_gateway.log_safety import account_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    account_id: str = "acc1",
    name: str = "Test",
    host: str = "http://127.0.0.1:5001",
    api_key: str = "test_key",
    weight: float = 1.0,
    enabled: bool = True,
    is_master: bool = False,
) -> BrokerAccount:
    return BrokerAccount(
        account_id=account_id,
        name=name,
        openalgo_host=host,
        api_key=api_key,
        allocation_weight=weight,
        enabled=enabled,
        is_master=is_master,
    )


def _make_order(
    symbol: str = "NIFTY25APR20000CE",
    action: str = "BUY",
    qty: str = "2",
    exchange: str = "NFO",
) -> Order:
    return Order(symbol=symbol, action=action, quantity=qty, exchange=exchange)


# ---------------------------------------------------------------------------
# 1. Multiplier-based allocation
# ---------------------------------------------------------------------------


class TestMultiplierAllocation:
    """compute_multiplier_allocation and AllocationMode.MULTIPLIER end-to-end."""

    def test_global_multiplier_applied(self) -> None:
        accs = [_make_account("a1"), _make_account("a2")]
        cfg = MirrorConfig(multiplier=3.0)
        result = compute_multiplier_allocation(2, accs, cfg)
        assert result["a1"] == 6
        assert result["a2"] == 6

    def test_per_account_multiplier_overrides_global(self) -> None:
        accs = [_make_account("a1"), _make_account("a2")]
        cfg = MirrorConfig(
            multiplier=1.0,
            account_multipliers={"a2": 2.0},
        )
        result = compute_multiplier_allocation(4, accs, cfg)
        assert result["a1"] == 4   # global 1×
        assert result["a2"] == 8   # per-account 2×

    def test_zero_multiplier_omits_account(self) -> None:
        accs = [_make_account("a1"), _make_account("a2")]
        cfg = MirrorConfig(multiplier=1.0, account_multipliers={"a2": 0.0})
        result = compute_multiplier_allocation(5, accs, cfg)
        assert "a1" in result
        assert "a2" not in result

    def test_fractional_multiplier_rounds(self) -> None:
        accs = [_make_account("a1")]
        cfg = MirrorConfig(multiplier=1.5)
        result = compute_multiplier_allocation(3, accs, cfg)
        # 3 × 1.5 = 4.5 → rounds to 5 (round-half-to-even) or 5 — must be int
        assert isinstance(result["a1"], int)
        assert result["a1"] in (4, 5)  # both are acceptable rounding outcomes

    def test_minimum_quantity_is_one(self) -> None:
        accs = [_make_account("a1")]
        cfg = MirrorConfig(multiplier=0.1)
        result = compute_multiplier_allocation(1, accs, cfg)
        assert result["a1"] >= 1

    def test_config_get_multiplier_fallback(self) -> None:
        cfg = MirrorConfig(multiplier=2.5)
        assert cfg.get_multiplier("unknown_acc") == 2.5

    def test_config_get_multiplier_per_account(self) -> None:
        cfg = MirrorConfig(multiplier=1.0, account_multipliers={"acc_x": 3.0})
        assert cfg.get_multiplier("acc_x") == 3.0

    def test_position_mirror_multiplier_mode_execute(self) -> None:
        """PositionMirror.execute routes through multiplier allocation."""
        accs = [
            _make_account("slave1"),
            _make_account("slave2"),
        ]
        cfg = MirrorConfig(
            mode=AllocationMode.MULTIPLIER,
            multiplier=1.0,
            account_multipliers={"slave2": 2.0},
        )
        mirror = PositionMirror(accs, mirror_config=cfg)

        captured: list[tuple[str, int]] = []

        def _fake_place(order: Order, account: BrokerAccount, qty: int) -> MagicMock:
            captured.append((account.account_id, qty))
            mock_result = MagicMock()
            mock_result.success = True
            return mock_result

        with patch.object(PositionMirror, "_place_on_account", side_effect=_fake_place):
            order = _make_order(qty="4")
            mirror.execute(order)

        qty_map = dict(captured)
        assert qty_map.get("slave1") == 4   # 4 × 1.0
        assert qty_map.get("slave2") == 8   # 4 × 2.0

    def test_allocation_mode_multiplier_in_enum(self) -> None:
        assert AllocationMode.MULTIPLIER.value == "MULTIPLIER"


# ---------------------------------------------------------------------------
# 2. WebSocket-based position change detection (PositionWatcher)
# ---------------------------------------------------------------------------


class TestPositionWatcher:
    """PositionWatcher detects position changes via polling."""

    def _make_watcher(
        self, poll_interval: float = 0.05
    ) -> PositionWatcher:
        acc = _make_account(host="http://127.0.0.1:9999")
        return PositionWatcher(acc, poll_interval=poll_interval)

    def test_initial_state_not_running(self) -> None:
        watcher = self._make_watcher()
        assert not watcher.is_running

    def test_start_sets_running(self) -> None:
        watcher = self._make_watcher(poll_interval=60.0)
        try:
            watcher.start()
            assert watcher.is_running
        finally:
            watcher.stop()

    def test_stop_clears_running(self) -> None:
        watcher = self._make_watcher(poll_interval=60.0)
        watcher.start()
        watcher.stop()
        assert not watcher.is_running

    def test_stop_timeout_retains_live_thread_for_retry(self) -> None:
        watcher = self._make_watcher()
        release_thread = threading.Event()
        thread = threading.Thread(target=release_thread.wait, daemon=True)
        watcher._running = True
        watcher._thread = thread
        thread.start()

        try:
            assert watcher.stop(timeout=0.01) is False
            assert watcher._thread is thread
            assert watcher.is_running is True
        finally:
            release_thread.set()
            thread.join(timeout=1.0)

        assert watcher.stop(timeout=1.0) is True
        assert watcher._thread is None
        assert watcher.is_running is False

    def test_double_start_is_noop(self) -> None:
        watcher = self._make_watcher(poll_interval=60.0)
        try:
            watcher.start()
            thread1 = watcher._thread
            watcher.start()  # second call
            assert watcher._thread is thread1  # same thread object
        finally:
            watcher.stop()

    def test_on_change_callback_registered(self) -> None:
        watcher = self._make_watcher()
        cb = MagicMock()
        watcher.on_change(cb)
        assert cb in watcher._callbacks

    def test_prime_seeds_source_snapshot_without_emitting_a_change(self) -> None:
        watcher = self._make_watcher()
        callback = MagicMock()
        watcher.on_change(callback)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "status": "success",
            "data": [
                {
                    "symbol": "RELIANCE",
                    "quantity": 3,
                    "exchange": "NSE",
                    "product": "MIS",
                }
            ],
        }
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.post.return_value = response

        with patch("flinttrade_ditto.mirror.httpx.Client", return_value=http):
            snapshot = watcher.prime()

        assert snapshot[("NSE", "RELIANCE", "MIS")]["quantity"] == 3
        assert watcher._last_snapshot == snapshot
        callback.assert_not_called()

    def test_snapshot_keeps_same_symbol_in_distinct_products(self) -> None:
        watcher = self._make_watcher()
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "status": "success",
            "data": [
                {
                    "symbol": "RELIANCE",
                    "quantity": 3,
                    "exchange": "NSE",
                    "product": "MIS",
                },
                {
                    "symbol": "RELIANCE",
                    "quantity": 7,
                    "exchange": "NSE",
                    "product": "CNC",
                },
            ],
        }
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.post.return_value = response

        with patch("flinttrade_ditto.mirror.httpx.Client", return_value=http):
            snapshot = watcher._fetch_snapshot()

        assert snapshot == {
            ("NSE", "RELIANCE", "MIS"): {
                "symbol": "RELIANCE",
                "quantity": 3,
                "exchange": "NSE",
                "product": "MIS",
            },
            ("NSE", "RELIANCE", "CNC"): {
                "symbol": "RELIANCE",
                "quantity": 7,
                "exchange": "NSE",
                "product": "CNC",
            },
        }

    @pytest.mark.parametrize(
        "payload",
        [
            {"status": "success"},
            {"status": "success", "data": None},
            {"status": "error", "data": []},
            {"status": "success", "data": [None]},
            {"status": "success", "data": [{"quantity": 1, "exchange": "NSE", "product": "MIS"}]},
            {"status": "success", "data": [{"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS"}]},
            {
                "status": "success",
                "data": [
                    {
                        "symbol": "RELIANCE",
                        "quantity": "not-a-quantity",
                        "exchange": "NSE",
                        "product": "MIS",
                    }
                ],
            },
        ],
    )
    def test_fetch_snapshot_rejects_incomplete_or_malformed_payloads(
        self,
        payload: object,
    ) -> None:
        watcher = self._make_watcher()
        response = MagicMock(status_code=200)
        response.json.return_value = payload
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.post.return_value = response

        with (
            patch("flinttrade_ditto.mirror.httpx.Client", return_value=http),
            pytest.raises(RuntimeError, match="positionbook"),
        ):
            watcher._fetch_snapshot()

    def test_authoritative_empty_snapshot_is_valid_and_closes_prior_position(self) -> None:
        watcher = self._make_watcher()
        watcher._last_snapshot = {
            "RELIANCE": {
                "symbol": "RELIANCE",
                "quantity": 3,
                "exchange": "NSE",
                "product": "MIS",
            }
        }
        callback = MagicMock()
        watcher.on_change(callback)
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "success", "data": []}
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.post.return_value = response

        with patch("flinttrade_ditto.mirror.httpx.Client", return_value=http):
            watcher._poll_once()

        callback.assert_called_once()
        assert callback.call_args.args[1]["quantity"] == 0
        assert watcher._last_snapshot == {}

    def test_malformed_snapshot_never_becomes_a_flat_position(self) -> None:
        watcher = self._make_watcher()
        prior = {
            "RELIANCE": {
                "symbol": "RELIANCE",
                "quantity": 3,
                "exchange": "NSE",
                "product": "MIS",
            }
        }
        watcher._last_snapshot = prior
        callback = MagicMock()
        watcher.on_change(callback)
        response = MagicMock(status_code=200)
        response.json.return_value = {
            "status": "success",
            "data": [{"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS"}],
        }
        http = MagicMock()
        http.__enter__ = MagicMock(return_value=http)
        http.__exit__ = MagicMock(return_value=False)
        http.post.return_value = response

        with (
            patch("flinttrade_ditto.mirror.httpx.Client", return_value=http),
            pytest.raises(RuntimeError, match="positionbook"),
        ):
            watcher._poll_once()

        callback.assert_not_called()
        assert watcher._last_snapshot == prior

    def test_detect_changes_new_position(self) -> None:
        watcher = self._make_watcher()
        current = {"NIFTY25APR20000CE": {"symbol": "NIFTY25APR20000CE", "quantity": 75}}
        changed = watcher._detect_changes(current)
        assert "NIFTY25APR20000CE" in changed

    def test_detect_changes_qty_updated(self) -> None:
        watcher = self._make_watcher()
        # Seed a previous snapshot
        watcher._last_snapshot = {
            "NIFTY25APR20000CE": {"symbol": "NIFTY25APR20000CE", "quantity": 75}
        }
        current = {"NIFTY25APR20000CE": {"symbol": "NIFTY25APR20000CE", "quantity": 150}}
        changed = watcher._detect_changes(current)
        assert "NIFTY25APR20000CE" in changed

    def test_detect_changes_unchanged_position_not_reported(self) -> None:
        watcher = self._make_watcher()
        pos = {"symbol": "RELIANCE", "quantity": 10}
        watcher._last_snapshot = {"RELIANCE": pos}
        changed = watcher._detect_changes({"RELIANCE": dict(pos)})
        assert "RELIANCE" not in changed

    def test_detect_changes_closed_position(self) -> None:
        """A position that disappears from an authoritative snapshot reports quantity=0."""
        watcher = self._make_watcher()
        watcher._last_snapshot = {
            "BANKNIFTY25APR47000CE": {"symbol": "BANKNIFTY25APR47000CE", "quantity": 30}
        }
        changed = watcher._detect_changes({})  # position closed
        assert "BANKNIFTY25APR47000CE" in changed
        assert changed["BANKNIFTY25APR47000CE"]["quantity"] == 0

    def test_product_transition_closes_old_leg_before_opening_new_leg(self) -> None:
        watcher = self._make_watcher()
        mis_key = ("NSE", "RELIANCE", "MIS")
        cnc_key = ("NSE", "RELIANCE", "CNC")
        watcher._last_snapshot = {
            mis_key: {
                "symbol": "RELIANCE",
                "quantity": 3,
                "exchange": "NSE",
                "product": "MIS",
            }
        }

        changed = watcher._detect_changes(
            {
                cnc_key: {
                    "symbol": "RELIANCE",
                    "quantity": 3,
                    "exchange": "NSE",
                    "product": "CNC",
                }
            }
        )

        assert list(changed) == [mis_key, cnc_key]
        assert changed[mis_key]["quantity"] == 0
        assert changed[cnc_key]["quantity"] == 3

    def test_callback_fires_on_position_change(self) -> None:
        """Full integration: mock HTTP response triggers callback."""
        fired: list[tuple[str, dict]] = []

        watcher = self._make_watcher(poll_interval=0.02)
        watcher.on_change(lambda acc_id, pos: fired.append((acc_id, pos)))

        response_data = {
            "status": "success",
            "data": [
                {
                    "symbol": "NIFTY25APR20000CE",
                    "quantity": 75,
                    "exchange": "NFO",
                    "product": "MIS",
                }
            ],
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = response_data

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(return_value=mock_resp)

        with patch("flinttrade_ditto.mirror.httpx.Client", return_value=mock_client):
            watcher.start()
            deadline = time.time() + 1.0
            while not fired and time.time() < deadline:
                time.sleep(0.01)
            watcher.stop()

        assert len(fired) >= 1
        assert fired[0][1]["symbol"] == "NIFTY25APR20000CE"

    def test_http_error_does_not_crash_watcher(self) -> None:
        """A failed HTTP poll should not stop the watcher thread."""
        watcher = self._make_watcher(poll_interval=0.02)

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post = MagicMock(side_effect=ConnectionError("refused"))

        with patch("flinttrade_ditto.mirror.httpx.Client", return_value=mock_client):
            watcher.start()
            time.sleep(0.1)
            assert watcher.is_running
            watcher.stop()

    def test_poll_failure_notifies_error_callbacks_without_exception_detail(self) -> None:
        watcher = self._make_watcher(poll_interval=60.0)
        failures: list[str] = []
        watcher.on_error(failures.append)

        def fail_once() -> None:
            watcher._stop_event.set()
            raise RuntimeError("private broker failure detail")

        watcher._poll_once = fail_once  # type: ignore[method-assign]
        watcher._poll_loop()

        assert failures == [watcher._account.account_id]

    def test_poll_log_redacts_account_and_broker_exception(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        private_account_id = "private-account-9087"
        private_detail = "broker rejected secret credential material"
        watcher = PositionWatcher(_make_account(private_account_id), poll_interval=60.0)

        def fail_once() -> dict[str, dict]:
            watcher._stop_event.set()
            raise RuntimeError(private_detail)

        watcher._fetch_snapshot = fail_once  # type: ignore[method-assign]
        caplog.set_level(logging.WARNING, logger="flinttrade.ditto.mirror")

        watcher.start()
        assert watcher._thread is not None
        watcher._thread.join(timeout=1.0)
        watcher.stop(timeout=1.0)

        assert private_account_id not in caplog.text
        assert private_detail not in caplog.text
        assert account_ref(private_account_id) in caplog.text

    def test_min_poll_interval_enforced(self) -> None:
        acc = _make_account()
        watcher = PositionWatcher(acc, poll_interval=0.01)
        # Minimum is 0.5 s
        assert watcher._poll_interval >= 0.5


# ---------------------------------------------------------------------------
# 3. Broker cost metadata
# ---------------------------------------------------------------------------


class TestBrokerCostMetadata:
    """BrokerCostMetadata computation and MirrorConfig cost routing."""

    def _kotak_meta(self) -> BrokerCostMetadata:
        return BrokerCostMetadata(
            broker_key="kotak",
            display_name="Kotak Neo",
            brokerage_frac=0.0,
            brokerage_flat_per_order=0.0,
            stt_futures_sell=0.0005,
            stt_options_sell=0.0015,
            exchange_charge_futures=1.73e-5,
            exchange_charge_options=3.503e-4,
            gst_rate=0.18,
            sebi_charge_per_crore=10.0,
            stamp_duty_buy_futures=2e-5,
            stamp_duty_buy_options=3e-5,
            demat_amc_annual=600.0,
            notes="Zero brokerage from Nov 2025",
        )

    def _paid_meta(self) -> BrokerCostMetadata:
        """Simulate a broker with 0.02% brokerage."""
        return BrokerCostMetadata(
            broker_key="other",
            brokerage_frac=0.0002,
            stt_options_sell=0.0015,
        )

    def test_broker_key_stored(self) -> None:
        meta = self._kotak_meta()
        assert meta.broker_key == "kotak"

    def test_zero_brokerage_kotak(self) -> None:
        meta = self._kotak_meta()
        assert meta.brokerage_frac == 0.0
        assert meta.brokerage_flat_per_order == 0.0

    def test_roundtrip_cost_is_float(self) -> None:
        meta = self._kotak_meta()
        cost = meta.estimated_roundtrip_cost_frac(is_options=True)
        assert isinstance(cost, float)
        assert cost >= 0.0

    def test_roundtrip_cost_futures_lower_than_options(self) -> None:
        """Options have higher STT and exchange charges than futures."""
        meta = self._kotak_meta()
        cost_fut = meta.estimated_roundtrip_cost_frac(is_options=False)
        cost_opt = meta.estimated_roundtrip_cost_frac(is_options=True)
        assert cost_opt > cost_fut

    def test_kotak_cheaper_than_paid_broker(self) -> None:
        kotak = self._kotak_meta()
        other = self._paid_meta()
        assert (
            kotak.estimated_roundtrip_cost_frac()
            < other.estimated_roundtrip_cost_frac()
        )


class TestMirrorConfigCostRouting:
    """MirrorConfig attaches broker cost metadata and routes to cheapest."""

    def test_get_broker_cost_returns_none_for_unknown(self) -> None:
        cfg = MirrorConfig()
        assert cfg.get_broker_cost("unknown_acc") is None

    def test_get_broker_cost_returns_metadata(self) -> None:
        meta = BrokerCostMetadata(broker_key="kotak")
        cfg = MirrorConfig(broker_costs={"acc_kotak": meta})
        assert cfg.get_broker_cost("acc_kotak") is meta

    def test_cheapest_account_returns_zero_brokerage(self) -> None:
        free_meta = BrokerCostMetadata(broker_key="kotak", brokerage_frac=0.0)
        paid_meta = BrokerCostMetadata(broker_key="other", brokerage_frac=0.0003)
        cfg = MirrorConfig(
            broker_costs={"acc_free": free_meta, "acc_paid": paid_meta}
        )
        cheapest = cfg.cheapest_account(["acc_free", "acc_paid"])
        assert cheapest == "acc_free"

    def test_cheapest_account_no_metadata_returns_none(self) -> None:
        cfg = MirrorConfig()
        result = cfg.cheapest_account(["a1", "a2"])
        assert result is None

    def test_cheapest_account_single_candidate(self) -> None:
        meta = BrokerCostMetadata(broker_key="kotak")
        cfg = MirrorConfig(broker_costs={"sole": meta})
        assert cfg.cheapest_account(["sole"]) == "sole"

    def test_cheapest_account_ignores_accounts_without_metadata(self) -> None:
        meta = BrokerCostMetadata(broker_key="kotak", brokerage_frac=0.0)
        cfg = MirrorConfig(broker_costs={"with_meta": meta})
        # "no_meta" has no cost data so should be ignored
        cheapest = cfg.cheapest_account(["no_meta", "with_meta"])
        assert cheapest == "with_meta"

    def test_mirror_config_in_position_mirror(self) -> None:
        """MirrorConfig.broker_costs is accessible from PositionMirror."""
        meta = BrokerCostMetadata(broker_key="kotak")
        cfg = MirrorConfig(broker_costs={"acc1": meta})
        mirror = PositionMirror(mirror_config=cfg)
        assert mirror._mirror_config is cfg
        assert mirror._mirror_config.get_broker_cost("acc1") is meta

    def test_notes_field_stored(self) -> None:
        meta = BrokerCostMetadata(notes="test note")
        assert meta.notes == "test note"
