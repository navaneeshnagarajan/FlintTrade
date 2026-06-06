"""Contract test — `packages/apps/terminal/src/services/api.ts` ↔ Flask order routes.

This file does NOT test runtime behaviour. It is a static parity check that
catches the exact kind of bug the 2026-05-19 Codex stop-gate review surfaced:

- `dcebc35` flipped the backend ``orders_bp`` prefix from ``/v1/orders`` to
  ``/api/v1/orders`` to match the frontend.
- `3f80518` aligned half the frontend leaf names (``cancelorder`` → ``cancel``,
  etc.) — but the safety-proxy was still wide open for accidental drift.
- `f754cff` added ``/options`` + ``/options-multi`` to close a mode-gate
  bypass that was discovered when `optionsOrder` had been temporarily
  routed through OpenAlgo direct.
- `9fe4dd3` retro-fitted regression coverage for the new routes.

Each of those incidents stemmed from the same root cause: the frontend's
``postOrder("leaf", body)`` strings and the backend's ``@orders_bp.route("/leaf")``
declarations are two halves of an undeclared contract. If either side
silently drifts, the bug only shows up in production.

This test asserts that the SET of order-leaf names declared by the frontend
matches the SET of order-leaf names registered by the backend, for both:

- the core safety-proxy blueprint (``orders_bp``, place / cancel / etc.)
- the engine advanced-order blueprint (``order_bp``, basket / split / etc.)

If a frontend dev adds a new ``postOrder("foo", …)`` call without a matching
backend handler, this test fails. Symmetrically, if a backend route is added
without a frontend caller, the test surfaces the orphan so the dev decides
whether to wire it up or remove it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — locate the frontend service file and parse postOrder("leaf", …)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_API_TS = _REPO_ROOT / "packages" / "apps" / "terminal" / "src" / "services" / "api.ts"

# Regex hits `postOrder<…>("leaf", …)` and captures the leaf string. The
# generic-type angle brackets are optional because the call site may or may
# not annotate the response type.
_POSTORDER_CALL_RE = re.compile(
    r"postOrder\s*(?:<[^>]*>)?\s*\(\s*\"(?P<leaf>[a-z][a-z0-9-]*)\"",
    re.MULTILINE,
)


def _frontend_postorder_leaves() -> set[str]:
    """Return the set of ``postOrder("leaf", …)`` leaf names in ``api.ts``.

    Reads the source file as text rather than executing TypeScript so the
    test can run without a Node toolchain. The regex is intentionally narrow
    — only matches lower-kebab-case leaves to avoid false positives in
    comments or strings used for other purposes.
    """
    if not _API_TS.exists():
        pytest.skip(f"Frontend service file not found at {_API_TS}")
    source = _API_TS.read_text(encoding="utf-8")
    return {m.group("leaf") for m in _POSTORDER_CALL_RE.finditer(source)}


def _backend_order_route_leaves() -> set[str]:
    """Return the set of leaf names registered under ``/api/v1/orders/*``.

    Boots the Flask app via ``create_flask_app()`` and walks ``url_map`` so
    the result reflects whichever blueprints are currently wired in
    ``app.py`` — exactly what a real request would hit.
    """
    from flinttrade_core.app import create_flask_app  # noqa: PLC0415

    app = create_flask_app()
    leaves: set[str] = set()
    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if path.startswith("/api/v1/orders/"):
            leaf = path[len("/api/v1/orders/"):]
            # Skip routes with URL parameters (e.g. /bracket/<id>) — those
            # are not the kind of static leaf the frontend addresses via
            # postOrder("name", ...).
            if "<" in leaf or not leaf:
                continue
            leaves.add(leaf)
    return leaves


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrderContract:
    """Bidirectional parity between frontend `postOrder(...)` calls and
    backend `@orders_bp.route` / `@order_bp.route` declarations."""

    def test_every_frontend_call_has_a_backend_route(self):
        """A `postOrder("foo", ...)` call without `/api/v1/orders/foo` would
        404 in production — the bug `dcebc35` was meant to fix."""
        frontend = _frontend_postorder_leaves()
        backend = _backend_order_route_leaves()
        missing = frontend - backend
        assert not missing, (
            # Plain string (not f-string) — the {leaf} placeholder is filled in by
            # the .replace() chained below. Previously this was an f-string which
            # caused F821 (undefined `leaf`) under ruff because Python evaluates
            # f-strings eagerly even inside the assert-message expression.
            "Frontend calls postOrder(\"{leaf}\", …) for leaves with no "
            f"matching backend route under /api/v1/orders/: {sorted(missing)}.\n"
            "Either add the backend handler (mirror an existing route in "
            "packages/core/core/src/order_routes.py or packages/services/engine/src/order_routes.py) "
            "or rename the frontend call to a leaf that exists."
        ).replace("{leaf}", next(iter(missing), ""))

    def test_every_backend_route_has_a_frontend_caller(self):
        """A `/api/v1/orders/foo` handler with no frontend caller is either
        dead or undocumented — flag it. To intentionally keep a backend-only
        endpoint, add it to `_BACKEND_ONLY_LEAVES` below with a justification."""
        frontend = _frontend_postorder_leaves()
        backend = _backend_order_route_leaves()
        unused = backend - frontend - _BACKEND_ONLY_LEAVES
        assert not unused, (
            f"Backend registers /api/v1/orders/{{leaf}} for leaves with no "
            f"frontend caller: {sorted(unused)}.\n"
            "Either wire the frontend to call them via postOrder(...), remove "
            "the dead routes, or add the leaf to _BACKEND_ONLY_LEAVES in this "
            "test with a justification comment."
        )

    def test_frontend_extraction_finds_known_calls(self):
        """Sanity check on the regex — at minimum, the canonical
        `place`, `cancel`, and `options` calls must be detected. If this
        breaks, the regex needs adjusting before the other two tests
        become meaningful."""
        frontend = _frontend_postorder_leaves()
        for required in ("place", "cancel", "options"):
            assert required in frontend, (
                f"Regex failed to find postOrder(\"{required}\", …) in "
                f"{_API_TS} — adjust _POSTORDER_CALL_RE before trusting "
                "the contract assertions."
            )


# ---------------------------------------------------------------------------
# Allowlist — backend routes we intentionally keep without a frontend caller
# ---------------------------------------------------------------------------

# Order endpoints that exist on the backend for internal / direct-API use
# (curl, n8n flows, automation scripts, paper-trading harness tests) but are
# not called from the React terminal. If a leaf is here, the absence of a
# frontend caller is by design.
_BACKEND_ONLY_LEAVES: set[str] = {
    # `options-strategy` — engine helper for named multi-leg strategies
    # (iron_condor, etc.). The terminal builds its own multi-leg payloads
    # via `optionsMultiOrder` (which calls `/options-multi`) and does not
    # consume the named-strategy endpoint directly today.
    "options-strategy",
    # `bracket` and `brackets` — bracket order endpoints (engine
    # `bracket_routes.py`). Frontend clients exist
    # (`ftApi.trading.ts::placeBracketOrder` / `getActiveBrackets` /
    # `cancelBracketOrder`) but are NOT YET consumed by any terminal
    # component — there is no bracket-order entry/management UI today, so
    # these endpoints currently have no frontend caller. Kept here as a
    # known, intentional gap (the bracket UI is a planned follow-up); the
    # backend + its gated path are fully tested in `test_bracket_routes.py`.
    "bracket",
    "brackets",
}
