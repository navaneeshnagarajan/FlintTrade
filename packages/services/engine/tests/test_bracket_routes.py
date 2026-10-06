"""Tests for ``flinttrade_engine.bracket_routes`` (Flask Blueprint).

Covers POST /api/v1/orders/bracket (place), GET /api/v1/orders/brackets (list),
and DELETE /api/v1/orders/bracket/<id> (cancel) — happy and error paths, plus
the route-level OCO-honesty refusals (422 ``oco_unsupported`` /
``trailing_unsupported``), the principal derivation (JWT identity + broker
target resolution), and the ``require_live_unlocked`` mode-guard fan-out.

The mode guard is bypassed when ``app.config["TESTING"] = True``, so most
tests need no JWT minting; the guard tests build an app with
``TESTING=False`` and mint real tokens with a pinned JWT secret (mirroring
``test_mode_guard.py``).
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask, request

from flinttrade_engine.bracket_order import BracketOrderError, BracketOrderService, BracketPrincipal

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _laya_ready() -> None:
    """Single-exit brackets admit through Laya before the service places them."""
    from flinttrade_engine.laya import DecisionStatus, process_laya, reset_process_laya_for_tests

    reset_process_laya_for_tests()
    process_laya().set_status(DecisionStatus.READY)
    yield
    reset_process_laya_for_tests()

_JWT_SECRET = "test-secret-for-bracket-routes-hs256"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENTRY = {
    "symbol": "NIFTY25APRFUT",
    "exchange": "NFO",
    "action": "BUY",
    "quantity": 50,
    "price": 0,
    "strategy": "Flint",
    "product": "MIS",
}

# Exactly ONE protective exit leg — the supported bracket shape today.
_BRACKET_BODY = {
    "entry": _ENTRY,
    "stoploss": 22000.0,
}


def _make_service(success: bool = True, bracket_id: str = "br-001") -> MagicMock:
    """Build a mock BracketOrderService.

    Args:
        success:    Whether place_bracket should return success.
        bracket_id: UUID to attach to mock bracket objects.

    Returns:
        Configured MagicMock.
    """
    svc = MagicMock()
    bracket = MagicMock()
    bracket.bracket_id = bracket_id
    bracket.to_dict.return_value = {"bracket_id": bracket_id, "status": "active"}

    result = MagicMock()
    result.success = success
    result.message = "OK" if success else "Rejected"
    result.error = "" if success else "validation_error"
    result.bracket = bracket if success else None
    svc.place_bracket.return_value = result

    svc.get_active_brackets.return_value = [bracket] if success else []
    svc.get_bracket.return_value = bracket if success else None
    svc.cancel_bracket.return_value = success
    return svc


def _make_app(svc: BracketOrderService | MagicMock | None, testing: bool = True) -> Flask:
    """Build a Flask app with the bracket blueprint registered.

    Args:
        svc:     The (mock) bracket service, or ``None`` to leave it unset.
        testing: Whether to enable the TESTING mode-guard bypass.

    Returns:
        Configured Flask app.
    """
    from flinttrade_engine.bracket_routes import bracket_bp

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = testing
    if svc is not None:
        flask_app.config["BRACKET_SERVICE"] = svc
    flask_app.config["BROKER_ROUTER"] = SimpleNamespace(default_selector="dhan:default")
    flask_app.register_blueprint(bracket_bp)
    return flask_app


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def service() -> MagicMock:
    """A fresh success-mode mock service."""
    return _make_service()


@pytest.fixture()
def client(service):
    """Flask test client with a mock BracketOrderService configured.

    Yields:
        Flask test client.
    """
    with _make_app(service).test_client() as c:
        yield c


@pytest.fixture()
def client_no_service():
    """Flask test client without BRACKET_SERVICE (simulates unconfigured state).

    Yields:
        Flask test client.
    """
    with _make_app(None).test_client() as c:
        yield c


@pytest.fixture()
def pinned_jwt_secret(monkeypatch) -> str:
    """Pin the JWT secret so token minting and decoding stay in sync.

    Returns:
        The pinned secret.
    """
    monkeypatch.setenv("JWT_SECRET", _JWT_SECRET)
    import flinttrade_core.auth_routes as auth_mod

    monkeypatch.setattr(auth_mod, "_JWT_SECRET_KEY", _JWT_SECRET)
    return _JWT_SECRET


@pytest.fixture()
def guarded_client(service, pinned_jwt_secret):
    """Test client with ``TESTING=False`` so ``require_live_unlocked`` applies.

    Yields:
        Flask test client.
    """
    with _make_app(service, testing=False).test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/v1/orders/bracket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,endpoint", [("POST", "/bracket"), ("DELETE", "/bracket/br-001")])
@pytest.mark.parametrize("raw_body", ["[]", "[1]", "null", '"text"', "false", "0", "{not json"])
def test_bracket_body_must_be_a_json_object(client, service, method, endpoint, raw_body) -> None:
    response = client.open(
        f"/api/v1/orders{endpoint}", method=method, data=raw_body, content_type="application/json"
    )
    assert response.status_code == 400
    assert "JSON object" in response.get_json()["message"]
    service.place_bracket.assert_not_called()
    service.cancel_bracket.assert_not_called()


class TestPlaceBracket:
    def test_place_success_returns_201(self, client, service) -> None:
        """A valid stop-loss bracket is admitted and placed.

        Args:
            client: Flask test client.
            service: Mock service backing the client.
        """
        resp = client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert "bracket_id" in data["data"]
        service.place_bracket.assert_called_once()

    def test_place_with_target_only_returns_201(self, client, service) -> None:
        """A target-only exit leg is the other supported bracket shape.

        Args:
            client: Flask test client.
            service: Mock service backing the client.
        """
        resp = client.post(
            "/api/v1/orders/bracket", json={"entry": _ENTRY, "target": 22500.0}
        )
        assert resp.status_code == 201
        service.place_bracket.assert_called_once()
        assert service.place_bracket.call_args.kwargs["target"] == 22500.0

    def test_gtt_variety_is_refused_before_the_service(self, client, service) -> None:
        """GTT is refused before Laya admission reaches the bracket service."""
        resp = client.post(
            "/api/v1/orders/bracket",
            json={**_BRACKET_BODY, "variety": "G.T.T"},
        )
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "gtt_unsupported"
        assert resp.get_json()["message"] == "Not placed. GTT orders aren't supported right now."
        service.place_bracket.assert_not_called()

    def test_broker_held_variety_is_refused(self, client, service) -> None:
        """A broker-held super or forever variety does not place legs."""
        resp = client.post(
            "/api/v1/orders/bracket",
            json={**_BRACKET_BODY, "entry": {**_ENTRY, "variety": "super"}},
        )
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "broker_held_unsupported"
        service.place_bracket.assert_not_called()

    def test_conflicting_entry_types_are_rejected_before_admission(self, client, service, monkeypatch) -> None:
        from flinttrade_engine.laya import process_laya

        admit = MagicMock(wraps=process_laya().admit)
        monkeypatch.setattr(process_laya(), "admit", admit)
        response = client.post(
            "/api/v1/orders/bracket",
            json={**_BRACKET_BODY, "entry": {**_ENTRY, "order_type": "LIMIT", "pricetype": "MARKET", "price": 100}},
        )
        assert response.status_code == 400
        admit.assert_not_called()
        service.place_bracket.assert_not_called()

    @pytest.mark.parametrize("type_fields", [
        {"order_type": " limit ", "pricetype": "LIMIT"},
        {"order_type": "LIMIT", "pricetype": " limit "},
        {"order_type": "limit"},
        {"pricetype": "limit"},
    ])
    def test_entry_aliases_agree_for_admission_and_service(self, client, service, monkeypatch, type_fields) -> None:
        from flinttrade_engine.laya import process_laya

        admit = MagicMock(wraps=process_laya().admit)
        monkeypatch.setattr(process_laya(), "admit", admit)
        response = client.post(
            "/api/v1/orders/bracket",
            json={**_BRACKET_BODY, "entry": {**_ENTRY, **type_fields, "price": 100}},
        )
        assert response.status_code == 201, response.get_json()
        assert admit.call_args_list[0].args[0].order_type == "LIMIT"
        assert service.place_bracket.call_args.args[0]["pricetype"] == "LIMIT"

    @pytest.mark.parametrize("price,expected", [(0, "MARKET"), ("0", "MARKET"), (100, "LIMIT")])
    def test_entry_default_type_agrees_with_service(self, client, service, monkeypatch, price, expected) -> None:
        from flinttrade_engine.laya import process_laya

        admit = MagicMock(wraps=process_laya().admit)
        monkeypatch.setattr(process_laya(), "admit", admit)
        response = client.post(
            "/api/v1/orders/bracket", json={**_BRACKET_BODY, "entry": {**_ENTRY, "price": price}}
        )
        assert response.status_code == 201, response.get_json()
        forwarded = service.place_bracket.call_args.args[0]
        service_type = forwarded.get("pricetype", "MARKET" if float(forwarded["price"]) == 0 else "LIMIT")
        assert admit.call_args_list[0].args[0].order_type == service_type == expected

    @pytest.mark.integration
    @pytest.mark.parametrize(
        "type_fields",
        [
            {},
            {"order_type": ""},
            {"order_type": None},
            {"pricetype": ""},
            {"pricetype": None},
            {"order_type": "", "pricetype": None},
            {"order_type": None, "pricetype": ""},
            {"order_type": " ", "pricetype": "\t"},
        ],
    )
    @pytest.mark.parametrize("price,expected", [(0, "MARKET"), ("0", "MARKET"), (100, "LIMIT")])
    def test_empty_entry_aliases_match_real_service_defaults_without_mutating_body(
        self, monkeypatch, pinned_jwt_secret, type_fields, price, expected
    ) -> None:
        from flinttrade_core.auth_routes import _create_token
        from flinttrade_engine.laya import process_laya

        place_leg = MagicMock(side_effect=["ENTRY-1", "EXIT-1"])
        service = BracketOrderService(place_leg=place_leg)
        app = _make_app(service, testing=False)
        decoded_bodies = []

        @app.before_request
        def capture_body():
            body = request.get_json()
            decoded_bodies.append((body, deepcopy(body)))

        admit = MagicMock(wraps=process_laya().admit)
        monkeypatch.setattr(process_laya(), "admit", admit)
        token = _create_token("operator", mode="live", live_mode_unlocked=True)
        response = app.test_client().post(
            "/api/v1/orders/bracket",
            json={"entry": {**_ENTRY, **type_fields, "price": price}, "stoploss": 90},
            headers=_bearer(token),
        )

        assert response.status_code == 201, response.get_json()
        assert [call.args[0].order_type for call in admit.call_args_list] == [expected, "SL"]
        assert place_leg.call_count == 2
        assert [call.args[0].pricetype.value for call in place_leg.call_args_list] == [expected, "SL"]
        bracket = service.get_bracket(response.get_json()["data"]["bracket_id"])
        assert bracket is not None
        assert bracket.entry_pricetype == expected
        assert bracket.entry_price == float(price)
        original, snapshot = decoded_bodies[0]
        assert original == snapshot

    def test_place_missing_entry_returns_400(self, client) -> None:
        """Missing entry field returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post("/api/v1/orders/bracket", json={"stoploss": 22000.0})
        assert resp.status_code == 400
        assert "entry" in resp.get_json()["message"]

    def test_place_missing_both_exits_returns_400(self, client, service) -> None:
        """Neither stoploss nor target → HTTP 400 before touching the service.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        resp = client.post("/api/v1/orders/bracket", json={"entry": _ENTRY})
        assert resp.status_code == 400
        assert "stoploss" in resp.get_json()["message"]
        service.place_bracket.assert_not_called()

    def test_place_oco_pair_returns_422(self, client, service) -> None:
        """stoploss + target together is refused with ``oco_unsupported``.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        resp = client.post(
            "/api/v1/orders/bracket",
            json={"entry": _ENTRY, "stoploss": 22000.0, "target": 22500.0},
        )
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "oco_unsupported"
        service.place_bracket.assert_not_called()

    def test_place_trailing_sl_returns_422(self, client, service) -> None:
        """trailing_sl is refused with ``trailing_unsupported`` — no fill monitor.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        resp = client.post(
            "/api/v1/orders/bracket",
            json={"entry": _ENTRY, "stoploss": 22000.0, "trailing_sl": 25.0},
        )
        assert resp.status_code == 422
        assert resp.get_json()["code"] == "trailing_unsupported"
        service.place_bracket.assert_not_called()

    def test_place_non_numeric_stoploss_returns_400(self, client) -> None:
        """A non-numeric stoploss returns HTTP 400.

        Args:
            client: Flask test client.
        """
        resp = client.post(
            "/api/v1/orders/bracket", json={"entry": _ENTRY, "stoploss": "lots"}
        )
        assert resp.status_code == 400
        assert "stoploss" in resp.get_json()["message"]

    def test_place_forwards_no_trailing_to_service(self, client, service) -> None:
        """The route always passes ``trailing_sl=None`` to the service.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        kwargs = service.place_bracket.call_args.kwargs
        assert kwargs["trailing_sl"] is None
        assert kwargs["stoploss"] == 22000.0
        assert isinstance(kwargs["principal"], BracketPrincipal)

    def test_place_service_rejection_returns_422(self) -> None:
        """Service-level rejection surfaces as HTTP 422."""
        service = _make_service(success=False)
        with _make_app(service).test_client() as c:
            resp = c.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 422
        assert resp.get_json()["status"] == "error"
        service.place_bracket.assert_called_once()

    def test_place_partial_bracket_surfaces_data(self) -> None:
        """A partial bracket (entry live, exit failed) is included in the 422 body."""
        svc = _make_service(success=False)
        partial = MagicMock()
        partial.to_dict.return_value = {"bracket_id": "br-p1", "status": "partial"}
        svc.place_bracket.return_value.bracket = partial
        svc.place_bracket.return_value.message = "UNPROTECTED"
        with _make_app(svc).test_client() as c:
            resp = c.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 422
        data = resp.get_json()
        assert data["data"]["status"] == "partial"
        assert data["data"]["bracket_id"] == "br-p1"

    def test_no_service_returns_503(self, client_no_service) -> None:
        """Missing BRACKET_SERVICE returns HTTP 503.

        Args:
            client_no_service: Flask test client without service config.
        """
        resp = client_no_service.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Principal derivation (identity from JWT, broker target from body/config)
