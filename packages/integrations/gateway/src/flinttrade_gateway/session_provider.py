"""AuthenticatingSessionProvider — per-(actor, account) ACL gate (contract §11.4).

v1.0.1 Identity H2: session lookup that authorises ``request_ctx.actor_id``
against ``workspace.json.brokers.account_acls[adapter_id][account_id]`` BEFORE
the Session leaves the provider.

This is the single enforcement gate for BOTH the read and the write path — the
BrokerRouter obtains every Session (quotes/historical and place_order alike)
through this callable, so an unauthorised read is refused with the same
``SafetyBypassError`` as an unauthorised write and there is no separate code path
that could be bypassed. The provider owns the workspace.json dependency; the
router stays workspace-agnostic.
"""

from __future__ import annotations

from typing import Any

from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_engine.request_context import RequestContext

from .registry import BrokerRegistry


class AuthenticatingSessionProvider:
    """Session lookup with a per-``(actor, account)`` ACL check (contract §11.4).

    ``account_acls`` shape::

        {
          "dhan": {
            "personal": ["nava@flinttrade.local"],
            "spouse":   ["nava@flinttrade.local", "spouse@flinttrade.local"]
          },
          ...
        }
    """

    def __init__(
        self,
        registry: BrokerRegistry,
        account_acls: dict[str, dict[str, list[str]]],
    ) -> None:
        self._registry = registry
        self._acls = account_acls

    def __call__(self, request_ctx: RequestContext, adapter_id: str, account_id: str) -> Any:
        allowed_actors = self._acls.get(adapter_id, {}).get(account_id, [])
        if request_ctx.actor_id not in allowed_actors:
            raise SafetyBypassError(
                f"actor '{request_ctx.actor_id}' is not authorised for "
                f"({adapter_id}, {account_id}). workspace.json.brokers.account_acls "
                f"must list this actor for this account."
            )
        return self._registry.get_session_for(adapter_id, account_id)
