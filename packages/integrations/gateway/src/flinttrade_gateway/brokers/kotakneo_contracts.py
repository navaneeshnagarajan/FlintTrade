"""Versioned, offline exact listings for the reviewed Kotak index options.

This is an injected snapshot, not a downloader or an eligibility grant. Refresh
and freshness budgets belong to the reference-data owner. No lot is inferred.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid

SCHEMA_REVISION = "kotak-master-0ba71b7f-v1"
_STRIKE_SOURCE = (
    "https://github.com/Kotak-Neo/kotak-neo-python/blob/"
    "0ba71b7f7c295652d4c3ea2b5ce5a88849db18a3/neo_api_client/services/scrip_search.py"
)
_EXPIRY_SOURCE = (
    "https://github.com/Kotak-Neo/Kotak-Neo/blob/"
    "e76202a0545898e37608757d0a218cc847e8d287/docs/market-data-apis/instruments.md"
)
# Independent exchange price rules. These do NOT decode dTickSize/lPrecision.
_TICKS = {
    ("NFO", "NIFTY"): ("https://www.nseindia.com/products-services/equity-derivatives-nifty50",
        "6de5c4d335ecc87f3628c7432efec2310c5ecd8199e54a7c6e32db15643de215"),
    ("BFO", "SENSEX"): ("https://beta.bseindia.com/static/markets/Derivatives/DeriReports/contractindex.aspx",
        "c3eb8374ceb659ce9cbb74eed203c93425e2d3dafb6cbf544e99603cb748de89"),
}
_IST = timezone(timedelta(hours=5, minutes=30))
# Exact selected native class profiles, not a universal NSE/BSE spelling.
# NSE Nifty contract specification uses OPTIDX; BSE's contract-file Product
# Type is IO (Index Options), distinct from IF/SF/SO. No unknown class grants
# option authority merely because a row also contains a CE/PE right.
# https://www.nseindia.com/products-services/equity-derivatives-nifty50
# https://www.bseindia.com/downloads1/File_Format_Equity_Derivatives.pdf
_OPTION_CLASSES = {("nse_fo", "NIFTY"): "OPTIDX", ("bse_fo", "SENSEX"): "IO"}
_FIELDS = (
    "pSymbol", "pTrdSymbol", "pExchSeg", "pSymbolName", "pOptionType", "pInstType",
    "lExpiryDate", "pExpiryDate", "dStrikePrice;", "lLotSize", "dTickSize", "lPrecision",
    "pMultiplier", "lFreezeQty", "dPriceDenominator", "dGeneralNumerator", "dGeneralDenominator",
)


def is_selected_option_symbol(symbol: str, exchange: str) -> bool:
    """Identify requests requiring the selected index-option listing profile.

    Args:
        symbol: Exact caller symbol; no alias, case conversion or expiry roll.
        exchange: Exact FlintTrade venue code.

    Returns:
        Whether the symbol requests a selected underlying or recognisable
        option. This is a refusal classifier, never proof of a listed contract;
        opaque listed symbols are identified separately by the resolver.
    """
    return exchange in {"NFO", "BFO"} and (
        symbol in {"NIFTY", "SENSEX"}
        or symbol.startswith(("NIFTY", "SENSEX")) and symbol.endswith(("CE", "PE"))
    )


def _text(value: Any) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise BrokerReadResponseInvalid from None
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise BrokerReadResponseInvalid from None
    return value


def _number(value: Any, *, positive: bool = False, whole: bool = False) -> Decimal:
    if type(value) is not str and type(value) is not int:
        raise BrokerReadResponseInvalid from None
    if type(value) is int and value.bit_length() > 212:
        raise BrokerReadResponseInvalid from None
    try:
        n = Decimal(_text(value) if type(value) is str else str(value))
    except (InvalidOperation, ValueError):
        raise BrokerReadResponseInvalid from None
    if not n.is_finite():
        raise BrokerReadResponseInvalid from None
    _, digits, exponent = n.as_tuple()
    if len(digits) > 64 or not -12 <= exponent <= 32 or max(len(digits) + exponent, 0) > 32:
        raise BrokerReadResponseInvalid from None
    if n < 0 or positive and n == 0 or whole and n != n.to_integral_value():
        raise BrokerReadResponseInvalid from None
    return n


def _instant(value: datetime) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BrokerReadResponseInvalid from None
    return value.astimezone(UTC)


def _expiry(raw: Any, segment: str, *, sdk: bool = False) -> date:
    # SDK transforms pExpiryDate using UTC; REST defines lExpiryDate in IST.
    if sdk and type(raw) is str and len(raw) == 9 and raw[2:5].isalpha():
        months = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
        try:
            return date(int(raw[5:]), months.index(raw[2:5].upper()) + 1, int(raw[:2]))
        except ValueError:
            raise BrokerReadResponseInvalid from None
    epoch = int(_number(raw, whole=True)) + (315511200 if segment == "nse_fo" else 0)
    try:
        return datetime.fromtimestamp(epoch, UTC if sdk else _IST).date()
    except (OverflowError, OSError, ValueError):
        raise BrokerReadResponseInvalid from None


@dataclass(frozen=True, slots=True)
class KotakListedContract:
    """Immutable exact listing built by KotakContractResolver.from_records.

    Attributes:
        symbol: Exact listed trading symbol; opaque spellings remain unchanged.
        exchange: FlintTrade venue for this listing.
        token: Exact native instrument token in native_segment's namespace.
        native_segment: Native exchange segment.
        underlying: Exact selected index underlying.
        option_type: Native CE or PE right.
        instrument_type: Venue-specific qualified native index-option class.
        expiry: ISO expiry date, not a qualified session-close instant.
        strike: Exact index-point strike derived only from dStrikePrice;.
        lot_size: Positive whole underlying units per listed lot.
        raw_json: Detached native fields, with original units and spellings.
        source: Caller-bound source identity, not a fetched resource.
        source_revision: Exact snapshot revision used for invocation comparison.
        source_digest: Digest of the detached complete supplied row set.
        observed_at: Aware source observation instant.
        valid_until: Exclusive snapshot freshness deadline, not session expiry.
    """
    symbol: str
    exchange: str
    token: str
    native_segment: str
    underlying: str
    option_type: str
    instrument_type: str
    expiry: str
    strike: str
    lot_size: int
    raw_json: str
    source: str
    source_revision: str
    source_digest: str
    observed_at: datetime
    valid_until: datetime

    def evidence(self) -> dict[str, Any]:
        """Return detached listing and independently sourced tick observations.

        Returns:
            Exact native fields, source/record digests and freshness operands.
            The independent INR tick does not prove raw broker tick scaling,
            eligibility, paid fees or permission to execute on the expiry date.
        """
        raw = json.loads(self.raw_json)
        url, digest = _TICKS[(self.exchange, self.underlying)]
        return {
            "broker": "kotakneo", "symbol": self.symbol, "exchange": self.exchange,
            "instrument_id": self.token, "broker_exchange_segment": self.native_segment,
            "underlying": self.underlying, "option_type": self.option_type,
            "instrument_type": self.instrument_type, "expiry": self.expiry, "strike": self.strike,
            "strike_unit": "index_points", "lot_size": self.lot_size, "quantity_unit": "underlying_units",
            "raw_tick_size": raw["dTickSize"], "raw_precision": raw["lPrecision"],
            "tick_size_inr": "0.05", "tick_scale_verified": False,
            "tick_source": {"kind": "independent_exchange_rule", "url": url, "sha256": digest,
                            "reviewed_on": "2026-10-24", "master_scale": "unverified"},
            "source": self.source, "source_revision": self.source_revision, "schema_revision": SCHEMA_REVISION,
            "source_digest": self.source_digest, "record_digest": hashlib.sha256(self.raw_json.encode()).hexdigest(),
            "observed_at": self.observed_at.isoformat(), "valid_until": self.valid_until.isoformat(),
            "expiry_source": _EXPIRY_SOURCE, "strike_source": _STRIKE_SOURCE, "broker_fields": raw,
        }


@dataclass(frozen=True, slots=True)
class KotakContractResolver:
    """Immutable selected-option snapshot; construct through from_records.

    Attributes:
        contracts: Validated exact listings; no fallback or nearest-contract row.
        revision: Caller-bound source revision, never a synthetic refresh counter.
        observed_at: Aware inclusive start of snapshot validity.
        valid_until: Aware exclusive freshness deadline, not a session cutoff.
    """
    contracts: tuple[KotakListedContract, ...]
    revision: str
    observed_at: datetime
    valid_until: datetime

    @classmethod
    def from_records(cls, rows: list[dict], *, source: str, revision: str,
                     observed_at: datetime, valid_until: datetime) -> KotakContractResolver:
        """Validate and detach an explicitly supplied, versioned native row set.

        Args:
            rows: Nonempty native records for the selected NSE/BSE index options.
            source: Nonblank source identity; this method performs no download.
            revision: Exact nonblank source revision for compare-and-swap refresh.
            observed_at: Aware observation instant, retained in UTC.
            valid_until: Aware exclusive snapshot deadline after observed_at.

        Returns:
            An immutable resolver with exact venue/class/right/underlying,
            token, lot, strike, expiry and native-unit observations.

        Raises:
            BrokerReadResponseInvalid: A required value is missing, malformed,
                contradictory, outside the qualified profile, or duplicated.
        """
        source, revision = _text(source), _text(revision)
        observed_at, valid_until = _instant(observed_at), _instant(valid_until)
        if valid_until <= observed_at or type(rows) is not list or not rows:
            raise BrokerReadResponseInvalid from None
        detached = []
        for row in rows:
            if type(row) is not dict or any(type(k) is not str for k in row):
                raise BrokerReadResponseInvalid from None
            raw = {k: row[k] for k in _FIELDS if k in row}
            if any(type(v) is not str and type(v) is not int for v in raw.values()):
                raise BrokerReadResponseInvalid from None
            for value in raw.values():
                if type(value) is int and value.bit_length() > 213:
                    raise BrokerReadResponseInvalid from None
                if type(value) is str:
                    try:
                        value.encode("utf-8")
                    except UnicodeError:
                        raise BrokerReadResponseInvalid from None
            detached.append(raw)
        digest = hashlib.sha256(json.dumps(detached, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        contracts = []
        keys, tokens = set(), set()
        for raw in detached:
            try:
                segment = _text(raw["pExchSeg"])
                exchange = {"nse_fo": "NFO", "bse_fo": "BFO"}[segment]
                symbol, underlying = _text(raw["pTrdSymbol"]), _text(raw["pSymbolName"])
                if (exchange, underlying) not in _TICKS:
                    raise BrokerReadResponseInvalid from None
                token = _text(raw["pSymbol"])
                if not token.isascii() or not token.isdigit():
                    raise BrokerReadResponseInvalid from None
                _number(token, positive=True, whole=True)
                right, kind = _text(raw["pOptionType"]), _text(raw["pInstType"])
                if right not in {"CE", "PE"} or kind != _OPTION_CLASSES.get((segment, underlying)):
                    raise BrokerReadResponseInvalid from None
                expiry = _expiry(raw["lExpiryDate"], segment)
                if "pExpiryDate" in raw and _expiry(raw["pExpiryDate"], segment, sdk=True) != expiry:
                    raise BrokerReadResponseInvalid from None
                strike = _number(raw["dStrikePrice;"], positive=True)
                sign, digits, exponent = strike.as_tuple()
                # The pin's literal dStrikePrice; filter multiplies index points
                # by 100. Shift only this field, without ambient Decimal rounding.
                strike_text = format(Decimal((sign, digits, exponent - 2)), "f")
                if "." in strike_text:
                    strike_text = strike_text.rstrip("0").rstrip(".")
                lot = int(_number(raw["lLotSize"], positive=True, whole=True))
                _number(raw["dTickSize"], positive=True)
                _number(raw["lPrecision"], whole=True)
            except (KeyError, UnicodeError):
                raise BrokerReadResponseInvalid from None
            key, token_key = (exchange, symbol), (segment, token)
            if key in keys or token_key in tokens:
                raise BrokerReadResponseInvalid from None
            keys.add(key)
            tokens.add(token_key)
            contracts.append(KotakListedContract(symbol, exchange, token, segment, underlying, right, kind,
                expiry.isoformat(), strike_text, lot, json.dumps(raw, sort_keys=True, separators=(",", ":")),
                source, revision, digest, observed_at, valid_until))
        return cls(tuple(contracts), revision, observed_at, valid_until)

    def contains(self, symbol: str, exchange: str) -> bool:
        """Report exact snapshot membership without asserting current freshness.

        Args:
            symbol: Case-sensitive listed trading symbol, not an underlying.
            exchange: Exact FlintTrade venue code.

        Returns:
            Whether this snapshot contains the exact pair. Call resolve before
            consuming its contract; membership alone is not admission evidence.
        """
        return any(contract.symbol == symbol and contract.exchange == exchange for contract in self.contracts)

    def check_captured(self, contract: KotakListedContract, *, now: datetime) -> None:
        """Revalidate the retained listing, without selecting or replacing it.

        Args:
            contract: Actual immutable listing previously returned by this snapshot.
            now: Current aware invocation instant after all adapter waits.

        Raises:
            BrokerReadResponseInvalid: Foreign, stale, future or expiry-day capture.
        """
        now = _instant(now)
        if (not any(row is contract for row in self.contracts)
                or not self.observed_at <= now < self.valid_until
                or date.fromisoformat(contract.expiry) <= now.astimezone(_IST).date()):
            raise BrokerReadResponseInvalid from None

    def resolve(self, symbol: str, exchange: str, *, now: datetime) -> KotakListedContract:
        """Resolve one exact fresh listing, conservatively excluding its expiry date.

        Args:
            symbol: Exact case-sensitive trading symbol, never an underlying alias.
            exchange: Exact FlintTrade venue code.
            now: Aware current invocation/read instant supplied by the caller.

        Returns:
            The sole matching contract before its local expiry date.

        Raises:
            BrokerReadResponseInvalid: Evidence is stale, future, missing or
                ambiguous, or now reaches the expiry date. No qualified session
                cutoff exists here, so even a fresh expiry-day snapshot refuses.
        """
        now = _instant(now)
        if not self.observed_at <= now < self.valid_until:
            raise BrokerReadResponseInvalid from None
        matches = [c for c in self.contracts if c.symbol == symbol and c.exchange == exchange]
        # A date is not an independently qualified trading-session cutoff.
        # Snapshot freshness cannot authorise any part of the expiry date;
        # fail closed for that whole local date until session evidence exists.
        if len(matches) != 1 or date.fromisoformat(matches[0].expiry) <= now.astimezone(_IST).date():
            raise BrokerReadResponseInvalid from None
        return matches[0]
