"""Append-only, hash-chained local audit logger for the operator's own records.

Behaviour:
- Append-only — never deletes; old daily files may optionally be compressed
- Retention is operator-controlled (whatever the operator keeps on disk) —
  there is no purge or expiry code here
- File format: audit_YYYY-MM-DD.jsonl (one JSON object per line)
- Storage: /data/flinttrade/audit/

Tamper-evidence (hash chain):
- Every record carries a monotonic ``seq``, the ``prev_hash`` of the record
  before it, and its own ``hash`` (SHA-256 over the record's canonical JSON,
  every field except ``hash`` — so ``seq`` and ``prev_hash`` are covered too).
- The chain is *continuous across daily-file rotation and process restarts*:
  on first write the logger resumes from the tail hash of the newest existing
  file, or from the genesis hash (64 zeros) when the log is empty or begins
  with legacy pre-chain records.
- :meth:`AuditLogger.verify_chain` recomputes the chain across every file and
  reports the first break, so any *interior* edit, deletion, insertion, or
  reordering is detectable. Deletion of the oldest (prefix) or newest (suffix)
  records cannot be told from the operator's own retention/rotation using the
  log alone, so ``verify_chain`` also returns ``anchored_at_genesis`` — whether
  the first verified record is the genesis record (seq 0) — to distinguish a
  chain that is provably complete from the start from one whose earliest records
  are absent. This is the detection a ``chain_break`` / ``chain_restored``
  monitor would build on (that ActivityLog event emission is not yet wired) and
  makes the "hash-chain" claim in the audit routes true.
- Records are ``flush()``-ed *and* ``os.fsync()``-ed on every write, and the
  audit directory itself is fsync-ed when a new daily file is created, so an
  accepted record survives a power loss (flush alone leaves it in the OS cache;
  a new file also needs its parent-directory entry on disk). A crash mid-write
  can leave a newline-less partial record, which is truncated on the next open
  (it was never fsync-committed) rather than merged into the following record.

Events logged:
- ORDER_PLACED, ORDER_MODIFIED, ORDER_CANCELLED
- SAFETY_CHECK (each layer verdict)
- LOGIN, LOGOUT
- KILL_SWITCH_ACTIVATED, KILL_SWITCH_RESET
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flinttrade_core.owner_file_lock import OwnerSafeFileLock

logger = logging.getLogger("flinttrade.data.audit")

# Genesis link for the first record of a fresh chain (no predecessor).
GENESIS_HASH = "0" * 64

def _default_audit_dir() -> str:
    """Resolve the audit directory through the canonical workspace helper."""
    from flinttrade_core.workspace import audit_log_dir

    return str(audit_log_dir())

IST = timezone(timedelta(hours=5, minutes=30))


class AuditLogger:
    """Append-only audit logger writing daily JSONL files.

    Usage::

        audit = AuditLogger()
        audit.log_order_placed(strategy="Flint", symbol="RELIANCE", ...)
        audit.log_safety_check(layer="L1_ORDER", verdict="PASS", ...)
        audit.log_login(user="admin")
    """

    def __init__(self, audit_dir: str | None = None) -> None:
        self._audit_dir = Path(audit_dir or _default_audit_dir())
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._chain_lock = OwnerSafeFileLock(
            self._audit_dir / ".audit-chain.lock",
            timeout=10,
            mode=0o600,
            thread_local=False,
        )
        self._current_date: str = ""
        self._current_file: Any = None
        # Hash-chain cursor. ``_last_hash == ""`` means "not yet resolved"; it
        # is lazily loaded from the newest file's tail on the first write so a
        # restart resumes the same chain rather than forking a new one.
        self._last_hash: str = ""
        self._seq: int = -1

    def close(self) -> None:
        """Close the current file handle."""
        with self._lock:
            if self._current_file is not None:
                self._current_file.close()
                self._current_file = None

    def __enter__(self) -> AuditLogger:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # File management
    # ------------------------------------------------------------------

    def _get_file(self, today: str) -> Any:
        """Return a file handle for today's audit log, rotating on date change."""
        with self._lock:
            if today != self._current_date:
                self.close()
                self._current_date = today
                filepath = self._audit_dir / f"audit_{today}.jsonl"
                existed = filepath.exists()
                self._current_file = open(filepath, "a", encoding="utf-8")
                if not existed:
                    # A new file's directory entry must reach disk too, or a crash
                    # right after its first record would lose the whole file.
                    self._fsync_dir()
                logger.debug("Audit log rotated to %s", filepath)
            return self._current_file

    @staticmethod
    def _repair_torn_tail(path: Path) -> None:
        """Drop a trailing partial line left by a crash mid-write.

        :meth:`_write` fsyncs only *after* writing a complete ``line + "\\n"``,
        so a file whose last byte is not a newline ends in an uncommitted partial
        record. Truncating back to the last newline restores a clean append point
        and stops the next record from being concatenated onto the partial (which
        would merge two records into one unparseable line and swallow the valid
        one). Every committed record is newline-terminated, so this never drops
        durable data.
        """
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size == 0:
            return
        with open(path, "rb+") as fh:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) == b"\n":
                return  # cleanly terminated — nothing to repair
            newline_at = -1
            pos = size - 1
            step = 4096
            while pos >= 0:
                start = max(0, pos - step + 1)
                fh.seek(start)
                data = fh.read(pos - start + 1)
                idx = data.rfind(b"\n")
                if idx != -1:
                    newline_at = start + idx
                    break
                pos = start - 1
            fh.truncate(newline_at + 1)  # keep through the last newline (0 → empty)
            fh.flush()
            os.fsync(fh.fileno())

    def _fsync_dir(self, *, required: bool = False) -> None:
        """fsync the audit directory so a newly created file's entry persists.

        POSIX-only; a best-effort no-op where opening a directory fd is not
        supported (e.g. Windows), where journalled filesystems cover this.
        """
        try:
            dir_fd = os.open(self._audit_dir, os.O_RDONLY)
        except OSError:
            if required and os.name != "nt":
                raise
            return
        try:
            os.fsync(dir_fd)
        except OSError:
            if required and os.name != "nt":
                raise
        finally:
            os.close(dir_fd)

    @staticmethod
    def _record_hash(record: dict[str, Any]) -> str:
        """SHA-256 over a record's canonical JSON, excluding the ``hash`` field.

        Every other field — including ``seq`` and ``prev_hash`` — is covered,
        so editing any of them (or the linkage) invalidates the hash. Sorted
        keys + compact separators give a stable, reproducible canonical form.
        """
        payload = {k: v for k, v in record.items() if k != "hash"}
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _iter_files(self) -> list[Path]:
        """Return one canonical audit file per day in chronological order.

        A crash after the durable gzip replacement but before source deletion
        can leave both forms present. The plain source remains canonical until
        compression finishes reconciling that state; temporary gzip files are
        never part of the visible chain.
        """
        files_by_day: dict[str, Path] = {}
        for suffix in (".jsonl", ".jsonl.gz"):
            for path in self._audit_dir.glob(f"audit_*{suffix}"):
                day = path.name.removeprefix("audit_").removesuffix(suffix)
                try:
                    parsed_day = date.fromisoformat(day)
                except ValueError:
                    continue
                if parsed_day.isoformat() != day:
                    continue
                if suffix == ".jsonl" or day not in files_by_day:
                    files_by_day[day] = path
        return [files_by_day[day] for day in sorted(files_by_day)]

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        """Read a plain or gzipped audit file as a list of raw JSON lines."""
        if path.suffix == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                return [ln for ln in fh if ln.strip()]
        with open(path, "r", encoding="utf-8") as fh:
            return [ln for ln in fh if ln.strip()]

    def _resolve_chain_tail(self) -> None:
        """Resolve a validated durable tail that is safe to append behind."""
        with self._lock:
            trailing_legacy_record = False
            tail: dict[str, Any] | None = None
            for path in reversed(self._iter_files()):
                try:
                    lines = self._read_lines(path)
                except (OSError, gzip.BadGzipFile, UnicodeError) as exc:
                    raise RuntimeError(f"audit chain tail is unreadable in {path.name}: {exc}") from exc
                for line in reversed(lines):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(f"audit chain tail contains invalid JSON in {path.name}") from exc
                    if not isinstance(rec, dict) or not rec.get("hash"):
                        trailing_legacy_record = True
                        continue

                    if trailing_legacy_record:
                        raise RuntimeError("audit chain has an unchained record after its chained region")
                    if self._record_hash(rec) != str(rec.get("hash")):
                        raise RuntimeError("audit chain tail record does not match its hash")
                    try:
                        seq = int(rec.get("seq", -1))
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("audit chain tail has an invalid sequence") from exc

                    if tail is None:
                        tail = rec
                        if seq == 0:
                            if str(rec.get("prev_hash")) != GENESIS_HASH:
                                raise RuntimeError("audit chain genesis record has an invalid predecessor")
                            self._last_hash = str(rec["hash"])
                            self._seq = seq
                            return
                        continue

                    try:
                        predecessor_seq = int(rec.get("seq", -1))
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("audit chain predecessor has an invalid sequence") from exc
                    if self._record_hash(rec) != str(rec.get("hash")):
                        raise RuntimeError("audit chain predecessor does not match its hash")
                    tail_seq = int(tail["seq"])
                    if str(tail.get("prev_hash")) != str(rec["hash"]) or tail_seq != predecessor_seq + 1:
                        raise RuntimeError("audit chain tail does not link to its predecessor")
                    self._last_hash = str(tail["hash"])
                    self._seq = tail_seq
                    return

            if tail is not None:
                raise RuntimeError("audit chain tail is missing its predecessor")
            self._last_hash = GENESIS_HASH
            self._seq = -1

    def _prepare_append(self) -> None:
        """Repair an uncommitted plain chain tail and resolve a safe append point."""
        files = self._iter_files()
        if files and files[-1].suffix == ".jsonl":
            self._repair_torn_tail(files[-1])
        verification = self.verify_chain()
        if not verification["ok"]:
            failure = verification.get("break") or {}
            reason = failure.get("reason", "unknown chain break")
            raise RuntimeError(f"audit chain verification failed before append: {reason}")
        self._resolve_chain_tail()

    def _write(self, event: dict[str, Any]) -> str:
        """Append one hash-chained JSON record to today's audit file.

        The record is linked to its predecessor via ``prev_hash`` and sealed
        with its own ``hash``, then flushed and fsync-ed so an accepted record
        survives a crash. The chain cursor persists across daily rotation and
        restarts, so the whole log verifies as one tamper-evident chain.
        """
        with self._lock, self._chain_lock:
            today = datetime.now(IST).strftime("%Y-%m-%d")
            # A different process can leave a partial write after this instance
            # has opened its file, so prepare under the shared lock every time.
            self._prepare_append()
            self._seq += 1
            record = {**event, "seq": self._seq, "prev_hash": self._last_hash}
            record["hash"] = self._record_hash(record)
            f = self._get_file(today)
            line = json.dumps(record, default=str, ensure_ascii=False)
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())  # force to disk — flush() only reaches the OS cache
            self._last_hash = record["hash"]
            return str(record["hash"])

    def _make_event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        """Build a timestamped audit event."""
        return {
            "ts": datetime.now(IST).isoformat(),
            "event_type": event_type,
            **fields,
        }

    # ------------------------------------------------------------------
    # Order events
    # ------------------------------------------------------------------

    def log_order_placed(
        self,
        *,
        strategy: str,
        symbol: str,
        exchange: str,
        action: str,
        quantity: str,
        price: str,
        pricetype: str = "",
        product: str = "",
        orderid: str = "",
    ) -> None:
        self._write(self._make_event(
            "ORDER_PLACED",
            strategy=strategy, symbol=symbol, exchange=exchange,
            action=action, quantity=quantity, price=price,
            pricetype=pricetype, product=product, orderid=orderid,
        ))

    def log_order_modified(
        self,
        *,
        strategy: str,
        symbol: str,
        exchange: str,
        orderid: str,
        action: str,
        quantity: str,
        price: str,
    ) -> None:
        self._write(self._make_event(
            "ORDER_MODIFIED",
            strategy=strategy, symbol=symbol, exchange=exchange,
            orderid=orderid, action=action, quantity=quantity, price=price,
        ))

    def log_order_cancelled(
        self,
        *,
        strategy: str,
        orderid: str,
        symbol: str = "",
        exchange: str = "",
    ) -> None:
        self._write(self._make_event(
            "ORDER_CANCELLED",
            strategy=strategy, orderid=orderid,
            symbol=symbol, exchange=exchange,
        ))

    # ------------------------------------------------------------------
    # Safety events
    # ------------------------------------------------------------------

    def log_safety_check(
        self,
        *,
        layer: str,
        verdict: str,
        reason: str = "",
        symbol: str = "",
        exchange: str = "",
        strategy: str = "",
    ) -> None:
        self._write(self._make_event(
            "SAFETY_CHECK",
            layer=layer, verdict=verdict, reason=reason,
            symbol=symbol, exchange=exchange, strategy=strategy,
        ))

    def log_kill_switch(self, *, activated: bool, reason: str = "") -> None:
        event_type = "KILL_SWITCH_ACTIVATED" if activated else "KILL_SWITCH_RESET"
        self._write(self._make_event(event_type, reason=reason))

    # ------------------------------------------------------------------
    # Login / logout events
    # ------------------------------------------------------------------

    def log_login(self, *, user: str = "", ip: str = "", method: str = "") -> None:
        self._write(self._make_event("LOGIN", user=user, ip=ip, method=method))

    def log_logout(self, *, user: str = "", reason: str = "") -> None:
        self._write(self._make_event("LOGOUT", user=user, reason=reason))

    # ------------------------------------------------------------------
    # Generic event
    # ------------------------------------------------------------------

    def log_event(self, event_type: str, **fields: Any) -> str:
        """Log an arbitrary audit event and return its durable record hash."""
        return self._write(self._make_event(event_type, **fields))

    def verify_event_receipt(
        self,
        audit_reference: str,
        *,
        event_type: str,
        resolution_id: str,
        evidence_digest: str,
    ) -> bool:
        """Verify one fsynced audit record in an intact chain binds the evidence."""
        reference = str(audit_reference or "").strip()
        if not reference or not event_type or not resolution_id or not evidence_digest:
            return False
        with self._lock, self._chain_lock:
            chain = self.verify_chain()
            if not chain["ok"] or not chain["anchored_at_genesis"]:
                return False
            for path in reversed(self._iter_files()):
                try:
                    lines = self._read_lines(path)
                except (OSError, gzip.BadGzipFile):
                    continue
                for line in reversed(lines):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(record, dict) or str(record.get("hash") or "") != reference:
                        continue
                    return (
                        self._record_hash(record) == reference
                        and record.get("event_type") == event_type
                        and record.get("resolution_id") == resolution_id
                        and record.get("evidence_digest") == evidence_digest
                    )
        return False

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def read_day(self, day: str) -> list[dict[str, Any]]:
        """Read all events for a given date (YYYY-MM-DD)."""
        with self._lock, self._chain_lock:
            filepath = self._audit_dir / f"audit_{day}.jsonl"
            if not filepath.exists():
                gz_path = filepath.with_suffix(".jsonl.gz")
                if gz_path.exists():
                    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                        return [json.loads(line) for line in f if line.strip()]
                return []

            with open(filepath, "r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]

    def list_audit_files(self) -> list[str]:
        """List the canonical plain or compressed file for each audit day."""
        with self._lock, self._chain_lock:
            return [path.name for path in self._iter_files()]

    def verify_chain(self) -> dict[str, Any]:
        """Recompute the hash chain across every audit file, oldest first.

        Detects any *interior* content edit (a record's stored ``hash`` no longer
        matches its fields), deletion, insertion, or reordering (a broken
        ``prev_hash`` link or a ``seq`` gap). Deletion of the oldest (prefix) or
        newest (suffix) records cannot be told from the operator's own
        retention/rotation using the log alone, because the surviving tail is
        internally consistent; ``anchored_at_genesis`` reports whether the first
        verified record is the genesis record (``seq`` 0, ``prev_hash`` genesis)
        so a chain that is provably complete from the start is distinguishable
        from one whose earliest records are absent. Legacy pre-chain records
        (no ``hash``) are skipped until the first chained record, which becomes
        the anchor; verification then runs forward from there.

        Returns:
            ``{"ok": bool, "checked": int, "anchored_at_genesis": bool,
            "break": {...} | None}`` — ``checked`` counts verified chained
            records; ``break`` describes the first failure (file, line, seq,
            reason) or is ``None`` when the present records form an unbroken
            chain.
        """
        with self._lock, self._chain_lock:
            prev: str | None = None  # running expected prev_hash; None until anchored
            expected_seq = 0
            checked = 0
            anchored_at_genesis = False
            for path in self._iter_files():
                try:
                    lines = self._read_lines(path)
                except (OSError, gzip.BadGzipFile) as exc:
                    return {"ok": False, "checked": checked, "anchored_at_genesis": anchored_at_genesis,
                            "break": {"file": path.name, "reason": f"unreadable: {exc}"}}
                for idx, line in enumerate(lines):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        return {"ok": False, "checked": checked, "anchored_at_genesis": anchored_at_genesis,
                                "break": {"file": path.name, "line": idx, "reason": "invalid JSON"}}
                    is_chained = isinstance(rec, dict) and bool(rec.get("hash"))
                    if prev is None:
                        if not is_chained:
                            continue  # legacy pre-chain prefix
                        prev = str(rec.get("prev_hash", GENESIS_HASH))
                        expected_seq = int(rec.get("seq", 0))
                        anchored_at_genesis = prev == GENESIS_HASH and expected_seq == 0
                    reason: str | None = None
                    if not is_chained:
                        reason = "chained-region record is missing its hash (deletion or insertion?)"
                    elif str(rec.get("prev_hash")) != prev:
                        reason = "prev_hash does not link to the previous record's hash"
                    elif self._record_hash(rec) != str(rec.get("hash")):
                        reason = "record content does not match its hash (tampered)"
                    elif int(rec.get("seq", -1)) != expected_seq:
                        reason = f"seq gap: expected {expected_seq}, found {rec.get('seq')}"
                    if reason is not None:
                        return {"ok": False, "checked": checked, "anchored_at_genesis": anchored_at_genesis,
                                "break": {"file": path.name, "line": idx,
                                          "seq": rec.get("seq"), "reason": reason}}
                    prev = str(rec["hash"])
                    expected_seq += 1
                    checked += 1
            return {"ok": True, "checked": checked, "anchored_at_genesis": anchored_at_genesis, "break": None}

    # ------------------------------------------------------------------
    # Compression (optional compression of old daily files, operator-controlled retention)
    # ------------------------------------------------------------------

    @staticmethod
    def _compression_temp_path(gz_path: Path) -> Path:
        """Return the deterministic same-directory compression staging path."""
        return gz_path.with_name(f"{gz_path.name}.tmp")

    @staticmethod
    def _write_gzip_temp(source: Path, temp_path: Path) -> None:
        """Write and fsync a complete gzip without exposing it as the final file."""
        with open(source, "rb") as source_file, open(temp_path, "wb") as temp_file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=temp_file, mtime=0) as gzip_file:
                shutil.copyfileobj(source_file, gzip_file)
            temp_file.flush()
            os.fsync(temp_file.fileno())

    def _reconcile_orphaned_compression_temps(self) -> None:
        """Resolve temp-only states without replacing an extant source."""
        for temp_path in sorted(self._audit_dir.glob("audit_*.jsonl.gz.tmp")):
            gz_path = temp_path.with_suffix("")
            source_path = gz_path.with_suffix("")
            if source_path.exists():
                continue  # the normal compression pass rewrites from the source
            if gz_path.exists():
                temp_path.unlink()
                self._fsync_dir(required=True)
                continue
            try:
                with gzip.open(temp_path, "rb") as gzip_file:
                    while gzip_file.read(1024 * 1024):
                        pass
                os.replace(temp_path, gz_path)
                self._fsync_dir(required=True)
                logger.info("Recovered compressed audit file: %s", gz_path.name)
            except (EOFError, OSError, gzip.BadGzipFile) as exc:
                logger.error("Failed to reconcile compression temp %s: %s", temp_path.name, exc)

    def compress_old_files(self, older_than_days: int = 30) -> int:
        """Gzip audit files older than N days. Returns count of compressed files."""
        with self._lock, self._chain_lock:
            cutoff = date.today() - timedelta(days=older_than_days)
            compressed = 0
            self._reconcile_orphaned_compression_temps()

            for filepath in sorted(self._audit_dir.glob("audit_*.jsonl")):
                file_date_str = filepath.name.removeprefix("audit_").removesuffix(".jsonl")
                try:
                    file_date = date.fromisoformat(file_date_str)
                except ValueError:
                    continue
                if file_date.isoformat() != file_date_str or file_date >= cutoff:
                    continue

                gz_path = filepath.with_suffix(".jsonl.gz")
                temp_path = self._compression_temp_path(gz_path)
                try:
                    self._write_gzip_temp(filepath, temp_path)
                    os.replace(temp_path, gz_path)
                    self._fsync_dir(required=True)
                    filepath.unlink()
                    self._fsync_dir(required=True)
                    compressed += 1
                    logger.info("Compressed audit file: %s", filepath.name)
                except Exception as exc:
                    # The source stays canonical after any recoverable failure.
                    # A durable final or partial temp is reconciled next time.
                    logger.error("Failed to compress %s: %s", filepath.name, exc)

            return compressed
