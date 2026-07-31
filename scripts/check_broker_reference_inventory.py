#!/usr/bin/env python3
"""Validate local broker reference captures used by native/MCP integration work.

The captures themselves live under ``.local`` and are intentionally untracked.
This checker gives future broker-work waves a repeatable way to prove that the
local evidence folder still contains the public MCP pages, broker API docs, and
Kotak Neo v2 docs that the committed catalogue/adapters were built against.
"""

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

DEFAULT_REFERENCE_ROOT = Path(".local/reference-research/2026-07-06")
DEFAULT_API_REFERENCE_ROOT = Path(".local/reference-research/2026-07-03")
MCP_SOURCES = {
    "dhan": "https://docs.dhanhq.co/mcp/",
    "upstox": "https://upstox.com/developer/api-documentation/mcp-integration/",
    "groww": "https://groww.in/updates/groww-mcp",
}
MCP_HTML_MARKERS = {
    "dhan": [
        "model context protocol",
        "native mcp server",
        "supported clients",
        "trade, manage your portfolio",
    ],
    "upstox": [
        "https://mcp.upstox.com/mcp",
        "read-only access",
        "daily re-authorization",
        "claude desktop",
        "chatgpt",
        "cursor",
        "vs code",
    ],
    "groww": [
        "https://mcp.groww.in/mcp",
        "growwmcp",
        "mcp-remote@0.1.18",
        "52155",
        "ddpi",
        "no background syncing",
        "no data storage on ai servers",
        "stocks and f&o",
    ],
}
KOTAK_REQUIRED_FILES = [
    "content-paths.txt",
    "README.md",
    "SHA256SUMS",
    "raw/index.html",
    "raw/content/curl-examples.md",
    "raw/content/holdings.md",
    "raw/content/instruments.md",
    "raw/content/limits.md",
    "raw/content/login-with-totp.md",
    "raw/content/margins.md",
    "raw/content/order-report-apis.md",
    "raw/content/order/cancel-order.md",
    "raw/content/order/modify-order.md",
    "raw/content/order/place-order.md",
    "raw/content/positions.md",
    "raw/content/quotes.md",
    "raw/content/trade-api-faq .md",
    "raw/content/websocket/websocket.md",
]
KOTAK_MARKERS = {
    "raw/content/login-with-totp.md": [
        "tradeapilogin",
        "tradeapivalidate",
        "authorization",
        "neo-fin-key",
        "totp",
        "mpin",
    ],
    "raw/content/curl-examples.md": [
        "auth",
        "sid",
        "neo-fin-key",
        "quotes",
        "do not send",
        "ts",
    ],
    "raw/content/order/cancel-order.md": [
        "/quick/order/cancel",
        "/quick/order/bo/exit",
        "/quick/order/co/exit",
        "neo-fin-key",
        "trading symbol",
    ],
    "raw/content/instruments.md": [
        "ptrdsymbol",
        "'ts' field",
        "authorization",
    ],
    "raw/content/quotes.md": [
        "plain token",
        "authorization",
        "nse_cm",
    ],
    "raw/content/websocket/websocket.md": [
        "connect to order feed",
        "session token",
        "sid",
        "data center",
    ],
}
GROWW_API_REQUIRED_FILES = [
    "inventories/00-docs.json",
    "inventories/02-api-keys.json",
    "inventories/03-python-sdk.json",
    "inventories/04-curl-docs.json",
    "public-docs-extract/api-keys.json",
    "public-docs-extract/curl-historical-data.json",
    "public-docs-extract/curl-instruments.json",
    "public-docs-extract/curl-live-data.json",
    "public-docs-extract/curl-margin.json",
    "public-docs-extract/curl-orders.json",
    "public-docs-extract/curl-portfolio.json",
    "public-docs-extract/curl-smart-orders.json",
    "public-docs-extract/curl-user.json",
    "public-docs-extract/python-sdk-feed.json",
    "public-docs-extract/python-sdk-historical-data.json",
    "public-docs-extract/python-sdk-instruments.json",
    "public-docs-extract/python-sdk-intro.json",
    "public-docs-extract/python-sdk-live-data.json",
    "public-docs-extract/python-sdk-margin.json",
    "public-docs-extract/python-sdk-orders.json",
    "public-docs-extract/python-sdk-portfolio.json",
    "public-docs-extract/python-sdk-smart-orders.json",
    "public-docs-extract/python-sdk-user.json",
]
GROWW_API_MARKERS = {
    "public-docs-extract/api-keys.json": [
        "groww cloud | api keys",
        "static-ip-api-trading-setup",
    ],
    "public-docs-extract/python-sdk-intro.json": [
        "pip install growwapi",
        "growwapi.get_access_token",
        "api_key",
        "secret",
        "pyotp",
    ],
    "public-docs-extract/python-sdk-orders.json": [
        "place_order",
        "modify_order",
        "cancel_order",
        "get_order_status_by_reference",
        "get_order_detail",
    ],
    "public-docs-extract/python-sdk-live-data.json": [
        "get_quote",
        "depth",
        "open_interest",
    ],
    "public-docs-extract/python-sdk-historical-data.json": [
        "get_historical_candle_data",
        "interval_in_minutes",
        "candles",
    ],
    "public-docs-extract/python-sdk-portfolio.json": [
        "get_holdings_for_user",
        "get_positions_for_user",
        "trading_symbol",
    ],
    "public-docs-extract/python-sdk-margin.json": [
        "get_available_margin_details",
        "get_order_margin_details",
        "fno_margin_details",
    ],
    "public-docs-extract/python-sdk-smart-orders.json": [
        "create_smart_order",
        "cancel_smart_order",
        "smart_order_type_gtt",
        "smart_order_type_oco",
    ],
    "public-docs-extract/python-sdk-feed.json": [
        "growwfeed",
        "subscribe_ltp",
        "subscribe_market_depth",
        "feed.consume",
    ],
    "public-docs-extract/python-sdk-user.json": [
        "get_user_profile",
        "vendor_user_id",
        "active_segments",
    ],
}
INDSTOCKS_API_REQUIRED_FILES = [
    "inventories/04-api-overview.json",
    "inventories/06-users-auth.json",
    "inventories/07-instruments-master.json",
    "inventories/08-market-quote.json",
    "inventories/09-historical-data.json",
    "inventories/10-websockets.json",
    "inventories/11-normal-orders.json",
    "inventories/12-smart-orders-gtt.json",
    "inventories/13-margin-calculation.json",
    "inventories/14-portfolio-funds.json",
    "inventories/15-utility.json",
    "inventories/17-faq.json",
    "public-docs-extract/api-overview.json",
    "public-docs-extract/faq.json",
    "public-docs-extract/historical-data.json",
    "public-docs-extract/instruments-master.json",
    "public-docs-extract/margin-calculation.json",
    "public-docs-extract/market-quote.json",
    "public-docs-extract/normal-orders.json",
    "public-docs-extract/portfolio-funds.json",
    "public-docs-extract/smart-orders-gtt.json",
    "public-docs-extract/users-auth.json",
    "public-docs-extract/utility.json",
    "public-docs-extract/websockets.json",
]
INDSTOCKS_API_MARKERS = {
    "public-docs-extract/faq.json": [
        "pip install indstocks-sdk",
        "npm install indstocks-sdk",
    ],
    "public-docs-extract/users-auth.json": [
        "get /user/profile",
        "get /funds",
        "authorization: your_access_token",
    ],
    "public-docs-extract/instruments-master.json": [
        "get /market/instruments",
        "security_id",
        "instruments.csv",
    ],
    "public-docs-extract/market-quote.json": [
        "get /market/quotes/full",
        "get /market/quotes/ltp",
        "live_price",
        "market_depth",
    ],
    "public-docs-extract/historical-data.json": [
        "get /market/historical/{interval}",
        "1minute",
        "candles",
    ],
    "public-docs-extract/websockets.json": [
        "wss://ws-prices.indstocks.com/api/v1/ws/prices",
        "wss://ws-order-updates.indstocks.com/api/v1/ws/trades",
        "order_updates",
    ],
    "public-docs-extract/normal-orders.json": [
        "post /order",
        "post /order/modify",
        "post /order/cancel",
        "algo_id",
    ],
    "public-docs-extract/smart-orders-gtt.json": [
        "post /smart/order",
        "post /smart/order/cancel",
        "sl_trigger_price",
        "tgt_trigger_price",
    ],
    "public-docs-extract/margin-calculation.json": [
        "get /margin",
        "total_margin",
        "brokerage",
    ],
    "public-docs-extract/portfolio-funds.json": [
        "get /portfolio/holdings",
        "get /portfolio/positions",
        "pnl_absolute",
    ],
    "public-docs-extract/utility.json": [
        "get /option-chain",
        "get /option-chain-symbols",
    ],
}


