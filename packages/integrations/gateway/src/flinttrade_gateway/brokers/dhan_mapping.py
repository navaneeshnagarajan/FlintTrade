"""Canonical-to-Dhan mapping tables.

Values are grounded in the official DhanHQ Agent Skill (``dhan-oss/dhanhq-skills``)
and the DhanHQ v2 SDK constants — see that skill's ``SKILL.md`` "Current SDK
Constants" table. These tables back the (gated) DhanAdapter's request building
and instrument resolution; keep them in lock-step with ``DHAN_CAPABILITIES``.
"""

from __future__ import annotations

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
