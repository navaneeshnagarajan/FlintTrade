"""Offline regression coverage for HTTP flow-node DNS address validation."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from flinttrade_automation.flow_nodes.base import FlowContext
from flinttrade_automation.flow_nodes.http_node import HTTPRequestNode, SSRFError, _validate_public_url

pytestmark = pytest.mark.unit

_HOST = "flow-target.invalid"
_URL = f"https://{_HOST}/api"
_PRIVATE_ADDRESSES = (
    "127.0.0.1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.0.1",
    "169.254.1.1",
    "169.254.169.254",
    "0.0.0.0",
    "224.0.0.1",
    "240.0.0.1",
    "::1",
    "fc00::1",
    "fe80::1",
    "ff02::1",
    "::",
    "::ffff:127.0.0.1",
)


def _dns_answer(address: str) -> tuple:
    """Construct one getaddrinfo answer without making a DNS request."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    endpoint = (address, 0, 0, 0) if family == socket.AF_INET6 else (address, 0)
    return family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", endpoint


@pytest.mark.parametrize("address", _PRIVATE_ADDRESSES)
@pytest.mark.parametrize("private_first", [True, False], ids=["private-first", "public-first"])
def test_hostname_rejects_any_non_public_dns_answer(address: str, private_first: bool) -> None:
    """A public answer must never mask an unsafe A or AAAA answer."""
    answers = [_dns_answer(address), _dns_answer("8.8.8.8")]
    if not private_first:
        answers.reverse()
    # Replace only this module's socket reference, not the global DNS function.
    with patch("flinttrade_automation.flow_nodes.http_node.socket") as resolver:
        resolver.getaddrinfo.return_value = answers
        with pytest.raises(SSRFError, match="non-public address|cloud metadata endpoint"):
            _validate_public_url(_URL)


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "fc00::1"])
def test_unsafe_dns_blocks_node_before_http_client_and_context_write(address: str) -> None:
    """Rejected hostnames fail closed before request creation or output mutation."""
    context = FlowContext(variables={"response": "unchanged"})
    with (
        patch("flinttrade_automation.flow_nodes.http_node.socket") as resolver,
        patch("httpx.Client") as client,
    ):
        resolver.getaddrinfo.return_value = [_dns_answer(address)]
        result = HTTPRequestNode(url=_URL, output_var="response").execute(context)

    assert result.success is False
    assert result.error is not None and result.error.startswith("HTTPRequestNode blocked:")
    assert result.output is None
    assert context.variables == {"response": "unchanged"}
    client.assert_not_called()


def test_public_ipv4_and_ipv6_answers_keep_http_node_response_contract() -> None:
    """All-public dual-stack hosts still reach the client and publish output."""
    response = MagicMock()
    response.is_success = True
    response.status_code = 200
    response.json.return_value = {"price": 100}
    context = FlowContext()
    with (
        patch("flinttrade_automation.flow_nodes.http_node.socket") as resolver,
        patch("httpx.Client") as client,
    ):
        resolver.getaddrinfo.return_value = [_dns_answer("8.8.8.8"), _dns_answer("2606:4700:4700::1111")]
        client.return_value.__enter__.return_value.request.return_value = response
        result = HTTPRequestNode(url=_URL, output_var="response").execute(context)

    assert result.success is True
    assert result.output == {"price": 100}
    assert result.metadata == {"status_code": 200}
    assert context.get("response") == {"price": 100}


def test_dns_resolution_error_still_fails_closed() -> None:
    """A resolver failure remains a policy rejection before any HTTP request."""
    with patch("flinttrade_automation.flow_nodes.http_node.socket") as resolver:
        resolver.getaddrinfo.side_effect = socket.gaierror("offline resolver failure")
        with pytest.raises(SSRFError, match="could not resolve host"):
            _validate_public_url(_URL)
