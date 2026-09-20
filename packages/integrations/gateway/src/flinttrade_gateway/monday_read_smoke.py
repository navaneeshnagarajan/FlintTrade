"""FT-MONDAY-002 native Dhan + Kotak Neo read-smoke (non-funded).

In-process login + ticks / depth / latency (+ hist / chain where the SDK
allows). Never places, modifies, or cancels an order. Successful smoke is
``Connected (read)`` / ``API smoke`` — never placeable Live orders.

Neo has no sandbox. Operator copy is ``Live read only until funded unlock.``
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

CHROME_CONNECTED_READ = "Connected (read)"
CHROME_API_SMOKE = "API smoke"
NEO_OPERATOR_COPY = "Live read only until funded unlock."
MONDAY_READ_BROKERS = frozenset({"dhan", "kotakneo"})
READ_SMOKE_EXTRA_KEY = "read_smoke_ok"
WRITE_VERBS = frozenset({
    "place_order",
    "modify_order",
    "cancel_order",
    "cancel_all",
    "cancel_all_orders",
    "cancel_cover_order",
    "cancel_bracket_order",
})

ReadCall = Callable[[Any, Any], Awaitable[Any]]


@dataclass(frozen=True)
class ReadSmokeStep:
    name: str
    ok: bool
    latency_ms: float
    error: str | None = None
    supported: bool = True


@dataclass
class ReadSmokeResult:
    broker_id: str
    ok: bool
    chrome: str
    steps: list[ReadSmokeStep] = field(default_factory=list)
    operator_copy: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "broker_id": self.broker_id,
            "ok": self.ok,
            "chrome": self.chrome,
            "operator_copy": self.operator_copy,
            "steps": [
                {
                    "name": step.name,
                    "ok": step.ok,
                    "latency_ms": step.latency_ms,
                    "error": step.error,
                    "supported": step.supported,
                }
                for step in self.steps
            ],
        }


def monday_read_connectable(broker_id: str, catalog_connectable: bool = False) -> bool:
    """Dhan + Neo stay selectable for Connected (read) / API smoke.

    A stale catalogue ``connectable=False`` or coming-soon activation block
    must not hide Neo from Setup. Live place stays fail-closed elsewhere.
    """
    if broker_id in MONDAY_READ_BROKERS:
        return True
    return bool(catalog_connectable)


def stamp_monday_read_smoke(session: Any, ok: bool) -> None:
    """Persist smoke evidence on the session. Chrome must read this flag."""
    extra = getattr(session, "extra", None)
    if extra is None:
        try:
            session.extra = {}
        except Exception:  # noqa: BLE001 — read-only handle; skip stamp
            return
        extra = session.extra
    extra[READ_SMOKE_EXTRA_KEY] = bool(ok)


def monday_read_smoke_ok(session: Any) -> bool:
    extra = getattr(session, "extra", None) or {}
    return extra.get(READ_SMOKE_EXTRA_KEY) is True


async def probe_monday_session_reads(
    adapter: Any,
    session: Any,
    *,
    symbols: list[str] | None = None,
) -> bool:
    """REST quotes + depth against an already-logged-in session. Never a write."""
    symbols = list(symbols or ["NSE:RELIANCE"])
    try:
        await adapter.quotes(session, symbols)
        depth = getattr(adapter, "market_depth", None)
        if callable(depth):
            await depth(session, symbols)
    except Exception:  # noqa: BLE001 — failed smoke never paints Connected
        stamp_monday_read_smoke(session, False)
        return False
    stamp_monday_read_smoke(session, True)
    return True


def monday_read_chrome(broker_id: str, *, connected: bool, reads_ok: bool) -> str | None:
    """Honest chrome for the Monday Dhan + Neo path.

    A failed read never paints Connected. Success is Connected (read) / API
    smoke — never a live-order claim.
    """
    if broker_id not in MONDAY_READ_BROKERS:
        return None
    if not connected or not reads_ok:
        return None
    return CHROME_CONNECTED_READ


def _neo_copy(broker_id: str) -> str | None:
    if broker_id == "kotakneo":
        return NEO_OPERATOR_COPY
    return None


async def _timed(name: str, call: Callable[[], Awaitable[Any]]) -> ReadSmokeStep:
    started = time.perf_counter()
    try:
        await call()
    except NotImplementedError as exc:
        latency_ms = (time.perf_counter() - started) * 1000.0
        return ReadSmokeStep(name, False, latency_ms, str(exc) or "unsupported", supported=False)
    except Exception as exc:  # noqa: BLE001 — honest smoke, never fake Connected
        latency_ms = (time.perf_counter() - started) * 1000.0
        return ReadSmokeStep(name, False, latency_ms, str(exc) or exc.__class__.__name__)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return ReadSmokeStep(name, True, latency_ms)


async def run_monday_read_smoke(
    broker_id: str,
    adapter: Any,
    credentials: dict[str, Any],
    *,
    symbols: list[str] | None = None,
    historical_req: dict[str, Any] | None = None,
    option_chain_req: dict[str, Any] | None = None,
) -> ReadSmokeResult:
    """Login + non-funded read smoke. Never a write. Honest on failure."""
    if broker_id not in MONDAY_READ_BROKERS:
        raise ValueError(f"Monday read-smoke is Dhan + Neo only, not {broker_id}")
    symbols = list(symbols or ["NSE:RELIANCE"])
    steps: list[ReadSmokeStep] = []
    session: Any = None

    async def _login() -> Any:
        nonlocal session
        session = await adapter.login(credentials)
        return session

    login_step = await _timed("login", _login)
    steps.append(login_step)
    if not login_step.ok or session is None:
        return ReadSmokeResult(
            broker_id,
            False,
            "",
            steps,
            operator_copy=_neo_copy(broker_id),
        )

    steps.append(await _timed("quotes", lambda: adapter.quotes(session, symbols)))
    depth = getattr(adapter, "market_depth", None)
    if callable(depth):
        steps.append(await _timed("depth", lambda: depth(session, symbols)))
    else:
        steps.append(ReadSmokeStep("depth", False, 0.0, "unsupported", supported=False))

    hist = getattr(adapter, "historical", None)
    if callable(hist) and historical_req is not None:
        steps.append(await _timed("history", lambda: hist(session, historical_req)))
    chain = getattr(adapter, "option_chain", None)
    if callable(chain) and option_chain_req is not None:
        steps.append(await _timed("optionchain", lambda: chain(session, option_chain_req)))

    required = [step for step in steps if step.name in {"login", "quotes", "depth"}]
    ok = all(step.ok or not step.supported for step in required) and all(
        step.ok for step in required if step.supported
    )
    chrome = monday_read_chrome(broker_id, connected=login_step.ok, reads_ok=ok) or ""
    if ok:
        chrome = CHROME_CONNECTED_READ
    if session is not None:
        stamp_monday_read_smoke(session, ok)
    return ReadSmokeResult(broker_id, ok, chrome, steps, operator_copy=_neo_copy(broker_id))
