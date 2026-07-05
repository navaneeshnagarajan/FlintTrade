"""Tests for adapter.py — bootstrap, broker catalog, and loader."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]  # tests/ -> gateway/ -> integrations/ -> packages/ -> repo
# OpenAlgo is now an external test-dep cloned to .local/external/openalgo
# by scripts/setup-test-deps.sh — no longer a git submodule under infra/.
_OPENALGO_BROKER_DIR = _REPO_ROOT / ".local" / "external" / "openalgo" / "broker"

_OPENALGO_AVAILABLE = _OPENALGO_BROKER_DIR.is_dir() and any(
    _OPENALGO_BROKER_DIR.iterdir()
)


def _submodule_required(func):
    """Skip decorator when the openalgo external test-dep is not present."""
    return pytest.mark.skipif(
        not _OPENALGO_AVAILABLE,
        reason=".local/external/openalgo not present (run scripts/setup-test-deps.sh)",
    )(func)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from flinttrade_gateway.adapter import (  # noqa: E402 — kept below skip-helper definitions for readability
    BROKER_CATALOG,
    BrokerAdapter,
    _WrappedBrokerAdapter,
    _bootstrap_openalgo_imports,
    load_broker_adapter,
)
from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: E402 — see comment above
from flinttrade_gateway.models import BrokerInfo  # noqa: E402 — see comment above


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


class TestBrokerCatalog:
    """Verify the BROKER_CATALOG constants are consistent and complete."""

    def test_broker_catalog_has_31_non_sandbox_entries(self):
        """Exactly 32 live (non-sandbox) brokers must be in the catalog.

        31 track OpenAlgo upstream exactly (upstream gained ``iiflcapital`` in
        v2.0.1.1) plus 1 FlintTrade-native-only entry, ``kotakneo`` (Kotak Neo) —
        distinct from the upstream ``kotak`` (Kotak Securities). Groww remains an
        upstream OpenAlgo entry too, now with FlintTrade-native metadata attached.
        A future addition on either side trips this assertion.
        """
        live = [info for info in BROKER_CATALOG.values() if not info.is_sandbox]
        assert len(live) == 32, (
            f"Expected 32 live brokers, got {len(live)}: "
            f"{sorted(info.name for info in live)}"
        )
        # The one native-only (non-upstream) live entry.
        native_only = [info.name for info in live if info.name == "kotakneo"]
        assert native_only == ["kotakneo"]

    def test_broker_catalog_includes_iiflcapital(self):
        """iiflcapital must be present and distinct from iifl (added v2.0.1.1)."""
        assert "iiflcapital" in BROKER_CATALOG
        assert "iifl" in BROKER_CATALOG
        assert BROKER_CATALOG["iiflcapital"].name == "iiflcapital"
        assert BROKER_CATALOG["iifl"].name == "iifl"

    def test_broker_catalog_has_dhan_sandbox(self):
        """dhan_sandbox must be present and marked is_sandbox=True."""
        assert "dhan_sandbox" in BROKER_CATALOG
        entry = BROKER_CATALOG["dhan_sandbox"]
        assert entry.is_sandbox is True

    def test_all_entries_are_broker_info(self):
        """Every catalog value must be a BrokerInfo and key must match name."""
        for key, value in BROKER_CATALOG.items():
            assert isinstance(value, BrokerInfo), (
                f"Catalog entry '{key}' is {type(value)!r}, expected BrokerInfo"
            )
            assert value.name == key, (
                f"Key '{key}' does not match BrokerInfo.name '{value.name}'"
            )

    def test_catalog_total_size(self):
        """Total catalog entries must be exactly 33 (32 live + 1 sandbox).

        32 live = 31 OpenAlgo-upstream + 1 FlintTrade-native ``kotakneo``.
        """
        assert len(BROKER_CATALOG) == 33

    def test_zerodha_supports_new_exchanges(self):
        """Zerodha gained NCO, MCX_INDEX, GLOBAL_INDEX in OpenAlgo v2.0.0.7+."""
        zerodha = BROKER_CATALOG["zerodha"]
        for code in ("NCO", "MCX_INDEX", "GLOBAL_INDEX", "NSE_INDEX", "BSE_INDEX"):
            assert code in zerodha.exchanges, (
                f"Expected Zerodha to advertise {code} after v2.0.1.1 sync"
            )

    def test_upstox_supports_global_index(self):
        """Upstox added GLOBAL_INDEX (world feeds + USDINR / BRENT / WTI)."""
        assert "GLOBAL_INDEX" in BROKER_CATALOG["upstox"].exchanges

    def test_all_auth_flow_types_are_valid(self):
        """Every entry must have a recognised AuthFlowType."""
        from models import AuthFlowType

        valid = set(AuthFlowType)
        for key, info in BROKER_CATALOG.items():
            assert info.auth_flow in valid, (
                f"Broker '{key}' has invalid auth_flow '{info.auth_flow}'"
            )

    def test_every_entry_has_at_least_one_exchange(self):
        """No broker should have an empty exchange list."""
        for key, info in BROKER_CATALOG.items():
            assert len(info.exchanges) > 0, (
                f"Broker '{key}' has no exchanges configured"
            )

    def test_known_oauth_brokers(self):
        """Spot-check that key OAuth brokers have the correct flow type."""
        from models import AuthFlowType

        expected_oauth = ["zerodha", "fyers", "flattrade", "pocketful", "paytm", "dhan"]
        for name in expected_oauth:
            assert BROKER_CATALOG[name].auth_flow == AuthFlowType.oauth_redirect, (
                f"Expected {name} to be oauth_redirect"
            )

    def test_known_totp_brokers(self):
        """Spot-check that key TOTP brokers have the correct flow type."""
        from models import AuthFlowType

        expected_totp = ["angel", "fivepaisa", "zebu", "shoonya", "firstock", "tradejini"]
        for name in expected_totp:
            assert BROKER_CATALOG[name].auth_flow == AuthFlowType.totp_form, (
                f"Expected {name} to be totp_form"
            )

    def test_definedge_is_otp_sms(self):
        """definedge must use otp_sms flow."""
        from models import AuthFlowType

        assert BROKER_CATALOG["definedge"].auth_flow == AuthFlowType.otp_sms

    def test_samco_is_otp_multistep(self):
        """Samco must use otp_multistep — it has a 4-step OTP 2FA flow, not TOTP."""
        from models import AuthFlowType

        assert "samco" in BROKER_CATALOG
        entry = BROKER_CATALOG["samco"]
        assert entry.auth_flow == AuthFlowType.otp_multistep, (
            f"Expected samco to be otp_multistep, got {entry.auth_flow!r}. "
            "Samco uses a 4-step OTP flow: request OTP → submit OTP → "
            "generate access token → login."
        )

    def test_samco_aux_params_include_secret_api_key_and_ip_fields(self):
        """Samco catalog entry must declare its broker-specific aux_params."""
        entry = BROKER_CATALOG["samco"]
        assert "secret_api_key" in entry.aux_params
        assert "primary_ip" in entry.aux_params
        assert "secondary_ip" in entry.aux_params

    def test_samco_not_in_totp_brokers(self):
        """Samco must NOT be categorised as a totp_form broker."""
        from models import AuthFlowType

        entry = BROKER_CATALOG["samco"]
        assert entry.auth_flow != AuthFlowType.totp_form, (
            "Samco was incorrectly categorised as totp_form. "
            "It uses a multi-step OTP flow (otp_multistep)."
        )

    def test_known_api_key_direct_brokers(self):
        """Spot-check api_key_direct brokers."""
        from models import AuthFlowType

        expected_direct = ["deltaexchange", "groww", "wisdom", "ibulls", "iifl"]
        for name in expected_direct:
            assert BROKER_CATALOG[name].auth_flow == AuthFlowType.api_key_direct, (
                f"Expected {name} to be api_key_direct"
            )

    def test_groww_native_metadata_is_disabled_until_live_verification(self):
        entry = BROKER_CATALOG["groww"]
        assert entry.native is True
        assert entry.connectable is False
        assert entry.mcp is not None
        assert entry.mcp.remote_url == "https://mcp.groww.in/mcp"
        assert {m.id for m in entry.auth_methods} == {"api_key_totp", "api_key_secret", "access_token"}

    def test_kotakneo_catalogue_matches_native_segment_map_but_stays_disabled(self):
        """Kotak Neo metadata must expose every segment the native mapper supports."""
        from flinttrade_gateway.brokers.kotakneo_mapping import EXCHANGE_TO_KOTAK

        entry = BROKER_CATALOG["kotakneo"]
        assert entry.native is True
        assert entry.connectable is False
        assert set(EXCHANGE_TO_KOTAK) <= set(entry.exchanges)


# ---------------------------------------------------------------------------
# Bootstrap tests
# ---------------------------------------------------------------------------


class TestBootstrap:
    """Verify _bootstrap_openalgo_imports() behaviour."""

    def test_bootstrap_is_idempotent(self):
        """Calling bootstrap twice must not raise and must not corrupt shims."""
        _bootstrap_openalgo_imports()
        _bootstrap_openalgo_imports()  # second call is a no-op

        # Shims must still be registered correctly after double-call.
        assert "database.token_db" in sys.modules
        assert "database.auth_db" in sys.modules
        assert "utils.logging" in sys.modules
        assert "utils.config" in sys.modules

    def test_bootstrap_registers_shims(self):
        """After bootstrap, all four shim modules must be in sys.modules."""
        _bootstrap_openalgo_imports()

        shim_keys = ["database.token_db", "database.auth_db", "utils.logging", "utils.config"]
        for key in shim_keys:
            assert key in sys.modules, f"Shim '{key}' not in sys.modules after bootstrap"

    def test_bootstrap_adds_openalgo_to_sys_path(self):
        """After bootstrap, the openalgo root path must appear in sys.path."""
        from adapter import _OPENALGO_ROOT_STR

        _bootstrap_openalgo_imports()

        assert _OPENALGO_ROOT_STR in sys.path, (
            f"Expected '{_OPENALGO_ROOT_STR}' in sys.path after bootstrap"
        )


# ---------------------------------------------------------------------------
# _OPENALGO_ROOT path test
# ---------------------------------------------------------------------------


class TestOpenAlgoRootPath:
    """Verify the module-level path constants are correct."""

    def test_openalgo_root_path(self):
        """_OPENALGO_ROOT must point to the openalgo external test-dep root."""
        from adapter import _OPENALGO_ROOT

        assert _OPENALGO_ROOT.name == "openalgo"
        # openalgo lives under .local/external/openalgo; previously it was a
        # submodule at infra/openalgo. Adapter must resolve to whichever path
        # exists.
        assert _OPENALGO_ROOT.parent.name in {"external", "infra"}

        if not _OPENALGO_AVAILABLE:
            pytest.skip("openalgo external test-dep not available; skipping existence check")

        assert _OPENALGO_ROOT.is_dir(), f"Expected directory at {_OPENALGO_ROOT}"


# ---------------------------------------------------------------------------
# load_broker_adapter tests
# ---------------------------------------------------------------------------


class TestLoadBrokerAdapter:
    """Verify the adapter loader behaviour."""

    def test_load_broker_adapter_unknown_raises(self):
        """Loading an unknown broker must raise BrokerNotFoundError."""
        with pytest.raises(BrokerNotFoundError) as exc_info:
            load_broker_adapter("nonexistent")

        assert "nonexistent" in str(exc_info.value)

    def test_load_broker_adapter_unknown_error_message_contains_broker_name(self):
        """The error message must include the attempted broker name."""
        bad_name = "totally_fake_broker_xyz"
        with pytest.raises(BrokerNotFoundError) as exc_info:
            load_broker_adapter(bad_name)

        assert bad_name in str(exc_info.value)

    @_submodule_required
    @pytest.mark.skipif(
        not __import__("os").getenv("DATABASE_URL"),
        reason="DATABASE_URL not configured; OpenAlgo broker modules require a DB",
    )
    def test_load_broker_adapter_returns_wrapped_adapter(self):
        """Loading zerodha must return a _WrappedBrokerAdapter instance."""
        adapter = load_broker_adapter("zerodha")
        assert isinstance(adapter, _WrappedBrokerAdapter)
        assert adapter._broker == "zerodha"

    @_submodule_required
    @pytest.mark.skipif(
        not __import__("os").getenv("DATABASE_URL"),
        reason="DATABASE_URL not configured; OpenAlgo broker modules require a DB",
    )
    def test_loaded_adapter_satisfies_protocol(self):
        """The returned object must satisfy the BrokerAdapter Protocol."""
        adapter = load_broker_adapter("zerodha")
        assert isinstance(adapter, BrokerAdapter)


# ---------------------------------------------------------------------------
# Wrapped adapter read-contract compatibility
# ---------------------------------------------------------------------------


class _FakeAuth:
    def authenticate_broker(self, *args):
        return "token", None


class _FakeOrder:
    pass


class _FakeFunds:
    pass


class _FakeData:
    def __init__(self) -> None:
        self.history_calls: list[tuple[str, str, str, str, str, str]] = []
        self.option_chain_calls: list[tuple[str, str, str | None, str]] = []
        self.quote_calls: list[tuple[str, str, str]] = []

    def get_history(self, symbol: str, exchange: str, interval: str, start: str, end: str, token: str):
        self.history_calls.append((symbol, exchange, interval, start, end, token))
        return {"candles": []}

    def get_quotes(self, symbol: str, exchange: str, token: str):
        self.quote_calls.append((symbol, exchange, token))
        return {"symbol": symbol, "exchange": exchange, "ltp": 1.0}

    def get_depth(self, symbol: str, exchange: str, token: str):
        return {"symbol": symbol, "exchange": exchange, "bids": [], "asks": []}

    def get_option_chain(self, symbol: str, exchange: str, expiry: str | None, token: str):
        self.option_chain_calls.append((symbol, exchange, expiry, token))
        return {"underlying": symbol, "exchange": exchange, "strikes": []}

    def search_symbols(self, query: str, exchange: str, token: str):
        return {"query": query, "exchange": exchange, "token": token}


class TestWrappedAdapterReadContract:
    def test_get_history_accepts_registry_param_dict_contract(self):
        data = _FakeData()
        adapter = _WrappedBrokerAdapter("demo", _FakeAuth(), _FakeOrder(), data, _FakeFunds())

        result = adapter.get_history(
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "interval": "1d", "start": "2026-07-01",
             "end": "2026-07-04"},
            "TOKEN",
        )

        assert result == {"candles": []}
        assert data.history_calls == [("NIFTY", "NSE_INDEX", "1d", "2026-07-01", "2026-07-04", "TOKEN")]

    def test_get_option_chain_accepts_registry_param_dict_contract(self):
        data = _FakeData()
        adapter = _WrappedBrokerAdapter("demo", _FakeAuth(), _FakeOrder(), data, _FakeFunds())

        result = adapter.get_option_chain(
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": "2026-07-30"},
            "TOKEN",
        )

        assert result == {"underlying": "NIFTY", "exchange": "NSE_INDEX", "strikes": []}
        assert data.option_chain_calls == [("NIFTY", "NSE_INDEX", "2026-07-30", "TOKEN")]

    def test_get_quotes_accepts_session_symbol_list_contract(self):
        data = _FakeData()
        adapter = _WrappedBrokerAdapter("demo", _FakeAuth(), _FakeOrder(), data, _FakeFunds())

        result = adapter.get_quotes(["NSE:INFY"], "TOKEN")

        assert result == {"symbol": "INFY", "exchange": "NSE", "ltp": 1.0}
        assert data.quote_calls == [("INFY", "NSE", "TOKEN")]


# ---------------------------------------------------------------------------
# Parameterised: broker directory existence
# ---------------------------------------------------------------------------


def _all_broker_names() -> list[str]:
    return sorted(BROKER_CATALOG.keys())


@pytest.mark.parametrize("broker_name", _all_broker_names())
def test_broker_directory_exists(broker_name: str):
    """Each catalog entry must have a corresponding directory in OpenAlgo."""
    if not _OPENALGO_AVAILABLE:
        pytest.skip(".local/external/openalgo not present (run scripts/setup-test-deps.sh)")

    broker_dir = _OPENALGO_BROKER_DIR / broker_name
    assert broker_dir.is_dir(), (
        f"Expected broker directory at {broker_dir} for '{broker_name}'"
    )
