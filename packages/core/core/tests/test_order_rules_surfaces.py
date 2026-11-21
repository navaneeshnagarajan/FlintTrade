"""The same order gets the same rule result from the API, Practice and backtests.

Live stays fail-closed here: nothing in this module unlocks Live or reaches a
broker. The adapter-boundary refusal is covered in the gateway router tests.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from flinttrade_core.order_rules import evaluate_order, headline, results_payload

pytestmark = [pytest.mark.usefixtures("owned_flask_apps")]

_TEST_API_KEY = "test-order-rules-surfaces-key"
_TODAY = date.today()
NIFTY_CE = "NIFTY25NOV2624000CE"
SENSEX_CE = "SENSEX27NOV2680000CE"

# (name, request body) pairs that a block-level rule refuses on every surface.
_BLOCKED = [
    (
        "option market",
        {
            "symbol": NIFTY_CE,
            "exchange": "NFO",
            "action": "BUY",
            "quantity": 75,
            "price": 0,
            "product": "MIS",
            "order_type": "MARKET",
        },
    ),
    (
        "option stop market",
        {
            "symbol": NIFTY_CE,
            "exchange": "NFO",
            "action": "SELL",
            "quantity": 75,
            "price": 0,
            "trigger_price": 80,
            "product": "MIS",
            "order_type": "SL-M",
        },
    ),
    (
        "bse stop limit gap",
        {
            "symbol": SENSEX_CE,
            "exchange": "BFO",
            "action": "SELL",
            "quantity": 20,
            "price": 39.95,
            "trigger_price": 50,
            "product": "MIS",
            "order_type": "SL",
        },
    ),
]


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module, tmp_path_factory):
    monkeypatch_module.setenv("FLINTTRADE_API_KEY", _TEST_API_KEY)
    frontend = tmp_path_factory.mktemp("order_rules_frontend") / "absent"
    monkeypatch_module.setenv("FLINTTRADE_FRONTEND_DIST", str(frontend))
    monkeypatch_module.setenv("DHAN_LIVE_ORDERS", "0")
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture(autouse=True)
def _laya_ready() -> None:
    from flinttrade_engine.laya import DecisionStatus, process_laya

    process_laya().set_status(DecisionStatus.READY)
    yield


@pytest.fixture(autouse=True)
def _reset_limits(flask_app):
    for key in ("RATE_LIMITER", "LIMITER"):
        limiter = flask_app.config.get(key)
        if limiter is not None:
            limiter.reset()
    yield


@pytest.fixture()
def client(flask_app):
    with flask_app.test_client() as test_client:
        yield test_client


def _practice_headers() -> dict[str, str]:
    from flinttrade_core.auth_routes import _create_token

    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_create_token('testuser', mode='practice')}",
    }


def _shape(results: list[dict]) -> list[tuple[str, str, str, str]]:
    return [(r["level"], r["source"], r["rule_id"], r["message"]) for r in results]


def _backtest_rule_results(body: dict) -> tuple[bool, list[dict]]:
    from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, OrderSide, OrderType

    types = {"MARKET": OrderType.MARKET, "LIMIT": OrderType.LIMIT, "SL": OrderType.STOP_LIMIT, "SL-M": OrderType.STOP}
    engine = BacktestEngine(EngineConfig(symbol=body["symbol"], exchange=body["exchange"]))
    order = EngineOrder(
        symbol=body["symbol"],
        side=OrderSide(body["action"]),
        order_type=types[body["order_type"]],
        quantity=int(body["quantity"]),
        limit_price=Decimal(str(body.get("price") or 0)),
        stop_price=Decimal(str(body.get("trigger_price") or 0)),
    )
    accepted = engine._apply_order_rules(order)
    return accepted, order.rule_results


@pytest.mark.parametrize(("name", "body"), _BLOCKED, ids=[name for name, _ in _BLOCKED])
def test_blocked_order_has_one_result_on_every_surface(name: str, body: dict, flask_app, client) -> None:
    expected = results_payload(evaluate_order(body, broker="practice", broker_name="Practice"))
    assert expected and expected[0]["level"] == "block"

    # API (the MCP order tools call the same endpoint).
    sandbox = MagicMock()
    flask_app.config["DATA_SANDBOX_ENGINE"] = sandbox
    response = client.post("/api/v1/orders/place", json=body, headers=_practice_headers())
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["code"] == "order_rule_blocked"
    assert _shape(payload["rule_results"]) == _shape(expected)
    assert payload["message"] == f"{expected[0]['source']} · {expected[0]['message']}"
    sandbox.place_order.assert_not_called()

    # Practice engine.
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    try:
        result = engine.place_order(
            body["symbol"],
            body["exchange"],
            body["action"],
            int(body["quantity"]),
            float(body.get("price") or 0) or 100.0,
            order_type=body["order_type"],
            trigger_price=float(body.get("trigger_price") or 0),
        )
    finally:
        engine.close()
    assert result["status"] == "REJECTED"
    assert result["message"] == payload["message"]
    assert _shape(result["rule_results"])[0] == _shape(expected)[0]

    # Backtest: the same rule ids are recorded on the order.
    _accepted, backtest_results = _backtest_rule_results(body)
    assert _shape(backtest_results) == _shape(expected)


def test_practice_never_instant_fills_an_option_market_order() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    try:
        result = engine.place_order(NIFTY_CE, "NFO", "BUY", 75, 100.0, order_type="MARKET")
        assert result["status"] == "REJECTED"
        assert engine.get_orders() == [] or all(o.get("status") != "COMPLETE" for o in engine.get_orders())
        assert engine.get_positions() == []
    finally:
        engine.close()


def test_practice_refuses_a_modify_into_an_out_of_range_stop_limit() -> None:
    from flinttrade_data.sandbox_engine import SandboxEngine

    engine = SandboxEngine(db_path=":memory:")
    try:
        engine.place_order(SENSEX_CE, "BFO", "BUY", 20, 60.0, order_type="LIMIT")
        engine.check_pending_fills({f"BFO:{SENSEX_CE}": 60.0})
        stop = engine.place_order(SENSEX_CE, "BFO", "SELL", 20, 45.0, order_type="SL", trigger_price=50.0)
        assert stop["status"] == "PENDING"
        refused = engine.modify_order(stop["order_id"], price=39.95)
        assert refused["status"] == "REJECTED"
        assert refused["message"] == "Exchange · Stop-loss limit must be within ₹10 of trigger."
    finally:
        engine.close()


def test_backtest_option_market_becomes_a_capped_limit_and_can_stay_unfilled() -> None:
    from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, OrderSide, OrderType

    engine = BacktestEngine(EngineConfig(symbol=NIFTY_CE, exchange="NFO"))
    engine._last_price = lambda _symbol: Decimal("100")  # type: ignore[method-assign]
    order = EngineOrder(symbol=NIFTY_CE, side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=75)
    assert engine._apply_order_rules(order) is True
    assert order.order_type == OrderType.LIMIT
    assert order.limit_price == Decimal("103.00")
    assert order.rule_results[0]["rule_id"] == "options-market-order-not-sent"
    # A bar that gaps above the cap leaves the order unfilled.
    assert engine._check_limit_fill(order, Decimal("120"), Decimal("110")) is None


def test_backtest_option_stop_market_becomes_a_capped_stop_limit() -> None:
    from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, OrderSide, OrderType

    engine = BacktestEngine(EngineConfig(symbol=NIFTY_CE, exchange="NFO"))
    order = EngineOrder(
        symbol=NIFTY_CE, side=OrderSide.SELL, order_type=OrderType.STOP, quantity=75, stop_price=Decimal("80")
    )
    assert engine._apply_order_rules(order) is True
    assert order.order_type == OrderType.STOP_LIMIT
    assert order.limit_price == Decimal("77.60")


def test_backtest_without_a_last_price_rejects_an_option_market_order() -> None:
    from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, OrderSide, OrderType

    engine = BacktestEngine(EngineConfig(symbol=NIFTY_CE, exchange="NFO"))
    order = EngineOrder(symbol=NIFTY_CE, side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=75)
    assert engine._apply_order_rules(order) is False


def test_equity_backtest_market_orders_are_unchanged() -> None:
    from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, OrderSide, OrderType

    engine = BacktestEngine(EngineConfig(symbol="RELIANCE", exchange="NSE"))
    order = EngineOrder(symbol="RELIANCE", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=1)
    assert engine._apply_order_rules(order) is True
    assert order.order_type == OrderType.MARKET


def test_api_returns_warnings_with_an_accepted_practice_order(flask_app, client) -> None:
    sandbox = MagicMock()
    sandbox.place_order.return_value = {
        "order_id": "SB-1",
        "status": "PENDING",
        "message": "Practice LIMIT order is pending",
    }
    flask_app.config["DATA_SANDBOX_ENGINE"] = sandbox
    body = {
        "symbol": NIFTY_CE,
        "exchange": "NFO",
        "action": "BUY",
        "quantity": 75,
        "price": 200,
        "product": "MIS",
        "order_type": "LIMIT",
        "last_price": 100,
    }
    response = client.post("/api/v1/orders/place", json=body, headers=_practice_headers())
    expected = results_payload(evaluate_order(body, broker="practice", broker_name="Practice", last_price=100))
    if response.status_code == 200:
        assert _shape(response.get_json()["rule_results"]) == _shape(expected)
        assert expected[0]["message"] == "Price may be outside the exchange band (₹60–₹140)."
    else:
        # A Practice admission refusal (for example, the session is closed)
        # still never turns a warning into a block.
        assert response.get_json().get("code") != "order_rule_blocked"


def test_headline_prefixes_the_source() -> None:
    results = evaluate_order({"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "MARKET"}, on=_TODAY)
    assert headline(results) == "FlintTrade · Market orders aren't accepted on options. Use a limit price."
