"""Request identity passed from HTTP middleware to trading routers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


def parse_selector(selector: str) -> tuple[str, str]:
    """Split a canonical ``'adapter_id:account_id'`` selector on the FIRST colon.

    The selector is the principal's account binding (identity X7). Account ids
    may themselves contain colons (e.g. an OpenAlgo sub-account ``zerodha:sub``),
    so only the first colon is the delimiter — everything after it is the
    account id.

    Args:
        selector: The composite ``'adapter_id:account_id'`` string.

    Returns:
        A ``(adapter_id, account_id)`` tuple.

    Raises:
        ValueError: If there is no colon, or either side is empty.
    """
    adapter_id, sep, account_id = selector.partition(":")
    if not sep or not adapter_id or not account_id:
        raise ValueError(
            f"invalid selector {selector!r}: must be 'adapter_id:account_id'"
        )
    return adapter_id, account_id


@dataclass(frozen=True)
class RequestContext:
    """Per-request identity bundle minted only at the verified request boundary."""

    jti: str
    actor_type: Literal["human", "agent", "external_intent"]
    actor_id: str
    mode: Literal["explore", "practice", "live"]
    intent_source: str | None = None
    external_nonce_hash: str | None = None
    # The principal's account binding: a canonical ``'adapter_id:account_id'``
    # selector (identity X7). Appended LAST so existing positional constructions
    # keep working. ``None`` means the principal is not yet bound to one account
    # (e.g. read-only/exploratory contexts that resolve the account downstream).
    selector: str | None = None

    def selector_parts(self) -> tuple[str, str] | None:
        """Return ``(adapter_id, account_id)`` when a selector is bound, else ``None``."""
        if self.selector is None:
            return None
        return parse_selector(self.selector)
