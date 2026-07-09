"""Tests for FlintTrade Flask app — indicators/compute endpoint.

Run with:
    python -m pytest packages/core/core/tests/test_app.py -v --import-mode=importlib
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_TEST_API_KEY = "test-api-key-for-unit-tests"


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    """Return a Flask test client for the FlintTrade app."""
    from flinttrade_core.app import create_flask_app

    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        # Wrap the test client so every request includes the auth header
        original_open = c.open

        def authed_open(*args, **kwargs):
            headers = kwargs.pop("headers", {}) or {}
            headers["X-API-Key"] = _TEST_API_KEY
            return original_open(*args, headers=headers, **kwargs)

        c.post = lambda *a, **kw: authed_open(*a, method="POST", **kw)
        c.get = lambda *a, **kw: authed_open(*a, method="GET", **kw)
        c.delete = lambda *a, **kw: authed_open(*a, method="DELETE", **kw)
        yield c


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch for environment variables."""
    import os
    original_env = dict(os.environ)
    yield type("MonkeyPatch", (), {
        "setenv": lambda self, k, v: os.environ.update({k: v}),
        "delenv": lambda self, k, **kw: os.environ.pop(k, None),
    })()
    os.environ.clear()
    os.environ.update(original_env)


def _make_bars(n: int = 100) -> list[dict[str, float | int]]:
    """Generate synthetic OHLCV bars for testing."""
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.normal(0, 1, n))
    bars: list[dict[str, float | int]] = []
    for i, c in enumerate(closes):
        high = c + abs(rng.normal(0, 0.5))
        low = c - abs(rng.normal(0, 0.5))
        bars.append(
            {
                "time": 1_700_000_000 + i * 60,
                "open": float(c - 0.1),
                "high": float(high),
                "low": float(low),
                "close": float(c),
                "volume": float(rng.integers(100_000, 1_000_000)),
            }
        )
    return bars


# ---------------------------------------------------------------------------
# Input validation tests
# ---------------------------------------------------------------------------


