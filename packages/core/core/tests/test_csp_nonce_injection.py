"""DS-CSP-09: the gateway weaves a per-request nonce into the served index.html.

Covers the two halves of the fix:
  * inject_csp_nonce() adds nonce="..." to every <script> tag lacking one, and
  * build_csp_header() splices the matching 'nonce-...' into script-src while never
    permitting 'unsafe-inline'.

The end-to-end SPA-serving path needs a built dist/index.html (a CI/build artefact that
is absent in a clean checkout), so the integration assertion is exercised against a
temporary dist via a tiny Flask app rather than the full create_flask_app().
"""

from __future__ import annotations

import re

from flinttrade_core.csp import (
    apply_security_headers,
    build_csp_header,
    generate_nonce,
    inject_csp_nonce,
)


class TestInjectCspNonce:
    def test_adds_nonce_to_bare_script_tag(self):
        out = inject_csp_nonce("<script>x()</script>", "ABC123")
        assert out == '<script nonce="ABC123">x()</script>'

    def test_adds_nonce_to_script_with_attributes(self):
        html = '<script type="module" src="/assets/index.js"></script>'
        out = inject_csp_nonce(html, "N1")
        assert out.startswith('<script nonce="N1" type="module"')

    def test_does_not_double_nonce(self):
        html = '<script nonce="existing" src="/a.js"></script>'
        assert inject_csp_nonce(html, "N1") == html

    def test_handles_multiple_scripts(self):
        html = "<script src='/a.js'></script><div></div><script>b()</script>"
        out = inject_csp_nonce(html, "Z")
        assert out.count('nonce="Z"') == 2

    def test_empty_nonce_is_noop(self):
        html = "<script>x()</script>"
        assert inject_csp_nonce(html, "") == html


class TestBuildCspHeader:
    def test_no_nonce_has_no_unsafe_inline_in_script_src(self):
        csp = build_csp_header(None)
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        assert "'unsafe-inline'" not in script_src

    def test_nonce_spliced_into_script_src(self):
        csp = build_csp_header("MYNONCE")
        assert "'nonce-MYNONCE'" in csp
        script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src"))
        assert "'unsafe-inline'" not in script_src

    def test_base_policy_not_mutated_across_calls(self):
        first = build_csp_header("A")
        second = build_csp_header("B")
        assert "'nonce-A'" not in second
        assert "'nonce-B'" not in first


def test_served_html_and_header_share_one_nonce(tmp_path):
    """A served document's <script nonce> must match the CSP header's 'nonce-...'."""
    from flask import Flask, Response, g

    app = Flask(__name__)
    dist_index = "<!doctype html><script type=module src=/assets/app.js></script>"

    @app.before_request
    def _nonce():
        g.csp_nonce = generate_nonce()

    @app.after_request
    def _hdr(resp):
        resp.headers.setdefault("Content-Security-Policy", build_csp_header(g.csp_nonce))
        return apply_security_headers(resp)

    @app.route("/")
    def index():
        return Response(inject_csp_nonce(dist_index, g.csp_nonce), mimetype="text/html")

    with app.test_client() as c:
        resp = c.get("/")
        body = resp.get_data(as_text=True)
        csp = resp.headers["Content-Security-Policy"]
        html_nonce = re.search(r'<script nonce="([^"]+)"', body)
        hdr_nonce = re.search(r"'nonce-([^']+)'", csp)
        assert html_nonce and hdr_nonce
        assert html_nonce.group(1) == hdr_nonce.group(1)
        assert "'unsafe-inline'" not in csp.split("script-src", 1)[1].split(";", 1)[0]
