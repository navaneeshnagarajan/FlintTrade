"""Dependency-neutral exact broker identity and credential version values.

Identity resolution does not grant execution authority; order gates own that.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote
from uuid import RFC_4122, UUID

INT64_MAX = (1 << 63) - 1
_ADAPTER = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}", re.ASCII)
_ACCOUNT = re.compile(r"[A-Za-z0-9._:@+\-]{1,128}", re.ASCII)
_ALNUM = re.compile(r"[A-Za-z0-9]", re.ASCII)


class BrokerSelectorValidationError(ValueError):
    """Malformed identity/version; never include an untrusted value."""

    def __init__(self) -> None:
        super().__init__("broker_selector_invalid")


class BrokerTargetRequiredError(ValueError):
    """Neither a complete explicit nor configured target was supplied."""

    def __init__(self) -> None:
        super().__init__("broker_target_required")


@dataclass(frozen=True, order=True)
class BrokerSelector:
    """An opaque, case-sensitive account within an exact routing adapter."""

    adapter_id: str
    account_id: str

    def __post_init__(self) -> None:
        if (
            type(self.adapter_id) is not str
            or not _ADAPTER.fullmatch(self.adapter_id)
            or type(self.account_id) is not str
            or not _ACCOUNT.fullmatch(self.account_id)
            or not _ALNUM.search(self.account_id)
        ):
            raise BrokerSelectorValidationError


@dataclass(frozen=True)
class CredentialVersion:
    """One selector generation in a randomly identified vault incarnation."""

    selector: BrokerSelector
    vault_incarnation: UUID
    generation: int

    def __post_init__(self) -> None:
        _validate_selector(self.selector)
        if (
            type(self.vault_incarnation) is not UUID
            or self.vault_incarnation.version != 4
            or self.vault_incarnation.variant != RFC_4122
            or type(self.generation) is not int
            or not 0 <= self.generation <= INT64_MAX
        ):
            raise BrokerSelectorValidationError


def _validate_selector(selector: object) -> None:
    if type(selector) is not BrokerSelector:
        raise BrokerSelectorValidationError
    selector.__post_init__()


def parse_broker_selector(value: object) -> BrokerSelector:
    """Split only the first colon; remaining colons belong to the account."""
    if type(value) is not str or ":" not in value:
        raise BrokerSelectorValidationError
    return BrokerSelector(*value.split(":", 1))


def serialise_broker_selector(selector: BrokerSelector) -> str:
    """Serialise validated identity without rewriting either component."""
    _validate_selector(selector)
    return selector.adapter_id + ":" + selector.account_id


def broker_selector_from_path(adapter_id: object, account_id: object) -> BrokerSelector:
    """Validate framework-decoded segments, without decoding them again."""
    return BrokerSelector(adapter_id, account_id)


def broker_selector_path_parts(selector: BrokerSelector) -> tuple[str, str]:
    """Encode each component once for use as a URL path segment."""
    _validate_selector(selector)
    return quote(selector.adapter_id, safe=""), quote(selector.account_id, safe="")


def resolve_exact_target(
    configured_selector: str | None,
    explicit_selector: BrokerSelector | None,
) -> BrokerSelector:
    """Prefer a complete explicit target; never combine partial identities."""
    if explicit_selector is not None:
        _validate_selector(explicit_selector)
        return explicit_selector
    if configured_selector is None:
        raise BrokerTargetRequiredError
    return parse_broker_selector(configured_selector)
