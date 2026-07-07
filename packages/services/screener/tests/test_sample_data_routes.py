"""Tests for ``flinttrade_screener.sample_data_routes``.

These routes are the honest placeholders that close the 2026-05-19
orphan-API audit finding: eight frontend endpoints whose real backends
weren't built were generating 404s in production. Each stub returns
``is_sample_data: true`` with realistic data so the corresponding
widgets render their "Demo" badge instead of erroring out.

The tests below confirm:
1. Every route returns HTTP 200.
2. Every route returns ``is_sample_data: true`` (so the frontend
   contract is preserved when a real implementation lands).
3. Response shape matches the frontend TypeScript interfaces.
4. Symbol/sector/exchange query parameters echo through correctly.

A future PR replacing each stub MUST keep these assertions passing.
"""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_screener.sample_data_routes import sample_data_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Return a Flask test client with only the sample-data blueprint registered."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(sample_data_bp)
    with flask_app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# /api/v1/etf/screener
# ---------------------------------------------------------------------------


def test_etf_screener_returns_sample_data(client):
    resp = client.get("/api/v1/etf/screener")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert isinstance(data["etfs"], list)
    assert len(data["etfs"]) >= 1
    # First entry has the expected EtfScreenerRow shape.
    row = data["etfs"][0]
    for field in ("symbol", "name", "category", "exchange", "price", "change_1d",
                  "expense_ratio", "sparkline", "annual_returns"):
        assert field in row, f"ETF row missing field {field}"
    assert isinstance(row["sparkline"], list)


# ---------------------------------------------------------------------------
# /api/v1/sectors/rotation
# ---------------------------------------------------------------------------


def test_sectors_rotation_returns_sample_data(client):
    resp = client.get("/api/v1/sectors/rotation")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert isinstance(data["sectors"], list)
    assert len(data["sectors"]) >= 1
    quadrants = {row["quadrant"] for row in data["sectors"]}
    # Should cover at least one quadrant of the RRG diagram.
    assert quadrants <= {"leading", "weakening", "lagging", "improving"}
    assert quadrants  # non-empty


# ---------------------------------------------------------------------------
# /api/v1/analytics/risk-return
# ---------------------------------------------------------------------------


def test_risk_return_returns_sample_data(client):
    resp = client.get("/api/v1/analytics/risk-return")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert isinstance(data["points"], list)
    assert "avg_return" in data
    assert "avg_volatility" in data
    assert "best_sharpe_symbol" in data
    # best_sharpe_symbol must actually be in the points list.
    symbols = {p["symbol"] for p in data["points"]}
    assert data["best_sharpe_symbol"] in symbols


# ---------------------------------------------------------------------------
# /api/v1/crypto/funding_rates
# ---------------------------------------------------------------------------


def test_crypto_funding_rates_returns_sample_data(client):
    resp = client.get("/api/v1/crypto/funding_rates")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert isinstance(data["rates"], list)
    assert len(data["rates"]) >= 1
    rate = data["rates"][0]
    for field in ("symbol", "rate", "predicted_rate", "next_funding_ms",
                  "history", "open_interest_usd"):
        assert field in rate, f"funding-rate row missing field {field}"


def test_crypto_funding_rates_does_not_mint_fresh_timestamp(client):
    """Hardcoded funding rates must NOT carry a request-time ``updated_at``.

    Stamping ``now()`` on fabricated prices made them look seconds-fresh on
    every poll, actively defeating the user's staleness instincts. Sample
    payloads omit the field entirely; the widget badges on ``is_sample_data``.
    """
    resp = client.get("/api/v1/crypto/funding_rates")
    data = resp.get_json()
    assert "updated_at" not in data
    assert data["is_sample_data"] is True


# ---------------------------------------------------------------------------
# /api/v1/global/indices
# ---------------------------------------------------------------------------


def test_global_indices_returns_sample_data(client):
    # Frontend calls `market/global_indices` (see
    # packages/apps/terminal/src/services/ftApi.analysis.ts:245), so the
    # backend route MUST live at /api/v1/market/global_indices. A
    # mismatched route here would silently 404 in production.
    resp = client.get("/api/v1/market/global_indices")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert isinstance(data["indices"], list)
    assert len(data["indices"]) >= 4  # India + US + Europe + Asia coverage
    regions = {idx["region"] for idx in data["indices"]}
    assert regions <= {"India", "US", "Europe", "Asia"}
    assert "India" in regions  # NIFTY/SENSEX must be present


