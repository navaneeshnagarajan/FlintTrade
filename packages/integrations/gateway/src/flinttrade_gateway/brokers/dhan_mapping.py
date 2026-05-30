"""Canonical-to-Dhan order mapping tables."""

ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOP_LOSS",
    "SLM": "STOP_LOSS_MARKET",
}

PRODUCT_MAP = {
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "NRML": "MARGIN",
}

VALIDITY_MAP = {
    "DAY": "DAY",
    "IOC": "IOC",
    "GTT": "FOREVER",
}
