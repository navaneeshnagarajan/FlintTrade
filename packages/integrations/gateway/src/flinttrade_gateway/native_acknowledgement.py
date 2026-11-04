"""Observed native identifiers from an unqualified post-dispatch outcome.

This exception never signals success, completeness or safe retry. The existing
writer records it only inside its actual completion frame and keeps the attempt
unknown. A constructible exception alone is not provenance or authority.
"""
from __future__ import annotations

from typing import Any

from flinttrade_core.exceptions import BrokerError


class UncertainNativeAcknowledgement(BrokerError):
    """Retain observed IDs without inventing a complete related-order set."""

    def __init__(self, message: str, *, broker_id: str, rows: Any) -> None:
        super().__init__(message, broker_id=broker_id)
        observations = [rows] if type(rows) is dict else rows if type(rows) is list else []
        self.observed_order_ids = tuple(
            row["orderId"] for row in observations
            if type(row) is dict and type(row.get("orderId")) is str and row["orderId"]
            and row["orderId"] == row["orderId"].strip() and row["orderId"].isprintable()
            and not any(char.isspace() for char in row["orderId"])
        )
