"""Installed-web frontend serving regressions.

These tests exercise the Flask test client only; they do not start the app or
open a browser.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import structlog
from flask import Flask


def _create_frontend_app(dist: Path, monkeypatch: pytest.MonkeyPatch) -> Flask:
    """Create a rate-limited test app around the supplied frontend tree."""
    monkeypatch.setenv("FLINTTRADE_FRONTEND_DIST", str(dist))
    monkeypatch.setenv("OPENALGO_API_KEY", "spa-static-serving-test-key")

    from flinttrade_core import app as app_module

    real_limiter = app_module.Limiter

    def _one_per_hour_limiter(*args: object, **kwargs: object):
        kwargs["default_limits"] = ["1 per hour"]
        return real_limiter(*args, **kwargs)

    monkeypatch.setattr(app_module, "Limiter", _one_per_hour_limiter)
    app = app_module.create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def built_frontend_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Flask:
    """Build an app around a tiny, real frontend output tree."""
    dist = tmp_path / "dist"
    assets = dist / "assets"
    fonts = dist / "fonts"
    assets.mkdir(parents=True)
    fonts.mkdir()
    (dist / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.js").write_bytes(b"globalThis.flintTradeLoaded = true;\n")
    (fonts / "app.woff2").write_bytes(b"test-font")

    return _create_frontend_app(dist, monkeypatch)


@pytest.mark.unit
def test_nested_frontend_asset_is_served_instead_of_spa_html(built_frontend_app: Flask) -> None:
    """A nested asset path must retain its bytes and JavaScript MIME type."""
    response = built_frontend_app.test_client().get("/assets/app.js")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "globalThis.flintTradeLoaded = true;\n"
    assert response.mimetype != "text/html"


@pytest.mark.unit
def test_missing_frontend_asset_returns_404_instead_of_spa_html(built_frontend_app: Flask) -> None:
    """A stale chunk URL must fail explicitly rather than masquerading as HTML."""
    response = built_frontend_app.test_client().get("/assets/missing.js")

    assert response.status_code == 404
    assert response.mimetype != "text/html"


@pytest.mark.unit
@pytest.mark.parametrize(
    "path",
    ["/index.html", "/INDEX.HTML", "/Index.Html", "/./index.html", "/_static_flask/index.html"],
)
def test_direct_index_path_uses_the_csp_nonce(built_frontend_app: Flask, path: str) -> None:
    """Every route that serves the SPA document must use its response nonce."""
    response = built_frontend_app.test_client().get(path)
    body = response.get_data(as_text=True)
    csp = response.headers["Content-Security-Policy"]

    html_nonce = re.search(r'<script nonce="([^"]+)"', body)
    header_nonce = re.search(r"'nonce-([^']+)'", csp)

    assert response.status_code == 200
    assert html_nonce is not None
    assert header_nonce is not None
    assert html_nonce.group(1) == header_nonce.group(1)


@pytest.mark.unit
def test_frontend_asset_burst_is_not_rate_limited(built_frontend_app: Flask) -> None:
    """One page load may fetch more than the API's 50-request default limit."""
    client = built_frontend_app.test_client()

    statuses = [
        [client.get(path).status_code for _ in range(2)]
        for path in ("/assets/app.js", "/fonts/app.woff2")
    ]

    assert statuses == [[200, 200], [200, 200]]


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/assets/missing.js", "/fonts/missing.woff2"])
def test_missing_frontend_asset_remains_rate_limited(built_frontend_app: Flask, path: str) -> None:
    """Missing static paths must not bypass the default request limit."""
    client = built_frontend_app.test_client()

    statuses = [client.get(path).status_code for _ in range(2)]

    assert statuses == [404, 429]


@pytest.mark.unit
def test_frontend_symlink_escape_remains_rate_limited(
    built_frontend_app: Flask,
    tmp_path: Path,
) -> None:
    """A static-path symlink outside dist is neither served nor exempted."""
    outside = tmp_path / "outside.js"
    outside.write_bytes(b"must not be served")
    escaped = Path(built_frontend_app.config["_DIST_PATH"]) / "assets" / "escape.js"
    try:
        escaped.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("this runner cannot create symbolic links")

    client = built_frontend_app.test_client()
    statuses = [client.get("/assets/escape.js").status_code for _ in range(2)]

    assert statuses == [404, 429]


@pytest.mark.unit
@pytest.mark.parametrize("path", ["/assets/../index.html", "/assets/%2e%2e/index.html"])
def test_frontend_static_traversal_alias_remains_rate_limited(
    built_frontend_app: Flask,
    path: str,
) -> None:
    """A static-looking URL may not exempt a file outside its static subtree."""
    client = built_frontend_app.test_client()

    statuses = [client.get(path).status_code for _ in range(2)]

    assert statuses == [200, 429]


