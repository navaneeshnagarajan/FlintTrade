"""Export SEBI audit logs to CSV and PDF.

Reads from AuditLogger's daily JSONL files and produces:

- CSV: one row per audit event
- PDF: table with summary statistics via reportlab (optional dep)

reportlab is an optional dependency — if it is not installed, ``to_pdf()``
raises :class:`AuditExportError` with a helpful message.

Usage::

    from packages.data.src.audit_logger import AuditLogger
    from packages.data.src.audit_export import AuditExporter
    from datetime import date
    from pathlib import Path

    exporter = AuditExporter(AuditLogger())
    rows = exporter.to_csv(date(2026, 4, 1), date(2026, 4, 30), Path("/tmp/audit.csv"))
    print(f"Exported {rows} rows")
"""

from __future__ import annotations

import csv
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.data.audit_export")


class AuditExportError(Exception):
    """Raised when an export operation fails.

    Args:
        message: Human-readable description of the failure.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class AuditExporter:
    """Export audit logs to CSV and PDF formats.

    Args:
        audit_logger: An :class:`~packages.data.src.audit_logger.AuditLogger`
            instance whose data files will be read.

    Example::

        exporter = AuditExporter(AuditLogger())
        count = exporter.to_csv(date(2026, 4, 1), date(2026, 4, 30), Path("/tmp/audit.csv"))
    """

    # Canonical column ordering for CSV / PDF output.
    _CSV_COLUMNS: list[str] = [
        "ts",
        "event_type",
        "strategy",
        "symbol",
        "exchange",
        "action",
        "quantity",
        "price",
        "pricetype",
        "product",
        "orderid",
        "layer",
        "verdict",
        "reason",
        "user",
        "ip",
        "method",
    ]

    def __init__(self, audit_logger: Any) -> None:
        self._logger = audit_logger

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _date_range(self, from_date: date, to_date: date) -> list[str]:
        """Return ISO-date strings for every day in [from_date, to_date].

        Args:
            from_date: First day inclusive.
            to_date: Last day inclusive.

        Returns:
            List of ``"YYYY-MM-DD"`` strings, oldest first.
        """
        days: list[str] = []
        current = from_date
        while current <= to_date:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days

    def _load_events(self, from_date: date, to_date: date) -> list[dict[str, Any]]:
        """Read all events in the date range from the audit logger.

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            Flat list of event dicts ordered by day (ascending).
        """
        events: list[dict[str, Any]] = []
        for day in self._date_range(from_date, to_date):
            day_events = self._logger.read_day(day)
            events.extend(day_events)
        return events

    @staticmethod
    def _flatten(event: dict[str, Any]) -> dict[str, Any]:
        """Return a flat dict suitable for CSV/PDF rows.

        Unknown keys are included at the end; known keys occupy their
        canonical positions so the CSV header is stable.

        Args:
            event: Raw audit event dict.

        Returns:
            Flattened event dict.
        """
        return dict(event)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def to_csv(self, from_date: date, to_date: date, path: Path) -> int:
        """Export audit entries to a CSV file.

        All event types are written with a fixed header covering the known
        columns.  Unknown fields appear as extra columns at the end.

        Args:
            from_date: First day to export (inclusive).
            to_date: Last day to export (inclusive).
            path: Destination ``.csv`` file path.  Parent directories are
                created if they do not exist.

        Returns:
            Number of data rows written (not counting the header).

        Raises:
            AuditExportError: If the file cannot be written.
        """
        events = self._load_events(from_date, to_date)

        # Build a superset of all field names to handle arbitrary event types.
        all_keys: list[str] = list(self._CSV_COLUMNS)
        extra: list[str] = []
        for ev in events:
            for k in ev:
                if k not in all_keys and k not in extra:
                    extra.append(k)
        fieldnames = all_keys + extra

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=fieldnames,
                    extrasaction="ignore",
                    restval="",
                )
                writer.writeheader()
                for ev in events:
                    writer.writerow(ev)
        except OSError as exc:
            raise AuditExportError(f"Cannot write CSV to {path}: {exc}") from exc

        logger.info(
            "Audit CSV exported: %d rows → %s", len(events), path
        )
        return len(events)

    def to_pdf(
        self,
        from_date: date,
        to_date: date,
        path: Path,
        title: str = "FlintTrade Audit Report",
    ) -> int:
        """Export audit entries to a PDF file.

        Produces a landscape A4 PDF containing:

        - Cover section with title, date range, and generation timestamp.
        - Summary statistics table (total events, by type, orders/safety).
        - Paginated audit event table.

        Requires the ``reportlab`` package (``pip install reportlab>=4.0``
        or add the ``export`` optional extra).

        Args:
            from_date: First day to export (inclusive).
            to_date: Last day to export (inclusive).
            path: Destination ``.pdf`` file path.
            title: Report title shown at the top of the first page.

        Returns:
            Number of event rows written to the PDF.

        Raises:
            AuditExportError: If ``reportlab`` is not installed or the
                file cannot be written.
        """
        try:
            from reportlab.lib import colors  # noqa: PLC0415
            from reportlab.lib.pagesizes import A4, landscape  # noqa: PLC0415
            from reportlab.lib.styles import getSampleStyleSheet  # noqa: PLC0415
            from reportlab.lib.units import cm  # noqa: PLC0415
            from reportlab.platypus import (  # noqa: PLC0415
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise AuditExportError(
                "reportlab is required for PDF export. "
                "Install it with: pip install 'flint-data[export]'"
            ) from exc

        events = self._load_events(from_date, to_date)
        stats = self._compute_stats(events)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            doc = SimpleDocTemplate(
                str(path),
                pagesize=landscape(A4),
                leftMargin=1.5 * cm,
                rightMargin=1.5 * cm,
                topMargin=1.5 * cm,
                bottomMargin=1.5 * cm,
            )
        except Exception as exc:
            raise AuditExportError(
                f"Cannot create PDF at {path}: {exc}"
            ) from exc

        styles = getSampleStyleSheet()
        story: list[Any] = []

        # ------ Title -------------------------------------------------------
        story.append(Paragraph(title, styles["Title"]))
        story.append(Spacer(1, 0.3 * cm))

        date_range_text = (
            f"Period: {from_date.isoformat()} to {to_date.isoformat()}"
        )
        story.append(Paragraph(date_range_text, styles["Normal"]))
        story.append(Spacer(1, 0.5 * cm))

        # ------ Summary table -----------------------------------------------
        summary_data = [
            ["Metric", "Value"],
            ["Total events", str(stats["total_events"])],
            ["Orders placed", str(stats["orders_placed"])],
            ["Orders rejected", str(stats["orders_rejected"])],
            ["Safety triggers", str(stats["safety_triggers"])],
        ]
        for event_type, count in stats["events_by_type"].items():
            summary_data.append([f"  {event_type}", str(count)])

        summary_table = Table(summary_data, colWidths=[8 * cm, 4 * cm])
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(summary_table)
        story.append(Spacer(1, 0.8 * cm))

        # ------ Events table ------------------------------------------------
        pdf_columns = ["ts", "event_type", "strategy", "symbol", "exchange", "action", "orderid"]
        col_header = ["Timestamp", "Event Type", "Strategy", "Symbol", "Exchange", "Action", "Order ID"]

        table_data: list[list[str]] = [col_header]
        for ev in events:
            row = [str(ev.get(col, "")) for col in pdf_columns]
            table_data.append(row)

        page_width = landscape(A4)[0] - 3 * cm
        col_widths = [4.5 * cm, 3.5 * cm, 3 * cm, 3 * cm, 2.5 * cm, 2 * cm, 3 * cm]
        # Normalise widths to fit page
        total_w = sum(col_widths)
        col_widths = [w * page_width / total_w for w in col_widths]

        events_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        events_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f8ff")]),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ("WORDWRAP", (0, 0), (-1, -1), True),
                ]
            )
        )
        story.append(events_table)

        try:
            doc.build(story)
        except Exception as exc:
            raise AuditExportError(f"PDF generation failed: {exc}") from exc

        logger.info("Audit PDF exported: %d rows → %s", len(events), path)
        return len(events)

    def summary_stats(self, from_date: date, to_date: date) -> dict[str, Any]:
        """Compute summary statistics for the given date range.

        Args:
            from_date: Start date (inclusive).
            to_date: End date (inclusive).

        Returns:
            Dict with keys:

            - ``total_events`` (int): Total number of audit events.
            - ``events_by_type`` (dict[str, int]): Count per ``event_type``.
            - ``orders_placed`` (int): Count of ``ORDER_PLACED`` events.
            - ``orders_rejected`` (int): Safety-rejected orders (``SAFETY_CHECK``
              with ``verdict == "REJECT"``).
            - ``safety_triggers`` (int): ``KILL_SWITCH_ACTIVATED`` + failed
              ``SAFETY_CHECK`` events.
        """
        events = self._load_events(from_date, to_date)
        return self._compute_stats(events)

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute summary statistics from a list of events.

        Args:
            events: Flat list of audit event dicts.

        Returns:
            Summary statistics dict (see :meth:`summary_stats`).
        """
        events_by_type: dict[str, int] = {}
        orders_placed = 0
        orders_rejected = 0
        safety_triggers = 0

        for ev in events:
            etype = ev.get("event_type", "UNKNOWN")
            events_by_type[etype] = events_by_type.get(etype, 0) + 1

            if etype == "ORDER_PLACED":
                orders_placed += 1
            elif etype == "SAFETY_CHECK":
                verdict = str(ev.get("verdict", "")).upper()
                if verdict in ("REJECT", "FAIL", "BLOCK"):
                    orders_rejected += 1
                    safety_triggers += 1
            elif etype == "KILL_SWITCH_ACTIVATED":
                safety_triggers += 1

        return {
            "total_events": len(events),
            "events_by_type": events_by_type,
            "orders_placed": orders_placed,
            "orders_rejected": orders_rejected,
            "safety_triggers": safety_triggers,
        }