def test_global_indices_does_not_mint_fresh_timestamp(client):
    """Hardcoded index levels must NOT carry a request-time ``updated_at``.

    Two requests used to return different seconds-fresh timestamps on
    identical fabricated prices — a connected trader saw Dow/Nikkei/HSI at
    stub levels 'updated 5 seconds ago' every morning. Sample payloads omit
    the field; the GlobalIndices widget badges on ``is_sample_data``.
    """
    resp = client.get("/api/v1/market/global_indices")
    data = resp.get_json()
    assert "updated_at" not in data
    assert data["is_sample_data"] is True


def test_global_indices_old_path_returns_404(client):
    """Sanity check that the old (incorrect) path doesn't accidentally work.

    Locks the contract — if anyone re-introduces /global/indices as a
    duplicate route, this fails. Frontend pairs with /market/global_indices.
    """
    resp = client.get("/api/v1/global/indices")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /api/v1/screener/shareholding
# ---------------------------------------------------------------------------


def test_shareholding_returns_sample_data_with_default_symbol(client):
    resp = client.get("/api/v1/screener/shareholding")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert "shareholding" in data
    assert "financials" in data
    assert "announcements" in data
    # Percentages should sum to ~100 (allow small rounding).
    sh = data["shareholding"]
    total = sh["promoter_pct"] + sh["fii_pct"] + sh["dii_pct"] + sh["public_pct"] + sh["government_pct"]
    assert 99.0 <= total <= 101.0


def test_shareholding_echoes_symbol_param(client):
    resp = client.get("/api/v1/screener/shareholding?symbol=tcs")
    assert resp.status_code == 200
    data = resp.get_json()
    # Server normalises to upper-case.
    assert data["shareholding"]["symbol"] == "TCS"
    assert data["financials"]["symbol"] == "TCS"


# ---------------------------------------------------------------------------
# /api/v1/screener/sector-constituents
# ---------------------------------------------------------------------------


def test_sector_constituents_returns_sample_data(client):
    resp = client.get("/api/v1/screener/sector-constituents?sector=BANKNIFTY")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["is_sample_data"] is True
    assert data["sector"] == "BANKNIFTY"
    assert data["benchmark"] == "NIFTY"
    assert isinstance(data["constituents"], list)
    assert len(data["constituents"]) >= 1
    c0 = data["constituents"][0]
    for field in ("symbol", "name", "weight", "tail", "current_quadrant"):
        assert field in c0, f"constituent missing field {field}"
    assert c0["current_quadrant"] in {"leading", "weakening", "lagging", "improving"}


# ---------------------------------------------------------------------------
# /api/v1/screener/lot-size
# ---------------------------------------------------------------------------


def test_lot_size_known_symbol_returns_real_value(client):
    resp = client.get("/api/v1/screener/lot-size?symbol=NIFTY&exchange=NFO")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["symbol"] == "NIFTY"
    assert data["exchange"] == "NFO"
    assert data["lot_size"] == 75  # Current NIFTY lot size (post-2024 reset)


def test_lot_size_is_flagged_as_sample_data(client):
    """The lot-size stub MUST declare ``is_sample_data: true``.

    This was the ONLY route in the blueprint without the flag — and its
    value multiplies real order quantities in the ScalperWidget. An
    unflagged hardcoded lot size is a live-money honesty bug: the frontend
    needs the flag to refuse to prefer this table over an audited source.
    """
    for query in ("symbol=NIFTY&exchange=NFO", "symbol=XYZ123", "symbol=USDINR&exchange=CDS"):
        resp = client.get(f"/api/v1/screener/lot-size?{query}")
        assert resp.status_code == 200
        assert resp.get_json()["is_sample_data"] is True, f"missing flag for {query}"


def test_lot_size_banknifty_returns_30(client):
    resp = client.get("/api/v1/screener/lot-size?symbol=BANKNIFTY")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lot_size"] == 30


def test_lot_size_unknown_symbol_returns_zero(client):
    """Unknown symbols return ``0`` so the frontend falls back to its built-in table."""
    resp = client.get("/api/v1/screener/lot-size?symbol=XYZ123")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lot_size"] == 0


def test_lot_size_currency_pair(client):
    resp = client.get("/api/v1/screener/lot-size?symbol=USDINR&exchange=CDS")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["lot_size"] == 1000
    assert data["exchange"] == "CDS"
