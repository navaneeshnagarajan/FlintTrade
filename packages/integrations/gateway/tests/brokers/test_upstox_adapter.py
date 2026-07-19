"""Adapter tests for the full Upstox parity surface (mock facade; no SDK).

The original v2 surface (login, gated trio happy path, portfolio reads, quotes,
history, option chain, margin) is covered by
``tests/brokers/test_upstox_adapter_base.py``; this file exercises everything added in the
parity wave: OAuth code login, broker-side logout, variety dispatch (AMO /
sliced / GTT) through the gated trio, the batch writes (multi-order,
cancel-all, exit-all, convert-position) and their router gating, the new reads
(order details/history, GTT book, trades-by-order, date-range trade history,
MTF positions, profile, brokerage, P&L reports, kill switch, v3 quotes,
option contracts, expiries, expired contracts/history, instrument search,
market information, feed authorisation) and the injected-feed tick stream.
"""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import BrokerError, OrderRejectedByBroker, SessionExpired
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.upstox import (
    _ROUTER_TOKEN,
    UpstoxAdapter,
    UpstoxClient,
    _facade_with_error_translation,
)
from flinttrade_gateway.brokers.upstox_mapping import UpstoxMappingError

pytestmark = pytest.mark.unit


class _StandInApiException(Exception):
    """ApiException-shaped stand-in (the upstox-python SDK is not installed)."""

    def __init__(self, status, body=None, reason=""):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.body = body
        self.headers = None


_StandInApiException.__name__ = "ApiException"  # match the SDK class name for duck-typing

_OK = {"status": "success"}


class MockUpstox:
    """Full-surface stand-in for the UpstoxClient facade (records every call)."""

    def __init__(self):
        self.calls: list[tuple] = []

    # -- auth --
    def logout(self):
        self.calls.append(("logout",))
        return {**_OK, "data": True}

    # -- orders: writes --
    def place_order(self, params):
        self.calls.append(("place", params))
        return {**_OK, "data": {"order_ids": ["UOID1"]}}

    def place_order_v3(self, params):
        self.calls.append(("place_v3", params))
        return {**_OK, "data": {"order_ids": ["UOID-V3-1", "UOID-V3-2"]}}

    def place_multi_order(self, payloads):
        self.calls.append(("multi_place", payloads))
        return {
            **_OK,
            "data": [{"order_id": "M1", "correlation_id": "1"}, {"order_id": "M2", "correlation_id": "2"}],
            "errors": [],
            "summary": {"total": 2, "success": 2},
        }

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {**_OK, "data": {"order_id": "UOID1"}}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {**_OK, "data": {"order_id": order_id}}

    def cancel_multi_order(self, tag=None, segment=None):
        self.calls.append(("cancel_multi", tag, segment))
        return {
            **_OK,
            "data": {"order_ids": ["C1", "C2"]},
            "errors": None,
            "summary": {"total": 2, "success": 2, "error": 0},
        }

    def exit_positions(self, tag=None, segment=None):
        self.calls.append(("exit_positions", tag, segment))
        return {
            **_OK,
            "data": {"order_ids": ["X1"]},
            "errors": None,
            "summary": {"total": 1, "success": 1, "error": 0},
        }

    # -- orders: GTT --
    def place_gtt_order(self, params):
        self.calls.append(("gtt_place", params))
        return {**_OK, "data": {"gtt_order_ids": ["GTT-CU100"]}}

    def modify_gtt_order(self, params):
        self.calls.append(("gtt_modify", params))
        return {**_OK, "data": {"gtt_order_ids": ["GTT-CU100"]}}

    def cancel_gtt_order(self, params):
        self.calls.append(("gtt_cancel", params))
        return {**_OK, "data": {"gtt_order_ids": ["GTT-CU100"]}}

    def gtt_order_details(self, gtt_order_id=None):
        self.calls.append(("gtt_details", gtt_order_id))
        if gtt_order_id is None:
            return {**_OK, "data": []}
        return {
            **_OK,
            "data": [
                {
                    "gtt_order_id": "GTT-CU100",
                    "type": "SINGLE",
                    "trading_symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "D",
                    "quantity": 1,
                    "rules": [
                        {
                            "strategy": "ENTRY",
                            "status": "PENDING",
                            "trigger_price": 2850.0,
                            "transaction_type": "BUY",
                            "order_id": None,
                        }
                    ],
                },
            ],
        }

    # -- orders: reads --
    def order_book(self):
        return {**_OK, "data": []}

    def order_details(self, order_id):
        self.calls.append(("order_details", order_id))
        return {
            **_OK,
            "data": {
                "order_id": order_id,
                "status": "complete",
                "trading_symbol": "TCS",
                "instrument_token": "NSE_EQ|INE467B01029",
                "transaction_type": "BUY",
                "order_type": "LIMIT",
                "product": "D",
                "quantity": 5,
                "price": 3500,
                "filled_quantity": 5,
                "average_price": 3499.5,
            },
        }

    def order_history(self, order_id=None, tag=None):
        self.calls.append(("order_history", order_id, tag))
        return {
            **_OK,
            "data": [
                {
                    "order_id": "1",
                    "status": "put order req received",
                    "trading_symbol": "TCS",
                    "instrument_token": "NSE_EQ|INE467B01029",
                    "transaction_type": "BUY",
                    "order_type": "LIMIT",
                    "product": "D",
                    "quantity": 5,
                    "price": 3500,
                },
                {
                    "order_id": "1",
                    "status": "complete",
                    "trading_symbol": "TCS",
                    "instrument_token": "NSE_EQ|INE467B01029",
                    "transaction_type": "BUY",
                    "order_type": "LIMIT",
                    "product": "D",
                    "quantity": 5,
                    "price": 3500,
                },
            ],
        }

    def trade_book(self):
        return {**_OK, "data": []}

    def trades_by_order(self, order_id):
        self.calls.append(("trades_by_order", order_id))
        return {
            **_OK,
            "data": [
                {
                    "order_id": order_id,
                    "trading_symbol": "TCS",
                    "instrument_token": "NSE_EQ|INE467B01029",
                    "transaction_type": "BUY",
                    "quantity": 5,
                    "average_price": 3499.5,
                    "product": "D",
                },
            ],
        }

    def trade_history(self, start_date, end_date, page_number, page_size, segment=None):
        self.calls.append(("trade_history", start_date, end_date, page_number, page_size, segment))
        return {
            **_OK,
            "data": [
                {
                    "trade_id": "T1",
                    "scrip_name": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "EQ",
                    "transaction_type": "BUY",
                    "quantity": 10,
                    "price": 2900.0,
                    "amount": 29000.0,
                    "trade_date": "2025-04-01",
                },
            ],
        }

    # -- portfolio --
    def positions(self):
        return {**_OK, "data": []}

    def mtf_positions(self):
        self.calls.append(("mtf_positions",))
        return {
            **_OK,
            "data": [
                {
                    "trading_symbol": "SBIN",
                    "instrument_token": "NSE_EQ|INE062A01020",
                    "product": "MTF",
                    "quantity": 100,
                    "average_price": 600.0,
                    "last_price": 612.0,
                    "pnl": 1200.0,
                },
            ],
        }

    def convert_position(self, params):
        self.calls.append(("convert", params))
        return {**_OK, "data": {"status": "complete"}}

    def holdings(self):
        return {**_OK, "data": []}

    # -- user / funds / charges --
    def funds(self):
        return {**_OK, "data": {"equity": {"available_margin": 50000, "used_margin": 12000}}}

    def profile(self):
        self.calls.append(("profile",))
        return {
            **_OK,
            "data": {
                "user_id": "AB1234",
                "user_name": "N",
                "email": "n@x.in",
                "broker": "UPSTOX",
                "exchanges": ["NSE"],
                "products": ["D", "I"],
                "order_types": ["LIMIT"],
                "is_active": True,
                "poa": False,
            },
        }

    def kill_switch_status(self):
        self.calls.append(("kill_status",))
        return {**_OK, "data": {"kill_switch_status": "DEACTIVATED"}}

    def update_kill_switch(self, body):
        self.calls.append(("kill_update", body))
        return {**_OK, "data": {"kill_switch_status": body["action"]}}

    def brokerage(self, instrument_token, quantity, product, transaction_type, price):
        self.calls.append(("brokerage", instrument_token, quantity, product, transaction_type, price))
        return {
            **_OK,
            "data": {"charges": {"total": 104.05, "brokerage": 20.0, "taxes": {"gst": 3.6}, "other_taxes": {}}},
        }

    def margin(self, instruments):
        self.calls.append(("margin", instruments))
        return {**_OK, "data": {"required_margin": 14500, "final_margin": 14000}}

    # -- reports --
    def pnl_report(self, segment, financial_year, page_number, page_size):
        self.calls.append(("pnl_report", segment, financial_year, page_number, page_size))
        return {
            **_OK,
            "data": [
                {"scrip_name": "INFY", "quantity": 10, "buy_amount": 15000.0, "sell_amount": 15500.0},
            ],
        }

    def pnl_charges(self, segment, financial_year):
        self.calls.append(("pnl_charges", segment, financial_year))
        return {**_OK, "data": {"charges_breakdown": {"total": 350.5, "brokerage": 120.0}}}

    # -- market data --
    def full_quote(self, instrument_keys):
        self.calls.append(("full_quote", instrument_keys))
        return {
            **_OK,
            "data": {
                "NSE_EQ:RELIANCE": {
                    "symbol": "RELIANCE",
                    "instrument_token": "NSE_EQ|INE002A01018",
                    "last_price": 2905.5,
                    "ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2899},
                    "depth": {
                        "buy": [{"price": 2905.0, "quantity": 10, "orders": 2}],
                        "sell": [{"price": 2906.0, "quantity": 8, "orders": 1}],
                    },
                }
            },
        }

    def ohlc_quote_v3(self, instrument_keys, interval):
        self.calls.append(("ohlc_v3", instrument_keys, interval))
        return {
            **_OK,
            "data": {
                "NSE_EQ:RELIANCE": {
                    "last_price": 2905.5,
                    "instrument_token": "NSE_EQ|INE002A01018",
                    "live_ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2905, "volume": 12000},
                    "prev_ohlc": {"close": 2899},
                }
            },
        }

    def ltp_quote_v3(self, instrument_keys):
        self.calls.append(("ltp_v3", instrument_keys))
        return {
            **_OK,
            "data": {
                "NSE_EQ:RELIANCE": {
                    "last_price": 2905.5,
                    "instrument_token": "NSE_EQ|INE002A01018",
                    "volume": 99,
                    "cp": 2899.0,
                }
            },
        }

    def option_greeks_v3(self, instrument_keys):
        self.calls.append(("greeks_v3", instrument_keys))
        return {
            **_OK,
            "data": {
                "NSE_FO|54452": {
                    "last_price": 120.5,
                    "instrument_token": "NSE_FO|54452",
                    "iv": 13.2,
                    "delta": 0.55,
                    "gamma": 0.002,
                    "theta": -8.1,
                    "vega": 6.4,
                    "oi": 30000,
                    "volume": 5000,
                }
            },
        }

    def historical(self, instrument_key, unit, interval, to_date, from_date):
        self.calls.append(("historical", (instrument_key, unit, interval, to_date, from_date)))
        return {**_OK, "data": {"candles": [["2025-01-02T00:00:00+05:30", 100, 110, 95, 105, 1500, 0]]}}

    def intra_day(self, instrument_key, unit, interval):
        self.calls.append(("intra_day", (instrument_key, unit, interval)))
        return {**_OK, "data": {"candles": [["2025-01-02T09:15:00+05:30", 100, 110, 95, 105, 1500, 0]]}}

    def expired_history(self, expired_instrument_key, interval, to_date, from_date):
        self.calls.append(("expired_history", (expired_instrument_key, interval, to_date, from_date)))
        return {**_OK, "data": {"candles": [["2024-06-27T00:00:00+05:30", 50, 55, 48, 52, 900, 100]]}}

    def expiries(self, instrument_key):
        self.calls.append(("expiries", instrument_key))
        return {**_OK, "data": ["2025-06-26", "2025-07-03"]}

    def expired_future_contracts(self, instrument_key, expiry_date):
        self.calls.append(("expired_futures", instrument_key, expiry_date))
        return {**_OK, "data": [{"instrument_key": "NSE_FO|FUT1|expired", "trading_symbol": "NIFTY FUT"}]}

    def expired_option_contracts(self, instrument_key, expiry_date):
        self.calls.append(("expired_options", instrument_key, expiry_date))
        return {**_OK, "data": [{"instrument_key": "NSE_FO|OPT1|expired", "trading_symbol": "NIFTY CE"}]}

    def option_chain(self, instrument_key, expiry_date):
        return {**_OK, "data": []}

    def option_contracts(self, instrument_key, expiry_date=None):
        self.calls.append(("option_contracts", instrument_key, expiry_date))
        return {
            **_OK,
            "data": [
                {
                    "instrument_key": "NSE_FO|54452",
                    "trading_symbol": "NIFTY 24600 CE",
                    "strike_price": 24600,
                    "lot_size": 75,
                }
            ],
        }

    def search_instruments(self, query, *, page_number=1, records=30):
        self.calls.append(("search", query))
        assert page_number == 1
        assert records == 30
        return {
            **_OK,
            "data": [{"instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE"}],
            "meta_data": {
                "page": {"page_number": 1, "records": 30, "total_records": 1, "total_pages": 1}
            },
        }

    # -- market information --
    def exchange_timings(self, date):
        self.calls.append(("timings", date))
        return {**_OK, "data": [{"exchange": "NSE", "start_time": 1, "end_time": 2}]}

    def market_holidays(self, date=None):
        self.calls.append(("holidays", date))
        return {
            **_OK,
            "data": [
                {
                    "date": "2025-08-15",
                    "description": "Independence Day",
                    "holiday_type": "SPECIAL_SESSION",
                    "closed_exchanges": ["NSE"],
                    "open_exchanges": [{"exchange": "NSE", "start_time": 1755246600000, "end_time": 1755250200000}],
                }
            ],
        }

    def market_status(self, exchange):
        self.calls.append(("status", exchange))
        return {**_OK, "data": {"exchange": exchange, "status": "NORMAL_OPEN"}}

    # -- streaming --
    def market_feed_authorize(self):
        self.calls.append(("feed_auth",))
        return {**_OK, "data": {"authorized_redirect_uri": "wss://feed.upstox/market?t=1"}}

    def portfolio_feed_authorize(self, order_update=True, position_update=False, holding_update=False):
        self.calls.append(("portfolio_auth", order_update, position_update, holding_update))
        return {**_OK, "data": {"authorized_redirect_uri": "wss://feed.upstox/portfolio?t=1"}}


