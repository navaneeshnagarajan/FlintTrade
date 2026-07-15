"""Broker-neutral portfolio safety-state calculations."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from flinttrade_core.l2_state import (
    PortfolioSafetyStateError,
    _AccountingSnapshot,
    _AccountSource,
    _canonical_option_type,
    _fingerprint_rows,
    _greek_contributions,
    _portfolio_greeks,
    _project_unresolved_reservations,
    compute_local_daily_pnl,
    gather_safety_state,
)


def test_option_type_falls_back_to_contract_symbol_for_broker_instrument_family() -> None:
    assert _canonical_option_type({
        "symbol": "NIFTY30JUL2625000CE",
        "exchange": "NFO",
        "instrument_type": "OPTIDX",
    }) == "CE"


def test_order_snapshot_fingerprint_includes_advanced_exposure_markers() -> None:
    base = {
        "orderid": "A-1:0",
        "status": "PENDING",
        "symbol": "TCS",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "quantity": "1",
    }

    regular = _fingerprint_rows([base], "order")
    conditional = _fingerprint_rows([
        {
            **base,
            "safety_order_id": "conditional:A-1:0",
            "raw_broker_order_id": "A-1",
            "order_family": "conditional",
            "leg_name": "CONDITIONAL_LEG_0",
            "parent_order_id": "A-1",
            "margin_unfunded": True,
        }
    ], "order")

    assert regular != conditional


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("option_type", "PE"),
        ("expiry", "2026-08-27"),
        ("strike_price", "25100"),
        ("underlying", "BANKNIFTY"),
    ],
)
def test_position_snapshot_fingerprint_includes_option_contract_identity(field: str, changed: str) -> None:
    base = {
        "symbol": "NIFTY30JUL2625000CE",
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "75",
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": "25000",
        "underlying": "NIFTY",
    }

    assert _fingerprint_rows([base], "position") != _fingerprint_rows([{**base, field: changed}], "position")


@pytest.mark.asyncio
async def test_native_option_greeks_require_an_adapter_resolved_instrument_id() -> None:
    symbol = "NIFTY30JUL2625000CE"
    adapter = SimpleNamespace(
        portfolio_greeks=AsyncMock(return_value=[{
            "symbol": symbol,
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 6.4,
        }])
    )

    with pytest.raises(PortfolioSafetyStateError, match="resolved instrument identity"):
        await _portfolio_greeks(
            _AccountSource(target=adapter, session=object()),
            [],
            [{
                "symbol": symbol,
                "exchange": "NFO",
                "quantity": 75,
                "action": "BUY",
                "option_type": "CE",
            }],
        )


@pytest.mark.asyncio
async def test_native_option_greeks_reject_one_resolved_id_for_two_contracts() -> None:
    orders = [
        {
            "symbol": "NIFTY30JUL2625000CE",
            "exchange": "NFO",
            "quantity": 50,
            "action": "BUY",
            "option_type": "CE",
        },
        {
            "symbol": "NIFTY30JUL2625100CE",
            "exchange": "NFO",
            "quantity": 50,
            "action": "BUY",
            "option_type": "CE",
        },
    ]

    async def duplicate_resolved_id(
        _session: object,
        positions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return [
            {
                "symbol": position["symbol"],
                "instrument_id": "NSE_FO|54452",
                "exchange": position["exchange"],
                "delta": 0.6,
                "vega": 10.0,
            }
            for position in positions
        ]

    adapter = SimpleNamespace(portfolio_greeks=AsyncMock(side_effect=duplicate_resolved_id))

    with pytest.raises(PortfolioSafetyStateError, match="unique resolved instrument identity"):
        await _greek_contributions(
            _AccountSource(target=adapter, session=object()),
            [],
            orders,
        )


def test_local_daily_pnl_uses_signed_trade_cash_flow_not_broker_pnl() -> None:
    positions = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": "15",
            "pnl": "99999999",
        },
    ]
    trades = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": "5",
            "price": "110",
        },
    ]
    quotes = [
        {
            "symbol": "RELIANCE",
                "exchange": "NSE",
                "ltp": 105,
                "prev_close": 100,
                "previous_close_trusted": True,
        },
    ]

    # Opening quantity = 15 - 5 = 10. Daily MTM is therefore
    # 15*105 - 10*100 - 5*110 = 25, irrespective of broker ``pnl``.
    assert compute_local_daily_pnl(trades, positions, quotes) == pytest.approx(25.0)


def test_local_daily_pnl_computes_closed_intraday_loss_without_quotes() -> None:
    trades = [
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 10,
            "price": 100,
        },
        {
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 10,
            "price": 90,
        },
    ]

    assert compute_local_daily_pnl(trades, [], []) == pytest.approx(-100.0)


def test_local_daily_pnl_rejects_ambiguous_current_close_as_previous_close() -> None:
    holdings = [
        {"symbol": "TCS", "exchange": "NSE", "product": "CNC", "quantity": 2},
    ]
    quotes = [
        {"symbol": "TCS", "exchange": "NSE", "ltp": 95, "prev_close": 0, "close": 100},
    ]

    with pytest.raises(PortfolioSafetyStateError, match="previous close"):
        compute_local_daily_pnl([], [], quotes, holdings)


def test_local_daily_pnl_rejects_untrusted_quote_previous_close() -> None:
    positions = [{"symbol": "TCS", "exchange": "NSE", "product": "MIS", "quantity": 1}]
    quotes = [{"symbol": "TCS", "exchange": "NSE", "ltp": 95, "prev_close": 100}]

    with pytest.raises(PortfolioSafetyStateError, match="previous close"):
        compute_local_daily_pnl([], positions, quotes)


@pytest.mark.parametrize(
    ("positions", "trades", "quotes", "expected"),
    [
        (
            [
                {
                    "symbol": "NIFTY",
                    "exchange": "NFO",
                    "product": "NRML",
                        "quantity": -10,
                        "multiplier": 1,
                        "cross_currency": False,
                }
            ],
            [],
            [{
                "symbol": "NIFTY",
                "exchange": "NFO",
                "ltp": 90,
                "prev_close": 100,
                "previous_close_trusted": True,
            }],
            100.0,
        ),
        (
            [
                {
                    "symbol": "NIFTY",
                    "exchange": "NFO",
                    "product": "NRML",
                        "quantity": -6,
                        "multiplier": 1,
                        "cross_currency": False,
                }
            ],
            [
                {
                    "symbol": "NIFTY",
                    "exchange": "NFO",
                    "product": "NRML",
                    "action": "BUY",
                    "quantity": 4,
                    "price": 95,
                },
            ],
            [{
                "symbol": "NIFTY",
                "exchange": "NFO",
                "ltp": 90,
                "prev_close": 100,
                "previous_close_trusted": True,
            }],
            80.0,
        ),
        (
            [{"symbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": -5}],
            [
                {
                    "symbol": "SBIN",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "SELL",
                    "quantity": 5,
                    "price": 100,
                },
            ],
            [{
                "symbol": "SBIN",
                "exchange": "NSE",
                "ltp": 90,
                "prev_close": 80,
                "previous_close_trusted": True,
            }],
            50.0,
        ),
    ],
)
def test_local_daily_pnl_handles_short_and_partial_cover_ledgers(
    positions: list[dict[str, object]],
    trades: list[dict[str, object]],
    quotes: list[dict[str, object]],
    expected: float,
) -> None:
    assert compute_local_daily_pnl(trades, positions, quotes) == pytest.approx(expected)


def test_local_daily_pnl_keeps_products_separate_while_reusing_market_quote() -> None:
    positions = [
        {"symbol": "TCS", "exchange": "NSE", "product": "MIS", "quantity": 2},
    ]
    holdings = [{"symbol": "TCS", "exchange": "NSE", "product": "CNC", "quantity": 3}]
    trades = [
        {
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 2,
            "price": 100,
        },
    ]
    quotes = [{
        "symbol": "TCS",
        "exchange": "NSE",
        "ltp": 110,
        "prev_close": 90,
        "previous_close_trusted": True,
    }]

    assert compute_local_daily_pnl(trades, positions, quotes, holdings) == pytest.approx(80.0)


@pytest.mark.parametrize(
    ("positions", "trades", "quotes", "match"),
    [
        (
            [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": 1}],
            [],
            [],
            "quote",
        ),
        (
            [],
            [
                {
                    "symbol": "INFY",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "SIDEWAYS",
                    "quantity": 1,
                    "price": 100,
                },
            ],
            [],
            "action",
        ),
    ],
)
def test_local_daily_pnl_refuses_incomplete_accounting(
    positions: list[dict[str, object]],
    trades: list[dict[str, object]],
    quotes: list[dict[str, object]],
    match: str,
) -> None:
    with pytest.raises(PortfolioSafetyStateError, match=match):
        compute_local_daily_pnl(trades, positions, quotes)


@pytest.mark.asyncio
async def test_gather_safety_state_reads_exact_native_selector_and_recomputes_pnl() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    adapter = SimpleNamespace(
        positions=AsyncMock(
            return_value=[
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "product": "MIS",
                    "quantity": "5",
                    "pnl": "-500000",
                },
            ],
        ),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(
            return_value={
                "used_margin": "25000",
                "total_balance": "100000",
                "opening_risk_capital": "100000",
            }
        ),
        trade_book=AsyncMock(
            return_value=[
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "BUY",
                    "quantity": "5",
                    "price": "100",
                    "timestamp": "2026-07-13 10:15:00",
                },
            ],
        ),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(
            return_value=[
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "ltp": 90,
                    "prev_close": 80,
                },
            ],
        ),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
        "dhan",
        account_id="D1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.daily_pnl == pytest.approx(-50.0)
    assert state.starting_capital == pytest.approx(100000.0)
    assert state.used_margin == pytest.approx(25000.0)
    assert len(state.positions) == 1
    assert adapter.positions.await_count == 2
    adapter.funds.assert_awaited_once_with(session)
    assert adapter.trade_book.await_count == 2
    assert adapter.holdings.await_count == 2
    adapter.quotes.assert_awaited_once_with(session, ["NSE:TCS"])


@pytest.mark.asyncio
async def test_gather_safety_state_aggregates_authoritative_option_greeks() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    option_position = {
        "symbol": "NIFTY 30 JUL 26 25000 CE",
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "75",
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 25_000,
        "underlying": "NIFTY",
        "overnight_quantity": "0",
        "day_buy_quantity": "75",
        "day_sell_quantity": "0",
        "accounting_complete": True,
        "multiplier": 1,
        "cross_currency": False,
    }
    option_trade = {
        "symbol": option_position["symbol"],
        "instrument_id": option_position["instrument_id"],
        "exchange": "NFO",
        "product": "NRML",
        "action": "BUY",
        "quantity": "75",
        "price": "100",
        "timestamp": "2026-07-13 10:15:00",
        "multiplier": 1,
        "cross_currency": False,
    }
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[option_position]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "25000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[option_trade]),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(return_value=[{
            "symbol": option_position["symbol"],
            "exchange": "NFO",
            "ltp": 105,
        }]),
        portfolio_greeks=AsyncMock(return_value=[{
            "symbol": option_position["symbol"],
            "instrument_id": option_position["instrument_id"],
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 6.4,
        }]),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.net_delta == pytest.approx(39.0)
    assert state.net_vega == pytest.approx(480.0)
    adapter.portfolio_greeks.assert_awaited_once()
    greek_positions = adapter.portfolio_greeks.await_args.args[1]
    assert greek_positions == [{
        "symbol": option_position["symbol"],
        "instrument_id": option_position["instrument_id"],
        "exchange": "NFO",
        "quantity": 75.0,
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 25_000.0,
        "underlying": "NIFTY",
    }]


@pytest.mark.asyncio
async def test_gather_safety_state_uses_prospective_post_order_option_greeks() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    symbol = "NIFTY30JUL2625000CE"
    position = {
        "symbol": symbol,
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "75",
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 25_000,
        "underlying": "NIFTY",
        "overnight_quantity": "75",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "accounting_complete": True,
        "multiplier": 1,
        "cross_currency": False,
        "previous_close": 100,
        "previous_close_trusted": True,
    }
    order = SimpleNamespace(
        symbol=symbol,
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="75",
        pricetype="MARKET",
    )
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[position]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "25000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(return_value=[{
            "symbol": symbol,
            "exchange": "NFO",
            "ltp": 105,
            "prev_close": 100,
            "previous_close_trusted": True,
        }]),
        portfolio_greeks=AsyncMock(return_value=[{
            "symbol": symbol,
            "instrument_id": position["instrument_id"],
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 6.4,
        }]),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[order],
    )

    assert state.net_delta == pytest.approx(39.0)
    assert state.net_vega == pytest.approx(480.0)
    prospective = state.admission_for(0)
    assert prospective.net_delta == pytest.approx(78.0)
    assert prospective.net_vega == pytest.approx(960.0)
    assert adapter.portfolio_greeks.await_count == 2
    assert adapter.portfolio_greeks.await_args_list[1].args[1][0]["quantity"] == 150.0


@pytest.mark.asyncio
async def test_gather_safety_state_accepts_native_token_resolved_for_new_option_contract() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    symbol = "NIFTY30JUL2625000CE"
    order = SimpleNamespace(
        symbol=symbol,
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="75",
        pricetype="MARKET",
    )

    async def resolved_greek_rows(
        _session: object,
        positions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        assert positions == [{
            "symbol": symbol,
            "instrument_id": "",
            "exchange": "NFO",
            "quantity": 75.0,
            "option_type": "CE",
            "expiry": "",
            "strike_price": 0.0,
            "underlying": "",
        }]
        return [{
            "symbol": symbol,
            "instrument_id": "NSE_FO|54452",
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 6.4,
        }]

    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        portfolio_greeks=AsyncMock(side_effect=resolved_greek_rows),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[order],
    )

    assert state.net_delta == 0.0
    assert state.net_vega == 0.0
    assert state.admission_for(0).net_delta == pytest.approx(39.0)
    assert state.admission_for(0).net_vega == pytest.approx(480.0)
    adapter.portfolio_greeks.assert_awaited_once()


@pytest.mark.asyncio
async def test_gather_safety_state_reads_greeks_for_dhan_call_display_alias() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    symbol = "DIVISLAB 28 JUL 3600 CALL"
    order = SimpleNamespace(
        symbol=symbol,
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="100",
        pricetype="MARKET",
    )

    async def resolved_greek_rows(
        _session: object,
        positions: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        assert positions == [{
            "symbol": symbol,
            "instrument_id": "",
            "exchange": "NFO",
            "quantity": 100.0,
            "option_type": "CE",
            "expiry": "",
            "strike_price": 0.0,
            "underlying": "",
        }]
        return [{
            "symbol": symbol,
            "instrument_id": "100003",
            "exchange": "NFO",
            "delta": 0.52,
            "vega": 6.4,
        }]

    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        portfolio_greeks=AsyncMock(side_effect=resolved_greek_rows),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
        "dhan",
        account_id="DHAN1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[order],
    )

    assert state.admission_for(0).net_delta == pytest.approx(52.0)
    assert state.admission_for(0).net_vega == pytest.approx(640.0)
    adapter.portfolio_greeks.assert_awaited_once()


@pytest.mark.asyncio
async def test_gather_safety_state_counts_active_unfilled_option_orders_before_new_order() -> None:
    """Accepted remainder is exposure even before it appears in the position book."""
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    symbol = "NIFTY30JUL2625000CE"
    position = {
        "symbol": symbol,
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "50",
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 25_000,
        "underlying": "NIFTY",
        "overnight_quantity": "50",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "accounting_complete": True,
        "multiplier": 1,
        "cross_currency": False,
        "previous_close": 100,
        "previous_close_trusted": True,
    }
    pending = {
        **position,
        "order_id": "pending-1",
        "status": "PARTIALLY FILLED",
        "action": "BUY",
        "quantity": "50",
        "filled_quantity": "25",
        "pricetype": "LIMIT",
        "price": "101",
    }
    proposed = SimpleNamespace(
        symbol=symbol,
        instrument_id=position["instrument_id"],
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="25",
        pricetype="MARKET",
        option_type="CE",
        expiry="2026-07-30",
        strike_price=25_000,
        underlying="NIFTY",
    )

    async def greek_rows(_session: object, positions: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "symbol": row["symbol"],
                "instrument_id": row["instrument_id"],
                "exchange": row["exchange"],
                "delta": 0.5,
                "vega": 4.0,
            }
            for row in positions
        ]

    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[position]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "25000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[pending]),
        quotes=AsyncMock(return_value=[{
            "symbol": symbol,
            "exchange": "NFO",
            "ltp": 105,
            "prev_close": 100,
            "previous_close_trusted": True,
        }]),
        portfolio_greeks=AsyncMock(side_effect=greek_rows),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[proposed],
    )

    assert state.net_delta == pytest.approx(37.5)
    assert state.net_vega == pytest.approx(300.0)
    admission = state.admission_for(0)
    assert admission.net_delta == pytest.approx(50.0)
    assert admission.net_vega == pytest.approx(400.0)
    assert sum(int(row.quantity) for row in admission.positions) == 75
    assert adapter.order_book.await_count == 2


@pytest.mark.asyncio
async def test_gather_safety_state_ignores_terminal_orders() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[{
            "status": "COMPLETE",
            "symbol": "NIFTY30JUL2625000CE",
            "exchange": "NFO",
            "product": "NRML",
            "action": "BUY",
            "quantity": "50",
        }]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        portfolio_greeks=AsyncMock(side_effect=AssertionError("terminal orders carry no exposure")),
    )
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.net_delta == 0.0
    assert state.net_vega == 0.0
    adapter.portfolio_greeks.assert_not_awaited()


@pytest.mark.asyncio
async def test_gather_safety_state_fails_closed_without_order_book_reader() -> None:
    session = object()
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
    )
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)

    with pytest.raises(PortfolioSafetyStateError, match="order_book"):
        await gather_safety_state(
            {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
            "upstox",
            account_id="UPX1",
        )


@pytest.mark.asyncio
async def test_gather_safety_state_projects_unresolved_local_reservation() -> None:
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    current_order = SimpleNamespace(
        symbol="TCS",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="5",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-1",
        starting_quantity=0,
        order=reserved_order,
    )
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        margin_calculator=AsyncMock(return_value={"required_margin": "1000"}),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        orders=[current_order],
        reservations=[reservation],
        include_order_margin=True,
    )

    admission = state.admission_for(0)
    assert [(row.symbol, row.quantity) for row in admission.positions] == [("RELIANCE", "10")]
    assert admission.used_margin == pytest.approx(2000)
    assert state.reconciled_reservation_ids == ()


@pytest.mark.asyncio
async def test_gather_safety_state_retains_reservation_visible_as_active_order() -> None:
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-1",
        starting_quantity=0,
        order=reserved_order,
    )
    active = {
        "orderid": "OID-1",
        "status": "OPEN",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "quantity": "10",
        "filled_quantity": "0",
        "pricetype": "MARKET",
    }
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[active]),
        funds=AsyncMock(return_value={
            "used_margin": "1000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        reservations=[reservation],
    )

    assert state.reconciled_reservation_ids == ()


def test_active_then_disappearing_order_reprojects_until_fill_reaches_positions() -> None:
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-1",
        starting_quantity=0,
        order=reserved_order,
    )
    active = {
        "orderid": "OID-1",
        "status": "OPEN",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "quantity": "10",
        "filled_quantity": "0",
    }
    complete = {**active, "status": "COMPLETE", "filled_quantity": "10"}

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(positions=[], trades=[], holdings=[], orders=[active]),
    )
    assert projected == []
    assert settled == ()

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(positions=[], trades=[], holdings=[], orders=[]),
    )
    assert projected == [reserved_order]
    assert settled == ()

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(
            positions=[{
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "product": "MIS",
                "quantity": "10",
            }],
            trades=[],
            holdings=[],
            orders=[complete],
        ),
    )
    assert projected == []
    assert settled == ("reservation-1",)


def test_zero_fill_terminal_reservation_settles_when_broker_omits_identity() -> None:
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-REJECTED",
        starting_quantity=0,
        order=reserved_order,
    )

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(
            positions=[],
            trades=[],
            holdings=[],
            orders=[{
                "orderid": "OID-REJECTED",
                "status": "REJECTED",
                "filled_quantity": "0",
            }],
        ),
    )

    assert projected == []
    assert settled == ("reservation-1",)


def test_terminal_reservation_with_unknown_fill_remains_projected() -> None:
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-CANCELLED",
        starting_quantity=0,
        order=reserved_order,
    )

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(
            positions=[],
            trades=[],
            holdings=[],
            orders=[{"orderid": "OID-CANCELLED", "status": "CANCELLED"}],
        ),
    )

    assert projected == [reserved_order]
    assert settled == ()


def test_cancelled_conditional_parent_settles_each_zero_fill_leg_reservation() -> None:
    order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservations = [
        SimpleNamespace(
            reservation_id=f"reservation-{index}",
            broker_order_id=f"ALERT-1:{index}",
            starting_quantity=0,
            order=order,
        )
        for index in range(2)
    ]

    projected, settled = _project_unresolved_reservations(
        reservations,
        _AccountingSnapshot(
            positions=[],
            trades=[],
            holdings=[],
            orders=[{
                "orderid": "ALERT-1",
                "order_family": "conditional",
                "status": "CANCELLED",
                "filled_quantity": "0",
            }],
        ),
    )

    assert projected == []
    assert settled == ("reservation-0", "reservation-1")


def test_cancelled_conditional_parent_with_unknown_fill_remains_reserved() -> None:
    order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="ALERT-1:0",
        starting_quantity=0,
        order=order,
    )

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(
            positions=[],
            trades=[],
            holdings=[],
            orders=[{
                "orderid": "ALERT-1",
                "order_family": "conditional",
                "status": "CANCELLED",
            }],
        ),
    )

    assert projected == [order]
    assert settled == ()


def test_triggered_conditional_parent_remains_reserved_without_leg_identity() -> None:
    order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="ALERT-1:0",
        starting_quantity=0,
        order=order,
    )

    projected, settled = _project_unresolved_reservations(
        [reservation],
        _AccountingSnapshot(
            positions=[],
            trades=[],
            holdings=[],
            orders=[{
                "orderid": "ALERT-1",
                "order_family": "conditional",
                "status": "TRIGGERED",
                "filled_quantity": "0",
            }],
        ),
    )

    assert projected == [order]
    assert settled == ()


@pytest.mark.asyncio
async def test_native_adapter_can_require_serial_accounting_reads() -> None:
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    active = 0
    maximum = 0

    async def read_empty(_session):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return []

    adapter = SimpleNamespace(
        safety_snapshot_requires_serial_reads=True,
        positions=read_empty,
        trade_book=read_empty,
        holdings=read_empty,
        safety_order_book=read_empty,
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
    )

    await gather_safety_state(
        {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
        "dhan",
        account_id="DHAN1",
    )

    assert maximum == 1


@pytest.mark.asyncio
async def test_completed_reservation_waits_for_position_propagation() -> None:
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    reserved_order = SimpleNamespace(
        symbol="RELIANCE",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="10",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )
    reservation = SimpleNamespace(
        reservation_id="reservation-1",
        broker_order_id="OID-1",
        starting_quantity=0,
        order=reserved_order,
    )
    complete = {
        "orderid": "OID-1",
        "status": "COMPLETE",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "MIS",
        "action": "BUY",
        "quantity": "10",
        "filled_quantity": "10",
        "pricetype": "MARKET",
    }
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[complete]),
        funds=AsyncMock(return_value={
            "used_margin": "1000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        reservations=[reservation],
    )

    assert state.reconciled_reservation_ids == ()


@pytest.mark.asyncio
async def test_gather_safety_state_rejects_option_order_without_authoritative_greeks() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    order = SimpleNamespace(
        symbol="NIFTY30JUL2625000PE",
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="75",
        pricetype="MARKET",
    )
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        portfolio_greeks=AsyncMock(return_value=[]),
    )

    with pytest.raises(PortfolioSafetyStateError, match="option portfolio"):
        await gather_safety_state(
            {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
            "upstox",
            account_id="UPX1",
            at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
            orders=[order],
        )


@pytest.mark.asyncio
async def test_gather_safety_state_checks_each_batch_leg_against_every_sibling() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    orders = [
        SimpleNamespace(
            symbol="NIFTY30JUL2625000CE",
            exchange="NFO",
            product="NRML",
            action="BUY",
            quantity="50",
            pricetype="MARKET",
            price="0",
        ),
        SimpleNamespace(
            symbol="NIFTY30JUL2625100CE",
            exchange="NFO",
            product="NRML",
            action="BUY",
            quantity="50",
            pricetype="MARKET",
            price="0",
        ),
    ]

    async def greek_rows(_session: object, positions: list[dict[str, object]]) -> list[dict[str, object]]:
        instrument_ids = {
            "NIFTY30JUL2625000CE": "NSE_FO|54452",
            "NIFTY30JUL2625100CE": "NSE_FO|54453",
        }
        return [
            {
                "symbol": position["symbol"],
                "instrument_id": instrument_ids[str(position["symbol"])],
                "exchange": position["exchange"],
                "delta": 0.6,
                "vega": 10.0,
            }
            for position in positions
        ]

    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "30000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        portfolio_greeks=AsyncMock(side_effect=greek_rows),
        margin_calculator=AsyncMock(return_value={"required_margin": "20000"}),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=orders,
        include_order_margin=True,
    )

    first = state.admission_for(0)
    second = state.admission_for(1)
    assert len(first.positions) == 1
    assert first.positions[0].symbol == orders[1].symbol
    assert first.positions[0].quantity == "50"
    assert first.used_margin == pytest.approx(70_000.0)
    assert first.net_delta == pytest.approx(60.0)
    assert first.net_vega == pytest.approx(1_000.0)
    assert len(second.positions) == 1
    assert second.positions[0].symbol == orders[0].symbol
    assert second.positions[0].quantity == "50"
    assert second.used_margin == pytest.approx(70_000.0)
    assert second.net_delta == pytest.approx(60.0)
    assert second.net_vega == pytest.approx(1_000.0)
    assert adapter.margin_calculator.await_count == 2


@pytest.mark.asyncio
async def test_gather_safety_state_does_not_credit_an_uncertain_option_hedge() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)
    symbol = "NIFTY30JUL2625000CE"
    position = {
        "symbol": symbol,
        "instrument_id": "NSE_FO|54452",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "100",
        "option_type": "CE",
        "expiry": "2026-07-30",
        "strike_price": 25_000,
        "underlying": "NIFTY",
        "overnight_quantity": "100",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "accounting_complete": True,
        "multiplier": 1,
        "cross_currency": False,
        "previous_close": 100,
        "previous_close_trusted": True,
    }
    pending_hedge = {
        **position,
        "order_id": "pending-sell",
        "status": "OPEN",
        "action": "SELL",
        "quantity": "100",
        "filled_quantity": "0",
        "pricetype": "LIMIT",
        "price": "105",
    }
    proposed = SimpleNamespace(
        symbol=symbol,
        instrument_id=position["instrument_id"],
        exchange="NFO",
        product="NRML",
        action="BUY",
        quantity="100",
        pricetype="MARKET",
        option_type="CE",
        expiry="2026-07-30",
        strike_price=25_000,
        underlying="NIFTY",
    )

    async def greek_rows(_session: object, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return [
            {
                "symbol": row["symbol"],
                "instrument_id": row["instrument_id"],
                "exchange": row["exchange"],
                "delta": 0.5,
                "vega": 4.0,
            }
            for row in rows
        ]

    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[position]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "10000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[pending_hedge]),
        quotes=AsyncMock(return_value=[{
            "symbol": symbol,
            "exchange": "NFO",
            "ltp": 105,
            "prev_close": 100,
            "previous_close_trusted": True,
        }]),
        portfolio_greeks=AsyncMock(side_effect=greek_rows),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[proposed],
    )

    admission = state.admission_for(0)
    assert admission.net_delta == pytest.approx(100.0)
    assert admission.net_vega == pytest.approx(800.0)
    assert [(row.symbol, row.quantity) for row in admission.positions] == [(symbol, "100")]


@pytest.mark.asyncio
async def test_gather_safety_state_keeps_non_option_greeks_explicitly_zero() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        portfolio_greeks=AsyncMock(side_effect=AssertionError("no option read expected")),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
        "dhan",
        account_id="DH1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.net_delta == 0.0
    assert state.net_vega == 0.0
    adapter.portfolio_greeks.assert_not_awaited()


@pytest.mark.asyncio
async def test_gather_safety_state_fails_closed_on_incomplete_option_greeks() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    option_position = {
        "symbol": "NIFTY30JUL2625000PE",
        "instrument_id": "NSE_FO|54453",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": "-75",
        "option_type": "PE",
        "overnight_quantity": "-75",
        "day_buy_quantity": "0",
        "day_sell_quantity": "0",
        "accounting_complete": True,
        "multiplier": 1,
        "cross_currency": False,
    }
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[option_position]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "25000",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(return_value=[{
            "symbol": option_position["symbol"],
            "exchange": "NFO",
            "ltp": 105,
            "prev_close": 100,
            "previous_close_trusted": True,
        }]),
        portfolio_greeks=AsyncMock(return_value=[{
            "symbol": option_position["symbol"],
            "instrument_id": option_position["instrument_id"],
            "exchange": "NFO",
            "delta": -0.48,
        }]),
    )

    with pytest.raises(PortfolioSafetyStateError, match="option Greek"):
        await gather_safety_state(
            {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
            "upstox",
            account_id="UPX1",
            at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        )


@pytest.mark.asyncio
async def test_gather_safety_state_reads_ltp_for_price_deviation_checks() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    order = SimpleNamespace(
        symbol="TCS",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="1",
        pricetype="LIMIT",
    )
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "ltp": 3500.0,
        }]),
    )

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
        "upstox",
        account_id="UPX1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        orders=[order],
    )

    assert state.ltp_for(order) == 3500.0
    adapter.quotes.assert_awaited_once_with(session, ["NSE:TCS"])


@pytest.mark.asyncio
async def test_gather_safety_state_fails_closed_when_required_order_ltp_is_missing() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    registry = SimpleNamespace(get_session_for=lambda adapter_id, account_id: session)
    order = SimpleNamespace(
        symbol="TCS",
        exchange="NSE",
        product="MIS",
        action="BUY",
        quantity="1",
        pricetype="SL",
    )
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        quotes=AsyncMock(return_value=[]),
    )

    with pytest.raises(PortfolioSafetyStateError, match="order LTP"):
        await gather_safety_state(
            {"NATIVE_ADAPTERS": {"upstox": adapter}, "REGISTRY": registry},
            "upstox",
            account_id="UPX1",
            at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
            orders=[order],
        )


@pytest.mark.asyncio
async def test_gather_safety_state_fails_closed_when_capital_is_unavailable() -> None:
    client = SimpleNamespace(
        positionbook=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={"used_margin": "0", "total_balance": "0"}),
        tradebook=AsyncMock(return_value=[]),
        orderbook=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        multi_quotes=AsyncMock(return_value=[]),
    )

    with pytest.raises(PortfolioSafetyStateError, match="capital"):
        await gather_safety_state({"OPENALGO_CLIENT": client}, "openalgo")


@pytest.mark.asyncio
async def test_time_only_openalgo_trades_require_an_authoritative_started_session() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    client = SimpleNamespace(
        positionbook=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 1,
        }]),
        tradebook=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
            "price": 100,
            "timestamp": "09:30:00",
        }]),
        orderbook=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": 0,
            "total_balance": 100_000,
            "opening_risk_capital": 100_000,
        }),
        multi_quotes=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "ltp": 110,
        }]),
    )
    at = datetime(2026, 7, 13, 10, 0, tzinfo=ist)

    with pytest.raises(PortfolioSafetyStateError, match="Authoritative market session"):
        await gather_safety_state({"OPENALGO_CLIENT": client}, "openalgo", at=at)

    scheduler = SimpleNamespace(
        get_market_session=lambda exchange, *, on, symbol: (
            time(9, 15),
            time(15, 30),
        ) if exchange == "NSE" and on == at.date() and symbol == "TCS" else None,
    )
    with pytest.raises(PortfolioSafetyStateError, match="before the current session opens"):
        await gather_safety_state(
            {"OPENALGO_CLIENT": client, "TIME_SCHEDULER": scheduler},
            "openalgo",
            at=at.replace(hour=8),
        )

    state = await gather_safety_state(
        {"OPENALGO_CLIENT": client, "TIME_SCHEDULER": scheduler},
        "openalgo",
        at=at,
    )

    assert state.daily_pnl == pytest.approx(10.0)


@pytest.mark.asyncio
async def test_gather_safety_state_backfills_previous_close_from_completed_daily_history() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    client = SimpleNamespace(
        positionbook=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 1,
        }]),
        tradebook=AsyncMock(return_value=[]),
        orderbook=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": 0,
            "total_balance": 100000,
            "opening_risk_capital": 100000,
        }),
        multi_quotes=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "ltp": 90,
            "prev_close": 999,
            "previous_close_trusted": False,
        }]),
        history=AsyncMock(return_value=[{
            "timestamp": "2026-07-10T15:30:00+05:30",
            "close": 100,
        }]),
    )

    state = await gather_safety_state(
        {"OPENALGO_CLIENT": client},
        "openalgo",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.daily_pnl == pytest.approx(-10.0)
    client.history.assert_awaited_once_with("TCS", "NSE", "D", "2026-06-29", "2026-07-12")


@pytest.mark.asyncio
async def test_gather_safety_state_rejects_non_completed_history_candle() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    client = SimpleNamespace(
        positionbook=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 1,
        }]),
        tradebook=AsyncMock(return_value=[]),
        orderbook=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(return_value={
            "used_margin": 0,
            "total_balance": 100000,
            "opening_risk_capital": 100000,
        }),
        multi_quotes=AsyncMock(return_value=[{
            "symbol": "TCS",
            "exchange": "NSE",
            "ltp": 90,
        }]),
        history=AsyncMock(return_value=[{
            "timestamp": "2026-07-13T09:30:00+05:30",
            "close": 100,
        }]),
    )

    with pytest.raises(PortfolioSafetyStateError, match="non-completed session"):
        await gather_safety_state(
            {"OPENALGO_CLIENT": client},
            "openalgo",
            at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        )


def test_local_daily_pnl_uses_broker_pnl_multiplier_without_spurious_fx() -> None:
    positions = [
        {
            "symbol": "USDINR",
            "exchange": "CDS",
            "product": "NRML",
            "quantity": 1,
            "multiplier": 1000,
            "fx_rate": 83.25,
            "cross_currency": False,
            "close_price": 10.0,
            "previous_close_trusted": True,
        }
    ]
    quotes = [{
        "symbol": "USDINR",
        "exchange": "CDS",
        "ltp": 10.1,
        "prev_close": 10.0,
        "previous_close_trusted": True,
    }]

    assert compute_local_daily_pnl([], positions, quotes) == pytest.approx(100.0)


def test_local_daily_pnl_applies_fx_only_to_explicit_cross_currency_position() -> None:
    positions = [{
        "symbol": "EURUSD",
        "exchange": "CDS",
        "product": "NRML",
        "quantity": 1,
        "multiplier": 1000,
        "fx_rate": 83.25,
        "cross_currency": True,
        "close_price": 1.1,
        "previous_close_trusted": True,
    }]
    quotes = [{"symbol": "EURUSD", "exchange": "CDS", "ltp": 1.2}]

    assert compute_local_daily_pnl([], positions, quotes) == pytest.approx(8325.0)


def test_local_daily_pnl_includes_untouched_delivery_holdings() -> None:
    holdings = [
        {
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 10,
            "close_price": 100,
            "previous_close_trusted": True,
        }
    ]
    quotes = [{"symbol": "TCS", "exchange": "NSE", "ltp": 90, "prev_close": 100}]

    assert compute_local_daily_pnl([], [], quotes, holdings) == pytest.approx(-100.0)


def test_delivery_holding_plus_proven_day_position_reconciles_without_double_counting() -> None:
    holdings = [
        {
            "symbol": "TCS",
            "instrument_id": "INE467B01029",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": 10,
            "close_price": 100,
            "previous_close_trusted": True,
            "accounting_complete": True,
        }
    ]
    positions = [
        {
            "symbol": "TCS",
            "instrument_id": "INE467B01029",
            "exchange": "NSE",
            "product": "CNC",
            "quantity": -3,
            "overnight_quantity": 0,
            "day_buy_quantity": 0,
            "day_sell_quantity": 3,
            "accounting_complete": True,
        }
    ]
    trades = [
        {
            "symbol": "TCS",
            "instrument_id": "INE467B01029",
            "exchange": "NSE",
            "product": "CNC",
            "action": "SELL",
            "quantity": 3,
            "price": 95,
        }
    ]
    quotes = [{"symbol": "TCS", "exchange": "NSE", "ltp": 90, "prev_close": 100}]

    assert compute_local_daily_pnl(trades, positions, quotes, holdings) == pytest.approx(-85.0)


def test_delivery_overlap_without_day_accounting_fails_closed() -> None:
    holdings = [
        {"symbol": "TCS", "exchange": "NSE", "product": "CNC", "quantity": 10}
    ]
    positions = [
        {"symbol": "TCS", "exchange": "NSE", "product": "CNC", "quantity": -3}
    ]
    trades = [
        {
            "symbol": "TCS",
            "exchange": "NSE",
            "product": "CNC",
            "action": "SELL",
            "quantity": 3,
            "price": 95,
        }
    ]

    with pytest.raises(PortfolioSafetyStateError, match="overlap"):
        compute_local_daily_pnl(trades, positions, [], holdings)


def test_native_rows_must_agree_on_instrument_identity() -> None:
    positions = [
        {
            "symbol": "TCS",
            "instrument_id": "INE467B01029",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 1,
        }
    ]
    trades = [
        {
            "symbol": "TCS",
            "instrument_id": "different-token",
            "exchange": "NSE",
            "product": "MIS",
            "action": "BUY",
            "quantity": 1,
            "price": 100,
        }
    ]

    with pytest.raises(PortfolioSafetyStateError, match="canonical instrument identity"):
        compute_local_daily_pnl(trades, positions, [])


def test_local_daily_pnl_rejects_derivative_without_multiplier() -> None:
    positions = [
        {
            "symbol": "NIFTY26JULFUT",
            "exchange": "NFO",
            "product": "NRML",
            "quantity": 1,
            "close_price": 25000,
        }
    ]
    quotes = [
        {
            "symbol": "NIFTY26JULFUT",
            "exchange": "NFO",
            "ltp": 24900,
                "prev_close": 25000,
                "previous_close_trusted": True,
        }
    ]

    with pytest.raises(PortfolioSafetyStateError, match="multiplier"):
        compute_local_daily_pnl([], positions, quotes)


def test_local_daily_pnl_rejects_derivative_without_currency_provenance() -> None:
    positions = [{
        "symbol": "NIFTY26JULFUT",
        "exchange": "NFO",
        "product": "NRML",
        "quantity": 1,
        "multiplier": 25,
        "close_price": 25000,
        "previous_close_trusted": True,
    }]
    quotes = [{"symbol": "NIFTY26JULFUT", "exchange": "NFO", "ltp": 24900}]

    with pytest.raises(PortfolioSafetyStateError, match="settlement-currency provenance"):
        compute_local_daily_pnl([], positions, quotes)


def test_local_daily_pnl_rejects_cross_currency_position_without_fx_rate() -> None:
    positions = [{
        "symbol": "EURUSD",
        "exchange": "CDS",
        "product": "NRML",
        "quantity": 1,
        "multiplier": 1000,
        "cross_currency": True,
        "close_price": 1.1,
        "previous_close_trusted": True,
    }]
    quotes = [{"symbol": "EURUSD", "exchange": "CDS", "ltp": 1.2}]

    with pytest.raises(PortfolioSafetyStateError, match="FX rate"):
        compute_local_daily_pnl([], positions, quotes)


@pytest.mark.asyncio
async def test_gather_safety_state_rejects_stale_native_fill() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    adapter = SimpleNamespace(
        positions=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(
            return_value=[
                {
                    "symbol": "TCS",
                    "exchange": "NSE",
                    "product": "MIS",
                    "action": "BUY",
                    "quantity": 1,
                    "price": 100,
                    "timestamp": "2026-07-12 14:00:00",
                }
            ]
        ),
        order_book=AsyncMock(return_value=[]),
        funds=AsyncMock(
            return_value={
                "used_margin": 0,
                "total_balance": 100000,
                "opening_risk_capital": 100000,
            }
        ),
    )
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)

    with pytest.raises(PortfolioSafetyStateError, match="another trading date"):
        await gather_safety_state(
            {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
            "dhan",
            account_id="D1",
            at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
        )


@pytest.mark.asyncio
async def test_gather_safety_state_retries_once_until_accounting_snapshot_is_stable() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    session = object()
    first = [{"symbol": "TCS", "exchange": "NSE", "product": "MIS", "quantity": 1}]
    stable = [{"symbol": "TCS", "exchange": "NSE", "product": "MIS", "quantity": 2}]
    adapter = SimpleNamespace(
        positions=AsyncMock(side_effect=[first, stable, stable]),
        holdings=AsyncMock(return_value=[]),
        trade_book=AsyncMock(return_value=[]),
        order_book=AsyncMock(return_value=[]),
        funds=AsyncMock(
            return_value={
                "used_margin": 0,
                "total_balance": 100000,
                "opening_risk_capital": 100000,
            }
        ),
        quotes=AsyncMock(
            return_value=[{
                "symbol": "TCS",
                "exchange": "NSE",
                "ltp": 100,
                "prev_close": 100,
                "previous_close_trusted": True,
            }]
        ),
    )
    registry = SimpleNamespace(get_session_for=lambda _adapter_id, _account_id: session)

    state = await gather_safety_state(
        {"NATIVE_ADAPTERS": {"dhan": adapter}, "REGISTRY": registry},
        "dhan",
        account_id="D1",
        at=datetime(2026, 7, 13, 11, 0, tzinfo=ist),
    )

    assert state.daily_pnl == 0
    assert adapter.positions.await_count == 3


@pytest.mark.asyncio
async def test_gather_safety_state_refuses_non_default_openalgo_selector() -> None:
    with pytest.raises(PortfolioSafetyStateError, match="one configured account"):
        await gather_safety_state(
            {"OPENALGO_CLIENT": object()},
            "openalgo",
            account_id="second-account",
        )
