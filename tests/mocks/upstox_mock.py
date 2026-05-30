"""Mock of the ``upstox_python_sdk`` surface (Identity H9 default-mock).

Wave-2 broker; the adapter is not yet built, so this is a forward-looking safety stub.
Read paths return canned data; order paths raise so no test can reach a live broker.
"""

from __future__ import annotations

from typing import Any

MOCK = True
__version__ = "0.0.0-mock"


class _MockRefused(RuntimeError):
    """Raised when test code reaches a real-money path through the safety mock."""


class Configuration:
    def __init__(self, *_: Any, **__: Any) -> None:
        self.access_token = "MOCK_TOKEN"


class ApiClient:
    def __init__(self, configuration: Configuration | None = None, *_: Any, **__: Any) -> None:
        self.configuration = configuration or Configuration()


class OrderApi:
    def __init__(self, api_client: ApiClient | None = None) -> None:
        self.api_client = api_client or ApiClient()

    def place_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("upstox_mock.place_order refused (default-mock SDK)")

    def cancel_order(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise _MockRefused("upstox_mock.cancel_order refused (default-mock SDK)")


class PortfolioApi:
    def __init__(self, api_client: ApiClient | None = None) -> None:
        self.api_client = api_client or ApiClient()

    def get_positions(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}

    def get_holdings(self, *_: Any, **__: Any) -> dict[str, Any]:
        return {"status": "success", "data": [], "mock": True}
