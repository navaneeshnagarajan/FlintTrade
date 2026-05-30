"""Content Security Policy (CSP) and security headers middleware.

Provides a configurable CSP policy dict, a formatter, an
``apply_security_headers()`` after-request hook, and a
``/csp-report`` violation endpoint.

Wire into Flask::

    from flinttrade_core.csp import apply_security_headers, csp_report_bp
    app.after_request(apply_security_headers)
    app.register_blueprint(csp_report_bp)

The default policy follows OWASP recommendations and is intentionally
strict.  The ``unsafe-inline`` entries for ``script-src`` and
``style-src`` are included because the React SPA (served by Vite)
currently requires them; a ``TODO`` marker flags where nonce-based
removal should happen in a later hardening pass.
"""

from __future__ import annotations

import logging
import re
import secrets
from typing import Any

from flask import Blueprint, Response, g, request

logger = logging.getLogger("flinttrade.csp")


def generate_nonce() -> str:
    """Generate a fresh 128-bit random nonce for a single response.

    Attach to ``flask.g`` at request start so templates / inline script
    attributes can read it, and :func:`apply_security_headers` will
    weave it into the ``Content-Security-Policy`` header.
    """
    return secrets.token_urlsafe(16)


# ---------------------------------------------------------------------------
# Default CSP policy
# ---------------------------------------------------------------------------

#: Default Content Security Policy directives.
#:
#: Each key is a CSP directive name; each value is a list of sources.
#: The policy is serialised by :func:`_format_csp`.
CSP_POLICY: dict[str, list[str]] = {
    "default-src": ["'self'"],
    # Scripts: self + strict-dynamic; nonces are injected per-response via
    # `apply_security_headers` so dynamically-inserted scripts carry a valid
    # nonce. 'unsafe-inline' is intentionally omitted from script-src —
    # removing it was the point of this hardening. 'strict-dynamic' allows
    # nonce-approved scripts to load further scripts without re-nonce.
    "script-src": ["'self'", "'strict-dynamic'"],
    # Styles still allow inline: Tailwind utility classes compile to static
    # CSS but a small number of runtime style props (framer-motion, Radix)
    # emit inline <style> elements. Migrating those is tracked separately.
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", "https:"],
    # connect-src is intentionally permissive across protocols: the OpenAlgo host is
    # user-configurable (localhost, VPN 10.x, or a remote server) so we cannot pin it.
    # This mirrors the policy the terminal previously shipped in its <meta> CSP (now
    # removed in favour of this per-request HTTP header). The XSS-containment value of
    # CSP's XSS value comes from the script directive (nonce-based, no inline allowance),
    # not connect-src.
    "connect-src": ["'self'", "ws:", "wss:", "http:", "https:"],
    "frame-ancestors": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    # Direct browsers to POST violation reports to our endpoint
    "report-uri": ["/csp-report"],
}


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


def _format_csp(policy: dict[str, list[str]]) -> str:
    """Serialise a CSP policy dict into a valid ``Content-Security-Policy`` string.

    Each directive is rendered as ``directive-name source1 source2;``.
    The ``report-uri`` directive, if present, is always appended last.

    Args:
        policy: Mapping of directive names to lists of source values.

    Returns:
        Single-line CSP header value string.

    Example::

        >>> _format_csp({"default-src": ["'self'"], "img-src": ["'self'", "data:"]})
        "default-src 'self'; img-src 'self' data:"
    """
    # Ensure report-uri is last (convention)
    report_uri = policy.get("report-uri")
    directives: list[str] = []
    for name, sources in policy.items():
        if name == "report-uri":
            continue
        if sources:
            directives.append(f"{name} {' '.join(sources)}")
        else:
            directives.append(name)
    if report_uri:
        directives.append(f"report-uri {' '.join(report_uri)}")
    return "; ".join(directives)


def build_csp_header(nonce: str | None = None) -> str:
    """Return the serialised CSP header value, splicing ``nonce`` into ``script-src``.

    The base policy (:data:`CSP_POLICY`) forbids inline scripts (no ``'unsafe-inline'``
    in the script directive); when a per-request ``nonce`` is supplied it is added so the
    nonce-tagged bootstrap script in the served ``index.html`` is permitted and
    ``'strict-dynamic'`` can extend trust to the chunks it loads. The base policy dict is
    never mutated.
    """
    _policy = {k: list(v) for k, v in CSP_POLICY.items()}
    if nonce:
        _policy["script-src"] = _policy.get("script-src", []) + [f"'nonce-{nonce}'"]
    return _format_csp(_policy)


