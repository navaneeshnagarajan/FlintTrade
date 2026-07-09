"""Contract tests for the mock-shape-drift bug class.

Frontend and backend are tested in isolation with mocks. Two drifts slip
through both suites green yet break production:

1. **Async-client shape** — code + tests drive ``router.client.<method>()`` on a
   MagicMock, so a rename/removal of an :class:`OpenAlgoClient` method is invisible
   to those tests. This asserts the methods callers depend on still exist and are
   still coroutines.
2. **Route existence** — the frontend calls ``/api/v1/<x>`` (or ``/v1/<x>``), but the
   backend blueprint may be registered at the wrong prefix or dropped (the recurring
   ``/v1`` vs ``/api/v1`` wiring bug). This asserts every endpoint the terminal's
   ftApi layer calls maps to a real route on the assembled Flask app.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

# packages/core/core/tests/<this file> → repo root is 4 parents up.
ROOT = Path(__file__).resolve().parents[4]
FTAPI_DIR = ROOT / "packages" / "apps" / "terminal" / "src" / "services"


# ---------------------------------------------------------------------------
# 1. Async-client shape
# ---------------------------------------------------------------------------


def test_openalgo_client_exposes_expected_async_methods() -> None:
    from flinttrade_core.openalgo_client import OpenAlgoClient

    # Methods production code + MagicMock-based tests depend on. A rename here
    # would keep every mock test green while breaking the real order/data path.
    expected_async = {
        "place_order", "place_smart_order", "modify_order", "cancel_order",
        "cancel_all_orders", "close_position", "order_status",
        "positionbook", "orderbook", "tradebook", "holdings", "funds", "margin",
        "quotes", "depth", "history", "option_chain", "expiry", "ping", "close",
    }
    for name in sorted(expected_async):
        method = getattr(OpenAlgoClient, name, None)
        assert method is not None, f"OpenAlgoClient.{name} is gone — callers/mocks depend on it"
        assert inspect.iscoroutinefunction(method), f"OpenAlgoClient.{name} is no longer async"

    # run_sync is the SYNC entry point that marshals a client coroutine onto the
    # client's own persistent loop (the Telegram bot + Flask routes rely on it).
    run_sync = getattr(OpenAlgoClient, "run_sync", None)
    assert callable(run_sync), "OpenAlgoClient.run_sync missing — sync callers depend on it"
    assert not inspect.iscoroutinefunction(run_sync), "run_sync must stay synchronous"


# ---------------------------------------------------------------------------
# 2. Route existence for ftApi-called URLs
# ---------------------------------------------------------------------------

# Endpoints the ftApi layer builds fully dynamically (path segment interpolated,
# not just a trailing id), so a static rule match is not meaningful. Kept short
# and explicit — each is a conscious exemption, not a silent skip.
_DYNAMIC_ENDPOINT_ALLOWLIST: set[str] = set()


def _frontend_called_paths() -> set[str]:
    """Extract the full backend paths the terminal ftApi helpers call.

    get/post/patch/del("x") → ``/api/v1/x``; getV1/postV1("x") → ``/v1/x``. Only
    the literal head (before any ``?`` query or ``+`` concatenation) is used.
    """
    paths: set[str] = set()
    pattern = re.compile(r'\b(get|post|patch|del|getV1|postV1)(?:<[^>]*>)?\(\s*"([^"?]+)')
    for ts in FTAPI_DIR.glob("ftApi*.ts"):
        for helper, endpoint in pattern.findall(ts.read_text(encoding="utf-8")):
            endpoint = endpoint.strip()
            if not endpoint or "${" in endpoint:
                continue
            prefix = "/v1/" if helper.endswith("V1") else "/api/v1/"
            paths.add((prefix + endpoint).rstrip("/"))
    return paths


def _backend_static_prefixes(app) -> set[str]:
    """Static (param-free) prefix of every registered rule, e.g.
    ``/api/v1/journal/entries/<id>`` → ``/api/v1/journal/entries``."""
    prefixes: set[str] = set()
    for rule in app.url_map.iter_rules():
        static = rule.rule.split("<", 1)[0].rstrip("/")
        prefixes.add(static)
        prefixes.add(rule.rule.rstrip("/"))  # also the full rule for no-param routes
    return prefixes


def test_frontend_ftapi_routes_exist_in_backend() -> None:
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    backend = _backend_static_prefixes(app)
    called = _frontend_called_paths()
    assert called, "extracted no ftApi endpoints — the parser or ftApi layout changed"

    missing = sorted(
        fp
        for fp in called
        if fp not in _DYNAMIC_ENDPOINT_ALLOWLIST
        and fp not in backend
        and not any(b.startswith(fp + "/") or fp.startswith(b + "/") for b in backend)
    )
    assert not missing, (
        f"{len(missing)} ftApi-called route(s) have NO matching backend rule "
        f"(the /v1 vs /api/v1 wiring bug, or a dropped blueprint):\n  "
        + "\n  ".join(missing)
    )