@dataclass(frozen=True)
class CheckResult:
    """One inventory validation result."""

    ok: bool
    message: str


def _normalise(text: str) -> str:
    """Return lower-cased text with HTML entities decoded and whitespace folded."""
    decoded = html.unescape(text).replace("‘", "'").replace("’", "'")
    return " ".join(decoded.lower().split())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _latest_matching(root: Path, prefix: str) -> Path | None:
    candidates = sorted(p for p in root.glob(f"{prefix}*") if p.is_dir())
    return candidates[-1] if candidates else None


def _missing_files(base: Path, relative_paths: Iterable[str]) -> list[str]:
    return [rel for rel in relative_paths if not (base / rel).is_file()]


def _check_markers(base: Path, marker_map: dict[str, Sequence[str]]) -> list[str]:
    missing: list[str] = []
    for rel, markers in marker_map.items():
        path = base / rel
        if not path.is_file():
            missing.append(f"{rel}: file missing")
            continue
        text = _normalise(_read_text(path))
        for marker in markers:
            if marker.lower() not in text:
                missing.append(f"{rel}: missing marker {marker!r}")
    return missing


def validate_mcp_capture(mcp_dir: Path) -> list[CheckResult]:
    """Validate the broker MCP public-page capture."""
    results: list[CheckResult] = []
    required = ["sources.txt", "SHA256SUMS"] + [
        f"raw/{broker}.headers.txt" for broker in MCP_SOURCES
    ] + [
        f"raw/{broker}.html" for broker in MCP_SOURCES
    ]
    missing = _missing_files(mcp_dir, required)
    results.append(CheckResult(not missing, f"MCP capture files: {', '.join(missing) or 'ok'}"))
    if missing:
        return results

    sources_text = _normalise(_read_text(mcp_dir / "sources.txt"))
    source_misses = [
        f"{broker} {url}"
        for broker, url in MCP_SOURCES.items()
        if f"{broker} {url}".lower() not in sources_text
    ]
    results.append(CheckResult(not source_misses, f"MCP sources: {', '.join(source_misses) or 'ok'}"))

    sums_text = _normalise(_read_text(mcp_dir / "SHA256SUMS"))
    sum_misses = [
        f"raw/{broker}.html"
        for broker in MCP_SOURCES
        if f"raw/{broker}.html" not in sums_text
    ]
    results.append(CheckResult(not sum_misses, f"MCP checksums: {', '.join(sum_misses) or 'ok'}"))

    marker_map = {
        f"raw/{broker}.html": markers
        for broker, markers in MCP_HTML_MARKERS.items()
    }
    marker_misses = _check_markers(mcp_dir, marker_map)
    results.append(CheckResult(not marker_misses, f"MCP page markers: {', '.join(marker_misses) or 'ok'}"))
    return results


