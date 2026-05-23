"""Request identity passed from HTTP middleware to trading routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class RequestContext:
    """Per-request identity bundle minted only at the verified request boundary."""

    jti: str
    actor_type: Literal["human", "agent", "external_intent"]
    actor_id: str
    mode: Literal["explore", "practice", "live"]
    intent_source: str | None = None
    external_nonce_hash: str | None = None
