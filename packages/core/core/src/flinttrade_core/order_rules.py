"""Dated order rules for Indian markets.

One table, loaded from ``data/order_rules.json``, decides which orders the
exchange or broker will refuse, which ones may be refused, and what a broker
does to an order on the way. The order ticket (through its TypeScript mirror of
this evaluator, tested against the same cases), Practice, backtests and the
order API all read the same rows, so the same order gets the same level,
source and message everywhere.

Rules are data. Each row carries an id, an authority (regulatory, exchange or
broker), a level (block, warn or info), a source label, a scope, an
effective-from date and the on-screen message with placeholders. Precedence is
regulatory, then exchange, then broker; within that a block outranks a warn and
a warn outranks an info.

This module does not hold lot sizes (instrument master), charges
(``indian_charges``) or broker behaviour such as attached stop-loss and target
orders (the broker capability profile). Callers pass those facts in.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

from flinttrade_core.symbol_utils import parse_option_symbol

_TABLE_PATH = Path(__file__).parent / "data" / "order_rules.json"

LEVELS: tuple[str, ...] = ("block", "warn", "info")
AUTHORITIES: tuple[str, ...] = ("regulatory", "exchange", "broker", "product")
SCOPE_EXCHANGES: frozenset[str] = frozenset({"all", "NSE", "BSE", "MCX"})
SCOPE_BROKERS: frozenset[str] = frozenset({"all", "dhan", "kotakneo", "practice"})
SCOPE_INSTRUMENTS: frozenset[str] = frozenset({"all", "option", "future", "equity", "derivative"})
SCOPE_ORDER_TYPES: frozenset[str] = frozenset({"all", "MARKET", "LIMIT", "SL", "SL-M"})
CHECKS: frozenset[str] = frozenset(
    {
        "order_type_not_allowed",
        "stop_limit_gap",
        "stop_limit_at_trigger",
        "price_band",
        "order_rate",
        "note",
        "market_price_cap",
        "separate_stop_loss_target",
        "needs_trade_today",
        "order_budget",
        "modification_cap",
        "square_off",
        "live_acknowledgement",
        "circuit_band",
        "market_band",
    }
)
# Checks that are not decided per order: the order throttle, the broker budget
# counters and the Live switch read their rows directly.
NOT_PER_ORDER_CHECKS: frozenset[str] = frozenset(
    {"order_rate", "order_budget", "modification_cap", "live_acknowledgement"}
)

_NSE_VENUES = {"NSE", "NFO", "NSE_FO", "NSE_FNO", "NSE_EQ", "NSE_CM", "CDS", "NSE_INDEX"}
_BSE_VENUES = {"BSE", "BFO", "BSE_FO", "BSE_FNO", "BSE_EQ", "BCD", "BSE_INDEX"}
_DERIVATIVE_VENUES = {"NFO", "NSE_FO", "NSE_FNO", "BFO", "BSE_FO", "BSE_FNO", "MCX", "CDS", "BCD", "NCO"}
_ORDER_TYPE_ALIASES = {
    "MARKET": "MARKET",
    "MKT": "MARKET",
    "LIMIT": "LIMIT",
    "LMT": "LIMIT",
    "SL": "SL",
    "SL-L": "SL",
    "SL_LIMIT": "SL",
    "STOP_LIMIT": "SL",
    "STOP_LOSS": "SL",
    "SL-M": "SL-M",
    "SLM": "SL-M",
    "SL_M": "SL-M",
    "STOP": "SL-M",
    "STOP_LOSS_MARKET": "SL-M",
}
_PAISA = Decimal("0.05")
_IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Current wall-clock time in India; rule dates and session times are IST."""
    return datetime.now(_IST)


def ist_today() -> date:
    """Today's date in India."""
    return ist_now().date()


def ist_minutes() -> int:
    """Minutes since IST midnight, for session-time rules such as square-off."""
    now = ist_now()
    return now.hour * 60 + now.minute


_STRIKE_THEN_SIDE = re.compile(r"\d[-_ ]?(CE|PE|CALL|PUT)$")


