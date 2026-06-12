"""Adapter tests for the full Upstox parity surface (mock facade; no SDK).

The original v2 surface (login, gated trio happy path, portfolio reads, quotes,
history, option chain, margin) is covered by the root-level
``tests/test_upstox_adapter.py``; this file exercises everything added in the
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

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyBypassError
from flinttrade_gateway.brokers.upstox import _ROUTER_TOKEN, UpstoxAdapter
from flinttrade_gateway.brokers.upstox_mapping import UpstoxMappingError

pytestmark = pytest.mark.unit

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
        return {**_OK, "data": [{"order_id": "M1", "correlation_id": "1"},
                                {"order_id": "M2", "correlation_id": "2"}],
                "errors": [], "summary": {"total": 2, "success": 2}}

    def modify_order(self, params):
        self.calls.append(("modify", params))
        return {**_OK, "data": {"order_id": "UOID1"}}

    def cancel_order(self, order_id):
        self.calls.append(("cancel", order_id))
        return {**_OK, "data": {"order_id": order_id}}

    def cancel_multi_order(self, tag=None, segment=None):
        self.calls.append(("cancel_multi", tag, segment))
        return {**_OK, "data": {"order_ids": ["C1", "C2"]}, "summary": {"total": 2, "success": 2}}

    def exit_positions(self, tag=None, segment=None):
        self.calls.append(("exit_positions", tag, segment))
        return {**_OK, "data": {"order_ids": ["X1"]}, "summary": {"total": 1, "success": 1}}

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
        return {**_OK, "data": [
            {"gtt_order_id": "GTT-CU100", "type": "SINGLE", "trading_symbol": "RELIANCE",
             "exchange": "NSE", "product": "D", "quantity": 1,
             "rules": [{"strategy": "ENTRY", "status": "PENDING", "trigger_price": 2850.0,
                        "transaction_type": "BUY", "order_id": None}]},
        ]}

    # -- orders: reads --
    def order_book(self):
        return {**_OK, "data": []}

    def order_details(self, order_id):
        self.calls.append(("order_details", order_id))
        return {**_OK, "data": {"order_id": order_id, "status": "complete",
                                "trading_symbol": "TCS", "instrument_token": "NSE_EQ|INE467B01029",
                                "transaction_type": "BUY", "order_type": "LIMIT", "product": "D",
                                "quantity": 5, "price": 3500, "filled_quantity": 5,
                                "average_price": 3499.5}}

    def order_history(self, order_id=None, tag=None):
        self.calls.append(("order_history", order_id, tag))
        return {**_OK, "data": [
            {"order_id": "1", "status": "put order req received", "trading_symbol": "TCS",
             "instrument_token": "NSE_EQ|INE467B01029", "transaction_type": "BUY",
             "order_type": "LIMIT", "product": "D", "quantity": 5, "price": 3500},
            {"order_id": "1", "status": "complete", "trading_symbol": "TCS",
             "instrument_token": "NSE_EQ|INE467B01029", "transaction_type": "BUY",
             "order_type": "LIMIT", "product": "D", "quantity": 5, "price": 3500},
        ]}

    def trade_book(self):
        return {**_OK, "data": []}

    def trades_by_order(self, order_id):
        self.calls.append(("trades_by_order", order_id))
        return {**_OK, "data": [
            {"order_id": order_id, "trading_symbol": "TCS", "instrument_token": "NSE_EQ|INE467B01029",
             "transaction_type": "BUY", "quantity": 5, "average_price": 3499.5, "product": "D"},
        ]}

    def trade_history(self, start_date, end_date, page_number, page_size, segment=None):
        self.calls.append(("trade_history", start_date, end_date, page_number, page_size, segment))
        return {**_OK, "data": [
            {"trade_id": "T1", "scrip_name": "RELIANCE", "exchange": "NSE", "segment": "EQ",
             "transaction_type": "BUY", "quantity": 10, "price": 2900.0, "amount": 29000.0,
             "trade_date": "2025-04-01"},
        ]}

    # -- portfolio --
    def positions(self):
        return {**_OK, "data": []}

    def mtf_positions(self):
        self.calls.append(("mtf_positions",))
        return {**_OK, "data": [
            {"trading_symbol": "SBIN", "instrument_token": "NSE_EQ|INE062A01020", "product": "MTF",
             "quantity": 100, "average_price": 600.0, "last_price": 612.0, "pnl": 1200.0},
        ]}

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
        return {**_OK, "data": {"user_id": "AB1234", "user_name": "N", "email": "n@x.in",
                                "broker": "UPSTOX", "exchanges": ["NSE"], "products": ["D", "I"],
                                "order_types": ["LIMIT"], "is_active": True, "poa": False}}

    def kill_switch_status(self):
        self.calls.append(("kill_status",))
        return {**_OK, "data": {"kill_switch_status": "DEACTIVATED"}}

    def update_kill_switch(self, body):
        self.calls.append(("kill_update", body))
        return {**_OK, "data": {"kill_switch_status": body["action"]}}

    def brokerage(self, instrument_token, quantity, product, transaction_type, price):
        self.calls.append(("brokerage", instrument_token, quantity, product, transaction_type, price))
        return {**_OK, "data": {"charges": {"total": 104.05, "brokerage": 20.0,
                                            "taxes": {"gst": 3.6}, "other_taxes": {}}}}

    def margin(self, instruments):
        self.calls.append(("margin", instruments))
        return {**_OK, "data": {"required_margin": 14500, "final_margin": 14000}}

    # -- reports --
    def pnl_report(self, segment, financial_year, page_number, page_size):
        self.calls.append(("pnl_report", segment, financial_year, page_number, page_size))
        return {**_OK, "data": [
            {"scrip_name": "INFY", "quantity": 10, "buy_amount": 15000.0, "sell_amount": 15500.0},
        ]}

    def pnl_charges(self, segment, financial_year):
        self.calls.append(("pnl_charges", segment, financial_year))
        return {**_OK, "data": {"charges_breakdown": {"total": 350.5, "brokerage": 120.0}}}

    # -- market data --
    def full_quote(self, instrument_keys):
        return {**_OK, "data": {}}

    def ohlc_quote_v3(self, instrument_keys, interval):
        self.calls.append(("ohlc_v3", instrument_keys, interval))
        return {**_OK, "data": {"NSE_EQ:RELIANCE": {
            "last_price": 2905.5, "instrument_token": "NSE_EQ|INE002A01018",
            "live_ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2905, "volume": 12000},
            "prev_ohlc": {"close": 2899},
        }}}

    def ltp_quote_v3(self, instrument_keys):
        self.calls.append(("ltp_v3", instrument_keys))
        return {**_OK, "data": {"NSE_EQ:RELIANCE": {
            "last_price": 2905.5, "instrument_token": "NSE_EQ|INE002A01018", "volume": 99, "cp": 2899.0,
        }}}

    def option_greeks_v3(self, instrument_keys):
        self.calls.append(("greeks_v3", instrument_keys))
        return {**_OK, "data": {"NSE_FO|54452": {
            "last_price": 120.5, "instrument_token": "NSE_FO|54452", "iv": 13.2, "delta": 0.55,
            "gamma": 0.002, "theta": -8.1, "vega": 6.4, "oi": 30000, "volume": 5000,
        }}}

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
        return {**_OK, "data": [{"instrument_key": "NSE_FO|54452", "trading_symbol": "NIFTY 24600 CE",
                                 "strike_price": 24600, "lot_size": 75}]}

    def search_instruments(self, query):
        self.calls.append(("search", query))
        return {**_OK, "data": [{"instrument_key": "NSE_EQ|INE002A01018", "trading_symbol": "RELIANCE"}]}

    # -- market information --
    def exchange_timings(self, date):
        self.calls.append(("timings", date))
        return {**_OK, "data": [{"exchange": "NSE", "start_time": 1, "end_time": 2}]}

    def market_holidays(self, date=None):
        self.calls.append(("holidays", date))
        return {**_OK, "data": [{"date": "2025-08-15", "description": "Independence Day",
                                 "holiday_type": "TRADING_HOLIDAY", "closed_exchanges": ["NSE"]}]}

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
        instrument_resolver=lambda s, e: "NSE_EQ|INE002A01018",
        **kw,
    )


async def _session(adapter):
    return await adapter.login({"client_id": "C1", "access_token": "TOK"})


def _order(**kw) -> Order:
    base = dict(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                product="MIS", quantity="10", price="2900")
    base.update(kw)
    return Order(**base)


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
    session = await adapter.login({
        "client_id": "C1", "code": "mk404x", "api_key": "K1",
        "api_secret": "S1", "redirect_uri": "https://app.local/cb",
    })
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
    oid = await adapter.place_order(session, _order(variety="iceberg", quantity="50000"),
                                    _router_token=_ROUTER_TOKEN)
    assert oid == "UOID-V3-1"  # first sliced leg id
    kind, params = mock.calls[0]
    assert kind == "place_v3" and params["slice"] is True and params["quantity"] == 50000


@pytest.mark.asyncio
async def test_place_order_gtt_routes_to_gtt_endpoint():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    order = _order(variety="gtt", product="CNC", trigger_price="2850",
                   stop_loss_price="2800", target_price="2950")
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
        await adapter.place_order(session, _order(variety="bracket", stop_loss_price="2870"),
                                  _router_token=_ROUTER_TOKEN)
    assert mock.calls == []


@pytest.mark.asyncio
async def test_modify_order_dispatches_gtt_by_id_and_by_changes_flag():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.modify_order(session, "GTT-CU100", {"quantity": 2, "trigger_price": 2860},
                               _router_token=_ROUTER_TOKEN)
    kind, params = mock.calls[0]
    assert kind == "gtt_modify" and params["gtt_order_id"] == "GTT-CU100"
    assert params["rules"][0]["trigger_price"] == 2860.0

    mock.calls.clear()
    await adapter.modify_order(session, "GTT-CU101", {"variety": "gtt", "quantity": 3, "trigger_price": 2870},
                               _router_token=_ROUTER_TOKEN)
    assert mock.calls[0][0] == "gtt_modify"

    mock.calls.clear()
    await adapter.modify_order(session, "240221025997024", {"quantity": 4, "price": 2950},
                               _router_token=_ROUTER_TOKEN)
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
async def test_convert_position_resolves_token_and_maps_products():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    out = await adapter.convert_position(session, {
        "symbol": "RELIANCE", "exchange": "NSE", "old_product": "MIS", "new_product": "CNC",
        "transaction_type": "BUY", "quantity": 10,
    }, _router_token=_ROUTER_TOKEN)
    assert out == {"status": "complete"}
    kind, params = mock.calls[0]
    assert kind == "convert"
    assert params["instrument_token"] == "NSE_EQ|INE002A01018"
    assert params["old_product"] == "I" and params["new_product"] == "D"


@pytest.mark.asyncio
@pytest.mark.parametrize("method, args", [
    ("place_order", (_order(variety="gtt", trigger_price="2850"),)),
    ("place_multi_order", ([_order()],)),
    ("cancel_all_orders", ()),
    ("exit_all_positions", ()),
    ("convert_position", ({"symbol": "RELIANCE", "exchange": "NSE", "old_product": "MIS",
                           "new_product": "CNC", "transaction_type": "BUY", "quantity": 1},)),
])
async def test_every_write_is_router_gated(method, args):
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    with pytest.raises(SafetyBypassError):
        await getattr(adapter, method)(session, *args)
    assert mock.calls == []  # the broker was never touched


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
async def test_historical_expired_flag_routes_to_expired_endpoint():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    candles = await adapter.historical(session, {
        "symbol": "NIFTY", "exchange": "NFO", "interval": "1d", "expired": True,
        "instrument_key": "NSE_FO|54452|27-06-2024",
        "from_date": "2024-06-01", "to_date": "2024-06-27",
    })
    kinds = [c[0] for c in mock.calls]
    assert kinds == ["expired_history"]
    assert candles.bars[0].close == 52.0


@pytest.mark.asyncio
async def test_historical_one_second_unit_reaches_client():
    mock = MockUpstox()
    adapter = _adapter(mock)
    session = await _session(adapter)
    await adapter.historical(session, {"symbol": "RELIANCE", "exchange": "NSE", "interval": "1s",
                                       "from_date": "2025-06-01", "to_date": "2025-06-02"})
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
        yield {"type": "live_feed", "feeds": {
            "NSE_EQ|INE002A01018": {"ltpc": {"ltp": 2905.5, "ltt": "1718595000123", "cp": 2899.0}},
            "NSE_FO|99999": {"fullFeed": {"marketFF": {
                "ltpc": {"ltp": 120.5, "ltt": "2"}, "vtt": "1000", "oi": "555",
            }}},
        }}

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
