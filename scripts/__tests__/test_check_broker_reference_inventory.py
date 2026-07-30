from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "check_broker_reference_inventory.py"
SPEC = importlib.util.spec_from_file_location("check_broker_reference_inventory", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def _write(path: Path, text: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_valid_capture(root: Path) -> tuple[Path, Path]:
    mcp = root / "broker-mcp-current-20260706T000000Z"
    kotak = root / "kotak-neo-api-v2-current-latest"
    groww = root / "groww-trade-api-docs"
    indstocks = root / "indstocks-api-docs"
    _write(
        mcp / "sources.txt",
        "\n".join(
            [
                "dhan https://docs.dhanhq.co/mcp/",
                "upstox https://upstox.com/developer/api-documentation/mcp-integration/",
                "groww https://groww.in/updates/groww-mcp",
            ]
        ),
    )
    _write(
        mcp / "SHA256SUMS",
        "\n".join(["abc raw/dhan.html", "abc raw/upstox.html", "abc raw/groww.html"]),
    )
    _write(mcp / "raw/dhan.headers.txt")
    _write(mcp / "raw/upstox.headers.txt")
    _write(mcp / "raw/groww.headers.txt")
    _write(
        mcp / "raw/dhan.html",
        "Model Context Protocol native MCP server supported clients trade, manage your portfolio",
    )
    _write(
        mcp / "raw/upstox.html",
        "https://mcp.upstox.com/mcp Read-Only Access Daily re-authorization Claude Desktop ChatGPT Cursor VS Code",
    )
    _write(
        mcp / "raw/groww.html",
        "https://mcp.groww.in/mcp GrowwMCP mcp-remote@0.1.18 52155 DDPI No background syncing "
        "No data storage on AI servers stocks and F&amp;O",
    )

    _write(kotak / "README.md")
    _write(kotak / "SHA256SUMS")
    _write(kotak / "raw/index.html")
    content_files = [
        "content/curl-examples.md",
        "content/holdings.md",
        "content/instruments.md",
        "content/limits.md",
        "content/login-with-totp.md",
        "content/margins.md",
        "content/order-report-apis.md",
        "content/order/cancel-order.md",
        "content/order/modify-order.md",
        "content/order/place-order.md",
        "content/positions.md",
        "content/quotes.md",
        "content/trade-api-faq .md",
        "content/websocket/websocket.md",
    ]
    _write(kotak / "content-paths.txt", "\n".join(content_files))
    for rel in content_files:
        _write(kotak / "raw" / rel)
    _write(
        kotak / "raw/content/login-with-totp.md",
        "tradeApiLogin tradeApiValidate Authorization neo-fin-key TOTP MPIN",
    )
    _write(kotak / "raw/content/curl-examples.md", "Auth Sid neo-fin-key Quotes do not send ts")
    _write(
        kotak / "raw/content/order/cancel-order.md",
        "/quick/order/cancel /quick/order/bo/exit /quick/order/co/exit neo-fin-key trading symbol",
    )
    _write(kotak / "raw/content/instruments.md", "pTrdSymbol 'ts' field Authorization")
    _write(kotak / "raw/content/quotes.md", "plain token Authorization nse_cm")
    _write(kotak / "raw/content/websocket/websocket.md", "Connect to Order feed Session Token sid Data Center")

    for rel in [
        "inventories/00-docs.json",
        "inventories/02-api-keys.json",
        "inventories/03-python-sdk.json",
        "inventories/04-curl-docs.json",
        "public-docs-extract/curl-historical-data.json",
        "public-docs-extract/curl-instruments.json",
        "public-docs-extract/curl-live-data.json",
        "public-docs-extract/curl-margin.json",
        "public-docs-extract/curl-orders.json",
        "public-docs-extract/curl-portfolio.json",
        "public-docs-extract/curl-smart-orders.json",
        "public-docs-extract/curl-user.json",
    ]:
        _write(groww / rel)
    _write(groww / "public-docs-extract/api-keys.json", "Groww Cloud | API Keys static-ip-api-trading-setup")
    _write(groww / "public-docs-extract/python-sdk-intro.json", "pip install growwapi GrowwAPI.get_access_token api_key secret pyotp")
    _write(
        groww / "public-docs-extract/python-sdk-orders.json",
        "place_order modify_order cancel_order get_order_status_by_reference get_order_detail",
    )
    _write(groww / "public-docs-extract/python-sdk-live-data.json", "get_quote market_depth open_interest")
    _write(
        groww / "public-docs-extract/python-sdk-historical-data.json",
        "get_historical_candle_data interval_in_minutes candles",
    )
    _write(groww / "public-docs-extract/python-sdk-instruments.json", "instruments.csv exchange_token trading_symbol")
    _write(
        groww / "public-docs-extract/python-sdk-portfolio.json",
        "get_holdings_for_user get_positions_for_user trading_symbol",
    )
    _write(
        groww / "public-docs-extract/python-sdk-margin.json",
        "get_available_margin_details get_order_margin_details fno_margin_details",
    )
    _write(
        groww / "public-docs-extract/python-sdk-smart-orders.json",
        "create_smart_order cancel_smart_order SMART_ORDER_TYPE_GTT SMART_ORDER_TYPE_OCO",
    )
    _write(groww / "public-docs-extract/python-sdk-feed.json", "GrowwFeed subscribe_ltp subscribe_market_depth feed.consume")
    _write(groww / "public-docs-extract/python-sdk-user.json", "get_user_profile vendor_user_id active_segments")

    for rel in [
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
    ]:
        _write(indstocks / rel)
    _write(indstocks / "public-docs-extract/faq.json", "pip install indstocks-sdk npm install indstocks-sdk")
    _write(indstocks / "public-docs-extract/users-auth.json", "GET /user/profile GET /funds Authorization: YOUR_ACCESS_TOKEN")
    _write(indstocks / "public-docs-extract/instruments-master.json", "GET /market/instruments security_id instruments.csv")
    _write(
        indstocks / "public-docs-extract/market-quote.json",
        "GET /market/quotes/full GET /market/quotes/ltp live_price market_depth",
    )
    _write(indstocks / "public-docs-extract/historical-data.json", "GET /market/historical/{interval} 1minute candles")
    _write(
        indstocks / "public-docs-extract/websockets.json",
        "wss://ws-prices.indstocks.com/api/v1/ws/prices "
        "wss://ws-order-updates.indstocks.com/api/v1/ws/trades order_updates",
    )
    _write(indstocks / "public-docs-extract/normal-orders.json", "POST /order POST /order/modify POST /order/cancel algo_id")
    _write(
        indstocks / "public-docs-extract/smart-orders-gtt.json",
        "POST /smart/order POST /smart/order/cancel sl_trigger_price tgt_trigger_price",
    )
    _write(indstocks / "public-docs-extract/margin-calculation.json", "GET /margin total_margin brokerage")
    _write(
        indstocks / "public-docs-extract/portfolio-funds.json",
        "GET /portfolio/holdings GET /portfolio/positions pnl_absolute",
    )
    _write(indstocks / "public-docs-extract/utility.json", "GET /option-chain GET /option-chain-symbols")
    return mcp, kotak


def test_validate_inventory_accepts_complete_public_reference_captures(tmp_path: Path) -> None:
    _write_valid_capture(tmp_path)

    results = checker.validate_inventory(tmp_path)

    assert results
    assert all(result.ok for result in results), [result.message for result in results]


def test_validate_inventory_reports_missing_markers(tmp_path: Path) -> None:
    _write_valid_capture(tmp_path)
    (tmp_path / "broker-mcp-current-20260706T000000Z/raw/upstox.html").write_text(
        "https://mcp.upstox.com/mcp Claude Desktop ChatGPT Cursor VS Code",
        encoding="utf-8",
    )

    results = checker.validate_inventory(tmp_path)

    failures = [result.message for result in results if not result.ok]
    assert failures == [
        "MCP page markers: raw/upstox.html: missing marker 'read-only access', "
        "raw/upstox.html: missing marker 'daily re-authorization'"
    ]


def test_validate_inventory_uses_latest_timestamped_mcp_capture(tmp_path: Path) -> None:
    old_mcp, _ = _write_valid_capture(tmp_path)
    new_mcp = tmp_path / "broker-mcp-current-20260706T010000Z"
    for path in old_mcp.rglob("*"):
        if path.is_file():
            target = new_mcp / path.relative_to(old_mcp)
            _write(target, path.read_text(encoding="utf-8"))
    (new_mcp / "raw/groww.html").write_text("stale", encoding="utf-8")

    results = checker.validate_inventory(tmp_path)

    failures = [result.message for result in results if not result.ok]
    assert failures == [
        "MCP page markers: raw/groww.html: missing marker 'https://mcp.groww.in/mcp', "
        "raw/groww.html: missing marker 'growwmcp', "
        "raw/groww.html: missing marker 'mcp-remote@0.1.18', "
        "raw/groww.html: missing marker '52155', "
        "raw/groww.html: missing marker 'ddpi', "
        "raw/groww.html: missing marker 'no background syncing', "
        "raw/groww.html: missing marker 'no data storage on ai servers', "
        "raw/groww.html: missing marker 'stocks and f&o'"
    ]


def test_validate_inventory_reports_missing_api_doc_markers(tmp_path: Path) -> None:
    _write_valid_capture(tmp_path)
    (tmp_path / "indstocks-api-docs/public-docs-extract/websockets.json").write_text(
        "wss://ws-prices.indstocks.com/api/v1/ws/prices",
        encoding="utf-8",
    )

    results = checker.validate_inventory(tmp_path)

    failures = [result.message for result in results if not result.ok]
    assert failures == [
        "INDstocks API page markers: public-docs-extract/websockets.json: missing marker "
        "'wss://ws-order-updates.indstocks.com/api/v1/ws/trades', "
        "public-docs-extract/websockets.json: missing marker 'order_updates'"
    ]
