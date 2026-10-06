"""Offline Dhan depth crosses the real owned-read and Practice boundaries."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from flinttrade_core import order_routes
from flinttrade_core.models import Action, Exchange, Order, PriceType, Product
from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
from flinttrade_core.rate_limiter import RateLimiter
from flinttrade_data.sandbox_engine import SandboxEngine
from flinttrade_engine.safety import SafetySystem
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver
from packages.core.core.tests.test_ai_broker_context import runtime as runtime

pytestmark = pytest.mark.integration

_SYMBOL = "SYNTHCASH"
_TOKENS = {"NSE": "990001", "BSE": "990002"}


class _OfflineDhanClient:
    """Replace SDK I/O only; no production read/translation boundary is mocked."""

    def __init__(self):
        self.calls = []
        self.forbidden_calls = []
        self.depth = {
            "buy": [{"price": 99.5, "quantity": 8, "orders": 2}, {"price": 99.0, "quantity": 13, "orders": 3}],
            "sell": [{"price": 100.5, "quantity": 5, "orders": 1}, {"price": 101.0, "quantity": 11, "orders": 2}],
        }

    def quote_data(self, securities):
        self.calls.append(("quote_data", deepcopy(securities)))
        return {
            "status": "success",
            "data": {
                "status": "success",
                "data": {
                    segment: {str(token): {"last_price": 100.0, "depth": deepcopy(self.depth)} for token in tokens}
                    for segment, tokens in securities.items()
                },
            },
        }

    def get_fund_limits(self):
        self.calls.append(("get_fund_limits", None))
        return {"status": "success", "data": {"availabelBalance": 500.0}}

    def __getattr__(self, name):
        self.forbidden_calls.append(name)
        raise AssertionError(f"Unexpected SDK operation: {name}")


@pytest.fixture
def practice_runtime(runtime, backend_lease_proof, tmp_path, monkeypatch):
    sdk = _OfflineDhanClient()
    native = DhanAdapter(
        client_factory=lambda _session: sdk,
        security_resolver=build_security_resolver(
            [
                {
                    "SECURITY_ID": token,
                    "EXCH_ID": exchange,
                    "SEGMENT": "E",
                    "TRADING_SYMBOL": _SYMBOL,
                    "INSTRUMENT": "EQUITY",
                    "INSTRUMENT_TYPE": "ES",
                }
                for exchange, token in _TOKENS.items()
            ]
        ),
    )
    runtime.dependencies.adapters["dhan"] = native
    sandbox = SandboxEngine(str(tmp_path / "practice-depth.sqlite3"), initial_capital=100_000.0)
    forbidden_calls = []

    def forbidden(*_args, **_kwargs):
        forbidden_calls.append("live_write_or_unowned_read")
        pytest.fail("Practice must never call a Live write or an unowned read")

    for operation in ("place_order", "modify_order", "cancel_order"):
        monkeypatch.setattr(native, operation, forbidden)
    monkeypatch.setattr(runtime.client, "_read_port", forbidden)
    app = runtime.app
    app.config.update(
        DATA_SANDBOX_ENGINE=sandbox,
        RATE_LIMITER=RateLimiter(),
        BACKEND_LEASE_PROOF=backend_lease_proof,
        SAFETY=SafetySystem(),
        BROKER_ROUTER=SimpleNamespace(place_order=forbidden),
        TICK_RECORDER=None,
    )
    app.register_blueprint(order_routes.orders_bp)
    events = []
    practice = PracticeAgentAdapter(app, runtime.token(), event_sink=lambda kind, data: events.append((kind, data)))
    yield SimpleNamespace(
        practice=practice, sdk=sdk, audit=runtime.audit, history=runtime.adapter, sandbox=sandbox, events=events
    )
    practice.close()
    assert not sdk.forbidden_calls
    assert not forbidden_calls
    sandbox.close()


def _audit_events(runtime):
    return [
        event
        for filename in runtime.audit.list_audit_files()
        for event in runtime.audit.read_day(filename.removeprefix("audit_").removesuffix(".jsonl"))
    ]


@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
async def test_practice_consumes_native_dhan_depth_with_owned_read_receipt(practice_runtime, exchange):
    runtime = practice_runtime
    quote = await runtime.practice.quotes(symbol=_SYMBOL, exchange=exchange)
    depth = await runtime.practice.depth(symbol=_SYMBOL, exchange=exchange)

    assert depth["status"] == "success"
    assert depth["data"]["instrument"]["symbol"] == _SYMBOL
    assert depth["data"]["instrument"]["exchange"] == exchange
    assert [(level["price"], level["quantity"]) for level in depth["data"]["bids"]] == [(99.5, 8), (99.0, 13)]
    assert [(level["price"], level["quantity"]) for level in depth["data"]["asks"]] == [(100.5, 5), (101.0, 11)]
    events = _audit_events(runtime)
    assert len(events) == 1
    record = events[0]["market_data"]["depth"]
    assert record["value"] == depth["data"]
    assert "error_code" not in record
    assert record["source_as_of"] is None
    assert record["observed_at"]
    assert record["provenance"]["selector"] == {"adapter_id": "dhan", "account_id": "Quotes"}
    assert events[0]["event_id"] == quote["input_receipt"]["event_id"]
    assert events[0]["input_digest"] == quote["input_receipt"]["input_digest"]
    assert runtime.sdk.calls == [
        ("quote_data", {f"{exchange}_EQ": [int(_TOKENS[exchange])]}),
        ("quote_data", {f"{exchange}_EQ": [int(_TOKENS[exchange])]}),
        ("get_fund_limits", None),
    ]
    assert runtime.sandbox.get_orders() == []
    assert runtime.sandbox.get_trades() == []


@pytest.mark.parametrize(
    "malformed_depth",
    [
        None,
        {
            "buy": [{"price": 99.5, "quantity": True, "orders": 1}],
            "sell": [{"price": 100.5, "quantity": 5, "orders": 1}],
        },
        {
            "buy": [{"price": float("nan"), "quantity": 8, "orders": 1}],
            "sell": [{"price": 100.5, "quantity": 5, "orders": 1}],
        },
        {"buy": [{"price": 99.5, "quantity": 8}], "sell": [{"price": 100.5, "quantity": 5, "orders": 1}]},
    ],
    ids=["null-depth", "boolean-quantity", "non-finite-price", "missing-orders"],
)
async def test_malformed_native_depth_blocks_practice_before_any_write(practice_runtime, malformed_depth):
    runtime = practice_runtime
    runtime.sdk.depth = malformed_depth

    with pytest.raises(PracticeAgentError, match="broker_context_invalid_response"):
        await runtime.practice.depth(symbol=_SYMBOL, exchange="NSE")
    decision = await runtime.practice.route_order(
        Order(
            symbol=_SYMBOL,
            exchange=Exchange.NSE,
            action=Action.BUY,
            quantity="1",
            product=Product.MIS,
            pricetype=PriceType.MARKET,
        )
    )

    assert decision.passed is False
    assert decision.response["code"] == "broker_context_invalid_response"
    assert runtime.sandbox.get_orders() == []
    assert runtime.sandbox.get_trades() == []
    assert runtime.audit.list_audit_files() == []
    assert runtime.history.calls == []
    assert runtime.sdk.calls == [("quote_data", {"NSE_EQ": [int(_TOKENS["NSE"])]})] * 4
    assert all(kind != "dispatch_started" for kind, _ in runtime.events)
