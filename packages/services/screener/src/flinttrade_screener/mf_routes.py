"""Flask blueprint for Mutual Fund NAV endpoints.

Provides 3 endpoints under /api/v1/ for the Invest > Mutual Fund Explorer tab:
    - GET /api/v1/mf/search?q=axis     — search funds by name/AMC
    - GET /api/v1/mf/nav/<scheme_code>  — get current NAV for a scheme
    - GET /api/v1/mf/categories         — list SEBI fund categories

Data source: AMFI India daily NAV file (``https://www.amfiindia.com/spages/NAVAll.txt``).
The file is pipe-delimited and freely available without authentication.
Parsed data is cached in memory with a 24-hour TTL (NAV updates once daily
after market close).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.request import urlopen
from urllib.error import URLError

from flask import Blueprint, jsonify, request

logger = logging.getLogger("flinttrade.screener.mf_routes")

mf_bp = Blueprint("mutual_funds", __name__, url_prefix="/api/v1")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class MutualFund:
    """Single mutual fund scheme with current NAV."""

    scheme_code: int
    scheme_name: str
    amc: str
    category: str
    nav: float
    nav_date: str
    scheme_type: str  # Open, Close, Interval


# ---------------------------------------------------------------------------
# AMFI NAV parser + in-memory cache (24-hour TTL)
# ---------------------------------------------------------------------------

_AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
_CACHE_TTL_SECS: float = 86400.0  # 24 hours

_funds_cache: list[MutualFund] = []
_categories_cache: list[str] = []
_cache_ts: float = 0.0


def _parse_amfi_nav(raw_text: str) -> list[MutualFund]:
    """Parse the AMFI NAV text file into MutualFund objects.

    The AMFI file format:
        - Header lines with scheme type and AMC info
        - Lines starting with "Scheme Code;" are column headers
        - Data lines: SchemeCode;ISINGrowth;ISINReinvest;SchemeName;NAV;Date

    AMC and category are derived from the header sections which look like:
        ``Open Ended Schemes(Debt Scheme - Banking and PSU Fund)``
        ``AMC Name``

    Args:
        raw_text: Full text content of the AMFI NAVAll.txt file.

    Returns:
        List of MutualFund objects parsed from the file.
    """
    funds: list[MutualFund] = []
    current_scheme_type = "Open"
    current_category = ""
    current_amc = ""

    # Pattern for section headers like:
    # "Open Ended Schemes(Debt Scheme - Banking and PSU Fund)"
    section_pattern = re.compile(
        r"^(Open Ended|Close Ended|Interval)\s+Schemes?\s*\((.+)\)\s*$",
        re.IGNORECASE,
    )

    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue

        # Skip column header lines
        if line.startswith("Scheme Code;"):
            continue

        # Check for section header (scheme type + category)
        section_match = section_pattern.match(line)
        if section_match:
            current_scheme_type = section_match.group(1).strip()
            current_category = section_match.group(2).strip()
            continue

        # Data lines have semicolons — 5 or 6 fields
        parts = line.split(";")
        if len(parts) >= 5:
            try:
                scheme_code = int(parts[0].strip())
            except (ValueError, IndexError):
                # Not a data line (could be an AMC name)
                # AMC names are plain text lines between section headers and data
                if ";" not in line and not line.startswith("Scheme"):
                    current_amc = line.strip()
                continue

            scheme_name = parts[3].strip() if len(parts) > 3 else ""
            nav_str = parts[4].strip() if len(parts) > 4 else ""
            nav_date = parts[5].strip() if len(parts) > 5 else ""

            # Skip N.A. or invalid NAV values
            try:
                nav = float(nav_str)
            except (ValueError, TypeError):
                nav = 0.0

            if scheme_name and nav > 0:
                funds.append(MutualFund(
                    scheme_code=scheme_code,
                    scheme_name=scheme_name,
                    amc=current_amc,
                    category=current_category,
                    nav=round(nav, 4),
                    nav_date=nav_date,
                    scheme_type=current_scheme_type,
                ))
        else:
            # Plain text line — likely an AMC name
            if ";" not in line and len(line) > 3:
                current_amc = line.strip()

    return funds


def _fetch_and_cache() -> list[MutualFund]:
    """Download AMFI NAV file and cache the parsed result.

    Returns cached data if within TTL. Falls back to empty list on
    network errors (the next request will retry).

    Returns:
        List of MutualFund objects.
    """
    global _funds_cache, _categories_cache, _cache_ts  # noqa: PLW0603

    now = time.time()
    if _funds_cache and (now - _cache_ts) < _CACHE_TTL_SECS:
        return _funds_cache

    try:
        logger.info("Fetching AMFI NAV data from %s", _AMFI_URL)
        with urlopen(_AMFI_URL, timeout=30) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")

        funds = _parse_amfi_nav(raw)
        if funds:
            _funds_cache = funds
            _cache_ts = now

            # Build unique sorted category list
            cats = sorted({f.category for f in funds if f.category})
            _categories_cache = cats

            logger.info(
                "AMFI NAV loaded: %d schemes, %d categories",
                len(funds),
                len(cats),
            )
        else:
            logger.warning("AMFI NAV parse returned 0 funds")
        return _funds_cache

    except (URLError, OSError, TimeoutError) as exc:
        logger.error("Failed to fetch AMFI NAV data: %s", exc)
        # Return whatever is in cache (may be stale or empty)
        return _funds_cache


def _get_categories() -> list[str]:
    """Return cached category list, fetching data if needed.

    Returns:
        Sorted list of SEBI fund category strings.
    """
    if not _categories_cache:
        _fetch_and_cache()
    return _categories_cache


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@mf_bp.route("/mf/search", methods=["GET"])
def mf_search() -> Any:
    """Search mutual funds by name, AMC, or category.

    Query params:
        q (str): Search query (required, min 2 chars).
        category (str): Optional SEBI category filter.
        limit (int): Max results (default 50, max 200).

    Response JSON:
        {
          "status": "success",
          "query": "axis",
          "count": 15,
          "funds": [ { scheme_code, scheme_name, amc, category, nav, nav_date, scheme_type } ]
        }
    """
    query = (request.args.get("q", "") or "").strip().lower()
    category_filter = (request.args.get("category", "") or "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)

    if len(query) < 2:
        return jsonify({
            "status": "error",
            "message": "Search query must be at least 2 characters",
        }), 400

    funds = _fetch_and_cache()

    results: list[MutualFund] = []
    for fund in funds:
        if category_filter and fund.category != category_filter:
            continue
        if (
            query in fund.scheme_name.lower()
            or query in fund.amc.lower()
        ):
            results.append(fund)
            if len(results) >= limit:
                break

    return jsonify({
        "status": "success",
        "data": {
            "query": query,
            "count": len(results),
            "funds": [asdict(f) for f in results],
        },
    })


@mf_bp.route("/mf/nav/<int:scheme_code>", methods=["GET"])
def mf_nav(scheme_code: int) -> Any:
    """Get current NAV for a specific mutual fund scheme.

    Path params:
        scheme_code (int): AMFI scheme code.

    Response JSON:
        {
          "status": "success",
          "fund": { scheme_code, scheme_name, amc, category, nav, nav_date, scheme_type }
        }
    """
    funds = _fetch_and_cache()

    for fund in funds:
        if fund.scheme_code == scheme_code:
            return jsonify({
                "status": "success",
                "data": {"fund": asdict(fund)},
            })

    return jsonify({
        "status": "error",
        "message": f"Scheme code {scheme_code} not found",
    }), 404


@mf_bp.route("/mf/categories", methods=["GET"])
def mf_categories() -> Any:
    """List all available SEBI mutual fund categories.

    Response JSON:
        {
          "status": "success",
          "count": 36,
          "categories": [ "Debt Scheme - Banking and PSU Fund", ... ]
        }
    """
    cats = _get_categories()
    return jsonify({
        "status": "success",
        "data": {
            "count": len(cats),
            "categories": cats,
        },
    })