def _adapter(mock, **kw):
    return UpstoxAdapter(
        client_factory=lambda _s: mock,
        instrument_resolver=lambda _symbol, exchange: {
            "NFO": "NSE_FO|54452",
            "NSE_INDEX": "NSE_INDEX|Nifty 50",
        }.get(exchange, "NSE_EQ|INE002A01018"),
        **kw,
    )


async def _session(adapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


def _order(**kw) -> Order:
    base = dict(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="2900"
    )
    base.update(kw)
    return Order(**base)


def _gtt_changes(**overrides):
    changes = {
        "type": "SINGLE",
        "quantity": 2,
        "trigger_price": 2860,
        "entry_trigger_type": "ABOVE",
        "stop_loss_price": 0,
        "stop_loss_trailing_gap": 0,
        "target_price": 0,
        "stop_loss_trigger_type": "IMMEDIATE",
        "target_trigger_type": "IMMEDIATE",
    }
    changes.update(overrides)
    return changes


def test_facade_funds_uses_v3_sdk_method_without_v2_version_argument():
    class _Response:
        def to_dict(self):
            return {"status": "success", "data": {"available_to_trade": {"total": 1}}}

    class _UserApi:
        def __init__(self):
            self.calls = 0

        def get_user_fund_margin_v3(self):
            self.calls += 1
            return _Response()

        def get_user_fund_margin(self, _version):
            raise AssertionError("v2 funds retrieval must not be used")

    facade = object.__new__(UpstoxClient)
    facade._user = _UserApi()

    assert facade.funds()["status"] == "success"
    assert facade._user.calls == 1


def _run_emergency_dispatch(mock, **dispatcher_kwargs):
    import asyncio
    from datetime import datetime, timezone

    from flinttrade_engine.request_context import RequestContext
    from flinttrade_engine.safety import (
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
        L5_EMERGENCY_POLICY,
        SafetyGate,
        set_safety_gate_secret,
    )
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.router import BrokerRouter

    adapter = _adapter(mock)
    session = Session(
        access_token="TOK",
        expires_at=datetime.now(timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="upstox",
        extra={"client": mock},
    )
    gate = SafetyGate()
    consumed_gate_ids: list[str] = []

    def consume(gate_id: str) -> bool:
        consumed_gate_ids.append(gate_id)
        return gate.consume(gate_id)

    set_safety_gate_secret(b"upstox-planned-emergency-secret-0123456789")
    router = BrokerRouter(
        {"upstox": adapter},
        lambda _request_ctx, _adapter_id, _account_id: session,
        consume_gate=consume,
    )
    request_ctx = RequestContext(
        jti="upstox-planned-emergency",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="upstox:acct-1",
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: EmergencyBrokerTarget(
            request_ctx=request_ctx,
            adapter_id="upstox",
            account_id="acct-1",
        ),
        run_awaitable=asyncio.run,
        **dispatcher_kwargs,
    )
    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="Upstox emergency")
    return result, consumed_gate_ids


# ---------------------------------------------------------------------------
# Auth: OAuth code login, login URL, logout
# ---------------------------------------------------------------------------


def test_build_login_url_static():
    url = UpstoxAdapter.build_login_url("K1", "https://app.local/cb", "s1")
    assert url.startswith("https://api.upstox.com/v2/login/authorization/dialog?")
    assert "client_id=K1" in url and "state=s1" in url


@pytest.mark.asyncio
async def test_login_exchanges_oauth_code_for_token():
    seen: list[dict] = []

    def exchanger(params):
        seen.append(params)
        return {"access_token": "FRESH-TOK", "token_type": "Bearer"}

    adapter = _adapter(MockUpstox(), token_exchanger=exchanger)
    session = await adapter.login(
        {
            "client_id": "C1",
            "code": "mk404x",
            "api_key": "K1",
            "api_secret": "S1",
            "redirect_uri": "https://app.local/cb",
        }
    )
    assert session.access_token == "FRESH-TOK"
    assert seen[0]["grant_type"] == "authorization_code" and seen[0]["code"] == "mk404x"


@pytest.mark.asyncio
async def test_login_without_token_or_code_raises():
    with pytest.raises(BrokerError, match="access_token"):
        await UpstoxAdapter().login({"client_id": "C1"})


@pytest.mark.asyncio
async def test_logout_calls_broker_and_clears_client():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.logout(session)
    assert ("logout",) in mock.calls
    assert "client" not in session.extra
    # Idempotent: a second logout must not raise.
    await adapter.logout(session)


# ---------------------------------------------------------------------------
# Gated trio: variety dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_order_amo_variety_flags_after_market():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    oid = await adapter.place_order(session, _order(variety="amo"), _router_token=_ROUTER_TOKEN)
    assert oid == "UOID1"
    kind, params = mock.calls[0]
    assert kind == "place" and params["is_amo"] is True


@pytest.mark.asyncio
async def test_place_order_iceberg_routes_to_v3_slice():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    oid = await adapter.place_order(session, _order(variety="iceberg", quantity="50000"), _router_token=_ROUTER_TOKEN)
    assert oid == "UOID-V3-1"  # first sliced leg id
    kind, params = mock.calls[0]
    assert kind == "place_v3" and params["slice"] is True and params["quantity"] == 50000


@pytest.mark.asyncio
async def test_place_order_gtt_routes_to_gtt_endpoint():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = _order(variety="gtt", product="CNC", trigger_price="2850", stop_loss_price="2800", target_price="2950")
    oid = await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert oid == "GTT-CU100"
    kind, params = mock.calls[0]
    assert kind == "gtt_place" and params["type"] == "MULTIPLE"
    assert [r["strategy"] for r in params["rules"]] == ["ENTRY", "STOPLOSS", "TARGET"]


@pytest.mark.asyncio
async def test_place_order_bracket_still_refused_through_gate():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(UpstoxMappingError, match="variety"):
        await adapter.place_order(
            session, _order(variety="bracket", stop_loss_price="2870"), _router_token=_ROUTER_TOKEN
        )
    assert mock.calls == []


@pytest.mark.asyncio
async def test_modify_order_dispatches_gtt_by_id_and_by_changes_flag():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(
        session, "GTT-CU100", _gtt_changes(), _router_token=_ROUTER_TOKEN
    )
    kind, params = mock.calls[0]
    assert kind == "gtt_modify" and params["gtt_order_id"] == "GTT-CU100"
    assert params["rules"][0]["trigger_price"] == 2860.0

    mock.calls.clear()
    await adapter.modify_order(
        session,
        "GTT-CU101",
        _gtt_changes(variety="gtt", quantity=3, trigger_price=2870),
        _router_token=_ROUTER_TOKEN,
    )
    assert mock.calls[0][0] == "gtt_modify"

    mock.calls.clear()
    await adapter.modify_order(session, "240221025997024", {"quantity": 4, "price": 2950}, _router_token=_ROUTER_TOKEN)
    assert mock.calls[0][0] == "modify"


@pytest.mark.asyncio
async def test_cancel_order_dispatches_gtt_by_id_prefix():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.cancel_order(session, "GTT-CU100", _router_token=_ROUTER_TOKEN)
    assert mock.calls[0] == ("gtt_cancel", {"gtt_order_id": "GTT-CU100"})
    await adapter.cancel_order(session, "240221025997024", _router_token=_ROUTER_TOKEN)
    assert mock.calls[1] == ("cancel", "240221025997024")


@pytest.mark.asyncio
async def test_forever_order_writes_require_router_token():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    with pytest.raises(SafetyBypassError):
        await adapter.modify_forever(session, "GTT-CU100", {"quantity": 2, "trigger_price": 2860})
    with pytest.raises(SafetyBypassError):
        await adapter.cancel_forever(session, "GTT-CU100")

    assert mock.calls == []


@pytest.mark.asyncio
async def test_modify_forever_sends_full_replacement_gtt_payload():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    await adapter.modify_forever(
        session,
        "GTT-CU100",
        {
            "type": "MULTIPLE",
            "quantity": 2,
            "trigger_price": 2860,
            "entry_trigger_type": "BELOW",
            "stop_loss_price": 2800,
            "stop_loss_trailing_gap": 0,
            "target_price": 2950,
            "stop_loss_trigger_type": "IMMEDIATE",
            "target_trigger_type": "IMMEDIATE",
        },
        _router_token=_ROUTER_TOKEN,
    )

    assert mock.calls == [
        (
            "gtt_modify",
            {
                "type": "MULTIPLE",
                "quantity": 2,
                "rules": [
                    {"strategy": "ENTRY", "trigger_type": "BELOW", "trigger_price": 2860.0},
                    {"strategy": "STOPLOSS", "trigger_type": "IMMEDIATE", "trigger_price": 2800.0},
                    {"strategy": "TARGET", "trigger_type": "IMMEDIATE", "trigger_price": 2950.0},
                ],
                "gtt_order_id": "GTT-CU100",
            },
        )
    ]


@pytest.mark.asyncio
async def test_cancel_forever_sends_exact_gtt_payload():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    await adapter.cancel_forever(session, "GTT-CU100", _router_token=_ROUTER_TOKEN)

    assert mock.calls == [("gtt_cancel", {"gtt_order_id": "GTT-CU100"})]


# ---------------------------------------------------------------------------
# Batch writes: multi-order / cancel-all / exit-all / convert — all gated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_place_multi_order_builds_batch_and_returns_ids():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.place_multi_order(
        session, [_order(), _order(action="SELL", quantity="5")], _router_token=_ROUTER_TOKEN
    )
    assert out["order_ids"] == ["M1", "M2"] and out["success"] == 2
    kind, payloads = mock.calls[0]
    assert kind == "multi_place" and [p["correlation_id"] for p in payloads] == ["1", "2"]


