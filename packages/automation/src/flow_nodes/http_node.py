"""HTTP request flow node — makes an outbound HTTP call using httpx."""

from __future__ import annotations

from typing import Any, Literal

from .base import FlowContext, FlowNode, FlowResult

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class HTTPRequestNode(FlowNode):
    """Make a synchronous HTTP request and surface the response.

    The response body (JSON if parseable, otherwise raw text) and status
    code are stored in the :class:`FlowResult` and optionally written
    back to a named variable in the shared :class:`FlowContext`.

    Args:
        url: Target URL.  May contain ``{variable}`` placeholders that are
            resolved from ``context.variables`` at execution time.
        method: HTTP verb — ``"GET"``, ``"POST"``, ``"PUT"``, ``"PATCH"``,
            or ``"DELETE"``.  Defaults to ``"GET"``.
        headers: Request headers dict.  Defaults to empty.
        body: Request body dict (sent as JSON).  Defaults to ``None``.
        output_var: If provided, writes the parsed response body to this
            variable name in :attr:`FlowContext.variables`.
        timeout: Request timeout in seconds.  Defaults to 10.

    Example::

        node = HTTPRequestNode(
            url="https://example.com/api",
            method="POST",
            body={"key": "value"},
            output_var="api_response",
        )
        result = node.execute(context)
        assert result.success
    """

    node_type = "http_request"

    def __init__(
        self,
        url: str,
        method: HTTPMethod = "GET",
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        output_var: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.body = body
        self.output_var = output_var
        self.timeout = timeout

    def execute(self, context: FlowContext) -> FlowResult:
        """Perform the HTTP request.

        Args:
            context: Shared flow context.  URL placeholders are resolved
                from ``context.variables``.

        Returns:
            :class:`FlowResult` with ``output`` as the parsed response body
            (dict for JSON, str otherwise) and ``metadata["status_code"]``.
        """
        try:
            import httpx  # lazy import — optional at module level
        except ImportError:
            return FlowResult.fail(
                "httpx is required for HTTPRequestNode. "
                "Install it with: pip install httpx"
            )

        try:
            # Resolve any {var} placeholders in the URL.
            resolved_url = self.url.format(**context.variables)

            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(
                    method=self.method,
                    url=resolved_url,
                    headers=self.headers,
                    json=self.body if self.body is not None else None,
                )

            try:
                parsed: Any = response.json()
            except Exception:  # noqa: BLE001
                parsed = response.text

            if self.output_var:
                context.set(self.output_var, parsed)

            success = response.is_success
            if not success:
                return FlowResult(
                    success=False,
                    output=parsed,
                    error=f"HTTP {response.status_code}",
                    metadata={"status_code": response.status_code},
                )
            return FlowResult.ok(output=parsed, status_code=response.status_code)

        except Exception as exc:  # noqa: BLE001
            return FlowResult.fail(f"HTTPRequestNode error: {exc}")
