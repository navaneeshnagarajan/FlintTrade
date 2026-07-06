"""Bhavcopy (full-market EOD) downloader — NSE daily archives to local storage.

Downloads the NSE bhavcopy families via ``jugaad-data`` (already a declared
dependency of this package) into a local directory, one CSV per segment per
trading day:

  * ``equity`` — the equity bhavcopy (``bhavcopy_save``)
  * ``fo``     — the F&O bhavcopy (``bhavcopy_fo_save``)
  * ``index``  — the index bhavcopy (``bhavcopy_index_save``)
  * ``full``   — the full bhavcopy incl. delivery data (``full_bhavcopy_save``)

This is the "download the whole market, not just my watchlist" complement to
the per-symbol OHLCV downloader: bhavcopies carry every listed instrument's
EOD row, so a local archive supports scans/backtests without per-symbol API
calls. Weekends are skipped automatically; already-downloaded files are not
re-fetched (idempotent re-runs). Failures are captured per day/segment rather
than aborting the batch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("flinttrade.historical.bhavcopy")

# One route call may fetch at most this many calendar days — bhavcopy fetches
# are sequential network calls against NSE archives; a bounded batch keeps the
# request thread honest. Larger backfills = repeated calls.
MAX_RANGE_DAYS = 31

SEGMENTS: tuple[str, ...] = ("equity", "fo", "index", "full")


def _default_savers() -> dict[str, Callable[..., str]]:
    """Import the jugaad-data savers lazily (network library; test-injectable)."""
    from jugaad_data import nse  # noqa: PLC0415

    return {
        "equity": nse.bhavcopy_save,
        "fo": nse.bhavcopy_fo_save,
        "index": nse.bhavcopy_index_save,
        "full": nse.full_bhavcopy_save,
    }


@dataclass
class BhavcopyDayResult:
    """Outcome of one trading day's bhavcopy downloads."""

    trade_date: str = ""
    saved: list[str] = field(default_factory=list)     # segment names fetched
    skipped: list[str] = field(default_factory=list)   # already on disk
    errors: dict[str, str] = field(default_factory=dict)  # segment → error

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "trade_date": self.trade_date,
            "saved": self.saved,
            "skipped": self.skipped,
            "errors": self.errors,
        }


@dataclass
class BhavcopyRangeResult:
    """Outcome of a date-range bhavcopy download."""

    start: str = ""
    end: str = ""
    segments: list[str] = field(default_factory=list)
    days: list[BhavcopyDayResult] = field(default_factory=list)

    @property
    def saved_count(self) -> int:
        return sum(len(d.saved) for d in self.days)

    @property
    def error_count(self) -> int:
        return sum(len(d.errors) for d in self.days)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "start": self.start,
            "end": self.end,
            "segments": self.segments,
            "saved_count": self.saved_count,
            "error_count": self.error_count,
            "days": [d.to_dict() for d in self.days],
        }


class BhavcopyDownloader:
    """Download NSE bhavcopy archives for a date range into ``dest_dir``.

    Args:
        dest_dir: Directory to save CSVs into (created if missing). Each
            segment gets a subdirectory (``equity/``, ``fo/``, ``index/``,
            ``full/``).
        savers: Optional segment→saver mapping (tests inject fakes; production
            defaults to the jugaad-data savers).
    """

    def __init__(
        self,
        dest_dir: str | Path,
        savers: dict[str, Callable[..., str]] | None = None,
    ) -> None:
        self._dest = Path(dest_dir)
        self._savers = savers if savers is not None else _default_savers()

    def _segment_dir(self, segment: str) -> Path:
        seg_dir = self._dest / segment
        seg_dir.mkdir(parents=True, exist_ok=True)
        return seg_dir

    @staticmethod
    def _already_downloaded(seg_dir: Path, trade_date: date) -> bool:
        """A prior save for this date exists (jugaad names files with the date)."""
        token = trade_date.strftime("%d%b%Y").upper()  # e.g. 06JUL2026
        iso = trade_date.isoformat()
        for f in seg_dir.iterdir() if seg_dir.exists() else []:
            name = f.name.upper()
            if token in name or iso in name:
                return True
        return False

    def download_day(self, trade_date: date, segments: list[str] | None = None) -> BhavcopyDayResult:
        """Download one trading day's bhavcopies (skips files already on disk)."""
        segs = [s for s in (segments or list(SEGMENTS)) if s in self._savers]
        result = BhavcopyDayResult(trade_date=trade_date.isoformat())

        for segment in segs:
            seg_dir = self._segment_dir(segment)
            if self._already_downloaded(seg_dir, trade_date):
                result.skipped.append(segment)
                continue
            try:
                self._savers[segment](trade_date, str(seg_dir))
                result.saved.append(segment)
            except Exception as exc:  # per-segment capture — a holiday or a
                # missing archive must not abort the remaining segments/days.
                result.errors[segment] = str(exc)
                logger.warning(
                    "Bhavcopy %s/%s failed: %s", trade_date.isoformat(), segment, exc
                )
        return result

    def download_range(
        self,
        start: date,
        end: date,
        segments: list[str] | None = None,
    ) -> BhavcopyRangeResult:
        """Download bhavcopies for every weekday in [start, end].

        Raises:
            ValueError: if the range is reversed or longer than
                :data:`MAX_RANGE_DAYS` calendar days.
        """
        if end < start:
            raise ValueError("end date is before start date")
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(
                f"Range too large: {(end - start).days + 1} days (max {MAX_RANGE_DAYS} per call)"
            )

        segs = [s for s in (segments or list(SEGMENTS)) if s in SEGMENTS]
        result = BhavcopyRangeResult(start=start.isoformat(), end=end.isoformat(), segments=segs)

        current = start
        while current <= end:
            if current.weekday() < 5:  # Mon-Fri; NSE holidays surface as per-day errors
                result.days.append(self.download_day(current, segs))
            current += timedelta(days=1)
        return result
