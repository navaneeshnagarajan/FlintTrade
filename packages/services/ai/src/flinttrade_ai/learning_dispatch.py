"""Exact-send adapter between the legacy LLM consumer and core learning consent."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from flinttrade_core.learning_consent import (
    DatasetRecord,
    DatasetScope,
    LearningConsentLedger,
    LearningRefused,
    Recipient,
)
from flinttrade_core.service_usage_contracts import TariffSnapshot, UsageAmounts


@dataclass(frozen=True)
class LearningBinding:
    """One explicit grant plus qualified dispatch facts, supplied by the core owner.

    Neither the LLM nor its output constructs this binding. No ambient/default
    grant is selected. A binding is not a send permit: all facts are checked again
    by LearningConsentLedger at each actual transport invocation.
    """

    ledger: LearningConsentLedger
    grant_id: str
    scope: DatasetScope
    recipient: Recipient
    current_recipient: Callable[[], Recipient]
    rights_check: Callable[[dict[str, Any]], bool]
    reservation: Callable[[bytes], UsageAmounts]
    tariff: TariffSnapshot
    controls: Mapping[str, str]
    controls_evidence: str
    run_id: str
    trial_id: str

    def dispatch(self, *, purpose: str, records: tuple[DatasetRecord, ...], endpoint: str,
                 payload: dict[str, Any], send: Callable[[bytes], Any], attempt_id: str | None = None) -> Any:
        """Bind the exact wire bytes and invoke under the latest revocation fence."""
        if endpoint != self.recipient.endpoint or payload.get("model") != self.recipient.model:
            raise LearningRefused("learning destination/model does not match bound recipient")
        # These exact bytes are passed to HTTP, not reserialised independently.
        wire = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        reservation = self.reservation(wire)
        if max(payload.get("max_tokens", 0), payload.get("max_output_tokens", 0)) > reservation.output_tokens:
            raise LearningRefused("learning output bound exceeds reservation")
        batch = self.ledger.batch(self.scope, records, wire, transform=self.scope.transform)
        attempt = attempt_id or str(uuid4())
        return self.ledger.dispatch(grant_id=self.grant_id, batch_id=batch, recipient=self.recipient,
            current_recipient=self.current_recipient, purpose=purpose, operation=self.recipient.method,
            payload=wire, attempt_id=attempt, request_id=attempt, run_id=self.run_id, trial_id=self.trial_id,
            reservation=reservation, tariff=self.tariff, controls=self.controls, controls_evidence=self.controls_evidence,
            rights_check=self.rights_check, send=lambda: send(wire))
