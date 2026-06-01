"""Exception hierarchy for the FlintTrade broker gateway."""

from __future__ import annotations


class GatewayError(Exception):
    """Base exception for all gateway errors.

    Args:
        message: Human-readable description of what went wrong.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class BrokerNotFoundError(GatewayError):
    """Raised when a broker name is not present in the catalogue.

    Args:
        message: Description identifying which broker name was missing.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class AuthFlowError(GatewayError):
    """Raised when the broker authentication flow fails.

    Args:
        message: Description of the auth failure.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class CredentialError(GatewayError):
    """Raised when credential encryption or decryption fails.

    Args:
        message: Description of the credential issue.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class SessionError(GatewayError):
    """Raised on invalid or expired session state.

    Args:
        message: Description of the session problem.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ContractError(GatewayError):
    """Raised when master contract loading or lookup fails.

    Args:
        message: Description of the contract issue.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
