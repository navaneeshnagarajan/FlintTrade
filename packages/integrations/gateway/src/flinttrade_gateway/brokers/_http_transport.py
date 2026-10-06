"""Single-request REST transport for the native adapters without an SDK."""

from __future__ import annotations

from typing import Any, Callable


def _build_httpx_transport(timeout: float = 10.0) -> Callable[..., tuple[int, Any]]:
    """Build a synchronous transport with lazy httpx loading and no retries.

    Broker writes can share this path, so retry policy must not be inherited
    from a general-purpose HTTP pool. Decode JSON when possible, else raw text.
    """
    import httpx  # noqa: PLC0415

    def _request(
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> tuple[int, Any]:
        resp = httpx.request(method, url, headers=headers, params=params, json=json_body, timeout=timeout)
        try:
            payload: Any = resp.json()
        except ValueError:
            payload = resp.text
        return resp.status_code, payload

    return _request
