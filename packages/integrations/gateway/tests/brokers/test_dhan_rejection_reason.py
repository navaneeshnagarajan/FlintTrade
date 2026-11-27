from __future__ import annotations

import pytest

from flinttrade_core.order_routes import _http_broker_error_fields
from flinttrade_gateway.brokers.dhan_mapping import (
    STATIC_IP_OR_SEGMENT,
    STATIC_IP_REJECTED,
    DhanApiRejection,
    DhanMappingError,
    dhan_rejection_reason,
    unwrap,
)


def _failure(code: str, message: str) -> dict:
    return {
        "status": "failure",
        "remarks": {"error_code": code, "error_type": "Input_Exception", "error_message": message},
    }


@pytest.mark.parametrize(
    ("code", "message", "reason"),
    [
        ("DH-905", "Invalid IP", STATIC_IP_REJECTED),
        ("DH-905", "invalid ip", STATIC_IP_REJECTED),
        ("DH-906", "Order not allowed: IP address is not whitelisted", STATIC_IP_REJECTED),
        ("DH-901", "Static-IP mismatch", STATIC_IP_REJECTED),
        ("DH-903", "IPs not registered", STATIC_IP_REJECTED),
        ("DH-903", "Account segment not active", STATIC_IP_OR_SEGMENT),
        ("dh-903", "", STATIC_IP_OR_SEGMENT),
        ("DH-905", "Missing required fields, bad values for parameters etc.", None),
        ("DH-905", "Invalid ship-to zip", None),
        ("DH-905", "Tip: check the IPO window", None),
        ("DH-1001", "Invalid IP", None),
        ("", "Invalid IP", None),
    ],
)
def test_dhan_rejection_reason(code: str, message: str, reason: str | None) -> None:
    assert dhan_rejection_reason(code, message) == reason


def test_ip_rejection_shows_sentence_above_dhan_message() -> None:
    with pytest.raises(DhanApiRejection) as caught:
        unwrap(_failure("DH-905", "Invalid IP"))
    assert str(caught.value) == f"{STATIC_IP_REJECTED}\nInvalid IP"
    assert (caught.value.broker_code, caught.value.broker_message) == ("DH-905", "Invalid IP")


def test_bare_dh903_points_at_static_ip_and_segment() -> None:
    with pytest.raises(DhanApiRejection) as caught:
        unwrap(_failure("DH-903", "Account not active"))
    assert str(caught.value) == f"{STATIC_IP_OR_SEGMENT}\nAccount not active"


def test_bare_dh905_stays_an_input_error() -> None:
    with pytest.raises(DhanMappingError) as caught:
        unwrap(_failure("DH-905", "Missing required fields"))
    assert caught.value.reason is None
    assert str(caught.value) == "Dhan API error: Missing required fields"
    assert "static IP" not in str(caught.value)


def test_other_dh_code_with_ip_text() -> None:
    with pytest.raises(DhanApiRejection) as caught:
        unwrap(_failure("DH-906", "Request IP not registered"))
    assert caught.value.reason == STATIC_IP_REJECTED


def test_route_fields_carry_sentence_and_dhan_message() -> None:
    exc = DhanApiRejection("DH-905", "Invalid IP", "Invalid IP")
    assert _http_broker_error_fields(exc, "dhan") == {
        "broker_code": "DH-905",
        "broker_message": "Invalid IP",
        "broker_reason": STATIC_IP_REJECTED,
    }
    assert _http_broker_error_fields(exc, "kotakneo") == {}


def test_route_fields_omit_sentence_for_input_error() -> None:
    exc = DhanApiRejection("DH-905", "Missing required fields", "Missing required fields")
    assert _http_broker_error_fields(exc, "dhan") == {
        "broker_code": "DH-905",
        "broker_message": "Missing required fields",
    }
