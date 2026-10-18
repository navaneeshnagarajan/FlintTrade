"""Shared acquisition leases over existing, explicitly injected read/feed owners.

No credential store, provider discovery, implicit failover or execution routing
lives here. A binding's authorised callback must revalidate the existing read
grant. An open_feed callback returns its actual close handle; retired callbacks
cannot publish into a replacement. The owner creates no worker or timer.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from flinttrade_core.data_contracts import (
    DataIntegrityError,
    canonical_json,
    finite_number,
    generation,
    text,
    timestamp,
    validate_identity,
    validate_scope,
    validate_source,
)


@dataclass
class _Binding:
    descriptor: dict[str, Any]
    open_feed: Callable[[Callable[[dict[str, Any]], bool]], Callable[[], None]]
    authorised: Callable[[], bool]
    max_age: float
    lease_seconds: float
    token: object | None = None
    stop: Callable[[], None] | None = None
    leases: set[str] = field(default_factory=set)
    frame: dict[str, Any] | None = None
    updates: deque = field(default_factory=lambda: deque(maxlen=128))
    reason: str = "awaiting_snapshot"
    reconnect_limit: int = 0
    reconnect_attempts: int = 0
    opening: bool = False


class SharedAcquisition:
    """One acquisition per exact configured dataset, shared by view leases."""

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._bindings: dict[str, _Binding] = {}
        self._leases: dict[str, tuple[_Binding, float]] = {}
        self._closed = False
        self._retiring: dict[str, Callable | None] = {}
        self._stopping: set[str] = set()

    def register(self, dataset_id: str, *, identity: dict[str, Any], source: dict[str, Any], scope: dict[str, Any],
                 policy_revision: str, max_age_seconds: float, lease_seconds: float,
                 open_feed: Callable[[Callable[[dict[str, Any]], bool]], Callable[[], None]],
                 authorised: Callable[[], bool], reconnect_limit: int = 0) -> None:
        """Bind an existing reader. Rebinding retires all old view generations."""
        text(dataset_id, "dataset_id")
        descriptor = {"dataset_id": dataset_id, "identity": validate_identity(identity),
                      "source": validate_source(source), "scope": validate_scope(scope),
                      "policy_revision": text(policy_revision, "policy_revision")}
        maximum = finite_number(max_age_seconds, "max_age_seconds", positive=True)
        lifetime = finite_number(lease_seconds, "lease_seconds", positive=True)
        generation(reconnect_limit)
        with self._lock:
            if self._closed or dataset_id in self._retiring:
                raise RuntimeError("acquisition owner closed or retirement pending")
            previous = self._bindings.get(dataset_id)
            stop = self._retire(previous) if previous else None
            self._bindings[dataset_id] = _Binding(descriptor, open_feed, authorised, maximum, lifetime,
                                                   reconnect_limit=reconnect_limit)
        if stop:
            stop()

    def acquire(self, dataset_id: str, *, scope: dict[str, Any]) -> dict[str, Any]:
        """Lease the configured dataset, never select a replacement on failure."""
        self.expire()
        with self._lock:
            if self._closed or dataset_id in self._retiring:
                raise RuntimeError("acquisition owner closed or retirement pending")
            binding = self._bindings[dataset_id]
            self._check(binding, scope)
            lease_id = uuid.uuid4().hex
            binding.leases.add(lease_id)
            self._leases[lease_id] = (binding, self._clock() + binding.lease_seconds)
            start = binding.token is None
            if start:
                binding.opening = True
                binding.token = object()
                binding.frame = None
                binding.updates.clear()
                binding.reason = "awaiting_snapshot"
            token = binding.token
        if start:
            try:
                stop = binding.open_feed(lambda frame: self._publish(binding, token, frame))
                if not callable(stop):
                    raise TypeError("feed owner did not return a close handle")
                with self._lock:
                    binding.opening = False
                    retired = binding.token is not token
                    if not retired:
                        binding.stop = stop
                if retired:
                    self._finish_stop(binding, stop)()
            except Exception:
                with self._lock:
                    if binding.token is token:
                        binding.token = object()  # fence even late callbacks from a failed opener
                        binding.reason = "acquisition_failed"
        return {"lease_id": lease_id, "snapshot": self.read(lease_id, scope=scope)}

    def _check(self, binding: _Binding, scope: dict[str, Any]) -> None:
        if validate_scope(scope) != binding.descriptor["scope"]:
            raise PermissionError("data scope mismatch")
        if not self._authorised(binding):
            raise PermissionError("data authority retired")

    def _publish(self, binding: _Binding, token: object, raw: dict[str, Any]) -> bool:
        with self._lock:
            if binding.token is not token or not binding.leases:
                return False
            try:
                self._check(binding, binding.descriptor["scope"])
                frame = json.loads(canonical_json(raw))
                generation(frame["sequence"])
                if frame["kind"] == "unavailable" and frame.get("reason") == "source_unavailable":
                    binding.reason = "source_unavailable"
                    return False
                if frame["kind"] not in ("snapshot", "update"):
                    raise DataIntegrityError("unknown update kind")
                observed, retrieved = timestamp(frame["observed_at"]), timestamp(frame["retrieved_at"])
                if observed > retrieved or retrieved.timestamp() > self._clock():
                    raise DataIntegrityError("retrieval precedes observation")
                if frame.get("published_at") is not None and timestamp(frame["published_at"]) > retrieved:
                    raise DataIntegrityError("retrieval precedes publication")
                if "payload" not in frame:
                    raise DataIntegrityError("missing observation payload")
                previous = binding.frame
                if previous and frame["sequence"] <= previous["sequence"]:
                    if frame != previous:
                        binding.reason = "sequence_conflict"
                    return False
                if frame["kind"] == "update" and (
                    previous is None or binding.reason or frame["sequence"] != previous["sequence"] + 1
                ):
                    binding.reason = "resync_required"
                    return False
                binding.frame = frame
                binding.reason = ""
                binding.updates.append(frame)
                return True
            except PermissionError:
                binding.reason = "authority_retired"
                return False
            except (ValueError, TypeError, KeyError):
                binding.reason = "invalid_observation"
                return False

    def read(self, lease_id: str, *, scope: dict[str, Any], after_sequence: int | None = None) -> dict[str, Any]:
        """Return detached snapshot plus ordered updates and explicit replay loss."""
        with self._lock:
            if lease_id in self._leases:
                self._check(self._leases[lease_id][0], scope)
        self.expire()
        with self._lock:
            binding, expires_at = self._leases[lease_id]
            self._check(binding, scope)
            frame = binding.frame
            age = None if frame is None else max(0.0, self._clock() - timestamp(frame["observed_at"]).timestamp())
            status = "unavailable" if age is None else "stale" if binding.reason or age > binding.max_age else "fresh"
            updates = []
            replay_gap = False
            if after_sequence is not None:
                generation(after_sequence)
                updates = [entry for entry in binding.updates if entry["sequence"] > after_sequence]
                replay_gap = bool(updates and updates[0]["sequence"] > after_sequence + 1)
            return json.loads(canonical_json({
                **binding.descriptor, "status": status, "reason": binding.reason or ("expired" if status == "stale" else ""),
                "age_seconds": age, "expires_at": expires_at, "sequence": None if frame is None else frame["sequence"],
                "observed_at": None if frame is None else frame["observed_at"],
                "published_at": None if frame is None else frame.get("published_at"),
                "retrieved_at": None if frame is None else frame["retrieved_at"],
                "payload": None if frame is None else frame["payload"], "updates": updates, "replay_gap": replay_gap,
            }))

    def release(self, lease_id: str, *, scope: dict[str, Any]) -> bool:
        """Close a view; only the last lease releases the acquired resource."""
        with self._lock:
            entry = self._leases.get(lease_id)
            if entry is None:
                return False
            binding = entry[0]
            # Revocation must not stop a caller from releasing its own lease.
            if validate_scope(scope) != binding.descriptor["scope"]:
                raise PermissionError("data scope mismatch")
            del self._leases[lease_id]
            binding.leases.remove(lease_id)
            stop = self._retire(binding) if not binding.leases else None
        if stop:
            stop()
        return True

    def _retire(self, binding: _Binding) -> Callable | None:
        binding.token = None
        for lease_id in binding.leases:
            self._leases.pop(lease_id, None)
        binding.leases.clear()
        binding.frame = None
        binding.updates.clear()
        binding.reason = "retired"
        stop, binding.stop = binding.stop, None
        if binding.opening:
            self._retiring[binding.descriptor["dataset_id"]] = None
        return self._finish_stop(binding, stop) if stop else None

    def _finish_stop(self, binding: _Binding, stop: Callable) -> Callable:
        dataset_id = binding.descriptor["dataset_id"]
        self._retiring[dataset_id] = stop
        return lambda: self._run_stop(dataset_id, stop)

    def _run_stop(self, dataset_id: str, stop: Callable) -> None:
        with self._lock:
            if self._retiring.get(dataset_id) is not stop:
                return
            if dataset_id in self._stopping:
                raise RuntimeError("acquisition retirement already draining")
            self._stopping.add(dataset_id)
        try:
            stop()
            with self._lock:
                if self._retiring.get(dataset_id) is stop:
                    del self._retiring[dataset_id]
        finally:
            with self._lock:
                self._stopping.discard(dataset_id)

    def _retry_retirements(self) -> None:
        with self._lock:
            pending = list(self._retiring.items())
        errors = []
        for dataset_id, stop in pending:
            if stop is not None:
                try:
                    self._run_stop(dataset_id, stop)
                except Exception as error:
                    errors.append(error)
        if errors:
            raise RuntimeError("acquisition source still draining") from errors[0]

    def expire(self) -> None:
        """Release expired leases on owner activity; no unowned background timer."""
        self._retry_retirements()
        with self._lock:
            expired = [(key, entry[0].descriptor["scope"]) for key, entry in self._leases.items()
                       if entry[1] <= self._clock() or not self._authorised(entry[0])]
        for lease_id, scope in expired:
            self.release(lease_id, scope=scope)

    def close(self) -> None:
        """Drain all owned feeds, fencing callbacks before closing resources."""
        with self._lock:
            self._closed = True
            for binding in self._bindings.values():
                self._retire(binding)
        self._retry_retirements()
        with self._lock:
            if self._retiring:
                raise RuntimeError("acquisition retirement still pending")

    @staticmethod
    def _authorised(binding: _Binding) -> bool:
        try:
            return binding.authorised() is True
        except Exception:
            return False

    def reconnect(self, lease_id: str, *, scope: dict[str, Any]) -> bool:
        """Bounded same-feed reconnect; success requires a new snapshot.

        This cannot switch providers, restart workers or replay executions.
        """
        with self._lock:
            binding = self._leases[lease_id][0]
            self._check(binding, scope)
            if (binding.reconnect_attempts >= binding.reconnect_limit or binding.opening
                    or binding.descriptor["dataset_id"] in self._retiring):
                return False
            binding.reconnect_attempts += 1
            token = binding.token = object()
            stop, binding.stop = binding.stop, None
            binding.opening = True
            binding.reason = "resync_required"
        if stop:
            self._finish_stop(binding, stop)()
        try:
            close = binding.open_feed(lambda frame: self._publish(binding, token, frame))
            if not callable(close):
                raise TypeError("feed owner did not return a close handle")
            with self._lock:
                binding.opening = False
                retired = binding.token is not token
                if not retired:
                    binding.stop = close
                fresh = not retired and not binding.reason
            if retired:
                self._finish_stop(binding, close)()
            return fresh
        except Exception:
            with self._lock:
                binding.opening = False
                if binding.token is token:
                    binding.token = object()
                    binding.reason = "reconnect_failed"
            return False

    def diagnostics(self) -> dict[str, Any]:
        """Measured process-local ownership counts, not real provider capacity."""
        try:
            self.expire()
        except RuntimeError:
            # Counts must remain observable when exact-source cleanup is pending.
            pass
        with self._lock:
            return {"status": "degraded" if self._retiring else "available", "scope": "process",
                    "configured_datasets": len(self._bindings),
                    "active_acquisitions": sum(item.token is not None for item in self._bindings.values()),
                    "leases": len(self._leases), "retirement_pending": len(self._retiring),
                    "provider_capacity": None, "provider_capacity_status": "unmeasured"}
