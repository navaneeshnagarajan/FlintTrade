"""TDD tests for gateway exception hierarchy."""

from __future__ import annotations

import pytest

from exceptions import (
    GatewayError,
    BrokerNotFoundError,
    AuthFlowError,
    CredentialError,
    SessionError,
    ContractError,
)


# ---------------------------------------------------------------------------
# GatewayError (base)
# ---------------------------------------------------------------------------


class TestGatewayError:
    def test_message_attribute(self) -> None:
        exc = GatewayError("something went wrong")
        assert exc.message == "something went wrong"

    def test_str_returns_message(self) -> None:
        exc = GatewayError("something went wrong")
        assert str(exc) == "something went wrong"

    def test_is_exception(self) -> None:
        assert issubclass(GatewayError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(GatewayError, match="base error"):
            raise GatewayError("base error")


# ---------------------------------------------------------------------------
# BrokerNotFoundError
# ---------------------------------------------------------------------------


class TestBrokerNotFoundError:
    def test_message_attribute(self) -> None:
        exc = BrokerNotFoundError("broker 'unknown_broker' not in catalog")
        assert exc.message == "broker 'unknown_broker' not in catalog"

    def test_str_returns_message(self) -> None:
        exc = BrokerNotFoundError("broker 'unknown_broker' not in catalog")
        assert str(exc) == "broker 'unknown_broker' not in catalog"

    def test_subclasses_gateway_error(self) -> None:
        assert issubclass(BrokerNotFoundError, GatewayError)

    def test_caught_as_gateway_error(self) -> None:
        with pytest.raises(GatewayError):
            raise BrokerNotFoundError("not found")

    def test_caught_as_specific_type(self) -> None:
        with pytest.raises(BrokerNotFoundError):
            raise BrokerNotFoundError("not found")


# ---------------------------------------------------------------------------
# AuthFlowError
# ---------------------------------------------------------------------------


class TestAuthFlowError:
    def test_message_attribute(self) -> None:
        exc = AuthFlowError("TOTP verification failed")
        assert exc.message == "TOTP verification failed"

    def test_str_returns_message(self) -> None:
        exc = AuthFlowError("TOTP verification failed")
        assert str(exc) == "TOTP verification failed"

    def test_subclasses_gateway_error(self) -> None:
        assert issubclass(AuthFlowError, GatewayError)

    def test_caught_as_gateway_error(self) -> None:
        with pytest.raises(GatewayError):
            raise AuthFlowError("auth failed")

    def test_caught_as_specific_type(self) -> None:
        with pytest.raises(AuthFlowError):
            raise AuthFlowError("auth failed")


# ---------------------------------------------------------------------------
# CredentialError
# ---------------------------------------------------------------------------


class TestCredentialError:
    def test_message_attribute(self) -> None:
        exc = CredentialError("Fernet decryption failed: invalid token")
        assert exc.message == "Fernet decryption failed: invalid token"

    def test_str_returns_message(self) -> None:
        exc = CredentialError("Fernet decryption failed: invalid token")
        assert str(exc) == "Fernet decryption failed: invalid token"

    def test_subclasses_gateway_error(self) -> None:
        assert issubclass(CredentialError, GatewayError)

    def test_caught_as_gateway_error(self) -> None:
        with pytest.raises(GatewayError):
            raise CredentialError("bad key")

    def test_caught_as_specific_type(self) -> None:
        with pytest.raises(CredentialError):
            raise CredentialError("bad key")


# ---------------------------------------------------------------------------
# SessionError
# ---------------------------------------------------------------------------


class TestSessionError:
    def test_message_attribute(self) -> None:
        exc = SessionError("session token has expired")
        assert exc.message == "session token has expired"

    def test_str_returns_message(self) -> None:
        exc = SessionError("session token has expired")
        assert str(exc) == "session token has expired"

    def test_subclasses_gateway_error(self) -> None:
        assert issubclass(SessionError, GatewayError)

    def test_caught_as_gateway_error(self) -> None:
        with pytest.raises(GatewayError):
            raise SessionError("expired")

    def test_caught_as_specific_type(self) -> None:
        with pytest.raises(SessionError):
            raise SessionError("expired")


# ---------------------------------------------------------------------------
# ContractError
# ---------------------------------------------------------------------------


class TestContractError:
    def test_message_attribute(self) -> None:
        exc = ContractError("master contract file not found for NFO")
        assert exc.message == "master contract file not found for NFO"

    def test_str_returns_message(self) -> None:
        exc = ContractError("master contract file not found for NFO")
        assert str(exc) == "master contract file not found for NFO"

    def test_subclasses_gateway_error(self) -> None:
        assert issubclass(ContractError, GatewayError)

    def test_caught_as_gateway_error(self) -> None:
        with pytest.raises(GatewayError):
            raise ContractError("missing contract")

    def test_caught_as_specific_type(self) -> None:
        with pytest.raises(ContractError):
            raise ContractError("missing contract")


# ---------------------------------------------------------------------------
# Cross-hierarchy: no accidental aliases
# ---------------------------------------------------------------------------


class TestExceptionIsolation:
    def test_different_exceptions_are_not_interchangeable(self) -> None:
        with pytest.raises(BrokerNotFoundError):
            try:
                raise BrokerNotFoundError("not found")
            except AuthFlowError:
                pytest.fail("AuthFlowError should not catch BrokerNotFoundError")

    def test_all_subclass_gateway_error(self) -> None:
        for cls in (
            BrokerNotFoundError,
            AuthFlowError,
            CredentialError,
            SessionError,
            ContractError,
        ):
            assert issubclass(cls, GatewayError), f"{cls.__name__} must subclass GatewayError"

    def test_none_are_aliases_of_each_other(self) -> None:
        classes = [
            BrokerNotFoundError,
            AuthFlowError,
            CredentialError,
            SessionError,
            ContractError,
        ]
        for i, cls_a in enumerate(classes):
            for cls_b in classes[i + 1 :]:
                assert cls_a is not cls_b, f"{cls_a.__name__} must not be the same as {cls_b.__name__}"
