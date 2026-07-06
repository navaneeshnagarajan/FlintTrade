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
