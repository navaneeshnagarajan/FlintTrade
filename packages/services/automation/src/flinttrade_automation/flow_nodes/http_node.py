"""HTTP request flow node — makes an outbound HTTP call using httpx."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any, Literal
from urllib.parse import urlparse

from .base import FlowContext, FlowNode, FlowResult

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]


class SSRFError(ValueError):
    """Raised when a flow URL fails SSRF safety checks."""


def _validate_public_url(url: str) -> None:
    """Reject non-http(s) schemes and hosts that resolve to private ranges.

    Blocks loopback, link-local, private RFC1918, IPv6 ULA, multicast, and
    cloud metadata endpoints (169.254.169.254). Raises :class:`SSRFError` on
    any violation. Resolves every A/AAAA record — a single private answer
    causes rejection (prevents DNS-rebinding attacks at first-hop).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"scheme '{parsed.scheme}' not allowed (http/https only)")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host component")
    # Block bare-IP loopback/private targets without DNS lookup.
    try:
        ip_direct = ipaddress.ip_address(host)
    except ValueError:
        ip_direct = None
    if ip_direct is not None:
        _reject_if_private(ip_direct, host)
        return
    # Resolve hostname and reject if any address lands in a private range.
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise SSRFError(f"could not resolve host '{host}': {exc}") from exc
    for info in infos:
        addr = info[4][0]
        try:
            _reject_if_private(ipaddress.ip_address(addr), host)
        except ValueError:
            continue


def _reject_if_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
    # 169.254.169.254 is the cloud metadata endpoint — explicit block.
    if str(ip) == "169.254.169.254":
        raise SSRFError(f"host '{host}' resolves to cloud metadata endpoint")
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise SSRFError(f"host '{host}' resolves to non-public address {ip}")


class HTTPRequestNode(FlowNode):
    """Make a synchronous HTTP request and surface the response.

    The response body (JSON if parseable, otherwise raw text) and status
    code are stored in the :class:`FlowResult` and optionally written
    back to a named variable in the shared :class:`FlowContext`.

    Security: URLs are validated before each request. Only http(s) schemes
    are accepted, and hosts resolving to loopback, RFC1918, link-local,
    multicast, or the cloud metadata endpoint are rejected (prevents SSRF
    against the local FlintTrade backend or cloud metadata service).
    Redirects are disabled; each hop would need re-validation.

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
            try:
                _validate_public_url(resolved_url)
            except SSRFError as exc:
                return FlowResult.fail(f"HTTPRequestNode blocked: {exc}")

            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
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
