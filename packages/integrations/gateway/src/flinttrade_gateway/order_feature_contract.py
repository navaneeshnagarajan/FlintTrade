"""Pure, versioned evidence records; validation never authorises broker activity.

Documentation, implementation and readiness are independent evidence dimensions.
In particular, native GTT does not depend on native reduce-only. Concrete-looking
records still require the existing safety/runtime gates before any eventual write.
An ``unknown`` product, segment or quantity unit denotes an unresolved scope, never
a wildcard that grants account or instrument eligibility.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from urllib.parse import urlsplit


@dataclass(frozen=True)
class OrderFeatureRecord:
    """Keep source-backed API facts separate from implementation and readiness."""

    schema_version: int
    broker: str
    api_version: str
    checked_on: str
    family: str
    operation: str
    product: str
    segment: str
    documented: str
    implemented: str
    readiness: str
    supported_fields: tuple[str, ...]
    quantity_unit: str
    limitations: tuple[str, ...]
    sources: tuple[str, ...]


def validate_feature_records(records: Sequence[OrderFeatureRecord]) -> None:
    """Raise ``ValueError`` for malformed, contradictory or duplicate records.

    This checks the shape of supplied evidence, not its truth or live safety.
    ``verified`` is representable for future evidence but cannot be inferred by
    this validator. It requires positive support and a resolved record scope.
    Neither acceptance here nor presence in an inventory replaces readiness gates.
    """
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise ValueError("records must be a sequence of OrderFeatureRecord instances")

    identities: set[tuple[str, ...]] = set()
    for index, record in enumerate(records):
        prefix = f"record {index}"
        if not isinstance(record, OrderFeatureRecord):
            raise ValueError(f"{prefix} must be an OrderFeatureRecord")
        if type(record.schema_version) is not int or record.schema_version != 1:
            raise ValueError(f"{prefix} requires schema_version 1")

        for name in (
            "broker", "api_version", "checked_on", "family", "operation", "product", "segment",
            "documented", "implemented", "readiness", "quantity_unit",
        ):
            value = getattr(record, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{prefix} {name} must be a non-empty, trimmed string")

        try:
            checked_on = date.fromisoformat(record.checked_on)
        except ValueError as exc:
            raise ValueError(f"{prefix} checked_on must be an ISO date") from exc
        if checked_on.isoformat() != record.checked_on:
            raise ValueError(f"{prefix} checked_on must use YYYY-MM-DD")
        for name in ("documented", "implemented"):
            if getattr(record, name) not in {"yes", "no", "unknown"}:
                raise ValueError(f"{prefix} {name} must be yes, no or unknown")
        if record.readiness not in {"unverified", "blocked", "verified"}:
            raise ValueError(f"{prefix} readiness must be unverified, blocked or verified")

        for name in ("product", "segment", "quantity_unit"):
            value = getattr(record, name)
            if any(character in value for character in "*?") or value.casefold() in {"all", "any"}:
                raise ValueError(f"{prefix} {name} cannot be a wildcard eligibility grant")

        for name in ("supported_fields", "limitations", "sources"):
            values = getattr(record, name)
            if not isinstance(values, tuple) or any(
                not isinstance(value, str) or not value or value != value.strip() for value in values
            ):
                raise ValueError(f"{prefix} {name} must be a tuple of non-empty, trimmed strings")
            if len(set(values)) != len(values):
                raise ValueError(f"{prefix} {name} contains duplicate entries")
        if not record.sources:
            raise ValueError(f"{prefix} sources must contain evidence links")
        for source in record.sources:
            try:
                parsed = urlsplit(source)
                valid = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            except ValueError as exc:
                raise ValueError(f"{prefix} sources must be valid HTTPS evidence links") from exc
            if not valid or any(character.isspace() for character in source):
                raise ValueError(f"{prefix} sources must be valid HTTPS evidence links without credentials")

        unresolved = any(
            getattr(record, name).casefold() == "unknown"
            for name in ("documented", "implemented", "product", "segment", "quantity_unit")
        )
        if (unresolved or record.readiness == "blocked") and not record.limitations:
            raise ValueError(f"{prefix} limitations must explain unresolved or blocked evidence")
        if record.readiness == "verified" and (
            record.documented != "yes" or record.implemented != "yes" or unresolved
        ):
            raise ValueError(f"{prefix} verified readiness requires positive support and concrete scope")

        identity = (
            record.broker, record.api_version, record.family, record.operation, record.product, record.segment,
        )
        if identity in identities:
            raise ValueError(f"{prefix} duplicate broker/version/family/operation/product/segment")
        identities.add(identity)
