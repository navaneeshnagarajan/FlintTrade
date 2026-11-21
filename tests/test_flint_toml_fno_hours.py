"""flint.toml F&O hours must agree with the session clock in market_hours."""

from __future__ import annotations

import tomllib
from pathlib import Path

from flinttrade_engine import market_hours

FLINT_TOML = Path(__file__).resolve().parents[1] / "flint.toml"


def _exchanges() -> dict:
    return tomllib.loads(FLINT_TOML.read_text(encoding="utf-8"))["exchanges"]


def test_fno_revised_close_matches_the_clock():
    revised_close = market_hours._NFO_CLOSE_REVISED.strftime("%H:%M")
    for segment in ("NFO", "BFO"):
        entry = _exchanges()[segment]
        assert entry["revised_from"] == market_hours._CAS_REVISION.isoformat()
        assert entry["revised_hours"].endswith(f"-{revised_close}")
        assert entry["index_expiry_close"] == "15:30"


def test_deploy_freeze_covers_the_revised_fno_close():
    revised_close = market_hours._NFO_CLOSE_REVISED.strftime("%H:%M")
    assert _exchanges()["deploy_freeze"]["equity_end"] >= revised_close
