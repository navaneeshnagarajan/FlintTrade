"""Option chain fetcher and analyzer.

Fetches live option chain via OpenAlgo /api/v1/optionchain, parses into
structured strike data, and supports all F&O exchanges:
- NFO: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, stock options
- BFO: SENSEX, BANKEX, SENSEX50
- CDS: USDINR, EURINR, GBPINR, JPYINR
- MCX: CRUDEOIL, GOLD, SILVER options
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from packages.core.src.models import OptionChainStrike
from packages.core.src.openalgo_client import OpenAlgoClient

logger = logging.getLogger("flinttrade.screener.option_chain")


@dataclass
class StrikeData:
    """Parsed strike with CE and PE data side-by-side."""

    strike_price: float = 0.0
    ce_ltp: float = 0.0
    ce_oi: int = 0
    ce_volume: int = 0
    ce_iv: float = 0.0
    ce_delta: float = 0.0
    ce_gamma: float = 0.0
    ce_theta: float = 0.0
    ce_vega: float = 0.0
    ce_bid: float = 0.0
    ce_ask: float = 0.0
    pe_ltp: float = 0.0
    pe_oi: int = 0
    pe_volume: int = 0
    pe_iv: float = 0.0
    pe_delta: float = 0.0
    pe_gamma: float = 0.0
    pe_theta: float = 0.0
    pe_vega: float = 0.0
    pe_bid: float = 0.0
    pe_ask: float = 0.0

    @property
    def ce_oi_value(self) -> float:
        """CE OI * CE LTP — notional value locked in calls."""
        return self.ce_oi * self.ce_ltp

    @property
    def pe_oi_value(self) -> float:
        """PE OI * PE LTP — notional value locked in puts."""
        return self.pe_oi * self.pe_ltp


@dataclass
class OptionChainSnapshot:
    """Full option chain snapshot with metadata."""

    underlying: str = ""
    exchange: str = ""
    spot_price: float = 0.0
    atm_strike: float = 0.0
    strikes: list[StrikeData] = field(default_factory=list)

    @property
    def total_ce_oi(self) -> int:
        return sum(s.ce_oi for s in self.strikes)

    @property
    def total_pe_oi(self) -> int:
        return sum(s.pe_oi for s in self.strikes)

    @property
    def total_ce_volume(self) -> int:
        return sum(s.ce_volume for s in self.strikes)

    @property
    def total_pe_volume(self) -> int:
        return sum(s.pe_volume for s in self.strikes)

    def get_strike(self, strike_price: float) -> StrikeData | None:
        """Find a specific strike."""
        for s in self.strikes:
            if s.strike_price == strike_price:
                return s
        return None

    def strikes_near_atm(self, count: int = 10) -> list[StrikeData]:
        """Get N strikes above and below ATM."""
        if not self.strikes or self.atm_strike == 0:
            return list(self.strikes)
        sorted_strikes = sorted(self.strikes, key=lambda s: s.strike_price)
        atm_idx = 0
        min_diff = float("inf")
        for i, s in enumerate(sorted_strikes):
            diff = abs(s.strike_price - self.atm_strike)
            if diff < min_diff:
                min_diff = diff
                atm_idx = i
        start = max(0, atm_idx - count)
        end = min(len(sorted_strikes), atm_idx + count + 1)
        return sorted_strikes[start:end]


# Lot sizes for common underlyings
LOT_SIZES: dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 50,
    "SENSEX": 20,
    "BANKEX": 30,
    "SENSEX50": 25,
    "USDINR": 1000,
    "EURINR": 1000,
    "GBPINR": 1000,
    "JPYINR": 1000,
    "CRUDEOIL": 100,
    "GOLD": 100,
    "GOLDM": 10,
    "SILVER": 30,
    "SILVERM": 5,
    "NATURALGAS": 1250,
    "COPPER": 2500,
    "ZINC": 5000,
}

# Exchange-to-spot-index mapping for fetching spot price
_SPOT_EXCHANGE: dict[str, str] = {
    "NFO": "NSE_INDEX",
    "BFO": "BSE_INDEX",
    "CDS": "CDS",
    "MCX": "MCX",
}


def find_atm_strike(spot: float, strikes: list[float]) -> float:
    """Find the ATM strike closest to spot price."""
    if not strikes:
        return 0.0
    return min(strikes, key=lambda s: abs(s - spot))


class OptionChainAnalyzer:
    """Fetch and analyze option chains across all F&O exchanges.

    Usage::

        analyzer = OptionChainAnalyzer(client)
        snapshot = analyzer.fetch("NIFTY", "NFO")
        near_atm = snapshot.strikes_near_atm(5)
    """

    def __init__(self, client: OpenAlgoClient) -> None:
        self._client = client

    def fetch(
        self,
        symbol: str,
        exchange: str = "NFO",
        spot_price: float | None = None,
    ) -> OptionChainSnapshot:
        """Fetch option chain and build a structured snapshot.

        If spot_price is not given, fetches it from the quotes endpoint.
        """
        chain = self._client.option_chain(symbol, exchange)

        # Get spot price
        if spot_price is None:
            spot_price = self._fetch_spot(symbol, exchange)

        # Parse strikes
        strike_data = [self._parse_strike(s) for s in chain.strikes]

        # Find ATM
        strike_prices = [s.strike_price for s in strike_data]
        atm = find_atm_strike(spot_price, strike_prices)

        snapshot = OptionChainSnapshot(
            underlying=chain.underlying or symbol,
            exchange=chain.exchange or exchange,
            spot_price=spot_price,
            atm_strike=atm,
            strikes=sorted(strike_data, key=lambda s: s.strike_price),
        )

        logger.info(
            "Option chain: %s %s — %d strikes, spot=%.2f, ATM=%.0f",
            symbol, exchange, len(strike_data), spot_price, atm,
        )
        return snapshot

    def _fetch_spot(self, symbol: str, exchange: str) -> float:
        """Fetch spot price for the underlying."""
        spot_exch = _SPOT_EXCHANGE.get(exchange, "NSE_INDEX")
        try:
            quote = self._client.quotes(symbol, spot_exch)
            return quote.ltp
        except Exception:
            try:
                quote = self._client.quotes(symbol, "NSE")
                return quote.ltp
            except Exception as exc:
                logger.warning("Could not fetch spot for %s: %s", symbol, exc)
                return 0.0

    @staticmethod
    def _parse_strike(s: OptionChainStrike) -> StrikeData:
        return StrikeData(
            strike_price=s.strike_price,
            ce_ltp=s.ce_ltp, ce_oi=s.ce_oi, ce_volume=s.ce_volume,
            ce_iv=s.ce_iv, ce_delta=s.ce_delta, ce_gamma=s.ce_gamma,
            ce_theta=s.ce_theta, ce_vega=s.ce_vega, ce_bid=s.ce_bid, ce_ask=s.ce_ask,
            pe_ltp=s.pe_ltp, pe_oi=s.pe_oi, pe_volume=s.pe_volume,
            pe_iv=s.pe_iv, pe_delta=s.pe_delta, pe_gamma=s.pe_gamma,
            pe_theta=s.pe_theta, pe_vega=s.pe_vega, pe_bid=s.pe_bid, pe_ask=s.pe_ask,
        )

    @staticmethod
    def get_lot_size(symbol: str) -> int:
        """Get lot size for an underlying. Returns 1 if unknown."""
        return LOT_SIZES.get(symbol.upper(), 1)
