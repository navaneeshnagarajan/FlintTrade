"""Options strategy builders — typed factories that produce :class:`BasketLeg` lists.

Each static method on :class:`OptionsStrategyBuilder` returns a
``list[BasketLeg]`` that can be passed directly to
:class:`~flinttrade_engine.basket_orders.BasketOrderExecutor.execute`.

Supported strategies
--------------------
- Short Straddle — sell ATM call + sell ATM put
- Long Strangle  — buy OTM call + buy OTM put
- Iron Condor    — put credit spread + call credit spread
- Iron Butterfly — ATM short straddle + OTM long wings
- Bull Call Spread — buy lower call + sell higher call
- Bear Put Spread  — buy higher put  + sell lower put

All strategies use *NFO* as the default exchange and *NRML* as the default
product (suitable for overnight F&O positions).

Symbol format — the helpers construct symbols of the form::

    {UNDERLYING}{EXPIRY}{STRIKE}CE   e.g. NIFTY25MAY2526000CE
    {UNDERLYING}{EXPIRY}{STRIKE}PE   e.g. NIFTY25MAY2526000PE

The ``expiry`` parameter must match exactly whatever OpenAlgo/broker uses
(e.g. ``"25MAY25"``).  ``strike`` values are passed as floats and formatted
as integers (no decimals) unless the strike itself is fractional (rare on NSE).

Usage::

    legs = OptionsStrategyBuilder.iron_condor(
        underlying="NIFTY",
        expiry="25MAY25",
        put_short=24500.0,
        put_long=24000.0,
        call_short=26000.0,
        call_long=26500.0,
        lots=1,
    )
    result = await executor.execute(legs, strategy="iron_condor_may")
"""

from __future__ import annotations

from flinttrade_engine.basket_orders import BasketLeg


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------


def _fmt_strike(strike: float) -> str:
    """Format a strike price as an integer string (no trailing zero decimals).

    Args:
        strike: Strike price value.

    Returns:
        String representation — ``"26000"`` for ``26000.0``,
        ``"26050.5"`` for ``26050.5``.
    """
    if strike == int(strike):
        return str(int(strike))
    return str(strike)


def _option_symbol(
    underlying: str,
    expiry: str,
    strike: float,
    option_type: str,
) -> str:
    """Construct an option symbol in OpenAlgo format.

    Args:
        underlying: Base symbol (e.g. ``"NIFTY"``).
        expiry: Expiry string as used by the broker (e.g. ``"25MAY25"``).
        strike: Strike price.
        option_type: ``"CE"`` or ``"PE"``.

    Returns:
        Composed symbol string, e.g. ``"NIFTY25MAY2526000CE"``.
    """
    return f"{underlying.upper()}{expiry.upper()}{_fmt_strike(strike)}{option_type.upper()}"


# ---------------------------------------------------------------------------
# OptionsStrategyBuilder
# ---------------------------------------------------------------------------


