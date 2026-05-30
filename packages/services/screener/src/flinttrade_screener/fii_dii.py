"""FII/DII institutional flow data scraper and analysis.

Absorbs patterns from MarketCalls/fii-dii-data:
- NSE session management with cookie refresh
- Cash market FII/DII data from NSE API
- F&O participant OI data from NSE CSV archives
- Sentiment score derivation from flows + PCR
- DuckDB caching with daily refresh

Data sources:
- Cash segment: ``https://www.nseindia.com/api/fiidiiTradeReact``
- F&O OI: ``https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_*.csv``

Usage::

    from .fii_dii import FiiDiiTracker

    tracker = FiiDiiTracker(db_path=":memory:")
    data = tracker.fetch_latest()
    trend = tracker.get_trend(days=30)
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import httpx

logger = logging.getLogger("flinttrade.screener.fii_dii")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Constants (absorbed from fii-dii-data's CONFIG)
# ---------------------------------------------------------------------------

_NSE_HOME = "https://www.nseindia.com/"
_NSE_API = "https://www.nseindia.com/api/fiidiiTradeReact"
_FAO_BASE = "https://nsearchives.nseindia.com/content/nsccl"
_TIMEOUT = 25.0
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0
_HISTORY_MAX = 200

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.nseindia.com/reports-indices-fii-dii-trading-activity",
}

_MONTHS = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FiiDiiSnapshot:
    """Single day's FII/DII cash + F&O data.

    Fields mirror fii-dii-data's ``transformData`` output.
    """

    trade_date: str = ""
    # Cash segment
    fii_buy: float = 0.0
    fii_sell: float = 0.0
    fii_net: float = 0.0
    dii_buy: float = 0.0
    dii_sell: float = 0.0
    dii_net: float = 0.0
    # F&O — FII
    fii_idx_fut_long: int = 0
    fii_idx_fut_short: int = 0
    fii_idx_fut_net: int = 0
    fii_stk_fut_long: int = 0
    fii_stk_fut_short: int = 0
    fii_stk_fut_net: int = 0
    fii_idx_call_long: int = 0
    fii_idx_call_short: int = 0
    fii_idx_call_net: int = 0
    fii_idx_put_long: int = 0
    fii_idx_put_short: int = 0
    fii_idx_put_net: int = 0
    # F&O — DII
    dii_idx_fut_long: int = 0
    dii_idx_fut_short: int = 0
    dii_idx_fut_net: int = 0
    dii_stk_fut_long: int = 0
    dii_stk_fut_short: int = 0
    dii_stk_fut_net: int = 0
    # Derived
    pcr: float = 0.0
    sentiment_score: float = 50.0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class FiiDiiTrend:
    """Multi-day FII/DII trend summary."""

    days: int = 0
    snapshots: list[FiiDiiSnapshot] = field(default_factory=list)
    fii_net_total: float = 0.0
    dii_net_total: float = 0.0
    avg_sentiment: float = 50.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "days": self.days,
            "snapshots": [s.to_dict() for s in self.snapshots],
            "fii_net_total": self.fii_net_total,
            "dii_net_total": self.dii_net_total,
            "avg_sentiment": self.avg_sentiment,
        }


# ---------------------------------------------------------------------------
# DuckDB schema
# ---------------------------------------------------------------------------

_SCHEMA_FII_DII = """
CREATE TABLE IF NOT EXISTS fii_dii_flows (
    trade_date          VARCHAR PRIMARY KEY,
    fii_buy             DOUBLE DEFAULT 0,
    fii_sell            DOUBLE DEFAULT 0,
    fii_net             DOUBLE DEFAULT 0,
    dii_buy             DOUBLE DEFAULT 0,
    dii_sell            DOUBLE DEFAULT 0,
    dii_net             DOUBLE DEFAULT 0,
    fii_idx_fut_long    BIGINT DEFAULT 0,
    fii_idx_fut_short   BIGINT DEFAULT 0,
    fii_idx_fut_net     BIGINT DEFAULT 0,
    fii_stk_fut_long    BIGINT DEFAULT 0,
    fii_stk_fut_short   BIGINT DEFAULT 0,
    fii_stk_fut_net     BIGINT DEFAULT 0,
    fii_idx_call_long   BIGINT DEFAULT 0,
    fii_idx_call_short  BIGINT DEFAULT 0,
    fii_idx_call_net    BIGINT DEFAULT 0,
    fii_idx_put_long    BIGINT DEFAULT 0,
    fii_idx_put_short   BIGINT DEFAULT 0,
    fii_idx_put_net     BIGINT DEFAULT 0,
    dii_idx_fut_long    BIGINT DEFAULT 0,
    dii_idx_fut_short   BIGINT DEFAULT 0,
    dii_idx_fut_net     BIGINT DEFAULT 0,
    dii_stk_fut_long    BIGINT DEFAULT 0,
    dii_stk_fut_short   BIGINT DEFAULT 0,
    dii_stk_fut_net     BIGINT DEFAULT 0,
    pcr                 DOUBLE DEFAULT 0,
    sentiment_score     DOUBLE DEFAULT 50,
    updated_at          VARCHAR DEFAULT ''
);
"""


# ---------------------------------------------------------------------------
# NSE session + fetch helpers (absorbed from fii-dii-data)
# ---------------------------------------------------------------------------


def _refresh_nse_session(client: httpx.Client) -> str:
    """Hit NSE homepage to obtain fresh session cookies.

    Returns:
        Cookie string for subsequent requests.
    """
    try:
        resp = client.get(_NSE_HOME, timeout=10.0)
        cookies = resp.headers.get_list("set-cookie")
        if cookies:
            return "; ".join(c.split(";")[0] for c in cookies)
    except httpx.HTTPError as exc:
        logger.warning("Failed to refresh NSE session: %s", exc)
    return ""


def _with_retry(
    fn: Any,
    label: str,
    max_attempts: int = _MAX_RETRIES,
) -> Any:
    """Execute ``fn()`` with exponential backoff retries.

    Args:
        fn: Callable to execute.
        label: Label for log messages.
        max_attempts: Maximum retry attempts.

    Returns:
        Result of ``fn()``.

    Raises:
        Exception: The last exception if all attempts fail.
    """
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_attempts:
                delay = _RETRY_BASE_DELAY * attempt
                logger.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.1fs",
                    label, attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def _fetch_nse_cash(client: httpx.Client, cookies: str) -> list[dict[str, Any]]:
    """Fetch cash-segment FII/DII data from NSE API.

    Args:
        client: httpx Client with headers pre-set.
        cookies: NSE session cookies.

    Returns:
        List of category dicts from the NSE API.
    """
    def _do_fetch() -> list[dict[str, Any]]:
        headers = {**_HEADERS, "Cookie": cookies}
        resp = client.get(_NSE_API, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) > 0:
            return data
        raise ValueError("NSE API returned empty or non-array response")

    return _with_retry(_do_fetch, "NSE cash API")


def _fetch_fao_oi(
    client: httpx.Client,
    cookies: str,
    date_str: str,
) -> str | None:
    """Fetch F&O participant OI CSV from NSE archives.

    The ``date_str`` is in ``DD-Mon-YYYY`` format (e.g. ``"01-Apr-2026"``).

    Args:
        client: httpx Client.
        cookies: NSE session cookies.
        date_str: Trade date string from NSE API.

    Returns:
        CSV text or None if unavailable.
    """
    parts = date_str.split("-")
    if len(parts) != 3:
        return None
    day = parts[0].zfill(2)
    month = _MONTHS.get(parts[1])
    year = parts[2]
    if not month:
        return None

    date_part = f"{day}{month}{year}"
    urls = [
        f"{_FAO_BASE}/fao_participant_oi_{date_part}_b.csv",
        f"{_FAO_BASE}/fao_participant_oi_{date_part}.csv",
    ]

    headers = {**_HEADERS, "Cookie": cookies}
    for url in urls:
        try:
            resp = client.get(url, headers=headers, timeout=15.0)
            if resp.status_code == 200 and len(resp.text) > 50:
                return resp.text
        except httpx.HTTPError:
            continue
    return None


def _parse_fao_csv(csv_text: str | None) -> dict[str, dict[str, int]]:
    """Parse F&O participant OI CSV into FII/DII dicts.

    Absorbed from fii-dii-data's ``parseFao`` function.

    Args:
        csv_text: Raw CSV text from NSE.

    Returns:
        Dict with ``"FII"`` and/or ``"DII"`` keys, each mapping to
        OI position fields.
    """
    result: dict[str, dict[str, int]] = {}
    if not csv_text:
        return result

    lines = csv_text.strip().split("\n")
    if len(lines) < 2:
        return result

    reader = csv.reader(lines[1:])
    for row in reader:
        if len(row) < 9:
            continue
        client_type = row[0].strip().upper()
        if "FII" not in client_type and "DII" not in client_type:
            continue

        key = "FII" if "FII" in client_type else "DII"

        def _int(val: str) -> int:
            try:
                return int(val.strip().replace(",", ""))
            except (ValueError, IndexError):
                return 0

        result[key] = {
            "idx_fut_long": _int(row[1]),
            "idx_fut_short": _int(row[2]),
            "stk_fut_long": _int(row[3]),
            "stk_fut_short": _int(row[4]),
            "idx_call_long": _int(row[5]),
            "idx_call_short": _int(row[6]),
            "idx_put_long": _int(row[7]),
            "idx_put_short": _int(row[8]),
        }

    return result


def _compute_sentiment(
    fii_net: float,
    fii_idx_fut_net: int,
    pcr: float,
) -> float:
    """Derive a 0-100 sentiment score from flows.

    Absorbed from fii-dii-data's sentiment heuristic.

    Args:
        fii_net: FII net cash flow (in crores).
        fii_idx_fut_net: FII index futures net OI.
        pcr: FII put-call ratio.

    Returns:
        Sentiment score clamped to [0, 100].
    """
    sentiment = 50.0
    sentiment += fii_net / 200.0
    sentiment += fii_idx_fut_net / 5000.0
    if pcr > 1.3:
        sentiment -= 10.0
    if pcr < 0.7:
        sentiment += 10.0
    return round(max(0.0, min(100.0, sentiment)), 1)


def _transform_data(
    raw_cash: list[dict[str, Any]],
    fao_csv: str | None,
) -> FiiDiiSnapshot | None:
    """Transform raw NSE data into a ``FiiDiiSnapshot``.

    Absorbed from fii-dii-data's ``transformData`` function.

    Args:
        raw_cash: List of category dicts from NSE cash API.
        fao_csv: Raw F&O participant OI CSV text (may be None).

    Returns:
        FiiDiiSnapshot or None if no valid data.
    """
    snap = FiiDiiSnapshot()

    for row in raw_cash:
        cat = str(row.get("category", "")).upper()
        if "FII" in cat or "FPI" in cat:
            snap.fii_buy = float(row.get("buyValue", 0))
            snap.fii_sell = float(row.get("sellValue", 0))
            snap.fii_net = float(row.get("netValue", 0))
            snap.trade_date = str(row.get("date", ""))
        elif "DII" in cat:
            snap.dii_buy = float(row.get("buyValue", 0))
            snap.dii_sell = float(row.get("sellValue", 0))
            snap.dii_net = float(row.get("netValue", 0))

    if not snap.trade_date:
        return None

    fao = _parse_fao_csv(fao_csv)

    if "FII" in fao:
        f = fao["FII"]
        snap.fii_idx_fut_long = f["idx_fut_long"]
        snap.fii_idx_fut_short = f["idx_fut_short"]
        snap.fii_idx_fut_net = f["idx_fut_long"] - f["idx_fut_short"]
        snap.fii_stk_fut_long = f["stk_fut_long"]
        snap.fii_stk_fut_short = f["stk_fut_short"]
        snap.fii_stk_fut_net = f["stk_fut_long"] - f["stk_fut_short"]
        snap.fii_idx_call_long = f["idx_call_long"]
        snap.fii_idx_call_short = f["idx_call_short"]
        snap.fii_idx_call_net = f["idx_call_long"] - f["idx_call_short"]
        snap.fii_idx_put_long = f["idx_put_long"]
        snap.fii_idx_put_short = f["idx_put_short"]
        snap.fii_idx_put_net = f["idx_put_long"] - f["idx_put_short"]

        if f["idx_call_short"] > 0:
            snap.pcr = round(f["idx_put_short"] / f["idx_call_short"], 2)
        else:
            snap.pcr = 1.0

        snap.sentiment_score = _compute_sentiment(
            snap.fii_net, snap.fii_idx_fut_net, snap.pcr
        )

    if "DII" in fao:
        d = fao["DII"]
        snap.dii_idx_fut_long = d["idx_fut_long"]
        snap.dii_idx_fut_short = d["idx_fut_short"]
        snap.dii_idx_fut_net = d["idx_fut_long"] - d["idx_fut_short"]
        snap.dii_stk_fut_long = d["stk_fut_long"]
        snap.dii_stk_fut_short = d["stk_fut_short"]
        snap.dii_stk_fut_net = d["stk_fut_long"] - d["stk_fut_short"]

    snap.updated_at = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    return snap


# ---------------------------------------------------------------------------
# FiiDiiTracker
# ---------------------------------------------------------------------------


class FiiDiiTracker:
    """Fetch, cache, and query FII/DII institutional flow data.

    Scrapes NSE for daily cash + F&O data, caches in DuckDB, and provides
    trend analysis.  Follows the same pipeline pattern as fii-dii-data:
    fetch -> transform -> validate -> store -> serve.

    Args:
        db_path: Path to DuckDB database.  Use ``":memory:"`` for tests.
    """

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(
                Path.home() / ".flinttrade" / "data" / "fii_dii.duckdb"
            )
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            if self._db_path == ":memory:":
                self._conn = duckdb.connect(":memory:")
            else:
                Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
                self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        self.connection.execute(_SCHEMA_FII_DII)

    # ------------------------------------------------------------------
    # Store / retrieve
    # ------------------------------------------------------------------

    def _upsert(self, snap: FiiDiiSnapshot) -> None:
        """Insert or replace a snapshot in DuckDB."""
        self.connection.execute(
            """INSERT OR REPLACE INTO fii_dii_flows VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            [
                snap.trade_date,
                snap.fii_buy, snap.fii_sell, snap.fii_net,
                snap.dii_buy, snap.dii_sell, snap.dii_net,
                snap.fii_idx_fut_long, snap.fii_idx_fut_short, snap.fii_idx_fut_net,
                snap.fii_stk_fut_long, snap.fii_stk_fut_short, snap.fii_stk_fut_net,
                snap.fii_idx_call_long, snap.fii_idx_call_short, snap.fii_idx_call_net,
                snap.fii_idx_put_long, snap.fii_idx_put_short, snap.fii_idx_put_net,
                snap.dii_idx_fut_long, snap.dii_idx_fut_short, snap.dii_idx_fut_net,
                snap.dii_stk_fut_long, snap.dii_stk_fut_short, snap.dii_stk_fut_net,
                snap.pcr, snap.sentiment_score, snap.updated_at,
            ],
        )

    def _row_to_snapshot(self, columns: list[str], row: tuple[Any, ...]) -> FiiDiiSnapshot:
        """Convert a DuckDB result row to a FiiDiiSnapshot."""
        d = dict(zip(columns, row))
        return FiiDiiSnapshot(**d)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_latest(self) -> FiiDiiSnapshot | None:
        """Fetch the latest FII/DII data from NSE and cache it.

        Follows fii-dii-data's pipeline: refresh session -> fetch cash ->
        fetch F&O OI -> transform -> validate -> store.

        Returns:
            FiiDiiSnapshot, or None if NSE data is unavailable.
        """
        try:
            with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
                cookies = _refresh_nse_session(client)
                raw_cash = _fetch_nse_cash(client, cookies)

                # Find the target date from the response
                target_date = ""
                for row in raw_cash:
                    cat = str(row.get("category", "")).upper()
                    if "FII" in cat or "FPI" in cat or "DII" in cat:
                        target_date = str(row.get("date", ""))
                        break

                if not target_date:
                    logger.info("No date found in NSE FII/DII response")
                    return None

                # Check if we already have this date's data
                existing = self.get_data_for_date(target_date)
                if existing is not None and existing.fii_net != 0:
                    logger.info("FII/DII data for %s already cached", target_date)
                    return existing

                fao_csv = _fetch_fao_oi(client, cookies, target_date)
                snap = _transform_data(raw_cash, fao_csv)

                if snap is None:
                    return None

                self._upsert(snap)
                logger.info(
                    "FII/DII updated: %s (FII net: %.2f)", snap.trade_date, snap.fii_net
                )
                return snap

        except Exception as exc:  # noqa: BLE001
            logger.error("FII/DII fetch pipeline failed: %s", exc)
            return None

    def get_data_for_date(self, trade_date: str) -> FiiDiiSnapshot | None:
        """Get cached FII/DII data for a specific date.

        Args:
            trade_date: Trade date string (NSE format, e.g. ``"01-Apr-2026"``).

        Returns:
            FiiDiiSnapshot or None if not cached.
        """
        result = self.connection.execute(
            "SELECT * FROM fii_dii_flows WHERE trade_date = ?",
            [trade_date],
        )
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(columns, row)

    def get_trend(self, days: int = 30) -> FiiDiiTrend:
        """Get the FII/DII trend for the last N trading days.

        Args:
            days: Number of most recent records to include.

        Returns:
            FiiDiiTrend with aggregated statistics.
        """
        result = self.connection.execute(
            "SELECT * FROM fii_dii_flows ORDER BY trade_date DESC LIMIT ?",
            [days],
        )
        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()

        snapshots = [self._row_to_snapshot(columns, r) for r in rows]

        fii_total = sum(s.fii_net for s in snapshots)
        dii_total = sum(s.dii_net for s in snapshots)
        avg_sent = (
            sum(s.sentiment_score for s in snapshots) / len(snapshots)
            if snapshots
            else 50.0
        )

        return FiiDiiTrend(
            days=len(snapshots),
            snapshots=snapshots,
            fii_net_total=round(fii_total, 2),
            dii_net_total=round(dii_total, 2),
            avg_sentiment=round(avg_sent, 1),
        )

    def get_latest_cached(self) -> FiiDiiSnapshot | None:
        """Return the most recent cached snapshot without fetching.

        Returns:
            FiiDiiSnapshot or None if the cache is empty.
        """
        result = self.connection.execute(
            "SELECT * FROM fii_dii_flows ORDER BY trade_date DESC LIMIT 1"
        )
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_snapshot(columns, row)

    def store_snapshot(self, snap: FiiDiiSnapshot) -> None:
        """Manually store a FiiDiiSnapshot (e.g. from tests or imports).

        Args:
            snap: Snapshot to store.
        """
        self._upsert(snap)


