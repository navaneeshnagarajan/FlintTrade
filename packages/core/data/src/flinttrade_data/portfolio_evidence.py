"""Read-only portfolio facts from explicit CSV imports and manual records.

Uses a caller-owned SQLite connection, not a broker/sandbox ledger or another
backend. The caller owns secure storage, authorisation and connection lifetime.
No NAV source, inference or price feed can construct private holdings here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import threading
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from flinttrade_core.data_contracts import canonical_json, digest, text, timestamp, validate_scope


class EvidenceConflict(ValueError):
    """A source record identity already has different immutable evidence."""


def _decimal(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("quantities and cash must be exact decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not number.is_finite() or len(value) > 128:
        raise ValueError("invalid decimal")
    return str(number)


class PortfolioEvidence:
    """Append and read exact-account declared facts, without execution authority."""

    def __init__(self, connection: sqlite3.Connection, *, initialise: bool = True) -> None:
        if connection.in_transaction:
            raise RuntimeError("portfolio evidence requires an idle owned connection")
        self._connection = connection
        self._lock = threading.RLock()
        if not initialise:
            expected = {"portfolio_evidence": ("scope_id", "record_key", "document", "record_hash"),
                        "portfolio_evidence_batches": ("batch_id", "document")}
            for table, columns in expected.items():
                found = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table})"))
                if found != columns:
                    raise RuntimeError("portfolio evidence schema unavailable")
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise RuntimeError("portfolio evidence integrity unavailable")
            try:
                members = set()
                fields = ("record_id", "kind", "instrument_id", "venue", "currency", "quantity_unit",
                          "quantity", "observed_at", "cash_amount")
                for batch_id, document in connection.execute("SELECT batch_id, document FROM portfolio_evidence_batches"):
                    batch = json.loads(document)
                    if digest(batch) != batch_id:
                        raise ValueError("batch checksum mismatch")
                    scope_id = digest(validate_scope(batch["scope"]))
                    for row in batch["records"]:
                        key = digest({"source_id": batch["source_id"], "record_id": row["record_id"],
                                      "kind": row["kind"], "observed_at": row["observed_at"]})
                        members.add((scope_id, key, digest(row), batch["origin"], batch["input_sha256"]))
                for scope_id, key, document, expected_hash in connection.execute(
                    "SELECT scope_id, record_key, document, record_hash FROM portfolio_evidence"
                ):
                    fact = json.loads(document)
                    member = (scope_id, key, digest({field: fact[field] for field in fields}),
                              fact["origin"], fact["input_sha256"])
                    expected_key = digest({"source_id": fact["source_id"], "record_id": fact["record_id"],
                                           "kind": fact["kind"], "observed_at": fact["observed_at"]})
                    if digest(fact) != expected_hash or key != expected_key or member not in members:
                        raise ValueError("fact checksum or scoped batch membership mismatch")
            except (ValueError, TypeError, KeyError):
                raise RuntimeError("portfolio evidence integrity unavailable") from None
            return
        connection.execute("CREATE TABLE IF NOT EXISTS portfolio_evidence "
                           "(scope_id TEXT NOT NULL, record_key TEXT NOT NULL, document TEXT NOT NULL, "
                           "record_hash TEXT NOT NULL, "
                           "PRIMARY KEY(scope_id, record_key))")
        connection.execute("CREATE TABLE IF NOT EXISTS portfolio_evidence_batches "
                           "(batch_id TEXT PRIMARY KEY, document TEXT NOT NULL)")


    def append(self, *, scope: dict[str, Any], origin: str, source_id: str,
               records: list[dict[str, Any]] | None = None, csv_text: str | None = None) -> dict[str, Any]:
        """Atomically record an explicit import/manual batch with input provenance."""
        scope = validate_scope(scope)
        if scope["account_id"] is None:
            raise ValueError("private evidence requires an exact account")
        text(source_id, "source_id")
        if origin == "statement_csv":
            if type(csv_text) is not str or records is not None or len(csv_text.encode()) > 2_000_000:
                raise ValueError("bounded explicit CSV required")
            input_hash = hashlib.sha256(csv_text.encode()).hexdigest()
            records = list(csv.DictReader(io.StringIO(csv_text)))
        elif origin == "manual":
            if csv_text is not None or type(records) is not list:
                raise ValueError("explicit manual records required")
            input_hash = digest(records)
        else:
            raise ValueError("only statement_csv or manual evidence is admitted")
        if not records or len(records) > 10_000:
            raise ValueError("empty or oversized evidence batch")
        admitted = []
        for raw in records:
            row = {key: text(raw.get(key), key) for key in ("record_id", "kind", "instrument_id", "venue",
                                                           "currency", "quantity_unit")}
            if row["kind"] not in ("holding", "transaction"):
                raise ValueError("unknown evidence kind")
            quantity = _decimal(raw.get("quantity"))
            if row["kind"] == "holding" and Decimal(quantity) < 0:
                raise ValueError("negative declared holding")
            row.update(quantity=quantity, observed_at=timestamp(raw.get("observed_at")).isoformat(),
                       cash_amount=None if raw.get("cash_amount") in (None, "") else _decimal(raw["cash_amount"]))
            admitted.append(row)
        manifest = {"schema_version": 1, "scope": scope, "source_id": source_id, "origin": origin,
                    "input_sha256": input_hash, "records": admitted, "verification": "user_declared",
                    "complete": False, "execution_authority": False}
        batch_id = digest(manifest)
        scope_id = digest(scope)
        with self._lock:
            conn = self._connection
            if conn.in_transaction:
                raise RuntimeError("portfolio evidence cannot join another transaction")
            conn.execute("SAVEPOINT portfolio_append")
            try:
                for row in admitted:
                    key = digest({"source_id": source_id, "record_id": row["record_id"], "kind": row["kind"],
                                  "observed_at": row["observed_at"]})
                    previous = conn.execute("SELECT document FROM portfolio_evidence WHERE scope_id=? AND record_key=?",
                                            (scope_id, key)).fetchone()
                    fact = {**row, "source_id": source_id, "origin": origin, "input_sha256": input_hash,
                            "published_at": None, "retrieved_at": datetime.now(UTC).isoformat()}
                    if previous:
                        existing = json.loads(previous[0])
                        if any(existing.get(field) != value for field, value in row.items()):
                            raise EvidenceConflict("source record conflict requires explicit reconciliation")
                    else:
                        conn.execute("INSERT INTO portfolio_evidence VALUES (?,?,?,?)",
                                     (scope_id, key, canonical_json(fact), digest(fact)))
                conn.execute("INSERT OR IGNORE INTO portfolio_evidence_batches VALUES (?,?)",
                             (batch_id, canonical_json(manifest)))
                conn.execute("RELEASE portfolio_append")
            except Exception:
                conn.execute("ROLLBACK TO portfolio_append")
                conn.execute("RELEASE portfolio_append")
                raise
            stored = conn.execute("SELECT document FROM portfolio_evidence_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if stored is None or digest(json.loads(stored[0])) != batch_id:
                raise ValueError("portfolio batch readback mismatch")
        return {"batch_id": batch_id, "input_sha256": input_hash, "count": len(admitted),
                "verification": "user_declared", "complete": False, "execution_authority": False}

    def read(self, scope: dict[str, Any]) -> dict[str, Any]:
        """Return recorded facts only; absent data never establishes a flat book."""
        scope = validate_scope(scope)
        with self._lock:
            rows = self._connection.execute("SELECT document, record_hash FROM portfolio_evidence WHERE scope_id=?",
                                            (digest(scope),)).fetchall()
        if any(digest(json.loads(row[0])) != row[1] for row in rows):
            raise ValueError("portfolio evidence checksum mismatch")
        records = sorted((json.loads(row[0]) for row in rows), key=lambda row: (row["observed_at"], row["record_id"]))
        return {"scope": scope, "records": records, "status": "partial" if records else "unavailable",
                "complete": False, "execution_authority": False, "holdings_inferred_from_transactions": False}
