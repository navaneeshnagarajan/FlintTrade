"""Per-run model bounds with durable, conservative attempt accounting.

These are call and per-response output limits, not monetary or input limits.
Reservations are never refunded: a failed request or an unknown outcome may
still have incurred provider usage. Recovery never resumes a run's authority.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any


class ModelBudgetExhausted(RuntimeError):
    """No more provider requests are authorised for this Practice run."""


class PracticeModelBudget:
    """Serialise a shared analysis/reflection budget behind durable evidence."""

    def __init__(
        self, call_limit: int, output_limit: int, *, event_sink: Callable[[str, dict[str, Any]], None],
    ) -> None:
        if type(call_limit) is not int or not 1 <= call_limit <= 10_000:
            raise ValueError("model_call_limit must be an integer between 1 and 10000")
        if type(output_limit) is not int or not 16 <= output_limit <= 4096:
            raise ValueError("model_output_limit must be an integer between 16 and 4096")
        self.call_limit = call_limit
        self.output_limit = output_limit
        self._event_sink = event_sink
        self._lock = threading.Lock()
        self._used = 0
        self._evidence_failed = False

    @property
    def exhausted(self) -> bool:
        with self._lock:
            return self._used >= self.call_limit

    def snapshot(self) -> dict[str, Any]:
        """Return only safe numeric bounds, consumption and availability."""
        with self._lock:
            return self._snapshot(self._used)

    def _snapshot(self, used: int) -> dict[str, Any]:
        return {
            "model_call_limit": self.call_limit,
            "model_output_limit": self.output_limit,
            "model_calls_used": used,
            "model_calls_remaining": self.call_limit - used,
            "status": ("evidence_unavailable" if self._evidence_failed
                       else "exhausted" if used >= self.call_limit else "available"),
        }

    def reserve(self, operation: str) -> int:
        """Commit an attempt before permitting exactly one top-level request."""
        if operation not in {"analysis", "reflection"}:
            raise ValueError("Unsupported Practice model operation")
        with self._lock:
            if self._evidence_failed:
                raise RuntimeError("practice_model_evidence_unavailable")
            if self._used >= self.call_limit:
                raise ModelBudgetExhausted("model_limit_exhausted")
            attempt = self._used + 1
            try:
                self._event_sink("model_attempt_reserved", {"operation": operation, **self._snapshot(attempt)})
            except Exception:
                self._evidence_failed = True
                # Do not increment on an unconfirmed evidence write or expose
                # exception text. The whole run must stop, never retry a call.
                raise RuntimeError("practice_model_evidence_unavailable") from None
            self._used = attempt
            return attempt


def freeze_practice_client(client: Any, *, output_limit: int) -> Any:
    """Copy a production client into a dedicated, single-request configuration.

    Existing explicitly injected protocol doubles remain injectable. This is
    not a runtime bypass flag: production always constructs an LLMClient, which
    is replaced with an explicit configuration that cannot reread settings.
    The caller retains ownership of closing the original and returned clients.
    """
    from flinttrade_ai.llm_client import LLMClient  # noqa: PLC0415

    if not isinstance(client, LLMClient):
        return client
    if type(output_limit) is not int or not 16 <= output_limit <= 4096:
        raise ValueError("model_output_limit must be an integer between 16 and 4096")
    config = replace(client.config, max_tokens=output_limit, reasoning_max_tokens=0)
    return LLMClient(config=config, fallback_config=None)


def bounded_practice_chat(client: Any, output_limit: int, *args: Any, **kwargs: Any) -> Any:
    """Clamp production output overrides without changing injected protocols."""
    from flinttrade_ai.llm_client import LLMClient  # noqa: PLC0415

    if isinstance(client, LLMClient):
        requested_model = args[3] if len(args) > 3 else kwargs.get("model")
        if requested_model is not None and requested_model != "" and requested_model != client.config.model:
            raise RuntimeError("practice_model_override_refused")
        # LLMClient.chat(messages, temperature, max_tokens, ...). Handle both
        # keyword and positional overrides; default/invalid caps cannot remove
        # this run's bound. The existing protocol doubles need no new kwargs.
        requested = args[2] if len(args) > 2 else kwargs.get("max_tokens")
        cap = min(requested, output_limit) if type(requested) is int and requested > 0 else output_limit
        if len(args) > 2:
            args = (*args[:2], cap, *args[3:])
        else:
            kwargs["max_tokens"] = cap
    return client.chat(*args, **kwargs)