@pytest.mark.asyncio
async def test_cancel_all_orders_passes_tag_and_segment():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.cancel_all_orders(session, tag="ALGO1", segment="EQ", _router_token=_ROUTER_TOKEN)
    assert out["order_ids"] == ["C1", "C2"]
    assert mock.calls[0] == ("cancel_multi", "ALGO1", "EQ")


@pytest.mark.asyncio
async def test_exit_all_positions_sweeps():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.exit_all_positions(session, _router_token=_ROUTER_TOKEN)
    assert out["order_ids"] == ["X1"] and out["success"] == 1
    assert mock.calls[0] == ("exit_positions", None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["cancel_all_orders", "exit_all_positions"])
@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "message": "broker refused sweep"},
        {"status": "success", "data": {}, "summary": {"total": 0, "success": 0, "error": 0}},
        {
            "status": "success",
            "data": {"order_ids": [" PADDED "]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["DUP", "DUP"]},
            "summary": {"total": 2, "success": 2, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["CONTROL\x00"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C\u0301"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
    ],
)
async def test_emergency_sweep_adapter_rejects_non_success_or_invalid_envelope(verb, response):
    class InvalidSweepUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "OPEN-1",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                ],
            }

        def cancel_multi_order(self, tag=None, segment=None):
            self.calls.append(("cancel_multi", tag, segment))
            return response

        def exit_positions(self, tag=None, segment=None):
            self.calls.append(("exit_positions", tag, segment))
            return response

    adapter = _adapter(InvalidSweepUpstox())
    session = await _session(adapter)

    with pytest.raises(UpstoxMappingError, match="cancel/exit"):
        await getattr(adapter, verb)(session, _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_emergency_planner_cancels_active_gtt_through_gated_cancel_contract():
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class ActiveGttUpstox(MockUpstox):
        def gtt_order_details(self, gtt_order_id=None):
            self.calls.append(("gtt_details", gtt_order_id))
            return {
                **_OK,
                "data": [
                    {
                        "gtt_order_id": "GTT-EMERGENCY-1",
                        "type": "SINGLE",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "product": "D",
                        "quantity": 1,
                        "rules": [
                            {
                                "strategy": "ENTRY",
                                "status": "PENDING",
                                "trigger_price": 2850,
                                "transaction_type": "BUY",
                                "order_id": None,
                            }
                        ],
                    }
                ],
            }

    mock = ActiveGttUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert len(plan.writes) == 1
    write = plan.writes[0]
    assert write.parent_verb == "cancel_all_orders"
    assert write.verb == "cancel_order"
    assert write.payload == {"_op": "cancel_order", "order_id": "GTT-EMERGENCY-1"}

    with pytest.raises(SafetyBypassError, match="outside BrokerRouter"):
        await adapter.cancel_order(session, write.payload["order_id"])
    assert not any(call[0] == "gtt_cancel" for call in mock.calls)

    await adapter.cancel_order(session, write.payload["order_id"], _router_token=_ROUTER_TOKEN)
    assert mock.calls[-1] == ("gtt_cancel", {"gtt_order_id": "GTT-EMERGENCY-1"})


@pytest.mark.asyncio
async def test_emergency_planner_keeps_visible_protected_order_pending_without_replay():
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class StaleCancelledOrderUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "ACKNOWLEDGED-CANCEL-1",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                ],
            }

    adapter = _adapter(StaleCancelledOrderUpstox())
    session = await _session(adapter)

    plan = await adapter.plan_emergency_reduction(
        session,
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset({"ACKNOWLEDGED-CANCEL-1"}),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_emergency_planner_rejects_regular_and_gtt_id_overlap():
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class CollidingOrderBooksUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "GTT-COLLISION",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                ],
            }

        def gtt_order_details(self, gtt_order_id=None):
            return {
                **_OK,
                "data": [
                    {
                        "gtt_order_id": "GTT-COLLISION",
                        "type": "SINGLE",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "product": "D",
                        "quantity": 1,
                        "rules": [],
                    }
                ],
            }

    adapter = _adapter(CollidingOrderBooksUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="overlapping ids"):
        await adapter.plan_emergency_reduction(
            session,
            policy=L5_EMERGENCY_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_source", ["order book", "GTT order book", "position book"])
async def test_emergency_planner_rejects_malformed_success_snapshot(malformed_source):
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class MalformedSnapshotUpstox(MockUpstox):
        def order_book(self):
            if malformed_source == "order book":
                return {**_OK, "data": None}
            return {**_OK, "data": []}

        def gtt_order_details(self, gtt_order_id=None):
            self.calls.append(("gtt_details", gtt_order_id))
            if malformed_source == "GTT order book":
                return {**_OK, "data": None}
            return {**_OK, "data": []}

        def positions(self):
            if malformed_source == "position book":
                return {**_OK, "data": None}
            return {**_OK, "data": []}

    adapter = _adapter(MalformedSnapshotUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match=f"emergency {malformed_source} response is malformed"):
        await adapter.plan_emergency_reduction(
            session,
            policy=L5_EMERGENCY_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "message": "broker refused sweep"},
        {"status": "success", "data": {}, "summary": {"total": 0, "success": 0, "error": 0}},
        {
            "status": "success",
            "data": {"order_ids": [" PADDED "]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["DUP", "DUP"]},
            "summary": {"total": 2, "success": 2, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["CONTROL\u200b"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C\u0301"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
    ],
)
def test_emergency_dispatcher_marks_invalid_upstox_sweep_failed(response):
    import asyncio
    from datetime import datetime, timezone

    from flinttrade_engine.request_context import RequestContext
    from flinttrade_engine.safety import (
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
        L5_EMERGENCY_POLICY,
        SafetyGate,
        set_safety_gate_secret,
    )
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.router import BrokerRouter

    class InvalidSweepUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "OPEN-1",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                ],
            }

        def cancel_multi_order(self, tag=None, segment=None):
            self.calls.append(("cancel_multi", tag, segment))
            return response

        def exit_positions(self, tag=None, segment=None):
            self.calls.append(("exit_positions", tag, segment))
            return response

    mock = InvalidSweepUpstox()
    adapter = _adapter(mock)
    session = Session(
        access_token="TOK",
        expires_at=datetime.now(timezone.utc).timestamp() + 3600,
        account_id="acct-1",
        adapter_id="upstox",
    )
    safety_gate = SafetyGate()
    set_safety_gate_secret(b"upstox-emergency-test-secret-0123456789")
    router = BrokerRouter(
        {"upstox": adapter},
        lambda _request_ctx, _adapter_id, _account_id: session,
        consume_gate=safety_gate.consume,
    )
    request_ctx = RequestContext(
        jti="emergency-jti",
        actor_type="human",
        actor_id="operator",
        mode="live",
        selector="upstox:acct-1",
    )
    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: router,
        target_provider=lambda: EmergencyBrokerTarget(
            request_ctx=request_ctx,
            adapter_id="upstox",
            account_id="acct-1",
        ),
        run_awaitable=asyncio.run,
    )

    result = dispatcher.dispatch(L5_EMERGENCY_POLICY, reason="test malformed response")

    assert result.complete is False
    assert [outcome.failure_code for outcome in result.outcomes] == [
        "dispatch_failed",
        "",
    ]
    assert mock.calls == [
        ("gtt_details", None),
        ("cancel_multi", None, None),
        ("gtt_details", None),
    ]


