"""Temporary account-mutation admission until the reviewed Task 9D cutover.

Production is unconditionally unavailable. The callable dependency is only an
explicit composition seam for isolated tests of retained legacy internals; it
is never populated from workspace settings, environment or request input.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MutationAdmission = Callable[[], None]
CUTOVER_UNAVAILABLE = "broker_account_cutover_unavailable"


class BrokerAccountCutoverUnavailable(RuntimeError):
    """Fixed, metadata-free internal outcome for unavailable account writes."""

    def __init__(self) -> None:
        super().__init__(CUTOVER_UNAVAILABLE)


def require_broker_account_mutations() -> None:
    """Reject production mutations until Task 9D removes this guard."""
    raise BrokerAccountCutoverUnavailable


def mutation_admission_for(app: Any) -> MutationAdmission:
    """Resolve an explicitly injected composition dependency, default denied."""
    return app.config.get("BROKER_ACCOUNT_MUTATION_ADMISSION", require_broker_account_mutations)


def guard_broker_account_http() -> Any | None:
    """Adapt only the fixed unavailable outcome to the shared HTTP contract."""
    from flask import current_app, jsonify  # noqa: PLC0415

    try:
        mutation_admission_for(current_app)()
    except BrokerAccountCutoverUnavailable:
        response = jsonify({"error": CUTOVER_UNAVAILABLE})
        response.status_code = 503
        response.headers["Cache-Control"] = "no-store"
        return response
    return None