@pytest.mark.unit
def test_frontend_internal_symlink_alias_remains_rate_limited(
    built_frontend_app: Flask,
) -> None:
    """A static-subtree symlink back to dist/index.html must not be exempted."""
    dist = Path(built_frontend_app.config["_DIST_PATH"])
    escaped = dist / "assets" / "index-alias.html"
    try:
        escaped.symlink_to(dist / "index.html")
    except (NotImplementedError, OSError):
        pytest.skip("this runner cannot create symbolic links")

    client = built_frontend_app.test_client()
    statuses = [client.get("/assets/index-alias.html").status_code for _ in range(2)]

    assert statuses == [200, 429]


@pytest.mark.unit
def test_symlinked_static_root_does_not_broaden_the_exemption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An assets directory aliased to dist itself must not become an exemption root."""
    dist = tmp_path / "dist-root-alias"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    try:
        (dist / "assets").symlink_to(dist, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("this runner cannot create symbolic links")

    app = _create_frontend_app(dist, monkeypatch)
    client = app.test_client()
    statuses = [client.get("/assets/index.html").status_code for _ in range(2)]

    assert statuses == [200, 429]


@pytest.mark.unit
def test_looping_static_root_does_not_abort_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed optional assets directory must stay non-exempt without crashing."""
    dist = tmp_path / "dist-static-loop"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    try:
        (dist / "assets").symlink_to("assets", target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("this runner cannot create symbolic links")

    app = _create_frontend_app(dist, monkeypatch)
    client = app.test_client()
    statuses = [client.get("/assets/missing.js").status_code for _ in range(2)]

    assert statuses == [404, 429]


@pytest.mark.unit
def test_looping_frontend_override_degrades_to_api_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed optional dist override must not abort backend startup."""
    dist = tmp_path / "dist-loop"
    try:
        dist.symlink_to(dist, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("this runner cannot create symbolic links")

    app = _create_frontend_app(dist, monkeypatch)

    assert app.config["_FRONTEND_AVAILABLE"] is False


@pytest.mark.unit
def test_unknown_api_route_remains_rate_limited(built_frontend_app: Flask) -> None:
    """The SPA exemption must not cover unknown paths in an API namespace."""
    client = built_frontend_app.test_client()

    statuses = [client.get("/api/not-a-real-route").status_code for _ in range(2)]

    assert statuses == [404, 429]


@pytest.mark.unit
def test_generic_spa_route_remains_rate_limited(built_frontend_app: Flask) -> None:
    """Only static build files, not every catch-all route, bypass the default limit."""
    client = built_frontend_app.test_client()

    statuses = [client.get("/portfolio/example").status_code for _ in range(2)]

    assert statuses == [200, 429]


@pytest.mark.unit
def test_rate_limited_request_log_uses_the_current_request_id(
    built_frontend_app: Flask,
) -> None:
    """A rejected request must not inherit the preceding request's log context."""
    app = built_frontend_app

    @app.get("/rate-limit-context-probe")
    def _rate_limit_context_probe() -> str:
        return "ok"

    observed: list[tuple[int, str | None]] = []

    @app.after_request
    def _capture_request_context(response):  # type: ignore[no-untyped-def]
        observed.append(
            (
                response.status_code,
                structlog.contextvars.get_contextvars().get("request_id"),
            )
        )
        return response

    client = app.test_client()
    accepted = client.get(
        "/rate-limit-context-probe",
        headers={
            "X-API-Key": "spa-static-serving-test-key",
            "X-Request-ID": "accepted-request",
        },
    )

    limited = client.get(
        "/rate-limit-context-probe",
        headers={
            "X-API-Key": "spa-static-serving-test-key",
            "X-Request-ID": "limited-request",
        },
    )

    assert accepted.status_code == 200
    assert limited.status_code == 429
    assert observed == [(200, "accepted-request"), (429, "limited-request")]

@pytest.mark.unit
def test_nested_docs_index_html_exact_sentinel_stays_nested(
    built_frontend_app: Flask,
) -> None:
    """nested `docs/index.html` exact sentinel must stay nested (never treated as root SPA)."""
    dist = Path(built_frontend_app.config["_DIST_PATH"])
    docs = dist / "docs"
    docs.mkdir()
    sentinel = "NESTED_DOCS_INDEX_SENTINEL_EXACT"
    (docs / "index.html").write_text(
        f"<!doctype html><p>{sentinel}</p>", encoding="utf-8"
    )

    response = built_frontend_app.test_client().get("/docs/index.html")
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert sentinel in body
    assert "flintTradeLoaded" not in body  # not the root SPA content


@pytest.mark.unit
def test_direct_root_index_html_case_insensitive_serves_spa_with_nonce(
    built_frontend_app: Flask,
) -> None:
    """direct root `/INDEX.HTML` must serve root SPA with nonce under case-insensitive resolution."""
    response = built_frontend_app.test_client().get("/INDEX.HTML")
    body = response.get_data(as_text=True)
    csp = response.headers.get("Content-Security-Policy", "")

    assert response.status_code == 200
    assert 'src="/assets/app.js"' in body  # root SPA index served (case-insensitive matched to root)
    # nonce present in html or header
    assert 'nonce="' in body or "nonce-" in csp
