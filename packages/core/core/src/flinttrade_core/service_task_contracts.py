"""Typed non-trading task refusals and authorised context integration."""

from __future__ import annotations

from dataclasses import dataclass


class TaskRefused(RuntimeError):
    """Closed, non-secret refusal code, never arbitrary provider exception text."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True, slots=True)
class TaskContext:
    """One authorised full procedure/retrieval fragment supplied by core.

    The resolver receives exact actor/purpose/references. It owns scope/rights
    checks. ``validate_send`` on the resolver is called again at each actual
    provider send; raw references and private bodies never reach the router.
    """

    reference: str
    version: str
    body: str
    classification: str
    receipt: str
