"""Exact app-owned Paper binding at the canonical order ingress only."""
from __future__ import annotations

from typing import Any

from flask import current_app, request

from .practice_agent_adapter import PracticeAgentError


def request_execution_binding() -> Any:
    """Resolve a trusted object, not a client-selected account or UI mode."""
    from .auth_routes import verify_operator_session_token
    from .auth_scopes import _session_token
    from .execution_session import RunExecutionBinding
    from .protection_grants import request_principal

    binding = request.environ.get("flinttrade.execution_binding")
    if binding is None:
        return None
    try:
        if (type(binding) is not RunExecutionBinding or binding.registry.app is not current_app._get_current_object()
                or binding.scope.environment != "paper" or request.path != "/api/v1/orders/place"
                or request.method != "POST"):
            raise ValueError
        binding.validate()
        protection = request_principal()
        if protection is not None:
            if protection.scope != binding.scope:
                raise ValueError
        else:
            token = _session_token()
            if not token or verify_operator_session_token(token).actor_ref != binding.scope.actor:
                raise ValueError
        return binding
    except Exception:
        raise PracticeAgentError("practice_execution_scope_invalid") from None


def practice_request_sandbox() -> Any:
    """Use only the pinned book, never active-account/mode fallback."""
    binding = request_execution_binding()
    if binding is not None:
        return binding.sandbox
    return current_app.config.get("DATA_SANDBOX_ENGINE")
