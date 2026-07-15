"""Canonical-to-Dhan mapping tables.

Values are grounded in the official DhanHQ Agent Skill (``dhan-oss/dhanhq-skills``)
and the DhanHQ v2 SDK constants — see that skill's ``SKILL.md`` "Current SDK
Constants" table. These tables back the (gated) DhanAdapter's request building
and instrument resolution; keep them in lock-step with ``DHAN_CAPABILITIES``.
"""

from __future__ import annotations

from datetime import date
import json
import math
import struct
from typing import Any, Callable

# Canonical order type -> Dhan order_type.
ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOP_LOSS",
    "SLM": "STOP_LOSS_MARKET",
}

# Canonical product -> Dhan productType. Note Dhan uses INTRADAY/MARGIN (not
# MIS/NRML); MTF is equity-only (never F&O/commodity/currency — see the skill's
# Product-Type Rules).
PRODUCT_MAP = {
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "NRML": "MARGIN",
    "MTF": "MTF",
}

# Canonical validity -> Dhan validity. GTT maps to Dhan's "forever order" family.
VALIDITY_MAP = {
    "DAY": "DAY",
    "IOC": "IOC",
    "GTT": "FOREVER",
}

# Canonical transaction side -> Dhan transaction_type.
SIDE_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
}

# Canonical exchange -> Dhan exchange_segment. Dhan collapses cash/derivative/
# currency/commodity/index into segment codes (NSE_EQ, NSE_FNO, MCX_COMM, IDX_I …).
EXCHANGE_SEGMENT_MAP = {
    "NSE": "NSE_EQ",
    "BSE": "BSE_EQ",
    "NFO": "NSE_FNO",
    "BFO": "BSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I",
}

# Index underlying -> (security_id, segment). The security master is the
# authoritative source; this is a fast-path index for the common underlyings
# (skill "Instrument Resolution Rules"). Treat as a cache, not the source of truth.
INDEX_SECURITY_IDS = {
    "NIFTY": ("13", "IDX_I"),
    "NIFTY 50": ("13", "IDX_I"),
    "BANKNIFTY": ("25", "IDX_I"),
    "BANK NIFTY": ("25", "IDX_I"),
    "FINNIFTY": ("27", "IDX_I"),
    "MIDCPNIFTY": ("442", "IDX_I"),
    "SENSEX": ("51", "IDX_I"),
}
INDEX_SYMBOLS = frozenset({*INDEX_SECURITY_IDS, "BANKEX"})


def to_dhan_segment(exchange: str) -> str:
    """Map a canonical exchange code to a Dhan ``exchange_segment``.

    Args:
        exchange: Canonical FlintTrade exchange (e.g. ``"NSE"``, ``"NFO"``).

    Returns:
        The Dhan segment code (e.g. ``"NSE_EQ"``, ``"NSE_FNO"``).

    Raises:
        KeyError: If *exchange* has no Dhan segment mapping.
    """
    return EXCHANGE_SEGMENT_MAP[exchange.upper()]


# ---------------------------------------------------------------------------
# Reverse maps (Dhan -> canonical) for response parsing
# ---------------------------------------------------------------------------

SEGMENT_TO_EXCHANGE = {
    "NSE_EQ": "NSE",
    "BSE_EQ": "BSE",
    "NSE_FNO": "NFO",
    "BSE_FNO": "BFO",
    "NSE_CURRENCY": "CDS",
    "BSE_CURRENCY": "BCD",
    "MCX_COMM": "MCX",
    "IDX_I": "NSE_INDEX",
}
DHAN_TO_ORDER_TYPE = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "STOP_LOSS": "SL",
    "STOP_LOSS_MARKET": "SL-M",
}
DHAN_TO_PRODUCT = {
    "INTRADAY": "MIS",
    "CNC": "CNC",
    "MARGIN": "NRML",
    "MTF": "MTF",
    "CO": "MIS",
    "BO": "MIS",
}


