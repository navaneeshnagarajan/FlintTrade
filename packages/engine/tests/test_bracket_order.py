"""Tests for packages/engine/src/bracket_order.py.

No live OpenAlgo client required — all broker interactions are tested through
the no-client simulation path or with a lightweight mock.
"""

from __future__ import annotations




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _svc():
    """Return a BracketOrderService with no live client."""
    from packages.engine.src.bracket_order import BracketOrderService
    return BracketOrderService()


def _entry(
    symbol: str = "NIFTY25APRFUT",
    exchange: str = "NFO",
    action: str = "BUY",
    quantity: int = 50,
    price: float = 0,
) -> dict:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "quantity": quantity,
        "price": price,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Parameter validation rejects malformed inputs before any order is sent."""

    def test_missing_symbol_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "symbol": ""},
            stoploss=22000.0,
            target=22500.0,
        )
        assert not result.success
        assert "symbol" in result.error

    def test_invalid_action_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "action": "HOLD"},
            stoploss=22000.0,
            target=22500.0,
        )
        assert not result.success
        assert "BUY or SELL" in result.error

    def test_zero_quantity_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry={**_entry(), "quantity": 0},
            stoploss=22000.0,
            target=22500.0,
        )
        assert not result.success
        assert "quantity" in result.error

    def test_zero_stoploss_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(),
            stoploss=0.0,
            target=22500.0,
        )
        assert not result.success
        assert "stoploss" in result.error

    def test_zero_target_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(),
            stoploss=22000.0,
            target=0.0,
        )
        assert not result.success
        assert "target" in result.error

    def test_buy_sl_above_target_fails(self):
        """For a BUY entry the SL must be below the target."""
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(action="BUY"),
            stoploss=22600.0,  # above target → invalid
            target=22500.0,
        )
        assert not result.success
        assert "below target" in result.error

    def test_sell_sl_below_target_fails(self):
        """For a SELL entry the SL must be above the target."""
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(action="SELL"),
            stoploss=21900.0,  # below target → invalid
            target=22000.0,
        )
        assert not result.success
        assert "above target" in result.error

    def test_negative_trailing_sl_fails(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(),
            stoploss=22000.0,
            target=22500.0,
            trailing_sl=-10.0,
        )
        assert not result.success
        assert "trailing_sl" in result.error


# ---------------------------------------------------------------------------
# Placement (no-client simulation)
# ---------------------------------------------------------------------------


class TestPlaceBracket:
    """place_bracket without a live client uses simulated order IDs."""

    def test_success_returns_bracket(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        assert result.success
        assert result.bracket is not None

    def test_bracket_id_is_set(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        assert result.bracket.bracket_id  # non-empty UUID string

    def test_bracket_has_all_three_order_ids(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        b = result.bracket
        assert b.entry_order_id
        assert b.sl_order_id
        assert b.target_order_id

    def test_bracket_status_active_when_all_legs_placed(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        assert result.bracket.status == "active"

    def test_bracket_is_in_active_list(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        active = svc.get_active_brackets()
        bracket_ids = [b.bracket_id for b in active]
        assert result.bracket.bracket_id in bracket_ids

    def test_trailing_sl_stored_on_bracket(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0, trailing_sl=25.0
        )
        assert result.bracket.trailing_sl == 25.0

    def test_sell_entry_bracket(self):
        """SELL entry should produce BUY legs for SL and target."""
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(action="SELL"),
            stoploss=22600.0,
            target=22100.0,
        )
        assert result.success
        assert result.bracket.action == "SELL"


# ---------------------------------------------------------------------------
# Modify bracket
# ---------------------------------------------------------------------------


class TestModifyBracket:
    def test_modify_sl(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        result = svc.modify_bracket(bid, new_sl=21900.0)
        assert result.success
        assert result.bracket.stoploss == 21900.0

    def test_modify_target(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        result = svc.modify_bracket(bid, new_target=22700.0)
        assert result.success
        assert result.bracket.target == 22700.0

    def test_modify_unknown_bracket_fails(self):
        svc = _svc()
        result = svc.modify_bracket("nonexistent-id", new_sl=21000.0)
        assert not result.success
        assert "not found" in result.message.lower()

    def test_modify_cancelled_bracket_fails(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        svc.cancel_bracket(bid)
        result = svc.modify_bracket(bid, new_sl=21000.0)
        assert not result.success

    def test_modify_with_no_fields_fails(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        result = svc.modify_bracket(bid)
        assert not result.success


# ---------------------------------------------------------------------------
# Cancel bracket
# ---------------------------------------------------------------------------


class TestCancelBracket:
    def test_cancel_active_bracket(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        assert svc.cancel_bracket(bid)
        assert svc.get_bracket(bid).status == "cancelled"

    def test_cancelled_bracket_not_in_active_list(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        svc.cancel_bracket(bid)
        ids = [b.bracket_id for b in svc.get_active_brackets()]
        assert bid not in ids

    def test_cancel_unknown_bracket_returns_false(self):
        svc = _svc()
        assert not svc.cancel_bracket("does-not-exist")

    def test_cancel_already_cancelled_returns_false(self):
        svc = _svc()
        bid = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        ).bracket.bracket_id
        svc.cancel_bracket(bid)
        assert not svc.cancel_bracket(bid)


# ---------------------------------------------------------------------------
# to_dict serialisation
# ---------------------------------------------------------------------------


class TestBracketDict:
    def test_to_dict_has_required_keys(self):
        svc = _svc()
        result = svc.place_bracket(
            entry=_entry(), stoploss=22000.0, target=22500.0
        )
        d = result.bracket.to_dict()
        for key in (
            "bracket_id", "entry_order_id", "sl_order_id", "target_order_id",
            "symbol", "exchange", "action", "quantity",
            "entry_price", "stoploss", "target", "status",
            "created_at", "updated_at",
        ):
            assert key in d, f"Missing key: {key}"
