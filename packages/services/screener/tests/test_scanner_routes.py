"""Tests for packages/services/screener/src/scanner_routes.py (Flask Blueprint).

Covers:
  POST /ft-api/v1/scanner/run     — prebuilt key, inline config, invalid key, error
  GET  /ft-api/v1/scanner/prebuilt — lists all prebuilt scans
  POST /ft-api/v1/scanner/custom  — validates custom ScanConfig, empty body

The MarketScanner.scan method is mocked to avoid TA-Lib I/O and keep tests fast.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scan_result(symbol: str = "NIFTY") -> MagicMock:
    """Build a mock ScanResult.

    Args:
        symbol: Symbol name for the result.

    Returns:
        MagicMock with the required ScanResult interface.
    """
    r = MagicMock()
    r.symbol = symbol
    r.exchange = "NSE"
    r.ltp = 22000.0
    r.change_pct = 1.25
    r.matched_conditions = ["rsi_oversold"]
    r.scan_time = datetime.now(timezone.utc)
    r.score = 0.85
    return r


_VALID_CONFIG = {
    "name": "test_scan",
    "conditions": [
        {
            "indicator": "rsi",
            "operator": "below",
            "value": 30,
        }
    ],
    "universe": "nifty50",
    "timeframe": "1d",
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Flask test app with scanner_bp registered.

    Yields:
        Flask application instance.
    """
    from flinttrade_screener.scanner_routes import scanner_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(scanner_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client.

    Args:
        app: Flask application fixture.

    Returns:
        Test client instance.
    """
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/scanner/run
# ---------------------------------------------------------------------------


class TestScannerRun:
    def test_run_prebuilt_success(self, client) -> None:
        """A valid prebuilt key triggers a scan and returns results.

        Args:
            client: Flask test client.
        """
        mock_results = [_make_scan_result("RELIANCE")]
        with patch(
            "flinttrade_screener.scanner_routes._scanner.scan",
            return_value=mock_results,
        ):
            # Use the first available prebuilt key
            from flinttrade_screener.scanner_routes import PREBUILT_SCANS
            first_key = next(iter(PREBUILT_SCANS))
            resp = client.post(
                "/v1/scanner/run",
                json={"prebuilt": first_key},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["matched_count"] == 1
        assert data["results"][0]["symbol"] == "RELIANCE"
        assert "is_sample_data" in data

    def test_unknown_prebuilt_key_returns_400(self, client) -> None:
        """An unknown prebuilt key returns HTTP 400 with a helpful message.

        Args:
            client: Flask test client.
        """
        resp = client.post("/v1/scanner/run", json={"prebuilt": "no_such_scan"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "no_such_scan" in data["message"]

    def test_run_inline_config_success(self, client) -> None:
        """An inline ScanConfig dict triggers a scan correctly.

        Args:
            client: Flask test client.
        """
        mock_results: list = []
        with patch(
            "flinttrade_screener.scanner_routes._scanner.scan",
            return_value=mock_results,
        ):
            resp = client.post(
                "/v1/scanner/run",
                json={"config": _VALID_CONFIG},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["matched_count"] == 0

    def test_invalid_inline_config_returns_400(self, client) -> None:
        """A malformed inline config (missing required fields) returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/scanner/run",
            json={"config": {"name": "broken", "conditions": "not-a-list"}},
        )
        assert resp.status_code == 400

    def test_missing_prebuilt_and_config_returns_400(self, client) -> None:
        """Body without prebuilt or config returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/v1/scanner/run", json={})
        assert resp.status_code == 400
        assert "'prebuilt'" in resp.get_json()["message"] or "config" in resp.get_json()["message"]

    def test_scanner_exception_returns_500(self, client) -> None:
        """Exception inside scanner.scan surfaces as HTTP 500.

        Args:
            client: Flask test client.
        """
        with patch(
            "flinttrade_screener.scanner_routes._scanner.scan",
            side_effect=RuntimeError("TA-Lib error"),
        ):
            from flinttrade_screener.scanner_routes import PREBUILT_SCANS
            first_key = next(iter(PREBUILT_SCANS))
            resp = client.post(
                "/v1/scanner/run",
                json={"prebuilt": first_key},
            )

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /ft-api/v1/scanner/run — live registry path
# ---------------------------------------------------------------------------


def _rising_dict_bars(n: int = 60) -> list[dict]:
    """Steadily rising daily bars → RSI ≈ 100, so 'rsi above 50' always matches."""
    bars = []
    for i in range(n):
        close = 100.0 + i
        bars.append({
            "open": close - 1.0,
            "high": close + 1.0,
            "low": close - 2.0,
            "close": close,
            "volume": 1_000 + i,
            "timestamp": f"2026-01-{(i % 28) + 1:02d}",  # extra key must be tolerated
        })
    return bars


def _rising_array_bars(n: int = 60) -> list[list]:
    """The same rising series in [ts, o, h, l, c, v] positional form."""
    return [
        [1_700_000_000 + i * 86_400, 99.0 + i, 101.0 + i, 98.0 + i, 100.0 + i, 1_000 + i]
        for i in range(n)
    ]


class _FakeRegistry:
    """Connected BrokerRegistry double that records get_history calls."""

    def __init__(self, candles, account_id: str | None = "acc-primary") -> None:
        self._candles = candles
        self._account_id = account_id
        self.calls: list[tuple[str, dict]] = []

    def is_connected(self) -> bool:
        return True

    def get_primary_account_id(self) -> str | None:
        return self._account_id

    def get_history(self, account_id: str, params: dict) -> dict:
        self.calls.append((account_id, params))
        return {"candles": self._candles}


_LIVE_CONFIG = {
    "name": "live_path_scan",
    "conditions": [{"indicator": "rsi", "operator": "above", "value": 50}],
    "universe": "custom",
    "custom_symbols": ["RELIANCE", "TCS"],
    "timeframe": "1d",
}


class TestScannerRunLiveRegistry:
    """The live (broker-connected) path through the REAL scanner.

    Regression for the registry-call signature bug: _registry_data_fetcher used
    to call registry.get_history(symbol=..., days=...) but the registry's
    contract is get_history(account_id, params) — the TypeError was swallowed
    per symbol, so a connected scanner silently returned zero candles for every
    symbol and could never match anything.
    """

    def test_live_scan_matches_with_dict_candles(self, app, client) -> None:
        registry = _FakeRegistry(_rising_dict_bars())
        app.config["REGISTRY"] = registry

        resp = client.post("/v1/scanner/run", json={"config": _LIVE_CONFIG})

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["is_sample_data"] is False
        # rising closes → RSI ≈ 100 → both symbols match with non-empty results
        assert data["matched_count"] == 2
        assert {r["symbol"] for r in data["results"]} == {"RELIANCE", "TCS"}
        assert all(r["ltp"] > 0 for r in data["results"])

    def test_live_scan_calls_registry_with_correct_signature(self, app, client) -> None:
        registry = _FakeRegistry(_rising_dict_bars())
        app.config["REGISTRY"] = registry

        client.post("/v1/scanner/run", json={"config": _LIVE_CONFIG})

        # one positional (account_id, params) call per scanned symbol
        assert len(registry.calls) == 2
        for account_id, params in registry.calls:
            assert account_id == "acc-primary"
            assert set(params) == {"symbol", "exchange", "interval", "start", "end"}
            assert params["interval"] == "1d"
            # ISO dates spanning ~a year, oldest first
            assert params["start"] < params["end"]
        assert {params["symbol"] for _, params in registry.calls} == {"RELIANCE", "TCS"}

    def test_live_scan_normalises_array_candles(self, app, client) -> None:
        registry = _FakeRegistry(_rising_array_bars())
        app.config["REGISTRY"] = registry

        resp = client.post("/v1/scanner/run", json={"config": _LIVE_CONFIG})

        data = resp.get_json()
        assert data["is_sample_data"] is False
        assert data["matched_count"] == 2

    def test_no_usable_account_falls_back_to_sample(self, app, client) -> None:
        registry = _FakeRegistry(_rising_dict_bars(), account_id=None)
        app.config["REGISTRY"] = registry

        resp = client.post("/v1/scanner/run", json={"config": _LIVE_CONFIG})

        assert resp.status_code == 200
        data = resp.get_json()
        # connected but no account id → honest sample fallback, not a broken scan
        assert data["is_sample_data"] is True
        assert registry.calls == []

    def test_per_symbol_history_errors_skip_symbol(self, app, client) -> None:
        class _ErroringRegistry(_FakeRegistry):
            def get_history(self, account_id: str, params: dict) -> dict:
                super().get_history(account_id, params)
                raise RuntimeError("broker hiccup")

        registry = _ErroringRegistry(_rising_dict_bars())
        app.config["REGISTRY"] = registry

        resp = client.post("/v1/scanner/run", json={"config": _LIVE_CONFIG})

        assert resp.status_code == 200
        data = resp.get_json()
        # the fetcher was built (live mode) but every symbol's fetch failed →
        # zero matches, never a 500
        assert data["is_sample_data"] is False
        assert data["matched_count"] == 0


# ---------------------------------------------------------------------------
# GET /ft-api/v1/scanner/prebuilt
# ---------------------------------------------------------------------------


class TestScannerPrebuilt:
    def test_returns_all_prebuilt_scans(self, client) -> None:
        """Prebuilt endpoint returns all configured scans with correct shape.

        Args:
            client: Flask test client.
        """
        resp = client.get("/v1/scanner/prebuilt")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["count"] > 0
        scan = data["data"]["scans"][0]
        assert "key" in scan
        assert "name" in scan
        assert "conditions" in scan

    def test_prebuilt_count_matches_data(self, client) -> None:
        """The count field in the response matches the length of the scans list.

        Args:
            client: Flask test client.
        """
        resp = client.get("/v1/scanner/prebuilt")
        data = resp.get_json()
        assert data["count"] == len(data["data"]["scans"])


# ---------------------------------------------------------------------------
# POST /ft-api/v1/scanner/custom
# ---------------------------------------------------------------------------


class TestScannerCustom:
    def test_valid_config_echoed_back(self, client) -> None:
        """A valid ScanConfig is validated and echoed with metadata.

        Args:
            client: Flask test client.
        """
        resp = client.post("/v1/scanner/custom", json=_VALID_CONFIG)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "test_scan"
        assert data["data"]["symbol_count"] > 0
        assert len(data["data"]["conditions"]) == 1

    def test_empty_body_returns_400(self, client) -> None:
        """Empty body returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/scanner/custom",
            data="",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_invalid_config_returns_400(self, client) -> None:
        """Malformed ScanConfig (conditions as string) returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/v1/scanner/custom",
            json={"name": "bad", "conditions": "not-a-list"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["status"] == "error"