def test_emergency_cancel_enumerates_over_ten_and_gates_each_reducing_chunk():
    class OverLimitOrdersUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.open_order_ids = [f"OID-{index:02d}" for index in range(12)]

        def order_book(self):
            self.calls.append(("order_book", tuple(self.open_order_ids)))
            return {
                **_OK,
                "data": [
                    {
                        "order_id": order_id,
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                    for order_id in self.open_order_ids
                ],
            }

        def positions(self):
            self.calls.append(("positions",))
            return {**_OK, "data": []}

        def cancel_order(self, order_id):
            self.calls.append(("cancel", order_id))
            self.open_order_ids.remove(order_id)
            return {**_OK, "data": {"order_id": order_id}}

        def cancel_multi_order(self, tag=None, segment=None):
            assert len(self.open_order_ids) <= 10
            cancelled = list(self.open_order_ids)
            self.calls.append(("cancel_multi", tuple(cancelled)))
            self.open_order_ids.clear()
            return {
                **_OK,
                "data": {"order_ids": cancelled},
                "errors": None,
                "summary": {"total": len(cancelled), "success": len(cancelled), "error": 0},
            }

    mock = OverLimitOrdersUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    mutations = [call for call in mock.calls if call[0] in {"cancel", "cancel_multi", "exit_positions", "place"}]
    assert result.complete
    assert mutations == [
        ("cancel", "OID-00"),
        ("cancel", "OID-01"),
        ("cancel_multi", tuple(f"OID-{index:02d}" for index in range(2, 12))),
    ]
    assert len(consumed_gate_ids) == len(set(consumed_gate_ids)) == len(mutations)


def test_emergency_exit_gates_each_of_over_ten_positions_exactly():
    class OverLimitPositionsUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.completed_orders: list[dict[str, object]] = []
            self.open_positions = [
                {
                    "trading_symbol": f"SYMBOL{index:02d}",
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                    "product": "I",
                    "quantity": index + 1,
                }
                for index in range(12)
            ]

        def order_book(self):
            self.calls.append(("order_book",))
            return {**_OK, "data": list(self.completed_orders)}

        def positions(self):
            self.calls.append(("positions", len(self.open_positions)))
            return {**_OK, "data": list(self.open_positions)}

        def place_order(self, params):
            self.calls.append(("place", params))
            closed = self.open_positions.pop(0)
            assert params["transaction_type"] == "SELL"
            assert params["quantity"] == closed["quantity"]
            order_id = f"EXIT-{closed['trading_symbol']}"
            self.completed_orders.append(
                {
                    "order_id": order_id,
                    "status": "complete",
                    "tag": params["tag"],
                    "trading_symbol": closed["trading_symbol"],
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                    "transaction_type": "SELL",
                    "order_type": "MARKET",
                    "product": "I",
                    "quantity": closed["quantity"],
                    "filled_quantity": closed["quantity"],
                }
            )
            return {**_OK, "data": {"order_ids": [order_id]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("every Upstox emergency exit must be exact and tagged")

    mock = OverLimitPositionsUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    mutations = [call for call in mock.calls if call[0] in {"place", "exit_positions"}]
    assert result.complete
    assert [call[0] for call in mutations] == ["place"] * 12
    assert len(consumed_gate_ids) == len(set(consumed_gate_ids)) == len(mutations)


def test_emergency_delivery_eq_uses_one_strictly_reducing_gated_opposite_order():
    class DeliveryPositionUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.quantity = 5
            self.completed_order: dict[str, object] | None = None

        def order_book(self):
            self.calls.append(("order_book",))
            return {**_OK, "data": [self.completed_order] if self.completed_order else []}

        def positions(self):
            self.calls.append(("positions", self.quantity))
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                    }
                ],
            }

        def place_order(self, params):
            self.calls.append(("place", params))
            assert params["transaction_type"] == "SELL"
            assert params["order_type"] == "MARKET"
            assert params["product"] == "D"
            assert params["quantity"] == 5
            self.completed_order = {
                "order_id": "EXIT-DELIVERY-1",
                "status": "complete",
                "tag": params["tag"],
                "trading_symbol": "RELIANCE",
                "exchange": "NSE",
                "segment": "NSE_EQ",
                "transaction_type": "SELL",
                "order_type": "MARKET",
                "product": "D",
                "quantity": 5,
                "filled_quantity": 5,
            }
            self.quantity = 0
            return {**_OK, "data": {"order_ids": ["EXIT-DELIVERY-1"]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must not use Upstox exit-all")

    mock = DeliveryPositionUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    mutations = [call for call in mock.calls if call[0] == "place"]
    assert result.complete
    assert len(mutations) == 1
    assert len(consumed_gate_ids) == len(set(consumed_gate_ids)) == 1


def test_emergency_readback_restarts_quiet_window_when_order_reopens():
    class ReopeningOrderUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.open_order_ids = ["OID-INITIAL"]
            self.empty_reads = 0
            self.reopened = False

        def order_book(self):
            if not self.open_order_ids:
                self.empty_reads += 1
                if self.empty_reads == 2 and not self.reopened:
                    self.open_order_ids.append("OID-REOPENED")
                    self.reopened = True
            self.calls.append(("order_book", tuple(self.open_order_ids)))
            return {
                **_OK,
                "data": [
                    {
                        "order_id": order_id,
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "transaction_type": "BUY",
                        "order_type": "LIMIT",
                        "product": "I",
                        "quantity": 1,
                    }
                    for order_id in self.open_order_ids
                ],
            }

        def positions(self):
            return {**_OK, "data": []}

        def cancel_multi_order(self, tag=None, segment=None):
            cancelled = list(self.open_order_ids)
            self.calls.append(("cancel_multi", tuple(cancelled)))
            self.open_order_ids.clear()
            return {
                **_OK,
                "data": {"order_ids": cancelled},
                "errors": None,
                "summary": {"total": len(cancelled), "success": len(cancelled), "error": 0},
            }

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("No position mutation is needed")

    mock = ReopeningOrderUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    cancel_calls = [call for call in mock.calls if call[0] == "cancel_multi"]
    assert result.complete
    assert mock.reopened is True
    assert cancel_calls == [
        ("cancel_multi", ("OID-INITIAL",)),
        ("cancel_multi", ("OID-REOPENED",)),
    ]
    assert len(consumed_gate_ids) == len(set(consumed_gate_ids)) == 2


def test_invisible_exit_order_is_not_duplicated_or_reported_complete():
    class DelayedExitVisibilityUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.quantity = 5
            self.exit_calls = 0
            self.post_exit_position_reads = 0

        def order_book(self):
            self.calls.append(("order_book",))
            return {**_OK, "data": []}

        def positions(self):
            if self.exit_calls:
                self.post_exit_position_reads += 1
                if self.post_exit_position_reads >= 3:
                    self.quantity = 0
            self.calls.append(("positions", self.quantity))
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "I",
                        "quantity": self.quantity,
                    }
                ],
            }

        def place_order(self, params):
            self.exit_calls += 1
            self.calls.append(("place", params))
            return {**_OK, "data": {"order_ids": ["EXIT-DELAYED-1"]}}

    mock = DelayedExitVisibilityUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    assert not result.complete
    assert mock.exit_calls == 1
    assert len(consumed_gate_ids) == 1


def test_invisible_partially_filled_fte_does_not_trigger_a_duplicate_residual_exit():
    class InvisiblePartialExitUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.quantity = 5
            self.place_calls = 0

        def order_book(self):
            return {**_OK, "data": []}

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 2 if self.place_calls else 0,
                    }
                ],
            }

        def place_order(self, params):
            self.place_calls += 1
            self.calls.append(("place", params))
            self.quantity = 3
            return {**_OK, "data": {"order_ids": ["FTE-INVISIBLE-PARTIAL"]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must use the exact reducing write")

    mock = InvisiblePartialExitUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(
        mock,
        planned_readback_attempts=8,
        planned_readback_delay_seconds=0,
    )

    placements = [call for call in mock.calls if call[0] == "place"]
    assert not result.complete
    assert mock.quantity == 3
    assert len(placements) == 1
    assert placements[0][1]["quantity"] == 5
    assert len(consumed_gate_ids) == 1


def test_emergency_delivery_exit_does_not_duplicate_while_completed_order_position_is_stale():
    class StaleCompletedDeliveryExitUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.quantity = 5
            self.exit_calls = 0
            self.exit_tag = ""
            self.post_exit_position_reads = 0

        def order_book(self):
            self.calls.append(("order_book", self.exit_calls))
            if not self.exit_calls:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "EXIT-DELIVERY-COMPLETE",
                        "status": "complete",
                        "tag": self.exit_tag,
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 5,
                        "filled_quantity": 5,
                    }
                ],
            }

        def positions(self):
            if self.exit_calls:
                self.post_exit_position_reads += 1
                if self.post_exit_position_reads >= 3:
                    self.quantity = 0
            self.calls.append(("positions", self.quantity))
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                    }
                ],
            }

        def place_order(self, params):
            self.exit_calls += 1
            self.exit_tag = params["tag"]
            self.calls.append(("place", params))
            return {**_OK, "data": {"order_ids": ["EXIT-DELIVERY-COMPLETE"]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must not use Upstox exit-all")

    mock = StaleCompletedDeliveryExitUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(mock)

    assert result.complete
    assert mock.exit_calls == 1
    assert len(consumed_gate_ids) == 1


def test_completed_fte_order_is_not_replayed_or_reported_complete_while_position_is_stale():
    class ProcessBoundaryDeliveryExitUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.completed_orders: list[dict[str, object]] = []

        def order_book(self):
            self.calls.append(("order_book", len(self.completed_orders)))
            return {**_OK, "data": list(self.completed_orders)}

        def positions(self):
            self.calls.append(("positions", 5))
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                    }
                ],
            }

        def place_order(self, params):
            self.calls.append(("place", params))
            self.completed_orders.append(
                {
                    "order_id": f"EXIT-{len(self.completed_orders) + 1}",
                    "status": "complete",
                    "tag": params["tag"],
                    "trading_symbol": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                    "transaction_type": "SELL",
                    "order_type": "MARKET",
                    "product": "D",
                    "quantity": 5,
                    "filled_quantity": 5,
                }
            )
            return {**_OK, "data": {"order_ids": [self.completed_orders[-1]["order_id"]]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must not use Upstox exit-all")

    mock = ProcessBoundaryDeliveryExitUpstox()
    dispatcher_settings = {
        "planned_readback_attempts": 8,
        "planned_readback_delay_seconds": 0,
    }

    first, first_gate_ids = _run_emergency_dispatch(mock, **dispatcher_settings)
    second, second_gate_ids = _run_emergency_dispatch(mock, **dispatcher_settings)

    placements = [call for call in mock.calls if call[0] == "place"]
    assert not first.complete
    assert not second.complete
    assert len(placements) == 1
    assert len(first_gate_ids) == 1
    assert second_gate_ids == []


@pytest.mark.parametrize(
    ("next_symbol", "next_quantity", "next_action"),
    [
        ("RELIANCE", 7, "SELL"),
        ("RELIANCE", -5, "BUY"),
    ],
)
def test_completed_fte_evidence_does_not_suppress_resized_or_reversed_position(
    next_symbol,
    next_quantity,
    next_action,
):
    """A second dispatcher emits a new FTE intent when exposure has changed."""

    class ChangedPositionUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.symbol = "RELIANCE"
            self.quantity = 5
            self.overnight_quantity = 5
            self.day_buy_quantity = 0
            self.day_sell_quantity = 0
            self.completed_orders: list[dict[str, object]] = []

        def order_book(self):
            return {**_OK, "data": list(self.completed_orders)}

        def positions(self):
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": self.symbol,
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                        "overnight_quantity": self.overnight_quantity,
                        "day_buy_quantity": self.day_buy_quantity,
                        "day_sell_quantity": self.day_sell_quantity,
                    }
                ],
            }

        def place_order(self, params):
            self.calls.append(("place", params))
            symbol = self.symbol
            self.completed_orders.append(
                {
                    "order_id": f"EXIT-{len(self.completed_orders) + 1}",
                    "status": "complete",
                    "tag": params["tag"],
                    "trading_symbol": symbol,
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                    "transaction_type": params["transaction_type"],
                    "order_type": "MARKET",
                    "product": "D",
                    "quantity": params["quantity"],
                    "filled_quantity": params["quantity"],
                }
            )
            self.quantity = 0
            return {**_OK, "data": {"order_ids": [self.completed_orders[-1]["order_id"]]}}

        def set_exposure(self, *, symbol, quantity):
            self.symbol = symbol
            self.quantity = quantity
            self.overnight_quantity = 0
            self.day_buy_quantity = max(quantity, 0)
            self.day_sell_quantity = max(-quantity, 0)

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must use the exact reducing write")

    mock = ChangedPositionUpstox()
    settings = {"planned_readback_attempts": 8, "planned_readback_delay_seconds": 0}
    first, first_gate_ids = _run_emergency_dispatch(mock, **settings)
    mock.set_exposure(symbol=next_symbol, quantity=next_quantity)
    second, second_gate_ids = _run_emergency_dispatch(mock, **settings)

    placements = [call[1] for call in mock.calls if call[0] == "place"]
    assert first.complete
    assert second.complete
    assert len(placements) == 2
    assert placements[1]["transaction_type"] == next_action
    assert placements[1]["tag"] != placements[0]["tag"]
    assert len(first_gate_ids) == 1
    assert len(second_gate_ids) == 1


