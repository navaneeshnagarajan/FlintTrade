"""Tests for packages/core/src/indicators_routes.py (Flask Blueprint).

Mocks the indicator functions from packages.indicators.src so tests
run without TA-Lib or Numba installed.

Run with:
    python -m pytest packages/core/tests/test_indicators_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_bars(n: int = 30) -> list[dict]:
    """Generate *n* synthetic OHLCV bars."""
    bars = []
    base = 100.0
    for i in range(n):
        o = base + i * 0.5
        c = o + 0.3
        bars.append({
            "time": 1_700_000_000 + i * 60,
            "open": o,
            "high": o + 1.0,
            "low": o - 0.5,
            "close": c,
            "volume": 1000 + i * 10,
        })
    return bars


# ---------------------------------------------------------------------------
# Fixtures — install a fake packages.indicators.src module tree
# ---------------------------------------------------------------------------

_FAKE_MODULES: dict[str, types.ModuleType] = {}


def _build_fake_indicators_modules() -> dict[str, types.ModuleType]:
    """Build a tree of fake indicator modules to inject into sys.modules.

    This prevents the real packages.indicators.src from being loaded,
    which would require TA-Lib / Numba.  It also provides the
    ``streaming`` sub-module that packages.ai.src.signal_pipeline imports.
    """
    # Main module
    mod = types.ModuleType("packages.indicators.src")
    mod.__path__ = []  # Make it look like a package

    # Single-array indicators
    for name in ("ema", "sma", "dema", "wma", "hull", "rsi",
                 "atr", "cci", "williams_r", "obv", "parabolic_sar"):
        setattr(mod, name, MagicMock(return_value=np.full(30, 105.0)))

    mod.vwap = MagicMock(return_value=np.full(30, 105.0))
    mod.vwma = MagicMock(return_value=np.full(30, 105.0))

    mod.macd = MagicMock(return_value=(
        np.full(30, 1.0), np.full(30, 0.5), np.full(30, 0.5),
    ))
    mod.bollinger_bands = MagicMock(return_value=(
        np.full(30, 110.0), np.full(30, 105.0), np.full(30, 100.0),
    ))
    mod.keltner_channels = MagicMock(return_value=(
        np.full(30, 110.0), np.full(30, 105.0), np.full(30, 100.0),
    ))
    mod.supertrend = MagicMock(return_value=(
        np.full(30, 105.0), np.full(30, True),
    ))

    # Streaming sub-module (imported by packages.ai.src.signal_pipeline)
    streaming = types.ModuleType("packages.indicators.src.streaming")
    streaming.StreamingEMA = MagicMock
    streaming.StreamingRSI = MagicMock
    mod.streaming = streaming

    # Pine converter sub-module (imported by pine/compile endpoint)
    pine = types.ModuleType("packages.indicators.src.pine_converter")
    pine.PineConverter = MagicMock
    mod.pine_converter = pine

    return {
        "packages.indicators.src": mod,
        "packages.indicators.src.streaming": streaming,
        "packages.indicators.src.pine_converter": pine,
    }


@pytest.fixture(autouse=True)
def _fake_indicators_module():
    """Inject fake indicator modules into sys.modules for every test."""
    fakes = _build_fake_indicators_modules()
    originals = {key: sys.modules.get(key) for key in fakes}
    sys.modules.update(fakes)
    yield fakes["packages.indicators.src"]
    for key, orig in originals.items():
        if orig is not None:
            sys.modules[key] = orig
        else:
            sys.modules.pop(key, None)


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    # Import the blueprint directly via importlib to avoid
    # triggering packages.core.src.__init__ side effects.
    mod = importlib.import_module("packages.core.src.indicators_routes")
    flask_app.register_blueprint(mod.indicators_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests — /indicators/compute
# ---------------------------------------------------------------------------


class TestIndicatorsCompute:
    """Tests for POST /api/v1/indicators/compute."""

    def test_valid_ema_indicator(self, client):
        """Compute a single EMA indicator returns a list of values."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["ema_20"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "ema_20" in data["data"]
        assert isinstance(data["data"]["ema_20"], list)
        assert len(data["data"]["ema_20"]) == 30

    def test_valid_macd_indicator(self, client):
        """MACD returns a dict with line, signal, histogram."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["macd"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        macd_data = data["data"]["macd"]
        assert "line" in macd_data
        assert "signal" in macd_data
        assert "histogram" in macd_data

    def test_missing_bars(self, client):
        """Empty bars list returns 400."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": [],
            "indicators": ["ema_20"],
        })
        assert resp.status_code == 400
        assert "non-empty" in resp.get_json()["message"]

    def test_missing_indicators_list(self, client):
        """Empty indicators list returns 400."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": [],
        })
        assert resp.status_code == 400
        assert "indicators" in resp.get_json()["message"]

    def test_invalid_bar_data(self, client):
        """Bars without required OHLC fields return 400."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": [{"time": 1, "close": 100}],  # missing open/high/low
            "indicators": ["ema_20"],
        })
        assert resp.status_code == 400

    def test_unknown_indicator_returns_error_key(self, client):
        """An unrecognised indicator name returns an error entry, not 400."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["nonexistent_indicator"],
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "error" in data["data"]["nonexistent_indicator"]
