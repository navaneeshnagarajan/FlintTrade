"""Shared Indian statutory charges.

One table, loaded from ``data/indian_charges.json``, feeds the backtest
calculator, Practice fills, the terminal charges calculator and mirror cost
metadata. Every rate has an exchange and an effective-from date.

The table corrects three drifted copies:

* The backtest calculator applied the futures STT rate to options, one F&O
  exchange percentage to every contract, and the futures stamp rate to options.
* The terminal calculator applied the cash exchange percentage to F&O, the
  options stamp rate to futures, and futures STT on both sides of a round trip.
* Mirror defaults used the NSE transaction line without the investor-protection
  total, and carried no BSE schedule. BSE futures are nil. Sensex options and
  Bankex options have their own premium rate.

Brokerage is not a statutory rate and is not in the table. Lot sizes are not
in the table either; callers read them from the instrument master.

All money uses :class:`~decimal.Decimal`. Each component is rounded to the
paisa with half-up rounding before GST is applied to the rounded brokerage,
exchange charge and SEBI fee.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from flinttrade_core.symbol_utils import parse_future_symbol, parse_option_symbol

_TWO = Decimal("0.01")
_TABLE_PATH = Path(__file__).parent / "data" / "indian_charges.json"

_CASH_EXCHANGES = {"NSE", "BSE", "NSE_EQ", "NSE_CM", "BSE_EQ"}
_NSE_DERIVATIVES = {"NFO", "NSE_FO", "NSE_FNO"}
_BSE_DERIVATIVES = {"BFO", "BSE_FO", "BSE_FNO"}


@dataclass(frozen=True)
class ChargeRate:
    """One effective-dated statutory rate."""

    exchange: str
    segment: str
    component: str
    side: str
    basis: str
    rate: Decimal
    per_contract_inr: Decimal
    effective_from: date
    effective_to: date | None
    citation: str


@dataclass(frozen=True)
class ChargeBreakdown:
    """Paisa-rounded charges for one fill. Brokerage is zero unless supplied."""

    stt: Decimal
    exchange_charges: Decimal
    exchange_label: str
    sebi_fee: Decimal
    stamp_duty: Decimal
    gst: Decimal
    brokerage: Decimal
    total: Decimal

    def as_floats(self) -> dict[str, float | str]:
        """JSON-friendly view used by Practice fills."""
        return {
            "stt": float(self.stt),
            "exchange_charges": float(self.exchange_charges),
            "exchange_label": self.exchange_label,
            "sebi_fee": float(self.sebi_fee),
            "stamp_duty": float(self.stamp_duty),
            "gst": float(self.gst),
            "brokerage": float(self.brokerage),
            "total": float(self.total),
        }


def exchange_transaction_label(exchange: str) -> str:
    """Name the exchange on a charges breakdown line."""
    key = exchange.strip().upper()
    if key in {"BSE", "BFO", "BSE_FO", "BSE_FNO", "BSE_EQ"}:
        return "BSE transaction"
    if key == "MCX":
        return "MCX transaction"
    return "NSE transaction"


@lru_cache(maxsize=1)
def load_rates() -> tuple[ChargeRate, ...]:
    """Return every row of the shared table."""
    payload = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    rows: list[ChargeRate] = []
    for raw in payload["rates"]:
        effective_to = raw.get("effective_to")
        rows.append(
            ChargeRate(
                exchange=str(raw["exchange"]),
                segment=str(raw["segment"]),
                component=str(raw["component"]),
                side=str(raw["side"]),
                basis=str(raw["basis"]),
                rate=Decimal(str(raw["rate"])),
                per_contract_inr=Decimal(str(raw["per_contract_inr"])),
                effective_from=date.fromisoformat(str(raw["effective_from"])),
                effective_to=date.fromisoformat(effective_to) if effective_to else None,
                citation=str(raw["citation"]),
            )
        )
    return tuple(rows)


def table_path() -> Path:
    """Absolute path of the shared JSON table."""
    return _TABLE_PATH


def lookup_rate(
    exchange: str,
    segment: str,
    component: str,
    side: str,
    on: date,
) -> ChargeRate | None:
    """Return the rate in force on ``on``.

    An exact exchange and segment beat an ``ANY`` / ``any`` row. A date before
    the first matching row uses that earliest row, so a backtest dated before
    the flat exchange schedule still applies the first uniform rate rather
    than zero.
    """
    wanted_exchange = exchange.strip().upper()
    wanted_segment = segment.strip().lower()
    wanted_component = component.strip().lower()
    wanted_side = side.strip().lower()
    pool = [
        row
        for row in load_rates()
        if row.component == wanted_component
        and row.exchange in {wanted_exchange, "ANY"}
        and row.segment in {wanted_segment, "any"}
        and row.side in {wanted_side, "both"}
    ]
    if not pool:
        return None

    def rank(row: ChargeRate) -> tuple[date, int, int, int]:
        return (
            row.effective_from,
            1 if row.exchange == wanted_exchange else 0,
            1 if row.segment == wanted_segment else 0,
            1 if row.side == wanted_side else 0,
        )

    in_force = [
        row
        for row in pool
        if row.effective_from <= on and (row.effective_to is None or on <= row.effective_to)
    ]
    if in_force:
        return max(in_force, key=rank)
    earliest = min(row.effective_from for row in pool)
    if on < earliest:
        return min((row for row in pool if row.effective_from == earliest), key=rank)
    return None


def rate_fraction(
    exchange: str,
    segment: str,
    component: str,
    side: str,
    on: date | None = None,
) -> Decimal:
    """Return the fractional rate, or zero when the table has no row."""
    row = lookup_rate(exchange, segment, component, side, on or date.today())
    return row.rate if row is not None else Decimal(0)


def _money(value: Decimal) -> Decimal:
    return value.quantize(_TWO, rounding=ROUND_HALF_UP)


def _component_amount(
    exchange: str,
    segment: str,
    component: str,
    side: str,
    on: date,
    trade_value: Decimal,
    contracts: int,
) -> Decimal:
    row = lookup_rate(exchange, segment, component, side, on)
    if row is None or row.basis == "gst_base":
        return Decimal(0)
    variable = trade_value * row.rate
    flat = row.per_contract_inr * Decimal(contracts)
    return _money(variable + flat)


def calculate_leg(
    *,
    exchange: str,
    segment: str,
    trade_value: Decimal,
    is_buy: bool,
    on: date | None = None,
    brokerage: Decimal = Decimal(0),
    contracts: int = 0,
) -> ChargeBreakdown:
    """Calculate one fill's estimated statutory charges.

    ``brokerage`` is included only when the caller has a configured broker
    rate. Practice passes zero and does not label the result as brokerage.
    """
    traded_on = on or date.today()
    side = "buy" if is_buy else "sell"
    value = Decimal(trade_value)
    broker = _money(Decimal(brokerage))
    stt = _component_amount(exchange, segment, "stt", side, traded_on, value, contracts)
    stamp = _component_amount(exchange, segment, "stamp_duty", side, traded_on, value, contracts)
    exchange_charges = _component_amount(
        exchange, segment, "exchange_transaction", side, traded_on, value, contracts
    )
    sebi = _component_amount(exchange, segment, "sebi", side, traded_on, value, contracts)
    gst_row = lookup_rate("ANY", "any", "gst", side, traded_on)
    gst_rate = gst_row.rate if gst_row is not None else Decimal(0)
    gst = _money((broker + exchange_charges + sebi) * gst_rate)
    total = _money(broker + stt + stamp + exchange_charges + sebi + gst)
    return ChargeBreakdown(
        stt=stt,
        exchange_charges=exchange_charges,
        exchange_label=exchange_transaction_label(exchange),
        sebi_fee=sebi,
        stamp_duty=stamp,
        gst=gst,
        brokerage=broker,
        total=total,
    )


def option_exercise_stt(
    *,
    segment: str,
    settlement_value: Decimal,
    on: date | None = None,
    exchange: str = "ANY",
) -> Decimal:
    """STT the buyer pays when an option is exercised.

    This is not charged on an ordinary buy or sell of premium. The basis is
    the settlement value, and the rate in force from 1 April 2026 is 0.15%.
    """
    traded_on = on or date.today()
    return _component_amount(
        exchange,
        segment,
        "stt",
        "exercise",
        traded_on,
        Decimal(settlement_value),
        0,
    )


def break_even_points(
    *,
    statutory_round_trip: Decimal,
    spread: Decimal,
    brokerage: Decimal,
    lot_size: int,
) -> Decimal:
    """Points needed to cover statutory charges, the spread and brokerage.

    ``lot_size`` is the contract multiplier from the instrument master.
    The result is rupees of cost divided by that multiplier.
    """
    if lot_size <= 0:
        raise ValueError("lot size must be a positive contract multiplier from the instrument master")
    cost = Decimal(statutory_round_trip) + Decimal(spread) + Decimal(brokerage)
    return cost / Decimal(lot_size)


def round_trip(
    *,
    exchange: str,
    segment: str,
    buy_value: Decimal,
    sell_value: Decimal,
    on: date | None = None,
    brokerage_per_leg: Decimal = Decimal(0),
    contracts: int = 0,
) -> tuple[ChargeBreakdown, ChargeBreakdown]:
    """Charges for a buy leg and the matching sell leg."""
    buy = calculate_leg(
        exchange=exchange,
        segment=segment,
        trade_value=buy_value,
        is_buy=True,
        on=on,
        brokerage=brokerage_per_leg,
        contracts=contracts,
    )
    sell = calculate_leg(
        exchange=exchange,
        segment=segment,
        trade_value=sell_value,
        is_buy=False,
        on=on,
        brokerage=brokerage_per_leg,
        contracts=contracts,
    )
    return buy, sell


def estimate_practice_fill(
    *,
    symbol: str,
    exchange: str,
    product: str,
    action: str,
    quantity: int,
    price: Decimal | float | str,
    on: date | None = None,
) -> ChargeBreakdown:
    """Estimated statutory charges for one Practice fill.

    Lot size is not an input. Turnover is price times quantity, which the
    caller already took from the instrument master or the order.
    """
    rate_exchange, segment = classify_fill(symbol, exchange, product)
    return calculate_leg(
        exchange=rate_exchange,
        segment=segment,
        trade_value=Decimal(str(price)) * Decimal(int(quantity)),
        is_buy=action.strip().upper() != "SELL",
        on=on,
        brokerage=Decimal(0),
    )


def classify_fill(symbol: str, exchange: str, product: str = "MIS") -> tuple[str, str]:
    """Map a broker symbol to ``(rate exchange, segment)``.

    Lot size is not decided here. Sensex options and Bankex options are their
    own segments because BSE charges them apart from stock options, and BSE
    futures are a nil segment of their own.
    """
    sym = symbol.strip().upper()
    exch = exchange.strip().upper()
    prod = product.strip().upper() or "MIS"
    if exch in _NSE_DERIVATIVES or exch == "NSE":
        rate_exchange = "NSE"
    elif exch in _BSE_DERIVATIVES or exch == "BSE":
        rate_exchange = "BSE"
    elif exch == "MCX":
        rate_exchange = "MCX"
    elif exch.startswith("NSE"):
        rate_exchange = "NSE"
    elif exch.startswith("BSE"):
        rate_exchange = "BSE"
    else:
        rate_exchange = "NSE"

    option = parse_option_symbol(sym)
    future = parse_future_symbol(sym)
    derivative_venue = exch in _NSE_DERIVATIVES | _BSE_DERIVATIVES | {"MCX", "CDS"}
    # Trust the symbol parser. A cash name such as RELIANCE ends in "CE"
    # and must not be treated as an option.
    if option is not None:
        underlying = option.underlying if option is not None else sym
        if rate_exchange == "MCX" or exch == "MCX":
            return "MCX", "commodity_options"
        if rate_exchange == "BSE":
            if underlying == "SENSEX":
                return "BSE", "sensex_options"
            if underlying == "BANKEX":
                return "BSE", "bankex_options"
            if underlying in {"SENSEX50", "SNSX50"}:
                return "BSE", "sensex50_options"
        return rate_exchange, "equity_options"
    if future is not None or sym.endswith("FUT") or (derivative_venue and exch == "MCX"):
        if rate_exchange == "MCX" or exch == "MCX":
            return "MCX", "commodity_futures"
        return rate_exchange, "equity_futures"
    if derivative_venue:
        return rate_exchange, "equity_futures"
    if prod == "MIS":
        return rate_exchange, "equity_intraday"
    return rate_exchange, "equity_delivery"


def statutory_mirror_defaults(on: date | None = None) -> dict[str, float]:
    """Statutory mirror fields generated from the shared table."""
    traded_on = on or date.today()

    def frac(exchange: str, segment: str, component: str, side: str) -> float:
        return float(rate_fraction(exchange, segment, component, side, traded_on))

    sebi = rate_fraction("ANY", "any", "sebi", "buy", traded_on)
    return {
        "stt_futures_sell": frac("NSE", "equity_futures", "stt", "sell"),
        "stt_options_sell": frac("NSE", "equity_options", "stt", "sell"),
        "exchange_charge_futures": frac("NSE", "equity_futures", "exchange_transaction", "buy"),
        "exchange_charge_options": frac("NSE", "equity_options", "exchange_transaction", "buy"),
        "exchange_charge_futures_bse": frac("BSE", "equity_futures", "exchange_transaction", "buy"),
        "exchange_charge_sensex_options": frac("BSE", "sensex_options", "exchange_transaction", "buy"),
        "exchange_charge_bse_stock_options": frac("BSE", "equity_options", "exchange_transaction", "buy"),
        "gst_rate": frac("ANY", "any", "gst", "buy"),
        "sebi_charge_per_crore": float(sebi * Decimal(10_000_000)),
        "stamp_duty_buy_futures": frac("ANY", "equity_futures", "stamp_duty", "buy"),
        "stamp_duty_buy_options": frac("ANY", "equity_options", "stamp_duty", "buy"),
    }


def derivative_stt_schedule() -> list[dict[str, str | float | None]]:
    """Options and futures sell-side STT windows, for the tax report."""
    futures = [row for row in load_rates() if row.segment == "equity_futures" and row.component == "stt"]
    options = {
        (row.effective_from, row.effective_to): row
        for row in load_rates()
        if row.segment == "equity_options" and row.component == "stt"
    }
    schedule: list[dict[str, str | float | None]] = []
    for row in sorted(futures, key=lambda item: item.effective_from):
        match = options.get((row.effective_from, row.effective_to))
        schedule.append(
            {
                "effective_from": row.effective_from.isoformat(),
                "effective_to": row.effective_to.isoformat() if row.effective_to else None,
                "options_sell_rate": float(match.rate) if match is not None else None,
                "futures_sell_rate": float(row.rate),
            }
        )
    return schedule


def stt_rate_for_segment(segment: str, action: str, on: date, exchange: str = "NSE") -> Decimal:
    """STT fraction for a tax-report segment name."""
    side = "sell" if action.strip().upper() == "SELL" else "buy"
    mapping = {
        "equity_delivery": ("ANY", "equity_delivery"),
        "equity_intraday": ("ANY", "equity_intraday"),
        "futures": (exchange if exchange in {"NSE", "BSE"} else "NSE", "equity_futures"),
        "options": (exchange if exchange in {"NSE", "BSE"} else "NSE", "equity_options"),
        "commodity": ("MCX", "commodity_futures"),
    }
    resolved = mapping.get(segment.lower())
    if resolved is None:
        return Decimal(0)
    rate_exchange, rate_segment = resolved
    if segment.lower() == "options" and exchange == "BSE":
        rate_segment = "sensex_options"
    return rate_fraction(rate_exchange, rate_segment, "stt", side, on)