def test_old_completed_fte_does_not_suppress_reopened_identical_exposure():
    """Accounting fingerprints distinguish a reopened same-symbol, same-size position."""

    class ReopenedIdenticalExposureUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.quantity = 5
            self.overnight_quantity = 5
            self.day_buy_quantity = 0
            self.day_sell_quantity = 0
            self.completed_orders: list[dict[str, object]] = []

        def order_book(self):
            return {**_OK, "data": list(self.completed_orders)}

        def positions(self):
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                        "overnight_quantity": self.overnight_quantity,
                        "day_buy_quantity": self.day_buy_quantity,
                        "day_sell_quantity": self.day_sell_quantity,
                    }
                ],
            }

        def place_order(self, params):
            self.calls.append(("place", params))
            self.completed_orders.append(
                {
                    "order_id": f"EXIT-{len(self.completed_orders) + 1}",
                    "status": "complete",
                    "tag": params["tag"],
                    "trading_symbol": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "NSE_EQ",
                    "transaction_type": "SELL",
                    "order_type": "MARKET",
                    "product": "D",
                    "quantity": 5,
                    "filled_quantity": 5,
                }
            )
            self.quantity = 0
            return {**_OK, "data": {"order_ids": [self.completed_orders[-1]["order_id"]]}}

        def reopen_identical_exposure(self):
            self.quantity = 5
            self.day_buy_quantity = 5
            self.day_sell_quantity = 5

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must use the exact reducing write")

    mock = ReopenedIdenticalExposureUpstox()
    settings = {"planned_readback_attempts": 8, "planned_readback_delay_seconds": 0}

    first, first_gate_ids = _run_emergency_dispatch(mock, **settings)
    mock.reopen_identical_exposure()
    second, second_gate_ids = _run_emergency_dispatch(mock, **settings)

    placements = [call[1] for call in mock.calls if call[0] == "place"]
    assert first.complete
    assert second.complete
    assert len(placements) == 2
    assert placements[0]["transaction_type"] == placements[1]["transaction_type"] == "SELL"
    assert placements[0]["quantity"] == placements[1]["quantity"] == 5
    assert placements[0]["tag"] != placements[1]["tag"]
    assert len(first_gate_ids) == len(second_gate_ids) == 1
    assert len(set(first_gate_ids + second_gate_ids)) == 2


@pytest.mark.asyncio
async def test_partially_filled_active_fte_suppresses_duplicate_residual_exit():
    """The active remainder remains pending without placing a second reducing order."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    original = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
        "overnight_quantity": "5",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "_emergency_accounting_complete": True,
    }

    class PartiallyFilledExitUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "FTE-PARTIAL",
                        "status": "open",
                        "tag": UpstoxAdapter._emergency_exit_tag(original),
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 5,
                        "filled_quantity": 2,
                        "pending_quantity": 3,
                    }
                ],
            }

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 3,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 2,
                    }
                ],
            }

    adapter = _adapter(PartiallyFilledExitUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_missing_protected_exit_tag_blocks_the_upstox_cancellation_branch():
    """A vanished protected exit must stop cancellation until readback resolves it."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
        "overnight_quantity": "5",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "_emergency_accounting_complete": True,
    }
    protected_tag = UpstoxAdapter._emergency_exit_tag(position)

    class MissingTaggedExitUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "UNKNOWN-EXIT",
                        "status": "open",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 5,
                        "filled_quantity": 0,
                        "pending_quantity": 5,
                    }
                ],
            }

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 0,
                    }
                ],
            }

    adapter = _adapter(MissingTaggedExitUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset({protected_tag}),
    )

    assert plan.pending_verbs == frozenset({"cancel_all_orders", "exit_all_positions"})
    assert plan.writes == ()


@pytest.mark.asyncio
async def test_duplicate_exact_active_ftes_are_both_cancelled_before_replanning():
    """Two exact active exits for one position must never be allowed to fill together."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
        "overnight_quantity": "5",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "_emergency_accounting_complete": True,
    }

    class DuplicateExactExitsUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": order_id,
                        "status": "open",
                        "tag": UpstoxAdapter._emergency_exit_tag(position),
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 5,
                        "filled_quantity": 0,
                        "pending_quantity": 5,
                    }
                    for order_id in ("FTE-DUPLICATE-1", "FTE-DUPLICATE-2")
                ],
            }

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 0,
                    }
                ],
            }

    adapter = _adapter(DuplicateExactExitsUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert [write.verb for write in plan.writes] == ["cancel_order", "cancel_order"]
    assert {write.payload["order_id"] for write in plan.writes} == {
        "FTE-DUPLICATE-1",
        "FTE-DUPLICATE-2",
    }


@pytest.mark.asyncio
async def test_emergency_planning_rejects_inconsistent_complete_position_accounting():
    """A complete Upstox accounting tuple must reconcile to its signed net."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    class InconsistentPositionUpstox(MockUpstox):
        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                        "overnight_quantity": 4,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 0,
                    }
                ],
            }

    adapter = _adapter(InconsistentPositionUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="accounting is inconsistent"):
        await adapter.plan_emergency_reduction(
            session,
            policy=MTM_EMERGENCY_POLICY,
            protected_order_ids=frozenset(),
            protected_exit_tags=frozenset(),
        )


@pytest.mark.asyncio
async def test_reducing_write_rejects_same_size_exposure_episode_change_before_broker_call():
    """The final adapter check binds an exact reducing write to its planned episode."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    class ChangedEpisodeUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.reopened = False

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 5 if self.reopened else 0,
                        "day_sell_quantity": 5 if self.reopened else 0,
                    }
                ],
            }

        def place_order(self, params):
            raise AssertionError("A changed exposure episode must not reach Upstox placement")

    mock = ChangedEpisodeUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )
    assert len(plan.writes) == 1

    mock.reopened = True
    with pytest.raises(BrokerError, match="episode changed"):
        await adapter.place_reducing_order(
            session,
            dict(plan.writes[0].payload),
            _router_token=_ROUTER_TOKEN,
        )


def test_conflicting_active_fte_is_cancelled_then_replanned_through_fresh_gates():
    """A mismatched active FTE is gated off before the exact residual exit is gated."""

    class ConflictingActiveExitUpstox(MockUpstox):
        def __init__(self):
            super().__init__()
            self.active = True
            self.quantity = 3
            self.completed_order: dict[str, object] | None = None

        def order_book(self):
            if not self.active:
                return {**_OK, "data": [self.completed_order] if self.completed_order else []}
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "FTE-CONFLICT",
                        "status": "open",
                        "tag": UpstoxAdapter._emergency_exit_tag(
                            {
                                "symbol": "RELIANCE",
                                "exchange": "NSE",
                                "product": "CNC",
                                "quantity": "2",
                                "overnight_quantity": "2",
                                "day_buy_quantity": "0",
                                "day_sell_quantity": "0",
                                "_emergency_accounting_complete": True,
                            }
                        ),
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 2,
                        "filled_quantity": 0,
                        "pending_quantity": 2,
                    }
                ],
            }

        def positions(self):
            if not self.quantity:
                return {**_OK, "data": []}
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": self.quantity,
                        "overnight_quantity": 3,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 0,
                    }
                ],
            }

        def cancel_order(self, order_id):
            assert order_id == "FTE-CONFLICT"
            self.calls.append(("cancel", order_id))
            self.active = False
            return {**_OK, "data": {"order_id": order_id}}

        def place_order(self, params):
            self.calls.append(("place", params))
            self.completed_order = {
                "order_id": "FTE-EXACT",
                "status": "complete",
                "tag": params["tag"],
                "trading_symbol": "RELIANCE",
                "exchange": "NSE",
                "segment": "NSE_EQ",
                "transaction_type": "SELL",
                "order_type": "MARKET",
                "product": "D",
                "quantity": 3,
                "filled_quantity": 3,
            }
            self.quantity = 0
            return {**_OK, "data": {"order_ids": ["FTE-EXACT"]}}

        def exit_positions(self, tag=None, segment=None):
            raise AssertionError("Delivery EQ must use the exact reducing write")

    mock = ConflictingActiveExitUpstox()
    result, consumed_gate_ids = _run_emergency_dispatch(
        mock,
        planned_readback_attempts=8,
        planned_readback_delay_seconds=0,
    )

    mutations = [call for call in mock.calls if call[0] in {"cancel", "place"}]
    assert result.complete
    assert [call[0] for call in mutations] == ["cancel", "place"]
    assert mutations[1][1]["transaction_type"] == "SELL"
    assert mutations[1][1]["quantity"] == 3
    assert len(consumed_gate_ids) == len(set(consumed_gate_ids)) == 2


@pytest.mark.asyncio
async def test_active_fte_suppresses_only_its_exact_matching_position():
    """A live FTE does not block a fresh reducing intent for another position."""
    from flinttrade_engine.safety import L5_EMERGENCY_POLICY

    class ActiveFteUpstox(MockUpstox):
        def order_book(self):
            return {
                **_OK,
                "data": [
                    {
                        "order_id": "FTE-RELIANCE",
                        "status": "open",
                        "tag": UpstoxAdapter._emergency_exit_tag(
                            {"symbol": "RELIANCE", "exchange": "NSE", "product": "CNC", "quantity": "5"}
                        ),
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "transaction_type": "SELL",
                        "order_type": "MARKET",
                        "product": "D",
                        "quantity": 5,
                    }
                ],
            }

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                    },
                    {
                        "trading_symbol": "INFY",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 3,
                    },
                ],
            }

    adapter = _adapter(ActiveFteUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=L5_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert len(plan.writes) == 1
    assert plan.writes[0].verb == "place_reducing_order"
    assert plan.writes[0].payload["symbol"] == "INFY"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["open", "complete"])
@pytest.mark.parametrize(
    "identity_override",
    [
        {"trading_symbol": "INFY"},
        {"exchange": "BSE", "segment": "BSE_EQ"},
        {"product": "I"},
    ],
    ids=["other-symbol", "other-exchange", "other-product"],
)
async def test_spoofed_fte_tag_for_another_position_does_not_suppress_reducing_write(
    status,
    identity_override,
):
    """A colliding tag is insufficient evidence for a different position intent."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    target_position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
    }

    class SpoofedFteUpstox(MockUpstox):
        def order_book(self):
            order = {
                "order_id": "FTE-SPOOFED",
                "status": status,
                "tag": UpstoxAdapter._emergency_exit_tag(target_position),
                "trading_symbol": "RELIANCE",
                "exchange": "NSE",
                "segment": "NSE_EQ",
                "transaction_type": "SELL",
                "order_type": "MARKET",
                "product": "D",
                "quantity": 5,
                "filled_quantity": 5,
            }
            return {**_OK, "data": [{**order, **identity_override}]}

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                    }
                ],
            }

    adapter = _adapter(SpoofedFteUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset(),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert len(plan.writes) == 1
    if status == "open":
        assert plan.writes[0].verb == "cancel_order"
        assert plan.writes[0].payload["order_id"] == "FTE-SPOOFED"
    else:
        assert plan.writes[0].verb == "place_reducing_order"
        assert plan.writes[0].payload == {
            "_op": "place_reducing_order",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": "5",
            "expected_position_quantity": "5",
            "action": "SELL",
            "pricetype": "MARKET",
            "price": "0",
            "trigger_price": "0",
            "variety": "regular",
            "emergency_tag": UpstoxAdapter._emergency_exit_tag(target_position),
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["open", "complete"])
@pytest.mark.parametrize(
    "identity_override",
    [
        {"trading_symbol": "INFY"},
        {"exchange": "BSE", "segment": "BSE_EQ"},
        {"product": "I"},
        {"transaction_type": "BUY"},
        {"quantity": 3, "filled_quantity": 3},
    ],
    ids=["active-infy", "other-exchange", "other-product", "wrong-side", "wrong-quantity"],
)
async def test_protected_exit_tag_retry_requires_the_full_reducing_intent_identity(
    status,
    identity_override,
):
    """A retry tag alone cannot stand in for RELIANCE's exact reducing order."""
    from flinttrade_engine.safety import MTM_EMERGENCY_POLICY

    position = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "quantity": "5",
        "overnight_quantity": "5",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "_emergency_accounting_complete": True,
    }
    protected_tag = UpstoxAdapter._emergency_exit_tag(position)

    class MismatchedProtectedTagUpstox(MockUpstox):
        def order_book(self):
            order = {
                "order_id": "WRONG-PROTECTED-FTE",
                "status": status,
                "tag": protected_tag,
                "trading_symbol": "RELIANCE",
                "exchange": "NSE",
                "segment": "NSE_EQ",
                "transaction_type": "SELL",
                "order_type": "MARKET",
                "product": "D",
                "quantity": 5,
                "filled_quantity": 5,
            }
            order.update(identity_override)
            if status == "open" and identity_override.get("quantity") == 3:
                order.update(filled_quantity=0, pending_quantity=3)
            return {**_OK, "data": [order]}

        def positions(self):
            return {
                **_OK,
                "data": [
                    {
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "segment": "NSE_EQ",
                        "product": "D",
                        "quantity": 5,
                        "overnight_quantity": 5,
                        "day_buy_quantity": 0,
                        "day_sell_quantity": 0,
                    }
                ],
            }

    adapter = _adapter(MismatchedProtectedTagUpstox())
    session = await _session(adapter)
    plan = await adapter.plan_emergency_reduction(
        session,
        policy=MTM_EMERGENCY_POLICY,
        protected_order_ids=frozenset(),
        protected_exit_tags=frozenset({protected_tag}),
    )

    assert plan.pending_verbs == frozenset({"exit_all_positions"})
    assert len(plan.writes) == 1
    if status == "open":
        assert plan.writes[0].verb == "cancel_order"
        assert plan.writes[0].payload["order_id"] == "WRONG-PROTECTED-FTE"
    else:
        assert plan.writes[0].verb == "place_reducing_order"
        assert plan.writes[0].payload["symbol"] == "RELIANCE"