# Matches an opening <script tag that does not already carry a nonce= attribute.
_SCRIPT_TAG_NO_NONCE_RE = re.compile(r"<script(?![^>]*\bnonce=)", re.IGNORECASE)


def inject_csp_nonce(html: str, nonce: str) -> str:
    """Add ``nonce="<nonce>"`` to every ``<script>`` tag in *html* that lacks one.

    Used when the gateway serves the terminal's ``index.html`` so the bootstrap script
    carries the same nonce the response's ``Content-Security-Policy`` header declares.
    A no-op when *nonce* is empty.
    """
    if not nonce:
        return html
    return _SCRIPT_TAG_NO_NONCE_RE.sub(f'<script nonce="{nonce}"', html)


# ---------------------------------------------------------------------------
# Header applicator
# ---------------------------------------------------------------------------


def apply_security_headers(response: Response) -> Response:
    """Apply CSP and additional security headers to every Flask response.

    Designed to be registered as an ``@app.after_request`` callback::

        app.after_request(apply_security_headers)

    Headers applied (only if not already set, so tests / overrides win):

    - ``Content-Security-Policy`` — from :data:`CSP_POLICY`
    - ``X-Frame-Options: DENY``
    - ``X-Content-Type-Options: nosniff``
    - ``Referrer-Policy: strict-origin-when-cross-origin``
    - ``Strict-Transport-Security: max-age=31536000; includeSubDomains``
    - ``Permissions-Policy: geolocation=(), microphone=(), camera=()``

    Args:
        response: The outgoing Flask :class:`~flask.Response`.

    Returns:
        The same response object with headers added.
    """
    # Splice the per-request nonce (if any) into script-src so the nonce-tagged
    # bootstrap script is permitted. The base policy dict is never mutated.
    nonce = getattr(g, "csp_nonce", None) if g else None
    response.headers.setdefault(
        "Content-Security-Policy", build_csp_header(nonce)
    )
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault(
        "Referrer-Policy", "strict-origin-when-cross-origin"
    )
    response.headers.setdefault(
        "Strict-Transport-Security",
        "max-age=31536000; includeSubDomains",
    )
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
    )
    return response


# ---------------------------------------------------------------------------
# CSP violation handler
# ---------------------------------------------------------------------------


def csp_report_handler(report: dict[str, Any]) -> None:
    """Log a CSP violation report emitted by the browser.

    Browsers ``POST`` a JSON body (wrapped in ``csp-report``) to the
    ``report-uri`` listed in the CSP header.  This function extracts
    the violation details and logs them at WARNING level so that they
    surface in monitoring dashboards.

    Args:
        report: The parsed ``csp-report`` dict from the browser payload.
            Expected keys include ``blocked-uri``, ``violated-directive``,
            ``document-uri``, and ``source-file``.
    """
    blocked = report.get("blocked-uri", "unknown")
    directive = report.get("violated-directive", "unknown")
    doc = report.get("document-uri", "unknown")
    source = report.get("source-file", "")
    line = report.get("line-number", "")
    logger.warning(
        "CSP violation — directive=%s blocked=%s document=%s source=%s:%s",
        directive,
        blocked,
        doc,
        source,
        line,
    )


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

#: Blueprint that provides the ``POST /csp-report`` endpoint.
csp_report_bp = Blueprint("csp_report", __name__)


@csp_report_bp.route("/csp-report", methods=["POST"])
def csp_report_endpoint() -> tuple[Response, int]:
    """Accept browser CSP violation reports.

    The browser ``POST``s either ``application/csp-report`` (Chrome/Firefox
    legacy) or ``application/reports+json`` (Reporting API v1).  Both are
    handled gracefully; malformed payloads are silently ignored so that
    this endpoint never returns a non-2xx status (which would confuse
    browsers into retry loops).

    Returns:
        HTTP 204 No Content — standard response for report endpoints.
    """
    content_type = request.content_type or ""
    payload: dict[str, Any] = {}

    if "application/csp-report" in content_type:
        outer: dict[str, Any] = request.get_json(force=True, silent=True) or {}
        payload = outer.get("csp-report", outer)
    elif "application/reports+json" in content_type:
        # Reporting API v1 sends a list of report objects
        reports: list[Any] = request.get_json(force=True, silent=True) or []
        if reports and isinstance(reports, list):
            body = reports[0].get("body", {})
            payload = body
    else:
        # Fallback — try JSON regardless
        outer = request.get_json(force=True, silent=True) or {}
        payload = outer.get("csp-report", outer)

    if payload:
        csp_report_handler(payload)

    return Response(status=204)