class DhanMappingError(ValueError):
    """Raised when an order cannot be translated to / from the Dhan API."""


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_text(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _present_order_number(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        if key not in record:
            continue
        value = record[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        return str(value)
    return None


def _optional_bool(value: Any, *, field: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    normalised = str(value).strip().lower()
    if normalised in {"true", "1"}:
        return True
    if normalised in {"false", "0"}:
        return False
    raise DhanMappingError(f"Dhan {field} is invalid")


def _norm_pricetype(pricetype: str) -> str:
    # FlintTrade uses "SL-M"; the canonical ORDER_TYPE_MAP key is "SLM".
    return str(pricetype).upper().replace("-", "")


# Order validity accepted by Dhan's place/slice endpoints (orders.md): DAY or
# IOC only. ``None`` keeps the broker default (DAY); the forever family maps GTT
# through ``VALIDITY_MAP`` separately.
PLACE_ORDER_VALIDITIES = ("DAY", "IOC")


def _norm_place_validity(validity: Any) -> str:
    """Validate an order validity for the Dhan place/slice surface.

    Args:
        validity: The canonical ``Order.validity`` (``None`` → ``DAY``).

    Returns:
        ``"DAY"`` or ``"IOC"``.

    Raises:
        DhanMappingError: If *validity* is neither ``DAY`` nor ``IOC``.
    """
    if validity is None:
        return "DAY"
    norm = str(validity).upper()
    if norm not in PLACE_ORDER_VALIDITIES:
        raise DhanMappingError(f"Dhan order validity must be DAY or IOC, got {validity!r}")
    return norm


# After-market-order timing (annexure.md "amoTime"): when an AMO is pumped.
AMO_TIMES = ("PRE_OPEN", "OPEN", "OPEN_30", "OPEN_60")


def _norm_amo_time(amo_time: Any) -> str:
    """Validate an after-market-order ``amoTime`` (annexure.md).

    Args:
        amo_time: The requested AMO time (``None`` → ``OPEN``).

    Returns:
        One of ``PRE_OPEN`` / ``OPEN`` / ``OPEN_30`` / ``OPEN_60``.

    Raises:
        DhanMappingError: If *amo_time* is not a documented AMO time.
    """
    if amo_time is None or str(amo_time) == "":
        return "OPEN"
    norm = str(amo_time).upper()
    if norm not in AMO_TIMES:
        raise DhanMappingError(f"Dhan amo_time must be one of {AMO_TIMES}, got {amo_time!r}")
    return norm


# ---------------------------------------------------------------------------
# Request building: FlintTrade Order -> dhanhq.place_order / modify_order kwargs
# ---------------------------------------------------------------------------


def to_place_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a FlintTrade ``Order`` into ``dhanhq.place_order`` keyword args.

    ``security_id`` is resolved by the adapter (Dhan trades by numeric id, not
    symbol). Raises :class:`DhanMappingError` for unmappable enum values.
    """
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise DhanMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_MAP:
        raise DhanMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise DhanMappingError(f"Unsupported product {product!r}")

    try:
        segment = to_dhan_segment(str(order.exchange))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {order.exchange!r}") from exc

    kwargs: dict[str, Any] = {
        "security_id": str(security_id),
        "exchange_segment": segment,
        "transaction_type": SIDE_MAP[side],
        "quantity": int(_num(order.quantity, 0)),
        "order_type": ORDER_TYPE_MAP[ptype],
        "product_type": PRODUCT_MAP[product],
        "price": _num(getattr(order, "price", 0)),
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
        "disclosed_quantity": int(_num(getattr(order, "disclosed_quantity", 0), 0)),
        # The SDK defaults validity='DAY', so an IOC order would silently rest as
        # DAY unless we pass it through (orders.md "validity" param).
        "validity": _norm_place_validity(getattr(order, "validity", None)),
    }
    if tag:
        kwargs["tag"] = tag
    return kwargs


def to_amo_order_payload(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate an ``amo`` ``Order`` into a Dhan ``POST /orders`` REST payload.

    An after-market order is a regular order placed outside market hours: it
    carries ``afterMarketOrder=true`` plus an ``amoTime`` pump window
    (``order.amo_time``, default ``OPEN`` — annexure.md; valid PRE_OPEN/OPEN/
    OPEN_30/OPEN_60 per orders.md).

    NOTE: this does NOT go through ``dhanhq.place_order``. The pinned dhanhq
    2.2.0 ``place_order`` both rejects ``PRE_OPEN`` and — critically — omits
    ``amoTime`` from the wire payload entirely (``_order.py:113``), so the pump
    window never reaches the broker. To deliver real AMO parity we build the
    documented ``/orders`` body ourselves and POST it via the SDK's
    ``DhanHTTP`` transport, exactly as the v2.5 endpoints do. Field names are
    camelCase to match orders.md.
    """
    kwargs = to_place_order_kwargs(order, security_id, tag=tag)
    payload: dict[str, Any] = {
        "transactionType": kwargs["transaction_type"],
        "exchangeSegment": kwargs["exchange_segment"],
        "productType": kwargs["product_type"],
        "orderType": kwargs["order_type"],
        "validity": kwargs["validity"],
        "securityId": kwargs["security_id"],
        "quantity": kwargs["quantity"],
        "disclosedQuantity": kwargs["disclosed_quantity"],
        "price": kwargs["price"],
        "triggerPrice": kwargs["trigger_price"],
        "afterMarketOrder": True,
        "amoTime": _norm_amo_time(getattr(order, "amo_time", None)),
    }
    if tag:
        payload["correlationId"] = tag
    return payload


def _validated_core(order: Any, security_id: str) -> dict[str, Any]:
    """Shared validation + core kwargs for every Dhan order variety."""
    side = str(order.action).upper()
    if side not in SIDE_MAP:
        raise DhanMappingError(f"Unsupported action {side!r}")
    ptype = _norm_pricetype(getattr(order, "pricetype", "MARKET"))
    if ptype not in ORDER_TYPE_MAP:
        raise DhanMappingError(f"Unsupported pricetype {ptype!r}")
    product = str(order.product).upper()
    if product not in PRODUCT_MAP:
        raise DhanMappingError(f"Unsupported product {product!r}")
    try:
        segment = to_dhan_segment(str(order.exchange))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {order.exchange!r}") from exc
    return {
        "security_id": str(security_id),
        "exchange_segment": segment,
        "transaction_type": SIDE_MAP[side],
        "quantity": int(_num(order.quantity, 0)),
        "order_type": ORDER_TYPE_MAP[ptype],
        "product_type": PRODUCT_MAP[product],
        "price": _num(getattr(order, "price", 0)),
    }


# Super orders accept only LIMIT / MARKET entry legs (super-order.md "Order
# Type"); SL / SL-M are not valid super-order entry types.
SUPER_ORDER_TYPES = ("LIMIT", "MARKET")


def to_super_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a ``bracket``/``cover`` ``Order`` into ``dhanhq.place_super_order`` kwargs.

    A Dhan super order carries entry + target + stop-loss legs. ``cover`` orders
    set only the stop-loss leg; ``bracket`` orders set target (and optionally a
    trailing jump) too. The entry leg must be LIMIT or MARKET (super-order.md);
    SL / SL-M entries and brackets that breach the directional rules (BUY needs
    targetPrice > price > stopLossPrice; SELL the inverse — mirrors the SDK's
    ``_super_order.py`` validation) fail closed as a mapped
    :class:`DhanMappingError` rather than a raw ``ValueError`` from the SDK.
    """
    kwargs = _validated_core(order, security_id)
    if kwargs["order_type"] not in SUPER_ORDER_TYPES:
        raise DhanMappingError(
            f"A Dhan super (bracket/cover) order must be LIMIT or MARKET, got {kwargs['order_type']!r}"
        )
    # Dhan's place_super_order rejects price <= 0, so a MARKET super order is
    # structurally impossible — require an entry (limit) price.
    if kwargs["price"] <= 0:
        raise DhanMappingError("A Dhan super (bracket/cover) order needs a limit entry price (MARKET is unsupported)")
    price = kwargs["price"]
    target = _num(getattr(order, "target_price", 0))
    stop_loss = _num(getattr(order, "stop_loss_price", 0))
    variety = str(getattr(order, "variety", "regular")).lower()
    if variety == "cover":
        target = 0.0  # a cover order has no target leg
    if target <= 0 and stop_loss <= 0:
        raise DhanMappingError("A super (bracket/cover) order needs a target_price or stop_loss_price")
    # Directional bracket sanity (mirrors _super_order.py:150) so a malformed
    # bracket fails here as a mapped error, not a raw ValueError 500 from the SDK.
    side = kwargs["transaction_type"]
    if side == "BUY":
        if target > 0 and not target > price:
            raise DhanMappingError("For a BUY super order, target_price must be above the entry price")
        if stop_loss > 0 and not stop_loss < price:
            raise DhanMappingError("For a BUY super order, stop_loss_price must be below the entry price")
    elif side == "SELL":
        if target > 0 and not target < price:
            raise DhanMappingError("For a SELL super order, target_price must be below the entry price")
        if stop_loss > 0 and not stop_loss > price:
            raise DhanMappingError("For a SELL super order, stop_loss_price must be above the entry price")
    kwargs.update(
        {
            "targetPrice": target,
            "stopLossPrice": stop_loss,
            "trailingJump": _num(getattr(order, "trailing_jump", 0)),
        }
    )
    if tag:
        kwargs["tag"] = tag
    return kwargs


def to_slice_order_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate an ``iceberg`` ``Order`` into ``dhanhq.place_slice_order`` kwargs.

    Dhan slices a large order into freeze-quantity legs server-side, so the
    payload mirrors a regular order (the broker performs the slicing).
    """
    return to_place_order_kwargs(order, security_id, tag=tag)


def to_forever_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]:
    """Translate a ``gtt`` ``Order`` into ``dhanhq.place_forever`` kwargs.

    A Dhan forever (GTT / good-till-triggered) order rests until its
    ``trigger_Price`` is hit, then fires at ``price``. Raises if no trigger price
    is supplied (a GTT without a trigger is meaningless).

    When the OCO leg trio (``price1`` / ``trigger_price1`` / ``quantity1``) is
    set on the order, the forever order is placed as ``OCO`` — the second leg
    cancels the first when it triggers (forever.md "Create Forever Order"). The
    trio is all-or-nothing: a partial OCO leg raises rather than silently
    placing a SINGLE order without the protective leg.
    """
    core = _validated_core(order, security_id)
    trigger = _num(getattr(order, "trigger_price", 0))
    if trigger <= 0:
        raise DhanMappingError("A GTT (forever) order needs a trigger_price")
    kwargs = {
        "security_id": core["security_id"],
        "exchange_segment": core["exchange_segment"],
        "transaction_type": core["transaction_type"],
        "product_type": core["product_type"],
        "order_type": core["order_type"],
        "quantity": core["quantity"],
        "price": core["price"],
        "trigger_Price": trigger,
        "order_flag": "SINGLE",
    }
    price1 = _num(getattr(order, "price1", None) or 0)
    trigger1 = _num(getattr(order, "trigger_price1", None) or 0)
    qty1 = int(_num(getattr(order, "quantity1", None) or 0, 0))
    if price1 > 0 or trigger1 > 0 or qty1 > 0:
        if not (price1 > 0 and trigger1 > 0 and qty1 > 0):
            raise DhanMappingError("An OCO forever order needs ALL of price1, trigger_price1 and quantity1")
        kwargs.update(
            {
                "order_flag": "OCO",
                "price1": price1,
                "trigger_Price1": trigger1,
                "quantity1": qty1,
            }
        )
    if tag:
        kwargs["tag"] = tag
    return kwargs


def to_margin_kwargs(order: Any, security_id: str) -> dict[str, Any]:
    """Translate an ``Order`` into ``dhanhq.margin_calculator`` kwargs (pre-trade)."""
    core = _validated_core(order, security_id)
    return {
        "security_id": core["security_id"],
        "exchange_segment": core["exchange_segment"],
        "transaction_type": core["transaction_type"],
        "quantity": core["quantity"],
        "product_type": core["product_type"],
        "price": core["price"],
        "trigger_price": _num(getattr(order, "trigger_price", 0)),
    }


def from_dhan_margin(resp: Any) -> dict[str, Any]:
    """Normalise a Dhan ``/margincalculator`` response into FlintTrade fields."""
    data = unwrap(resp)
    if not isinstance(data, dict):
        data = {}
    total = str(data.get("totalMargin", data.get("total_margin", 0)))
    return {
        "required_margin": total,  # common key across all three native adapters
        "total_margin": total,
        "span_margin": str(data.get("spanMargin", 0)),
        "exposure_margin": str(data.get("exposureMargin", 0)),
        "available_balance": str(data.get("availableBalance", 0)),
        "insufficient_balance": str(data.get("insufficientBalance", 0)),
        "brokerage": str(data.get("brokerage", 0)),
        "leverage": str(data.get("leverage", 0)),
    }


def from_dhan_expiry_list(resp: Any) -> list[str]:
    """Parse a Dhan ``/optionchain/expirylist`` response into expiry-date strings."""
    data = unwrap(resp)
    if isinstance(data, dict):
        data = data.get("data", data)
    if isinstance(data, list):
        return [str(d) for d in data]
    return []


def from_dhan_statement_list(resp: Any) -> list[dict[str, Any]]:
    """Unwrap a Dhan statement response (trade history / ledger) to a row list.

    Statement rows are returned as the broker provides them (informational
    reads), so we surface the unwrapped ``data`` list rather than imposing a
    bespoke normalisation that could mis-key the many statement columns.
    """
    data = unwrap(resp)
    if isinstance(data, dict):
        data = data.get("data", [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def to_modify_order_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``dhanhq.modify_order`` keyword args."""
    ptype = _norm_pricetype(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_MAP.get(ptype, str(changes.get("order_type", "LIMIT"))),
        "leg_name": str(changes.get("leg_name", "ENTRY_LEG")),
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "price": _num(changes.get("price", 0)),
        "trigger_price": _num(changes.get("trigger_price", 0)),
        "disclosed_quantity": int(_num(changes.get("disclosed_quantity", 0), 0)),
        "validity": VALIDITY_MAP.get(str(changes.get("validity", "DAY")).upper(), "DAY"),
    }


# ---------------------------------------------------------------------------
# Forever (GTT) order management — /forever/orders (forever.md)
# ---------------------------------------------------------------------------

# A forever order has an entry leg; an OCO forever order adds a target leg.
FOREVER_ORDER_FLAGS = ("SINGLE", "OCO")

# Forever-order legs (forever.md "Modify Forever Order"): TARGET_LEG is the
# SINGLE leg and the first OCO leg; STOP_LOSS_LEG is the second OCO leg. Unlike
# super orders, a forever order has NO ENTRY_LEG — passing one yields a DH-905
# reject — so the default and the allowed set are the forever pair only.
FOREVER_ORDER_LEGS = ("TARGET_LEG", "STOP_LOSS_LEG")


def to_modify_forever_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``dhanhq.modify_forever`` keyword args.

    Dhan's ``PUT /forever/orders/{order-id}`` allows changing price, quantity,
    order type, disclosed quantity, trigger price and validity per leg
    (forever.md "Modify Forever Order"). ``leg_name`` must be ``TARGET_LEG``
    (SINGLE / first OCO leg) or ``STOP_LOSS_LEG`` (second OCO leg) — ENTRY_LEG is
    a super-order concept and is rejected by the broker (DH-905).
    """
    flag = str(changes.get("order_flag", "SINGLE")).upper()
    if flag not in FOREVER_ORDER_FLAGS:
        raise DhanMappingError(f"Forever order_flag must be SINGLE or OCO, got {flag!r}")
    leg = str(changes.get("leg_name", "TARGET_LEG")).upper()
    if leg not in FOREVER_ORDER_LEGS:
        raise DhanMappingError(f"Forever leg_name must be one of {FOREVER_ORDER_LEGS}, got {leg!r}")
    ptype = _norm_pricetype(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_flag": flag,
        "order_type": ORDER_TYPE_MAP.get(ptype, str(changes.get("order_type", "LIMIT"))),
        "leg_name": leg,
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "price": _num(changes.get("price", 0)),
        "trigger_price": _num(changes.get("trigger_price", 0)),
        "disclosed_quantity": int(_num(changes.get("disclosed_quantity", 0), 0)),
        "validity": VALIDITY_MAP.get(str(changes.get("validity", "DAY")).upper(), "DAY"),
    }


def from_dhan_forever_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise one record of the ``GET /forever/orders`` list response."""
    seg = d.get("exchangeSegment", "")
    option_type, expiry, strike_price, underlying = _option_contract_identity(d)
    return {
        "orderid": str(d.get("orderId", "")),
        "exchange_order_id": str(d.get("exchangeOrderId", "")),
        "correlation_id": str(d.get("correlationId", "")),
        "status": d.get("orderStatus", ""),
        "order_flag": d.get("orderFlag", ""),
        "symbol": d.get("tradingSymbol", ""),
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "pricetype": DHAN_TO_ORDER_TYPE.get(d.get("orderType", ""), d.get("orderType", "")),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "quantity": str(d.get("quantity", 0)),
        "filled_quantity": _optional_text(d, "filledQty", "tradedQty"),
        "price": str(d.get("price", 0)),
        "trigger_price": str(d.get("triggerPrice", 0)),
        "quantity1": str(d.get("quantity1", 0)),
        "price1": str(d.get("price1", 0)),
        "trigger_price1": str(d.get("triggerPrice1", 0)),
        "oco_leg_complete": all(
            key in d and d.get(key) is not None for key in ("quantity1", "price1", "triggerPrice1")
        ),
        "leg_name": d.get("legName", ""),
        "created_at": str(d.get("createTime", "")),
        "option_type": option_type,
        "expiry": expiry,
        "strike_price": strike_price,
        "underlying": underlying,
    }


# ---------------------------------------------------------------------------
# Super order management — /super/orders (super-order.md)
# ---------------------------------------------------------------------------

SUPER_ORDER_LEGS = ("ENTRY_LEG", "TARGET_LEG", "STOP_LOSS_LEG")


def to_modify_super_order_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Translate modify ``changes`` into ``dhanhq.modify_super_order`` kwargs (leg-aware).

    The leg name selects which fields Dhan accepts: ENTRY_LEG takes all of them,
    TARGET_LEG takes only ``targetPrice``, STOP_LOSS_LEG takes ``stopLossPrice``
    + ``trailingJump`` — the SDK builds the per-leg payload from these kwargs.
    """
    leg = str(changes.get("leg_name", "ENTRY_LEG")).upper()
    if leg not in SUPER_ORDER_LEGS:
        raise DhanMappingError(f"Super order leg_name must be one of {SUPER_ORDER_LEGS}, got {leg!r}")
    ptype = _norm_pricetype(changes.get("pricetype", changes.get("order_type", "LIMIT")))
    return {
        "order_id": str(order_id),
        "order_type": ORDER_TYPE_MAP.get(ptype, str(changes.get("order_type", "LIMIT"))),
        "leg_name": leg,
        "quantity": int(_num(changes.get("quantity", 0), 0)),
        "price": _num(changes.get("price", 0)),
        "targetPrice": _num(changes.get("target_price", changes.get("targetPrice", 0))),
        "stopLossPrice": _num(changes.get("stop_loss_price", changes.get("stopLossPrice", 0))),
        "trailingJump": _num(changes.get("trailing_jump", changes.get("trailingJump", 0))),
    }


def from_dhan_super_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise one record of the ``GET /super/orders`` list response.

    Target / stop-loss legs are nested under the entry order as ``legDetails``
    (super-order.md "Super Order List"); they are surfaced as ``legs``.
    """
    seg = d.get("exchangeSegment", "")
    option_type, expiry, strike_price, underlying = _option_contract_identity(d)
    raw_legs = d.get("legDetails")
    legs = [leg for leg in raw_legs if isinstance(leg, dict)] if isinstance(raw_legs, list) else []
    leg_details_valid = (
        len(legs) == 2
        and len(legs) == len(raw_legs)
        and {str(leg.get("legName") or "").strip() for leg in legs} == {"TARGET_LEG", "STOP_LOSS_LEG"}
        and all(bool(str(leg.get("orderStatus") or "").strip()) for leg in legs)
    )
    return {
        "orderid": str(d.get("orderId", "")),
        "exchange_order_id": str(d.get("exchangeOrderId", "")),
        "correlation_id": str(d.get("correlationId", "")),
        "status": d.get("orderStatus", ""),
        "symbol": d.get("tradingSymbol", ""),
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "pricetype": DHAN_TO_ORDER_TYPE.get(d.get("orderType", ""), d.get("orderType", "")),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "quantity": str(d.get("quantity", 0)),
        "price": str(d.get("price", 0)),
        "target_price": str(d.get("targetPrice", 0)),
        "stop_loss_price": str(d.get("stopLossPrice", 0)),
        "trailing_jump": str(d.get("trailingJump", 0)),
        "filled_quantity": _optional_text(d, "filledQty", "tradedQty"),
        "average_price": str(d.get("averageTradedPrice", 0)),
        "legs": legs,
        "leg_details_valid": leg_details_valid,
        "option_type": option_type,
        "expiry": expiry,
        "strike_price": strike_price,
        "underlying": underlying,
    }


# ---------------------------------------------------------------------------
# Position conversion — POST /positions/convert (portfolio.md)
# ---------------------------------------------------------------------------

POSITION_TYPES = ("LONG", "SHORT", "CLOSED")


def _to_dhan_product(value: Any) -> str:
    """Map a canonical (or already-Dhan) product name to Dhan's productType."""
    raw = str(value).upper()
    if raw in PRODUCT_MAP:
        return PRODUCT_MAP[raw]
    if raw in PRODUCT_MAP.values():
        return raw
    raise DhanMappingError(f"Unsupported product {raw!r}")


def to_convert_position_kwargs(req: dict[str, Any], security_id: str) -> dict[str, Any]:
    """Translate a convert-position request into ``dhanhq.convert_position`` kwargs.

    ``req`` carries ``from_product`` / ``to_product`` (canonical MIS/CNC/NRML or
    Dhan INTRADAY/CNC/MARGIN), ``position_type`` (LONG/SHORT/CLOSED),
    ``exchange`` and ``quantity`` (portfolio.md "Convert Position").
    """
    position_type = str(req.get("position_type", "LONG")).upper()
    if position_type not in POSITION_TYPES:
        raise DhanMappingError(f"position_type must be one of {POSITION_TYPES}, got {position_type!r}")
    qty = int(_num(req.get("quantity", req.get("convert_qty", 0)), 0))
    if qty <= 0:
        raise DhanMappingError("convert_position needs a positive quantity")
    try:
        segment = to_dhan_segment(str(req.get("exchange", "NSE")))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {req.get('exchange')!r}") from exc
    return {
        "from_product_type": _to_dhan_product(req.get("from_product", req.get("from_product_type", ""))),
        "exchange_segment": segment,
        "position_type": position_type,
        "security_id": str(security_id),
        "convert_qty": qty,
        "to_product_type": _to_dhan_product(req.get("to_product", req.get("to_product_type", ""))),
    }


# The plain order-placement REST endpoint. Used directly (not via the SDK) for
# after-market orders, because the pinned dhanhq 2.2.0 ``place_order`` drops the
# ``amoTime`` field from its payload (see ``to_amo_order_payload``).
ORDERS_ENDPOINT = "/orders"


# ---------------------------------------------------------------------------
# Conditional Trigger Orders (v2.5) — /alerts/orders (conditional-trigger.md)
# ---------------------------------------------------------------------------

CONDITIONAL_TRIGGER_ENDPOINT = "/alerts/orders"
# Hard-required condition keys per conditional-trigger.md "Place Conditional
# Trigger" parameters. comparisonType / exchangeSegment / securityId / operator /
# timeFrame / expDate / frequency are all marked *required*; indicatorName and
# comparingValue are only *conditionally* required (they depend on
# comparisonType), so the broker validates those. Failing closed on the hard set
# is what the docstring promises.
_CONDITION_REQUIRED_KEYS = (
    "comparisonType",
    "exchangeSegment",
    "securityId",
    "operator",
    "timeFrame",
    "expDate",
    "frequency",
)


def to_conditional_order_leg(order: Any, security_id: str) -> dict[str, Any]:
    """Translate one order leg of a conditional trigger into Dhan's wire shape.

    Field names follow conditional-trigger.md exactly (note ``discQuantity``,
    not ``disclosedQuantity``, and string-typed price fields).
    """
    core = _validated_core(order, security_id)
    return {
        "transactionType": core["transaction_type"],
        "exchangeSegment": core["exchange_segment"],
        "productType": core["product_type"],
        "orderType": core["order_type"],
        "securityId": core["security_id"],
        "quantity": core["quantity"],
        "validity": str(getattr(order, "validity", "DAY") or "DAY").upper(),
        "price": str(core["price"]),
        "discQuantity": str(int(_num(getattr(order, "disclosed_quantity", 0), 0))),
        "triggerPrice": str(_num(getattr(order, "trigger_price", 0))),
    }


def to_conditional_trigger_payload(condition: dict[str, Any], order_legs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the ``POST/PUT /alerts/orders`` request body (condition + orders).

    Raises :class:`DhanMappingError` when a hard-required condition key is
    missing or no order legs are supplied — a trigger with nothing to fire is
    meaningless and must fail closed before reaching the broker.
    """
    if not isinstance(condition, dict):
        raise DhanMappingError("A conditional trigger needs a condition dict")
    missing = [k for k in _CONDITION_REQUIRED_KEYS if not condition.get(k)]
    if missing:
        raise DhanMappingError(f"Conditional trigger condition missing required keys: {missing}")
    if not order_legs:
        raise DhanMappingError("A conditional trigger needs at least one order leg")
    return {"condition": dict(condition), "orders": list(order_legs)}


def extract_alert_id(resp: Any) -> str:
    """Pull the alert id out of a conditional-trigger place/modify/cancel response."""
    data = unwrap(resp)
    if isinstance(data, dict):
        alert_id = data.get("alertId") or data.get("alert_id")
        if alert_id:
            return str(alert_id)
    raise DhanMappingError(f"No alert id in Dhan response: {resp}")


def from_dhan_conditional_trigger(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise one conditional-trigger record (get by id / list responses)."""
    raw_orders = d.get("orders")
    orders = [order for order in raw_orders if isinstance(order, dict)] if isinstance(raw_orders, list) else []
    return {
        "alert_id": str(d.get("alertId", "")),
        "status": d.get("alertStatus", ""),
        "created_at": str(d.get("createdTime", "")),
        "triggered_at": str(d.get("triggeredTime") or ""),
        "last_price": str(d.get("lastPrice", "")),
        "condition": d.get("condition") if isinstance(d.get("condition"), dict) else {},
        "orders": orders,
        "orders_valid": isinstance(raw_orders, list) and len(orders) == len(raw_orders),
    }


# ---------------------------------------------------------------------------
# Trader's Control (v2.5) — /pnlExit + Exit All (traders-control.md, portfolio.md)
# ---------------------------------------------------------------------------

PNL_EXIT_ENDPOINT = "/pnlExit"
EXIT_ALL_ENDPOINT = "/positions"  # DELETE /positions = Exit All (portfolio.md)
PNL_EXIT_PRODUCT_TYPES = ("INTRADAY", "DELIVERY")


def to_pnl_exit_payload(
    profit_value: float,
    loss_value: float,
    product_types: list[str] | None = None,
    enable_kill_switch: bool = False,
) -> dict[str, Any]:
    """Build the ``POST /pnlExit`` request body (traders-control.md "P&L Based Exit").

    ``productType`` accepts INTRADAY / DELIVERY (canonical MIS / CNC are
    translated). At least one of profit/loss must be positive — a P&L exit with
    no thresholds would configure nothing.
    """
    profit = _num(profit_value)
    loss = _num(loss_value)
    if profit <= 0 and loss <= 0:
        raise DhanMappingError("A P&L based exit needs a positive profit_value or loss_value")
    products: list[str] = []
    for p in product_types or ["INTRADAY"]:
        raw = str(p).upper()
        mapped = {"MIS": "INTRADAY", "CNC": "DELIVERY"}.get(raw, raw)
        if mapped not in PNL_EXIT_PRODUCT_TYPES:
            raise DhanMappingError(f"P&L exit productType must be one of {PNL_EXIT_PRODUCT_TYPES}, got {raw!r}")
        products.append(mapped)
    return {
        "profitValue": str(profit),
        "lossValue": str(loss),
        "productType": products,
        "enableKillSwitch": bool(enable_kill_switch),
    }


# ---------------------------------------------------------------------------
# Expired (rolling) options data — POST /charts/rollingoption
# ---------------------------------------------------------------------------

EXPIRED_OPTIONS_INTERVALS = (1, 5, 15, 25, 60)
EXPIRED_OPTIONS_EXPIRY_FLAGS = ("WEEK", "MONTH")
EXPIRED_OPTIONS_OPTION_TYPES = ("CALL", "PUT")
EXPIRED_OPTIONS_FIELDS = ("open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot")


def to_expired_options_kwargs(req: dict[str, Any], security_id: str) -> dict[str, Any]:
    """Translate a rolling-options request into ``dhanhq.expired_options_data`` kwargs.

    Validates the documented enums (expired-options-data.md) and fails closed
    via :class:`DhanMappingError` instead of the SDK's dict-shaped error.
    """
    interval = int(_num(req.get("interval", 1), 1))
    if interval not in EXPIRED_OPTIONS_INTERVALS:
        raise DhanMappingError(f"Expired-options interval must be one of {EXPIRED_OPTIONS_INTERVALS}, got {interval}")
    expiry_flag = str(req.get("expiry_flag", "WEEK")).upper()
    if expiry_flag not in EXPIRED_OPTIONS_EXPIRY_FLAGS:
        raise DhanMappingError(f"expiry_flag must be WEEK or MONTH, got {expiry_flag!r}")
    option_type = str(req.get("option_type", req.get("drv_option_type", "CALL"))).upper()
    if option_type not in EXPIRED_OPTIONS_OPTION_TYPES:
        raise DhanMappingError(f"option_type must be CALL or PUT, got {option_type!r}")
    required = [str(f).lower() for f in (req.get("required_data") or list(EXPIRED_OPTIONS_FIELDS))]
    bad = [f for f in required if f not in EXPIRED_OPTIONS_FIELDS]
    if bad:
        raise DhanMappingError(f"required_data fields not in {EXPIRED_OPTIONS_FIELDS}: {bad}")
    try:
        segment = to_dhan_segment(str(req.get("exchange", "NFO")))
    except KeyError as exc:
        raise DhanMappingError(f"No Dhan segment for exchange {req.get('exchange')!r}") from exc
    return {
        "security_id": str(security_id),
        "exchange_segment": segment,
        "instrument_type": str(req.get("instrument_type", req.get("instrument", "OPTIDX"))),
        "expiry_flag": expiry_flag,
        "expiry_code": int(_num(req.get("expiry_code", 0), 0)),
        "strike": str(req.get("strike", "ATM")),
        "drv_option_type": option_type,
        "required_data": required,
        "from_date": str(req.get("from_date", req.get("start", ""))),
        "to_date": str(req.get("to_date", req.get("end", ""))),
        "interval": interval,
    }


def from_dhan_expired_options(resp: Any) -> dict[str, Any]:
    """Normalise a ``/charts/rollingoption`` response to ``{"ce": ..., "pe": ...}``.

    Each present leg keeps Dhan's parallel arrays (open/high/low/close/iv/oi/
    volume/strike/spot/timestamp); an absent leg is None — the caller decides
    how to frame the series.
    """
    data = unwrap(resp)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]  # the endpoint nests its payload under a second "data"
    if not isinstance(data, dict):
        return {"ce": None, "pe": None}
    ce = data.get("ce")
    pe = data.get("pe")
    return {
        "ce": ce if isinstance(ce, dict) else None,
        "pe": pe if isinstance(pe, dict) else None,
    }


# ---------------------------------------------------------------------------
# Order-update WebSocket (order-update.md)
# ---------------------------------------------------------------------------

ORDER_UPDATE_WSS = "wss://api-order-update.dhan.co"

# Order-update Product letter -> canonical product (order-update.md "Product").
ORDER_UPDATE_PRODUCT = {
    "C": "CNC",
    "I": "MIS",
    "M": "NRML",
    "F": "MTF",
    "V": "MIS",  # CO normalises to intraday, matching DHAN_TO_PRODUCT
    "B": "MIS",  # BO likewise
}
ORDER_UPDATE_SIDE = {"B": "BUY", "S": "SELL"}
ORDER_UPDATE_ORDER_TYPE = {"LMT": "LIMIT", "MKT": "MARKET", "SL": "SL", "SLM": "SL-M"}


def order_update_login_payload(client_id: str, access_token: str) -> dict[str, Any]:
    """Build the order-update WebSocket authorisation message (MsgCode 42)."""
    return {
        "LoginReq": {"MsgCode": 42, "ClientId": str(client_id), "Token": str(access_token)},
        "UserType": "SELF",
    }


def decode_order_update(message: Any) -> dict[str, Any] | None:
    """Decode one order-update WebSocket frame into a normalised dict.

    Accepts the parsed dict or the raw JSON text. Returns None for frames that
    are not ``order_alert`` messages (connection acks, unknown types, junk).
    """
    if isinstance(message, (str, bytes)):
        import json  # noqa: PLC0415

        try:
            message = json.loads(message)
        except (ValueError, TypeError):
            return None
    if not isinstance(message, dict) or message.get("Type") != "order_alert":
        return None
    d = message.get("Data")
    if not isinstance(d, dict):
        return None
    return {
        "orderid": str(d.get("OrderNo", "")),
        "exchange_order_id": str(d.get("ExchOrderNo", "")),
        "status": str(d.get("Status", "")),
        "symbol": d.get("Symbol", ""),
        "exchange": d.get("Exchange", ""),
        "security_id": str(d.get("SecurityId", "")),
        "action": ORDER_UPDATE_SIDE.get(str(d.get("TxnType", "")).upper(), str(d.get("TxnType", ""))),
        "pricetype": ORDER_UPDATE_ORDER_TYPE.get(str(d.get("OrderType", "")).upper(), str(d.get("OrderType", ""))),
        "product": ORDER_UPDATE_PRODUCT.get(str(d.get("Product", "")).upper(), str(d.get("Product", ""))),
        "quantity": str(d.get("Quantity", 0)),
        "filled_quantity": str(d.get("TradedQty", 0)),
        "remaining_quantity": str(d.get("RemainingQuantity", 0)),
        "price": str(d.get("Price", 0)),
        "trigger_price": str(d.get("TriggerPrice", 0)),
        "average_price": str(d.get("AvgTradedPrice", 0)),
        "correlation_id": str(d.get("CorrelationId", "")),
        "updated_at": str(d.get("LastUpdatedTime", "")),
        "raw": d,
    }


# ---------------------------------------------------------------------------
# Response parsing (Dhan -> normalised FlintTrade-shaped dicts)
# ---------------------------------------------------------------------------


def unwrap(resp: Any) -> Any:
    """Unwrap a dhanhq ``{status, data, remarks}`` envelope; raise on failure."""
    if isinstance(resp, dict):
        if resp.get("status") == "failure":
            remarks = resp.get("remarks")
            msg = remarks.get("error_message") if isinstance(remarks, dict) else remarks
            raise DhanMappingError(f"Dhan API error: {msg or resp}")
        if "data" in resp:
            return resp["data"]
    return resp


def extract_order_id(resp: Any) -> str:
    """Pull the order id from a place/modify/cancel response."""
    data = unwrap(resp)
    if isinstance(data, dict):
        oid = data.get("orderId") or data.get("order_id") or data.get("orderid")
        if oid:
            return str(oid)
    raise DhanMappingError(f"No order id in Dhan response: {resp}")


def _option_contract_identity(d: dict[str, Any]) -> tuple[str, str, float, str]:
    raw_option_type = str(d.get("drvOptionType") or "").strip().upper()
    trading_symbol = str(d.get("tradingSymbol") or "")
    symbol_parts = trading_symbol.split("-")
    symbol_option_type = symbol_parts[-1].upper() if symbol_parts else ""
    option_type = {"CALL": "CE", "CE": "CE", "PUT": "PE", "PE": "PE"}.get(
        raw_option_type or symbol_option_type,
        "",
    )
    underlying = ""
    if len(symbol_parts) >= 4 and symbol_parts[-1].upper() in {"CE", "PE"}:
        underlying = "-".join(symbol_parts[:-3])
    raw_strike = d.get("drvStrikePrice")
    if raw_strike in (None, "") and option_type and len(symbol_parts) >= 3:
        raw_strike = symbol_parts[-2]
    return (
        option_type,
        str(d.get("drvExpiryDate") or ""),
        _num(raw_strike),
        underlying,
    )


def from_dhan_order(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan order-book record."""
    seg = d.get("exchangeSegment", "")
    option_type, expiry, strike_price, underlying = _option_contract_identity(d)
    order = {
        "orderid": str(d.get("orderId", "")),
        "exchange_order_id": str(d.get("exchangeOrderId", "")),
        "correlation_id": str(d.get("correlationId", "")),
        "status": d.get("orderStatus", ""),
        "symbol": d.get("tradingSymbol", ""),
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "pricetype": DHAN_TO_ORDER_TYPE.get(d.get("orderType", ""), d.get("orderType", "")),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "option_type": option_type,
        "expiry": expiry,
        "strike_price": strike_price,
        "underlying": underlying,
        "leg_name": str(d.get("legName", "")),
        "remarks": str(d.get("omsErrorDescription") or d.get("remarks") or d.get("Remarks") or ""),
    }
    for field, source_fields in {
        "quantity": ("quantity",),
        "filled_quantity": ("filledQty", "tradedQty"),
        "price": ("price",),
        "trigger_price": ("triggerPrice",),
        "average_price": ("averageTradedPrice",),
    }.items():
        value = _present_order_number(d, *source_fields)
        if value is not None:
            order[field] = value
    return order


def from_dhan_position(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan position record."""
    seg = d.get("exchangeSegment", "")
    carry_buy = d.get("carryForwardBuyQty")
    carry_sell = d.get("carryForwardSellQty")
    day_buy = d.get("dayBuyQty")
    day_sell = d.get("daySellQty")
    net_quantity = d.get("netQty")
    accounting_complete = all(
        value is not None for value in (carry_buy, carry_sell, day_buy, day_sell, net_quantity)
    )
    if accounting_complete:
        try:
            accounting_matches = int(net_quantity) == (
                int(carry_buy) - int(carry_sell) + int(day_buy) - int(day_sell)
            )
        except (TypeError, ValueError, OverflowError) as exc:
            raise DhanMappingError("Dhan position accounting is invalid") from exc
        if not accounting_matches:
            raise DhanMappingError("Dhan position accounting is inconsistent")
    trading_symbol = str(d.get("tradingSymbol") or "")
    option_type, expiry, strike_price, underlying = _option_contract_identity(d)
    return {
        "symbol": trading_symbol,
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "quantity": str(d.get("netQty", "")),
        "average_price": str(d.get("costPrice", d.get("buyAvg", 0))),
        "buy_quantity": str(d.get("buyQty", 0)),
        "sell_quantity": str(d.get("sellQty", 0)),
        "buy_avg": str(d.get("buyAvg", 0)),
        "sell_avg": str(d.get("sellAvg", 0)),
        "pnl": str(_num(d.get("realizedProfit", 0)) + _num(d.get("unrealizedProfit", 0))),
        "multiplier": d.get("multiplier"),
        "fx_rate": d.get("rbiReferenceRate", d.get("referenceRate")),
        "close_price": d.get("closePrice"),
        "previous_close_trusted": False,
        "cross_currency": _optional_bool(d.get("crossCurrency"), field="crossCurrency"),
        "overnight_quantity": str(_num(carry_buy) - _num(carry_sell)),
        "day_buy_quantity": str(day_buy or 0),
        "day_sell_quantity": str(day_sell or 0),
        "carry_forward_buy_quantity": str(carry_buy or 0),
        "carry_forward_sell_quantity": str(carry_sell or 0),
        "accounting_complete": accounting_complete,
        "option_type": option_type,
        "expiry": expiry,
        "strike_price": strike_price,
        "underlying": underlying,
    }


def from_dhan_holding(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan holding record."""
    raw_exchange = d.get("exchange", d.get("exchangeSegment", ""))
    raw_product = d.get("productType") or "CNC"
    total_quantity = d.get("totalQty")
    settled_quantity = d.get("dpQty")
    t1_quantity = d.get("t1Qty")
    accounting_complete = all(
        value is not None for value in (total_quantity, settled_quantity, t1_quantity)
    )
    if accounting_complete:
        try:
            accounting_matches = int(total_quantity) == int(settled_quantity) + int(t1_quantity)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DhanMappingError("Dhan holding accounting is invalid") from exc
        if not accounting_matches:
            raise DhanMappingError("Dhan holding accounting is inconsistent")
    return {
        "symbol": d.get("tradingSymbol", ""),
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(raw_exchange, raw_exchange),
        "product": DHAN_TO_PRODUCT.get(raw_product, raw_product),
        "quantity": str(total_quantity if total_quantity is not None else ""),
        "average_price": str(d.get("avgCostPrice", 0)),
        "ltp": str(d.get("lastTradedPrice", 0)),
        "multiplier": d.get("multiplier"),
        "fx_rate": d.get("rbiReferenceRate", d.get("referenceRate")),
        "close_price": d.get("closePrice"),
        "previous_close_trusted": False,
        "cross_currency": _optional_bool(d.get("crossCurrency"), field="crossCurrency"),
        "settled_quantity": str(settled_quantity or 0),
        "t1_quantity": str(t1_quantity or 0),
        "accounting_complete": accounting_complete,
    }


def from_dhan_trade(d: dict[str, Any]) -> dict[str, Any]:
    """Normalise a Dhan trade-book record."""
    seg = d.get("exchangeSegment", "")
    return {
        "orderid": str(d.get("orderId", "")),
        "symbol": d.get("tradingSymbol", ""),
        "instrument_id": str(d.get("securityId", "")),
        "exchange": SEGMENT_TO_EXCHANGE.get(seg, seg),
        "action": d.get("transactionType", ""),
        "quantity": str(d.get("tradedQuantity", d.get("quantity", 0))),
        "price": str(d.get("tradedPrice", d.get("price", 0))),
        "product": DHAN_TO_PRODUCT.get(d.get("productType", ""), d.get("productType", "")),
        "timestamp": str(d.get("exchangeTime", d.get("createTime", ""))),
        "multiplier": d.get("multiplier"),
        "fx_rate": d.get("rbiReferenceRate", d.get("referenceRate")),
        "cross_currency": _optional_bool(d.get("crossCurrency"), field="crossCurrency"),
    }


def from_dhan_funds(resp: Any) -> dict[str, Any]:
    """Normalise the Dhan fund-limit response."""
    d = unwrap(resp)
    if not isinstance(d, dict):
        return {
            "available_balance": "0",
            "used_margin": "0",
            "total_balance": "0",
            "opening_risk_capital": "0",
        }
    # Dhan's API uses the (sic) spelling "availabelBalance".
    available = d.get("availabelBalance", d.get("availableBalance", 0))
    used = d.get("utilizedAmount", 0)
    total = d.get("sodLimit", available)
    return {
        "available_balance": str(available),
        "used_margin": str(used),
        "total_balance": str(total),
        "opening_risk_capital": str(d.get("sodLimit", 0)),
        "extra": d,
    }


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

# Dhan intraday candle intervals (minutes). Anything else falls back to daily.
DHAN_INTRADAY_INTERVALS = {1, 5, 15, 25, 60}


def interval_to_dhan(interval: str) -> tuple[str, int]:
    """Map a FlintTrade interval to ``(kind, minutes)`` where kind is
    ``"intraday"`` or ``"daily"`` (minutes is 0 for daily)."""
    raw = str(interval).strip().lower()
    if raw in {"d", "1d", "day", "daily"}:
        return "daily", 0
    digits = "".join(ch for ch in raw if ch.isdigit())
    minutes = int(digits) if digits else 1
    if "h" in raw:  # hourly → minutes
        minutes *= 60
    if minutes not in DHAN_INTRADAY_INTERVALS:
        # snap to the nearest supported intraday interval; on a tie prefer the
        # larger interval (fewer requests / less over-sampling).
        target = minutes
        minutes = min(DHAN_INTRADAY_INTERVALS, key=lambda m: (abs(m - target), -m))
    return "intraday", minutes


def to_candles_dict(symbol: str, exchange: str, interval: str, resp: Any) -> dict[str, Any]:
    """Map a Dhan historical response (parallel arrays) to a Candles-shaped dict."""
    d = unwrap(resp) or {}
    opens = d.get("open", []) or []
    highs = d.get("high", []) or []
    lows = d.get("low", []) or []
    closes = d.get("close", []) or []
    vols = d.get("volume", []) or []
    stamps = d.get("timestamp", []) or []
    n = min(len(opens), len(highs), len(lows), len(closes))
    bars = [
        {
            "timestamp": str(stamps[i]) if i < len(stamps) else "",
            "open": _num(opens[i]),
            "high": _num(highs[i]),
            "low": _num(lows[i]),
            "close": _num(closes[i]),
            "volume": int(_num(vols[i])) if i < len(vols) else 0,
        }
        for i in range(n)
    ]
    return {"symbol": symbol, "exchange": exchange, "interval": str(interval), "bars": bars}


def from_dhan_quote(symbol: str, exchange: str, q: dict[str, Any]) -> dict[str, Any]:
    """Map a single Dhan quote record (marketfeed/quote) to a Quote-shaped dict."""
    ohlc = q.get("ohlc", {}) or {}
    return {
        "symbol": symbol,
        "exchange": exchange,
        "ltp": _num(q.get("last_price", q.get("ltp", 0))),
        "open": _num(ohlc.get("open", 0)),
        "high": _num(ohlc.get("high", 0)),
        "low": _num(ohlc.get("low", 0)),
        "close": _num(ohlc.get("close", 0)),
        "volume": int(_num(q.get("volume", 0))),
        "oi": int(_num(q.get("oi", 0))),
    }


def quote_from_feed(segment: str, security_id: str, feed: Any) -> dict[str, Any] | None:
    """Pull one security's quote dict out of the nested marketfeed/quote payload.

    The live SDK transport (``dhan_http._parse_response``) puts the whole REST
    body under ``data``, and ``/marketfeed/quote`` itself nests its payload under
    a second ``data`` (market-quote.md) — so the live shape is
    ``data.data.<SEGMENT>.<securityId>``. After :func:`unwrap` peels the outer
    ``data``, this peels the inner one when present (matching how
    :func:`from_dhan_expiry_list` / :func:`from_dhan_expired_options` already
    handle the double-nest) before reading ``{segment: {security_id: {...}}}``.
    """
    data = unwrap(feed)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]  # peel the endpoint's second "data" nest
    if not isinstance(data, dict):
        return None
    by_seg = data.get(segment)
    if not isinstance(by_seg, dict):
        return None
    rec = by_seg.get(str(security_id))
    return rec if isinstance(rec, dict) else None


def _option_chain_number(value: Any, *, field: str, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise DhanMappingError(f"Dhan option chain has an invalid {field}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DhanMappingError(f"Dhan option chain has an invalid {field}") from exc
    if not math.isfinite(number):
        raise DhanMappingError(f"Dhan option chain has an invalid {field}")
    return number


def _option_chain_oi(value: Any, *, field: str) -> int | None:
    """Return observed OI without turning an absent field into zero."""
    if value in (None, ""):
        return None
    number = _option_chain_number(value, field=field)
    if number < 0 or not number.is_integer():
        raise DhanMappingError(f"Dhan option chain has an invalid {field}")
    return int(number)


def _leg(leg: dict[str, Any], side: str) -> dict[str, Any]:
    """Map one CE/PE leg of a Dhan option-chain strike to ce_*/pe_* fields."""
    if not isinstance(leg, dict):
        raise DhanMappingError(f"Dhan option chain has an invalid {side} leg")
    greeks = leg.get("greeks")
    if greeks is None:
        greeks = {}
    if not isinstance(greeks, dict):
        raise DhanMappingError(f"Dhan option chain has invalid {side} Greeks")
    greek_values = tuple(greeks.get(name) for name in ("delta", "gamma", "theta", "vega"))
    complete_values = (*greek_values, leg.get("implied_volatility"))
    greeks_complete = all(value not in (None, "") and not isinstance(value, bool) for value in complete_values)
    if greeks_complete:
        greeks_complete = all(
            not isinstance(value, bool) and math.isfinite(_option_chain_number(value, field=f"{side} Greek"))
            for value in complete_values
        )
    security_id = leg.get("security_id") or leg.get("securityId") or ""
    if isinstance(security_id, bool):
        raise DhanMappingError(f"Dhan option chain has an invalid {side} security_id")
    mapped = {
        f"{side}_instrument_id": str(security_id).strip(),
        f"{side}_ltp": _option_chain_number(leg.get("last_price"), field=f"{side} last_price"),
        f"{side}_volume": int(_option_chain_number(leg.get("volume"), field=f"{side} volume")),
        f"{side}_iv": _option_chain_number(leg.get("implied_volatility"), field=f"{side} implied_volatility"),
        f"{side}_delta": _option_chain_number(greeks.get("delta"), field=f"{side} delta"),
        f"{side}_gamma": _option_chain_number(greeks.get("gamma"), field=f"{side} gamma"),
        f"{side}_theta": _option_chain_number(greeks.get("theta"), field=f"{side} theta"),
        f"{side}_vega": _option_chain_number(greeks.get("vega"), field=f"{side} vega"),
        f"{side}_bid": _option_chain_number(leg.get("top_bid_price"), field=f"{side} top_bid_price"),
        f"{side}_ask": _option_chain_number(leg.get("top_ask_price"), field=f"{side} top_ask_price"),
        f"{side}_greeks_complete": greeks_complete,
    }
    oi = _option_chain_oi(leg.get("oi"), field=f"{side} oi")
    if oi is not None:
        mapped[f"{side}_oi"] = oi
    return mapped


# ---------------------------------------------------------------------------
# Binary market feed (live tick stream)
# ---------------------------------------------------------------------------

# Dhan v2 binary feed response codes (first byte of each packet). 15/17 are the
# subscription REQUEST codes which some feed builds echo back; the documented
# RESPONSE codes (annexure.md "Feed Response Code") are 2 Ticker / 4 Quote /
# 8 Full — both spellings are decoded.
DHAN_FEED_TICKER = 15
DHAN_FEED_QUOTE = 17
DHAN_FEED_TICKER_RESP = 2
DHAN_FEED_QUOTE_RESP = 4
DHAN_FEED_FULL_RESP = 8

# Subscribe-mode -> live-feed RequestCode (marketfeed.py constants: Ticker=15,
# Quote=17, Full=21; v2 feed accepts exactly these three).
SUBSCRIBE_MODE_TO_REQUEST_CODE = {
    "TICKER": 15,
    "LTP": 15,
    "QUOTE": 17,
    "FULL": 21,
}

# Market-depth feeds (full-market-depth.md): subscribe RequestCode 23 on
# wss://depth-api-feed.dhan.co/twentydepth (20-level, <=50 instruments/conn) and
# wss://full-depth-api.dhan.co/twohundreddepth (200-level, 1 instrument/conn).
DHAN_DEPTH_REQUEST_CODE = 23
DHAN_DEPTH_BID = 41
DHAN_DEPTH_ASK = 51
DHAN_DEPTH_DISCONNECT = 50
DHAN_DEPTH_LEVELS = (20, 200)
# Depth header: int16 msg length, byte response code, byte segment, int32
# security id, uint32 (sequence for 20-level; row count for 200-level).
_DEPTH_HEADER = struct.Struct("<hBBiI")
_DEPTH_ROW = struct.Struct("<dII")  # float64 price, uint32 quantity, uint32 orders


def subscribe_mode_to_request_code(mode: str) -> int:
    """Map a canonical subscribe mode (TICKER/QUOTE/FULL) to the feed RequestCode.

    Raises:
        DhanMappingError: If *mode* is not a Dhan v2 feed mode.
    """
    code = SUBSCRIBE_MODE_TO_REQUEST_CODE.get(str(mode).upper())
    if code is None:
        raise DhanMappingError(
            f"Unsupported Dhan feed mode {mode!r} — expected one of {sorted(set(SUBSCRIBE_MODE_TO_REQUEST_CODE))}"
        )
    return code


# Feed exchange-segment byte → canonical exchange.
FEED_SEGMENT_TO_EXCHANGE = {
    0: "NSE_INDEX",
    1: "NSE",
    2: "NFO",
    3: "CDS",
    4: "BSE",
    5: "MCX",
    7: "BCD",
    8: "BFO",
}


def _decode_5_level_depth(blob: bytes) -> list[dict[str, Any]]:
    """Decode the 100-byte 5-level depth block of a Full packet (<IIHHff x5)."""
    packet = struct.Struct("<IIHHff")
    depth: list[dict[str, Any]] = []
    for i in range(5):
        bid_qty, ask_qty, bid_orders, ask_orders, bid_price, ask_price = packet.unpack_from(blob, i * packet.size)
        depth.append(
            {
                "bid_quantity": int(bid_qty),
                "ask_quantity": int(ask_qty),
                "bid_orders": int(bid_orders),
                "ask_orders": int(ask_orders),
                "bid_price": round(bid_price, 2),
                "ask_price": round(ask_price, 2),
            }
        )
    return depth


def decode_dhan_tick(data: bytes) -> dict[str, Any] | None:
    """Decode one Dhan binary market-feed packet into a normalised tick dict.

    Dhan streams a packed binary frame whose first byte is a response code.
    The documented response codes (annexure.md) are 2 = Ticker, 4 = Quote,
    8 = Full; the subscription request-code spellings 15/17 are accepted too.
    The header is ``<BHBIf`` = code, message-length, exchange-segment,
    security-id, LTP. Returns None for short or unrecognised packets.
    """
    if data is None or len(data) < 16:
        return None
    code = struct.unpack_from("<B", data, 0)[0]
    if code in (DHAN_FEED_TICKER, DHAN_FEED_TICKER_RESP):
        _, _, seg, security_id, ltp, _ltt = struct.unpack_from("<BHBIfI", data, 0)
        return {
            "code": code,
            "security_id": str(security_id),
            "exchange": FEED_SEGMENT_TO_EXCHANGE.get(seg, ""),
            "ltp": round(ltp, 2),
        }
    if code in (DHAN_FEED_QUOTE, DHAN_FEED_QUOTE_RESP) and len(data) >= 50:
        fields = struct.unpack_from("<BHBIfHIfIIIffff", data, 0)
        # 0 code, 1 msglen, 2 seg, 3 security_id, 4 ltp, 5 ltq, 6 ltt, 7 atp,
        # 8 volume, 9 total_sell_qty, 10 total_buy_qty, 11 open, 12 close, 13 high, 14 low
        return {
            "code": code,
            "security_id": str(fields[3]),
            "exchange": FEED_SEGMENT_TO_EXCHANGE.get(fields[2], ""),
            "ltp": round(fields[4], 2),
            "volume": int(fields[8]),
            "open": round(fields[11], 2),
            "close": round(fields[12], 2),
            "high": round(fields[13], 2),
            "low": round(fields[14], 2),
        }
    if code == DHAN_FEED_FULL_RESP and len(data) >= 162:
        f = struct.unpack_from("<BHBIfHIfIIIIIIffff100s", data, 0)
        # 0 code, 1 msglen, 2 seg, 3 security_id, 4 ltp, 5 ltq, 6 ltt, 7 atp,
        # 8 volume, 9 sell_qty, 10 buy_qty, 11 oi, 12 oi_high, 13 oi_low,
        # 14 open, 15 close, 16 high, 17 low, 18 depth-blob (5 levels)
        return {
            "code": code,
            "security_id": str(f[3]),
            "exchange": FEED_SEGMENT_TO_EXCHANGE.get(f[2], ""),
            "ltp": round(f[4], 2),
            "volume": int(f[8]),
            "oi": int(f[11]),
            "open": round(f[14], 2),
            "close": round(f[15], 2),
            "high": round(f[16], 2),
            "low": round(f[17], 2),
            "depth": _decode_5_level_depth(f[18]),
        }
    return None


def iter_dhan_depth_messages(data: bytes) -> list[dict[str, Any]]:
    """Decode a 20/200-level depth WebSocket frame into per-side messages.

    A frame may concatenate several messages; each starts with the 12-byte
    header ``<hBBiI`` (message length, response code 41 = Bid / 51 = Ask,
    exchange segment, security id, sequence/row count) followed by
    ``<dII`` rows (price float64, quantity uint32, orders uint32) — the layout
    decoded by the pinned SDK's ``fulldepth.py``. Unknown codes and truncated
    trailers are skipped, never raised.
    """
    out: list[dict[str, Any]] = []
    if not data:
        return out
    offset = 0
    while offset + _DEPTH_HEADER.size <= len(data):
        msg_length, msg_code, seg, security_id, n_rows = _DEPTH_HEADER.unpack_from(data, offset)
        if msg_length <= 0 or offset + msg_length > len(data):
            break
        if msg_code in (DHAN_DEPTH_BID, DHAN_DEPTH_ASK):
            body = data[offset + _DEPTH_HEADER.size : offset + msg_length]
            max_rows = min(len(body) // _DEPTH_ROW.size, 200)
            levels = [
                {
                    "price": _DEPTH_ROW.unpack_from(body, i * _DEPTH_ROW.size)[0],
                    "quantity": int(_DEPTH_ROW.unpack_from(body, i * _DEPTH_ROW.size)[1]),
                    "orders": int(_DEPTH_ROW.unpack_from(body, i * _DEPTH_ROW.size)[2]),
                }
                for i in range(max_rows)
            ]
            out.append(
                {
                    "code": int(msg_code),
                    "side": "bid" if msg_code == DHAN_DEPTH_BID else "ask",
                    "security_id": str(security_id),
                    "exchange": FEED_SEGMENT_TO_EXCHANGE.get(seg, ""),
                    "rows": int(n_rows),
                    "depth": levels,
                }
            )
        offset += msg_length
    return out


# ---------------------------------------------------------------------------
# Scrip master (instruments.md) — security-resolver source
# ---------------------------------------------------------------------------

SCRIP_MASTER_URLS = {
    "compact": "https://images.dhan.co/api-data/api-scrip-master.csv",
    "detailed": "https://images.dhan.co/api-data/api-scrip-master-detailed.csv",
}

# (EXCH_ID, SEGMENT letter) -> canonical exchange. Segment letters per
# instruments.md: C currency, D derivatives, E equity, M commodity, I index.
_SCRIP_EXCHANGE = {
    ("NSE", "E"): "NSE",
    ("NSE", "D"): "NFO",
    ("NSE", "C"): "CDS",
    ("NSE", "I"): "NSE_INDEX",
    ("BSE", "E"): "BSE",
    ("BSE", "D"): "BFO",
    ("BSE", "C"): "BCD",
    ("BSE", "I"): "BSE_INDEX",
    ("MCX", "M"): "MCX",
}


def _scrip_field(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _normalise_scrip_expiry(value: str) -> str:
    candidate = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        return ""


_REVERSE_LOOKUP_PREFIX = "\x00flinttrade:dhan-security-id:"
_REVERSE_RESULT_PREFIX = "\x00flinttrade:dhan-security-result:"


def _scrip_security_identity(row: dict[str, Any], security_id: str, exchange: str) -> dict[str, Any] | None:
    trading_symbol = _scrip_field(row, "SEM_TRADING_SYMBOL", "TRADING_SYMBOL")
    symbol = trading_symbol or _scrip_field(
        row,
        "SEM_CUSTOM_SYMBOL",
        "DISPLAY_NAME",
        "SM_SYMBOL_NAME",
        "SYMBOL_NAME",
    )
    if not symbol:
        return None
    option_type = _scrip_field(row, "SEM_OPTION_TYPE", "OPTION_TYPE").upper()
    option_type = {"CALL": "CE", "CE": "CE", "PUT": "PE", "PE": "PE"}.get(option_type, "")
    inferred_option_type, _expiry, inferred_strike, inferred_underlying = _option_contract_identity(
        {"tradingSymbol": trading_symbol}
    )
    option_type = option_type or inferred_option_type
    raw_strike = _scrip_field(row, "SEM_STRIKE_PRICE", "STRIKE_PRICE")
    strike_price: float | str = _num(raw_strike) if raw_strike else inferred_strike if option_type else ""
    underlying = _scrip_field(row, "UNDERLYING_SYMBOL")
    if option_type and not underlying:
        underlying = inferred_underlying or _scrip_field(row, "SM_SYMBOL_NAME", "SYMBOL_NAME")
    return {
        "security_id": security_id,
        "symbol": symbol,
        "exchange": exchange,
        "instrument_type": _scrip_field(
            row,
            "SEM_EXCH_INSTRUMENT_TYPE",
            "INSTRUMENT_TYPE",
            "SEM_INSTRUMENT_NAME",
            "INSTRUMENT",
        ),
        "option_type": option_type,
        "expiry": _normalise_scrip_expiry(_scrip_field(row, "SEM_EXPIRY_DATE", "SM_EXPIRY_DATE")),
        "strike_price": strike_price,
        "underlying": underlying or inferred_underlying,
    }


class _ScripMasterSecurityResolver:
    """Forward resolver with a wrapper-safe reverse lookup side channel."""

    def __init__(
        self,
        forward: dict[tuple[str, str], str],
        reverse: dict[tuple[str, str], dict[str, Any]],
    ) -> None:
        self._forward = forward
        self._reverse = reverse

    def __call__(self, symbol: str, exchange: str) -> str:
        raw_symbol = str(symbol)
        if raw_symbol.startswith(_REVERSE_LOOKUP_PREFIX):
            security_id = raw_symbol.removeprefix(_REVERSE_LOOKUP_PREFIX)
            identity = self.reverse(security_id, exchange)
            return _REVERSE_RESULT_PREFIX + json.dumps(identity, separators=(",", ":"), sort_keys=True)
        key = (raw_symbol.upper().strip(), str(exchange).upper().strip())
        try:
            return self._forward[key]
        except KeyError as exc:
            raise DhanMappingError(f"Scrip master has no security_id for {symbol}/{exchange}") from exc

    def reverse(self, security_id: str, exchange: str) -> dict[str, Any]:
        key = (str(security_id).strip(), str(exchange).upper().strip())
        try:
            return dict(self._reverse[key])
        except KeyError as exc:
            raise DhanMappingError(
                f"Scrip master has no instrument for security_id {security_id}/{exchange}"
            ) from exc


def reverse_security_id(
    resolver: Callable[[str, str], str],
    security_id: str,
    exchange_segment: str,
) -> dict[str, Any]:
    """Resolve a Dhan security id to canonical instrument identity.

    ``build_security_resolver`` exposes ``reverse`` directly. The encoded
    fallback deliberately travels through a plain two-argument wrapper so the
    production lazy resolver can initialise itself without losing reverse
    lookup capability.
    """
    raw_security_id = str(security_id).strip()
    raw_exchange = str(exchange_segment).upper().strip()
    exchange = SEGMENT_TO_EXCHANGE.get(raw_exchange, raw_exchange)
    if not raw_security_id or not exchange:
        raise DhanMappingError("Dhan reverse security lookup needs security_id and exchange")

    reverse = getattr(resolver, "reverse", None)
    try:
        if callable(reverse):
            identity = reverse(raw_security_id, exchange)
        else:
            identity = None
            encoded = resolver(f"{_REVERSE_LOOKUP_PREFIX}{raw_security_id}", exchange)
    except DhanMappingError:
        raise
    except Exception as exc:
        raise DhanMappingError("Configured Dhan reverse security-id lookup failed") from exc
    if not callable(reverse):
        if not isinstance(encoded, str) or not encoded.startswith(_REVERSE_RESULT_PREFIX):
            raise DhanMappingError("Configured Dhan security resolver has no reverse security-id lookup")
        try:
            identity = json.loads(encoded.removeprefix(_REVERSE_RESULT_PREFIX))
        except (TypeError, ValueError) as exc:
            raise DhanMappingError("Configured Dhan reverse security-id lookup returned invalid data") from exc

    if not isinstance(identity, dict):
        raise DhanMappingError("Configured Dhan reverse security-id lookup returned invalid data")
    if (
        str(identity.get("security_id") or "").strip() != raw_security_id
        or str(identity.get("exchange") or "").upper().strip() != exchange
        or not str(identity.get("symbol") or "").strip()
    ):
        raise DhanMappingError("Configured Dhan reverse security-id lookup returned inconsistent identity")
    return dict(identity)


def build_security_resolver(rows: list[dict[str, Any]]) -> Callable[[str, str], str]:
    """Build a callable forward resolver with a fail-closed reverse lookup.

    Accepts both compact (``SEM_*``) and detailed column tags. Symbols are
    indexed by trading symbol AND display/symbol name, upper-cased, per
    canonical exchange. Normal calls retain the existing
    ``resolver(symbol, exchange) -> security_id`` contract; ``resolver.reverse``
    and :func:`reverse_security_id` expose canonical identity by security id.
    """
    index: dict[tuple[str, str], str] = {}
    ambiguous_forward_keys: set[tuple[str, str]] = set()
    reverse_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sec_id = _scrip_field(row, "SEM_SMST_SECURITY_ID", "SECURITY_ID")
        if not sec_id:
            continue
        exch = _scrip_field(row, "SEM_EXM_EXCH_ID", "EXCH_ID").upper()
        seg = _scrip_field(row, "SEM_SEGMENT", "SEGMENT").upper()[:1]
        exchange = _SCRIP_EXCHANGE.get((exch, seg))
        if exchange is None:
            continue
        identity = _scrip_security_identity(row, sec_id, exchange)
        if identity is not None:
            reverse_key = (sec_id, exchange)
            existing = reverse_index.get(reverse_key)
            if existing is not None and existing != identity:
                raise DhanMappingError(f"Scrip master has conflicting identity for security_id {sec_id}/{exchange}")
            reverse_index[reverse_key] = identity
        for symbol in {
            _scrip_field(row, "SEM_TRADING_SYMBOL", "TRADING_SYMBOL").upper(),
            _scrip_field(row, "SEM_CUSTOM_SYMBOL", "DISPLAY_NAME").upper(),
            _scrip_field(row, "SM_SYMBOL_NAME", "SYMBOL_NAME").upper(),
        }:
            if symbol:
                key = (symbol, exchange)
                if key in ambiguous_forward_keys:
                    continue
                existing_security_id = index.get(key)
                if existing_security_id is None:
                    index[key] = sec_id
                elif existing_security_id != sec_id:
                    index.pop(key, None)
                    ambiguous_forward_keys.add(key)
    return _ScripMasterSecurityResolver(index, reverse_index)


def to_option_chain_dict(underlying: str, exchange: str, resp: Any) -> dict[str, Any]:
    """Map a Dhan option-chain response to an OptionChain-shaped dict.

    Dhan returns ``data.{last_price, oc}`` keyed by strike string →
    ``{ce:{...}, pe:{...}}`` (option-chain.md). As with quotes, the live SDK
    transport double-wraps the body (``data.data.{oc}``), so this peels the inner
    ``data`` when present before reading ``oc`` — mirroring the expiry-list and
    expired-options handling.
    """
    data = unwrap(resp)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]  # peel the endpoint's second "data" nest
    if not isinstance(data, dict):
        raise DhanMappingError("Dhan option chain payload is invalid")
    oc = data.get("oc")
    if not isinstance(oc, dict) or not oc:
        raise DhanMappingError("Dhan option chain contracts are invalid")
    strikes: list[dict[str, Any]] = []
    parsed_strikes: list[tuple[float, Any]] = []
    seen_strikes: set[float] = set()
    for strike_value, legs in oc.items():
        strike_price = _option_chain_number(strike_value, field="strike_price")
        if strike_price in seen_strikes:
            raise DhanMappingError("Dhan option chain has duplicate strike identities")
        seen_strikes.add(strike_price)
        parsed_strikes.append((strike_price, legs))
    for strike_price, legs in sorted(parsed_strikes, key=lambda item: item[0]):
        if not isinstance(legs, dict):
            raise DhanMappingError("Dhan option chain strike legs are invalid")
        row: dict[str, Any] = {"strike_price": strike_price}
        ce = legs.get("ce")
        pe = legs.get("pe")
        if ce is None:
            ce = {}
        if pe is None:
            pe = {}
        if not isinstance(ce, dict) or not isinstance(pe, dict):
            raise DhanMappingError("Dhan option chain strike legs are invalid")
        row.update(_leg(ce, "ce"))
        row.update(_leg(pe, "pe"))
        strikes.append(row)
    return {
        "underlying": underlying,
        "exchange": exchange,
        "spot_price": _option_chain_number(data.get("last_price"), field="last_price"),
        "strikes": strikes,
    }
