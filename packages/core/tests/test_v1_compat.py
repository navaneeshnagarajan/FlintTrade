"""Tests for packages.core.src.v1_compat.

Covers:
- V1CompatLayer.translate_request(): path mapping, payload key translation,
  unknown path pass-through, action value normalisation
- V1CompatLayer.translate_response(): wrap-required paths, already-wrapped
  response, pass-through for non-wrap paths
- V1CompatLayer.is_v1_path(): known and unknown paths
- V1CompatLayer.deprecated_paths(): only renamed paths returned
- V1CompatLayer._translate_payload(): action → transaction_type, value casing,
  non-action keys preserved, no mutation of original dict
- register_v1_compat(): Flask middleware registration (before/after request hooks)
"""

from __future__ import annotations



from packages.core.src.v1_compat import V1CompatLayer, register_v1_compat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compat() -> V1CompatLayer:
    return V1CompatLayer()


# ---------------------------------------------------------------------------
# translate_request() — path mapping
# ---------------------------------------------------------------------------


class TestTranslateRequestPath:
    def test_orderbook_mapped(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/orderbook", {})
        assert path == "/api/v1/orders"

    def test_positionbook_mapped(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/positionbook", {})
        assert path == "/api/v1/positions"

    def test_tradebook_mapped(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/tradebook", {})
        assert path == "/api/v1/trades"

    def test_holdings_unchanged(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/holdings", {})
        assert path == "/api/v1/holdings"

    def test_funds_unchanged(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/funds", {})
        assert path == "/api/v1/funds"

    def test_unknown_path_passed_through(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/unknown_endpoint", {"key": "val"})
        assert path == "/api/v1/unknown_endpoint"

    def test_placeorder_path_unchanged(self) -> None:
        c = _compat()
        path, _ = c.translate_request("/api/v1/placeorder", {})
        assert path == "/api/v1/placeorder"


# ---------------------------------------------------------------------------
# translate_request() — payload translation
# ---------------------------------------------------------------------------


class TestTranslateRequestPayload:
    def test_action_renamed_to_transaction_type(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {"action": "buy"})
        assert "transaction_type" in body
        assert "action" not in body

    def test_action_buy_uppercased(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {"action": "buy"})
        assert body["transaction_type"] == "BUY"

    def test_action_sell_uppercased(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {"action": "sell"})
        assert body["transaction_type"] == "SELL"

    def test_action_already_uppercase_preserved(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {"action": "BUY"})
        assert body["transaction_type"] == "BUY"

    def test_other_keys_preserved(self) -> None:
        c = _compat()
        _, body = c.translate_request(
            "/api/v1/placeorder",
            {"action": "buy", "symbol": "NIFTY", "quantity": 50},
        )
        assert body["symbol"] == "NIFTY"
        assert body["quantity"] == 50

    def test_empty_body_unchanged(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {})
        assert body == {}

    def test_original_dict_not_mutated(self) -> None:
        c = _compat()
        original = {"action": "buy", "qty": 10}
        c.translate_request("/api/v1/placeorder", original)
        assert "action" in original
        assert "transaction_type" not in original

    def test_unknown_action_value_uppercased(self) -> None:
        c = _compat()
        _, body = c.translate_request("/api/v1/placeorder", {"action": "hold"})
        assert body["transaction_type"] == "HOLD"


# ---------------------------------------------------------------------------
# translate_response()
# ---------------------------------------------------------------------------


class TestTranslateResponse:
    def test_orderbook_wraps_response(self) -> None:
        c = _compat()
        v2 = {"status": "success", "orders": []}
        v1 = c.translate_response("/api/v1/orderbook", v2)
        assert "data" in v1
        assert v1["data"] == v2

    def test_positionbook_wraps_response(self) -> None:
        c = _compat()
        v2 = {"positions": []}
        v1 = c.translate_response("/api/v1/positionbook", v2)
        assert "data" in v1

    def test_already_wrapped_response_not_double_wrapped(self) -> None:
        c = _compat()
        v2 = {"data": {"orders": []}, "status": "success"}
        v1 = c.translate_response("/api/v1/orderbook", v2)
        assert "data" in v1
        # Must not have data.data
        assert not isinstance(v1.get("data"), dict) or "data" not in v1["data"]

    def test_non_wrap_path_passes_through(self) -> None:
        c = _compat()
        v2 = {"result": "ok"}
        v1 = c.translate_response("/api/v1/placeorder", v2)
        assert v1 is v2

    def test_status_preserved_in_wrapped(self) -> None:
        c = _compat()
        v2 = {"status": "success", "data_key": "val"}
        v1 = c.translate_response("/api/v1/holdings", v2)
        assert v1["status"] == "success"

    def test_unknown_path_passes_through(self) -> None:
        c = _compat()
        v2 = {"foo": "bar"}
        v1 = c.translate_response("/api/v1/no_such_endpoint", v2)
        assert v1 is v2


# ---------------------------------------------------------------------------
# is_v1_path()
# ---------------------------------------------------------------------------


class TestIsV1Path:
    def test_known_path_returns_true(self) -> None:
        c = _compat()
        assert c.is_v1_path("/api/v1/orderbook") is True

    def test_unknown_path_returns_false(self) -> None:
        c = _compat()
        assert c.is_v1_path("/api/v2/orders") is False

    def test_placeorder_is_v1(self) -> None:
        c = _compat()
        assert c.is_v1_path("/api/v1/placeorder") is True


# ---------------------------------------------------------------------------
# deprecated_paths()
# ---------------------------------------------------------------------------


class TestDeprecatedPaths:
    def test_only_renamed_paths_returned(self) -> None:
        c = _compat()
        deprecated = c.deprecated_paths()
        for path in deprecated:
            v2 = V1CompatLayer.V1_TO_V2_ROUTES[path]
            assert path != v2, f"{path} maps to itself — should not be in deprecated_paths()"

    def test_orderbook_in_deprecated(self) -> None:
        c = _compat()
        assert "/api/v1/orderbook" in c.deprecated_paths()

    def test_result_is_sorted(self) -> None:
        c = _compat()
        deprecated = c.deprecated_paths()
        assert deprecated == sorted(deprecated)


# ---------------------------------------------------------------------------
# register_v1_compat() — Flask middleware
# ---------------------------------------------------------------------------


class TestRegisterV1Compat:
    def test_registers_on_flask_app(self) -> None:
        """register_v1_compat attaches V1CompatLayer to app.config."""
        from flask import Flask

        app = Flask(__name__)
        register_v1_compat(app)
        assert "V1_COMPAT" in app.config
        assert isinstance(app.config["V1_COMPAT"], V1CompatLayer)

    def test_before_request_hook_registered(self) -> None:
        """before_request hook is present after registration."""
        from flask import Flask

        app = Flask(__name__)
        register_v1_compat(app)
        # Flask stores before_request_funcs keyed by blueprint name (None = global)
        hooks = app.before_request_funcs.get(None, [])
        assert len(hooks) >= 1

    def test_after_request_hook_registered(self) -> None:
        """after_request hook is present after registration."""
        from flask import Flask

        app = Flask(__name__)
        register_v1_compat(app)
        hooks = app.after_request_funcs.get(None, [])
        assert len(hooks) >= 1

    def test_compat_header_added_for_v1_path(self) -> None:
        """Responses for v1 paths include X-FlintTrade-Compat header."""
        from flask import Flask, jsonify

        app = Flask(__name__)
        register_v1_compat(app)

        @app.get("/api/v1/orderbook")
        def _orderbook():
            return jsonify({"status": "success", "orders": []})

        with app.test_client() as client:
            resp = client.get("/api/v1/orderbook")
        assert resp.headers.get("X-FlintTrade-Compat") == "v1"

    def test_non_v1_path_no_compat_header(self) -> None:
        """Responses for non-v1 paths do NOT include the compat header."""
        from flask import Flask, jsonify

        app = Flask(__name__)
        register_v1_compat(app)

        @app.get("/api/v2/orders")
        def _orders():
            return jsonify({"orders": []})

        with app.test_client() as client:
            resp = client.get("/api/v2/orders")
        assert "X-FlintTrade-Compat" not in resp.headers
