"""Factory-owned, expiring qualification of the managed Laya decision path.

There is deliberately no default qualification suite or freshness policy.
Trusted server composition supplies reviewed cases and an explicit lifetime;
HTTP requests cannot supply verdicts, runtime identities or acceptance records.
Synthetic cases establish engineering correspondence, not model quality or
broker eligibility. This owner never changes the operator's mode or starts a
model. The existing runtime must already own its verified local process.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from flask import Flask

from flinttrade_engine import laya_decision
from flinttrade_engine.laya import DecisionStatus, Laya, process_laya
from flinttrade_engine.laya_decision import LayaPolicy, evaluate_free_text

from .backend_instance import require_backend_lease_proof
from .laya_runtime import LayaRuntime, process_runtime

Case = tuple[str, str, str, str]


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _sources() -> str:
    from flinttrade_engine import laya, laya_decision

    paths = (Path(__file__), Path(laya.__file__), Path(laya_decision.__file__),
             Path(__file__).with_name("laya_runtime.py"))
    return _digest([(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths])


class LayaQualificationOwner:
    """Retain successful checks for one factory, gate, runtime and configuration.

    Args:
        app: The normal factory whose safety and backend lease remain authoritative.
        gate: The same process-wide gate used by canonical order admission.
    """

    def __init__(self, app: Flask, gate: Laya) -> None:
        self.app = app
        self.gate = gate
        self._cases: tuple[Case, ...] = ()
        self._max_age = 0.0
        self._generation = 0
        self._record: dict[str, Any] | None = None
        self._binding: tuple[object, ...] | None = None
        self._expires = 0.0
        self._lock = threading.RLock()

    def configure(self, *, cases: tuple[Case, ...], max_age_seconds: float) -> None:
        """Install explicit reviewed cases; replacement retires earlier evidence.

        Args:
            cases: Unique identity, action, note and expected effect for each case.
            max_age_seconds: Explicit finite positive lifetime, never a default.

        Raises:
            ValueError: The suite lacks positive/refusal coverage or finite bounds.
        """
        if (type(cases) is not tuple or not cases or len(cases) > 1000
                or type(max_age_seconds) not in (int, float)
                or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
            raise ValueError("explicit bounded Laya qualification policy required")
        for case in cases:
            if (type(case) is not tuple or len(case) != 4
                    or any(type(value) is not str or not value.strip() for value in case)
                    or case[1] not in {"BUY", "SELL"} or not 0 < len(case[2]) <= 4000
                    or case[3] not in {"allow", "deny"}):
                raise ValueError("exact labelled Laya qualification cases required")
        if len({case[0] for case in cases}) != len(cases) or {case[3] for case in cases} != {"allow", "deny"}:
            raise ValueError("distinct positive and refusal qualification cases required")
        with self._lock:
            self._cases, self._max_age = cases, float(max_age_seconds)
            self.retire()

    def retire(self) -> None:
        """Retire entry evidence without stopping a runtime or releasing duties."""
        with self._lock:
            self._generation += 1
            self._record = None
            self._binding = None
            self._expires = 0.0

    def _current_binding(self) -> tuple[object, ...]:
        proof = require_backend_lease_proof(self.app.config.get("BACKEND_LEASE_PROOF"))
        runtime = process_runtime()
        if (self.app.config.get("LAYA_QUALIFICATION_OWNER") is not self or process_laya() is not self.gate
                or not self.gate.qualification_owner_is(self)
                or self.app.config.get("RUNTIME_ACCEPTING_REQUESTS", True) is not True
                or type(runtime) is not LayaRuntime or runtime.workspace_dir != Path(self.app.config["WORKSPACE_DIR"])):
            raise ValueError("Laya qualification owner replaced or retired")
        safety = self.app.config["SAFETY"]
        kill = safety.l5_kill
        if kill.is_active:
            raise ValueError("Laya qualification retired by kill")
        policy = laya_decision.load_policy()
        return (runtime, runtime.qualification_identity(self.gate), safety, kill, kill.activation_sequence,
                _digest(asdict(policy)), _sources(), self._generation, _digest([self._cases, self._max_age]), proof)

    def qualifies(self, policy: LayaPolicy | None = None) -> bool:
        """Recheck exact current custody; a DTO or stale successful report cannot admit.

        Args:
            policy: Optional policy whose digest must also match the retained qualification binding.

        Returns:
            Whether the same unexpired owner, runtime, policy and configuration still qualify.
        """
        with self._lock:
            record, binding, expires = self._record, self._binding, self._expires
        if record is None or binding is None or time.monotonic() >= expires:
            return False
        try:
            current = self._current_binding()
            valid = current == binding and (policy is None or _digest(asdict(policy)) == current[5])
        except Exception:
            valid = False
        with self._lock:
            if self._record is not record or self._binding is not binding or time.monotonic() >= self._expires:
                return False
            if not valid:
                self.retire()
            return valid

    def capture(self) -> object:
        """Retain the exact successful evidence for a single downstream command.

        Returns:
            The exact retained successful record object, not a caller-constructible report.

        Raises:
            ValueError: No current qualification exists; a JSON report is not accepted.
        """
        with self._lock:
            record = self._record
        if not self.qualifies():
            raise ValueError("current Laya qualification required")
        with self._lock:
            if record is None or self._record is not record:
                raise ValueError("Laya qualification changed during capture")
            return record

    def revalidate(self, captured: object) -> None:
        """Refuse stale command evidence, including retirement then requalification.

        Args:
            captured: Original record object retained by capture for this command.

        Raises:
            ValueError: Qualification retired or its exact record object was replaced.
        """
        if not self.qualifies():
            raise ValueError("Laya qualification retired")
        with self._lock:
            if captured is not self._record:
                raise ValueError("Laya qualification replaced")

    def qualify(self, *, verify_authority: Callable[[], None] | None = None) -> dict[str, Any]:
        """Run the real decision parser against every configured labelled case.

        Returns:
            Measured effects and exact version bindings. A failed check is retained
            as a rejected report, never as entry authority.

        Raises:
            ValueError: No policy, managed runtime, current owner or healthy process.
        """
        with self._lock:
            self.retire()
            if not self._cases:
                raise ValueError("Laya qualification policy is not configured")
            cases, generation, max_age = self._cases, self._generation, self._max_age
        if verify_authority is not None:
            verify_authority()
        before = self._current_binding()
        if before[7] != generation:
            raise ValueError("Laya qualification configuration changed")
        runtime = process_runtime()
        assert type(runtime) is LayaRuntime
        policy = laya_decision.load_policy()
        deadline = time.monotonic() + max_age
        # No owner lock is held over external HTTP. Configure/retire/kill remain
        # available; final identity comparison rejects their late completion.
        if runtime.publish_status() is not DecisionStatus.READY:
            raise ValueError("Laya runtime is not healthy")
        client = runtime.qualification_client(self.gate)
        effects: list[str] = []
        for _identity, action, note, _expected in cases:
            if verify_authority is not None:
                verify_authority()
            if time.monotonic() >= deadline or self._current_binding() != before:
                raise ValueError("Laya qualification expired or changed during measurement")
            decision = evaluate_free_text(mode="live", action=action, rationale=note,
                                          requested_quantity=1, degraded_ceiling=1, client=client, policy=policy)
            effects.append(decision.effect)
        after = self._current_binding()
        with self._lock:
            if verify_authority is not None:
                verify_authority()
            if after != before or self._generation != generation or time.monotonic() >= deadline:
                raise ValueError("Laya qualification expired or changed before publication")
            qualified = effects == [case[3] for case in cases]
            report = {"qualified": qualified, "observed_effects": effects,
                      "model_revision": policy.revision, "policy_revision": before[5],
                      "source_revision": before[6], "config_revision": before[8],
                      "runtime_revision": before[1], "case_ids": [case[0] for case in cases]}
            if qualified:
                self._record, self._binding, self._expires = report, before, deadline
        # Status is derived through the original health publisher, not set by a
        # caller-provided success flag or a constructed qualification DTO.
        runtime.publish_status()
        return json.loads(json.dumps(report))


def install_laya_qualification(app: Flask) -> LayaQualificationOwner:
    """Install an unconfigured owner on the normal factory's process-wide gate.

    Args:
        app: Normal factory whose process-wide gate receives the unconfigured owner.

    Returns:
        The same owner stored in app configuration and bound to the existing gate.
    """
    gate = process_laya()
    owner = LayaQualificationOwner(app, gate)
    app.config["LAYA_QUALIFICATION_OWNER"] = owner
    gate.bind_qualification_owner(owner)
    return owner