class OptionsStrategyBuilder:
    """Factory for common F&O multi-leg option strategies.

    All methods are static and return ``list[BasketLeg]``.  The legs can be
    passed directly to
    :class:`~flinttrade_engine.basket_orders.BasketOrderExecutor.execute`.
    """

    @staticmethod
    def short_straddle(
        underlying: str,
        expiry: str,
        strike: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """Sell ATM call + sell ATM put at the same strike.

        Net premium collected; max profit if underlying stays at strike.
        Unlimited risk on both sides.

        Args:
            underlying: Index/stock symbol (e.g. ``"NIFTY"``).
            expiry: Expiry string (e.g. ``"25MAY25"``).
            strike: ATM strike price.
            lots: Number of lots to trade.
            lot_size: Units per lot (default 50 for NIFTY).
            exchange: Derivatives exchange (default ``"NFO"``).
            product: Product type (default ``"NRML"``).

        Returns:
            Two-leg list: [sell CE, sell PE].
        """
        quantity = lots * lot_size
        return [
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, strike, "CE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, strike, "PE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]

    @staticmethod
    def long_strangle(
        underlying: str,
        expiry: str,
        call_strike: float,
        put_strike: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """Buy OTM call + buy OTM put at different strikes.

        Net debit paid; profits from large moves in either direction.

        Args:
            underlying: Index/stock symbol.
            expiry: Expiry string.
            call_strike: OTM call strike (above current price).
            put_strike: OTM put strike (below current price).
            lots: Number of lots.
            lot_size: Units per lot.
            exchange: Derivatives exchange.
            product: Product type.

        Returns:
            Two-leg list: [buy CE, buy PE].
        """
        quantity = lots * lot_size
        return [
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, call_strike, "CE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, put_strike, "PE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]

    @staticmethod
    def iron_condor(
        underlying: str,
        expiry: str,
        put_short: float,
        put_long: float,
        call_short: float,
        call_long: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """Put credit spread + call credit spread — four-legged range trade.

        Sell OTM put spread (put_long < put_short) and sell OTM call spread
        (call_short < call_long).  Net credit received; max profit in the range
        [put_short, call_short].

        Args:
            underlying: Index/stock symbol.
            expiry: Expiry string.
            put_short: Short put strike (closer to ATM).
            put_long: Long put strike (further OTM — protection leg).
            call_short: Short call strike (closer to ATM).
            call_long: Long call strike (further OTM — protection leg).
            lots: Number of lots.
            lot_size: Units per lot.
            exchange: Derivatives exchange.
            product: Product type.

        Returns:
            Four-leg list in execution order (BUYs first for margin efficiency).
        """
        quantity = lots * lot_size
        return [
            # Long protection legs (BUY first — margin relief)
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, put_long, "PE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, call_long, "CE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            # Short premium legs
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, put_short, "PE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, call_short, "CE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]

    @staticmethod
    def iron_butterfly(
        underlying: str,
        expiry: str,
        atm: float,
        wing: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """ATM short straddle + symmetrical OTM long wings.

        Sell ATM call + sell ATM put; buy (atm - wing) put + buy (atm + wing)
        call.  Lower premium than iron condor; max profit at ATM.

        Args:
            underlying: Index/stock symbol.
            expiry: Expiry string.
            atm: ATM strike price.
            wing: Distance from ATM to each wing strike (in strike points).
            lots: Number of lots.
            lot_size: Units per lot.
            exchange: Derivatives exchange.
            product: Product type.

        Returns:
            Four-leg list: [buy lower PE, buy upper CE, sell ATM CE, sell ATM PE].
        """
        quantity = lots * lot_size
        lower = atm - wing
        upper = atm + wing
        return [
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, lower, "PE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, upper, "CE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, atm, "CE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, atm, "PE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]

    @staticmethod
    def bull_call_spread(
        underlying: str,
        expiry: str,
        long_strike: float,
        short_strike: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """Buy lower-strike call + sell higher-strike call — bullish debit spread.

        Net debit; max profit = (short_strike - long_strike) - net debit.
        Requires long_strike < short_strike.

        Args:
            underlying: Index/stock symbol.
            expiry: Expiry string.
            long_strike: Lower strike (buy leg).
            short_strike: Higher strike (sell leg).
            lots: Number of lots.
            lot_size: Units per lot.
            exchange: Derivatives exchange.
            product: Product type.

        Returns:
            Two-leg list: [buy lower CE, sell higher CE].

        Raises:
            ValueError: When long_strike >= short_strike.
        """
        if long_strike >= short_strike:
            raise ValueError(
                f"bull_call_spread: long_strike ({long_strike}) must be < short_strike ({short_strike})"
            )
        quantity = lots * lot_size
        return [
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, long_strike, "CE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, short_strike, "CE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]

    @staticmethod
    def bear_put_spread(
        underlying: str,
        expiry: str,
        long_strike: float,
        short_strike: float,
        lots: int,
        lot_size: int = 50,
        exchange: str = "NFO",
        product: str = "NRML",
    ) -> list[BasketLeg]:
        """Buy higher-strike put + sell lower-strike put — bearish debit spread.

        Net debit; max profit = (long_strike - short_strike) - net debit.
        Requires long_strike > short_strike.

        Args:
            underlying: Index/stock symbol.
            expiry: Expiry string.
            long_strike: Higher strike (buy leg — in-the-money side).
            short_strike: Lower strike (sell leg — protection cap).
            lots: Number of lots.
            lot_size: Units per lot.
            exchange: Derivatives exchange.
            product: Product type.

        Returns:
            Two-leg list: [buy higher PE, sell lower PE].

        Raises:
            ValueError: When long_strike <= short_strike.
        """
        if long_strike <= short_strike:
            raise ValueError(
                f"bear_put_spread: long_strike ({long_strike}) must be > short_strike ({short_strike})"
            )
        quantity = lots * lot_size
        return [
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, long_strike, "PE"),
                exchange=exchange,
                action="BUY",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
            BasketLeg(
                symbol=_option_symbol(underlying, expiry, short_strike, "PE"),
                exchange=exchange,
                action="SELL",
                quantity=quantity,
                order_type="MARKET",
                product=product,
            ),
        ]
