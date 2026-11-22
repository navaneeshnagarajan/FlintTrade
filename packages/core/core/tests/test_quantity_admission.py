"""Order admission refuses a bad lot multiple or a freeze-quantity breach."""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_core import order_routes


@pytest.fixture
def app_context():
    app = Flask(__name__)
    with app.app_context():
        yield


@pytest.mark.unit
def test_admit_place_refuses_before_laya(monkeypatch: pytest.MonkeyPatch, app_context: None) -> None:
    def _laya_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Laya ran after a freeze refusal")

    monkeypatch.setattr(order_routes, "_laya_place_response", _laya_must_not_run)
    blocked, qualified = order_routes._admit_place(
        {
            "symbol": "NIFTY 24500 CE",
            "exchange": "NFO",
            "action": "BUY",
            "quantity": 3575,
            "lot_size": 65,
            "product": "MIS",
        },
        mode="practice",
        live=False,
        positions=[],
        our_orders=[],
        broker_orders=[],
    )
    assert qualified is False
    assert blocked is not None
    response, status = blocked
    assert status == 400
    body = response.get_json()
    assert body["code"] == "quantity_admission"
    assert body["message"] == "Max 1,755 per order for NIFTY. Place smaller orders."


@pytest.mark.unit
def test_admit_place_accepts_a_quantity_at_the_freeze_limit(app_context: None) -> None:
    assert order_routes._quantity_admission_response(
        {
            "symbol": "BANKNIFTY",
            "exchange": "NFO",
            "quantity": 900,
            "lot_size": 30,
        }
    ) is None


@pytest.mark.unit
def test_admit_place_uses_the_broker_freeze_quantity(app_context: None) -> None:
    blocked = order_routes._quantity_admission_response(
        {
            "symbol": "RELIANCE26APRFUT",
            "exchange": "NFO",
            "quantity": 500,
            "lot_size": 250,
            "freeze_qty": "250",
        }
    )
    assert blocked is not None
    response, status = blocked
    assert status == 400
    assert response.get_json()["message"] == (
        "Max 250 per order for RELIANCE. Place smaller orders."
    )


@pytest.mark.unit
def test_unverified_sensex_limit_warns_and_lets_the_order_continue(
    app_context: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        blocked = order_routes._quantity_admission_response(
            {"symbol": "SENSEX26DEC85000CE", "exchange": "BFO", "quantity": 1_020, "lot_size": 20}
        )
    assert blocked is None
    assert "Max per order for SENSEX may be 1,000 qty. Split if the broker rejects." in caplog.text


@pytest.mark.unit
def test_broker_freeze_for_sensex_still_refuses(app_context: None) -> None:
    blocked = order_routes._quantity_admission_response(
        {"symbol": "SENSEX26DEC85000CE", "exchange": "BFO", "quantity": 1_020, "lot_size": 20, "freeze_qty": 1_000}
    )
    assert blocked is not None
    response, status = blocked
    assert status == 400
    assert response.get_json()["message"] == "Max 1,000 per order for SENSEX. Place smaller orders."
