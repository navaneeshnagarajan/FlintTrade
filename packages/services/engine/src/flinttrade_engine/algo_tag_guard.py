"""Broker order-tagging guard.

Some broker API programmes require programmatic orders to carry the
broker-assigned ``algo_id`` and enforce per-exchange order ceilings. Native
adapters advertising ``algo_tag_required=True`` must route every order through
this guard, which:

* relays the correct ``algo_id`` to stamp on the order, and
* enforces a per-(broker, exchange) per-second algo-order ceiling, refusing the
  order (``AlgoTagLimitError``) before it can breach the broker's limit and risk
  an account flag.

Pure and clock-injectable for testing; thread-safe so it can be shared across
the order path.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

_WINDOW_SECONDS = 1.0


class AlgoTagLimitError(RuntimeError):
    """Raised when an algo order would exceed the per-exchange per-second cap."""


@dataclass(frozen=True)
class AlgoTagConfig:
    """Per-broker algo-tagging configuration.

    Attributes:
        algo_id: The broker-registered algo identifier to stamp on orders.
        max_orders_per_sec: Maximum algo orders per exchange per second.
    """

    algo_id: str
    max_orders_per_sec: int


class AlgoTagGuard:
    """Per-(broker, exchange) algo-order rate guard with algo_id relay."""

    def __init__(
        self,
        configs: dict[str, AlgoTagConfig],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._configs = dict(configs)
        self._clock = clock
        self._events: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: tuple[str, str], now: float) -> list[float]:
        return [t for t in self._events.get(key, []) if now - t < _WINDOW_SECONDS]

    def tag_order(self, broker: str, exchange: str) -> str:
        """Register an algo order and return the ``algo_id`` to tag it with.

        Raises:
            AlgoTagLimitError: if the broker is unconfigured, or the per-second
                algo-order ceiling for ``(broker, exchange)`` would be exceeded.
        """
        cfg = self._configs.get(broker)
        if cfg is None:
            raise AlgoTagLimitError(f"No algo-tag configuration for broker {broker!r}")

        key = (broker, exchange)
        now = self._clock()
        with self._lock:
            window = self._recent(key, now)
            if len(window) >= cfg.max_orders_per_sec:
                raise AlgoTagLimitError(
                    f"Algo-order rate limit for {broker}/{exchange}: "
                    f"{cfg.max_orders_per_sec}/s would be exceeded"
                )
            window.append(now)
            self._events[key] = window
        return cfg.algo_id

    def usage(self, broker: str, exchange: str) -> int:
        """Return the number of algo orders in the current 1s window."""
        now = self._clock()
        with self._lock:
            window = self._recent((broker, exchange), now)
            self._events[(broker, exchange)] = window
            return len(window)

    def algo_id_for(self, broker: str) -> str | None:
        """Return the configured ``algo_id`` for ``broker`` (or None)."""
        cfg = self._configs.get(broker)
        return None if cfg is None else cfg.algo_id