@dataclass(frozen=True)
class OrderRule:
    """One dated row of the rules table."""

    id: str
    authority: str
    level: str
    source: str
    check: str
    exchange: str
    broker: str
    instrument: str
    order_types: tuple[str, ...]
    expiry_day: bool | None
    underlying: str | None
    product: str | None
    family: str | None
    unless_broker: tuple[str, ...]
    effective_from: date
    effective_to: date | None
    parameters: Mapping[str, Any]
    message: str
    description: str

    def in_force(self, on: date) -> bool:
        """Whether the row applies on ``on``."""
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


@dataclass(frozen=True)
class RuleResult:
    """The one result shape every check returns."""

    level: str
    source: str
    rule_id: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """JSON view used by the API, MCP tools, Practice and backtests."""
        return {
            "level": self.level,
            "source": self.source,
            "rule_id": self.rule_id,
            "message": self.message,
        }


@dataclass(frozen=True)
class OrderFacts:
    """What the evaluator needs to know about one order.

    ``last_price`` is the desk's last traded price for the contract. The
    exchange measures its band from a moving reference it does not publish, so
    the band is a warning worked out from this price, never a hard refusal.
    """

    symbol: str
    exchange: str
    order_type: str
    action: str = "BUY"
    price: Decimal | None = None
    trigger_price: Decimal | None = None
    last_price: Decimal | None = None
    broker: str = "all"
    broker_name: str = ""
    expiry_day: bool | None = None
    has_stop_loss_or_target: bool = False
    stop_loss_target_placement: str = "attached"
    instrument: str | None = None
    product: str = ""
    traded_today: bool | None = None
    at_minutes: int | None = None
    circuit_low: Decimal | None = None
    circuit_high: Decimal | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=1)
def load_rules() -> tuple[OrderRule, ...]:
    """Return every row of the shared table, in file order."""
    payload = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    rows: list[OrderRule] = []
    for raw in payload["rules"]:
        scope = raw["scope"]
        effective_to = raw.get("effective_to")
        expiry_day = scope.get("expiry_day")
        rows.append(
            OrderRule(
                id=str(raw["id"]),
                authority=str(raw["authority"]),
                level=str(raw["level"]),
                source=str(raw["source"]),
                check=str(raw["check"]),
                exchange=str(scope["exchange"]),
                broker=str(scope["broker"]),
                instrument=str(scope["instrument"]),
                order_types=tuple(str(item) for item in scope["order_types"]),
                expiry_day=None if expiry_day is None else bool(expiry_day),
                underlying=str(scope["underlying"]).upper() if scope.get("underlying") else None,
                product=str(scope["product"]).upper() if scope.get("product") else None,
                family=str(raw["family"]) if raw.get("family") else None,
                unless_broker=tuple(str(item) for item in scope.get("unless_broker") or ()),
                effective_from=date.fromisoformat(str(raw["effective_from"])),
                effective_to=date.fromisoformat(effective_to) if effective_to else None,
                parameters=dict(raw.get("parameters") or {}),
                message=str(raw["message"]),
                description=str(raw["description"]),
            )
        )
    return tuple(rows)


def table_path() -> Path:
    """Absolute path of the shared JSON table."""
    return _TABLE_PATH


def rule_by_id(rule_id: str) -> OrderRule:
    """Return one row by its stable id."""
    for row in load_rules():
        if row.id == rule_id:
            return row
    raise KeyError(rule_id)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalise_order_type(value: object) -> str:
    """Map a broker or engine spelling onto MARKET, LIMIT, SL or SL-M."""
    token = str(getattr(value, "value", value) or "").strip().upper().replace(" ", "_")
    return _ORDER_TYPE_ALIASES.get(token, token)


def exchange_family(exchange: str) -> str:
    """Return NSE, BSE, MCX or the upper-cased venue for anything else."""
    venue = str(exchange or "").strip().upper()
    if venue in _NSE_VENUES:
        return "NSE"
    if venue in _BSE_VENUES:
        return "BSE"
    if venue in {"MCX", "MCX_INDEX"}:
        return "MCX"
    return venue


def instrument_kind(symbol: str, exchange: str) -> str:
    """Classify a contract as option, future or equity from its spelling."""
    name = str(symbol or "").strip().upper()
    venue = str(exchange or "").strip().upper()
    if venue in _DERIVATIVE_VENUES:
        # A strike before CE/PE marks an option; RELIANCE ends in CE but is not one.
        if parse_option_symbol(name) is not None or _STRIKE_THEN_SIDE.search(name):
            return "option"
        return "future"
    return "equity"


