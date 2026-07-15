"""Tests for packages/services/screener/src/oi_analytics_routes.py — OI heatmap, analysis, unusual."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from flask import Flask

import flinttrade_screener.oi_analytics_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CHAIN = [
    {
        "strike": 22000,
        "ce_oi": 150000,
        "pe_oi": 120000,
        "ce_oi_change": 5000,
        "pe_oi_change": -3000,
        "ce_volume": 8000,
        "pe_volume": 6500,
        "ce_ltp": 250.0,
        "pe_ltp": 180.0,
    },
    {
        "strike": 22100,
        "ce_oi": 80000,
        "pe_oi": 90000,
        "ce_oi_change": -2000,
        "pe_oi_change": 4000,
        "ce_volume": 4000,
        "pe_volume": 5000,
        "ce_ltp": 200.0,
        "pe_ltp": 220.0,
    },
]


def _future_expiry(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


class _ConnectedRegistry:
    def __init__(self) -> None:
        self.chain_calls: list[tuple[str, dict]] = []

    def is_connected(self) -> bool:
        return True

    def get_primary_account_id(self) -> str:
        return "acc-primary"

    def get_option_chain(self, account_id: str, params: dict) -> dict:
        self.chain_calls.append((account_id, params))
        return {"spot": 22050.0, "strikes": _CHAIN}


class _PayloadRegistry(_ConnectedRegistry):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload

    def get_option_chain(self, account_id: str, params: dict) -> dict:
        self.chain_calls.append((account_id, params))
        return self.payload


@pytest.fixture()
def app():
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.oi_analytics_bp)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/heatmap
# ---------------------------------------------------------------------------


def test_heatmap_ok(client):
    """200 with heatmap data."""
    resp = client.post(
        "/v1/oi/heatmap",
        json={"symbol": "NIFTY", "chain": _CHAIN},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_heatmap_sample_data(client):
    """200 with synthetic sample data when chain absent."""
    resp = client.post("/v1/oi/heatmap", json={"symbol": "NIFTY"})
    assert resp.status_code == 200


def test_heatmap_uses_connected_registry_option_chain_contract(app, client):
    registry = _ConnectedRegistry()
    app.config["REGISTRY"] = registry

    resp = client.post(
        "/v1/oi/heatmap",
        json={"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["is_sample_data"] is False
    assert registry.chain_calls == [
        ("acc-primary", {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": _future_expiry()})
    ]


def test_live_heatmap_preserves_missing_oi_changes(app, client):
    rows = [{**row} for row in _CHAIN]
    for row in rows:
        row.pop("ce_oi_change")
        row.pop("pe_oi_change")
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post("/v1/oi/heatmap", json={"symbol": "NIFTY", "expiry": _future_expiry()})

    body = response.get_json()
    assert response.status_code == 200
    assert body["is_sample_data"] is False
    assert all(entry["ce_change"] is None for entry in body["data"]["entries"])
    assert all(entry["pe_change"] is None for entry in body["data"]["entries"])


def test_live_heatmap_preserves_explicit_zero_oi_changes(app, client):
    rows = [{**row, "ce_oi_change": 0, "pe_oi_change": 0} for row in _CHAIN]
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post("/v1/oi/heatmap", json={"symbol": "NIFTY", "expiry": _future_expiry()})

    body = response.get_json()
    assert body["is_sample_data"] is False
    assert all(entry["ce_change"] == 0 for entry in body["data"]["entries"])
    assert all(entry["pe_change"] == 0 for entry in body["data"]["entries"])


def test_live_heatmap_zero_call_total_has_unavailable_pcr(app, client):
    rows = [{**row, "ce_oi": 0} for row in _CHAIN]
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post("/v1/oi/heatmap", json={"symbol": "NIFTY", "expiry": _future_expiry()})

    body = response.get_json()
    assert body["is_sample_data"] is False
    assert body["data"]["overall_pcr"] is None
    assert body["data"]["max_ce_oi_strike"] is None


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/analysis
# ---------------------------------------------------------------------------


def test_oi_analysis_ok(client):
    """200 with LB/SC/SB/LU signal analysis."""
    resp = client.post(
        "/v1/oi/analysis",
        json={"symbol": "NIFTY", "chain": _CHAIN, "spot": 22050.0},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_oi_analysis_sample(client):
    """200 with sample data when chain absent."""
    resp = client.post("/v1/oi/analysis", json={})
    assert resp.status_code == 200


@pytest.mark.parametrize("price_change", ["sideways", "rising", "", 7])
def test_oi_analysis_rejects_unknown_price_direction(client, price_change):
    response = client.post("/v1/oi/analysis", json={"price_change": price_change})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


# ---------------------------------------------------------------------------
# POST /ft-api/v1/oi/unusual
# ---------------------------------------------------------------------------


def test_unusual_ok(client):
    """200 with unusual OI activity report."""
    resp = client.post(
        "/v1/oi/unusual",
        json={"symbol": "NIFTY", "chain": _CHAIN},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "success"


def test_unusual_sample(client):
    """200 with sample data when chain absent."""
    resp = client.post("/v1/oi/unusual", json={})
    assert resp.status_code == 200


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
def test_live_oi_routes_reject_missing_oi(app, client, path):
    rows = [{**row} for row in _CHAIN]
    for row in rows:
        row.pop("ce_oi")
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post(
        f"/v1/oi/{path}",
        json={"price_change": "up", "expiry": _future_expiry()},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
@pytest.mark.parametrize("invalid_oi", [None, -1, float("nan"), float("inf"), True])
def test_live_oi_routes_reject_non_authoritative_oi(app, client, path, invalid_oi):
    rows = [{**row, "ce_oi": invalid_oi} for row in _CHAIN]
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post(
        f"/v1/oi/{path}",
        json={"price_change": "up", "expiry": _future_expiry()},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True


@pytest.mark.parametrize("path", ["analysis", "unusual"])
def test_live_signal_routes_require_explicit_oi_changes(app, client, path):
    rows = [{**row} for row in _CHAIN]
    for row in rows:
        row.pop("ce_oi_change")
        row.pop("pe_oi_change")
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post(
        f"/v1/oi/{path}",
        json={"price_change": "up", "expiry": _future_expiry()},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
def test_live_oi_routes_reject_the_whole_chain_when_any_source_row_is_malformed(app, client, path):
    valid = {**_CHAIN[0]}
    rows = [
        {**valid, "strike": "not-a-strike"},
        {**valid, "strike": True},
        {**valid, "pe_oi": -1},
        valid,
    ]
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post(
        f"/v1/oi/{path}",
        json={"price_change": "up", "expiry": _future_expiry()},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["is_sample_data"] is True


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
@pytest.mark.parametrize(
    ("metadata", "value"),
    [
        ("underlying", "BANKNIFTY"),
        ("exchange", "BFO"),
        ("expiry", "2099-01-01"),
        ("expiry", ""),
    ],
)
def test_live_oi_routes_reject_explicit_chain_identity_mismatch(
    app,
    client,
    path,
    metadata,
    value,
):
    payload = {"spot": 22050.0, "strikes": _CHAIN, metadata: value}
    app.config["REGISTRY"] = _PayloadRegistry(payload)

    response = client.post(
        f"/v1/oi/{path}",
        json={
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiry": _future_expiry(),
            "price_change": "up",
        },
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
@pytest.mark.parametrize("spot", ["garbage", "nan", float("nan"), float("inf"), True, 0, -1])
def test_live_oi_routes_reject_invalid_spot_with_controlled_400(client, path, spot):
    response = client.post(f"/v1/oi/{path}", json={"spot": spot})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert "NaN" not in response.get_data(as_text=True)


@pytest.mark.parametrize("threshold", ["garbage", "nan", float("nan"), float("inf"), True, -1])
def test_unusual_route_rejects_invalid_threshold_with_controlled_400(client, threshold):
    response = client.post("/v1/oi/unusual", json={"threshold": threshold})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert "NaN" not in response.get_data(as_text=True)


@pytest.mark.parametrize("n_strikes", ["garbage", "nan", float("nan"), float("inf"), True, 0, -1])
def test_heatmap_route_rejects_invalid_strike_count_with_controlled_400(client, n_strikes):
    response = client.post("/v1/oi/heatmap", json={"n_strikes": n_strikes})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected_exchange"),
    [
        ("NIFTY", "NFO", "NSE_INDEX"),
        ("SENSEX", "BFO", "BSE_INDEX"),
    ],
)
def test_native_oi_routes_request_the_underlying_index_exchange(
    app,
    client,
    symbol,
    exchange,
    expected_exchange,
):
    registry = _ConnectedRegistry()
    app.config["REGISTRY"] = registry
    expiry = _future_expiry()

    response = client.post(
        "/v1/oi/heatmap",
        json={"symbol": symbol, "exchange": exchange, "expiry": expiry},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is False
    assert registry.chain_calls == [
        ("acc-primary", {"symbol": symbol, "exchange": expected_exchange, "expiry": expiry})
    ]


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
def test_native_oi_routes_reject_a_contradictory_index_venue_before_live_read(app, client, path):
    registry = _ConnectedRegistry()
    app.config["REGISTRY"] = registry

    response = client.post(
        f"/v1/oi/{path}",
        json={
            "symbol": "SENSEX",
            "exchange": "NFO",
            "expiry": _future_expiry(),
            "price_change": "up",
        },
    )

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"
    assert registry.chain_calls == []


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
def test_live_oi_routes_reject_duplicate_strikes_chain_wide(app, client, path):
    rows = [{**row} for row in _CHAIN]
    rows.append({**rows[0]})
    app.config["REGISTRY"] = _PayloadRegistry({"spot": 22050.0, "strikes": rows})

    response = client.post(
        f"/v1/oi/{path}",
        json={"expiry": _future_expiry(), "price_change": "up"},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
@pytest.mark.parametrize("expiry", ["", "2020-01-01", "9999-12-31"])
def test_live_oi_routes_require_a_strictly_future_expiry(app, client, path, expiry):
    registry = _PayloadRegistry({"spot": 22050.0, "strikes": _CHAIN})
    app.config["REGISTRY"] = registry

    response = client.post(f"/v1/oi/{path}", json={"expiry": expiry, "price_change": "up"})

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True
    assert registry.chain_calls == []


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
def test_live_oi_routes_reject_non_object_json(client, path):
    response = client.post(f"/v1/oi/{path}", data="[]", content_type="application/json")

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


@pytest.mark.parametrize("path", ["heatmap", "analysis", "unusual"])
@pytest.mark.parametrize(
    ("field", "value"),
    [("symbol", 123), ("exchange", ["NFO"]), ("expiry", {"date": "2099-01-01"})],
)
def test_live_oi_routes_reject_non_string_identity_fields(client, path, field, value):
    response = client.post(f"/v1/oi/{path}", json={field: value})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("spot", 1e308),
        ("strike", 1e308),
        ("ce_oi", 10**100),
        ("ce_oi_change", 10**100),
        ("ce_ltp", 1e308),
    ],
)
def test_extreme_finite_oi_observations_fall_back_without_non_finite_output(app, client, field, value):
    payload = {"spot": 22050.0, "strikes": [{**row} for row in _CHAIN]}
    if field == "spot":
        payload["spot"] = value
    else:
        payload["strikes"][0][field] = value
    app.config["REGISTRY"] = _PayloadRegistry(payload)

    response = client.post(
        "/v1/oi/unusual",
        json={"expiry": _future_expiry(), "price_change": "up"},
    )

    assert response.status_code == 200
    assert response.get_json()["is_sample_data"] is True
    assert "Infinity" not in response.get_data(as_text=True)
    assert "NaN" not in response.get_data(as_text=True)


def test_low_spot_sample_oi_chain_has_only_positive_regular_strikes():
    snapshots = mod._make_sample_oi_chain(spot=1.0, step=100.0)
    strikes = [snapshot.strike for snapshot in snapshots]
    steps = [right - left for left, right in zip(strikes, strikes[1:])]

    assert min(strikes) > 0
    assert len(set(strikes)) == len(strikes)
    assert all(step > 0 for step in steps)
    assert max(steps) == pytest.approx(min(steps))
