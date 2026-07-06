"""Backend → desktop-shell notification producer (counterpart to lib.rs)."""

from __future__ import annotations

import pytest

from flinttrade_core.desktop_notify import NOTIFY_SENTINEL, notify


def test_no_op_without_desktop_shell(monkeypatch, capsys):
    monkeypatch.delenv("FLINTTRADE_DESKTOP", raising=False)
    notify("Order filled", "RELIANCE BUY 10")
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("flag", ["0", "false", ""])
def test_disabled_values_stay_silent(monkeypatch, capsys, flag):
    monkeypatch.setenv("FLINTTRADE_DESKTOP", flag)
    notify("Order filled", "body")
    assert capsys.readouterr().out == ""


def test_emits_tab_delimited_sentinel_under_desktop_shell(monkeypatch, capsys):
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    notify("Order filled", "RELIANCE BUY 10 @ 2900")
    out = capsys.readouterr().out
    assert out == f"{NOTIFY_SENTINEL}\tOrder filled\tRELIANCE BUY 10 @ 2900\n"


def test_flattens_tabs_and_newlines_to_keep_one_line(monkeypatch, capsys):
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    notify("Kill\tswitch\narmed", "line1\nline2\twith tabs")
    out = capsys.readouterr().out
    # Exactly one line, and the payload tabs are the two delimiters only.
    assert out.count("\n") == 1
    assert out == f"{NOTIFY_SENTINEL}\tKill switch armed\tline1 line2 with tabs\n"


def test_empty_title_is_dropped(monkeypatch, capsys):
    monkeypatch.setenv("FLINTTRADE_DESKTOP", "1")
    notify("   ", "body")
    assert capsys.readouterr().out == ""
