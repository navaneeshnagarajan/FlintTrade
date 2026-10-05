"""Memory-only Practice capability over canonical admission and authorised reads.

The adapter owns no broker handle, credentials, account-selection policy or HTTP
transport. Market inputs come from the existing exact-authority, audited broker
context collector. Its quote observation time is checked, but is explicitly not
represented as an exchange timestamp or proof of exchange freshness.

Orders enter the decorated Flask ``place_order`` view, preserving its signed
mode checks, rate limits, Laya admission and sandbox contract lock. There is no
retry or fallback execution path. Any uncertain write/evidence outcome seals
this capability until the operator reconciles and starts a new run.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, ExitStack, contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flask import Flask, jsonify

from .ai_broker_context import DERIVATIVE_EXCHANGES, BrokerAnalysisContext, BrokerContextError
from .backend_instance import BackendLeaseUnavailable, require_backend_lease_proof
from .broker_identity import BrokerSelector
from .broker_read_port import InstrumentLotSizeSnapshot
from .rate_limiter import RateLimiter

EventSink = Callable[[str, dict[str, Any]], None]
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._&:+/\-]{0,127}", re.ASCII)


def practice_entry_kill_code(app: Flask) -> str | None:
    """Observe the shared L5 only; this is not a Live L1–L5 order gate.

    Only a recognised explicit PASS permits a new Practice entry. A missing
    dependency, exception or structurally similar result is not permission.
    Exact reducing sandbox exits retain their separately proven exception.
    """
    from flinttrade_engine.safety import KillSwitch, SafetyResult, SafetySystem, SafetyVerdict

    try:
        safety = app.config.get("SAFETY")
        if type(safety) is not SafetySystem or type(safety.l5_kill) is not KillSwitch:
            raise ValueError
        result = safety.l5_kill.validate()
        if (type(result) is not SafetyResult or result.layer != "L5_KILL"
                or type(result.verdict) is not SafetyVerdict or type(result.passed) is not bool):
            raise ValueError
        if result.verdict is SafetyVerdict.PASS and result.passed is True:
            return None
        if result.verdict is SafetyVerdict.FAIL and result.passed is False:
            return "practice_kill_switch_active"
    except Exception:
        pass
    return "practice_safety_unavailable"


class PracticeAgentError(RuntimeError):
    """Safe, bounded refusal code without credentials or provider errors."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class PracticeOrderResponse:
    """Confirmed sandbox acknowledgement in the trader's executor shape."""

    orderid: str
    status: str
    fill_price: float
    quantity: int

    @property
    def price(self) -> float:
        """Compatibility alias; ``fill_price`` is the authoritative fill."""
        return self.fill_price


@dataclass(frozen=True, slots=True)
class PracticeDecision:
    """Preserve the entire canonical refusal, including a Laya clamp."""

    passed: bool
    error: str
    order_response: PracticeOrderResponse | None
    response: dict[str, Any]


