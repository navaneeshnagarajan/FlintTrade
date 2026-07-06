"""Mock of the ``neo_api_client`` (Kotak Neo) surface (Identity H9 default-mock).

Wave-3 broker; forward-looking safety stub. Read paths return canned data; order paths
raise so no test can reach a live broker.
"""

from __future__ import annotations

from typing import Any

MOCK = True
__version__ = "0.0.0-mock"


class _MockRefused(RuntimeError):
    """Raised when test code reaches a real-money path through the safety mock."""


class NeoAPI:
    """Mirror of ``neo_api_client.NeoAPI``."""

    def __init__(self, *_: Any, **__: Any) -> None:
        self._authenticated = False

    def login(self, *_: Any, **__: Any) -> dict[str, Any]:
        self._authenticated = True
        return {"status": "success", "mock": True}

    def session_2fa(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "mock": True}

    def positions(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def holdings(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def order_report(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def place_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("kotak_neo_mock.place_order refused (default-mock SDK)")

    def modify_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("kotak_neo_mock.modify_order refused (default-mock SDK)")

    def cancel_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("kotak_neo_mock.cancel_order refused (default-mock SDK)")


class OrderReportAPI:
    """Mirror of ``neo_api_client.OrderReportAPI`` (read-only report surface).

    The adapter's REST cancel branch imports this at call time
    (``kotakneo.py _cancel_order_rest``), so the mock must cover it or a
    leaked/installed mock turns that branch into an ImportError.
    """

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    def ordered_books(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}


class _ReqDataValidation:
    """Mirror of ``neo_api_client.req_data_validation`` (pure validators)."""

    @staticmethod
    def cancel_order_validation(order_id: Any, _amo: Any) -> None:
        if not str(order_id or "").strip():
            raise ValueError("order_id is required")


req_data_validation = _ReqDataValidation()
