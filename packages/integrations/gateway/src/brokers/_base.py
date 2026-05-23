"""Broker adapter ABC used by the safety-gated broker router."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from flinttrade_gateway.capabilities import Capabilities


@dataclass
class Session:
    access_token: str
    expires_at: float
    account_id: str = ""
    adapter_id: str = ""
    algo_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    read_only_until_at: float | None = None

    def is_expiring_soon(self, leeway_seconds: int = 60) -> bool:
        return self.expires_at <= datetime.now(tz=timezone.utc).timestamp() + leeway_seconds

    @property
    def is_read_only(self) -> bool:
        if self.read_only_until_at is None:
            return False
        return datetime.now(tz=timezone.utc).timestamp() < self.read_only_until_at


class BrokerAdapter(ABC):
    """Adapter boundary; write methods are called only by BrokerRouter."""

    @property
    @abstractmethod
    def broker_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> Capabilities:
        raise NotImplementedError

    @abstractmethod
    def place_order(self, session: Session, order: Any, *, _router_token: object | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def modify_order(self, session: Session, order: Any, *, _router_token: object | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, session: Session, broker_order_id: str, *, _router_token: object | None = None) -> Any:
        raise NotImplementedError

    @abstractmethod
    def quotes(self, session: Session, symbols: list[str]) -> dict[str, Any]:
        raise NotImplementedError

    async def stream_ticks(self, session: Session, symbols: list[str]) -> AsyncIterator[Any]:
        if False:
            yield session, symbols
        raise NotImplementedError

    @staticmethod
    def _require_router_token(_router_token: object | None, expected: object) -> None:
        if _router_token is not expected:
            from flinttrade_engine.safety import SafetyBypassError

            raise SafetyBypassError("adapter write method called outside BrokerRouter")