@pytest.mark.asyncio
async def test_convert_position_resolves_token_and_maps_products():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.convert_position(
        session,
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "old_product": "MIS",
            "new_product": "CNC",
            "transaction_type": "BUY",
            "quantity": 10,
        },
        _router_token=_ROUTER_TOKEN,
    )
    assert out == {"status": "complete"}
    kind, params = mock.calls[0]
    assert kind == "convert"
    assert params["instrument_token"] == "NSE_EQ|INE002A01018"
    assert params["old_product"] == "I" and params["new_product"] == "D"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method, args",
    [
        ("place_order", (_order(variety="gtt", trigger_price="2850"),)),
        ("place_multi_order", ([_order()],)),
        ("cancel_all_orders", ()),
        ("exit_all_positions", ()),
        (
            "place_reducing_order",
            (
                {
                    "_op": "place_reducing_order",
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "product": "CNC",
                    "quantity": "1",
                    "expected_position_quantity": "1",
                    "action": "SELL",
                    "emergency_tag": "FTE-test",
                },
            ),
        ),
        (
            "convert_position",
            (
                {
                    "symbol": "RELIANCE",
                    "exchange": "NSE",
                    "old_product": "MIS",
                    "new_product": "CNC",
                    "transaction_type": "BUY",
                    "quantity": 1,
                },
            ),
        ),
        # modify/cancel for BOTH the regular and the GTT-prefix dispatch branches —
        # every write path must refuse a bare call (no router token).
        ("modify_order", ("240221025997024", {"quantity": 4, "price": 2950})),
        ("modify_order", ("GTT-CU100", {"quantity": 2, "trigger_price": 2860})),
        ("cancel_order", ("240221025997024",)),
        ("cancel_order", ("GTT-CU100",)),
    ],
)
async def test_every_write_is_router_gated(method, args):
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await getattr(adapter, method)(session, *args)
    assert mock.calls == []  # the broker was never touched


@pytest.mark.asyncio
async def test_place_order_ioc_validity_reaches_broker():
    # IOC survives the gated place path (PlaceOrderRequest.validity DAY|IOC).
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.place_order(session, _order(validity="IOC"), _router_token=_ROUTER_TOKEN)
    kind, params = mock.calls[0]
    assert kind == "place" and params["validity"] == "IOC"


# ---------------------------------------------------------------------------
# Broker-error translation: the facade maps SDK ApiException to the taxonomy
# ---------------------------------------------------------------------------


def _err_body(error_code: str, message: str) -> bytes:
    import json

    # Real wire key is errorCode (camelCase) — see upstox_mapping._parse_error_body.
    return json.dumps({"status": "error", "errors": [{"errorCode": error_code, "message": message}]}).encode()


def test_facade_translates_api_exception_to_taxonomy():
    # The class decorator wraps every public facade method so a raw SDK
    # ApiException never escapes — it becomes a mapped BrokerError (contract §7).
    @_facade_with_error_translation
    class _FakeFacade:
        def place_order(self, params):  # noqa: ARG002
            raise _StandInApiException(400, _err_body("UDAPI100038", "Order rejected by exchange"))

        def funds(self):
            raise _StandInApiException(401, _err_body("UDAPI100050", "Token expired"), reason="Unauthorized")

    facade = _FakeFacade()
    with pytest.raises(OrderRejectedByBroker) as ei:
        facade.place_order({})
    assert ei.value.broker_id == "upstox" and ei.value.broker_code == "UDAPI100038"
    assert "rejected by exchange" in str(ei.value)  # broker message survives
    with pytest.raises(SessionExpired):
        facade.funds()


def test_facade_passes_non_api_exceptions_through():
    @_facade_with_error_translation
    class _FakeFacade:
        def boom(self):
            raise ValueError("not an ApiException")

    with pytest.raises(ValueError, match="not an ApiException"):
        _FakeFacade().boom()


@pytest.mark.asyncio
async def test_adapter_surfaces_mapped_broker_error_from_facade():
    # A facade write that raises a mapped (in-taxonomy) error must surface it as
    # a typed BrokerError through the gated adapter path, not a raw SDK error.
    class _RaisingUpstox(MockUpstox):
        def place_order(self, params):  # noqa: ARG002
            raise OrderRejectedByBroker("Order rejected: circuit limit", broker_code="UDAPI100038", broker_id="upstox")

    adapter = _adapter(_RaisingUpstox())
    session = await _session(adapter)
    with pytest.raises(OrderRejectedByBroker, match="circuit limit"):
        await adapter.place_order(session, _order(), _router_token=_ROUTER_TOKEN)


@pytest.mark.asyncio
async def test_reconcile_captures_mapped_broker_error_on_fetch_failure():
    # Once SDK errors map to BrokerError, reconcile's (BrokerError, ValueError)
    # catch turns a broker fetch failure into an error report, not a raised
    # exception (contract §14).
    class _RaisingUpstox(MockUpstox):
        def order_book(self):
            raise SessionExpired("Token expired", broker_code="UDAPI100050", broker_id="upstox")

    adapter = _adapter(_RaisingUpstox())
    session = await _session(adapter)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "upstox"
    assert "broker fetch failed" in report.error and "Token expired" in report.error


# ---------------------------------------------------------------------------
# Reads: order/GTT/trade surfaces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_order_details_normalises_single_order():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    out = await adapter.order_details(session, "UOID1")
    assert out["orderid"] == "UOID1" and out["symbol"] == "TCS"
    assert out["filled_quantity"] == "5" and out["average_price"] == "3499.5"


@pytest.mark.asyncio
async def test_order_history_requires_id_or_tag():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    rows = await adapter.order_history(session, order_id="1")
    assert len(rows) == 2 and rows[-1]["status"] == "complete"
    assert mock.calls[0] == ("order_history", "1", None)
    with pytest.raises(BrokerError, match="order_id or a tag"):
        await adapter.order_history(session)


@pytest.mark.asyncio
async def test_gtt_orders_read_normalises_rules():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    rows = await adapter.gtt_orders(session, "GTT-CU100")
    assert mock.calls[0] == ("gtt_details", "GTT-CU100")
    assert rows[0]["gtt_order_id"] == "GTT-CU100" and rows[0]["product"] == "CNC"
    assert rows[0]["rules"][0]["strategy"] == "ENTRY"


@pytest.mark.asyncio
async def test_forever_orders_lists_and_normalises_active_gtts():
    class ActiveGttUpstox(MockUpstox):
        def gtt_order_details(self, gtt_order_id=None):
            self.calls.append(("gtt_details", gtt_order_id))
            return {
                **_OK,
                "data": [
                    {
                        "gtt_order_id": "GTT-CU100",
                        "type": "SINGLE",
                        "trading_symbol": "RELIANCE",
                        "exchange": "NSE",
                        "product": "D",
                        "quantity": 1,
                        "rules": [
                            {
                                "strategy": "ENTRY",
                                "status": "PENDING",
                                "trigger_price": 2850.0,
                                "transaction_type": "BUY",
                                "order_id": None,
                            }
                        ],
                    }
                ],
            }

    mock = ActiveGttUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    rows = await adapter.forever_orders(session)

    assert mock.calls == [("gtt_details", None)]
    assert rows == [
        {
            "orderid": "GTT-CU100",
            "gtt_order_id": "GTT-CU100",
            "type": "SINGLE",
            "symbol": "RELIANCE",
            "instrument_token": "",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": "1",
            "filled_quantity": "0",
            "pricetype": "LIMIT",
            "price": "2850.0",
            "action": "BUY",
            "status": "PENDING",
            "entry_status": "PENDING",
            "trigger_price": "2850.0",
            "stop_loss_price": "",
            "stop_loss_trailing_gap": "0",
            "target_price": "",
            "rules": [
                {
                    "strategy": "ENTRY",
                    "status": "PENDING",
                    "trigger_type": "",
                    "trigger_price": "2850.0",
                    "transaction_type": "BUY",
                    "order_id": "",
                }
            ],
            "created_at": "",
            "expires_at": "",
        }
    ]


@pytest.mark.asyncio
async def test_trades_by_order_and_trade_history():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    fills = await adapter.trades_by_order(session, "1")
    assert fills[0]["orderid"] == "1" and fills[0]["price"] == "3499.5"
    rows = await adapter.trade_history(session, "2025-04-01", "2025-04-30", page=2, page_size=50, segment="EQ")
    assert rows[0]["trade_id"] == "T1"
    assert ("trade_history", "2025-04-01", "2025-04-30", 2, 50, "EQ") in mock.calls


