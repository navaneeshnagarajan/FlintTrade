"""Per-user chart preferences — themes, indicator sets, and layout presets.

Stored in DuckDB for multi-user readiness.  Three logical stores:

1. **Themes** — chart colour/style themes per user
2. **Indicator sets** — named collections of indicator configs (e.g. "My Scalping Setup")
3. **Layouts** — serialised Dockview/chart panel layouts per user

All three are held in a single DuckDB file (``flint.duckdb`` by default) using
three separate tables, each keyed by ``user_id``.

Example::

    from packages.core.src.chart_prefs import ChartPreferences

    prefs = ChartPreferences()
    prefs.set_theme("u1", {"background": "#0a0a0f", "upColor": "#22c55e"})
    theme = prefs.get_theme("u1")

    prefs.save_indicator_set("u1", "scalping", [{"name": "EMA", "params": {"period": 9}}])
    indicators = prefs.load_indicator_set("u1", "scalping")

    prefs.save_layout("u1", "intraday", {"panels": []})
    layout = prefs.load_layout("u1", "intraday")
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger("flinttrade.core.chart_prefs")

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_THEME_DDL = """
CREATE TABLE IF NOT EXISTS chart_prefs_theme (
    user_id     VARCHAR NOT NULL PRIMARY KEY,
    theme_json  VARCHAR NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP NOT NULL
);
"""

_INDICATOR_DDL = """
CREATE TABLE IF NOT EXISTS chart_prefs_indicators (
    user_id         VARCHAR NOT NULL,
    set_name        VARCHAR NOT NULL,
    indicators_json VARCHAR NOT NULL DEFAULT '[]',
    updated_at      TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, set_name)
);
"""

_LAYOUT_DDL = """
CREATE TABLE IF NOT EXISTS chart_prefs_layout (
    user_id     VARCHAR NOT NULL,
    layout_name VARCHAR NOT NULL,
    layout_json VARCHAR NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP NOT NULL,
    PRIMARY KEY (user_id, layout_name)
);
"""


def _default_db_path() -> str:
    """Resolve DuckDB path: env override > workspace > fallback."""
    env = os.getenv("DUCKDB_PATH")
    if env:
        return env
    try:
        from packages.core.src.workspace import Workspace  # noqa: PLC0415
        return str(Workspace().fast_data_dir / "flint.duckdb")
    except Exception:
        return str(Path.home() / ".flinttrade" / "data" / "flint.duckdb")


# ---------------------------------------------------------------------------
# ChartPreferences
# ---------------------------------------------------------------------------


class ChartPreferences:
    """Per-user chart theme, indicator set, and layout preferences.

    Args:
        db_path: DuckDB file path.  Defaults to the shared ``flint.duckdb``.

    All methods accept ``user_id`` as the first positional argument.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _default_db_path()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._ensure_schema()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Lazy DuckDB connection."""
        if self._conn is None:
            self._conn = duckdb.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Close the DuckDB connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> ChartPreferences:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _ensure_schema(self) -> None:
        conn = self.connection
        conn.execute(_THEME_DDL)
        conn.execute(_INDICATOR_DDL)
        conn.execute(_LAYOUT_DDL)
        logger.debug("ChartPreferences: schema ready at %s", self._db_path)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def set_theme(self, user_id: str, theme: dict[str, Any]) -> None:
        """Persist a chart theme for a user.

        Args:
            user_id: User identifier.
            theme: Dict of theme properties (colours, grid, etc.).
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.connection.execute(
            """
            INSERT INTO chart_prefs_theme (user_id, theme_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (user_id) DO UPDATE SET
                theme_json = excluded.theme_json,
                updated_at = excluded.updated_at
            """,
            [user_id, json.dumps(theme), now],
        )
        logger.debug("ChartPreferences.set_theme: user=%s", user_id)

    def get_theme(self, user_id: str) -> dict[str, Any] | None:
        """Return the stored chart theme for a user.

        Args:
            user_id: User identifier.

        Returns:
            Theme dict, or ``None`` if no theme has been saved.
        """
        row = self.connection.execute(
            "SELECT theme_json FROM chart_prefs_theme WHERE user_id = ?",
            [user_id],
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Indicator sets
    # ------------------------------------------------------------------

    def save_indicator_set(
        self,
        user_id: str,
        name: str,
        indicators: list[dict[str, Any]],
    ) -> None:
        """Save a named indicator set for a user.

        Args:
            user_id: User identifier.
            name: Friendly name, e.g. ``"My Scalping Setup"``.
            indicators: List of indicator config dicts.
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.connection.execute(
            """
            INSERT INTO chart_prefs_indicators (user_id, set_name, indicators_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, set_name) DO UPDATE SET
                indicators_json = excluded.indicators_json,
                updated_at      = excluded.updated_at
            """,
            [user_id, name, json.dumps(indicators), now],
        )
        logger.debug(
            "ChartPreferences.save_indicator_set: user=%s name=%s count=%d",
            user_id, name, len(indicators),
        )

    def load_indicator_set(
        self,
        user_id: str,
        name: str,
    ) -> list[dict[str, Any]] | None:
        """Load a named indicator set.

        Args:
            user_id: User identifier.
            name: Set name.

        Returns:
            List of indicator config dicts, or ``None`` if not found.
        """
        row = self.connection.execute(
            "SELECT indicators_json FROM chart_prefs_indicators WHERE user_id = ? AND set_name = ?",
            [user_id, name],
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])  # type: ignore[no-any-return]

    def list_indicator_sets(self, user_id: str) -> list[str]:
        """Return the names of all saved indicator sets for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of set names.
        """
        rows = self.connection.execute(
            "SELECT set_name FROM chart_prefs_indicators WHERE user_id = ? ORDER BY set_name",
            [user_id],
        ).fetchall()
        return [row[0] for row in rows]

    def delete_indicator_set(self, user_id: str, name: str) -> bool:
        """Delete a named indicator set.

        Args:
            user_id: User identifier.
            name: Set name.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        before = self.connection.execute(
            "SELECT COUNT(*) FROM chart_prefs_indicators WHERE user_id = ? AND set_name = ?",
            [user_id, name],
        ).fetchone()[0]  # type: ignore[index]
        if not before:
            return False
        self.connection.execute(
            "DELETE FROM chart_prefs_indicators WHERE user_id = ? AND set_name = ?",
            [user_id, name],
        )
        logger.debug("ChartPreferences.delete_indicator_set: user=%s name=%s", user_id, name)
        return True

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------

    def save_layout(
        self,
        user_id: str,
        layout_name: str,
        layout: dict[str, Any],
    ) -> None:
        """Persist a named chart layout for a user.

        Args:
            user_id: User identifier.
            layout_name: Layout identifier, e.g. ``"intraday"``.
            layout: Serialised layout dict (Dockview / panel state).
        """
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        self.connection.execute(
            """
            INSERT INTO chart_prefs_layout (user_id, layout_name, layout_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, layout_name) DO UPDATE SET
                layout_json = excluded.layout_json,
                updated_at  = excluded.updated_at
            """,
            [user_id, layout_name, json.dumps(layout), now],
        )
        logger.debug(
            "ChartPreferences.save_layout: user=%s layout=%s", user_id, layout_name
        )

    def load_layout(
        self,
        user_id: str,
        layout_name: str,
    ) -> dict[str, Any] | None:
        """Load a named chart layout.

        Args:
            user_id: User identifier.
            layout_name: Layout identifier.

        Returns:
            Layout dict, or ``None`` if not found.
        """
        row = self.connection.execute(
            "SELECT layout_json FROM chart_prefs_layout WHERE user_id = ? AND layout_name = ?",
            [user_id, layout_name],
        ).fetchone()
        if row is None:
            return None
        return json.loads(row[0])  # type: ignore[no-any-return]

    def list_layouts(self, user_id: str) -> list[str]:
        """Return the names of all saved layouts for a user.

        Args:
            user_id: User identifier.

        Returns:
            List of layout names.
        """
        rows = self.connection.execute(
            "SELECT layout_name FROM chart_prefs_layout WHERE user_id = ? ORDER BY layout_name",
            [user_id],
        ).fetchall()
        return [row[0] for row in rows]

    def delete_layout(self, user_id: str, layout_name: str) -> bool:
        """Delete a named layout.

        Args:
            user_id: User identifier.
            layout_name: Layout identifier.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        before = self.connection.execute(
            "SELECT COUNT(*) FROM chart_prefs_layout WHERE user_id = ? AND layout_name = ?",
            [user_id, layout_name],
        ).fetchone()[0]  # type: ignore[index]
        if not before:
            return False
        self.connection.execute(
            "DELETE FROM chart_prefs_layout WHERE user_id = ? AND layout_name = ?",
            [user_id, layout_name],
        )
        logger.debug("ChartPreferences.delete_layout: user=%s layout=%s", user_id, layout_name)
        return True
