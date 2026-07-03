"""Contract test — every literal ``fetch("/ft-api/…")`` in the terminal resolves.

Ground truth for Phase 1 G8 (`.local/specs/audit/gap-map.md`). The single most
recurrent bug class in this repo's history is a frontend URL whose backend
route is unregistered or sits under the wrong prefix — the ``/api/v1`` vs
``/v1`` 404 (commits ``dcebc35``, ``3208b0b3``, ``c7db123b``, ``e51b40e5``,
``353b4f77``). ``test_orders_contract.py`` nets the order-route family; this
test extends the same idea to the **prefix-sensitive direct-fetch island** —
the auth/config/admin/breadth/shortcuts/tax/docs endpoints the terminal calls
with a literal ``fetch("/ft-api/…")`` rather than through the ``ftApi`` helpers.

The terminal reaches the backend through the Vite ``/ft-api`` proxy, which the
backend's WSGI middleware strips before dispatch. So a literal
``fetch("/ft-api/v1/auth/login")`` must resolve, after the strip, to a
registered rule at ``/v1/auth/login``. This test boots the real app factory,
collects every literal ``/ft-api/…`` path from the terminal source, strips the
``/ft-api`` prefix and any query string exactly as the middleware does, and
asserts each path matches a rule in the live ``url_map``. A frontend dev moving
a route to the wrong prefix, or a backend dev renaming a blueprint prefix,
fails this test instead of shipping a silent 404.

Helper-based calls (``post``/``get``/``postV1``/``getV1`` with interpolated
endpoints) are intentionally out of scope here — their dynamic ``${…}``
segments cannot be resolved statically without guessing, and the order family
(the safety-critical helper surface) already has ``test_orders_contract.py``.
This test deliberately covers only the deterministic literal-fetch surface,
which is exactly where the prefix-sensitive auth island lives.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TERMINAL_SRC = _REPO_ROOT / "packages" / "apps" / "terminal" / "src"

# Matches fetch("/ft-api/…") and fetch(`/ft-api/…`) — captures the path up to
# the first quote/backtick, ``?`` (query string), or ``${`` (interpolation).
_FETCH_LITERAL_RE = re.compile(
    r"""fetch\(\s*[`"']/ft-api/(?P<path>[a-zA-Z0-9/_.-]+)""",
)


def _frontend_ft_api_paths() -> set[str]:
    """Collect every literal ``/ft-api/<path>`` fetch across the terminal source.

    Returns paths WITHOUT the ``/ft-api`` prefix and WITHOUT any query string,
    i.e. exactly what the WSGI ``/ft-api`` stripper hands to the URL map.
    """
    if not _TERMINAL_SRC.exists():
        pytest.skip(f"terminal source not found at {_TERMINAL_SRC}")

    paths: set[str] = set()
    for ts_file in _TERMINAL_SRC.rglob("*.ts*"):
        # Skip test files — they assert on mocked URLs, not real call sites.
        if "__tests__" in ts_file.parts or ts_file.name.endswith((".test.ts", ".test.tsx")):
            continue
        source = ts_file.read_text(encoding="utf-8")
        for match in _FETCH_LITERAL_RE.finditer(source):
            raw = match.group("path")
            # Drop a trailing dot the regex may greedily catch before ``${``.
            stripped = "/" + raw.rstrip("./")
            paths.add(stripped)
    return paths


# Endpoints that match by catch-all rather than by being the intended API
# route. The SPA fallback matches any GET path (client-side routing) AND raises
# MethodNotAllowed for other verbs on any path, so it can never count as a real
# backend route match.
_CATCH_ALL_ENDPOINTS = {"_spa_fallback", "static"}


@pytest.fixture(scope="module")
def api_route_patterns(tmp_path_factory, monkeypatch_module):
    """Compiled anchored regexes for every real (non-catch-all) registered rule.

    Boots the full app factory against an isolated workspace with a seeded
    ``master_password`` file (the factory reads it via ``_get_master_password``
    — it takes no password argument), so every blueprint is registered exactly
    as in production, then converts each rule template to a path regex.
    ``<path:x>`` matches across slashes; ``<x>`` / ``<conv:x>`` match one
    segment. Catch-all endpoints are excluded so a genuine 404 can't hide
    behind the SPA fallback.
    """
    ws = tmp_path_factory.mktemp("ft_contract_ws")
    (ws / "master_password").write_text("contract-test-master-password", encoding="utf-8")
    monkeypatch_module.setenv("FLINTTRADE_WORKSPACE_DIR", str(ws))
    # Register the dev-only admin/infra/backup blueprints too, so their
    # frontend callers (AdminRoute's /v1/admin/* fetches) are checked against
    # the routes that DO exist when the operator runs in dev — otherwise they'd
    # read as false 404s here.
    monkeypatch_module.setenv("FLINTTRADE_DEV", "1")

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    converter = re.compile(r"<(?:[^:<>]+:)?(?P<name>[^<>]+)>")

    patterns: list[re.Pattern[str]] = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in _CATCH_ALL_ENDPOINTS:
            continue
        template = rule.rule
        regex_parts: list[str] = []
        pos = 0
        for m in converter.finditer(template):
            regex_parts.append(re.escape(template[pos:m.start()]))
            # ``<path:...>`` is the only converter that spans slashes.
            seg = ".+" if template[m.start():m.end()].startswith("<path:") else "[^/]+"
            regex_parts.append(seg)
            pos = m.end()
        regex_parts.append(re.escape(template[pos:]))
        patterns.append(re.compile("^" + "".join(regex_parts) + "$"))
    return patterns


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (the built-in ``monkeypatch`` is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _resolves(patterns, path: str) -> bool:
    """True if ``path`` matches any real (non-catch-all) registered rule."""
    return any(p.match(path) for p in patterns)


# Frontend literal fetches with NO backend route — the shrinking known-gap
# list (mirrors the ``test_no_legacy_order_path.py`` allowlist pattern). Each
# entry is a real, tracked 404 the audit already found; fixing it must remove
# the entry (the shrink guard below fails if a listed path starts resolving).
_KNOWN_UNRESOLVED = {
    # SectorMap → PortfolioRRGTab fetches this; no backend route exists. Gap
    # G20 (feature-matrix.md, terminal-widgets-analysis) — Phase 2: build the
    # route or remove the dead tab. Its co-located test mocks fetch, so only
    # this contract test catches the 404.
    "/v1/rrg/portfolio",
}


@pytest.mark.integration
def test_every_literal_ft_api_fetch_resolves(api_route_patterns):
    paths = _frontend_ft_api_paths()
    # Sanity: the auth island must be present, or the extractor silently broke.
    assert "/v1/auth/login" in paths, "extractor found no auth routes — regex drift?"
    # Sanity: the matcher must reject a wrong-prefix / bogus path (guards the
    # SPA-fallback false-positive that an earlier revision of this test hit).
    assert not _resolves(api_route_patterns, "/api/v1/auth/login"), (
        "matcher accepts a wrong-prefix path — SPA fallback leaking into the check"
    )
    assert not _resolves(api_route_patterns, "/v1/does-not-exist")

    unresolved = {p for p in paths if not _resolves(api_route_patterns, p)}

    new_breakage = sorted(unresolved - _KNOWN_UNRESOLVED)
    assert not new_breakage, (
        "Terminal calls these literal /ft-api paths that resolve to NO backend "
        f"route (the recurring /api/v1-vs-/v1 404 class): {new_breakage}"
    )

    # Shrink guard: a known-gap path that now resolves must be removed from the
    # allowlist, so the list can only shrink as fixes land.
    fixed = sorted(p for p in _KNOWN_UNRESOLVED if _resolves(api_route_patterns, p))
    assert not fixed, (
        f"These paths now resolve — remove them from _KNOWN_UNRESOLVED: {fixed}"
    )