@pytest.mark.asyncio
async def test_mtf_positions_normalise_like_positions():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    rows = await adapter.mtf_positions(session)
    assert rows[0]["symbol"] == "SBIN" and rows[0]["product"] == "NRML"  # MTF → carry-forward
    assert rows[0]["pnl"] == "1200.0"


# ---------------------------------------------------------------------------
# Reads: user / charges / reports / kill switch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_read():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    profile = await adapter.profile(session)
    assert profile["user_id"] == "AB1234" and profile["is_active"] is True


@pytest.mark.asyncio
async def test_brokerage_calculator_builds_query():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.brokerage_calculator(session, _order(quantity="7", price="101.5"))
    assert out["total_charges"] == "104.05" and out["brokerage"] == "20.0"
    assert mock.calls[0] == ("brokerage", "NSE_EQ|INE002A01018", 7, "I", "BUY", 101.5)


@pytest.mark.asyncio
async def test_pnl_report_and_charges():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    rows = await adapter.pnl_report(session, "EQ", "2425", page=1, page_size=100)
    assert rows[0]["pnl"] == "500.0"
    charges = await adapter.pnl_charges(session, "EQ", "2425")
    assert charges["total_charges"] == "350.5"
    assert ("pnl_report", "EQ", "2425", 1, 100) in mock.calls
    assert ("pnl_charges", "EQ", "2425") in mock.calls


@pytest.mark.asyncio
async def test_kill_switch_actions_and_status():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.kill_switch(session, "activate")
    assert out["kill_switch_status"] == "ACTIVATE"
    assert mock.calls[0] == ("kill_update", {"action": "ACTIVATE"})
    with pytest.raises(BrokerError, match="ACTIVATE or DEACTIVATE"):
        await adapter.kill_switch(session, "pause")
    status = await adapter.kill_switch_status(session)
    assert status["kill_switch_status"] == "DEACTIVATED"


# ---------------------------------------------------------------------------
# Market data: v3 quotes, expired history, contracts, search, market info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v3_quote_reads():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    ohlc = await adapter.ohlc_quotes(session, ["NSE:RELIANCE"], interval="1d")
    assert ohlc[0]["ltp"] == 2905.5 and ohlc[0]["prev_close"] == 2899.0
    ltp = await adapter.ltp_quotes(session, ["NSE:RELIANCE"])
    assert ltp[0]["ltp"] == 2905.5
    greeks = await adapter.option_greeks(session, ["NFO:NIFTY24600CE"])
    assert greeks[0]["delta"] == 0.55
    kinds = [c[0] for c in mock.calls]
    assert kinds == ["ohlc_v3", "ltp_v3", "greeks_v3"]
    assert mock.calls[0][2] == "1d"  # interval forwarded


@pytest.mark.asyncio
async def test_option_greeks_matches_reordered_rows_by_exact_token() -> None:
    class ReorderedGreeksUpstox(MockUpstox):
        def option_greeks_v3(self, instrument_keys):
            self.calls.append(("greeks_v3", instrument_keys))
            return {
                **_OK,
                "data": {
                    "NSE_FO|PE": {
                        "instrument_token": "NSE_FO|PE",
                        "last_price": 90.0,
                        "iv": 14.2,
                        "delta": -0.45,
                        "gamma": 0.003,
                        "theta": -7.1,
                        "vega": 5.4,
                        "oi": 20,
                        "volume": 200,
                    },
                    "NSE_FO|CE": {
                        "instrument_token": "NSE_FO|CE",
                        "last_price": 120.0,
                        "iv": 13.2,
                        "delta": 0.55,
                        "gamma": 0.002,
                        "theta": -8.1,
                        "vega": 6.4,
                        "oi": 10,
                        "volume": 100,
                    },
                },
            }

    keys = {
        ("NIFTY24600CE", "NFO"): "NSE_FO|CE",
        ("NIFTY24700PE", "NFO"): "NSE_FO|PE",
    }
    mock = ReorderedGreeksUpstox()
    adapter = UpstoxAdapter(
        client_factory=lambda _session: mock,
        instrument_resolver=lambda symbol, exchange: keys[(symbol, exchange)],
    )
    session = await _session(adapter)

    greeks = await adapter.option_greeks(
        session,
        ["NFO:NIFTY24600CE", "NFO:NIFTY24700PE"],
    )

    assert [row["symbol"] for row in greeks] == ["NIFTY24600CE", "NIFTY24700PE"]
    assert [row["instrument_id"] for row in greeks] == ["NSE_FO|CE", "NSE_FO|PE"]
    assert [row["delta"] for row in greeks] == [0.55, -0.45]


@pytest.mark.asyncio
async def test_portfolio_greeks_uses_exact_position_tokens() -> None:
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    positions = [
        {
            "symbol": "NIFTY 30 JUL 26 25000 CE",
            "instrument_id": "NSE_FO|54452",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "",
            "strike_price": 0.0,
            "underlying": "",
        }
    ]

    greeks = await adapter.portfolio_greeks(session, positions)

    assert greeks == [
        {
            "symbol": "NIFTY 30 JUL 26 25000 CE",
            "instrument_id": "NSE_FO|54452",
            "exchange": "NFO",
            "delta": 0.55,
            "vega": 6.4,
        }
    ]
    assert mock.calls == [("greeks_v3", "NSE_FO|54452")]


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_a_symbol_token_identity_mismatch() -> None:
    adapter = UpstoxAdapter(
        client_factory=lambda _session: MockUpstox(),
        instrument_resolver=lambda _symbol, _exchange: "NSE_FO|AUTHORITATIVE",
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="conflicts with its authoritative instrument token"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY 30 JUL 26 25000 CE",
            "instrument_id": "NSE_FO|ANOTHER-CONTRACT",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
        }])


@pytest.mark.asyncio
async def test_portfolio_greeks_rejects_malformed_numeric_values() -> None:
    class MalformedGreeksUpstox(MockUpstox):
        def option_greeks_v3(self, instrument_keys):
            response = super().option_greeks_v3(instrument_keys)
            response["data"]["NSE_FO|54452"]["delta"] = "not-a-number"
            return response

    adapter = _adapter(MalformedGreeksUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option-Greek response is invalid"):
        await adapter.portfolio_greeks(session, [{
            "symbol": "NIFTY 30 JUL 26 25000 CE",
            "instrument_id": "NSE_FO|54452",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
        }])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda response: response.update({"status": "failure"}),
        lambda response: response.pop("status"),
        lambda response: response["data"]["NSE_FO|54452"].pop("instrument_token"),
        lambda response: response["data"]["NSE_FO|54452"].update({"oi": float("inf")}),
        lambda response: response["data"]["NSE_FO|54452"].update({"volume": "bad"}),
    ],
)
async def test_option_greeks_wraps_failed_or_non_finite_quote_payloads(mutate) -> None:
    class InvalidGreeksUpstox(MockUpstox):
        def option_greeks_v3(self, instrument_keys):
            response = super().option_greeks_v3(instrument_keys)
            mutate(response)
            return response

    adapter = _adapter(InvalidGreeksUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="option-Greek response is invalid"):
        await adapter.option_greeks(session, ["NFO:NIFTY24600CE"])


@pytest.mark.asyncio
async def test_portfolio_greeks_resolves_token_for_new_option_contract() -> None:
    mock = MockUpstox()
    resolutions: list[tuple[str, str]] = []

    def resolve(symbol: str, exchange: str) -> str:
        resolutions.append((symbol, exchange))
        return "NSE_FO|54452"

    adapter = UpstoxAdapter(
        client_factory=lambda _session: mock,
        instrument_resolver=resolve,
    )
    session = await _session(adapter)
    positions = [{
        "symbol": "NIFTY 30 JUL 26 25000 CE",
        "instrument_id": "",
        "exchange": "NFO",
        "quantity": 75.0,
        "option_type": "CE",
        "expiry": "",
        "strike_price": 0.0,
        "underlying": "",
    }]

    greeks = await adapter.portfolio_greeks(session, positions)

    assert greeks == [{
        "symbol": "NIFTY 30 JUL 26 25000 CE",
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "delta": 0.55,
        "vega": 6.4,
    }]
    assert resolutions == [("NIFTY 30 JUL 26 25000 CE", "NFO")]
    assert mock.calls == [("greeks_v3", "NSE_FO|54452")]


@pytest.mark.asyncio
async def test_portfolio_greeks_resolves_new_option_across_production_search_pages() -> None:
    class OptionSearchUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            self.calls.append(("search", query, page_number, records))
            return {
                **_OK,
                "data": [{
                    "instrument_key": "NSE_FO|54452",
                    "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                    "segment": "NSE_FO",
                }],
                "meta_data": {
                    "page": {"page_number": 1, "records": 30, "total_records": 1, "total_pages": 1}
                },
            }

    mock = OptionSearchUpstox()
    adapter = UpstoxAdapter(client_factory=lambda _session: mock)
    session = await _session(adapter)

    greeks = await adapter.portfolio_greeks(session, [{
        "symbol": "NIFTY 30 JUL 26 25000 CE",
        "instrument_id": "",
        "exchange": "NFO",
        "quantity": 75.0,
        "option_type": "CE",
    }])

    assert greeks[0]["instrument_id"] == "NSE_FO|54452"
    assert greeks[0]["delta"] == 0.55
    assert mock.calls == [
        ("search", "NIFTY 30 JUL 26 25000 CE", 1, 30),
        ("greeks_v3", "NSE_FO|54452"),
    ]


@pytest.mark.asyncio
async def test_market_depth_uses_full_quote_depth_ladder():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)

    depth = await adapter.market_depth(session, ["NSE:RELIANCE"])

    assert depth[0]["symbol"] == "RELIANCE"
    assert depth[0]["bids"][0] == {"price": 2905.0, "quantity": 10, "orders": 2}
    assert depth[0]["asks"][0] == {"price": 2906.0, "quantity": 8, "orders": 1}
    assert mock.calls == [("full_quote", "NSE_EQ|INE002A01018")]


@pytest.mark.asyncio
async def test_market_data_resolves_by_instrument_search_and_reuses_cache():
    mock = MockUpstox()
    adapter = UpstoxAdapter(client_factory=lambda _s: mock)
    session = await _session(adapter)

    await adapter.ohlc_quotes(session, ["NSE:RELIANCE"], interval="1d")
    await adapter.ltp_quotes(session, ["NSE:RELIANCE"])

    kinds = [c[0] for c in mock.calls]
    assert kinds == ["search", "ohlc_v3", "ltp_v3"]
    assert mock.calls[1][1] == "NSE_EQ|INE002A01018"
    assert mock.calls[2][1] == "NSE_EQ|INE002A01018"


@pytest.mark.asyncio
async def test_instrument_search_rejects_ambiguous_exact_contract_matches() -> None:
    class AmbiguousSearchUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            self.calls.append(("search", query))
            assert page_number == 1
            assert records == 30
            return {
                **_OK,
                "data": [
                    {
                        "instrument_key": "NSE_FO|54452",
                        "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                        "segment": "NSE_FO",
                    },
                    {
                        "instrument_key": "NSE_FO|99999",
                        "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                        "segment": "NSE_FO",
                    },
                ],
                "meta_data": {
                    "page": {"page_number": 1, "records": 30, "total_records": 2, "total_pages": 1}
                },
            }

    adapter = UpstoxAdapter(client_factory=lambda _session: AmbiguousSearchUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="unique Upstox instrument_token"):
        await adapter._resolve_instrument(session, "NIFTY 30 JUL 26 25000 CE", "NFO")


