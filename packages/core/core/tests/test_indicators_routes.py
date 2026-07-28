"""Tests for packages/core/core/src/indicators_routes.py (Flask Blueprint).

Mocks the indicator functions from flinttrade_indicators so tests
run without TA-Lib or Numba installed.

Run with:
    python -m pytest packages/core/core/tests/test_indicators_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import numpy as np
import pytest
from flask import Flask

pytestmark = pytest.mark.unit


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
# Fixtures — install a fake flinttrade_indicators module tree
# ---------------------------------------------------------------------------

_FAKE_MODULES: dict[str, types.ModuleType] = {}


def _build_fake_indicators_modules() -> dict[str, types.ModuleType]:
    """Build a tree of fake indicator modules to inject into sys.modules.

    This prevents the real flinttrade_indicators from being loaded,
    which would require TA-Lib / Numba.  It also provides the
    ``streaming`` sub-module that flinttrade_ai.signal_pipeline imports.
    """
    # Main module
    mod = types.ModuleType("flinttrade_indicators")
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

    def _fake_periodic(*args) -> np.ndarray:
        """Single-line fake: NaN warm-up of ``period`` bars, then the period value.

        The route passes the parsed period as the last positional argument,
        so the output depends on the period — letting tests assert that a
        ``_20`` suffix actually reached the indicator function.
        """
        n = len(args[0])
        period = int(args[-1])
        out = np.full(n, float(period))
        out[: min(period, n)] = np.nan
        return out

    # New single-line indicators with a period argument
    for name in ("alma", "kama", "tema", "t3", "trima", "mcginley_dynamic",
                 "mfi", "cmf", "roc", "mom", "trix", "chop",
                 "historical_volatility"):
        setattr(mod, name, MagicMock(side_effect=_fake_periodic))

    # New single-line indicators without a period argument
    for name in ("ad", "pvt", "awesome_oscillator", "coppock_curve"):
        setattr(mod, name, MagicMock(return_value=np.full(30, 105.0)))

    # New three-line band indicators (upper, middle, lower)
    for name in ("donchian_channels", "moving_average_envelopes",
                 "starc_bands"):
        setattr(mod, name, MagicMock(return_value=(
            np.full(30, 110.0), np.full(30, 105.0), np.full(30, 100.0),
        )))

    # New two-line indicators (pairs of arrays)
    for name in ("chandelier_exit", "stoch_rsi", "vortex", "kst",
                 "fisher_transform"):
        setattr(mod, name, MagicMock(return_value=(
            np.full(30, 1.0), np.full(30, 0.5),
        )))

    mod.squeeze_momentum = MagicMock(return_value=(
        np.full(30, 1.0), np.full(30, True),
    ))

    # Streaming sub-module (imported by flinttrade_ai.signal_pipeline)
    streaming = types.ModuleType("flinttrade_indicators.streaming")
    streaming.StreamingEMA = MagicMock
    streaming.StreamingRSI = MagicMock
    mod.streaming = streaming

    # Pine converter sub-module (imported by pine/compile endpoint)
    pine = types.ModuleType("flinttrade_indicators.pine_converter")
    pine.PineConverter = MagicMock
    mod.pine_converter = pine

    return {
        "flinttrade_indicators": mod,
        "flinttrade_indicators.streaming": streaming,
        "flinttrade_indicators.pine_converter": pine,
    }


@pytest.fixture(autouse=True)
def _fake_indicators_module():
    """Inject fake indicator modules into sys.modules for every test."""
    fakes = _build_fake_indicators_modules()
    originals = {key: sys.modules.get(key) for key in fakes}
    sys.modules.update(fakes)
    yield fakes["flinttrade_indicators"]
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
    # triggering flinttrade_core.__init__ side effects.
    mod = importlib.import_module("flinttrade_core.indicators_routes")
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

    def test_new_single_line_indicators(self, client):
        """New single-line indicators return bar-count arrays with None warm-up."""
        names = [
            "alma_20", "kama_10", "tema_20", "t3_5", "trima_20",
            "mcginley_dynamic_14", "mfi_14", "cmf_20", "roc_12", "mom_10",
            "trix_18", "chop_14", "historical_volatility_10",
        ]
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": names,
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        for name in names:
            values = data[name]
            assert isinstance(values, list), name
            assert len(values) == 30, name
            assert values[0] is None, name       # leading warm-up bar
            assert values[-1] is not None, name  # computed once warmed up

    def test_new_periodless_indicators(self, client):
        """Cumulative/fixed-window indicators accept their exact names only."""
        names = ["ad", "pvt", "awesome_oscillator", "coppock_curve"]
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": names,
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        for name in names:
            assert isinstance(data[name], list), name
            assert len(data[name]) == 30, name

    def test_donchian_channels_multiline(self, client):
        """Donchian Channels return upper/middle/lower sub-arrays."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["donchian_channels_20"],
        })
        assert resp.status_code == 200
        channels = resp.get_json()["data"]["donchian_channels_20"]
        assert set(channels) == {"upper", "middle", "lower"}
        for line in channels.values():
            assert len(line) == 30

    def test_stoch_rsi_multiline(self, client):
        """Stochastic RSI returns %K and %D sub-arrays."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["stoch_rsi_14"],
        })
        assert resp.status_code == 200
        stoch = resp.get_json()["data"]["stoch_rsi_14"]
        assert set(stoch) == {"k", "d"}
        assert len(stoch["k"]) == 30
        assert len(stoch["d"]) == 30

    @pytest.mark.parametrize(("name", "keys"), [
        ("moving_average_envelopes_20", {"upper", "middle", "lower"}),
        ("starc_bands", {"upper", "middle", "lower"}),
        ("chandelier_exit_22", {"long", "short"}),
        ("vortex_14", {"plus", "minus"}),
        ("kst", {"line", "signal"}),
        ("fisher_transform_9", {"fisher", "signal"}),
    ])
    def test_multiline_indicator_keys(self, client, name, keys):
        """Each multi-line indicator returns its documented sub-array keys."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": [name],
        })
        assert resp.status_code == 200
        payload = resp.get_json()["data"][name]
        assert set(payload) == keys
        for line in payload.values():
            assert len(line) == 30

    def test_squeeze_momentum_multiline(self, client):
        """Squeeze Momentum returns a momentum array plus boolean squeeze flags."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["squeeze_momentum"],
        })
        assert resp.status_code == 200
        squeeze = resp.get_json()["data"]["squeeze_momentum"]
        assert set(squeeze) == {"momentum", "squeeze_on"}
        assert len(squeeze["momentum"]) == 30
        assert len(squeeze["squeeze_on"]) == 30
        assert all(isinstance(flag, bool) for flag in squeeze["squeeze_on"])

    def test_alma_period_suffix_changes_output(self, client):
        """The parsed period suffix is forwarded to the indicator function."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["alma_10", "alma_50"],
        })
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        # The fake emits NaN for the first ``period`` bars, so a period of
        # 10 warms up mid-series while 50 exceeds the 30-bar window.
        assert data["alma_10"] != data["alma_50"]
        assert data["alma_10"][10] == 10.0
        assert all(v is None for v in data["alma_50"])

    def test_fixed_name_with_suffix_is_unknown(self, client):
        """Fixed-parameter names are exact-match; a suffixed form is unknown."""
        resp = client.post("/api/v1/indicators/compute", json={
            "bars": _sample_bars(),
            "indicators": ["kst_9"],
        })
        assert resp.status_code == 200
        assert "error" in resp.get_json()["data"]["kst_9"]