def is_option_contract(symbol: str, exchange: str) -> bool:
    """True for an option on a derivatives venue."""
    return instrument_kind(symbol, exchange) == "option"


def contract_expiry(symbol: str) -> date | None:
    """Return the expiry date spelt in an option symbol, when it has a day."""
    parts = parse_option_symbol(str(symbol or ""))
    if parts is None:
        return None
    token = parts.expiry  # e.g. 25NOV26 or NOV26
    if len(token) < 7 or not token[:2].isdigit():
        return None
    try:
        return datetime.strptime(token[:7], "%d%b%y").date()
    except ValueError:
        return None


def underlying_of(symbol: str) -> str:
    """Underlying name of an option or future spelling, else the symbol itself."""
    name = str(symbol or "").strip().upper()
    parts = parse_option_symbol(name)
    if parts is not None:
        return parts.underlying
    for index in ("SENSEX50", "SENSEX", "BANKEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTY"):
        if name.startswith(index):
            return index
    return name


def _minutes(hhmm: str) -> int:
    hours, _, minutes = hhmm.partition(":")
    return int(hours) * 60 + int(minutes or 0)


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation, ValueError:
        return None
    if not number.is_finite():
        return None
    return number


def _money(value: Decimal) -> str:
    """Format rupees the way the ticket does: no trailing .00, else two places."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return str(int(rounded))
    return f"{rounded:.2f}"


def _fill(template: str, values: Mapping[str, object]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


# ---------------------------------------------------------------------------
# Rule arithmetic, shared by the evaluator and tests
# ---------------------------------------------------------------------------


def max_stop_limit_gap(trigger: Decimal, parameters: Mapping[str, Any]) -> Decimal:
    """Largest allowed gap between a stop-loss limit and its trigger."""
    flat_up_to = Decimal(str(parameters.get("flat_gap_up_to_trigger_inr", 50)))
    min_gap = Decimal(str(parameters.get("min_gap_inr", 10)))
    pct = Decimal(str(parameters.get("max_gap_pct", 20)))
    if trigger <= flat_up_to:
        return min_gap
    return (trigger * pct / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def price_band(reference: Decimal, parameters: Mapping[str, Any]) -> tuple[Decimal, Decimal]:
    """Band around ``reference``: the larger of the percentage and the rupee floor."""
    pct = Decimal(str(parameters.get("band_pct", 40)))
    floor = Decimal(str(parameters.get("min_band_inr", 20)))
    width = max(reference * pct / Decimal(100), floor)
    low = max(_PAISA, reference - width)
    high = reference + width
    return (
        low.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        high.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )


def market_price_cap(reference: Decimal, action: str, on: date | None = None) -> Decimal:
    """Worst price a simulated market order may fill at (Practice and backtests)."""
    row = rule_by_id("practice-market-price-cap")
    pct = Decimal(str(row.parameters.get("cap_pct", 3)))
    factor = Decimal(1) + pct / Decimal(100) if str(action).upper() == "BUY" else Decimal(1) - pct / Decimal(100)
    return (reference * factor).quantize(_PAISA, rounding=ROUND_HALF_UP)


def market_band_label(reference: Decimal, parameters: Mapping[str, Any], *, option: bool) -> str:
    """Broker market-protection band for ``reference``, as ``2%`` or ``₹0.10``."""
    tiers = parameters.get("option_tiers" if option else "other_tiers") or []
    for upper, value, unit in tiers:
        if upper is None or reference < Decimal(str(upper)):
            return f"₹{value}" if unit == "inr" else f"{value}%"
    return ""


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


def _scope_matches(row: OrderRule, facts: OrderFacts, venue: str, kind: str, order_type: str) -> bool:
    if row.exchange != "all" and row.exchange != venue:
        return False
    if row.broker != "all" and row.broker != facts.broker:
        return False
    if facts.broker in row.unless_broker:
        return False
    if row.instrument == "derivative":
        if kind not in {"option", "future"}:
            return False
    elif row.instrument != "all" and row.instrument != kind:
        return False
    if row.product is not None and str(facts.product or "").upper() != row.product:
        return False
    if row.underlying is not None and underlying_of(facts.symbol) != row.underlying:
        return False
    if "all" not in row.order_types and order_type not in row.order_types:
        return False
    if row.expiry_day is not None:
        expiry_day = bool(facts.expiry_day)
        if expiry_day != row.expiry_day:
            return False
    return True


def _evaluate_row(row: OrderRule, facts: OrderFacts, order_type: str) -> RuleResult | None:
    source = _fill(row.source, {"broker_name": facts.broker_name or "Broker"})
    if row.check == "order_type_not_allowed":
        return RuleResult(row.level, source, row.id, row.message)
    if row.check == "stop_limit_gap":
        trigger, limit = facts.trigger_price, facts.price
        if trigger is None or limit is None or trigger <= 0 or limit <= 0:
            return None
        gap = max_stop_limit_gap(trigger, row.parameters)
        if abs(limit - trigger) <= gap:
            return None
        return RuleResult(row.level, source, row.id, _fill(row.message, {"max_gap": _money(gap)}))
    if row.check == "stop_limit_at_trigger":
        trigger, limit = facts.trigger_price, facts.price
        if trigger is None or limit is None or limit != trigger:
            return None
        return RuleResult(row.level, source, row.id, row.message)
    if row.check == "price_band":
        reference, limit = facts.last_price, facts.price
        if reference is None or limit is None or reference <= 0 or limit <= 0:
            return None
        low, high = price_band(reference, row.parameters)
        if low <= limit <= high:
            return None
        return RuleResult(row.level, source, row.id, _fill(row.message, {"low": _money(low), "high": _money(high)}))
    if row.check in {"note", "market_price_cap"}:
        return RuleResult(row.level, source, row.id, _fill(row.message, row.parameters))
    if row.check == "separate_stop_loss_target":
        if facts.has_stop_loss_or_target and facts.stop_loss_target_placement == "separate":
            return RuleResult(row.level, source, row.id, row.message)
        return None
    if row.check == "circuit_band":
        low, high, limit = facts.circuit_low, facts.circuit_high, facts.price
        if low is None or high is None or limit is None or low <= 0 or high < low:
            return None
        if low <= limit <= high:
            return None
        return RuleResult(row.level, source, row.id, _fill(row.message, {"low": _money(low), "high": _money(high)}))
    if row.check == "market_band":
        reference = facts.last_price
        if reference is None or reference <= 0:
            return None
        band = market_band_label(
            reference,
            row.parameters,
            option=(facts.instrument or instrument_kind(facts.symbol, facts.exchange)) == "option",
        )
        return RuleResult(row.level, source, row.id, _fill(row.message, {"band": band}))
    if row.check == "needs_trade_today":
        return RuleResult(row.level, source, row.id, row.message) if facts.traded_today is False else None
    if row.check == "square_off":
        if facts.at_minutes is None:
            return None
        cutoff = _minutes(str(row.parameters.get("square_off_from", "15:25")))
        lead = int(row.parameters.get("warn_minutes_before", 5))
        if facts.at_minutes < cutoff - lead:
            return None
        return RuleResult(row.level, source, row.id, _fill(row.message, row.parameters))
    # Throttle, budget, modification and Live-switch rows are read directly.
    return None


def _sort_key(index: int, row: OrderRule) -> tuple[int, int, int]:
    return (LEVELS.index(row.level), AUTHORITIES.index(row.authority), index)


def _with_expiry_day(facts: OrderFacts, kind: str, day: date) -> OrderFacts:
    if facts.expiry_day is not None or kind != "option":
        return facts
    expiry = contract_expiry(facts.symbol)
    return OrderFacts(**{**facts.__dict__, "expiry_day": expiry == day if expiry else False})


def evaluate(facts: OrderFacts, *, on: date | None = None) -> list[RuleResult]:
    """Return every rule result for one order, most serious first."""
    day = on or ist_today()
    venue = exchange_family(facts.exchange)
    kind = facts.instrument or instrument_kind(facts.symbol, facts.exchange)
    order_type = normalise_order_type(facts.order_type)
    facts = _with_expiry_day(facts, kind, day)
    scored: list[tuple[tuple[int, int, int], RuleResult]] = []
    settled_families: set[str] = set()
    for index, row in enumerate(load_rules()):
        if row.check in NOT_PER_ORDER_CHECKS:
            continue
        if row.family is not None and row.family in settled_families:
            continue
        if not row.in_force(day) or not _scope_matches(row, facts, venue, kind, order_type):
            continue
        if row.family is not None:
            # The first matching row of a family decides it, even when it passes.
            settled_families.add(row.family)
        result = _evaluate_row(row, facts, order_type)
        if result is not None:
            scored.append((_sort_key(index, row), result))
    scored.sort(key=lambda item: item[0])
    return [result for _, result in scored]


def stop_loss_limit_price(
    symbol: str,
    exchange: str,
    exit_action: str,
    trigger: Decimal,
    *,
    broker: str = "all",
    product: str = "",
    tick: Decimal = Decimal("0.05"),
    on: date | None = None,
) -> Decimal:
    """Limit price for a protective stop-loss leg.

    The limit sits past ``trigger`` in the exit direction (below it for a sell,
    above it for a buy) by the widest buffer every matching exchange row
    allows: the stop-loss gap and the price band, the band measured from the
    trigger because that is where the last price stands when the stop fires.
    Where no exchange row applies, the default buffer of the
    ``stop_limit_at_trigger`` row is used. The limit is rounded to ``tick``
    toward the trigger so it never leaves the allowed range; a sell limit
    never falls below one tick.
    """
    day = on or ist_today()
    side = str(exit_action).upper()
    facts = OrderFacts(
        symbol=symbol,
        exchange=exchange,
        order_type="SL",
        action=side,
        price=trigger,
        trigger_price=trigger,
        last_price=trigger,
        broker=broker or "all",
        product=str(product or "").upper(),
    )
    venue = exchange_family(exchange)
    kind = instrument_kind(symbol, exchange)
    facts = _with_expiry_day(facts, kind, day)
    limits: list[Decimal] = []
    default_pct: Decimal | None = None
    settled_families: set[str] = set()
    for row in load_rules():
        if row.check not in {"stop_limit_gap", "price_band", "stop_limit_at_trigger"}:
            continue
        if row.family is not None and row.family in settled_families:
            continue
        if not row.in_force(day) or not _scope_matches(row, facts, venue, kind, "SL"):
            continue
        if row.family is not None:
            settled_families.add(row.family)
        if row.check == "stop_limit_gap":
            limits.append(max_stop_limit_gap(trigger, row.parameters))
        elif row.check == "price_band":
            low, high = price_band(trigger, row.parameters)
            limits.append(trigger - low if side == "SELL" else high - trigger)
        else:
            default_pct = Decimal(str(row.parameters.get("default_buffer_pct", 0)))
    if limits:
        buffer = min(limits)
    else:
        buffer = trigger * (default_pct or Decimal(0)) / Decimal(100)
    if side == "SELL":
        ticks = ((trigger - buffer) / tick).to_integral_value(rounding=ROUND_CEILING)
        return max(tick, ticks * tick).quantize(_PAISA)
    ticks = ((trigger + buffer) / tick).to_integral_value(rounding=ROUND_FLOOR)
    return (ticks * tick).quantize(_PAISA)


def _field(order: object, *names: str) -> Any:
    for name in names:
        if isinstance(order, Mapping):
            if name in order and order[name] not in (None, ""):
                return order[name]
        else:
            value = getattr(order, name, None)
            if value not in (None, ""):
                return value
    return None


def facts_from_order(
    order: object,
    *,
    broker: str = "all",
    broker_name: str = "",
    last_price: object = None,
    expiry_day: bool | None = None,
    stop_loss_target_placement: str = "attached",
    traded_today: bool | None = None,
    at_minutes: int | None = None,
    circuit_low: object = None,
    circuit_high: object = None,
) -> OrderFacts:
    """Build :class:`OrderFacts` from an Order model, a mapping or an engine order."""
    order_type = _field(order, "pricetype", "order_type", "price_type", "orderType")
    stop_loss = _decimal(_field(order, "stop_loss_price", "stoploss", "stop_loss"))
    target = _decimal(_field(order, "target_price", "target"))
    action = _field(order, "action", "side", "transaction_type")
    return OrderFacts(
        symbol=str(_field(order, "symbol", "tradingsymbol") or ""),
        exchange=str(getattr(_field(order, "exchange"), "value", _field(order, "exchange")) or ""),
        order_type=normalise_order_type(order_type or ""),
        action=str(getattr(action, "value", action) or "BUY").upper(),
        price=_positive(_decimal(_field(order, "price", "limit_price"))),
        trigger_price=_positive(_decimal(_field(order, "trigger_price", "stop_price", "triggerPrice"))),
        last_price=_positive(_decimal(last_price)),
        broker=broker or "all",
        broker_name=broker_name,
        expiry_day=expiry_day,
        has_stop_loss_or_target=bool((stop_loss and stop_loss > 0) or (target and target > 0)),
        stop_loss_target_placement=stop_loss_target_placement,
        product=str(getattr(_field(order, "product"), "value", _field(order, "product")) or "").upper(),
        traded_today=traded_today,
        at_minutes=at_minutes,
        circuit_low=_positive(_decimal(circuit_low)),
        circuit_high=_positive(_decimal(circuit_high)),
    )


def _positive(value: Decimal | None) -> Decimal | None:
    return value if value is not None and value > 0 else None


def evaluate_order(order: object, *, on: date | None = None, **kwargs: Any) -> list[RuleResult]:
    """Evaluate an Order model, mapping or engine order."""
    return evaluate(facts_from_order(order, **kwargs), on=on)


def blocking(results: Iterable[RuleResult]) -> list[RuleResult]:
    """Only the results that refuse the order."""
    return [result for result in results if result.level == "block"]


def results_payload(results: Iterable[RuleResult]) -> list[dict[str, str]]:
    """JSON list for API and MCP responses."""
    return [result.as_dict() for result in results]


def headline(results: list[RuleResult]) -> str:
    """The ticket line: the most serious result prefixed by its source."""
    if not results:
        return ""
    top = results[0]
    return f"{top.source} · {top.message}"


class OrderRuleRefused(ValueError):
    """An order broke a block-level rule. Carries every result for the caller."""

    http_status = 400

    def __init__(self, results: list[RuleResult]) -> None:
        self.results = results
        blocks = blocking(results)
        super().__init__(headline(blocks or results))


class OrderBudgetExceeded(OrderRuleRefused):
    """A broker's order budget or modification cap would be exceeded."""

    http_status = 429