def validate_kotak_capture(kotak_dir: Path) -> list[CheckResult]:
    """Validate the Kotak Neo v2 public-docs capture."""
    results: list[CheckResult] = []
    missing = _missing_files(kotak_dir, KOTAK_REQUIRED_FILES)
    results.append(CheckResult(not missing, f"Kotak capture files: {', '.join(missing) or 'ok'}"))
    if missing:
        return results

    content_paths = _normalise(_read_text(kotak_dir / "content-paths.txt"))
    content_misses = [
        rel.removeprefix("raw/")
        for rel in KOTAK_REQUIRED_FILES
        if rel.startswith("raw/content/") and rel.removeprefix("raw/").lower() not in content_paths
    ]
    results.append(CheckResult(not content_misses, f"Kotak content index: {', '.join(content_misses) or 'ok'}"))

    marker_misses = _check_markers(kotak_dir, KOTAK_MARKERS)
    results.append(CheckResult(not marker_misses, f"Kotak page markers: {', '.join(marker_misses) or 'ok'}"))
    return results


def validate_groww_trade_api_capture(groww_dir: Path) -> list[CheckResult]:
    """Validate the Groww Trade API public-docs capture."""
    results: list[CheckResult] = []
    missing = _missing_files(groww_dir, GROWW_API_REQUIRED_FILES)
    results.append(CheckResult(not missing, f"Groww Trade API capture files: {', '.join(missing) or 'ok'}"))
    if missing:
        return results

    marker_misses = _check_markers(groww_dir, GROWW_API_MARKERS)
    results.append(CheckResult(not marker_misses, f"Groww Trade API page markers: {', '.join(marker_misses) or 'ok'}"))
    return results


