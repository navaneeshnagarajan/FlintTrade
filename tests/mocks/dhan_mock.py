"""Mock of the ``dhanhq`` SDK surface flinttrade calls (Identity H9 default-mock).

Stands in for the real ``dhanhq`` package during pytest so no test can reach a live
broker. Read paths return canned, obviously-fake data; any write/order path raises so an
accidental real-order illusion is impossible — a test that expects to place an order must
use an explicit stub, never this safety mock.
"""

from __future__ import annotations

from typing import Any

MOCK = True
__version__ = "0.0.0-mock"


class _MockRefused(RuntimeError):
    """Raised when test code reaches a real-money path through the safety mock."""


class DhanContext:
    """Mirror of ``dhanhq.DhanContext`` (client-id + access-token holder)."""

    def __init__(self, client_id: str = "MOCK_CLIENT", access_token: str = "MOCK_TOKEN") -> None:
        self.client_id = client_id
        self.access_token = access_token


class dhanhq:  # noqa: N801 — match the real SDK's lowercase class name
    """Mirror of the real ``dhanhq.dhanhq`` client. Read=canned, write=refused."""

    def __init__(self, context: DhanContext | None = None, *_: Any, **__: Any) -> None:
        self.context = context or DhanContext()

    # --- read paths: canned, obviously fake -------------------------------
    def get_fund_limits(self) -> dict[str, Any]:
        return {"status": "success", "data": {"availabelBalance": 0.0}, "mock": True}

    def get_positions(self) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def get_holdings(self) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def get_order_list(self) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    # --- write paths: refuse loudly ---------------------------------------
    def place_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused(
            "dhan_mock.place_order called — the default-mock SDK refuses order placement. "
            "Use an explicit test stub if you intend to assert order behaviour."
        )

    def modify_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("dhan_mock.modify_order refused (default-mock SDK)")

    def cancel_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("dhan_mock.cancel_order refused (default-mock SDK)")