@pytest.mark.asyncio
async def test_instrument_search_rejects_a_token_from_another_segment() -> None:
    class ConflictingSegmentUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            del query
            return {
                **_OK,
                "data": [{
                    "instrument_key": "BSE_FO|99999",
                    "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                    "segment": "NSE_FO",
                }],
                "meta_data": {
                    "page": {"page_number": page_number, "records": records, "total_records": 1, "total_pages": 1}
                },
            }

    adapter = UpstoxAdapter(client_factory=lambda _session: ConflictingSegmentUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="unique Upstox instrument_token"):
        await adapter._resolve_instrument(session, "NIFTY 30 JUL 26 25000 CE", "NFO")
    assert adapter._instrument_cache == {}


@pytest.mark.parametrize("instrument_key", ["NSE_FO", "NSE_FO|", "NSE_FO|   "])
@pytest.mark.asyncio
async def test_instrument_search_rejects_a_missing_token_body(instrument_key: str) -> None:
    class MissingTokenUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            del query
            return {
                **_OK,
                "data": [{
                    "instrument_key": instrument_key,
                    "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                    "segment": "NSE_FO",
                }],
                "meta_data": {
                    "page": {"page_number": page_number, "records": records, "total_records": 1, "total_pages": 1}
                },
            }

    adapter = UpstoxAdapter(client_factory=lambda _session: MissingTokenUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="unique Upstox instrument_token"):
        await adapter._resolve_instrument(session, "NIFTY 30 JUL 26 25000 CE", "NFO")
    assert adapter._instrument_cache == {}


@pytest.mark.parametrize(
    ("exchange", "instrument_key"),
    [("CDS", "NCD_FO|USDINR"), ("BCD", "BCD_FO|USDINR")],
)
@pytest.mark.asyncio
async def test_instrument_search_accepts_documented_currency_segments(
    exchange: str,
    instrument_key: str,
) -> None:
    symbol = "USDINR 30 JUL 26 85 CE"

    class CurrencySearchUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            assert query == symbol
            return {
                **_OK,
                "data": [{
                    "instrument_key": instrument_key,
                    "trading_symbol": symbol,
                    "segment": instrument_key.partition("|")[0],
                }],
                "meta_data": {
                    "page": {"page_number": page_number, "records": records, "total_records": 1, "total_pages": 1}
                },
            }

    adapter = UpstoxAdapter(client_factory=lambda _session: CurrencySearchUpstox())
    session = await _session(adapter)

    assert await adapter._resolve_instrument(session, symbol, exchange) == instrument_key


@pytest.mark.parametrize("instrument_key", ["NSE_FO", "NSE_FO|", "BSE_FO|OTHER"])
@pytest.mark.asyncio
async def test_injected_instrument_resolver_cannot_cache_an_invalid_identity(instrument_key: str) -> None:
    adapter = UpstoxAdapter(
        client_factory=lambda _session: MockUpstox(),
        instrument_resolver=lambda _symbol, _exchange: instrument_key,
    )
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="unique Upstox instrument_token"):
        await adapter._resolve_instrument(session, "NIFTY 30 JUL 26 25000 CE", "NFO")
    assert adapter._instrument_cache == {}


@pytest.mark.asyncio
async def test_instrument_search_rejects_an_exact_duplicate_on_a_later_page() -> None:
    class PaginatedSearchUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            self.calls.append(("search", query, page_number, records))
            exact = {
                "instrument_key": "NSE_FO|54452",
                "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
                "segment": "NSE_FO",
            }
            filler = [
                {
                    "instrument_key": f"NSE_EQ|{index}",
                    "trading_symbol": f"UNRELATED{index}",
                    "segment": "NSE_EQ",
                }
                for index in range(29)
            ] if page_number == 1 else []
            return {
                **_OK,
                "data": [exact, *filler],
                "meta_data": {
                    "page": {"page_number": page_number, "records": 30, "total_records": 31, "total_pages": 2}
                },
            }

    mock = PaginatedSearchUpstox()
    adapter = UpstoxAdapter(client_factory=lambda _session: mock)
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="unique Upstox instrument_token"):
        await adapter._resolve_instrument(session, "NIFTY 30 JUL 26 25000 CE", "NFO")

    assert mock.calls == [
        ("search", "NIFTY 30 JUL 26 25000 CE", 1, 30),
        ("search", "NIFTY 30 JUL 26 25000 CE", 2, 30),
    ]


@pytest.mark.asyncio
async def test_instrument_search_rejects_truncated_pagination_metadata() -> None:
    class TruncatedSearchUpstox(MockUpstox):
        def search_instruments(self, query, *, page_number=1, records=30):
            del query
            return {
                **_OK,
                "data": [
                    {
                        "instrument_key": f"NSE_EQ|{index}",
                        "trading_symbol": "RELIANCE" if index == 0 else f"UNRELATED{index}",
                        "segment": "NSE_EQ",
                    }
                    for index in range(30)
                ],
                "meta_data": {
                    "page": {"page_number": page_number, "records": records, "total_records": 31, "total_pages": 1}
                },
            }

    adapter = UpstoxAdapter(client_factory=lambda _session: TruncatedSearchUpstox())
    session = await _session(adapter)

    with pytest.raises(BrokerError, match="Cannot resolve Upstox instrument_token") as exc_info:
        await adapter._resolve_instrument(session, "RELIANCE", "NSE")
    assert isinstance(exc_info.value.__cause__, BrokerError)
    assert "pagination is invalid" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_historical_expired_flag_routes_to_expired_endpoint():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    candles = await adapter.historical(
        session,
        {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "interval": "1d",
            "expired": True,
            "instrument_key": "NSE_FO|54452|27-06-2024",
            "from_date": "2024-06-01",
            "to_date": "2024-06-27",
        },
    )
    kinds = [c[0] for c in mock.calls]
    assert kinds == ["expired_history"]
    assert candles.bars[0].close == 52.0


@pytest.mark.asyncio
async def test_historical_one_second_unit_reaches_client():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.historical(
        session,
        {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1s", "from_date": "2025-06-01", "to_date": "2025-06-02"},
    )
    _, args = mock.calls[0]
    assert args[1] == "seconds" and args[2] == "1"


@pytest.mark.asyncio
async def test_option_contracts_expiries_and_expired_contracts():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    contracts = await adapter.option_contracts(session, "NIFTY", expiry="2025-06-26")
    assert contracts[0]["strike_price"] == 24600.0
    expiries = await adapter.expiry_list(session, "NIFTY")
    assert expiries == ["2025-06-26", "2025-07-03"]
    opts = await adapter.expired_contracts(session, "NIFTY", "NSE_INDEX", "2024-06-27")
    assert opts[0]["instrument_key"] == "NSE_FO|OPT1|expired"
    futs = await adapter.expired_contracts(session, "NIFTY", "NSE_INDEX", "2024-06-27", kind="future")
    assert futs[0]["instrument_key"] == "NSE_FO|FUT1|expired"
    kinds = [c[0] for c in mock.calls]
    assert kinds == ["option_contracts", "expiries", "expired_options", "expired_futures"]


@pytest.mark.asyncio
async def test_search_instruments():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    rows = await adapter.search_instruments(session, "reliance")
    assert rows[0]["symbol"] == "RELIANCE"


@pytest.mark.asyncio
async def test_market_information_reads():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    timings = await adapter.market_timings(session, "2025-06-12")
    assert timings[0]["exchange"] == "NSE"
    holidays = await adapter.market_holidays(session)
    assert holidays[0]["date"] == "2025-08-15"
    assert holidays[0]["open_exchanges"] == [
        {"exchange": "NSE", "start_time": "1755246600000", "end_time": "1755250200000"},
    ]
    one_day = await adapter.market_holidays(session, "2025-08-15")
    assert one_day[0]["description"] == "Independence Day"
    status = await adapter.market_status(session, "nse")
    assert status["status"] == "NORMAL_OPEN"
    assert ("status", "NSE") in mock.calls  # exchange upper-cased


# ---------------------------------------------------------------------------
# Streaming: feed authorisation + injected decoded-message stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feed_authorisation_returns_wss_uris():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    market = await adapter.market_feed_authorize(session)
    assert market.startswith("wss://feed.upstox/market")
    portfolio = await adapter.portfolio_feed_authorize(session, position_update=True)
    assert portfolio.startswith("wss://feed.upstox/portfolio")
    assert ("portfolio_auth", True, True, False) in mock.calls


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_track_feed_map():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    assert adapter._feed_map["NSE_EQ|INE002A01018"] == ("RELIANCE", "NSE")
    await adapter.unsubscribe(session, ["NSE:RELIANCE"])
    assert adapter._feed_map == {}


@pytest.mark.asyncio
async def test_stream_without_feed_factory_raises():
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    with pytest.raises(NotImplementedError, match="stream"):
        adapter.stream(session)


@pytest.mark.asyncio
async def test_stream_yields_tick_events_from_injected_feed():
    async def feed(_session):
        yield {
            "type": "live_feed",
            "feeds": {
                "NSE_EQ|INE002A01018": {"ltpc": {"ltp": 2905.5, "ltt": "1718595000123", "cp": 2899.0}},
                "NSE_FO|99999": {
                    "fullFeed": {
                        "marketFF": {
                            "ltpc": {"ltp": 120.5, "ltt": "2"},
                            "vtt": "1000",
                            "oi": "555",
                        }
                    }
                },
            },
        }

    adapter = _adapter(MockUpstox(), feed_factory=feed)
    session = await _session(adapter)
    await adapter.subscribe(session, ["NSE:RELIANCE"])
    ticks = [t async for t in adapter.stream(session)]
    assert len(ticks) == 2
    mapped = next(t for t in ticks if t.symbol == "RELIANCE")
    assert mapped.exchange == "NSE" and mapped.ltp == 2905.5 and mapped.timestamp == "1718595000123"
    # Unsubscribed instrument falls back to the key's own segment/name.
    fallback = next(t for t in ticks if t.symbol == "99999")
    assert fallback.exchange == "NFO" and fallback.volume == 1000 and fallback.oi == 555


@pytest.mark.asyncio
async def test_reconcile_clean_on_empty_state():
    # Empty broker books + the default EMPTY local state agree → clean report.
    # The diff semantics themselves are covered by tests/test_reconciliation.py.
    adapter = _adapter(MockUpstox())
    session = await _session(adapter)
    report = await adapter.reconcile(session)
    assert report.adapter_id == "upstox"
    assert report.clean and report.error == ""


# ---------------------------------------------------------------------------
# G7 — replayable-credential payload
# ---------------------------------------------------------------------------


def test_replay_credentials_drops_oauth_code_and_keeps_exchanged_token() -> None:
    from flinttrade_gateway.brokers._base import Session

    adapter = UpstoxAdapter(client_factory=lambda _s: object())
    session = Session(access_token="exchanged", expires_at=9e9, account_id="U1", adapter_id="upstox")
    replay = adapter.replay_credentials(
        {"api_key": "K", "api_secret": "S", "code": "single-use", "redirect_uri": "http://cb"}, session
    )
    assert "code" not in replay
    assert replay["access_token"] == "exchanged"
    assert replay["api_key"] == "K" and replay["api_secret"] == "S"
