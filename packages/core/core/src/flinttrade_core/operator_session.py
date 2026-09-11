"""Dependency-neutral result of the existing full operator-session verifier."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VerifiedOperatorSession:
    """Opaque identity returned by trusted session verification, not raw claims.

    This DTO is not an authorisation capability by itself. Consumers obtain it
    from their trusted verifier; request deserialisation cannot establish a
    verified session. Authentication and current revocation checks remain with
    the existing auth owner.
    """

    actor_ref: str
    session_binding: str
    scopes: tuple[str, ...]