# ---------------------------------------------------------------------------
# Sample data for dev/fallback mode
# ---------------------------------------------------------------------------


def make_sample_fii_dii() -> FiiDiiSnapshot:
    """Generate a synthetic FII/DII snapshot for dev/fallback mode.

    Returns:
        FiiDiiSnapshot with realistic sample values.
    """
    return FiiDiiSnapshot(
        trade_date=date.today().strftime("%d-%b-%Y"),
        fii_buy=12500.0,
        fii_sell=13200.0,
        fii_net=-700.0,
        dii_buy=11800.0,
        dii_sell=10900.0,
        dii_net=900.0,
        fii_idx_fut_long=125000,
        fii_idx_fut_short=140000,
        fii_idx_fut_net=-15000,
        fii_stk_fut_long=80000,
        fii_stk_fut_short=75000,
        fii_stk_fut_net=5000,
        fii_idx_call_long=90000,
        fii_idx_call_short=110000,
        fii_idx_call_net=-20000,
        fii_idx_put_long=95000,
        fii_idx_put_short=85000,
        fii_idx_put_net=10000,
        dii_idx_fut_long=60000,
        dii_idx_fut_short=55000,
        dii_idx_fut_net=5000,
        dii_stk_fut_long=45000,
        dii_stk_fut_short=50000,
        dii_stk_fut_net=-5000,
        pcr=0.77,
        sentiment_score=42.5,
        updated_at=datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST"),
    )


