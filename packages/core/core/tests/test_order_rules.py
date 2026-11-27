"""The shared order rules table and its evaluator."""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from flinttrade_core import order_rules as rules
from flinttrade_core.order_rules import (
    blocking,
    AUTHORITIES,
    CHECKS,
    LEVELS,
    SCOPE_BROKERS,
    SCOPE_EXCHANGES,
    SCOPE_INSTRUMENTS,
    SCOPE_ORDER_TYPES,
    OrderBudget,
    OrderRuleRefused,
    evaluate_order,
    headline,
    load_rules,
    market_price_cap,
    max_stop_limit_gap,
    price_band,
    results_payload,
    rules_markdown,
)

_FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "order_rules_cases.json").read_text(encoding="utf-8"))
CASES = _FIXTURE["cases"]
STOP_LOSS_LIMITS = _FIXTURE["stop_loss_limits"]
NIFTY_CE = "NIFTY25NOV2624000CE"
SENSEX_CE = "SENSEX27NOV2680000CE"
_TODAY = date(2026, 11, 20)
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_EVALUATOR_PLACEHOLDERS = {"max_gap", "low", "high", "limit", "window", "wait", "broker_name", "band", "qty"}


# ---------------------------------------------------------------------------
# Table shape
# ---------------------------------------------------------------------------


def test_every_rule_has_a_stable_id_effective_from_and_known_scope() -> None:
    rows = load_rules()
    ids = [row.id for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row.id), row.id
        assert isinstance(row.effective_from, date), row.id
        assert row.effective_to is None or row.effective_to >= row.effective_from
        assert row.level in LEVELS, row.id
        assert row.authority in AUTHORITIES, row.id
        assert row.check in CHECKS, row.id
        assert row.exchange in SCOPE_EXCHANGES, row.id
        assert row.broker in SCOPE_BROKERS, row.id
        assert row.instrument in SCOPE_INSTRUMENTS, row.id
        assert set(row.order_types) <= SCOPE_ORDER_TYPES, row.id
        assert row.source, row.id
        assert row.message.strip(), row.id
        assert row.description.strip() and row.description != row.message, row.id


def test_every_placeholder_can_be_filled() -> None:
    for row in load_rules():
        for name in _PLACEHOLDER.findall(row.message) + _PLACEHOLDER.findall(row.source):
            assert name in row.parameters or name in _EVALUATOR_PLACEHOLDERS, (row.id, name)


def test_raw_rows_carry_no_reference_or_verification_fields() -> None:
    payload = json.loads(rules.table_path().read_text(encoding="utf-8"))
    allowed = {
        "id",
        "authority",
        "level",
        "source",
        "description",
        "check",
        "scope",
        "effective_from",
        "effective_to",
        "parameters",
        "message",
        "family",
    }
    for raw in payload["rules"]:
        assert set(raw) <= allowed, raw["id"]
        text = json.dumps(raw)
        assert "circular" not in text.lower()
        assert not re.search(r"\b(?:NSE|BSE)/[A-Z]+/\d+", text)


def test_markdown_generator_lists_id_scope_date_and_message() -> None:
    table = rules_markdown()
    lines = table.strip().splitlines()
    assert lines[0] == "| Rule id | Level | Scope | Effective from | Description | Message |"
    assert set(line.split("|")[2].strip() for line in lines[2:]) <= {"Blocks", "Warns", "Info"}
    assert len(lines) == len(load_rules()) + 2
    assert (
        "| `bse-stop-limit-gap` | Blocks | BSE · all brokers · options · SL | 2026-02-09 | On BSE the stop-loss limit price"
        in table
    )
    # Parameters already known from the row are filled in; sources are not listed.
    assert "Intraday F&O positions are closed from 15:25. Exit before then." in table
    assert "Regulation" not in table


# ---------------------------------------------------------------------------
# Every rule: the day before and the day of its effective_from
# ---------------------------------------------------------------------------

