"""Tests for Flask analysis routes blueprint.

Uses Flask test client — no real broker connections or API calls required.
All endpoints fall back to sample data when no registry is connected.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure repo root is on sys.path for cross-package imports
_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app():
    """Create a minimal Flask app with only the analysis blueprint registered."""
    from flask import Flask
    from flinttrade_screener.analysis_routes import analysis_bp

    flask_app = Flask("test_analysis")
    flask_app.config["TESTING"] = True
    # No REGISTRY in config → endpoints fall back to sample data
    flask_app.register_blueprint(analysis_bp)
    return flask_app


@pytest.fixture()
def client(app):
    """Flask test client."""
    return app.test_client()


def _post(client, path: str, body: dict | None = None):
    """Helper: POST JSON to the given path and return parsed response."""
    data = json.dumps(body or {})
    response = client.post(
        path,
        data=data,
        content_type="application/json",
    )
    return response, response.get_json()


def _chain_payload() -> dict:
    payload = {
        "spot": 24000.0,
        "lot_size": 75,
        "strikes": [
            {
                "strike_price": 23800,
                "ce_ltp": 260,
                "ce_oi": 30000,
                "ce_iv": 13.5,
                "ce_delta": 0.72,
                "pe_ltp": 40,
                "pe_oi": 70000,
                "pe_iv": 14.0,
                "pe_delta": -0.28,
            },
            {
                "strike_price": 24000,
                "ce_ltp": 130,
                "ce_oi": 80000,
                "ce_iv": 13.0,
                "ce_delta": 0.52,
                "pe_ltp": 110,
                "pe_oi": 82000,
                "pe_iv": 13.1,
                "pe_delta": -0.48,
            },
            {
                "strike_price": 24200,
                "ce_ltp": 55,
                "ce_oi": 35000,
                "ce_iv": 13.8,
                "ce_delta": 0.31,
                "pe_ltp": 230,
                "pe_oi": 28000,
                "pe_iv": 14.3,
                "pe_delta": -0.69,
            },
        ],
    }
    for row in payload["strikes"]:
        row.update({
            "ce_gamma": 0.001,
            "ce_theta": -8.0,
            "ce_vega": 6.0,
            "ce_greeks_complete": True,
            "pe_gamma": 0.001,
            "pe_theta": -8.0,
            "pe_vega": 6.0,
            "pe_greeks_complete": True,
        })
    return payload


def _future_expiry(days: int = 30) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _history_candles(n: int = 80) -> list[dict]:
    base = 1_700_000_000
    return [
        {"timestamp": base + i * 604_800, "open": 100 + i, "high": 102 + i, "low": 99 + i,
         "close": 101 + i, "volume": 10_000 + i}
        for i in range(n)
    ]


class _ConnectedRegistry:
    def __init__(self) -> None:
        self.history_calls: list[tuple[str, dict]] = []
        self.chain_calls: list[tuple[str, dict]] = []

    def is_connected(self) -> bool:
        return True

    def get_primary_account_id(self) -> str:
        return "acc-primary"

    def get_history(self, account_id: str, params: dict) -> dict:
        self.history_calls.append((account_id, params))
        return {"candles": _history_candles(), "spot": 24000.0}

    def get_option_chain(self, account_id: str, params: dict) -> dict:
        self.chain_calls.append((account_id, params))
        return _chain_payload()


class _PayloadRegistry(_ConnectedRegistry):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload

    def get_option_chain(self, account_id: str, params: dict) -> dict:
        self.chain_calls.append((account_id, params))
        return self.payload


# ---------------------------------------------------------------------------
# GEX endpoint
# ---------------------------------------------------------------------------


class TestGEXEndpoint:
    """Tests for POST /v1/gex."""

    def test_gex_returns_200(self, client):
        resp, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26"})
        assert resp.status_code == 200

    def test_gex_status_ok(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["status"] == "success"

    def test_gex_has_data(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert "data" in body
        # Terminal GEXData contract (mapped from the GEXResult dataclass).
        data = body["data"]
        assert "strikes" in data
        assert "net_gex" in data  # was total_net_gex on the dataclass
        assert "atm_strike" in data
        assert "gamma_flip_strike" in data
        assert "dealer_zone" in data
        assert "underlying" in data
        # Per-strike objects use the frontend `strike` key, not `strike_price`.
        if data["strikes"]:
            assert "strike" in data["strikes"][0]
            assert "call_gex" in data["strikes"][0]

    def test_gex_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})
        assert len(body["data"]["strikes"]) > 0

    def test_gex_symbol_in_response(self, client):
        _, body = _post(client, "/api/v1/gex", {"symbol": "BANKNIFTY", "exchange": "NFO"})
        assert body["symbol"] == "BANKNIFTY"

    def test_gex_uses_connected_registry_option_chain(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry
        expiry = _future_expiry()

        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry})

        assert body["is_sample_data"] is False
        assert body["data"]["gamma_flip_strike"] is None
        assert registry.chain_calls == [(
            "acc-primary",
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": expiry},
        )]

    def test_zero_net_gex_is_neutral(self, app, client):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row["ce_oi"] = 0
            row["pe_oi"] = 0
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        expiry = _future_expiry()

        _, body = _post(
            client,
            "/api/v1/gex",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert body["data"]["net_gex"] == 0.0
        assert body["data"]["dealer_zone"] == "Neutral Gamma"
        assert body["data"]["gamma_flip_strike"] is None

    def test_unknown_symbol_without_authoritative_lot_size_is_unavailable(self, app, client):
        payload = _chain_payload()
        payload.pop("lot_size")
        app.config["REGISTRY"] = _PayloadRegistry(payload)

        response, body = _post(
            client,
            "/api/v1/gex",
            {"symbol": "RELIANCE", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True
        assert body["lot_size"] is None
        assert body["data"]["available"] is False
        assert body["data"]["strikes"] == []

    def test_unknown_symbol_uses_live_lot_size_resolver_when_available(self, app, client):
        class _InstrumentClient:
            def instruments(self, *, exchange: str):
                assert exchange == "NFO"
                return {
                    "status": "success",
                    "data": [{"symbol": "RELIANCE", "exchange": "NFO", "lot_size": 250}],
                }

        payload = _chain_payload()
        payload.pop("lot_size")
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        app.config["OPENALGO_CLIENT"] = _InstrumentClient()

        response, body = _post(
            client,
            "/api/v1/gex",
            {"symbol": "RELIANCE", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        assert body["lot_size"] == 250
        assert body["data"]["available"] is True

    def test_known_index_lot_size_requires_authoritative_metadata(self, app, client):
        payload = _chain_payload()
        payload.pop("lot_size")
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        app.config["OPENALGO_CLIENT"] = None

        _, body = _post(
            client,
            "/api/v1/gex",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert body["is_sample_data"] is True
        assert body["lot_size"] == 75
        assert body["data"]["available"] is True
        assert body["data"]["strikes"]


# ---------------------------------------------------------------------------
# Vol Surface endpoint
# ---------------------------------------------------------------------------


class TestVolSurfaceEndpoint:
    """Tests for POST /v1/volsurface."""

    def test_volsurface_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": [_future_expiry(30), _future_expiry(60)], "strike_count": 20,
        })
        assert resp.status_code == 200

    def test_volsurface_status_ok(self, client):
        response, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO", "expiries": [_future_expiry()],
        })
        assert body["status"] == "success"

    def test_volsurface_has_matrix(self, client):
        response, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": [_future_expiry(30), _future_expiry(60)],
        })
        # Terminal VolSurfaceData contract (mapped from the raw dataclass).
        data = body["data"]
        assert "iv_matrix" in data
        assert "strikes" in data
        assert "days_to_expiry" in data  # was expiries_dte on the dataclass
        assert "expiries" in data  # human-readable labels
        assert "atm_strike" in data
        assert "underlying" in data
        assert "spot_price" in data

    def test_volsurface_matrix_dimensions(self, client):
        """iv_matrix rows should match expiry count."""
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": [_future_expiry(30), _future_expiry(60), _future_expiry(90)],
        })
        data = body["data"]
        n_expiries = len(data["days_to_expiry"])
        n_strikes = len(data["strikes"])
        assert len(data["iv_matrix"]) == n_expiries
        for row in data["iv_matrix"]:
            assert len(row) == n_strikes

    def test_volsurface_strike_count_limited(self, client):
        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY", "exchange": "NFO",
            "expiries": [_future_expiry()], "strike_count": 5,
        })
        assert len(body["data"]["strikes"]) <= 5

    def test_sample_volsurface_uses_the_requested_expiry_dte(self, client):
        expiry = _future_expiry(43)

        response, body = _post(
            client,
            "/api/v1/volsurface",
            {"symbol": "NIFTY", "exchange": "NFO", "expiries": [expiry]},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True
        assert body["data"]["expiries"] == [expiry]
        assert body["data"]["days_to_expiry"] == [43]

    def test_omitted_volsurface_expiries_are_generated_future_dates(self, client):
        response, body = _post(client, "/api/v1/volsurface", {})

        assert response.status_code == 200
        assert body["is_sample_data"] is True
        parsed = [date.fromisoformat(value) for value in body["data"]["expiries"]]
        assert all(value > date.today() for value in parsed)
        assert body["data"]["days_to_expiry"] == [
            (value - date.today()).days for value in parsed
        ]

    def test_volsurface_rejects_an_unbounded_expiry_vector(self, client):
        expiries = [_future_expiry(offset) for offset in range(1, 14)]

        response, body = _post(client, "/api/v1/volsurface", {"expiries": expiries})

        assert response.status_code == 400
        assert body["status"] == "error"
        assert "at most 12" in body["message"]

    def test_volsurface_uses_connected_registry_option_chain(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry
        expiry = _future_expiry()

        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiries": [expiry],
        })

        assert body["is_sample_data"] is False
        assert registry.chain_calls[0] == (
            "acc-primary",
            {"symbol": "NIFTY", "exchange": "NSE_INDEX", "expiry": expiry},
        )

    @pytest.mark.parametrize("expiry_form", ["iso", "compact"])
    def test_live_volsurface_derives_exact_dte_from_expiry(self, app, client, expiry_form):
        from datetime import date, timedelta

        from flinttrade_screener.symbol_converter import format_expiry_date

        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry
        future = date.today() + timedelta(days=23)
        expiry = future.isoformat() if expiry_form == "iso" else format_expiry_date(future)

        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiries": [expiry],
        })

        assert body["is_sample_data"] is False
        assert body["data"]["expiries"] == [expiry]
        assert body["data"]["days_to_expiry"] == [23]

    def test_live_volsurface_preserves_distinct_dte_for_multiple_expiries(self, app, client):
        from datetime import date, timedelta

        from flinttrade_screener.symbol_converter import format_expiry_date

        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry
        near_expiry = (date.today() + timedelta(days=11)).isoformat()
        far_expiry = format_expiry_date(date.today() + timedelta(days=37))

        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiries": [far_expiry, near_expiry],
        })

        assert body["is_sample_data"] is False
        assert body["data"]["expiries"] == [near_expiry, far_expiry]
        assert body["data"]["days_to_expiry"] == [11, 37]

    def test_live_volsurface_rejects_unparseable_expiry(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry

        response, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiries": ["not-an-expiry"],
        })

        assert response.status_code == 400
        assert body["status"] == "error"
        assert registry.chain_calls == []

    @pytest.mark.parametrize("expiry", ["2020-01-01", pytest.param("today", id="same-day")])
    def test_live_volsurface_requires_strictly_future_expiry(self, app, client, expiry):
        app.config["REGISTRY"] = _PayloadRegistry(_chain_payload())
        selected = date.today().isoformat() if expiry == "today" else expiry

        response, body = _post(
            client,
            "/api/v1/volsurface",
            {"symbol": "NIFTY", "exchange": "NFO", "expiries": [selected]},
        )

        assert response.status_code == 400
        assert body["status"] == "error"

    @pytest.mark.parametrize("missing_field", ["ce_ltp", "pe_ltp", "ce_iv", "pe_iv"])
    def test_live_volsurface_rejects_omitted_price_or_iv(self, app, client, missing_field):
        from datetime import date, timedelta

        payload = _chain_payload()
        for row in payload["strikes"]:
            row.pop(missing_field)
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        expiry = (date.today() + timedelta(days=20)).isoformat()

        _, body = _post(client, "/api/v1/volsurface", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiries": [expiry],
        })

        assert body["is_sample_data"] is True

    @pytest.mark.parametrize("invalid_value", [0, -1, float("nan"), float("inf")])
    @pytest.mark.parametrize("field", ["ce_ltp", "pe_ltp", "ce_iv", "pe_iv"])
    def test_live_volsurface_rejects_non_positive_or_non_finite_observations(
        self,
        app,
        client,
        field,
        invalid_value,
    ):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row[field] = invalid_value
        app.config["REGISTRY"] = _PayloadRegistry(payload)

        _, body = _post(
            client,
            "/api/v1/volsurface",
            {"symbol": "NIFTY", "exchange": "NFO", "expiries": [_future_expiry()]},
        )

        assert body["is_sample_data"] is True


# ---------------------------------------------------------------------------
# IV Smile endpoint
# ---------------------------------------------------------------------------


class TestIVSmileEndpoint:
    """Tests for POST /v1/ivsmile."""

    def test_ivsmile_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/ivsmile", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
        })
        assert resp.status_code == 200

    def test_ivsmile_returns_one_curve_per_requested_expiry(self, client):
        """Several expiries in, several curves out.

        This route read a single expiry via ``_body_expiry`` and always
        answered with exactly one curve, so a caller asking for a term
        structure had every expiry past the first dropped in silence — the
        terminal even allocated a three-colour palette for curves that could
        never arrive.
        """
        _, body = _post(client, "/api/v1/ivsmile", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiry_dates": ["26MAR26", "30APR26", "28MAY26"],
        })
        curves = body["data"]["curves"]
        assert len(curves) == 3
        assert [c["expiry"] for c in curves] == ["26MAR26", "30APR26", "28MAY26"]

    def test_ivsmile_deduplicates_and_caps_expiries(self, client):
        """Each expiry is its own chain read, so the fan-out is bounded."""
        _, body = _post(client, "/api/v1/ivsmile", {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiry_dates": ["26MAR26", "26MAR26", "30APR26", "28MAY26", "25JUN26"],
        })
        curves = body["data"]["curves"]
        assert len(curves) == 3, "duplicates collapse and the list is capped"
        assert [c["expiry"] for c in curves] == ["26MAR26", "30APR26", "28MAY26"]

    def test_ivsmile_single_expiry_still_returns_one_curve(self, client):
        """The single-expiry contract every existing caller relies on."""
        _, body = _post(client, "/api/v1/ivsmile", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
        })
        assert len(body["data"]["curves"]) == 1

    def test_ivsmile_status_ok(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["status"] == "success"

    def test_ivsmile_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        # Terminal IVSmileData contract: a `curves` array of per-strike points.
        data = body["data"]
        assert "underlying" in data
        assert "spot_price" in data
        assert "curves" in data and len(data["curves"]) >= 1
        curve = data["curves"][0]
        assert "atm_iv" in curve
        assert "atm_strike" in curve
        assert "skew_25delta" in curve  # was `skew` on the dataclass
        assert "points" in curve
        if curve["points"]:
            p = curve["points"][0]
            assert "strike" in p and "call_iv" in p and "put_iv" in p and "moneyness" in p

    def test_ivsmile_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert len(body["data"]["curves"][0]["points"]) > 0

    def test_ivsmile_atm_iv_positive(self, client):
        _, body = _post(client, "/api/v1/ivsmile", {"symbol": "NIFTY", "exchange": "NFO"})
        assert body["data"]["curves"][0]["atm_iv"] > 0

    def test_ivsmile_uses_connected_registry_option_chain(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry
        expiry = _future_expiry()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert registry.chain_calls[0][1]["exchange"] == "NSE_INDEX"
        assert registry.chain_calls[0][1]["expiry"] == expiry
        curve = body["data"]["curves"][0]
        assert curve["atm_iv"] == pytest.approx(0.1305)
        atm = next(point for point in curve["points"] if point["strike"] == 24000)
        assert atm == {
            "strike": 24000.0,
            "call_iv": pytest.approx(0.13),
            "put_iv": pytest.approx(0.131),
            "moneyness": pytest.approx(1.0),
        }

    def test_ivsmile_labels_fallback_when_every_live_option_leg_is_incomplete(self, app, client):
        class _IncompleteRegistry(_ConnectedRegistry):
            def get_option_chain(self, account_id: str, params: dict) -> dict:
                payload = super().get_option_chain(account_id, params)
                for row in payload["strikes"]:
                    row["pe_greeks_complete"] = False
                return payload

        app.config["REGISTRY"] = _IncompleteRegistry()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26"},
        )

        assert body["is_sample_data"] is True
        curve = body["data"]["curves"][0]
        assert curve["points"]
        assert curve["atm_iv"] > 0.0

    def test_ivsmile_mixed_expiries_keep_live_curves_and_omit_fallback(self, app, client):
        """One live expiry beside one unusable expiry must not poison the response.

        The connected widget accepts data only when is_sample_data is exactly
        False, so collapsing mixed results into a response-wide sample flag
        would discard every valid live curve; sample-backed fallback curves
        are omitted instead.
        """
        app.config["REGISTRY"] = _ConnectedRegistry()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiries": [_future_expiry(), "not-an-expiry"]},
        )

        assert body["is_sample_data"] is False
        assert len(body["data"]["curves"]) == 1
        assert body["data"]["curves"][0]["atm_iv"] > 0.0

    @pytest.mark.parametrize("expiry", ["not-an-expiry", "2020-01-01", pytest.param("today", id="same-day")])
    def test_live_ivsmile_requires_strictly_future_expiry(self, app, client, expiry):
        app.config["REGISTRY"] = _PayloadRegistry(_chain_payload())
        selected = date.today().isoformat() if expiry == "today" else expiry

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": selected},
        )

        assert body["is_sample_data"] is True
        assert body["data"]["curves"][0]["days_to_expiry"] in {0, 7}


# ---------------------------------------------------------------------------
# Straddle P&L endpoint
# ---------------------------------------------------------------------------


class TestStraddlePnLEndpoint:
    """Tests for POST /v1/straddlepnl."""

    def test_straddlepnl_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/straddlepnl", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry(),
            "interval": "5m", "adjustment_points": 50,
        })
        assert resp.status_code == 200

    def test_straddlepnl_status_ok(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_straddlepnl_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        data = body["data"]
        assert "timestamps" in data
        assert "pnl_series" in data
        assert "adjustments" in data
        assert "max_pnl" in data
        assert "min_pnl" in data
        assert "final_pnl" in data
        assert "initial_premium" in data

    def test_straddlepnl_timestamps_not_empty(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        assert len(body["data"]["timestamps"]) > 0

    def test_straddlepnl_pnl_series_same_length_as_timestamps(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY"})
        data = body["data"]
        assert len(data["pnl_series"]) == len(data["timestamps"])

    def test_straddlepnl_uses_connected_registry_history_contract(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry

        _, body = _post(client, "/api/v1/straddlepnl", {"symbol": "NIFTY", "exchange": "NSE_INDEX"})

        assert body["is_sample_data"] is True
        account_id, params = registry.history_calls[0]
        assert account_id == "acc-primary"
        assert params["symbol"] == "NIFTY"
        assert params["exchange"] == "NSE_INDEX"
        assert params["interval"] == "5m"
        assert "start" in params and "end" in params

    def test_straddle_with_live_history_and_explicit_inputs_stays_sample_without_option_provenance(
        self,
        app,
        client,
    ):
        app.config["REGISTRY"] = _ConnectedRegistry()

        response, body = _post(
            client,
            "/api/v1/straddlepnl",
            {
                "symbol": "NIFTY",
                "exchange": "NFO",
                "expiry": _future_expiry(),
                "strike": 24000,
                "ce_premium": 125,
                "pe_premium": 110,
            },
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize("expiry", ["not-an-expiry", "2020-01-01", date.today().isoformat()])
    def test_straddle_rejects_an_unusable_expiry(self, client, expiry):
        response, body = _post(client, "/api/v1/straddlepnl", {"expiry": expiry})

        assert response.status_code == 400
        assert body["status"] == "error"

    def test_straddle_omitted_expiry_is_generated_and_labelled_sample(self, client):
        response, body = _post(client, "/api/v1/straddlepnl", {})

        assert response.status_code == 200
        assert date.fromisoformat(body["expiry"]) > date.today()
        assert body["is_sample_data"] is True


# ---------------------------------------------------------------------------
# OI Profile endpoint
# ---------------------------------------------------------------------------


class TestOIProfileEndpoint:
    """Tests for POST /v1/oiprofile."""

    def test_oiprofile_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/oiprofile", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26", "interval": "5m",
        })
        assert resp.status_code == 200

    def test_oiprofile_status_ok(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_oiprofile_has_required_fields(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        data = body["data"]
        assert "strikes" in data
        assert "ce_oi" in data
        assert "pe_oi" in data
        assert "oi_butterfly" in data
        assert "oi_change" in data
        assert "futures_ohlcv" in data

    def test_oiprofile_butterfly_length_matches_strikes(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        data = body["data"]
        assert len(data["oi_butterfly"]) == len(data["strikes"])

    def test_oiprofile_strikes_not_empty(self, client):
        _, body = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        assert len(body["data"]["strikes"]) > 0

    def test_oiprofile_honours_strike_count(self, client):
        """strike_count windows the strikes ATM-centred; absent it returns all."""
        _, full = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY"})
        full_n = len(full["data"]["strikes"])
        # Only meaningful when the full chain has more strikes than the window.
        if full_n <= 4:
            pytest.skip("sample chain too small to window")

        _, windowed = _post(client, "/api/v1/oiprofile", {"symbol": "NIFTY", "strike_count": 4})
        data = windowed["data"]
        assert len(data["strikes"]) == 4
        # parallel per-strike arrays stay aligned with the windowed strikes
        assert len(data["oi_butterfly"]) == 4
        assert len(data["oi_change"]) == 4
        # the kept strikes are the 4 nearest the ATM, returned in strike order
        atm = data["atm_strike"]
        kept = [s["strike"] for s in data["strikes"]]
        assert kept == sorted(kept)
        all_strikes = [s["strike"] for s in full["data"]["strikes"]]
        nearest4 = sorted(sorted(all_strikes, key=lambda s: abs(s - atm))[:4])
        assert kept == nearest4


# ---------------------------------------------------------------------------
# Max Pain endpoint
# ---------------------------------------------------------------------------


class TestMaxPainEndpoint:
    """Tests for POST /v1/maxpain."""

    def test_maxpain_returns_200(self, client):
        resp, _ = _post(client, "/api/v1/maxpain", {
            "symbol": "NIFTY", "exchange": "NFO", "expiry": "26MAR26",
        })
        assert resp.status_code == 200

    def test_maxpain_status_ok(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        assert body["status"] == "success"

    def test_maxpain_has_strike(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        data = body["data"]
        assert "max_pain_strike" in data
        assert data["max_pain_strike"] > 0

    def test_maxpain_has_strike_losses(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        data = body["data"]
        assert "strike_losses" in data
        assert len(data["strike_losses"]) > 0

    def test_maxpain_total_loss_positive(self, client):
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        assert body["data"]["total_loss_at_max_pain"] >= 0

    def test_maxpain_strike_near_spot(self, client):
        """Max pain should be within a reasonable range of the spot."""
        _, body = _post(client, "/api/v1/maxpain", {"symbol": "NIFTY"})
        spot = body["spot"]
        max_pain = body["data"]["max_pain_strike"]
        # Max pain within 10% of spot is reasonable for synthetic data
        assert abs(max_pain - spot) <= spot * 0.10


# ---------------------------------------------------------------------------
# Expiry param normalisation (feature audit H7)
# ---------------------------------------------------------------------------


class TestExpiryParamNormalisation:
    """The terminal sends expiry_date/expiry_dates; routes must honour them."""

    def test_body_expiry_accepts_all_key_variants(self):
        from flinttrade_screener.analysis_routes import _body_expiry

        assert _body_expiry({"expiry": "26MAR26"}, "X") == "26MAR26"
        assert _body_expiry({"expiry_date": "26MAR26"}, "X") == "26MAR26"
        assert _body_expiry({"expiry_dates": ["26MAR26", "24APR26"]}, "X") == "26MAR26"
        assert _body_expiry({}, "FALLBACK") == "FALLBACK"

    def test_body_expiries_accepts_all_key_variants(self):
        from flinttrade_screener.analysis_routes import _body_expiries

        assert _body_expiries({"expiries": ["A"]}, ["X"]) == ["A"]
        assert _body_expiries({"expiry_dates": ["A", "B"]}, ["X"]) == ["A", "B"]
        assert _body_expiries({"expiry_date": "A"}, ["X"]) == ["A"]
        assert _body_expiries({}, ["DEF"]) == ["DEF"]

    def test_oiprofile_honours_frontend_expiry_date_key(self, client):
        resp, _ = _post(
            client,
            "/api/v1/oiprofile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry_date": "26MAR26"},
        )
        assert resp.status_code == 200

    def test_gex_honours_frontend_expiry_date_key(self, client):
        resp, _ = _post(
            client,
            "/api/v1/gex",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry_date": "26MAR26"},
        )
        assert resp.status_code == 200


class TestDaysToExpiry:
    """`_days_to_expiry` must yield a real time-to-expiry so the terminal's
    Greeks widgets get non-degenerate (T>0) greeks — a hardcoded 0 collapses
    gamma/theta/vega to zero."""

    def test_future_expiry_is_positive_and_accurate(self):
        from datetime import date, timedelta

        from flinttrade_screener.analysis_routes import _days_to_expiry
        from flinttrade_screener.symbol_converter import format_expiry_date

        future = date.today() + timedelta(days=30)
        assert _days_to_expiry(format_expiry_date(future)) == 30

    def test_accepts_iso_form_the_expiry_api_returns(self):
        # getExpiry emits ISO YYYY-MM-DD; this is what the live Greeks-heatmap
        # path feeds straight through to the IV-smile route.
        from datetime import date, timedelta

        from flinttrade_screener.analysis_routes import _days_to_expiry

        future = date.today() + timedelta(days=21)
        assert _days_to_expiry(future.isoformat()) == 21
        # A past ISO date clamps to 0.
        assert _days_to_expiry("2020-01-01") == 0

    def test_accepts_dashed_form_from_the_expiry_api(self):
        from datetime import date, timedelta

        from flinttrade_screener.analysis_routes import _days_to_expiry
        from flinttrade_screener.symbol_converter import format_expiry_date

        future = date.today() + timedelta(days=10)
        dashed = format_expiry_date(future)  # e.g. 16JUN26
        dashed = f"{dashed[:2]}-{dashed[2:5]}-{dashed[5:]}"  # 16-JUN-26
        assert _days_to_expiry(dashed) == 10

    def test_past_or_unparseable_expiry_is_zero(self):
        from flinttrade_screener.analysis_routes import _days_to_expiry

        assert _days_to_expiry("01JAN20") == 0   # well in the past
        assert _days_to_expiry("garbage") == 0
        assert _days_to_expiry("") == 0


class TestSampleDataHonesty:
    """No broker is connected in tests, so every option-chain analysis endpoint
    serves sample data and MUST say so (is_sample_data=True). Before this, several
    endpoints omitted the flag or computed it from ``registry is None`` — which
    mislabelled the sample fallback as live whenever a (disconnected) registry was
    present, presenting fabricated data as real (a house-rule violation)."""

    _BODY = {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()}

    def test_gex_reports_sample(self, client):
        _, body = _post(client, "/api/v1/gex", self._BODY)
        assert body["is_sample_data"] is True

    def test_volsurface_reports_sample(self, client):
        _, body = _post(
            client,
            "/api/v1/volsurface",
            {**self._BODY, "expiries": [self._BODY["expiry"]]},
        )
        assert body["is_sample_data"] is True

    def test_ivsmile_reports_sample(self, client):
        _, body = _post(client, "/api/v1/ivsmile", self._BODY)
        assert body["is_sample_data"] is True

    def test_straddlepnl_reports_sample(self, client):
        _, body = _post(client, "/api/v1/straddlepnl", self._BODY)
        assert body["is_sample_data"] is True

    def test_oiprofile_reports_sample(self, client):
        _, body = _post(client, "/api/v1/oiprofile", self._BODY)
        assert body["is_sample_data"] is True

    def test_maxpain_reports_sample(self, client):
        _, body = _post(client, "/api/v1/maxpain", self._BODY)
        assert body["is_sample_data"] is True


class TestLiveOptionChain:
    """With an OpenAlgo client configured, the option-chain endpoints fetch a REAL
    chain (via OpenAlgoClient.option_chain) and report is_sample_data=False — the
    other half of the honesty fix: sample only when genuinely unavailable."""

    class _Strike:
        def __init__(self, **kw):
            self._kw = kw

        def model_dump(self):
            data = dict(self._kw)
            for prefix in ("ce", "pe"):
                data.setdefault(f"{prefix}_gamma", 0.001)
                data.setdefault(f"{prefix}_theta", -8.0)
                data.setdefault(f"{prefix}_vega", 6.0)
                data.setdefault(f"{prefix}_greeks_complete", True)
            return data

    class _Chain:
        def __init__(self, strikes, spot_price=24000.0, expiry_date=""):
            self.strikes = strikes
            self.spot_price = spot_price
            self.expiry_date = expiry_date

    class _FakeOpenAlgo:
        def __init__(self):
            self.chain_calls = []

        async def option_chain(self, symbol, exchange="NSE_INDEX", expiry=""):
            self.chain_calls.append((symbol, exchange, expiry))
            S = TestLiveOptionChain._Strike
            return TestLiveOptionChain._Chain([
                S(strike_price=23800, ce_ltp=260, ce_oi=30000, ce_iv=13.5, ce_delta=0.72,
                  pe_ltp=40, pe_oi=70000, pe_iv=14.0, pe_delta=-0.28),
                S(strike_price=23900, ce_ltp=190, ce_oi=40000, ce_iv=13.2, ce_delta=0.63,
                  pe_ltp=65, pe_oi=65000, pe_iv=13.6, pe_delta=-0.37),
                S(strike_price=24000, ce_ltp=130, ce_oi=80000, ce_iv=13.0, ce_delta=0.52,
                  pe_ltp=110, pe_oi=82000, pe_iv=13.1, pe_delta=-0.48),
                S(strike_price=24100, ce_ltp=85, ce_oi=60000, ce_iv=13.4, ce_delta=0.41,
                  pe_ltp=160, pe_oi=45000, pe_iv=13.9, pe_delta=-0.59),
                S(strike_price=24200, ce_ltp=55, ce_oi=35000, ce_iv=13.8, ce_delta=0.31,
                  pe_ltp=230, pe_oi=28000, pe_iv=14.3, pe_delta=-0.69),
            ], expiry_date=expiry)

        def instruments(self, *, exchange):
            assert exchange == "NFO"
            return {
                "status": "success",
                "data": [{"symbol": "NIFTY", "exchange": "NFO", "lot_size": 75}],
            }

    def _post_with_client(self, app, client, path):
        app.config["OPENALGO_CLIENT"] = self._FakeOpenAlgo()
        return _post(
            client,
            path,
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

    def test_gex_uses_live_chain(self, app, client):
        _, body = self._post_with_client(app, client, "/api/v1/gex")
        assert body["status"] == "success"
        assert body["is_sample_data"] is False  # real chain via OpenAlgo, not sample
        assert body["data"]["strikes"]

    def test_maxpain_uses_live_chain(self, app, client):
        _, body = self._post_with_client(app, client, "/api/v1/maxpain")
        assert body["is_sample_data"] is False
        assert body["data"]["max_pain_strike"] > 0

    def test_ivsmile_uses_live_chain(self, app, client):
        _, body = self._post_with_client(app, client, "/api/v1/ivsmile")
        assert body["is_sample_data"] is False

    def test_ivsmile_passes_underlying_exchange_and_selected_expiry_to_openalgo(self, app, client):
        openalgo = self._FakeOpenAlgo()
        app.config["OPENALGO_CLIENT"] = openalgo
        expiry = _future_expiry()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert openalgo.chain_calls == [("NIFTY", "NSE_INDEX", expiry)]

    def test_openalgo_chain_without_response_expiry_identity_is_not_live(self, app, client):
        class _MissingExpiryOpenAlgo(self._FakeOpenAlgo):
            async def option_chain(inner_self, symbol, exchange="NSE_INDEX", expiry=""):
                chain = await super().option_chain(symbol, exchange, expiry)
                chain.expiry_date = ""
                return chain

        app.config["OPENALGO_CLIENT"] = _MissingExpiryOpenAlgo()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert body["is_sample_data"] is True

    def test_native_session_complete_greeks_outrank_incomplete_openalgo_chain(self, app, client):
        import time
        from types import SimpleNamespace

        from flinttrade_gateway.registry import BrokerRegistry

        native_calls = []

        class _NativeAdapter:
            async def option_chain(self, session, req):
                native_calls.append((session, req))
                return {**_chain_payload(), "spot": None, "spot_price": 25123.5}

        class _IncompleteStrike:
            def model_dump(self):
                return {
                    "strike_price": 25000,
                    "ce_iv": 13.0,
                    "pe_iv": 13.1,
                }

        class _IncompleteOpenAlgo:
            async def option_chain(self, _symbol, _exchange="NSE_INDEX", _expiry=""):
                return TestLiveOptionChain._Chain([_IncompleteStrike()], spot_price=24000.0)

        registry = BrokerRegistry()
        session = SimpleNamespace(expires_at=time.time() + 3600)
        registry.put_session("dhan", "native-1", session)
        app.config["REGISTRY"] = registry
        app.config["NATIVE_ADAPTERS"] = {"dhan": _NativeAdapter()}
        app.config["OPENALGO_CLIENT"] = _IncompleteOpenAlgo()

        expiry = _future_expiry()
        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert body["spot"] == 25123.5
        assert native_calls == [(
            session,
            {
                "symbol": "NIFTY",
                "underlying": "NIFTY",
                "exchange": "NSE_INDEX",
                "expiry": expiry,
            },
        )]

    def test_live_chain_selection_skips_a_spotless_complete_source(self, app, client):
        import time
        from types import SimpleNamespace

        from flinttrade_gateway.registry import BrokerRegistry

        class _NativeAdapter:
            def __init__(self, payload):
                self.payload = payload

            async def option_chain(self, _session, _request):
                return self.payload

        spotless = _chain_payload()
        spotless["spot"] = None
        usable = _chain_payload()
        usable["spot"] = 25123.5
        registry = BrokerRegistry()
        registry.put_session("spotless", "one", SimpleNamespace(expires_at=time.time() + 3600))
        registry.put_session("usable", "two", SimpleNamespace(expires_at=time.time() + 3600))
        app.config["REGISTRY"] = registry
        app.config["NATIVE_ADAPTERS"] = {
            "spotless": _NativeAdapter(spotless),
            "usable": _NativeAdapter(usable),
        }
        app.config["OPENALGO_CLIENT"] = None

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert body["is_sample_data"] is False
        assert body["spot"] == 25123.5
        assert body["data"]["curves"][0]["points"]

    def test_live_chain_selection_skips_a_complete_zero_strike_source(self, app, client):
        import time
        from types import SimpleNamespace

        from flinttrade_gateway.registry import BrokerRegistry

        class _NativeAdapter:
            def __init__(self, payload):
                self.payload = payload

            async def option_chain(self, _session, _request):
                return self.payload

        zero_strike = _chain_payload()
        for row in zero_strike["strikes"]:
            row["strike_price"] = 0
        usable = _chain_payload()
        registry = BrokerRegistry()
        registry.put_session("invalid", "one", SimpleNamespace(expires_at=time.time() + 3600))
        registry.put_session("usable", "two", SimpleNamespace(expires_at=time.time() + 3600))
        app.config["REGISTRY"] = registry
        app.config["NATIVE_ADAPTERS"] = {
            "invalid": _NativeAdapter(zero_strike),
            "usable": _NativeAdapter(usable),
        }
        app.config["OPENALGO_CLIENT"] = None

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert body["is_sample_data"] is False
        assert body["data"]["curves"][0]["points"]
        assert all(point["strike"] > 0 for point in body["data"]["curves"][0]["points"])

    def test_gex_incomplete_live_greeks_fall_back_to_labelled_sample(self, app, client):
        class _IncompleteStrike:
            def model_dump(self):
                return {
                    "strike_price": 24000,
                    "ce_oi": 100,
                    "pe_oi": 120,
                    "ce_gamma": None,
                    "pe_gamma": None,
                }

        class _IncompleteOpenAlgo:
            async def option_chain(self, _symbol, _exchange="NSE_INDEX", _expiry=""):
                return TestLiveOptionChain._Chain([_IncompleteStrike()], spot_price=24000.0)

        app.config["OPENALGO_CLIENT"] = _IncompleteOpenAlgo()

        _, body = _post(client, "/api/v1/gex", {"symbol": "NIFTY", "exchange": "NFO"})

        assert body["is_sample_data"] is True
        assert body["data"]["strikes"]
        assert any(row["call_gex"] != 0 for row in body["data"]["strikes"])

    def test_registry_chain_maps_bse_index_identity(self, app, client):
        registry = _ConnectedRegistry()
        app.config["OPENALGO_CLIENT"] = None
        app.config["REGISTRY"] = registry

        expiry = _future_expiry()
        _, body = _post(
            client,
            "/api/v1/maxpain",
            {"symbol": "SENSEX", "exchange": "BFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert registry.chain_calls == [(
            "acc-primary",
            {"symbol": "SENSEX", "exchange": "BSE_INDEX", "expiry": expiry},
        )]

    def test_ivsmile_live_chain_without_spot_uses_labelled_sample(self, app, client):
        class _NoSpotOpenAlgo(self._FakeOpenAlgo):
            async def option_chain(inner_self, symbol, exchange="NSE_INDEX", expiry=""):
                chain = await super().option_chain(symbol, exchange, expiry)
                chain.spot_price = 0.0
                return chain

        app.config["OPENALGO_CLIENT"] = _NoSpotOpenAlgo()

        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO"},
        )

        assert body["is_sample_data"] is True
        assert body["spot"] == 24000.0
        assert body["data"]["spot_price"] == 24000.0
        assert body["data"]["is_sample_data"] is True
        assert body["data"]["curves"][0]["points"]

    def test_ivsmile_curve_echoes_real_days_to_expiry(self, app, client):
        """Integration tripwire: a real future expiry must yield days_to_expiry>0
        in the returned curve. The terminal's Greeks widgets derive time-decay
        greeks from this; a 0 (the old hardcode / unparsed-ISO bug) collapses
        them. Guards the dte echo at the route boundary, not just in isolation."""
        from datetime import date, timedelta

        app.config["OPENALGO_CLIENT"] = self._FakeOpenAlgo()
        future_iso = (date.today() + timedelta(days=20)).isoformat()  # YYYY-MM-DD
        _, body = _post(
            client,
            "/api/v1/ivsmile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry_dates": [future_iso]},
        )
        assert body["is_sample_data"] is False
        curve = body["data"]["curves"][0]
        assert curve["days_to_expiry"] > 0, "ISO expiry must yield a real positive DTE"


class TestOptionChainTruthfulness:
    """Live provenance requires explicit usable inputs for each calculation."""

    _OI_PATHS = (
        "/api/v1/gex",
        "/api/v1/gammadensity",
        "/api/v1/oiprofile",
        "/api/v1/maxpain",
    )

    @staticmethod
    def _configure_registry(app, payload: dict) -> _PayloadRegistry:
        registry = _PayloadRegistry(payload)
        app.config["REGISTRY"] = registry
        app.config["OPENALGO_CLIENT"] = None
        return registry

    @staticmethod
    def _reported_strikes(path: str, body: dict) -> list[float]:
        if path == "/api/v1/maxpain":
            return [row["strike"] for row in body["data"]["strike_losses"]]
        return [row["strike"] for row in body["data"]["strikes"]]

    @pytest.mark.parametrize("path", _OI_PATHS)
    def test_oi_dependent_endpoint_rejects_missing_live_oi(self, app, client, path):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row.pop("ce_oi")
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            path,
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize("path", _OI_PATHS)
    @pytest.mark.parametrize("invalid_oi", [None, -1, float("nan"), float("inf"), True])
    def test_oi_dependent_endpoint_rejects_non_authoritative_live_oi(
        self,
        app,
        client,
        path,
        invalid_oi,
    ):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row["ce_oi"] = invalid_oi
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            path,
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    def test_explicit_zero_oi_remains_authoritative(self, app, client):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row["ce_oi"] = 0
            row["pe_oi"] = 0
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            "/api/v1/maxpain",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        assert body["data"]["available"] is False
        assert body["data"]["max_pain_strike"] == 0.0
        assert body["data"]["strike_losses"] == []

    def test_oi_profile_zero_call_total_has_unavailable_pcr(self, app, client):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row["ce_oi"] = 0
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            "/api/v1/oiprofile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        assert body["data"]["total_ce_oi"] == 0
        assert body["data"]["total_pe_oi"] > 0
        assert body["data"]["pcr"] is None
        assert body["data"]["max_ce_strike"] is None

    def test_oi_profile_all_zero_oi_has_no_support_or_resistance(self, app, client):
        payload = _chain_payload()
        for row in payload["strikes"]:
            row["ce_oi"] = 0
            row["pe_oi"] = 0
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            "/api/v1/oiprofile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        assert body["data"]["max_ce_strike"] is None
        assert body["data"]["max_pe_strike"] is None

    def test_snapshot_converter_never_materialises_missing_oi_as_zero(self):
        from flinttrade_screener.analysis_routes import _snapshot_from_registry_data

        row = _chain_payload()["strikes"][1]
        row.pop("ce_oi")

        snapshot = _snapshot_from_registry_data(
            {"spot": 24000.0, "strikes": [row]},
            "NIFTY",
            "NFO",
            24000.0,
        )

        assert snapshot.strikes == []

    @pytest.mark.parametrize("path", _OI_PATHS)
    def test_oi_endpoints_reject_the_whole_chain_when_any_source_row_is_malformed(
        self,
        app,
        client,
        path,
    ):
        from datetime import date, timedelta

        valid = _chain_payload()["strikes"][1]
        malformed = {**valid, "strike_price": "not-a-strike"}
        boolean_strike = {**valid, "strike_price": True}
        missing_oi = {**valid, "strike_price": 24100}
        missing_oi.pop("pe_oi")
        payload = {
            "spot": 24000.0,
            "strikes": [malformed, boolean_strike, missing_oi, valid],
        }
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            path,
            {
                "symbol": "NIFTY",
                "exchange": "NFO",
                "expiry": (date.today() + timedelta(days=30)).isoformat(),
            },
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize("path", ["/api/v1/ivsmile", "/api/v1/volsurface"])
    def test_non_oi_endpoints_reject_the_whole_chain_when_any_source_row_is_malformed(
        self,
        app,
        client,
        path,
    ):
        valid = _chain_payload()["strikes"][1]
        payload = {
            "spot": 24000.0,
            "strikes": [
                {**valid, "strike_price": "not-a-strike"},
                {**valid, "strike_price": True},
                valid,
            ],
        }
        self._configure_registry(app, payload)
        expiry = _future_expiry()
        request_body = {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry}
        if path == "/api/v1/volsurface":
            request_body["expiries"] = [expiry]

        response, body = _post(client, path, request_body)

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize(
        ("metadata", "value"),
        [
            ("underlying", "BANKNIFTY"),
            ("exchange", "BFO"),
            ("expiry", "2099-01-01"),
            ("expiry", ""),
        ],
    )
    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/gex",
            "/api/v1/gammadensity",
            "/api/v1/oiprofile",
            "/api/v1/maxpain",
            "/api/v1/ivsmile",
            "/api/v1/volsurface",
        ],
    )
    def test_explicit_chain_identity_mismatch_is_never_published_as_live(
        self,
        app,
        client,
        path,
        metadata,
        value,
    ):
        expiry = _future_expiry()
        payload = {**_chain_payload(), metadata: value}
        self._configure_registry(app, payload)
        request_body = {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry}
        if path == "/api/v1/volsurface":
            request_body["expiries"] = [expiry]

        response, body = _post(client, path, request_body)

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("ce_delta", -0.01),
            ("ce_delta", 1.01),
            ("pe_delta", 0.01),
            ("pe_delta", -1.01),
            ("ce_gamma", -0.01),
            ("pe_gamma", -0.01),
            ("ce_vega", -0.01),
            ("pe_vega", -0.01),
            ("ce_theta", float("nan")),
            ("pe_theta", float("inf")),
            ("ce_iv", 0.0),
            ("pe_iv", -1.0),
        ],
    )
    @pytest.mark.parametrize("path", ["/api/v1/gex", "/api/v1/gammadensity", "/api/v1/ivsmile"])
    def test_physically_impossible_complete_greeks_are_rejected(
        self,
        app,
        client,
        path,
        field,
        value,
    ):
        payload = _chain_payload()
        payload["strikes"][0][field] = value
        self._configure_registry(app, payload)

        response, body = _post(
            client,
            path,
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    def test_live_oi_profile_has_no_synthetic_change_or_futures_overlay(self, app, client):
        self._configure_registry(app, _chain_payload())

        response, body = _post(
            client,
            "/api/v1/oiprofile",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": _future_expiry()},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        data = body["data"]
        assert data["oi_change_available"] is False
        assert "oi_change" not in data
        assert "ce_oi_change" not in data
        assert "pe_oi_change" not in data
        assert all("ce_oi_change" not in row for row in data["strikes"])
        assert all("pe_oi_change" not in row for row in data["strikes"])
        assert all("ce_oi_change" not in row for row in data["profile_strikes"])
        assert all("pe_oi_change" not in row for row in data["profile_strikes"])
        assert data["futures_ohlcv"] == []

    def test_vol_surface_attempts_openalgo_without_a_connected_registry(self, app, client):
        openalgo = TestLiveOptionChain._FakeOpenAlgo()
        app.config["OPENALGO_CLIENT"] = openalgo
        expiry = _future_expiry()

        response, body = _post(
            client,
            "/api/v1/volsurface",
            {"symbol": "NIFTY", "exchange": "NFO", "expiries": [expiry]},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is False
        assert openalgo.chain_calls == [("NIFTY", "NSE_INDEX", expiry)]


class TestLiveRegistryHistory:
    def test_rrg_uses_connected_registry_history_contract(self, app, client):
        registry = _ConnectedRegistry()
        app.config["REGISTRY"] = registry

        resp = client.get("/api/v1/rrg/sectors?tail_length=4")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["is_sample_data"] is False
        assert len(registry.history_calls) >= 4
        account_id, params = registry.history_calls[0]
        assert account_id == "acc-primary"
        assert params["symbol"] == "NIFTY 50"
        assert params["exchange"] == "NSE_INDEX"
        assert params["interval"] == "W"
        assert "start" in params and "end" in params


class TestFiiLongShortRoute:
    """DP1 — FII long/short ratio surface endpoint."""

    _BIAS_LABELS = ("Strongly Long", "Long", "Neutral", "Short", "Strongly Short")

    def test_returns_ratio_surface_sample(self, client, monkeypatch):
        # Force the offline sample path deterministically: no live cache/fetch,
        # independent of any DuckDB cache on the host running the tests.
        class _FailingTracker:
            def __init__(self, *_a, **_k):
                raise RuntimeError("no NSE in tests")

        monkeypatch.setattr(
            "flinttrade_screener.fii_dii.FiiDiiTracker", _FailingTracker
        )

        resp = client.get("/api/v1/screener/fii-long-short")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "success"
        data = body["data"]
        assert data["is_sample_data"] is True
        ratio = data["ratio"]
        assert [s["segment"] for s in ratio["segments"]] == [
            "index_futures",
            "stock_futures",
            "index_calls",
            "index_puts",
        ]
        assert "futures_bias" in ratio
        assert ratio["bias_label"] in self._BIAS_LABELS

    def test_returns_ratio_surface_from_cache(self, client, monkeypatch):
        # A live-ish path: tracker yields a cached snapshot → not sample data.
        from flinttrade_screener.fii_dii import make_sample_fii_dii

        class _CachedTracker:
            def __init__(self, *_a, **_k):
                pass

            def get_latest_cached(self):
                return make_sample_fii_dii()

            def fetch_latest(self):  # pragma: no cover - cache hit wins
                return make_sample_fii_dii()

            def close(self):
                pass

        monkeypatch.setattr(
            "flinttrade_screener.fii_dii.FiiDiiTracker", _CachedTracker
        )

        resp = client.get("/api/v1/screener/fii-long-short")

        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["is_sample_data"] is False
        assert data["ratio"]["bias_label"] in self._BIAS_LABELS


class TestGammaDensityRoute:
    """DP2 — gamma density surface endpoint."""

    def test_returns_density_surface_sample(self, client):
        resp, body = _post(
            client, "/api/v1/gammadensity", {"symbol": "NIFTY", "exchange": "NFO"}
        )

        assert resp.status_code == 200
        assert body["status"] == "success"
        assert body["is_sample_data"] is True
        data = body["data"]
        assert data["underlying"] == "NIFTY"
        assert len(data["strikes"]) > 0
        # Both convexity-zone bands present; to-expiry wider than intraday.
        assert data["expiry_band"]["sigma_move"] >= data["intraday_band"]["sigma_move"]
        # Every strike carries both horizon densities.
        first = data["strikes"][0]
        assert "density_intraday" in first
        assert "density_expiry" in first

    def test_sample_density_uses_the_requested_expiry_dte(self, client):
        expiry = _future_expiry(43)

        response, body = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert response.status_code == 200
        assert body["is_sample_data"] is True
        assert body["expiry"] == expiry
        assert body["data"]["dte_days"] == 43.0

    def test_omitted_density_expiry_is_a_generated_future_date(self, client):
        response, body = _post(client, "/api/v1/gammadensity", {})

        assert response.status_code == 200
        parsed = date.fromisoformat(body["expiry"])
        assert parsed > date.today()
        assert body["data"]["dte_days"] == float((parsed - date.today()).days)

    def test_omitted_expiry_does_not_trigger_an_invented_live_read(self, app, client):
        registry = _PayloadRegistry(_chain_payload())
        app.config["REGISTRY"] = registry
        app.config["OPENALGO_CLIENT"] = None

        response, payload = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO"},
        )

        assert response.status_code == 200
        assert payload["is_sample_data"] is True
        assert payload["data"]["dte_days"] == 7.0
        assert registry.chain_calls == []

    @pytest.mark.parametrize(
        "expiry",
        ["not-an-expiry", "2020-01-01", pytest.param("today", id="same-day-expiry")],
    )
    def test_invalid_expiry_is_rejected_before_live_read(self, app, client, expiry):
        from datetime import date

        registry = _PayloadRegistry(_chain_payload())
        app.config["REGISTRY"] = registry
        app.config["OPENALGO_CLIENT"] = None
        body = {
            "symbol": "NIFTY",
            "exchange": "NFO",
            "expiry": date.today().isoformat() if expiry == "today" else expiry,
        }

        response, payload = _post(client, "/api/v1/gammadensity", body)

        assert response.status_code == 400
        assert payload["status"] == "error"
        assert registry.chain_calls == []

    def test_live_gamma_density_uses_authoritative_future_dte(self, app, client):
        from datetime import date, timedelta

        registry = _PayloadRegistry(_chain_payload())
        app.config["REGISTRY"] = registry
        app.config["OPENALGO_CLIENT"] = None
        expiry = (date.today() + timedelta(days=9)).isoformat()

        response, payload = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert response.status_code == 200
        assert payload["is_sample_data"] is False
        assert payload["data"]["dte_days"] == 9.0

    @pytest.mark.parametrize("expiry", ["", "not-a-date"])
    def test_unparseable_expiry_never_labels_live_density(self, app, client, expiry):
        app.config["OPENALGO_CLIENT"] = None
        app.config["REGISTRY"] = _PayloadRegistry(_chain_payload())

        resp, body = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert resp.status_code == 400
        assert body["status"] == "error"

    @pytest.mark.parametrize("day_offset", [-1, 0])
    def test_non_future_expiry_never_labels_live_density(self, app, client, day_offset):
        from datetime import date, timedelta

        app.config["OPENALGO_CLIENT"] = None
        app.config["REGISTRY"] = _PayloadRegistry(_chain_payload())
        expiry = (date.today() + timedelta(days=day_offset)).isoformat()

        response, body = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert response.status_code == 400
        assert body["status"] == "error"

    def test_future_expiry_uses_exact_live_horizon(self, app, client):
        from datetime import date, timedelta

        app.config["OPENALGO_CLIENT"] = None
        app.config["REGISTRY"] = _PayloadRegistry(_chain_payload())
        expiry = (date.today() + timedelta(days=12)).isoformat()

        _, body = _post(
            client,
            "/api/v1/gammadensity",
            {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry},
        )

        assert body["is_sample_data"] is False
        assert body["data"]["dte_days"] == 12.0

    @pytest.mark.parametrize("value", ["garbage", "nan", float("nan"), float("inf"), True])
    def test_invalid_interest_rate_returns_controlled_400(self, client, value):
        response, body = _post(
            client,
            "/api/v1/gammadensity",
            {"interest_rate": value, "expiry": _future_expiry()},
        )

        assert response.status_code == 400
        assert body["status"] == "error"
        assert "NaN" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ("/api/v1/volsurface", "strike_count", "garbage"),
        ("/api/v1/volsurface", "strike_count", float("nan")),
        ("/api/v1/volsurface", "strike_count", 0),
        ("/api/v1/oiprofile", "strike_count", "garbage"),
        ("/api/v1/oiprofile", "strike_count", float("inf")),
        ("/api/v1/oiprofile", "strike_count", -1),
    ],
)
def test_invalid_numeric_analysis_request_returns_controlled_400(client, path, field, value):
    request_body = {field: value, "expiry": _future_expiry()}
    if path == "/api/v1/volsurface":
        request_body["expiries"] = [_future_expiry()]

    response, body = _post(client, path, request_body)

    assert response.status_code == 400
    assert body["status"] == "error"
    assert "NaN" not in response.get_data(as_text=True)


class TestSecondAdversarialChainAdmission:
    """Regression coverage for bounded, expiry-attested whole-chain reads."""

    _CHAIN_PATHS = (
        "/api/v1/gex",
        "/api/v1/gammadensity",
        "/api/v1/volsurface",
        "/api/v1/ivsmile",
        "/api/v1/oiprofile",
        "/api/v1/maxpain",
    )

    @staticmethod
    def _request_body(path: str, expiry: str) -> dict:
        body = {"symbol": "NIFTY", "exchange": "NFO", "expiry": expiry}
        if path == "/api/v1/volsurface":
            body["expiries"] = [expiry]
        return body

    def test_vol_surface_sorts_live_strikes_without_detaching_values(self):
        from flinttrade_screener.analysis_routes import _chain_to_vol_surface_format

        rows = [
            {"strike_price": 24200, "ce_ltp": 21, "pe_ltp": 221, "ce_iv": 24, "pe_iv": 25},
            {"strike_price": 23800, "ce_ltp": 223, "pe_ltp": 23, "ce_iv": 14, "pe_iv": 15},
            {"strike_price": 24000, "ce_ltp": 120, "pe_ltp": 110, "ce_iv": 19, "pe_iv": 20},
        ]

        converted = _chain_to_vol_surface_format(
            {"strikes": rows},
            24000.0,
            days_to_expiry=30,
        )

        assert [row["strike"] for row in converted["strikes"]] == [23800.0, 24000.0, 24200.0]
        assert [(row["ce_ltp"], row["ce_iv"]) for row in converted["strikes"]] == [
            (223.0, 14.0),
            (120.0, 19.0),
            (21.0, 24.0),
        ]

    @pytest.mark.parametrize("path", _CHAIN_PATHS)
    def test_duplicate_strikes_reject_the_entire_live_chain(self, app, client, path):
        expiry = _future_expiry()
        payload = _chain_payload()
        payload["strikes"].append({**payload["strikes"][0]})
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        app.config["OPENALGO_CLIENT"] = None

        response, body = _post(client, path, self._request_body(path, expiry))

        assert response.status_code == 200
        assert body["is_sample_data"] is True

    @pytest.mark.parametrize("path", _CHAIN_PATHS)
    def test_contradictory_index_venue_is_rejected_before_any_live_read(self, app, client, path):
        registry = _PayloadRegistry(_chain_payload())
        app.config["REGISTRY"] = registry
        expiry = _future_expiry()
        body = self._request_body(path, expiry)
        body.update({"symbol": "SENSEX", "exchange": "NFO"})

        response, payload = _post(client, path, body)

        assert response.status_code == 400
        assert payload["status"] == "error"
        assert registry.chain_calls == []

    @pytest.mark.parametrize("path", _CHAIN_PATHS)
    @pytest.mark.parametrize("expiry", ["", "9999-12-31"])
    def test_unusable_expiry_never_publishes_connected_chain_as_live(self, app, client, path, expiry):
        registry = _PayloadRegistry(_chain_payload())
        app.config["REGISTRY"] = registry
        app.config["OPENALGO_CLIENT"] = None

        response, body = _post(client, path, self._request_body(path, expiry))

        if path in {"/api/v1/volsurface", "/api/v1/gammadensity"}:
            assert response.status_code == 400
            assert body["status"] == "error"
        else:
            assert response.status_code == 200
            assert body["is_sample_data"] is True
            assert body["expiry"] == expiry
        assert registry.chain_calls == []

    @pytest.mark.parametrize("path", _CHAIN_PATHS)
    def test_non_object_json_returns_controlled_400(self, client, path):
        response = client.post(path, data="[]", content_type="application/json")

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"

    @pytest.mark.parametrize("path", _CHAIN_PATHS)
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("symbol", 123),
            ("exchange", ["NFO"]),
            ("expiry", {"date": "2099-01-01"}),
        ],
    )
    def test_non_string_chain_identity_returns_controlled_400(self, client, path, field, value):
        expiry = _future_expiry()
        body = self._request_body(path, expiry)
        body[field] = value
        if path == "/api/v1/volsurface" and field == "expiry":
            body["expiries"] = [value]

        response = client.post(path, json=body)

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"

    @pytest.mark.parametrize(
        ("path", "payload_mutator"),
        [
            ("/api/v1/gex", lambda payload: payload["strikes"][0].__setitem__("ce_gamma", 1e308)),
            ("/api/v1/gex", lambda payload: payload.__setitem__("lot_size", 10**100)),
            ("/api/v1/oiprofile", lambda payload: payload["strikes"][0].__setitem__("ce_oi", 10**100)),
            ("/api/v1/volsurface", lambda payload: payload["strikes"][0].__setitem__("ce_ltp", 1e308)),
        ],
    )
    def test_extreme_finite_chain_observations_are_not_published_live(
        self,
        app,
        client,
        path,
        payload_mutator,
    ):
        expiry = _future_expiry()
        payload = _chain_payload()
        payload_mutator(payload)
        app.config["REGISTRY"] = _PayloadRegistry(payload)
        app.config["OPENALGO_CLIENT"] = None

        response, body = _post(client, path, self._request_body(path, expiry))

        assert response.status_code == 200
        assert body["is_sample_data"] is True
        assert "Infinity" not in response.get_data(as_text=True)
        assert "NaN" not in response.get_data(as_text=True)

    def test_low_spot_sample_strikes_are_positive_and_regular(self):
        from flinttrade_screener.analysis_routes import _make_sample_strikes

        strikes = [row.strike_price for row in _make_sample_strikes(spot=1.0, step=100.0)]
        steps = [right - left for left, right in zip(strikes, strikes[1:])]

        assert min(strikes) > 0
        assert len(set(strikes)) == len(strikes)
        assert all(step > 0 for step in steps)
        assert max(steps) == pytest.approx(min(steps))


class TestArbitrageScanRoute:
    """DP3 — cash-future / cross-exchange arbitrage scanner endpoint."""

    def test_sample_scan_when_no_rows(self, client):
        resp, body = _post(client, "/api/v1/screener/arbitrage", {})

        assert resp.status_code == 200
        assert body["status"] == "success"
        data = body["data"]
        assert data["is_sample_data"] is True
        assert len(data["scan"]["cash_future"]) > 0
        assert len(data["scan"]["cross_exchange"]) > 0

    @pytest.mark.parametrize("value", ["nan", float("nan"), float("inf"), True, 1e308])
    def test_rejects_non_finite_or_extreme_numeric_inputs(self, client, value):
        response = client.post("/api/v1/screener/arbitrage", json={"risk_free_rate": value})

        assert response.status_code == 400
        assert response.get_json()["status"] == "error"

    def test_rejects_non_object_json(self, client):
        response = client.post(
            "/api/v1/screener/arbitrage",
            data="[]",
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_scans_supplied_rows(self, client):
        resp, body = _post(client, "/api/v1/screener/arbitrage", {
            "cash_future": [
                {"underlying": "NIFTY", "spot": 24000.0, "future_price": 24120.0, "days_to_expiry": 5},
            ],
        })

        assert resp.status_code == 200
        data = body["data"]
        assert data["is_sample_data"] is False
        opp = data["scan"]["cash_future"][0]
        assert opp["underlying"] == "NIFTY"
        assert opp["signal"] == "cash_and_carry"


class TestCandlestickPatternsRoute:
    """W4 — candlestick pattern detection endpoint."""

    def test_sample_scan_when_no_bars(self, client):
        resp, body = _post(client, "/api/v1/candlestick-patterns", {})
        assert resp.status_code == 200
        assert body["status"] == "success"
        data = body["data"]
        assert data["is_sample_data"] is True
        assert len(data["scan"]["matches"]) > 0

    def test_rejects_non_object_json(self, client):
        response = client.post(
            "/api/v1/candlestick-patterns",
            data="[]",
            content_type="application/json",
        )

        assert response.status_code == 400

    def test_detects_supplied_bars(self, client):
        resp, body = _post(client, "/api/v1/candlestick-patterns", {
            "bars": [
                {"time": "1", "open": 100.5, "high": 101, "low": 99.5, "close": 99.8},
                {"time": "2", "open": 99.5, "high": 102, "low": 99.4, "close": 101.8},
            ],
        })
        assert resp.status_code == 200
        data = body["data"]
        assert data["is_sample_data"] is False
        patterns = {m["pattern"] for m in data["scan"]["matches"]}
        assert "bullish_engulfing" in patterns