def validate_indstocks_api_capture(indstocks_dir: Path) -> list[CheckResult]:
    """Validate the INDstocks public API-docs capture."""
    results: list[CheckResult] = []
    missing = _missing_files(indstocks_dir, INDSTOCKS_API_REQUIRED_FILES)
    results.append(CheckResult(not missing, f"INDstocks API capture files: {', '.join(missing) or 'ok'}"))
    if missing:
        return results

    marker_misses = _check_markers(indstocks_dir, INDSTOCKS_API_MARKERS)
    results.append(CheckResult(not marker_misses, f"INDstocks API page markers: {', '.join(marker_misses) or 'ok'}"))
    return results


def validate_inventory(
    reference_root: Path,
    *,
    api_reference_root: Path | None = None,
    mcp_dir: Path | None = None,
    kotak_dir: Path | None = None,
    groww_api_dir: Path | None = None,
    indstocks_api_dir: Path | None = None,
) -> list[CheckResult]:
    """Validate all known broker-reference captures under ``reference_root``."""
    results: list[CheckResult] = []
    if api_reference_root is None:
        api_reference_root = reference_root
    if mcp_dir is None:
        mcp_dir = _latest_matching(reference_root, "broker-mcp-current-")
    if kotak_dir is None:
        latest = reference_root / "kotak-neo-api-v2-current-latest"
        kotak_dir = latest if latest.exists() else _latest_matching(reference_root, "kotak-neo-api-v2-current-")
    if groww_api_dir is None:
        groww_api_dir = _latest_matching(api_reference_root, "groww-trade-api-docs")
    if indstocks_api_dir is None:
        indstocks_api_dir = _latest_matching(api_reference_root, "indstocks-api-docs")

    if mcp_dir is None:
        results.append(CheckResult(False, f"MCP capture directory missing under {reference_root}"))
    else:
        results.extend(validate_mcp_capture(mcp_dir))

    if kotak_dir is None:
        results.append(CheckResult(False, f"Kotak capture directory missing under {reference_root}"))
    else:
        results.extend(validate_kotak_capture(kotak_dir))

    if groww_api_dir is None:
        results.append(CheckResult(False, f"Groww Trade API capture directory missing under {api_reference_root}"))
    else:
        results.extend(validate_groww_trade_api_capture(groww_api_dir))

    if indstocks_api_dir is None:
        results.append(CheckResult(False, f"INDstocks API capture directory missing under {api_reference_root}"))
    else:
        results.extend(validate_indstocks_api_capture(indstocks_api_dir))
    return results


def _format_result(result: CheckResult) -> str:
    prefix = "OK" if result.ok else "FAIL"
    return f"{prefix}: {result.message}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-root",
        type=Path,
        default=DEFAULT_REFERENCE_ROOT,
        help="Root containing local MCP and Kotak public broker-reference captures.",
    )
    parser.add_argument(
        "--api-reference-root",
        type=Path,
        default=DEFAULT_API_REFERENCE_ROOT,
        help="Root containing local Groww Trade API and INDstocks API public-docs captures.",
    )
    parser.add_argument("--mcp-dir", type=Path, help="Explicit broker MCP capture directory.")
    parser.add_argument("--kotak-dir", type=Path, help="Explicit Kotak Neo v2 capture directory.")
    parser.add_argument("--groww-api-dir", type=Path, help="Explicit Groww Trade API docs capture directory.")
    parser.add_argument("--indstocks-api-dir", type=Path, help="Explicit INDstocks API docs capture directory.")
    args = parser.parse_args(argv)

    results = validate_inventory(
        args.reference_root,
        api_reference_root=args.api_reference_root,
        mcp_dir=args.mcp_dir,
        kotak_dir=args.kotak_dir,
        groww_api_dir=args.groww_api_dir,
        indstocks_api_dir=args.indstocks_api_dir,
    )
    for result in results:
        print(_format_result(result))
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
