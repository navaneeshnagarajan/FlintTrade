"""Bind optional backtest evidence to an existing run, never body authority."""
from __future__ import annotations

import os
import re
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from flask import current_app, request

from .model_control_auth import ModelControlDenied, _body, principal


class BacktestScopeUnavailable(RuntimeError):
    """The exact installed run/evidence owner is not available."""


@dataclass(frozen=True)
class BacktestRunSelection:
    """Request-local authenticated selection; no trading or scoring authority."""

    run_id: str
    actor: str
    session_binding: str
    scope: tuple[tuple[str, str], ...]
    services: Any
    run_owner: Any
    evidence_store: Any


def _operator() -> Any:
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        raise ModelControlDenied("loopback_required")
    allowed = set(os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(",")) - {"*", "null", ""}
    if urlsplit(request.host_url).hostname in {"localhost", "127.0.0.1", "::1"}:
        allowed.add(request.host_url.rstrip("/"))
    origin = request.headers.get("Origin")
    if request.headers.get("Sec-Fetch-Site") == "cross-site" or origin is not None and origin not in allowed:
        raise ModelControlDenied("origin_forbidden")
    return principal()


def select_backtest_run(body: dict[str, Any]) -> BacktestRunSelection | None:
    """A run ID selects existing custody; caller scope never labels a receipt."""
    if {"scope", "control_scope", "actor", "account", "environment"} & body.keys():
        raise ValueError("Server-owned evaluation scope required")
    if "run_id" not in body:
        return None
    body = _body()  # Preserve bounded, duplicate-free JSON at the sensitive seam.
    run_id = body["run_id"]
    if type(run_id) is not str or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", run_id) is None:
        raise ValueError("Exact run selector required")
    who = _operator()
    from .evaluation import EvaluationStore
    from .run_adoption import ModelRunServices

    app = current_app._get_current_object()
    services = app.config.get("MODEL_RUN_SERVICES")
    evidence_store = app.config.get("EVALUATION_STORE")
    if (not isinstance(services, ModelRunServices) or services.app is not app
            or services.closed or not isinstance(evidence_store, EvaluationStore)):
        raise BacktestScopeUnavailable
    try:
        with services.runs.fence(run_id, "reasoning"):
            services.authorise(who.actor_ref, "evaluation", "read", identity=None, body={"run_id": run_id})
            scope = vars(services.runs.scope(run_id))
            return BacktestRunSelection(run_id, who.actor_ref, who.session_binding,
                                        tuple(sorted(scope.items())), services, services.runs.owner(run_id), evidence_store)
    except (KeyError, ValueError):
        raise ModelControlDenied("backtest_run_scope_refused") from None


@contextmanager
def backtest_run_fence(selection: BacktestRunSelection | None) -> Iterator[dict[str, str] | None]:
    """Revalidate at immutable publication after data I/O, not around grading."""
    if selection is None:
        yield None
        return
    who = _operator()
    services = selection.services
    if (services is not current_app.config.get("MODEL_RUN_SERVICES") or services.closed
            or current_app.config.get("EVALUATION_STORE") is not selection.evidence_store):
        raise BacktestScopeUnavailable
    if (who.actor_ref, who.session_binding) != (selection.actor, selection.session_binding):
        raise ModelControlDenied("backtest_run_session_changed")
    with ExitStack() as stack:
        try:
            stack.enter_context(services.runs.fence(selection.run_id, "reasoning"))
            if services.runs.owner(selection.run_id) is not selection.run_owner:
                raise ModelControlDenied("backtest_run_owner_changed")
            services.authorise(who.actor_ref, "evaluation", "read", identity=None,
                               body={"run_id": selection.run_id})
            scope = vars(services.runs.scope(selection.run_id))
            if scope != dict(selection.scope):
                raise ModelControlDenied("backtest_run_scope_changed")
        except (KeyError, ValueError):
            raise ModelControlDenied("backtest_run_scope_refused") from None
        # Do not translate the caller's storage or simulation failures into an
        # authorisation refusal. The actual run fence still covers publication.
        yield dict(scope)
