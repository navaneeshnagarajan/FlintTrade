"""Portable procedures and scoped lexical recall on the existing MemoryLedger.

The composition root owns writers and independent validation. Model outputs are
candidates, never validation evidence. This module does not mint trading rights.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from flinttrade_ai.knowledge_ingest import validate_package
from flinttrade_ai.memory_ledger import InfluenceReceipt, MemoryDomain, MemoryEvent, MemoryLedger, MemoryQuery
from flinttrade_core.service_providers import EvidenceUseScope, PermissionState, RightsResolution, intersect_rights


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _package(files: Mapping[str, str]) -> tuple[dict[str, str], str]:
    copied = dict(files)
    if not copied or any(
        not isinstance(key, str) or not key or str(PurePosixPath(key)) != key
        or PurePosixPath(key).is_absolute() or ".." in PurePosixPath(key).parts
        or "\\" in key or not isinstance(value, str) for key, value in copied.items()
    ):
        raise ValueError("invalid portable package")
    return copied, _hash({key: hashlib.sha256(value.encode()).hexdigest() for key, value in sorted(copied.items())})


def _merge(old: str, local: str, new: str) -> str | None:
    """Conservative line-based three-way merge; ambiguous overlaps quarantine."""
    base = old.splitlines(keepends=True)
    edits = []
    for text in (local, new):
        changed = text.splitlines(keepends=True)
        for tag, start, end, a, b in difflib.SequenceMatcher(a=base, b=changed, autojunk=False).get_opcodes():
            if tag != "equal":
                edit = (start, end, changed[a:b])
                if edit not in edits:
                    edits.append(edit)
    edits.sort(key=lambda edit: (edit[0], edit[1]))
    for left, right in zip(edits, edits[1:]):
        if right[0] < left[1] or right[0] == left[0]:
            return None
    for start, end, replacement in reversed(edits):
        base[start:end] = replacement
    return "".join(base)


class KnowledgeStore:
    """Immutable packages, quarantined updates and atomic default/run pointers."""

    def __init__(self, ledger: MemoryLedger, *, clock: Callable[[], datetime] | None = None) -> None:
        self.ledger = ledger
        self.clock = clock or (lambda: datetime.now(UTC))

    def _write(self, payload: dict[str, Any], rights: RightsResolution, *, parents: tuple[str, ...] = (),
               expected_head: tuple[str, str | None] | None = None, event_id: str | None = None) -> str:
        identity = event_id or str(uuid4())
        self.ledger.append(MemoryEvent(identity, MemoryDomain.PROCEDURAL, payload, self.clock(),
                                       ("knowledge:curation",), rights=rights, parent_ids=parents),
                           expected_head=expected_head)
        return identity

    def version(self, version_id: str) -> dict[str, Any]:
        """Export exact package bytes and lineage for portability or revalidation."""
        event = self.ledger.get_event(version_id)
        value = event.to_dict()["payload"]
        if value.get("kind") != "skill-version":
            raise ValueError("not a skill version")
        return value

    def stock(self, name: str, version: str, files: Mapping[str, str], rights: RightsResolution) -> str:
        """Snapshot stock bytes once. Reusing a stock identity with new bytes refuses."""
        files, digest = _package(files)
        identity = "stock:" + _hash([name, version])
        payload = {"kind": "skill-version", "name": name, "version": version, "files": files,
                   "package_hash": digest, "origin": "stock", "proposer": "stock", "conflicts": []}
        try:
            previous = self.ledger.get_event(identity)
        except KeyError:
            self._write(payload, rights, event_id=identity)
        else:
            if previous.to_dict()["payload"] != payload or previous.rights != rights:
                raise ValueError("stock version is immutable")
        if self._head("default:" + name) is None:
            self.promote(identity, expected=None)
        return identity

    def propose(self, name: str, files: Mapping[str, str], *, proposer: str,
                source_ref: str, rights: RightsResolution | None = None,
                scope: KnowledgeScope | None = None, evidence_ids: tuple[str, ...] = ()) -> str:
        """Retain a new learned procedure, never infer stock rights or activation.

        Writers and current-rights resolution belong to trusted core owners.
        Repeating the same input is idempotent; changing bytes, rights or scope
        creates a distinct candidate. HTTP/model assertions cannot validate it.
        """
        files, digest = _package(files)
        if not name or not proposer or not source_ref:
            raise ValueError("candidate identity and provenance required")
        validate_package(name, files)
        if rights is None:
            rights = RightsResolution()
        self._check_scope(evidence_ids, asdict(scope) if scope else None)
        payload = {"kind": "skill-version", "name": name, "files": files,
                   "package_hash": digest, "origin": "learned", "proposer": proposer,
                   "source_ref": source_ref, "scope": asdict(scope) if scope else None, "conflicts": []}
        identity = "candidate:" + _hash([payload, rights.to_public_dict(), evidence_ids])
        try:
            self.ledger.get_event(identity)
        except KeyError:
            self._write(payload, rights, parents=evidence_ids, event_id=identity)
        return identity

    def _check_scope(self, parents: tuple[str, ...], scope: dict[str, str] | None) -> None:
        for identity in parents:
            payload = self.ledger.get_event(identity).to_dict()["payload"]
            parent_scope = payload.get("scope")
            if parent_scope is None and "account_id" in payload:
                parent_scope = {key: payload.get(key) for key in ("account_id", "environment", "run_id")}
            if parent_scope is not None and parent_scope != scope:
                raise ValueError("candidate evidence scope mismatch")

    def adapt(self, base: str, files: Mapping[str, str], *, proposer: str,
              scope: KnowledgeScope | None = None, evidence_ids: tuple[str, ...] = (),
              rights: RightsResolution | None = None) -> str:
        """Create an inert adaptation; never edit the stock package."""
        original = self.version(base)
        files, digest = _package(files)
        validate_package(original["name"], files)
        scope_dict = asdict(scope) if scope else original.get("scope")
        self._check_scope((base, *evidence_ids), scope_dict)
        # The bundled licence covers the base, not arbitrary new private/teacher
        # text. Known evidence can supply that ceiling; missing inputs stay unknown.
        if rights is None:
            rights = intersect_rights(*(self.ledger.get_event(identity).rights for identity in evidence_ids))
        return self._write({"kind": "skill-version", "name": original["name"], "files": files,
                            "package_hash": digest, "origin": "adapted", "base": base,
                            "proposer": proposer, "conflicts": [],
                            "scope": scope_dict}, rights, parents=(base, *evidence_ids))

    def rebase(self, local: str, new_base: str) -> str:
        """Merge old base/local/new base; even clean merges require fresh validation."""
        adaptation, new = self.version(local), self.version(new_base)
        old_id = adaptation.get("new_base", adaptation.get("base"))
        if old_id is None or adaptation["name"] != new["name"] or new["origin"] != "stock":
            raise ValueError("rebase needs matching adaptation and stock")
        old = self.version(old_id)
        files, conflicts = {}, []
        for path in sorted(set(old["files"]) | set(adaptation["files"]) | set(new["files"])):
            a, b, c = (version["files"].get(path) for version in (old, adaptation, new))
            merged = c if b == a else b if c == a or b == c else _merge(a, b, c) if None not in (a, b, c) else None
            if merged is None and not (b is None and c == a or c is None and b == a or b is c is None):
                conflicts.append(path)
                merged = b  # retained local bytes are quarantined, not a resolved merge
            if merged is not None:
                files[path] = merged
        files, digest = _package(files)
        return self._write({"kind": "skill-version", "name": new["name"], "files": files,
                            "package_hash": digest, "origin": "adapted", "old_base": old_id,
                            "local": local, "new_base": new_base, "proposer": adaptation["proposer"],
                            "scope": adaptation.get("scope"),
                            "conflicts": conflicts}, self.ledger.get_event(local).rights, parents=(local, new_base))

    def validate(self, candidate: str, *, validator: str, evidence_ref: str) -> str:
        """Record independently supplied validation bound to exact package bytes.

        The trusted evaluator calls this after its checks pass; this is not a
        validator itself and no model-supplied self-report is accepted as authority.
        """
        value = self.version(candidate)
        self._require_eligible(candidate)
        if not validator or validator == value["proposer"] or not evidence_ref:
            raise ValueError("independent validation evidence required")
        if value["conflicts"]:
            raise ValueError("conflicted candidate remains quarantined")
        validate_package(value["name"], value["files"])
        return self._write({"kind": "skill-validation", "candidate": candidate, "validator": validator,
                            "evidence_ref": evidence_ref, "package_hash": value["package_hash"]},
                           self.ledger.get_event(candidate).rights, parents=(candidate,))

    def _head(self, stream: str) -> MemoryEvent | None:
        return next((event for event in reversed(self.ledger.history(MemoryDomain.PROCEDURAL))
                     if isinstance(event.payload, Mapping) and event.payload.get("stream") == stream), None)

    def retire(self, version_id: str, *, reason: str) -> str:
        """Retain rejected/retired bytes and evidence, but refuse future influence."""
        self.version(version_id)
        if not reason:
            raise ValueError("retirement reason required")
        return self._write({"kind": "skill-retirement", "target": version_id, "reason": reason},
                           self.ledger.get_event(version_id).rights, parents=(version_id,))

    def _require_eligible(self, version_id: str) -> None:
        event = self.ledger.get_event(version_id)
        if any(getattr(event.rights.rights, key) is not PermissionState.ALLOWED for key in ("output_use", "retention")):
            raise ValueError("skill rights unresolved")
        if event.payload.get("origin") == "learned" and not event.payload.get("scope"):
            raise ValueError("learned procedure scope required")
        if any(item.payload.get("kind") == "skill-retirement" and item.payload.get("target") == version_id
               for item in self.ledger.history(MemoryDomain.PROCEDURAL)):
            raise ValueError("skill version retired")

    def promote(self, candidate: str, *, expected: str | None) -> str:
        """CAS the default after durable validation, retaining every rollback target."""
        value = self.version(candidate)
        validated = value["origin"] == "stock" or any(
            event.payload.get("kind") == "skill-validation" and event.payload.get("candidate") == candidate
            for event in self.ledger.history(MemoryDomain.PROCEDURAL)
        )
        if not validated:
            raise ValueError("candidate must be validated before becoming default")
        self._require_eligible(candidate)
        stream = "default:" + value["name"] + (":" + _hash(value["scope"]) if value.get("scope") else "")
        head = self._head(stream)
        if (head.payload["target"] if head else None) != expected:
            raise ValueError("default changed")
        return self._write({"kind": "skill-default", "stream": stream, "target": candidate},
                           self.ledger.get_event(candidate).rights, parents=(candidate,),
                           expected_head=(stream, head.event_id if head else None))

    def resolve(self, name: str, *, run_id: str | None = None, scope: KnowledgeScope | None = None) -> str:
        """Resolve an immutable run pin or the current default, never a candidate."""
        scope_dict = asdict(scope) if scope else None
        head = self._head("pin:" + _hash([run_id, name, scope_dict])) if run_id else None
        if head is None and scope is not None:
            head = self._head("default:" + name + ":" + _hash(scope_dict))
        head = head or self._head("default:" + name)
        if head is None:
            raise KeyError(name)
        self._require_eligible(head.payload["target"])
        return head.payload["target"]

    def pin(self, run_id: str, name: str, *, scope: KnowledgeScope | None = None) -> str:
        """Pin once. Default promotion cannot rewrite an already running activity."""
        stream = "pin:" + _hash([run_id, name, asdict(scope) if scope else None])
        head = self._head(stream)
        if head:
            self._require_eligible(head.payload["target"])
            return head.payload["target"]
        target = self.resolve(name, scope=scope)
        self._write({"kind": "skill-pin", "stream": stream, "target": target, "run_id": run_id},
                    self.ledger.get_event(target).rights, parents=(target,), expected_head=(stream, None))
        return target

    def catalogue(self, *, scope: KnowledgeScope | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
        """Describe retained versions without confusing candidates with usable defaults."""
        events = self.ledger.history(MemoryDomain.PROCEDURAL)
        heads = {event.payload["stream"]: event for event in events if "stream" in event.payload}
        retired = {event.payload["target"] for event in events if event.payload.get("kind") == "skill-retirement"}
        validated = {event.payload["candidate"] for event in events if event.payload.get("kind") == "skill-validation"}
        scope_dict = asdict(scope) if scope else None
        result = []
        for event in events:
            value = event.to_dict()["payload"]
            if value.get("kind") != "skill-version" or value.get("scope") not in (None, scope_dict):
                continue
            name = value["name"]
            default = heads.get("default:" + name + (":" + _hash(scope_dict) if scope else ""))
            default = default or heads.get("default:" + name)
            pinned = heads.get("pin:" + _hash([run_id, name, scope_dict])) if run_id else None
            selected = pinned or default
            is_default = default is not None and default.payload["target"] == event.event_id
            is_pinned = pinned is not None and pinned.payload["target"] == event.event_id
            is_validated = value["origin"] == "stock" or event.event_id in validated
            reason = None
            try:
                self._require_eligible(event.event_id)
            except ValueError as error:
                reason = str(error)
            state = ("retired" if event.event_id in retired else "quarantined" if value["conflicts"]
                     else "default" if is_default else "validated" if is_validated else "candidate")
            result.append({"name": name, "version_id": event.event_id, "origin": value["origin"],
                           "package_hash": value["package_hash"], "state": state, "default": is_default,
                           "validated": is_validated, "run_pinned": is_pinned,
                           "enabled": selected is not None and selected.payload["target"] == event.event_id
                           and reason is None and is_validated, "unavailable_reason": reason})
        return result

    def record_context(self, receipt: dict[str, Any]) -> str:
        """Persist exact selected package/chunk hashes before exposing a prompt."""
        parents = tuple(item["version_id"] for item in receipt["skills"])
        rights = self.ledger.get_event(parents[0]).rights if parents else RightsResolution()
        return self._write({"kind": "skill-context", **receipt}, rights, parents=parents)


@dataclass(frozen=True)
class KnowledgeScope:
    """Exact account/environment/run identity, not a symbol-only memory namespace."""

    account_id: str
    environment: str
    run_id: str

    def __post_init__(self) -> None:
        if any(not value or len(value) > 256 for value in asdict(self).values()):
            raise ValueError("complete bounded knowledge scope required")
        if self.environment not in {"paper", "live", "research"}:
            raise ValueError("invalid knowledge environment")


class KnowledgeMemory:
    """Scoped candidate/validation recall; lexical operation needs no embeddings."""

    def __init__(self, ledger: MemoryLedger, scope: KnowledgeScope, *, rights: RightsResolution,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.ledger, self.scope, self.rights = ledger, scope, rights
        self.clock = clock or (lambda: datetime.now(UTC))

    def propose(self, text: str, *, symbol: str, source_ref: str, proposer: str = "reflection") -> str:
        """Persist a quarantined lesson, not immediately influential memory."""
        identity = str(uuid4())
        self.ledger.append(MemoryEvent(identity, MemoryDomain.EPISODIC,
                           {**asdict(self.scope), "kind": "memory-candidate", "text": text,
                            "symbol": symbol, "proposer": proposer}, self.clock(), (source_ref,), rights=self.rights))
        return identity

    def validate(self, candidate: str, *, validator: str, evidence_ref: str) -> str:
        """Publish a separately checked lesson within its original scope/rights."""
        parent = self.ledger.get_event(candidate)
        payload = parent.to_dict()["payload"]
        if payload.get("kind") != "memory-candidate" or any(payload.get(k) != v for k, v in asdict(self.scope).items()):
            raise ValueError("candidate scope mismatch")
        if not validator or validator == payload["proposer"] or not evidence_ref:
            raise ValueError("independent validation evidence required")
        if any(getattr(parent.rights.rights, key) is not PermissionState.ALLOWED for key in ("output_use", "retention")):
            raise ValueError("memory rights unresolved")
        identity = str(uuid4())
        self.ledger.append(MemoryEvent(identity, MemoryDomain.EPISODIC,
                           {**payload, "kind": "validated-memory", "validator": validator, "evidence_ref": evidence_ref},
                           self.clock(), parent.source_refs, rights=self.rights, parent_ids=(candidate,)))
        return identity

    def context(self, symbol: str, query: str, *, max_bytes: int = 4096) -> tuple[str, InfluenceReceipt]:
        """Record exact scoped/as-of/validated influence before returning context."""
        identity = str(uuid4())
        context = self.ledger.read_projection().recall(
            receipt_id=identity, decision_id=identity, request_id=identity, decision_time=self.clock(),
            query=MemoryQuery(domain=MemoryDomain.EPISODIC, text=query, limit=10,
                              minimum_scope=EvidenceUseScope.LIVE_DECISION if self.scope.environment == "live"
                              else EvidenceUseScope.ISOLATED_RESEARCH,
                              metadata_filters=tuple({**asdict(self.scope), "symbol": symbol,
                                                      "kind": "validated-memory"}.items())),
        )
        text = "\n".join(str(event.payload["text"]) for event in context.events)
        if len(text.encode()) > max_bytes:
            raise ValueError("memory context byte budget exceeded")
        return text, context.receipt
