"""Tests for IntradayAllowList — configurable MIS blocked-scrips guard.

All tests are purely in-process; no broker/network calls.
"""

from __future__ import annotations



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _allow_list(blocked: set[str] | None = None):
    from flinttrade_engine.safety import IntradayAllowList
    return IntradayAllowList(blocked_scrips=blocked)


# ===========================================================================
# Default empty set — all symbols allowed
# ===========================================================================


class TestDefaultAllowAll:
    """Default (empty blocked set) behaviour."""

    def test_mis_allowed_by_default(self):
        allow = _allow_list()
        ok, reason = allow.is_allowed_intraday("RELIANCE", "NSE", "MIS")
        assert ok
        assert reason == ""

    def test_cnc_always_allowed_even_if_blocked(self):
        allow = _allow_list(blocked={"RELIANCE"})
        ok, reason = allow.is_allowed_intraday("RELIANCE", "NSE", "CNC")
        assert ok
        assert reason == ""

    def test_nrml_always_allowed_even_if_blocked(self):
        allow = _allow_list(blocked={"NIFTY25APRFUT"})
        ok, reason = allow.is_allowed_intraday("NIFTY25APRFUT", "NFO", "NRML")
        assert ok
        assert reason == ""


# ===========================================================================
# Blocked set behaviour
# ===========================================================================


class TestBlockedSet:
    """MIS blocked-set enforcement."""

    def test_blocked_mis_returns_false(self):
        allow = _allow_list(blocked={"SMEFOO"})
        ok, reason = allow.is_allowed_intraday("SMEFOO", "NSE", "MIS")
        assert not ok
        assert "SMEFOO" in reason

    def test_unblocked_symbol_is_allowed(self):
        allow = _allow_list(blocked={"SMEFOO"})
        ok, _ = allow.is_allowed_intraday("RELIANCE", "NSE", "MIS")
        assert ok

    def test_case_insensitive_symbol_match(self):
        allow = _allow_list(blocked={"ZZZTEST"})
        # lowercase input should still match
        ok, reason = allow.is_allowed_intraday("zzztest", "NSE", "MIS")
        assert not ok
        assert "zzztest" in reason.lower() or "ZZZTEST" in reason

    def test_case_insensitive_product(self):
        allow = _allow_list(blocked={"RELIANCE"})
        # Product "mis" (lowercase) should still block
        ok, _ = allow.is_allowed_intraday("RELIANCE", "NSE", "mis")
        assert not ok

    def test_initial_blocked_set_stored_uppercase(self):
        allow = _allow_list(blocked={"lowercase"})
        assert "LOWERCASE" in allow.BLOCKED_SCRIPS

    def test_multiple_blocked_symbols(self):
        allow = _allow_list(blocked={"A", "B", "C"})
        for sym in ("A", "B", "C"):
            ok, _ = allow.is_allowed_intraday(sym, "NSE", "MIS")
            assert not ok

        ok, _ = allow.is_allowed_intraday("D", "NSE", "MIS")
        assert ok


# ===========================================================================
# add / remove / update_blocked
# ===========================================================================


class TestMutation:
    """Dynamic blocked-set mutations."""

    def test_add_blocks_symbol(self):
        allow = _allow_list()
        allow.add("NEWSME")
        ok, _ = allow.is_allowed_intraday("NEWSME", "NSE", "MIS")
        assert not ok

    def test_add_is_case_insensitive(self):
        allow = _allow_list()
        allow.add("newsme")
        assert "NEWSME" in allow.BLOCKED_SCRIPS

    def test_remove_unblocks_symbol(self):
        allow = _allow_list(blocked={"NEWSME"})
        allow.remove("NEWSME")
        ok, _ = allow.is_allowed_intraday("NEWSME", "NSE", "MIS")
        assert ok

    def test_remove_noop_for_absent_symbol(self):
        allow = _allow_list()
        # Must not raise
        allow.remove("DOESNOTEXIST")

    def test_update_blocked_replaces_entire_set(self):
        allow = _allow_list(blocked={"OLD1", "OLD2"})
        allow.update_blocked({"NEW1", "NEW2", "NEW3"})
        assert not allow.is_blocked("OLD1")
        assert not allow.is_blocked("OLD2")
        assert allow.is_blocked("NEW1")
        assert allow.is_blocked("NEW3")

    def test_update_blocked_with_list(self):
        allow = _allow_list()
        allow.update_blocked(["X", "Y"])
        assert allow.is_blocked("X")
        assert allow.is_blocked("Y")


# ===========================================================================
# is_blocked convenience method
# ===========================================================================


class TestIsBlocked:
    def test_is_blocked_true(self):
        allow = _allow_list(blocked={"TATA"})
        assert allow.is_blocked("TATA")
        assert allow.is_blocked("tata")  # case insensitive

    def test_is_blocked_false(self):
        allow = _allow_list(blocked={"TATA"})
        assert not allow.is_blocked("RELIANCE")


# ===========================================================================
# Dunder helpers
# ===========================================================================


class TestDunders:
    def test_len_reflects_blocked_count(self):
        allow = _allow_list(blocked={"A", "B", "C"})
        assert len(allow) == 3

    def test_len_after_add(self):
        allow = _allow_list()
        assert len(allow) == 0
        allow.add("X")
        assert len(allow) == 1

    def test_repr(self):
        allow = _allow_list(blocked={"X", "Y"})
        r = repr(allow)
        assert "IntradayAllowList" in r
        assert "2" in r


# ===========================================================================
# WORKSPACE_KEY constant
# ===========================================================================


def test_workspace_key():
    from flinttrade_engine.safety import IntradayAllowList
    assert IntradayAllowList.WORKSPACE_KEY == "intraday_blocked_scrips"
