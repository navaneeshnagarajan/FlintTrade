"""Flask blueprint for IPO calendar endpoints.

Provides 2 endpoints under /api/v1/ for the Invest > IPO tab:
    - GET /api/v1/ipo/upcoming — upcoming IPOs
    - GET /api/v1/ipo/recent   — recently listed IPOs

Data is read from a manually-curated JSON file at
``packages/services/screener/data/ipo_calendar.json``. The file is cached in
memory for 1 hour so disk reads are minimal. A future version can
replace this with live NSE scraping or an API integration.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify

from flinttrade_core.source_root import discover_source_root

logger = logging.getLogger("flinttrade.screener.ipo_routes")

ipo_bp = Blueprint("ipo", __name__, url_prefix="/api/v1")

# ---------------------------------------------------------------------------
# Data file path
# ---------------------------------------------------------------------------

def _default_ipo_data_file(module_file: Path | str | None = None) -> Path:
    """Return the IPO calendar path inside the managed source checkout."""
    source_root = discover_source_root(module_file=module_file or __file__)
    return source_root / "packages" / "services" / "screener" / "data" / "ipo_calendar.json"


_DATA_FILE = _default_ipo_data_file()

# ---------------------------------------------------------------------------
# In-memory cache (1 hour TTL)
# ---------------------------------------------------------------------------

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0
_CACHE_TTL_SECS: float = 3600.0  # 1 hour


def _load_ipo_data() -> dict[str, Any]:
    """Load IPO calendar JSON, returning cached version if fresh.

    Returns:
        Parsed JSON dict with 'upcoming' and 'recent' lists.
    """
    global _cache, _cache_ts  # noqa: PLW0603

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL_SECS:
        return _cache

    if not _DATA_FILE.exists():
        logger.warning("IPO calendar file not found: %s", _DATA_FILE)
        return {"upcoming": [], "recent": [], "last_updated": ""}

    try:
        raw = _DATA_FILE.read_text(encoding="utf-8")
        data = json.loads(raw)
        _cache = data
        _cache_ts = now
        logger.info("IPO calendar loaded: %d upcoming, %d recent", len(data.get("upcoming", [])), len(data.get("recent", [])))
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load IPO calendar: %s", exc)
        return {"upcoming": [], "recent": [], "last_updated": ""}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@ipo_bp.route("/ipo/upcoming", methods=["GET"])
def ipo_upcoming() -> Any:
    """Return upcoming IPOs.

    Response JSON:
        {
          "status": "success",
          "last_updated": "2026-04-08",
          "ipos": [ { name, symbol, issue_size, price_band, lot_size,
                       open_date, close_date, listing_date, status, listing_gain } ]
        }
    """
    data = _load_ipo_data()
    return jsonify({
        "status": "success",
        "data": {
            "last_updated": data.get("last_updated", ""),
            "ipos": data.get("upcoming", []),
        },
    })


@ipo_bp.route("/ipo/recent", methods=["GET"])
def ipo_recent() -> Any:
    """Return recently listed IPOs.

    Response JSON:
        {
          "status": "success",
          "data": { "last_updated": "2026-04-08",
                    "ipos": [ { name, symbol, issue_size, price_band, lot_size,
                         open_date, close_date, listing_date, status, listing_gain } ] }
        }
    """
    data = _load_ipo_data()
    return jsonify({
        "status": "success",
        "data": {
            "last_updated": data.get("last_updated", ""),
            "ipos": data.get("recent", []),
        },
    })