class PracticeAgentAdapter:
    """Read-only data client and Practice-only executor for one operator run.

    ``event_sink`` is synchronous: returning acknowledges durable recording.
    A failure before dispatch prevents the write; a failure afterwards requires
    reconciliation and disables all subsequent writes. ``stop_check`` is a
    thread-safe signal, rechecked after reads and at the canonical boundary.
    Calling ``close`` permanently drops session authority. Never persist this
    object or its private token; the public events never include the token.
    During runtime drain, proven reductions may use only already-receipted
    cached quotes that still pass the ordinary freshness checks.
    """

    def __init__(
        self,
        app: Flask,
        session_token: str,
        *,
        max_quote_age_seconds: float = 30.0,
        event_sink: EventSink | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> None:
        if not isinstance(app, Flask) or not isinstance(app.config.get("RATE_LIMITER"), RateLimiter):
            raise PracticeAgentError("practice_runtime_unavailable")
        if app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True:
            raise PracticeAgentError("practice_runtime_unavailable")
        try:
            self._backend_lease_proof = require_backend_lease_proof(app.config.get("BACKEND_LEASE_PROOF"))
        except BackendLeaseUnavailable:
            raise PracticeAgentError("practice_runtime_unavailable") from None
        if (type(session_token) is not str or not session_token or len(session_token) > 16_384
                or type(max_quote_age_seconds) not in {float, int}
                or not math.isfinite(max_quote_age_seconds) or not 0 < max_quote_age_seconds <= 60):
            raise PracticeAgentError("practice_session_invalid")
        self._app = app
        self.__token = session_token
        self._identity: tuple[str, str] | None = None
        self._max_quote_age = float(max_quote_age_seconds)
        self._event_sink = event_sink
        self._stop_check = stop_check or (lambda: False)
        self._closed = False
        self._reconciliation_required = False
        self._cache: dict[tuple[str, str], BrokerAnalysisContext] = {}
        self._dispatch_lock = asyncio.Lock()
        self.validate_session()

    @property
    def mode(self) -> str:
        """Immutable execution mode; it is never read from caller order fields."""
        return "practice"

    @property
    def reconciliation_required(self) -> bool:
        """Whether a dispatch or its durable evidence has an uncertain outcome."""
        return self._reconciliation_required

    def validate_session(self) -> None:
        """Reverify backend ownership and signed operator session authority."""
        from .auth_routes import decode_token

        if self._closed:
            raise PracticeAgentError("practice_stopped")
        # Background calls do not traverse Flask's before_request hooks.
        # Keep the original minted owner: swapping app configuration cannot
        # transfer an existing adapter to a different runtime incarnation.
        try:
            if self._app.config.get("BACKEND_LEASE_PROOF") is not self._backend_lease_proof:
                raise BackendLeaseUnavailable
            require_backend_lease_proof(self._backend_lease_proof)
        except BackendLeaseUnavailable:
            raise PracticeAgentError("practice_runtime_unavailable") from None
        try:
            with self._app.app_context():
                claims = decode_token(self.__token)
            subject, jti, expiry = claims.get("sub"), claims.get("jti"), claims.get("exp")
            if (
                claims.get("type") != "session" or claims.get("mode") != "practice"
                or claims.get("setup_session") is True
                or type(subject) is not str or not subject.strip() or len(subject.encode()) > 1024
                or type(jti) is not str or not jti.strip() or len(jti.encode()) > 256
                or type(expiry) not in {int, float} or not math.isfinite(expiry)
                or expiry <= datetime.now(UTC).timestamp()
                or (self._identity is not None and self._identity != (subject, jti))
            ):
                raise ValueError
            self._identity = (subject, jti)
        except Exception:
            raise PracticeAgentError("practice_session_invalid") from None

    def close(self) -> None:
        """Permanently discard authority and cached inputs; never dispatch cleanup."""
        self._closed = True
        self.__token = ""
        self._cache.clear()

    def _check_cancellation(self) -> None:
        # Synchronous admission/evidence callbacks can request cancellation
        # without yielding. Do not wait for the next await to brake a write or
        # discard the capability after a result the caller may never receive.
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            self.close()
            raise asyncio.CancelledError

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        if self._event_sink is not None:
            try:
                self._event_sink(kind, deepcopy(payload))
            except Exception:
                self._reconciliation_required = True
                raise PracticeAgentError("practice_reconciliation_required") from None
        self._check_cancellation()

    @staticmethod
    def _instrument(symbol: object, exchange: object) -> tuple[str, str]:
        if (not isinstance(symbol, str) or not _IDENTITY.fullmatch(symbol)
                or not isinstance(exchange, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,15}", exchange)):
            raise PracticeAgentError("practice_order_invalid")
        return symbol, exchange

    def _quote(self, context: BrokerAnalysisContext, symbol: str, exchange: str) -> dict[str, Any]:
        try:
            data = context.market_data
            record = data["quote"]
            value = record["value"]
            instrument = value["instrument"]
            price = value["ltp"]
            observed = datetime.fromisoformat(record["observed_at"])
            age = (datetime.now(UTC) - observed).total_seconds()
            if record.get("source_as_of") is not None:
                source_time = datetime.fromisoformat(record["source_as_of"])
                if source_time.tzinfo is None or not 0 <= (datetime.now(UTC) - source_time).total_seconds() <= self._max_quote_age:
                    raise ValueError
            if (data["symbol"] != symbol or data["exchange"] != exchange
                    or instrument["symbol"] != symbol or instrument["exchange"] != exchange
                    or value["available"] is not True or type(price) not in {int, float}
                    or not math.isfinite(price) or price <= 0
                    or observed.tzinfo is None or not 0 <= age <= self._max_quote_age
                    or not context.receipt.get("event_id") or not context.receipt.get("input_digest")):
                raise ValueError
        except Exception:
            raise PracticeAgentError("practice_market_data_invalid") from None
        self._lot_size(context, symbol, exchange)
        return record

    def _lot_size(self, context: BrokerAnalysisContext, symbol: str, exchange: str) -> int | None:
        """Validate exact, fresh derivative metadata bound to the input digest."""
        if exchange not in DERIVATIVE_EXCHANGES:
            return None
        try:
            data = context.market_data
            record = data["lot_size"]
            value = InstrumentLotSizeSnapshot(**record["value"])
            provenance = record["provenance"]
            quote = data["quote"]
            if (data.get("schema_version") != 1
                    or value.symbol != symbol or value.exchange != exchange
                    or record["request"] != {"exchange": exchange, "symbols": [symbol]}
                    or type(provenance) is not dict or provenance.get("requested_role") != "quote"
                    or provenance != quote["provenance"]):
                raise ValueError
            BrokerSelector(**provenance["selector"])
            quote_id = quote["value"]["instrument"].get("instrument_id")
            if quote_id is not None and value.instrument_id is not None and quote_id != value.instrument_id:
                raise ValueError
            stamps = [record["observed_at"]]
            if record["source_as_of"] is not None:
                stamps.append(record["source_as_of"])
            for stamp in stamps:
                instant = datetime.fromisoformat(stamp)
                if instant.tzinfo is None or not 0 <= (datetime.now(UTC) - instant).total_seconds() <= self._max_quote_age:
                    raise ValueError
            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            if context.receipt["input_digest"] != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
                raise ValueError
            return value.lot_size
        except Exception:
            raise PracticeAgentError("practice_lot_data_invalid") from None

    def _lot_quantity(self, context: BrokerAnalysisContext, body: dict[str, Any]) -> None:
        lot_size = self._lot_size(context, body["symbol"], body["exchange"])
        if lot_size is not None and body["quantity"] % lot_size:
            raise PracticeAgentError("practice_lot_quantity_invalid")

    def _collect(self, symbol: str, exchange: str) -> BrokerAnalysisContext:
        from .ai_broker_context import collect_configured_broker_context

        self.validate_session()
        if self._app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True:
            raise PracticeAgentError("practice_runtime_unavailable")
        with self._app.test_request_context(
            "/api/v1/ai/agent/market-data", method="GET", headers={
                "Authorization": "Bearer " + self.__token, "X-FlintTrade-Mode": "practice",
            },
        ):
            return collect_configured_broker_context(symbol, exchange)

    async def _context(self, symbol: str, exchange: str, *, fresh: bool = False) -> BrokerAnalysisContext:
        self.validate_session()
        self._instrument(symbol, exchange)
        key = (symbol, exchange)
        if not fresh and key in self._cache:
            try:
                self._quote(self._cache[key], symbol, exchange)
                return self._cache[key]
            except PracticeAgentError:
                self._cache.pop(key, None)
        try:
            context = await asyncio.to_thread(self._collect, symbol, exchange)
            self.validate_session()
            if type(context) is not BrokerAnalysisContext:
                raise PracticeAgentError("practice_market_data_invalid")
            self._quote(context, symbol, exchange)
            self._cache[key] = deepcopy(context)
            return context
        except asyncio.CancelledError:
            # Cancelling the await cannot stop a running read thread. It has
            # no write capability; permanently seal dispatch before returning.
            self.close()
            raise
        except PracticeAgentError:
            raise
        except BrokerContextError as exc:
            raise PracticeAgentError(exc.code) from None
        except Exception:
            raise PracticeAgentError("practice_market_data_unavailable") from None

    async def _read_context(self, symbol: str, exchange: str, operation: str) -> BrokerAnalysisContext:
        try:
            return await self._context(symbol, exchange, fresh=operation == "quotes")
        except PracticeAgentError as exc:
            self._emit("data_unavailable", {"code": exc.code, "operation": operation,
                                             "symbol": symbol, "exchange": exchange})
            raise

    async def quotes(self, *, symbol: str, exchange: str) -> dict[str, Any]:
        """Return a validated observed quote, without inventing source freshness."""
        context = await self._read_context(symbol, exchange, "quotes")
        record = self._quote(context, symbol, exchange)
        return {"status": "success", "data": deepcopy(record["value"]),
                "observed_at": record["observed_at"], "source_as_of": record.get("source_as_of"),
                "input_receipt": dict(context.receipt)}

    async def depth(self, *, symbol: str, exchange: str) -> dict[str, Any]:
        """Return authorised depth, or make a missing capability visible."""
        context = await self._read_context(symbol, exchange, "depth")
        value = context.market_data.get("depth", {}).get("value")
        if not isinstance(value, dict):
            error = PracticeAgentError("practice_depth_unavailable")
            self._emit("data_unavailable", {"code": error.code, "operation": "depth",
                                             "symbol": symbol, "exchange": exchange})
            raise error
        return {"status": "success", "data": deepcopy(value)}

    async def history(
        self, *, symbol: str, exchange: str, interval: str, start_date: str, end_date: str,
    ) -> dict[str, Any]:
        """Expose the collector's bounded 5-minute context to the analysis engine."""
        context = await self._read_context(symbol, exchange, "history")
        try:
            value = context.market_data["historical"]["value"]
            if interval != "5m" or value["interval"] != interval or not value["bars"]:
                raise ValueError
            datetime.fromisoformat(start_date)
            datetime.fromisoformat(end_date)
            data = {field: [bar[field] for bar in value["bars"]] for field in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError):
            error = PracticeAgentError("practice_history_unavailable")
            self._emit("data_unavailable", {"code": error.code, "operation": "history",
                                             "symbol": symbol, "exchange": exchange})
            raise error from None
        return {"status": "success", "data": data}

    def _body(self, kwargs: Mapping[str, Any]) -> dict[str, Any]:
        symbol, exchange = self._instrument(kwargs.get("symbol"), kwargs.get("exchange"))
        product, action = kwargs.get("product"), kwargs.get("action")
        quantity = kwargs.get("quantity")
        if type(quantity) is str and quantity.isascii() and quantity.isdigit():
            quantity = int(quantity)
        if (exchange not in {"NSE", "BSE", *DERIVATIVE_EXCHANGES}
                or not isinstance(product, str) or product not in {"MIS", "NRML", "CNC"}
                or action not in {"BUY", "SELL"} or type(quantity) is not int or quantity <= 0
                or kwargs.get("mode", "practice") != "practice"
                or kwargs.get("order_type", kwargs.get("pricetype", "MARKET")) != "MARKET"
                or kwargs.get("variety", "regular") != "regular"
                or any(key in kwargs for key in ("apikey", "api_key", "account_id", "broker", "adapter_id"))):
            raise PracticeAgentError("practice_order_invalid")
        note = kwargs.get("rationale") or kwargs.get("note") or kwargs.get("admission_note") or ""
        strategy = kwargs.get("strategy") or "AutonomousAgent"
        if not isinstance(note, str) or not isinstance(strategy, str):
            raise PracticeAgentError("practice_order_invalid")
        return {"symbol": symbol, "exchange": exchange, "product": product, "action": action,
                "quantity": quantity, "order_type": "MARKET", "strategy": strategy,
                "admission_note": note, "rationale": note}

    def _is_reduction(
        self, body: dict[str, Any], positions: list[dict[str, Any]] | None = None,
        orders: list[dict[str, Any]] | None = None,
    ) -> bool:
        from flinttrade_engine.reduce_only import classify_reduce_only

        try:
            if positions is None or orders is None:
                sandbox = self._app.config.get("DATA_SANDBOX_ENGINE")
                positions, orders = sandbox.get_positions(), sandbox.get_orders()
            if (not isinstance(positions, list) or not isinstance(orders, list)
                    or any(not isinstance(row, dict) for row in [*positions, *orders])):
                raise ValueError
            return classify_reduce_only(
                symbol=body["symbol"], exchange=body["exchange"], product=body["product"],
                action=body["action"], quantity=body["quantity"], positions=positions,
                our_orders=orders, broker_orders=[], live=False,
            ).qualifies
        except Exception:
            return False

    def _dispatch_guard(self, body: dict[str, Any]) -> None:
        self._check_cancellation()
        self.validate_session()
        if self._reconciliation_required:
            raise PracticeAgentError("practice_reconciliation_required")
        # Ordinary draining brakes entries, while an already owned exact
        # reduction may finish. Losing the backend proof above blocks both.
        stopped = self._stop_check() or self._app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True
        kill_code = practice_entry_kill_code(self._app)
        if (stopped or kill_code is not None) and not self._is_reduction(body):
            raise PracticeAgentError(kill_code or "practice_stopped")
        self._check_cancellation()

    def _locked_dispatch_guard(
        self, body: dict[str, Any], positions: list[dict[str, Any]], orders: list[dict[str, Any]],
        context: BrokerAnalysisContext,
    ) -> tuple[Any, int] | AbstractContextManager[None]:
        # This callable is installed only in our in-process request environ.
        # External HTTP request headers/body cannot supply an environ callable.
        try:
            # Re-read under the canonical lock: reset/cancellation can change
            # the sandbox after the pre-admission snapshots were collected.
            self._dispatch_guard(body)
            self._quote(context, body["symbol"], body["exchange"])
            self._lot_quantity(context, body)
        except PracticeAgentError as exc:
            return jsonify(self._refusal(exc.code)), 409
        return self._write_admission(body, context)

    @contextmanager
    def _write_admission(self, body: dict[str, Any], context: BrokerAnalysisContext) -> Iterator[None]:
        """Lease just the synchronous sandbox write, never Laya or evidence I/O."""
        from flinttrade_engine.safety import SafetyBypassError

        self._dispatch_guard(body)
        self._quote(context, body["symbol"], body["exchange"])
        self._lot_quantity(context, body)
        if self._is_reduction(body):
            # Canonical contract lock still owns the fresh reduction proof.
            # This is a sandbox exit, not signed broker emergency authority.
            yield
            return
        with ExitStack() as admission:
            try:
                # The shared normal-write lease orders the L5 latch against
                # the fill, only after slow Laya admission has returned.
                admission.enter_context(self._app.config["SAFETY"].l5_kill.broker_write_admission(False))
            except SafetyBypassError:
                raise PracticeAgentError("practice_kill_switch_active") from None
            yield

    @staticmethod
    def _refusal(code: str) -> dict[str, Any]:
        return {"status": "error", "code": code, "message": code}

    def _confirmed_fill(self, response: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        order_id = response.get("order_id")
        if response.get("status") != "COMPLETE" or type(order_id) is not str or not order_id:
            raise PracticeAgentError("practice_reconciliation_required")
        sandbox = self._app.config.get("DATA_SANDBOX_ENGINE")
        trades = sandbox.get_trades()
        matched = [trade for trade in trades if str(trade.get("order_id") or trade.get("orderid") or "") == order_id]
        if len(matched) != 1:
            raise PracticeAgentError("practice_reconciliation_required")
        trade = matched[0]
        price = trade.get("price")
        if (any(str(trade.get(key)) != str(body[key]) for key in ("symbol", "exchange", "product", "action", "quantity"))
                or type(price) not in {float, int} or not math.isfinite(price) or price <= 0):
            raise PracticeAgentError("practice_reconciliation_required")
        return {**response, "orderid": order_id, "fill_price": float(price), "quantity": body["quantity"]}

    def _dispatch(
        self, body: dict[str, Any], context: BrokerAnalysisContext, *, cached_on_drain: bool = False,
    ) -> dict[str, Any]:
        from flinttrade_core.order_routes import place_order

        self._dispatch_guard(body)
        record = self._quote(context, body["symbol"], body["exchange"])
        self._lot_quantity(context, body)
        # The canonical Practice rule accepts only an explicitly identified LTP.
        # This marker comes from the validated quote receipt, never order input;
        # observation/source timestamps retain their separate evidence meanings.
        body = {**body, "price": float(record["value"]["ltp"]), "price_basis": "ltp"}
        self._emit("dispatch_started", {"mode": "practice", "order": body,
                                       "input_receipt": context.receipt,
                                       "quote_observed_at": record["observed_at"],
                                       "quote_source_as_of": record.get("source_as_of"),
                                       "cached_on_drain": cached_on_drain})
        try:
            self._dispatch_guard(body)
        except PracticeAgentError as exc:
            payload = self._refusal(exc.code)
            self._emit("dispatch_result", {"mode": "practice", "order": body, "response": payload})
            return payload
        try:
            with self._app.test_request_context(
                "/api/v1/orders/place", method="POST", json=body,
                headers={"Authorization": "Bearer " + self.__token, "X-FlintTrade-Mode": "practice"},
                environ_overrides={"flinttrade.practice_agent_guard": lambda body, positions, orders: (
                    self._locked_dispatch_guard(body, positions, orders, context)
                )},
            ):
                response = self._app.make_response(place_order())
                payload = response.get_json()
                if not isinstance(payload, dict):
                    raise ValueError
                payload = {**payload, "http_status": response.status_code}
                if 200 <= response.status_code < 300:
                    payload = self._confirmed_fill(payload, body)
                elif not (400 <= response.status_code < 500 and payload.get("status") == "error"
                          and not payload.get("order_id") and not payload.get("orderid")):
                    raise ValueError
                self._emit("dispatch_result", {"mode": "practice", "order": body, "response": payload})
                return payload
        except asyncio.CancelledError:
            # Once canonical dispatch has begun, cancellation may hide a fill
            # or its durable receipt. Never reuse this capability to retry it.
            self._reconciliation_required = True
            raise
        except Exception:
            self._reconciliation_required = True
            return self._refusal("practice_reconciliation_required")

    async def place_order(self, **kwargs: Any) -> dict[str, Any]:
        """Dispatch once through the canonical view; never resubmit a clamp/error."""
        try:
            async with self._dispatch_lock:
                body = self._body(kwargs)
                self._dispatch_guard(body)
                cached_on_drain = self._app.config.get("RUNTIME_ACCEPTING_REQUESTS") is not True
                try:
                    if cached_on_drain:
                        # _dispatch_guard already proved this exact reduction.
                        # Never refresh through retired broker dependencies or
                        # invent a price when the audited cache is unavailable.
                        context = self._cache.get((body["symbol"], body["exchange"]))
                        if type(context) is not BrokerAnalysisContext:
                            raise PracticeAgentError("practice_market_data_invalid")
                        self._quote(context, body["symbol"], body["exchange"])
                        context = deepcopy(context)
                    else:
                        context = await self._context(body["symbol"], body["exchange"], fresh=True)
                except PracticeAgentError as exc:
                    self._emit("data_unavailable", {"code": exc.code, "operation": "dispatch_quote",
                                                    "symbol": body["symbol"], "exchange": body["exchange"]})
                    raise
                return self._dispatch(body, context, cached_on_drain=cached_on_drain)
        except PracticeAgentError as exc:
            return self._refusal(exc.code)
        except asyncio.CancelledError:
            self.close()
            raise
        except Exception:
            return self._refusal("practice_order_invalid")

    async def route_order(self, order: Any) -> PracticeDecision:
        """Adapt a canonical typed Order into the trader's decision protocol."""
        try:
            fields = order.model_dump(mode="json")
        except (AttributeError, TypeError, ValueError):
            payload = self._refusal("practice_order_invalid")
        else:
            payload = await self.place_order(**fields)
        passed = payload.get("status") == "COMPLETE" and bool(payload.get("orderid"))
        acknowledgement = (
            PracticeOrderResponse(payload["orderid"], "COMPLETE", payload["fill_price"], payload["quantity"])
            if passed else None
        )
        return PracticeDecision(passed, "" if passed else str(payload.get("message") or "Practice order refused"),
                                acknowledgement, payload)
