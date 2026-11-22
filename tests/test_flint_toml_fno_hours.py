"""flint.toml F&O hours must agree with the session clock in market_hours."""

from __future__ import annotations

import tomllib
from datetime import date, timedelta
from pathlib import Path

from flinttrade_engine import market_hours

FLINT_TOML = Path(__file__).resolve().parents[1] / "flint.toml"


def _exchanges() -> dict:
    return tomllib.loads(FLINT_TOML.read_text(encoding="utf-8"))["exchanges"]


def _windows() -> list[dict]:
    return _exchanges()["fno_sessions"]


def test_fno_segments_point_at_the_dated_sessions():
    for segment in ("NFO", "BFO"):
        assert _exchanges()[segment]["sessions"] == "fno_sessions"


def test_fno_windows_are_contiguous_and_switch_on_the_clock_dates():
    windows = _windows()
    assert "from" not in windows[0]
    assert "until" not in windows[-1]
    for earlier, later in zip(windows, windows[1:]):
        assert date.fromisoformat(later["from"]) - date.fromisoformat(earlier["until"]) == timedelta(days=1)
    starts = [date.fromisoformat(window["from"]) for window in windows[1:]]
    assert starts == sorted(starts_from for starts_from, _close in market_hours._NFO_CLOSE_WINDOWS)


def test_every_fno_window_matches_the_clock_at_both_ends():
    for window in _windows():
        open_label, close_label = window["hours"].split("-")
        ends = [date.fromisoformat(window[key]) for key in ("from", "until") if key in window]
        if "from" not in window:
            ends.append(date.fromisoformat(window["until"]) - timedelta(days=365))
        if "until" not in window:
            ends.append(date.fromisoformat(window["from"]) + timedelta(days=365))
        for day in ends:
            for segment in ("NFO", "BFO"):
                opens, closes = market_hours.get_market_hours(segment, day)
                assert (opens.strftime("%H:%M"), closes.strftime("%H:%M")) == (open_label, close_label), (segment, day)


def test_index_expiry_close_matches_the_clock():
    revised = _windows()[-1]
    assert revised["index_expiry_close"] == market_hours._NFO_EXPIRING_INDEX_CLOSE.strftime("%H:%M")
    expiry = date.fromisoformat(revised["from"]) + timedelta(days=8)
    symbol = f"NIFTY{expiry.strftime('%d%b%y').upper()}24000CE"
    close = market_hours.derivative_contract_close("NFO", expiry, symbol=symbol, expiry_calendar=[expiry])
    assert close.strftime("%H:%M") == revised["index_expiry_close"]


def test_deploy_freeze_covers_the_latest_fno_close():
    latest_close = _windows()[-1]["hours"].split("-")[1]
    assert _exchanges()["deploy_freeze"]["equity_end"] >= latest_close
