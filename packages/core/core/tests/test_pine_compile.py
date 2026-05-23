"""Tests for POST /api/v1/indicators/pine/compile — Pine Script compilation endpoint.

Run with:
    python -m pytest packages/core/core/tests/test_pine_compile.py -v --import-mode=importlib
"""
from __future__ import annotations

import json

import pytest


_TEST_API_KEY = "test-pine-compile-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with indicators blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client."""
    with flask_app.test_client() as c:
        yield c


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


class TestPineCompileBasic:
    """Basic Pine Script compilation endpoint tests."""

    def test_compile_simple_ema(self, client):
        """Compiling a simple EMA script returns Python code with ema import."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": "x = ta.ema(close, 20)"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "ema(" in data["data"]["python_code"]
        assert "ema" in data["data"]["imports"]

    def test_compile_macd_script(self, client):
        """Compiling a MACD script returns Python code with macd import."""
        pine = "[ml, sl, hist] = ta.macd(close, 12, 26, 9)"
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": pine}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "macd(" in data["data"]["python_code"]
        assert "macd" in data["data"]["imports"]

    def test_compile_returns_supported_functions(self, client):
        """Compile response includes the supported_functions list."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": "x = ta.rsi(close, 14)"}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        funcs = data["data"]["supported_functions"]
        assert isinstance(funcs, list)
        assert len(funcs) > 10
        assert "ta.ema" in funcs
        assert "ta.rsi" in funcs


class TestPineCompileValidation:
    """Input validation tests."""

    def test_empty_code_returns_400(self, client):
        """Empty code string returns 400 error."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": ""}),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "non-empty" in data["message"]

    def test_missing_code_returns_400(self, client):
        """Missing code field returns 400 error."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({}),
        )
        assert resp.status_code == 400

    def test_non_string_code_returns_400(self, client):
        """Non-string code field returns 400 error."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": 12345}),
        )
        assert resp.status_code == 400

    def test_oversized_code_returns_400(self, client):
        """Code exceeding 50,000 chars returns 400 error."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": "x = ta.ema(close, 20)\n" * 5000}),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "too large" in data["message"].lower() or "50,000" in data["message"]


class TestPineCompileMultiLine:
    """Multi-line script compilation tests."""

    PINE_SCRIPT = """\
//@version=5
indicator("EMA Cross", overlay=true)
fast_len = input.int(9, "Fast")
slow_len = input.int(21, "Slow")
fast_ema = ta.ema(close, fast_len)
slow_ema = ta.ema(close, slow_len)
bull = ta.crossover(fast_ema, slow_ema)
plot(fast_ema, color=color.green)
alertcondition(bull, title="Bull Cross")
"""

    def test_multiline_compiles_successfully(self, client):
        """A realistic multi-line Pine Script compiles without errors."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": self.PINE_SCRIPT}),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        result = data["data"]
        assert "ema(" in result["python_code"]
        assert "crossover(" in result["python_code"]
        assert "ema" in result["imports"]
        assert "crossover" in result["imports"]

    def test_multiline_reports_warnings(self, client):
        """Multi-line script with inputs generates conversion warnings."""
        resp = client.post(
            "/api/v1/indicators/pine/compile",
            headers=_headers(),
            data=json.dumps({"code": self.PINE_SCRIPT}),
        )
        data = resp.get_json()
        # input.int conversions generate warnings
        assert len(data["data"]["warnings"]) > 0
