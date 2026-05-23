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
