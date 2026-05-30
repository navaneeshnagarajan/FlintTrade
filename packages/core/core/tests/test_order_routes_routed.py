"""T7 (gap G5): the selector-bound, safety-gated /api/v1/orders/<broker>/place route.

A focused test of the new route's auth + routing-availability gates on a minimal
Flask app (no full create_flask_app). Full live dispatch is exercised once a
broker adapter is registered behind the router.
"""

from __future__ import annotations

from flask import Flask

from flinttrade_core.order_routes import orders_bp


def _app(broker_router: object | None = None) -> Flask:
    app = Flask(__name__)
    app.config["BROKER_ROUTER"] = broker_router
    app.register_blueprint(orders_bp)
    return app


def test_routed_order_requires_auth() -> None:
    client = _app().test_client()
    resp = client.post("/api/v1/orders/dhan/place", json={"symbol": "RELIANCE"})
    assert resp.status_code == 401


def test_routed_order_route_is_registered() -> None:
    rules = {r.rule for r in _app().url_map.iter_rules()}
    assert "/api/v1/orders/<broker>/place" in rules
