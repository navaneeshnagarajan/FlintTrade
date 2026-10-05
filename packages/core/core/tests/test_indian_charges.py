"""Paisa checks for the shared Indian charges table.

The money assertions recompute each component from the loaded rate row.
They do not call ``calculate_leg``, so a rounding or side bug in the
calculator fails here.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from flinttrade_core.indian_charges import (
    break_even_points,
    load_rates,
    lookup_rate,
    option_exercise_stt,
    round_trip,
    statutory_mirror_defaults,
    table_path,
)
from flinttrade_core.instrument_lots import lot_size_from_master

_ON = date(2026, 4, 2)
_TWO = Decimal("0.01")
_ROOT = Path(__file__).resolve().parents[4]

_FORBIDDEN = (
    "0.0000325",
    "1.73e-5",
    "1.73e-05",
    "3.503e-4",
    "3.503e-04",
    "STT_RATE_FUTURES",
    "STT_RATE_OPTIONS",
    "EXCHANGE_TXN",
    "_EXCHANGE_CHARGES",
    "_STT_RATES",
    "_STAMP_DUTY_RATES",
    "≈ ₹30",
)

_SCAN_SUFFIXES = {".py", ".ts", ".tsx", ".md"}
_SKIP_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".local",
    "dist",
    "build",
}


def _money(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def _component(exchange: str, segment: str, component: str, side: str, turnover: Decimal) -> Decimal:
    row = lookup_rate(exchange, segment, component, side, _ON)
    if row is None or row.basis == "gst_base":
        return Decimal(0)
    return _money(turnover * row.rate)


def _leg(exchange: str, segment: str, turnover: Decimal, is_buy: bool) -> dict[str, Decimal]:
    side = "buy" if is_buy else "sell"
    stt = _component(exchange, segment, "stt", side, turnover)
    exchange_charges = _component(exchange, segment, "exchange_transaction", side, turnover)
    sebi = _component(exchange, segment, "sebi", side, turnover)
    stamp = _component(exchange, segment, "stamp_duty", side, turnover)
    gst_rate = lookup_rate("ANY", "any", "gst", side, _ON)
    assert gst_rate is not None
    gst = _money((exchange_charges + sebi) * gst_rate.rate)
    total = _money(stt + exchange_charges + sebi + stamp + gst)
    return {
        "stt": stt,
        "exchange_charges": exchange_charges,
        "sebi_fee": sebi,
        "stamp_duty": stamp,
        "gst": gst,
        "total": total,
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exchange", "segment", "turnover"),
    [
        ("NSE", "equity_futures", Decimal("10000000")),
        ("NSE", "equity_options", Decimal("1000000")),
        ("BSE", "equity_futures", Decimal("10000000")),
        ("BSE", "sensex_options", Decimal("1000000")),
    ],
)
def test_round_trip_matches_the_table_to_the_paisa(
    exchange: str,
    segment: str,
    turnover: Decimal,
) -> None:
    buy_expected = _leg(exchange, segment, turnover, True)
    sell_expected = _leg(exchange, segment, turnover, False)
    buy, sell = round_trip(
        exchange=exchange,
        segment=segment,
        buy_value=turnover,
        sell_value=turnover,
        on=_ON,
    )
    for name, expected in buy_expected.items():
        assert getattr(buy, name) == expected, name
    for name, expected in sell_expected.items():
        assert getattr(sell, name) == expected, name
    assert buy.brokerage == Decimal("0.00")
    assert sell.brokerage == Decimal("0.00")


@pytest.mark.unit
def test_published_exchange_totals() -> None:
    """Client totals named by the exchange circulars, in force on 2 April 2026."""
    cases = {
        ("NSE", "equity_futures"): Decimal("0.0000183"),
        ("NSE", "equity_options"): Decimal("0.0003553"),
        ("BSE", "equity_futures"): Decimal("0"),
        ("BSE", "sensex_options"): Decimal("0.000325"),
        ("BSE", "equity_options"): Decimal("0.00005"),
    }
    for (exchange, segment), rate in cases.items():
        row = lookup_rate(exchange, segment, "exchange_transaction", "buy", _ON)
        assert row is not None
        assert row.rate == rate
        assert row.effective_from <= _ON


@pytest.mark.unit
def test_futures_stt_is_sell_side_only() -> None:
    row = lookup_rate("ANY", "equity_futures", "stt", "buy", _ON)
    assert row is None
    sell = lookup_rate("ANY", "equity_futures", "stt", "sell", _ON)
    assert sell is not None
    assert sell.rate == Decimal("0.0005")


@pytest.mark.unit
def test_mirror_defaults_are_the_shared_table() -> None:
    defaults = statutory_mirror_defaults(_ON)
    futures = lookup_rate("NSE", "equity_futures", "exchange_transaction", "buy", _ON)
    sensex = lookup_rate("BSE", "sensex_options", "exchange_transaction", "buy", _ON)
    bse_futures = lookup_rate("BSE", "equity_futures", "exchange_transaction", "buy", _ON)
    assert futures is not None and sensex is not None and bse_futures is not None
    assert defaults["exchange_charge_futures"] == float(futures.rate)
    assert defaults["exchange_charge_sensex_options"] == float(sensex.rate)
    assert defaults["exchange_charge_futures_bse"] == float(bse_futures.rate)
    assert defaults["exchange_charge_futures_bse"] == 0.0


@pytest.mark.unit
def test_every_rate_has_exchange_and_effective_from() -> None:
    rows = load_rates()
    assert rows
    for row in rows:
        assert row.exchange
        assert row.effective_from
        assert row.per_contract_inr == Decimal(0)


def _published_leg(
    turnover: Decimal,
    *,
    stt: Decimal,
    exchange_rate: Decimal,
    stamp: Decimal,
    sebi: Decimal,
    gst: Decimal,
) -> dict[str, Decimal]:
    """Paisa total from the verified rates, not from a row the table returned."""
    exchange_charges = _money(turnover * exchange_rate)
    sebi_fee = _money(turnover * sebi)
    stamp_duty = _money(turnover * stamp)
    stt_amount = _money(turnover * stt)
    gst_amount = _money((exchange_charges + sebi_fee) * gst)
    total = _money(stt_amount + exchange_charges + sebi_fee + stamp_duty + gst_amount)
    return {
        "stt": stt_amount,
        "exchange_charges": exchange_charges,
        "sebi_fee": sebi_fee,
        "stamp_duty": stamp_duty,
        "gst": gst_amount,
        "total": total,
    }


@pytest.mark.unit
def test_verified_rates_and_effective_dates() -> None:
    """The table matches the exchange and Finance Act figures, including dates."""
    cases = [
        ("ANY", "equity_futures", "stt", "sell", Decimal("0.0005"), date(2026, 4, 1)),
        ("ANY", "equity_options", "stt", "sell", Decimal("0.0015"), date(2026, 4, 1)),
        ("ANY", "equity_intraday", "stt", "sell", Decimal("0.00025"), date(2004, 10, 1)),
        ("ANY", "equity_delivery", "stt", "buy", Decimal("0.001"), date(2004, 10, 1)),
        ("ANY", "equity_delivery", "stt", "sell", Decimal("0.001"), date(2004, 10, 1)),
        ("NSE", "equity_futures", "exchange_transaction", "buy", Decimal("0.0000183"), date(2026, 3, 1)),
        ("NSE", "equity_options", "exchange_transaction", "buy", Decimal("0.0003553"), date(2026, 3, 1)),
        ("NSE", "equity_intraday", "exchange_transaction", "buy", Decimal("0.0000307"), date(2026, 3, 1)),
        ("NSE", "equity_delivery", "exchange_transaction", "buy", Decimal("0.0000307"), date(2026, 3, 1)),
        ("BSE", "equity_futures", "exchange_transaction", "buy", Decimal("0"), date(2024, 10, 1)),
        ("BSE", "sensex_options", "exchange_transaction", "buy", Decimal("0.000325"), date(2024, 10, 1)),
        ("BSE", "bankex_options", "exchange_transaction", "buy", Decimal("0.000325"), date(2024, 10, 1)),
        ("BSE", "sensex50_options", "exchange_transaction", "buy", Decimal("0.00005"), date(2024, 10, 1)),
        ("BSE", "equity_options", "exchange_transaction", "buy", Decimal("0.00005"), date(2024, 10, 1)),
        ("BSE", "equity_delivery", "exchange_transaction", "buy", Decimal("0.0000375"), date(2024, 10, 1)),
        ("BSE", "equity_intraday", "exchange_transaction", "buy", Decimal("0.0000375"), date(2024, 10, 1)),
        ("ANY", "any", "sebi", "buy", Decimal("0.000001"), date(2017, 4, 1)),
        ("ANY", "equity_futures", "stamp_duty", "buy", Decimal("0.00002"), date(2020, 7, 1)),
        ("ANY", "equity_options", "stamp_duty", "buy", Decimal("0.00003"), date(2020, 7, 1)),
        ("ANY", "equity_intraday", "stamp_duty", "buy", Decimal("0.00003"), date(2020, 7, 1)),
        ("ANY", "equity_delivery", "stamp_duty", "buy", Decimal("0.00015"), date(2020, 7, 1)),
        ("ANY", "any", "gst", "buy", Decimal("0.18"), date(2017, 7, 1)),
        ("ANY", "equity_options", "stt", "exercise", Decimal("0.0015"), date(2026, 4, 1)),
    ]
    for exchange, segment, component, side, rate, effective_from in cases:
        row = lookup_rate(exchange, segment, component, side, _ON)
        assert row is not None, (exchange, segment, component, side)
        assert row.rate == rate
        assert row.effective_from == effective_from
    assert lookup_rate("ANY", "equity_futures", "stt", "buy", _ON) is None
    assert lookup_rate("ANY", "equity_futures", "stamp_duty", "sell", _ON) is None
    assert lookup_rate("ANY", "equity_intraday", "stt", "buy", _ON) is None
    stock = lookup_rate("BSE", "equity_options", "exchange_transaction", "buy", _ON)
    sensex50 = lookup_rate("BSE", "sensex50_options", "exchange_transaction", "buy", _ON)
    sensex = lookup_rate("BSE", "sensex_options", "exchange_transaction", "buy", _ON)
    assert stock is not None and sensex50 is not None and sensex is not None
    assert stock is not sensex50
    assert "stock options" in stock.citation
    assert "Sensex 50" in sensex50.citation
    assert sensex.rate != sensex50.rate


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exchange", "segment", "turnover", "stt_sell", "exchange_rate", "stamp_buy"),
    [
        ("NSE", "equity_futures", Decimal("1625000"), Decimal("0.0005"), Decimal("0.0000183"), Decimal("0.00002")),
        ("NSE", "equity_options", Decimal("13000"), Decimal("0.0015"), Decimal("0.0003553"), Decimal("0.00003")),
        ("BSE", "equity_futures", Decimal("1500000"), Decimal("0.0005"), Decimal("0"), Decimal("0.00002")),
        ("BSE", "sensex_options", Decimal("10000"), Decimal("0.0015"), Decimal("0.000325"), Decimal("0.00003")),
    ],
)
def test_named_round_trips_match_the_verified_rates_to_the_paisa(
    exchange: str,
    segment: str,
    turnover: Decimal,
    stt_sell: Decimal,
    exchange_rate: Decimal,
    stamp_buy: Decimal,
) -> None:
    sebi = Decimal("0.000001")
    gst = Decimal("0.18")
    buy_expected = _published_leg(
        turnover, stt=Decimal(0), exchange_rate=exchange_rate, stamp=stamp_buy, sebi=sebi, gst=gst
    )
    sell_expected = _published_leg(
        turnover, stt=stt_sell, exchange_rate=exchange_rate, stamp=Decimal(0), sebi=sebi, gst=gst
    )
    buy, sell = round_trip(
        exchange=exchange,
        segment=segment,
        buy_value=turnover,
        sell_value=turnover,
        on=_ON,
    )
    for name, expected in buy_expected.items():
        assert getattr(buy, name) == expected, name
    for name, expected in sell_expected.items():
        assert getattr(sell, name) == expected, name
    assert buy.stt == Decimal("0.00")


@pytest.mark.unit
def test_nifty_futures_reference_example_to_the_paisa() -> None:
    """One indicative NIFTY futures contract at the near-month master lot, index 25,000.

    Security id 14 is the revision-window fixture (also 65), not this example.
    """
    lot = lot_size_from_master("NIFTY")
    assert lot == 65
    notional = Decimal(lot) * Decimal(25000)
    assert notional == Decimal("1625000")
    buy, sell = round_trip(
        exchange="NSE",
        segment="equity_futures",
        buy_value=notional,
        sell_value=notional,
        on=_ON,
    )
    assert sell.stt == Decimal("812.50")
    assert buy.exchange_charges + sell.exchange_charges == Decimal("59.48")
    assert buy.stamp_duty == Decimal("32.50")
    assert sell.stamp_duty == Decimal("0.00")
    assert buy.sebi_fee + sell.sebi_fee == Decimal("3.26")
    assert buy.gst + sell.gst == Decimal("11.30")
    statutory = buy.total + sell.total
    assert statutory == Decimal("919.04")
    assert buy.exchange_label == "NSE transaction"
    spread = Decimal(lot)
    brokerage = Decimal(40)
    points = break_even_points(
        statutory_round_trip=statutory,
        spread=spread,
        brokerage=brokerage,
        lot_size=lot,
    )
    assert points.quantize(Decimal("1"), rounding=ROUND_HALF_UP) == Decimal("16")


@pytest.mark.unit
def test_option_exercise_stt_is_paid_by_the_buyer_on_settlement_value() -> None:
    settlement = Decimal("1625000")
    exercised = option_exercise_stt(segment="equity_options", settlement_value=settlement, on=_ON)
    assert exercised == Decimal("2437.50")
    buy, _sell = round_trip(
        exchange="NSE",
        segment="equity_options",
        buy_value=Decimal("13000"),
        sell_value=Decimal("13000"),
        on=_ON,
    )
    assert buy.stt == Decimal("0.00")


@pytest.mark.unit
def test_scalping_skill_matches_the_shared_table() -> None:
    """The worked example cannot drift away from the table or the instrument master."""
    skill = (_ROOT / "packages/services/ai/skills/scalping_techniques.md").read_text(encoding="utf-8")
    lot = lot_size_from_master("NIFTY")
    assert lot is not None
    notional = Decimal(lot) * Decimal(25000)
    buy, sell = round_trip(
        exchange="NSE",
        segment="equity_futures",
        buy_value=notional,
        sell_value=notional,
        on=_ON,
    )
    statutory = buy.total + sell.total
    points = break_even_points(
        statutory_round_trip=statutory,
        spread=Decimal(lot),
        brokerage=Decimal(40),
        lot_size=lot,
    )
    assert "30% of gross" not in skill
    assert "75-lot" not in skill
    assert "instrument master" in skill
    assert "twice a year" in skill
    assert "indicative" in skill.lower()
    assert f"lot size {lot}" in skill
    assert f"₹{sell.stt}" in skill
    assert f"₹{statutory}" in skill
    assert "about 16 points" in skill
    assert points.quantize(Decimal("1"), rounding=ROUND_HALF_UP) == Decimal("16")
    assert "does not cover STT" in skill


@pytest.mark.unit
def test_charge_rates_are_not_defined_outside_the_shared_table() -> None:
    """Fail when a drifted copy of a statutory rate is reintroduced."""
    table = table_path().resolve()
    offenders: list[str] = []
    for path in _ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
            continue
        if path.name == "test_indian_charges.py":
            continue
        if path.resolve() == table or any(part in _SKIP_PARTS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in _FORBIDDEN:
            if token in text:
                offenders.append(f"{path.relative_to(_ROOT)} contains {token}")
    assert offenders == []