# ---------------------------------------------------------------------------
# Rows read directly: broker order budget and modification cap
# ---------------------------------------------------------------------------


def _wait_label(seconds: int) -> str:
    """``1 second``, ``40 seconds``, ``3 minutes`` or ``2 hours``, rounded up."""
    if seconds < 60:
        return "1 second" if seconds == 1 else f"{seconds} seconds"
    if seconds < 3600:
        minutes = -(-seconds // 60)
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    hours = -(-seconds // 3600)
    return "1 hour" if hours == 1 else f"{hours} hours"


_WINDOWS: tuple[tuple[str, str, float], ...] = (
    ("per_second", "second", 1.0),
    ("per_minute", "minute", 60.0),
    ("per_hour", "hour", 3600.0),
    ("per_day", "day", 86400.0),
)


def _broker_rows(check: str, broker: str, on: date) -> list[OrderRule]:
    key = str(broker or "").strip().lower()
    return [row for row in load_rules() if row.check == check and row.broker in {key, "all"} and row.in_force(on)]


class OrderBudget:
    """Counts a broker's order writes against its published limits.

    One instance lives in the broker router. ``check_and_record`` refuses a
    write that would go over any window of a ``order_budget`` row, and a
    modify that would go over a ``modification_cap`` row. A refused write is
    not counted. Timestamps are monotonic seconds supplied by the caller so
    tests can drive the clock.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self._writes: dict[str, list[float]] = {}
        self._modifications: dict[tuple[str, str], int] = {}

    def check_and_record(
        self,
        broker: str,
        *,
        now: float,
        on: date | None = None,
        modify_order_id: str | None = None,
        broker_name: str = "",
    ) -> RuleResult | None:
        """Return a block result, or record the write and return None."""
        day = on or ist_today()
        key = str(broker or "").strip().lower()
        budget_rows = _broker_rows("order_budget", key, day)
        cap_rows = _broker_rows("modification_cap", key, day) if modify_order_id else []
        if not budget_rows and not cap_rows:
            return None
        with self._lock:
            history = [stamp for stamp in self._writes.get(key, []) if now - stamp < 86400.0]
            for row in budget_rows:
                source = _fill(row.source, {"broker_name": broker_name or key})
                for param, window, seconds in _WINDOWS:
                    if param not in row.parameters:
                        continue
                    limit = int(row.parameters[param])
                    recent = [stamp for stamp in history if now - stamp < seconds]
                    if len(recent) >= limit:
                        wait = max(1, int(-(-(seconds - (now - min(recent))) // 1)))
                        message = _fill(row.message, {"limit": limit, "window": window, "wait": _wait_label(wait)})
                        return RuleResult(row.level, source, row.id, message)
            for row in cap_rows:
                limit = int(row.parameters["max_modifications"])
                count = self._modifications.get((key, str(modify_order_id)), 0)
                if count >= limit:
                    source = _fill(row.source, {"broker_name": broker_name or key})
                    return RuleResult(row.level, source, row.id, _fill(row.message, {"limit": limit}))
            history.append(now)
            self._writes[key] = history
            if modify_order_id:
                mod_key = (key, str(modify_order_id))
                self._modifications[mod_key] = self._modifications.get(mod_key, 0) + 1
        return None

    def record(self, broker: str, *, now: float, on: date | None = None) -> None:
        """Count a write that must never be refused, such as a cancel."""
        key = str(broker or "").strip().lower()
        if not _broker_rows("order_budget", key, on or ist_today()):
            return
        with self._lock:
            history = [stamp for stamp in self._writes.get(key, []) if now - stamp < 86400.0]
            history.append(now)
            self._writes[key] = history


# ---------------------------------------------------------------------------
# Docs generator
# ---------------------------------------------------------------------------


_BROKER_LABELS = {"dhan": "Dhan", "kotakneo": "Kotak Neo", "practice": "Practice"}


def _scope_label(row: OrderRule) -> str:
    parts = []
    parts.append("all exchanges" if row.exchange == "all" else row.exchange)
    parts.append("all brokers" if row.broker == "all" else _BROKER_LABELS.get(row.broker, row.broker))
    instrument = {"all": "all instruments", "derivative": "futures and options"}.get(
        row.instrument, f"{row.instrument}s"
    )
    parts.append(instrument)
    if "all" not in row.order_types:
        parts.append(", ".join(row.order_types))
    if row.unless_broker:
        labels = ", ".join(_BROKER_LABELS.get(b, b) for b in row.unless_broker)
        parts.append(f"not {labels}")
    if row.underlying:
        parts.append(row.underlying)
    if row.product:
        parts.append(row.product)
    if row.expiry_day is True:
        parts.append("expiry day")
    elif row.expiry_day is False:
        parts.append("not expiry day")
    return " · ".join(parts)


def rules_markdown() -> str:
    """Markdown table of every rule: id, scope, effective-from, description and message."""
    lines = [
        "| Rule id | Scope | Effective from | Description | Message |",
        "|---|---|---|---|---|",
    ]
    for row in load_rules():
        until = f" to {row.effective_to.isoformat()}" if row.effective_to else ""
        message = _fill(row.message, row.parameters).replace("|", "\\|")
        description = row.description.replace("|", "\\|")
        lines.append(
            f"| `{row.id}` | {_scope_label(row)} | {row.effective_from.isoformat()}{until} | {description} | {message} |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "OrderBudget",
    "OrderBudgetExceeded",
    "OrderFacts",
    "OrderRule",
    "OrderRuleRefused",
    "RuleResult",
    "blocking",
    "contract_expiry",
    "evaluate",
    "evaluate_order",
    "exchange_family",
    "facts_from_order",
    "headline",
    "underlying_of",
    "instrument_kind",
    "is_option_contract",
    "load_rules",
    "market_band_label",
    "market_price_cap",
    "max_stop_limit_gap",
    "stop_loss_limit_price",
    "normalise_order_type",
    "price_band",
    "results_payload",
    "rule_by_id",
    "rules_markdown",
    "table_path",
]