class TestInputValidation:
    """Endpoint rejects malformed requests with 400."""

    def test_missing_bars_returns_400(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"indicators": ["ema_20"]},
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["status"] == "error"
        assert "bars" in data["message"].lower()

    def test_empty_bars_returns_400(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": [], "indicators": ["ema_20"]},
        )
        assert resp.status_code == 400

    def test_missing_indicators_returns_400(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": _make_bars(10)},
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data["status"] == "error"
        assert "indicators" in data["message"].lower()

    def test_too_many_bars_returns_400(self, client: Any) -> None:
        bars = _make_bars(1)
        # Extend to 2001 bars
        for i in range(2000):
            b = bars[0].copy()
            b["time"] = int(b["time"]) + i + 1
            bars.append(b)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["ema_20"]},
        )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "2000" in data["message"]

    def test_invalid_bar_field_returns_400(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/indicators/compute",
            json={
                "bars": [{"time": 1, "open": "not_a_number", "high": 1, "low": 1, "close": 1}],
                "indicators": ["ema_20"],
            },
        )
        assert resp.status_code == 400

    def test_missing_close_field_returns_400(self, client: Any) -> None:
        resp = client.post(
            "/api/v1/indicators/compute",
            json={
                "bars": [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0}],
                "indicators": ["ema_20"],
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Successful computation tests
# ---------------------------------------------------------------------------


class TestSuccessfulComputation:
    """Endpoint computes indicators correctly and returns 200."""

    def test_ema_20_returns_correct_length(self, client: Any) -> None:
        bars = _make_bars(60)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["ema_20"]},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        values = data["data"]["ema_20"]
        assert len(values) == 60
        # First 19 should be None (warmup)
        assert all(v is None for v in values[:19])
        # From index 19 onward should be numeric
        assert all(isinstance(v, float) for v in values[19:])

    def test_sma_50_warmup(self, client: Any) -> None:
        bars = _make_bars(80)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["sma_50"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["sma_50"]
        assert len(values) == 80
        assert all(v is None for v in values[:49])
        assert all(isinstance(v, float) for v in values[49:])

    def test_rsi_14_range(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["rsi_14"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["rsi_14"]
        numeric = [v for v in values if v is not None]
        assert all(0 <= v <= 100 for v in numeric)

    def test_macd_returns_three_arrays(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["macd"]},
        )
        assert resp.status_code == 200
        result = json.loads(resp.data)["data"]["macd"]
        assert isinstance(result, dict)
        for key in ("line", "signal", "histogram"):
            assert key in result
            assert len(result[key]) == 100

    def test_bollinger_bands_returns_three_arrays(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["bollinger_bands_20"]},
        )
        assert resp.status_code == 200
        result = json.loads(resp.data)["data"]["bollinger_bands_20"]
        assert isinstance(result, dict)
        for key in ("upper", "middle", "lower"):
            assert key in result
            assert len(result[key]) == 100
        # upper > middle > lower for all numeric values
        for i in range(100):
            u, m, lo = result["upper"][i], result["middle"][i], result["lower"][i]
            if u is not None and m is not None and lo is not None:
                assert u >= m >= lo

    def test_atr_14_non_negative(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["atr_14"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["atr_14"]
        numeric = [v for v in values if v is not None]
        assert all(v >= 0 for v in numeric)

    def test_williams_r_range(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["williams_r_14"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["williams_r_14"]
        numeric = [v for v in values if v is not None]
        assert all(-100 <= v <= 0 for v in numeric)

    def test_cci_20_length(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["cci_20"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["cci_20"]
        assert len(values) == 100

    def test_keltner_channels_returns_three_arrays(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["keltner_channels_20"]},
        )
        assert resp.status_code == 200
        result = json.loads(resp.data)["data"]["keltner_channels_20"]
        assert isinstance(result, dict)
        for key in ("upper", "middle", "lower"):
            assert key in result
            assert len(result[key]) == 100

    def test_obv_returns_array(self, client: Any) -> None:
        bars = _make_bars(60)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["obv"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["obv"]
        assert len(values) == 60
        # OBV starts at 0, no NaN warmup
        assert values[0] == 0.0

    def test_vwma_20_warmup(self, client: Any) -> None:
        bars = _make_bars(60)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["vwma_20"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["vwma_20"]
        assert len(values) == 60
        assert all(v is None for v in values[:19])

    def test_vwap_length(self, client: Any) -> None:
        bars = _make_bars(60)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["vwap"]},
        )
        assert resp.status_code == 200
        values = json.loads(resp.data)["data"]["vwap"]
        assert len(values) == 60

    def test_multiple_indicators_in_one_request(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={
                "bars": bars,
                "indicators": [
                    "ema_20", "sma_50", "rsi_14", "macd",
                    "bollinger_bands_20", "atr_14",
                    "williams_r_14", "cci_20",
                    "keltner_channels_20", "obv", "vwma_20",
                ],
            },
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert len(data["data"]) == 11


# ---------------------------------------------------------------------------
# Graceful error handling per-indicator
# ---------------------------------------------------------------------------


class TestPerIndicatorErrors:
    """Unknown indicators return per-entry error, not a 500."""

    def test_unknown_indicator_returns_error_key(self, client: Any) -> None:
        bars = _make_bars(50)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={
                "bars": bars,
                "indicators": ["ema_20", "totally_unknown_thing"],
            },
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        # Known indicator should succeed
        assert isinstance(data["data"]["ema_20"], list)
        # Unknown indicator should have error key
        unknown = data["data"]["totally_unknown_thing"]
        assert isinstance(unknown, dict)
        assert "error" in unknown

    def test_supertrend_returns_up_down(self, client: Any) -> None:
        bars = _make_bars(100)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["supertrend"]},
        )
        assert resp.status_code == 200
        result = json.loads(resp.data)["data"]["supertrend"]
        assert isinstance(result, dict)
        assert "up" in result and "down" in result
        assert len(result["up"]) == 100


# ---------------------------------------------------------------------------
# NaN serialisation
# ---------------------------------------------------------------------------


class TestNaNSerialisation:
    """NaN values in numpy output are converted to JSON null, not 'NaN'."""

    def test_ema_warmup_is_null_not_nan(self, client: Any) -> None:
        bars = _make_bars(30)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["ema_20"]},
        )
        raw_text = resp.data.decode()
        assert "NaN" not in raw_text
        values = json.loads(raw_text)["data"]["ema_20"]
        assert values[0] is None

    def test_rsi_warmup_null(self, client: Any) -> None:
        bars = _make_bars(30)
        resp = client.post(
            "/api/v1/indicators/compute",
            json={"bars": bars, "indicators": ["rsi_14"]},
        )
        values = json.loads(resp.data)["data"]["rsi_14"]
        assert values[0] is None


class TestAdvancedExecutorsGated:
    """The wired basket/split executors dispatch ONLY through the gated chain."""

    def test_basket_and_split_executors_are_gated_and_wired(self, client: Any) -> None:
        app = client.application
        basket = app.config.get("BASKET_EXECUTOR")
        split = app.config.get("SPLIT_EXECUTOR")

        # Both wired — the engine order_bp routes would 503 otherwise.
        assert basket is not None
        assert split is not None

        # Each holds the gated place_leg dispatcher (build_gated_leg_dispatchers)
        # and NO raw router/client — a raw write is structurally impossible.
        assert callable(getattr(basket, "_place_leg", None))
        assert callable(getattr(split, "_place_leg", None))
        assert not hasattr(basket, "_router")
        assert not hasattr(split, "_router")
