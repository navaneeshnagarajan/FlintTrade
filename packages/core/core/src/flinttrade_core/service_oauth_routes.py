"""Provider callbacks deposit encrypted codes; operator POST completes acquisition."""

from collections.abc import Callable

from flask import Blueprint, Flask, Response, current_app, g, jsonify, make_response, request
from flask.typing import ResponseReturnValue

from .service_connection_audit import ConnectionActorContext
from .service_connection_store import ServiceConnectionStore
from .service_oauth import CALLBACK_PATH, ServiceOAuth
from .service_task_contracts import TaskRefused

COOKIE = "flinttrade_service_oauth"


def bind_oauth(app: Flask, store: ServiceConnectionStore) -> ServiceConnectionStore:
    """Factory-only composition, with no files, network, threads or read recreation."""
    import time

    if store.oauth is None:
        store.oauth = ServiceOAuth(
            store,
            config=lambda: app.config.get("SERVICE_OAUTH_CONFIG", {}),
            transport=lambda: app.config.get("SERVICE_OAUTH_TRANSPORT"),
            clock=lambda: app.config.get("SERVICE_OAUTH_CLOCK", time.time)(),
        )
    return store


def owner() -> ServiceOAuth:
    store = current_app.config.get("SERVICE_CONNECTION_STORE")
    if store is None or store.oauth is None:
        raise TaskRefused("oauth_not_configured", 422)
    return store.oauth


def authority() -> ConnectionActorContext:
    from .service_connection_routes import _authenticate_connection_request

    proof, error = _authenticate_connection_request()
    who = getattr(proof, "principal", None)
    if error or who is None or "admin.services.write" not in who.scopes:
        raise TaskRefused("oauth_authority_changed", 403)
    return ConnectionActorContext(who.actor_ref, who.session_binding)


def checked_authority() -> tuple[ConnectionActorContext, Callable[[], None]]:
    original = authority()
    installed = owner()

    def check() -> None:
        if authority() != original:
            raise TaskRefused("oauth_authority_changed", 403)
        if owner() is not installed or current_app.config.get("SERVICE_CONNECTION_STORE") is not installed.store:
            raise TaskRefused("oauth_unavailable", 503)

    return original, check


def callback() -> Response:
    try:
        if request.method != "GET" or any(len(v) != 1 for _, v in request.args.lists()):
            raise TaskRefused("oauth_callback_invalid", 400)
        owner().callback(request.args.to_dict(), request.cookies.get(COOKIE), request.base_url)
        response = make_response(
            "Provider response received. Return to FlintTrade Settings and choose Complete sign-in.", 200
        )
    except TaskRefused as error:
        response = make_response("Provider response refused. Return to FlintTrade Settings.", error.status)
    except Exception:
        response = make_response("Provider response unavailable. Return to FlintTrade Settings.", 503)
    response.headers.update(
        {
            "Content-Type": "text/plain; charset=utf-8",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
        }
    )
    return response


def configure() -> ResponseReturnValue:
    from .service_connection_etags import parse_single_strong_entity_tag
    from .service_connection_routes import _record_attempt, _validated_json_body

    try:
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise TaskRefused("origin_forbidden", 403)
        payload, error = _validated_json_body()
        if error:
            return error
        if payload is None or set(payload) != {"deployment"} or payload["deployment"] not in ("api_only", "local_oss"):
            raise ValueError
        actor, check = checked_authority()
        revision = request.headers.get("If-Match")
        if revision is None:
            raise TaskRefused("connection_revision_required", 428)
        revision = parse_single_strong_entity_tag(revision)
        service = owner()
        service.configure(payload["deployment"], revision, check)
        check()
        response = jsonify(service.capabilities())
        response.headers["ETag"] = revision
        _record_attempt("accepted", getattr(g, "service_connection_proof", None))
        return response
    except TaskRefused as error:
        return jsonify(error=error.code), error.status
    except (ValueError, TypeError):
        return jsonify(error="invalid_request"), 400
    except Exception:
        return jsonify(error="oauth_unavailable"), 503


