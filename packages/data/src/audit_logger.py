"""SEBI-compliant append-only audit logger.

Requirements (from docs/SEBI_COMPLIANCE.md):
- 5-year retention of all order/trade/login events
- Append-only — never delete, only compress old files
- File format: audit_YYYY-MM-DD.jsonl (one JSON object per line)
- Storage: /data/flinttrade/audit/

Events logged:
- ORDER_PLACED, ORDER_MODIFIED, ORDER_CANCELLED
- SAFETY_CHECK (each layer verdict)
- LOGIN, LOGOUT
- KILL_SWITCH_ACTIVATED, KILL_SWITCH_RESET
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.data.audit")

_DEFAULT_AUDIT_DIR = os.getenv("AUDIT_LOG_DIR", "/data/flinttrade/audit")

IST = timezone(timedelta(hours=5, minutes=30))


class AuditLogger:
    """Append-only SEBI-compliant audit logger writing daily JSONL files.

    Usage::

        audit = AuditLogger()
        audit.log_order_placed(strategy="Flint", symbol="RELIANCE", ...)
        audit.log_safety_check(layer="L1_ORDER", verdict="PASS", ...)
        audit.log_login(user="admin")
    """

    def __init__(self, audit_dir: str | None = None) -> None:
        self._audit_dir = Path(audit_dir or _DEFAULT_AUDIT_DIR)
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        self._current_date: str = ""
        self._current_file: Any = None

    def close(self) -> None:
        """Close the current file handle."""
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

    def _get_file(self) -> Any:
        """Return a file handle for today's audit log, rotating on date change."""
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if today != self._current_date:
            self.close()
            self._current_date = today
            filepath = self._audit_dir / f"audit_{today}.jsonl"
            self._current_file = open(filepath, "a", encoding="utf-8")
            logger.debug("Audit log rotated to %s", filepath)
        return self._current_file

    def _write(self, event: dict[str, Any]) -> None:
        """Append a single JSON line to today's audit file."""
        f = self._get_file()
        line = json.dumps(event, default=str, ensure_ascii=False)
        f.write(line + "\n")
        f.flush()  # Ensure durability — SEBI requires no data loss

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

    def log_event(self, event_type: str, **fields: Any) -> None:
        """Log an arbitrary audit event."""
        self._write(self._make_event(event_type, **fields))

    # ------------------------------------------------------------------
    # Read / query
    # ------------------------------------------------------------------

    def read_day(self, day: str) -> list[dict[str, Any]]:
        """Read all events for a given date (YYYY-MM-DD)."""
        filepath = self._audit_dir / f"audit_{day}.jsonl"
        if not filepath.exists():
            # Try compressed version
            gz_path = filepath.with_suffix(".jsonl.gz")
            if gz_path.exists():
                with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                    return [json.loads(line) for line in f if line.strip()]
            return []

        with open(filepath, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def list_audit_files(self) -> list[str]:
        """List all audit files (both .jsonl and .jsonl.gz)."""
        files = sorted(self._audit_dir.glob("audit_*"))
        return [f.name for f in files]

    # ------------------------------------------------------------------
    # Compression (5-year retention, compress old files)
    # ------------------------------------------------------------------

    def compress_old_files(self, older_than_days: int = 30) -> int:
        """Gzip audit files older than N days. Returns count of compressed files."""
        cutoff = date.today() - timedelta(days=older_than_days)
        compressed = 0

        for filepath in sorted(self._audit_dir.glob("audit_*.jsonl")):
            # Extract date from filename: audit_YYYY-MM-DD.jsonl
            try:
                file_date_str = filepath.stem.replace("audit_", "")
                file_date = date.fromisoformat(file_date_str)
            except ValueError:
                continue

            if file_date >= cutoff:
                continue

            gz_path = filepath.with_suffix(".jsonl.gz")
            if gz_path.exists():
                continue

            try:
                with open(filepath, "rb") as f_in:
                    with gzip.open(gz_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                # Remove original only after successful compression
                filepath.unlink()
                compressed += 1
                logger.info("Compressed audit file: %s", filepath.name)
            except Exception as exc:
                logger.error("Failed to compress %s: %s", filepath.name, exc)
                # Clean up partial gz file
                if gz_path.exists():
                    gz_path.unlink()

        return compressed