# One order that the rule decides, for every per-order rule id.
_TRIGGERS: dict[str, tuple[dict, dict]] = {
    "options-stop-market-not-sent": (
        {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "SL-M", "trigger_price": "80"},
        {},
    ),
    "options-market-order-not-sent": ({"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "MARKET"}, {}),
    "algo-market-orders-fo-rejected": ({"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "MARKET"}, {}),
    "market-order-needs-trade-today": (
        {"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "MARKET"},
        {"traded_today": False},
    ),
    "bse-stop-limit-gap": (
        {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "SL", "trigger_price": "100", "price": "70"},
        {},
    ),
    "exit-position-closed": (
        {
            "symbol": NIFTY_CE,
            "exchange": "NFO",
            "action": "SELL",
            "pricetype": "LIMIT",
            "price": "40",
            "quantity": "75",
            "exit_only": True,
        },
        {"open_quantity": 0},
    ),
    "exit-quantity-capped": (
        {
            "symbol": NIFTY_CE,
            "exchange": "NFO",
            "action": "SELL",
            "pricetype": "LIMIT",
            "price": "40",
            "quantity": "150",
            "exit_only": True,
        },
        {"open_quantity": 75},
    ),
    "stop-loss-limit-at-trigger": (
        {"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "SL", "trigger_price": "100", "price": "100"},
        {},
    ),
    "bse-lpp-sensex-expiry-day": (
        {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "LIMIT", "price": "25"},
        {"last_price": "10", "expiry_day": True},
    ),
    "bse-limit-price-protection": (
        {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "LIMIT", "price": "200"},
        {"last_price": "100"},
    ),
    "nse-limit-price-protection-options": (
        {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "200"},
        {"last_price": "100"},
    ),
    "kotak-market-order-no-ltp": (
        {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "MARKET"},
        {"broker": "kotakneo", "broker_name": "Kotak Neo", "traded_today": False},
    ),
    "dhan-market-price-protection": (
        {"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "MARKET"},
        {"broker": "dhan", "broker_name": "Dhan"},
    ),
    "kotak-market-price-protection": (
        {"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "MARKET"},
        {"broker": "kotakneo", "broker_name": "Kotak Neo", "last_price": "1500"},
    ),
    "nse-options-operating-range": (
        {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "300"},
        {"circuit_low": "0.05", "circuit_high": "250"},
    ),
    "dhan-intraday-square-off": (
        {"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "LIMIT", "price": "24000", "product": "MIS"},
        {"broker": "dhan", "broker_name": "Dhan", "at_minutes": 15 * 60 + 22},
    ),
    "practice-market-price-cap": (
        {"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "MARKET"},
        {"broker": "practice", "broker_name": "Practice"},
    ),
    "practice-bracket-unsupported": (
        {"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "LIMIT", "price": "100", "stop_loss_price": "90"},
        {"broker": "practice", "broker_name": "Practice"},
    ),
    "broker-separate-stop-loss-target": (
        {"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "LIMIT", "price": "100", "stop_loss_price": "90"},
        {"broker": "kotakneo", "broker_name": "Kotak Neo"},
    ),
}


def _rule_ids(order: dict, context: dict, on: date) -> set[str]:
    return {result.rule_id for result in evaluate_order(order, on=on, **context)}


def test_every_per_order_rule_has_a_trigger_case() -> None:
    per_order = {row.id for row in load_rules() if row.check not in rules.NOT_PER_ORDER_CHECKS}
    assert per_order == set(_TRIGGERS)


@pytest.mark.parametrize("rule_id", sorted(_TRIGGERS))
def test_rule_applies_from_its_effective_date_and_not_the_day_before(rule_id: str) -> None:
    row = rules.rule_by_id(rule_id)
    order, context = _TRIGGERS[rule_id]
    assert rule_id not in _rule_ids(order, context, row.effective_from - timedelta(days=1))
    assert rule_id in _rule_ids(order, context, row.effective_from)


def test_order_rate_threshold_starts_on_its_effective_date() -> None:
    # evaluate() and OrderBudget skip this check; the row is listed as info.
    row = rules.rule_by_id("order-rate-threshold")
    assert not row.in_force(row.effective_from - timedelta(days=1))
    assert row.in_force(row.effective_from)
    assert row.parameters["max_per_second"] == 10
    assert row.level == "info"
    assert row.message == "Limit is {max_per_second} orders per second per exchange."


def test_live_acknowledgement_starts_on_its_effective_date() -> None:
    # The terminal's Live switch shows this row's message (see liveAcknowledgement.ts).
    row = rules.rule_by_id("self-built-algo-undertaking")
    assert not row.in_force(row.effective_from - timedelta(days=1))
    assert row.in_force(row.effective_from)
    assert row.level == "warn"
    assert "exchange grievance process" in row.message


@pytest.mark.parametrize("rule_id", ["dhan-order-rate-limits", "dhan-modifications-per-order"])
def test_dhan_budget_rows_start_on_their_effective_date(rule_id: str) -> None:
    row = rules.rule_by_id(rule_id)
    before, on = row.effective_from - timedelta(days=1), row.effective_from
    if rule_id == "dhan-order-rate-limits":
        budget = OrderBudget()
        assert all(budget.check_and_record("dhan", now=0.0, on=before) is None for _ in range(20))
        budget = OrderBudget()
        outcomes = [budget.check_and_record("dhan", now=0.0, on=on) for _ in range(11)]
        assert outcomes[:10] == [None] * 10
        assert outcomes[10] is not None and outcomes[10].rule_id == rule_id
    else:
        budget = OrderBudget()
        assert all(
            budget.check_and_record("dhan", now=float(i), on=before, modify_order_id="A") is None for i in range(30)
        )
        budget = OrderBudget()
        outcomes = [budget.check_and_record("dhan", now=float(i), on=on, modify_order_id="A") for i in range(26)]
        assert outcomes[:25] == [None] * 25
        assert outcomes[25] is not None and outcomes[25].rule_id == rule_id


def test_every_rule_is_covered_by_an_effective_date_test() -> None:
    covered = set(_TRIGGERS) | {
        "order-rate-threshold",
        "self-built-algo-undertaking",
        "dhan-order-rate-limits",
        "dhan-modifications-per-order",
    }
    assert covered == {row.id for row in load_rules()}


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "pricetype", "trigger", "limit", "warned"),
    [
        ("RELIANCE", "NSE", "SL", "100", "100", True),
        (SENSEX_CE, "BFO", "SL", "40", "40", True),
        ("RELIANCE", "NSE", "SL", "100", "99.95", False),
        ("RELIANCE", "NSE", "LIMIT", "", "100", False),
    ],
)
def test_stop_loss_limit_at_its_trigger_warns(symbol, exchange, pricetype, trigger, limit, warned) -> None:
    order = {"symbol": symbol, "exchange": exchange, "action": "SELL", "pricetype": pricetype, "price": limit}
    if trigger:
        order["trigger_price"] = trigger
    results = rules.evaluate_order(order, last_price=limit, on=_TODAY)
    hits = [r for r in results if r.rule_id == "stop-loss-limit-at-trigger"]
    assert bool(hits) is warned
    assert all(r.level == "warn" for r in hits)


@pytest.mark.parametrize(
    ("symbol", "exchange", "exit_action", "trigger", "limit", "on"),
    [
        # BSE option, trigger at or below ₹50: the ₹10 gap is tighter than the band.
        (SENSEX_CE, "BFO", "SELL", "50", "40.00", _TODAY),
        (SENSEX_CE, "BFO", "BUY", "30", "40.00", _TODAY),
        # Above ₹50: 20% of the trigger, rounded down to the tick.
        (SENSEX_CE, "BFO", "SELL", "50.05", "40.05", _TODAY),
        (SENSEX_CE, "BFO", "BUY", "250.35", "300.40", _TODAY),
        # NSE option: the price-protection band from the trigger (₹20 floor, then 40%).
        (NIFTY_CE, "NFO", "SELL", "30", "10.00", _TODAY),
        (NIFTY_CE, "NFO", "BUY", "30", "50.00", _TODAY),
        (NIFTY_CE, "NFO", "SELL", "250.35", "150.25", _TODAY),
        # No exchange gap or band: the table's default buffer.
        ("RELIANCE", "NSE", "SELL", "200", "190.00", _TODAY),
        ("RELIANCE", "NSE", "BUY", "33.33", "34.95", _TODAY),
        # SENSEX expiry day: the tighter expiry-day band floor.
        (SENSEX_CE, "BFO", "SELL", "40", "30.00", date(2026, 11, 27)),
        # A sell limit never drops below one tick.
        (NIFTY_CE, "NFO", "SELL", "0.10", "0.05", _TODAY),
    ],
)
def test_stop_loss_limit_price_uses_the_widest_buffer_the_table_allows(
    symbol, exchange, exit_action, trigger, limit, on
) -> None:
    got = rules.stop_loss_limit_price(symbol, exchange, exit_action, Decimal(trigger), on=on)
    assert got == Decimal(limit)
    order = {
        "symbol": symbol,
        "exchange": exchange,
        "action": exit_action,
        "pricetype": "SL",
        "trigger_price": trigger,
        "price": str(got),
    }
    assert rules.evaluate_order(order, last_price=trigger, on=on) == []
    # One tick wider leaves the rules.
    wider = got - Decimal("0.05") if exit_action == "SELL" else got + Decimal("0.05")
    if wider > 0 and exchange != "NSE":
        order["price"] = str(wider)
        assert rules.evaluate_order(order, last_price=trigger, on=on) != []


@pytest.mark.parametrize(
    ("trigger", "limit", "blocked", "gap"),
    [
        ("100", "80", False, "20"),
        ("100", "79.95", True, "20"),
        ("100", "120", False, "20"),
        ("100", "120.05", True, "20"),
        ("50", "40", False, "10"),
        ("50", "39.95", True, "10"),
        ("20", "10", False, "10"),
        ("20", "9.95", True, "10"),
        ("50.05", "40.04", False, "10.01"),
    ],
)
def test_bse_stop_limit_gap_edges(trigger: str, limit: str, blocked: bool, gap: str) -> None:
    order = {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "SL", "trigger_price": trigger, "price": limit}
    results = evaluate_order(order, on=date(2026, 11, 22))
    assert max_stop_limit_gap(Decimal(trigger), rules.rule_by_id("bse-stop-limit-gap").parameters) == Decimal(gap)
    if blocked:
        assert [r.rule_id for r in results] == ["bse-stop-limit-gap"]
        assert results[0].level == "block"
        assert results[0].message == f"Stop-loss limit must be within ₹{gap} of trigger."
        assert headline(results) == f"Exchange · Stop-loss limit must be within ₹{gap} of trigger."
    else:
        assert results == []


def test_stop_limit_gap_is_not_applied_on_nse() -> None:
    order = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "SL", "trigger_price": "50", "price": "20"}
    assert evaluate_order(order, on=date(2026, 11, 22)) == []


@pytest.mark.parametrize(
    ("reference", "floor", "low", "high"),
    [
        ("100", "20", "60.00", "140.00"),
        ("50", "20", "30.00", "70.00"),
        ("10", "20", "0.05", "30.00"),
        ("10", "10", "0.05", "20.00"),
        ("30", "10", "18.00", "42.00"),
    ],
)
def test_price_band_uses_the_larger_of_percent_and_floor(reference: str, floor: str, low: str, high: str) -> None:
    band = price_band(Decimal(reference), {"band_pct": 40, "min_band_inr": floor})
    assert band == (Decimal(low), Decimal(high))


def test_sensex_expiry_day_floor_is_ten_and_other_days_twenty() -> None:
    order = {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "LIMIT", "price": "25"}
    on = date(2026, 11, 22)
    expiry = evaluate_order(order, on=on, last_price="10", expiry_day=True)
    normal = evaluate_order(order, on=on, last_price="10", expiry_day=False)
    assert [r.rule_id for r in expiry] == ["bse-lpp-sensex-expiry-day"]
    assert expiry[0].message == "Price may be outside the exchange band (₹0.05–₹20)."
    assert normal == []


def test_sensex_expiry_day_is_inferred_from_the_contract() -> None:
    order = {"symbol": SENSEX_CE, "exchange": "BFO", "pricetype": "LIMIT", "price": "25"}
    assert [r.rule_id for r in evaluate_order(order, on=date(2026, 11, 27), last_price="10")] == [
        "bse-lpp-sensex-expiry-day"
    ]


def test_price_band_never_changes_the_price_and_only_warns() -> None:
    order = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "500"}
    results = evaluate_order(order, on=date(2026, 11, 22), last_price="100")
    assert [r.level for r in results] == ["warn"]
    assert order["price"] == "500"
    assert blocking(results) == []


def test_results_are_ordered_block_warn_info_then_authority() -> None:
    order = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "MARKET"}
    results = evaluate_order(
        order, on=date(2026, 11, 22), broker="kotakneo", broker_name="Kotak Neo", traded_today=False
    )
    # The two no-trade-today rows share one sentence, so only the exchange's fires.
    assert [r.level for r in results] == ["block", "block"]
    assert [r.source for r in results] == ["Exchange", "FlintTrade"]
    assert results[0].message == "This contract hasn't traded today. Use a limit price."


def test_refusal_carries_every_result() -> None:
    with pytest.raises(OrderRuleRefused) as excinfo:
        raise OrderRuleRefused(
            evaluate_order({"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "MARKET"}, on=date(2026, 11, 22))
        )
    assert str(excinfo.value) == "FlintTrade · Market orders aren't accepted on options. Use a limit price."
    assert excinfo.value.results[0].rule_id == "options-market-order-not-sent"


def test_equity_and_futures_limit_orders_pass() -> None:
    on = date(2026, 11, 22)
    assert evaluate_order({"symbol": "RELIANCE", "exchange": "NSE", "pricetype": "LIMIT", "price": "1"}, on=on) == []
    assert (
        evaluate_order({"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "LIMIT", "price": "1"}, on=on) == []
    )


def test_exact_circuit_warns_and_does_not_refuse() -> None:
    order = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "300"}
    on = date(2026, 11, 22)
    exact = evaluate_order(order, on=on, last_price="100", circuit_low="0.05", circuit_high="250")
    assert [(r.level, r.rule_id) for r in exact] == [
        ("warn", "nse-options-operating-range"),
        ("warn", "nse-limit-price-protection-options"),
    ]
    assert exact[0].message == "Price may be outside the exchange band (₹0.05–₹250)."
    assert blocking(exact) == []
    estimated = evaluate_order(order, on=on, last_price="100")
    assert [r.level for r in estimated] == ["warn"]


def test_raw_future_market_blocks_only_where_the_broker_does_not_convert() -> None:
    order = {"symbol": "NIFTY25NOVFUT", "exchange": "NFO", "pricetype": "MARKET"}
    on = date(2026, 11, 22)
    raw = evaluate_order(order, on=on, broker="upstox", broker_name="Upstox")
    assert [(r.level, r.rule_id) for r in raw] == [("block", "algo-market-orders-fo-rejected")]
    converted = evaluate_order(order, on=on, broker="kotakneo", broker_name="Kotak Neo", last_price="24000")
    assert [(r.level, r.rule_id, r.message) for r in converted] == [
        (
            "warn",
            "kotak-market-price-protection",
            "Market orders are sent as limits within 0.5% of the last price and may not fill.",
        ),
    ]


@pytest.mark.parametrize(
    ("price", "band"),
    [("0.5", "₹0.10"), ("4", "10%"), ("8", "5%"), ("50", "3%"), ("200", "2%"), ("800", "1%")],
)
def test_kotak_option_market_band_tiers(price: str, band: str) -> None:
    params = rules.rule_by_id("kotak-market-price-protection").parameters
    assert rules.market_band_label(Decimal(price), params, option=True) == band


def test_market_price_cap_moves_against_the_order() -> None:
    assert market_price_cap(Decimal("100"), "BUY") == Decimal("103.00")
    assert market_price_cap(Decimal("100"), "SELL") == Decimal("97.00")


def test_order_budget_windows_and_wait_message() -> None:
    budget = OrderBudget()
    on = date(2026, 11, 22)
    for second in range(25):
        for _ in range(10):
            assert budget.check_and_record("dhan", now=float(second), on=on) is None
    # 250 orders inside one minute: the next one waits for the minute window.
    refused = budget.check_and_record("dhan", now=25.0, on=on)
    assert refused is not None
    assert refused.message == "Not placed. Limit is 250 orders per minute. Retry in 35 seconds."
    assert refused.source == "Dhan"
    # Other brokers have no published budget rows.
    assert budget.check_and_record("upstox", now=25.0, on=on) is None


def test_order_budget_counts_cancels_without_refusing_them() -> None:
    budget = OrderBudget()
    on = date(2026, 11, 22)
    for _ in range(10):
        budget.record("dhan", now=0.0, on=on)
    refused = budget.check_and_record("dhan", now=0.5, on=on)
    assert refused is not None and refused.message == "Not placed. Limit is 10 orders per second. Retry in 1 second."


def test_intraday_square_off_follows_the_broker_profile() -> None:
    order = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "100", "product": "MIS"}
    on = date(2026, 11, 22)
    dhan = [r.rule_id for r in evaluate_order(order, on=on, broker="dhan", at_minutes=15 * 60 + 20)]
    kotak = [r.rule_id for r in evaluate_order(order, on=on, broker="kotakneo", at_minutes=15 * 60 + 20)]
    assert "dhan-intraday-square-off" in dhan
    assert "dhan-intraday-square-off" not in kotak


def test_wait_is_worded_for_its_window() -> None:
    from flinttrade_core.order_rules import _wait_label

    assert [_wait_label(n) for n in (1, 40, 61, 3600, 7201)] == [
        "1 second",
        "40 seconds",
        "2 minutes",
        "1 hour",
        "3 hours",
    ]


# ---------------------------------------------------------------------------
# Shared cases: the same order gives the same result everywhere
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
def test_shared_cases_match_the_evaluator(case: dict) -> None:
    results = evaluate_order(case["order"], on=date.fromisoformat(case["on"]), **case["context"])
    assert results_payload(results) == case["expected"]


@pytest.mark.parametrize("case", STOP_LOSS_LIMITS)
def test_shared_stop_loss_limits_match(case: dict) -> None:
    got = rules.stop_loss_limit_price(
        case["symbol"],
        case["exchange"],
        case["exit_action"],
        Decimal(case["trigger"]),
        on=date.fromisoformat(case["on"]),
    )
    assert str(got) == case["limit"]


_EXIT = {"symbol": NIFTY_CE, "exchange": "NFO", "pricetype": "LIMIT", "price": "40", "exit_only": True}


@pytest.mark.parametrize(
    ("action", "quantity", "net", "sent", "rule_id"),
    [
        ("SELL", 75, 150, 75, None),
        ("SELL", 150, 150, 150, None),
        ("SELL", 225, 150, 150, "exit-quantity-capped"),
        ("BUY", 225, -150, 150, "exit-quantity-capped"),
        ("SELL", 75, 0, 0, "exit-position-closed"),
        ("SELL", 75, -150, 0, "exit-position-closed"),
        ("BUY", 75, 150, 0, "exit-position-closed"),
    ],
)
def test_exit_ticket_never_opens_a_position(action, quantity, net, sent, rule_id) -> None:
    got, results = rules.exit_admission({**_EXIT, "action": action, "quantity": str(quantity)}, net)
    assert got == sent
    assert [r.rule_id for r in results] == ([rule_id] if rule_id else [])


def test_exit_ticket_copy() -> None:
    _, capped = rules.exit_admission({**_EXIT, "action": "SELL", "quantity": "225"}, 150)
    _, closed = rules.exit_admission({**_EXIT, "action": "SELL", "quantity": "75"}, 0)
    assert (capped[0].level, capped[0].message) == ("warn", "Quantity reduced to 150, the open position.")
    assert (closed[0].level, closed[0].message) == ("block", "Position is closed. Order not sent.")


def test_exit_rules_ignore_ordinary_orders() -> None:
    order = {**_EXIT, "action": "SELL", "quantity": "225", "exit_only": False}
    assert rules.evaluate_order(order, open_quantity=0, last_price="40") == []
    assert rules.evaluate_order({**_EXIT, "action": "SELL", "quantity": "225"}, last_price="40") == []


def test_a_name_ending_in_ce_is_not_an_option() -> None:
    from flinttrade_core.order_rules import instrument_kind

    assert instrument_kind("RELIANCE", "MCX") == "future"
    assert instrument_kind("RELIANCE", "NSE") == "equity"
    assert instrument_kind("NIFTY-Nov2026-24000-CE", "NFO") == "option"
    assert evaluate_order({"symbol": "RELIANCE", "exchange": "MCX", "pricetype": "MARKET"}, broker="kotakneo") == []


@pytest.mark.parametrize("broker,broker_name", [("practice", "Practice"), ("dhan", "Dhan")])
def test_an_option_exit_limit_at_the_cap_is_not_refused(broker: str, broker_name: str) -> None:
    last = Decimal("150")
    price = market_price_cap(last, "SELL")
    assert price == Decimal("145.50")
    results = evaluate_order(
        {
            "symbol": NIFTY_CE,
            "exchange": "NFO",
            "action": "SELL",
            "pricetype": "LIMIT",
            "price": str(price),
            "quantity": "75",
            "exit_only": True,
        },
        on=date(2026, 11, 22),
        broker=broker,
        broker_name=broker_name,
        last_price=last,
        open_quantity=75,
    )
    assert blocking(results) == []
    assert all(result.rule_id != "options-market-order-not-sent" for result in results)


def test_option_square_off_cap_includes_the_last_price() -> None:
    """Square off and Exit all price the limit from last, so last never sits outside it."""

    def option_exit_limit(last: Decimal, action: str) -> Decimal:
        cap = market_price_cap(last, action)
        ticks = max(1, round(float(cap) * 20 + 1e-7))
        return Decimal(str(ticks / 20))

    last = Decimal("0.05")
    while last <= Decimal("200.00"):
        sell = option_exit_limit(last, "SELL")
        buy = option_exit_limit(last, "BUY")
        assert sell <= last, (last, sell)
        assert buy >= last, (last, buy)
        last += Decimal("0.05")


def test_docs_page_carries_the_current_rules_table() -> None:
    from pathlib import Path

    page = Path(__file__).resolve().parents[4] / "docs" / "BROKER_AND_EXCHANGE_RULES.md"
    assert rules_markdown() in page.read_text(encoding="utf-8")

@pytest.mark.parametrize("broker", ["practice", "dhan"])
def test_an_option_market_refusal_hides_fill_info_rows(broker: str) -> None:
    results = evaluate_order(
        {"symbol": "NIFTY25NOV2624000CE", "exchange": "NFO", "pricetype": "MARKET"},
        on=date(2026, 11, 22),
        broker=broker,
        broker_name="Practice" if broker == "practice" else "Dhan",
        last_price="150",
    )
    ids = [result.rule_id for result in results]
    assert "options-market-order-not-sent" in ids
    assert "practice-market-price-cap" not in ids
    assert "dhan-market-price-protection" not in ids