# ---------------------------------------------------------------------------


class TestPrincipalDerivation:
    def _placed_principal(self, service: MagicMock) -> BracketPrincipal:
        return service.place_bracket.call_args.kwargs["principal"]

    def test_explicit_broker_and_account_win(self, client, service) -> None:
        """Explicit ``broker``/``account_id`` body fields set the principal target.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        client.post(
            "/api/v1/orders/bracket",
            json={**_BRACKET_BODY, "broker": "DHAN", "account_id": "acct-7"},
        )
        principal = self._placed_principal(service)
        assert principal.adapter_id == "dhan"
        assert principal.account_id == "acct-7"

    def test_account_only_requires_explicit_native_adapter(self, client, service) -> None:
        response = client.post("/api/v1/orders/bracket", json={**_BRACKET_BODY, "account_id": "acct-9"})
        assert response.status_code == 503
        service.place_bracket.assert_not_called()

    def test_default_selector_from_router_config(self, service) -> None:
        """Without body fields, ``brokers.execution.default`` sets the target."""
        flask_app = _make_app(service)
        flask_app.config["BROKER_ROUTER"] = SimpleNamespace(default_selector="dhan:acct-live")
        with flask_app.test_client() as c:
            c.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        principal = self._placed_principal(service)
        assert principal.adapter_id == "dhan"
        assert principal.account_id == "acct-live"

    def test_malformed_default_selector_fails_closed(self, service) -> None:
        flask_app = _make_app(service)
        flask_app.config["BROKER_ROUTER"] = SimpleNamespace(default_selector="no-colon-here")
        with flask_app.test_client() as client:
            response = client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert response.status_code == 503
        service.place_bracket.assert_not_called()

    def test_identity_comes_from_session_jwt(self, client, service, pinned_jwt_secret) -> None:
        """actor_id/jti on the principal come from the verified session JWT.

        Args:
            client:            Flask test client.
            service:           Mock service backing the client.
            pinned_jwt_secret: Deterministic JWT secret fixture.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="live", live_mode_unlocked=True)
        client.post("/api/v1/orders/bracket", json=_BRACKET_BODY, headers=_bearer(tok))
        principal = self._placed_principal(service)
        assert principal.actor_id == "alice"
        assert principal.jti

    def test_missing_token_yields_unknown_actor(self, client, service) -> None:
        """Without a decodable JWT (TESTING bypass) the actor is 'unknown'.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        principal = self._placed_principal(service)
        assert principal.actor_id == "unknown"
        assert principal.jti == ""


# ---------------------------------------------------------------------------
# Mode guard (require_live_unlocked) — TESTING=False fan-out
# ---------------------------------------------------------------------------


class TestModeGuard:
    """Both write routes sit behind ``require_live_unlocked``; list does not."""

    def test_place_without_token_returns_401(self, guarded_client) -> None:
        """Missing JWT → 401 ``auth_required``.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        resp = guarded_client.post("/api/v1/orders/bracket", json=_BRACKET_BODY)
        assert resp.status_code == 401
        assert resp.get_json()["code"] == "auth_required"

    def test_place_explore_mode_returns_403(self, guarded_client) -> None:
        """mode=explore → 403 ``mode_blocked``.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="explore")
        resp = guarded_client.post(
            "/api/v1/orders/bracket", json=_BRACKET_BODY, headers=_bearer(tok)
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "mode_blocked"

    def test_place_practice_mode_returns_403(self, guarded_client) -> None:
        """mode=practice → 403 ``practice_unsupported`` — no sandbox bracket parity.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="practice")
        resp = guarded_client.post(
            "/api/v1/orders/bracket", json=_BRACKET_BODY, headers=_bearer(tok)
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "practice_unsupported"

    def test_place_live_locked_returns_403(self, guarded_client) -> None:
        """mode=live without ``live_mode_unlocked`` → 403 ``live_locked``.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="live", live_mode_unlocked=False)
        resp = guarded_client.post(
            "/api/v1/orders/bracket", json=_BRACKET_BODY, headers=_bearer(tok)
        )
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "live_locked"

    def test_place_live_unlocked_passes(self, guarded_client) -> None:
        """mode=live with ``live_mode_unlocked`` → the handler executes (201).

        Args:
            guarded_client: Test client with TESTING=False.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="live", live_mode_unlocked=True)
        resp = guarded_client.post(
            "/api/v1/orders/bracket", json=_BRACKET_BODY, headers=_bearer(tok)
        )
        assert resp.status_code == 201

    def test_cancel_practice_mode_returns_403(self, guarded_client) -> None:
        """DELETE (a live broker write) is guarded exactly like placement.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        from flinttrade_core.auth_routes import _create_token

        tok = _create_token("alice", mode="practice")
        resp = guarded_client.delete("/api/v1/orders/bracket/br-001", headers=_bearer(tok))
        assert resp.status_code == 403
        assert resp.get_json()["code"] == "practice_unsupported"

    def test_list_is_not_mode_guarded(self, guarded_client) -> None:
        """GET /brackets is read-only — reachable without any JWT.

        Args:
            guarded_client: Test client with TESTING=False.
        """
        resp = guarded_client.get("/api/v1/orders/brackets")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/v1/orders/brackets
# ---------------------------------------------------------------------------


class TestListBrackets:
    def test_list_active_brackets(self, client) -> None:
        """Active brackets are returned in a list with count.

        Args:
            client: Flask test client.
        """
        resp = client.get("/api/v1/orders/brackets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 1
        assert len(data["data"]["brackets"]) == 1

    def test_no_service_returns_503(self, client_no_service) -> None:
        """Missing BRACKET_SERVICE returns HTTP 503 on list.

        Args:
            client_no_service: Flask test client without service config.
        """
        resp = client_no_service.get("/api/v1/orders/brackets")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# DELETE /api/v1/orders/bracket/<id>
# ---------------------------------------------------------------------------


class TestCancelBracket:
    def test_cancel_existing_bracket(self, client) -> None:
        """Cancelling an existing bracket returns 200 with success.

        Args:
            client: Flask test client.
        """
        resp = client.delete("/api/v1/orders/bracket/br-001")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_cancel_passes_principal_to_service(self, client, service) -> None:
        """The gated cancel receives a principal derived from the request.

        Args:
            client:  Flask test client.
            service: Mock service backing the client.
        """
        client.delete("/api/v1/orders/bracket/br-001")
        args, kwargs = service.cancel_bracket.call_args
        assert args[0] == "br-001"
        assert isinstance(kwargs["principal"], BracketPrincipal)

    def test_cancel_surfaces_sweep_warnings(self, service) -> None:
        """The 200 body carries the service's honest cancel caveats.

        Args:
            service: Mock service backing the client.
        """
        service.get_bracket.return_value.cancel_warnings = [
            "The MARKET entry position (if filled) remains open — square it off manually."
        ]
        with _make_app(service).test_client() as client:
            resp = client.delete("/api/v1/orders/bracket/br-001")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["data"]["warnings"] == [
            "The MARKET entry position (if filled) remains open — square it off manually."
        ]
        assert "remains open" in body["message"]

    def test_cancel_nonexistent_bracket_returns_404(self) -> None:
        """Cancel of a non-existent bracket returns HTTP 404."""
        svc = MagicMock()
        svc.get_bracket.return_value = None
        with _make_app(svc).test_client() as c:
            resp = c.delete("/api/v1/orders/bracket/ghost-id")
        assert resp.status_code == 404

    def test_cancel_already_done_returns_409(self) -> None:
        """Cancel of a completed bracket returns HTTP 409."""
        svc = MagicMock()
        bracket = MagicMock()
        bracket.to_dict.return_value = {"bracket_id": "br-x"}
        svc.get_bracket.return_value = bracket
        svc.cancel_bracket.return_value = False
        with _make_app(svc).test_client() as c:
            resp = c.delete("/api/v1/orders/bracket/br-x")
        assert resp.status_code == 409

    def test_cancel_gated_path_unavailable_returns_503(self) -> None:
        """A BracketOrderError from the service (fail-closed cancel) → HTTP 503.

        The 503 body must carry a FIXED, actionable operator message — never the
        raw exception text, which can embed broker/dispatcher internals
        (CodeQL py/stack-trace-exposure). The underlying detail is logged
        server-side instead.
        """
        svc = MagicMock()
        svc.get_bracket.return_value = MagicMock()
        svc.cancel_bracket.side_effect = BracketOrderError(
            "No gated cancel dispatcher is configured — leg OID-1: <internal broker trace>"
        )
        with _make_app(svc).test_client() as c:
            resp = c.delete("/api/v1/orders/bracket/br-001")
        assert resp.status_code == 503
        message = resp.get_json()["message"]
        assert "may still rest live at the broker" in message
        # The raw exception text (and any internal trace it embeds) must NOT leak.
        assert "internal broker trace" not in message
        assert "dispatcher" not in message

    def test_no_service_returns_503(self, client_no_service) -> None:
        """Missing BRACKET_SERVICE returns HTTP 503 on cancel.

        Args:
            client_no_service: Flask test client without service config.
        """
        resp = client_no_service.delete("/api/v1/orders/bracket/br-001")
        assert resp.status_code == 503