def bind_desktop_oauth_port(app: Flask, port: int | str) -> None:
    """Called only by the desktop's owned Waitress listener, before readiness."""
    port = int(port)
    if not 0 < port < 65536:
        raise ValueError("invalid bound listener")
    app.config["SERVICE_OAUTH_CONFIG"] = {
        "desktop_bound": True,
        "redirect_uri": f"http://127.0.0.1:{port}{CALLBACK_PATH}",
    }


def launch() -> Response:
    try:
        if set(request.args) != {"ticket"} or len(request.args.getlist("ticket")) != 1:
            raise TaskRefused("oauth_launch_invalid", 400)
        url, cookie = owner().launch(request.args["ticket"], request.base_url)
        response = make_response("", 302)
        response.headers["Location"] = url
        response.set_cookie(
            COOKIE, cookie, max_age=600, httponly=True, samesite="Lax", secure=False, path=CALLBACK_PATH
        )
    except TaskRefused as error:
        response = make_response("Provider launch refused. Return to FlintTrade Settings.", error.status)
    except Exception:
        response = make_response("Provider launch unavailable. Return to FlintTrade Settings.", 503)
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
        }
    )
    return response


def route(identifier: str, operation: str) -> ResponseReturnValue:
    from .service_connection_etags import parse_single_strong_entity_tag
    from .service_connection_routes import _record_attempt, _validated_json_body

    try:
        # Bearer session remains required, plus same-site browser protection.
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise TaskRefused("origin_forbidden", 403)
        payload, error = _validated_json_body()
        if error:
            return error
        external = operation == "start" and payload == {"browser": "external"}
        if payload is None or (
            not external and set(payload) != ({"transaction_id"} if operation in {"complete", "cancel"} else set())
        ):
            raise ValueError
        revision = request.headers.get("If-Match")
        if revision is None:
            raise TaskRefused("connection_revision_required", 428)
        revision = parse_single_strong_entity_tag(revision)
        actor, check = checked_authority()
        service = owner()
        if operation == "start":
            value, cookie = service.start(identifier, revision, actor, check, external_browser=external)
            response = jsonify(value)
            response.headers["ETag"] = revision
            _record_attempt("accepted", getattr(g, "service_connection_proof", None))
            if cookie is not None:
                response.set_cookie(
                    COOKIE, cookie, max_age=600, httponly=True, samesite="Lax", secure=False, path=CALLBACK_PATH
                )
            return response
        if operation in {"complete", "cancel"}:
            value = getattr(service, operation)(identifier, revision, payload["transaction_id"], actor, check)
        else:
            value = getattr(service, operation)(identifier, revision, actor, check)
        response = jsonify(value)
        response.headers["ETag"] = service.store.read_snapshot().etag
        _record_attempt("accepted", getattr(g, "service_connection_proof", None))
        return response
    except TaskRefused as error:
        return jsonify(error=error.code), error.status
    except (ValueError, TypeError, KeyError):
        return jsonify(error="invalid_request"), 400
    except Exception:
        return jsonify(error="oauth_unavailable"), 503


def read_status(identifier: str) -> ResponseReturnValue:
    try:
        from .service_connection_routes import _authenticate_connection_request

        proof, denial = _authenticate_connection_request()
        if denial:
            return denial
        if proof.principal is None:
            raise TaskRefused("operator_session_required", 403)
        actor = ConnectionActorContext(proof.principal.actor_ref, proof.principal.session_binding)
        value, etag = owner().status(identifier, actor)
        response = jsonify(value)
        response.headers["ETag"] = etag
        return response
    except TaskRefused as error:
        return jsonify(error=error.code), error.status
    except Exception:
        return jsonify(error="oauth_unavailable"), 503


def install_oauth_routes(blueprint: Blueprint) -> None:
    blueprint.add_url_rule("/oauth/configuration", "oauth_configure", configure, methods=["POST"])
    blueprint.add_url_rule("/oauth/launch", "oauth_launch", launch, methods=["GET"])
    blueprint.add_url_rule("/<identifier>/oauth/status", "oauth_status", read_status, methods=["GET"])
    blueprint.add_url_rule("/oauth/callback", "oauth_callback", callback, methods=["GET"])
    for operation in ("start", "complete", "cancel", "refresh", "disconnect"):
        blueprint.add_url_rule(
            "/<identifier>/oauth/" + operation,
            "oauth_" + operation,
            lambda identifier, op=operation: route(identifier, op),
            methods=["POST"],
        )
