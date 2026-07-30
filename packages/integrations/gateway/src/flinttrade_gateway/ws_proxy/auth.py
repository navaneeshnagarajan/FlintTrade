"""API key validation for WebSocket proxy client connections.

The proxy supports two validation modes, selected at server construction time:

1. **Static key** — a single API key string is set at startup and compared
   using a constant-time equality check (``hmac.compare_digest``).  This
   is the default mode and suitable for single-instance deployments.

2. **Callable validator** — a user-supplied coroutine or synchronous callable
   is invoked on every authentication request.  Use this for multi-tenant
   deployments where keys must be looked up in a database.

Empty API keys are always rejected, regardless of mode.
"""

from __future__ import annotations

import hmac
import logging
from typing import Awaitable, Callable

logger = logging.getLogger("flinttrade.gateway.ws_proxy.auth")


def validate_api_key(provided: str, expected: str) -> bool:
    """Constant-time comparison of two API key strings.

    Uses :func:`hmac.compare_digest` to prevent timing side-channel attacks.

    Args:
        provided: The API key submitted by the client.
        expected: The correct API key held by the server.

    Returns:
        ``True`` if both keys are non-empty and match, ``False`` otherwise.
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


class ApiKeyValidator:
    """Pluggable API key validator for the WS proxy.

    Wraps either a static key or a user-supplied callable so that the
    server has a single, uniform validation interface.

    Args:
        api_key: Static API key string.  Ignored when *validator* is given.
        validator: Optional async or sync callable with signature
            ``(api_key: str) -> bool``.  When supplied, *api_key* is ignored.

    Example — static key::

        v = ApiKeyValidator(api_key="secret123")
        ok = await v.check("secret123")   # True

    Example — custom validator::

        async def my_validator(key: str) -> bool:
            return await db.lookup(key)

        v = ApiKeyValidator(validator=my_validator)
        ok = await v.check("somekey")
    """

    def __init__(
        self,
        api_key: str = "",
        validator: Callable[[str], bool | Awaitable[bool]] | None = None,
    ) -> None:
        self._api_key = api_key
        self._validator = validator

    async def check(self, provided: str) -> bool:
        """Validate *provided* against the configured key or callable.

        Args:
            provided: The API key to validate.

        Returns:
            ``True`` if valid, ``False`` otherwise.
        """
        if not provided:
            logger.warning("ApiKeyValidator: empty key rejected")
            return False

        if self._validator is not None:
            import asyncio

            result = self._validator(provided)
            if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                return bool(await result)
            return bool(result)

        return validate_api_key(provided, self._api_key)