def make_sample_trend(days: int = 10) -> FiiDiiTrend:
    """Generate a synthetic FII/DII trend for dev/fallback mode.

    Args:
        days: Number of days in the trend.

    Returns:
        FiiDiiTrend with synthetic daily data.
    """
    import math

    snapshots: list[FiiDiiSnapshot] = []
    base_date = date.today()

    for i in range(days):
        d = base_date - timedelta(days=i)
        # Sinusoidal pattern for realistic look
        phase = i * 0.5
        fii_net = round(-500 + 800 * math.sin(phase), 2)
        dii_net = round(400 - 600 * math.sin(phase + 1.0), 2)
        sentiment = round(50 + 15 * math.sin(phase), 1)

        snapshots.append(FiiDiiSnapshot(
            trade_date=d.strftime("%d-%b-%Y"),
            fii_buy=round(12000 + 500 * math.sin(phase), 2),
            fii_sell=round(12000 + 500 * math.sin(phase) - fii_net, 2),
            fii_net=fii_net,
            dii_buy=round(11000 + 400 * math.sin(phase + 1), 2),
            dii_sell=round(11000 + 400 * math.sin(phase + 1) - dii_net, 2),
            dii_net=dii_net,
            pcr=round(0.8 + 0.3 * math.sin(phase + 0.5), 2),
            sentiment_score=max(0, min(100, sentiment)),
            updated_at=d.strftime("%Y-%m-%d 18:00:00 IST"),
        ))

    fii_total = sum(s.fii_net for s in snapshots)
    dii_total = sum(s.dii_net for s in snapshots)
    avg_sent = sum(s.sentiment_score for s in snapshots) / len(snapshots) if snapshots else 50.0

    return FiiDiiTrend(
        days=len(snapshots),
        snapshots=snapshots,
        fii_net_total=round(fii_total, 2),
        dii_net_total=round(dii_total, 2),
        avg_sentiment=round(avg_sent, 1),
    )
