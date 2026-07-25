"""Flask blueprint for FlintTrade analysis endpoints.

Provides 8 endpoints under /api/v1/ for the analysis tools:
    - POST /api/v1/gex
    - POST /api/v1/volsurface
    - POST /api/v1/ivsmile
    - POST /api/v1/straddlepnl
    - POST /api/v1/oiprofile
    - POST /api/v1/maxpain
    - GET  /api/v1/rrg/sectors
    - GET  /api/v1/screener/fii-dii

All endpoints:
1. Extract params from the JSON request body (or query string for GET).
2. Attempt to get live data from the BrokerRegistry (if connected).
3. Fall back to sample/synthetic data when no broker is connected (dev mode).
4. Call the relevant screener calculation function.
5. Return the result as JSON.

The BrokerRegistry is retrieved from ``current_app.config["REGISTRY"]`` which
is set up by ``create_flask_app()`` in packages/core/core/src/app.py.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from . import broker_registry_reads as broker_reads
from .gex import calculate_gex
from .iv_smile import calculate_iv_smile
from .lot_sizes import FALLBACK_LOT_SIZES, LotSizeResolver
from .oi_analysis import OIAnalysis
from .oi_profile import calculate_oi_profile
from .option_chain import LOT_SIZES, OptionChainSnapshot, StrikeData
from .rrg import (
    BENCHMARK_EXCHANGE,
    BENCHMARK_SYMBOL,
    NIFTY_SECTORS,
    SECTOR_EXCHANGE,
    _Series,
    build_sector_rrg,
    classify_quadrant,
    compute_rrg,
)
from .straddle_pnl import simulate_straddle_pnl
from .vol_surface import calculate_vol_surface

logger = logging.getLogger("flinttrade.screener.analysis_routes")

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/v1")

_MAX_CHAIN_ROWS = 10_000
_MAX_MARKET_VALUE = 1_000_000_000.0
_MAX_OPEN_INTEREST = 10_000_000_000
_MAX_OI_CHANGE = 10_000_000_000
_MAX_LOT_SIZE = 1_000_000
_MAX_IV_PERCENT = 10_000.0
_MAX_GAMMA = 1_000.0
_MAX_ABS_GREEK = 1_000_000_000.0
_MAX_OPTION_DTE_DAYS = 3_660
_MAX_VOL_SURFACE_EXPIRIES = 12


# ---------------------------------------------------------------------------
# Expiry param normalisation
#
# The terminal sends `expiry_date` / `expiry_dates`; these handlers historically
# read `expiry` / `expiries`. Accept all variants so a user-selected expiry is
# never silently dropped (which made every OI/GEX/IV panel fall back to a
# hardcoded expiry — see feature audit H7).
# ---------------------------------------------------------------------------


def _body_expiry(body: dict[str, Any], default: str) -> str:
    """Return a single expiry from the request body, accepting any key variant."""
    _validate_expiry_fields(body)
    for key in ("expiry", "expiry_date"):
        if key in body:
            return body[key].strip()
    for key in ("expiry_dates", "expiries"):
        if key in body:
            return body[key][0].strip()
    return default


def _body_expiries(body: dict[str, Any], default: list[str]) -> list[str]:
    """Return a list of expiries from the request body, accepting any key variant."""
    _validate_expiry_fields(body)
    for key in ("expiries", "expiry_dates"):
        if key in body:
            return [value.strip() for value in body[key]]
    for key in ("expiry", "expiry_date"):
        if key in body:
            return [body[key].strip()]
    return default


def _validate_expiry_fields(body: dict[str, Any]) -> None:
    for key in ("expiry", "expiry_date"):
        if key in body and not isinstance(body[key], str):
            raise ValueError(f"{key} must be a string")
    for key in ("expiries", "expiry_dates"):
        if key not in body:
            continue
        values = body[key]
        if not isinstance(values, list) or not values:
            raise ValueError(f"{key} must be a non-empty list of strings")
        if any(not isinstance(value, str) for value in values):
            raise ValueError(f"{key} must contain only strings")


_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _authoritative_expiry_date(expiry: Any) -> date | None:
    """Parse a supported expiry without conflating failure with expiry day."""
    if not isinstance(expiry, str):
        return None

    value = expiry.strip()
    iso = _ISO_DATE_RE.fullmatch(value)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except (ValueError, TypeError):
            return None

    from .symbol_converter import parse_expiry_date  # noqa: PLC0415

    cleaned = value.replace("-", "").replace(" ", "").upper()
    try:
        return parse_expiry_date(cleaned)
    except (ValueError, TypeError):
        return None


def _authoritative_days_to_expiry(expiry: Any, *, today: date | None = None) -> int | None:
    """Return exact non-negative calendar DTE, or ``None`` on parse failure."""
    parsed = _authoritative_expiry_date(expiry)
    if parsed is None:
        return None
    return max(0, (parsed - (today or date.today())).days)


def _live_option_days_to_expiry(expiry: Any, *, today: date | None = None) -> int | None:
    """Return a bounded, strictly future DTE suitable for live option maths."""
    dte = _authoritative_days_to_expiry(expiry, today=today)
    return dte if dte is not None and 0 < dte <= _MAX_OPTION_DTE_DAYS else None


def _days_to_expiry(expiry: str) -> int:
    """Whole calendar days from today to an expiry (>= 0).

    Accepts the three forms seen in the wild: ISO ``YYYY-MM-DD`` (what the
    terminal's expiry API actually returns), the strict ``DDMMMYY`` form, and
    the dashed ``DD-MMM-YY`` form. Returns 0 when the expiry cannot be parsed,
    so callers degrade gracefully rather than raising. Consumers that derive
    time-decay greeks (the terminal's Greeks Matrix widget, under both its grid
    and surface projections) need a real time-to-expiry — a hardcoded 0
    collapses gamma/theta/vega to zero.
    """
    dte = _authoritative_days_to_expiry(expiry)
    return dte if dte is not None else 0


# ---------------------------------------------------------------------------
# Registry access helper
# ---------------------------------------------------------------------------


def _get_registry() -> Any:
    """Return the BrokerRegistry from the current Flask app config.

    Returns:
        BrokerRegistry instance, or None if not configured.
    """
    return current_app.config.get("REGISTRY")


_INDEX_UNDERLYING_EXCHANGES = {
    "NIFTY": "NSE_INDEX",
    "BANKNIFTY": "NSE_INDEX",
    "FINNIFTY": "NSE_INDEX",
    "MIDCPNIFTY": "NSE_INDEX",
    "NIFTYNXT50": "NSE_INDEX",
    "SENSEX": "BSE_INDEX",
    "BANKEX": "BSE_INDEX",
    "SENSEX50": "BSE_INDEX",
}


def _option_chain_underlying_exchange(symbol: str, exchange: str) -> str:
    """Translate an option venue into the underlying instrument's exchange."""
    index_exchange = _INDEX_UNDERLYING_EXCHANGES.get(symbol.strip().upper())
    normalised = exchange.strip().upper()
    if index_exchange is not None:
        allowed = (
            {"NFO", "NSE", "NSE_INDEX"}
            if index_exchange == "NSE_INDEX"
            else {"BFO", "BSE", "BSE_INDEX"}
        )
        if normalised not in allowed:
            raise ValueError(
                f"exchange {exchange!r} is incompatible with index symbol {symbol!r}"
            )
        return index_exchange
    return {"NFO": "NSE", "BFO": "BSE"}.get(normalised, normalised)


def _generated_future_expiries(*day_offsets: int) -> list[str]:
    """Build stable ISO sample-expiry labels relative to the request date."""
    today = date.today()
    return [(today + timedelta(days=offset)).isoformat() for offset in day_offsets]


def _model_dump_preserving_unset(value: Any) -> Any:
    """Dump a Pydantic model without materialising defaults as observations."""
    try:
        return value.model_dump(exclude_unset=True)
    except TypeError:
        return value.model_dump()


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _request_json_object() -> dict[str, Any]:
    """Return the JSON request object, rejecting arrays, scalars, and JSON null."""
    body = request.get_json(silent=True)
    if body is None:
        if request.is_json and request.get_data(cache=True).strip():
            raise ValueError("JSON body must be an object")
        return {}
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def _request_identity_string(
    body: dict[str, Any],
    key: str,
    default: str,
    *,
    allow_blank: bool = False,
) -> str:
    """Read a request identity without coercing arrays, objects, or numbers."""
    if key not in body:
        return default
    value = body[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    value = value.strip()
    if not value and not allow_blank:
        raise ValueError(f"{key} must not be blank")
    return value


def _option_request(default_expiry: str) -> tuple[dict[str, Any], str, str, str]:
    body = _request_json_object()
    symbol = _request_identity_string(body, "symbol", "NIFTY")
    exchange = _request_identity_string(body, "exchange", "NFO")
    _option_chain_underlying_exchange(symbol, exchange)
    expiry = _body_expiry(body, default_expiry)
    return body, symbol, exchange, expiry


def _request_number(
    body: dict[str, Any],
    key: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    """Parse a finite request number and enforce an optional domain."""
    number = _finite_number(body.get(key, default))
    if number is None:
        raise ValueError(f"{key} must be a finite number")
    if minimum is not None and (
        number < minimum or (not minimum_inclusive and number == minimum)
    ):
        operator = "at least" if minimum_inclusive else "greater than"
        raise ValueError(f"{key} must be {operator} {minimum:g}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{key} must be at most {maximum:g}")
    return number


def _request_integer(
    body: dict[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int = 1000,
) -> int:
    """Parse a bounded integer request field without accepting booleans/NaN."""
    number = _request_number(body, key, float(default), minimum=float(minimum), maximum=float(maximum))
    if not number.is_integer():
        raise ValueError(f"{key} must be an integer")
    return int(number)


def _parse_adjustment_legs(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the Straddle P&L widget's optional ``adjustments`` legs.

    Each leg is ``{strike, type, action, premium, lots}``; the list is capped
    at 10 legs and every field is validated so a malformed body raises
    ``ValueError`` (surfaced as a clean 400) rather than a 500.
    """
    raw = body.get("adjustments")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("adjustments must be a list of option legs")
    if len(raw) > 10:
        raise ValueError("adjustments supports at most 10 legs")
    legs: list[dict[str, Any]] = []
    for index, candidate in enumerate(raw):
        if not isinstance(candidate, dict):
            raise ValueError(f"adjustments[{index}] must be an object")
        leg_strike = _finite_number(candidate.get("strike"))
        if leg_strike is None or leg_strike <= 0 or leg_strike > _MAX_MARKET_VALUE:
            raise ValueError(f"adjustments[{index}].strike must be a positive market value")
        leg_premium = _finite_number(candidate.get("premium"))
        if leg_premium is None or leg_premium < 0 or leg_premium > _MAX_MARKET_VALUE:
            raise ValueError(f"adjustments[{index}].premium must be a non-negative market value")
        leg_type = candidate.get("type")
        if leg_type not in ("CE", "PE"):
            raise ValueError(f"adjustments[{index}].type must be CE or PE")
        leg_action = candidate.get("action")
        if leg_action not in ("BUY", "SELL"):
            raise ValueError(f"adjustments[{index}].action must be BUY or SELL")
        leg_lots = _finite_number(candidate.get("lots", 1))
        if leg_lots is None or not float(leg_lots).is_integer() or not 1 <= leg_lots <= 100:
            raise ValueError(f"adjustments[{index}].lots must be an integer between 1 and 100")
        legs.append({
            "strike": float(leg_strike),
            "type": leg_type,
            "action": leg_action,
            "premium": float(leg_premium),
            "lots": int(leg_lots),
        })
    return legs


def _normalise_identity(value: Any) -> str | None:
    """Conservatively normalise a supplied chain identity token."""
    if value is None:
        return None
    if not isinstance(value, str):
        return ""
    stripped = value.strip()
    if not stripped:
        return None
    return re.sub(r"[\s_-]+", "", stripped.upper())


def _normalise_expiry_identity(value: Any) -> str | None:
    if value is None:
        return None
    parsed = _authoritative_expiry_date(value)
    if parsed is not None:
        return parsed.isoformat()
    return _normalise_identity(value)


def _chain_identity_matches(
    chain: dict[str, Any],
    symbol: str,
    exchange: str,
    expiry: str | None,
) -> bool:
    """Reject any explicit response identity that contradicts the request."""
    expected_symbol = _normalise_identity(symbol)
    for key in ("underlying", "symbol"):
        if key not in chain:
            continue
        supplied = _normalise_identity(chain.get(key))
        if supplied != expected_symbol:
            return False

    allowed_exchanges = {
        value
        for value in (
            _normalise_identity(exchange),
            _normalise_identity(_option_chain_underlying_exchange(symbol, exchange)),
        )
        if value
    }
    for key in ("exchange", "underlying_exchange"):
        if key not in chain:
            continue
        supplied = _normalise_identity(chain.get(key))
        if supplied not in allowed_exchanges:
            return False

    expected_expiry = _normalise_expiry_identity(expiry)
    if expected_expiry is not None:
        for key in ("expiry", "expiry_date"):
            if key not in chain:
                continue
            supplied = _normalise_expiry_identity(chain.get(key))
            if supplied != expected_expiry:
                return False
    return True


def _chain_has_requested_expiry_identity(
    chain: dict[str, Any],
    expiry: str | None,
) -> bool:
    """Require at least one explicit response expiry matching the request."""
    expected_expiry = _normalise_expiry_identity(expiry)
    if expected_expiry is None:
        return False
    observed = False
    for key in ("expiry", "expiry_date"):
        if key not in chain:
            continue
        observed = True
        if _normalise_expiry_identity(chain.get(key)) != expected_expiry:
            return False
    return observed


def _row_strike(row: dict[str, Any]) -> float | None:
    strike = _finite_number(row.get("strike_price", row.get("strike")))
    return strike if strike is not None and 0 < strike <= _MAX_MARKET_VALUE else None


def _row_open_interest(row: dict[str, Any], prefix: str) -> int | None:
    key = f"{prefix}_oi"
    if key not in row:
        return None
    oi = _finite_number(row[key])
    if oi is None or oi < 0 or oi > _MAX_OPEN_INTEREST or not oi.is_integer():
        return None
    return int(oi)


def _row_has_authoritative_oi(row: dict[str, Any]) -> bool:
    return _row_open_interest(row, "ce") is not None and _row_open_interest(row, "pe") is not None


def _normalise_live_option_chain(chain: Any) -> dict[str, Any] | None:
    """Normalise a native, bridge, or legacy option-chain response."""
    if hasattr(chain, "model_dump"):
        chain = _model_dump_preserving_unset(chain)
    elif not isinstance(chain, dict) and hasattr(chain, "strikes"):
        payload = {
            "spot_price": getattr(chain, "spot_price", None),
            "strikes": getattr(chain, "strikes", []),
        }
        for key in ("underlying", "symbol", "exchange", "underlying_exchange", "expiry", "expiry_date"):
            if hasattr(chain, key):
                payload[key] = getattr(chain, key)
        chain = payload
    if not isinstance(chain, dict):
        return None
    raw_strikes = chain.get("strikes") or chain.get("chain") or []
    if not isinstance(raw_strikes, list) or not raw_strikes:
        return None
    strikes: list[dict[str, Any]] = []
    for raw_row in raw_strikes:
        row = _model_dump_preserving_unset(raw_row) if hasattr(raw_row, "model_dump") else raw_row
        if not isinstance(row, dict):
            return None
        strikes.append(row)
    payload = dict(chain)
    payload["strikes"] = strikes
    return payload


def _chain_rows(chain: dict[str, Any]) -> list[dict[str, Any]] | None:
    rows = chain.get("strikes")
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > _MAX_CHAIN_ROWS
        or not all(isinstance(row, dict) for row in rows)
    ):
        return None
    return rows


def _rows_have_unique_strikes(rows: list[dict[str, Any]]) -> bool:
    strikes = [_row_strike(row) for row in rows]
    return all(strike is not None for strike in strikes) and len(strikes) == len(set(strikes))


def _chain_has_complete_greeks(chain: dict[str, Any]) -> bool:
    """Return whether every source row has valid strikes and physical Greeks."""
    rows = _chain_rows(chain)
    return rows is not None and _rows_have_unique_strikes(rows) and all(
        _row_has_valid_strike(row)
        and _leg_has_complete_greeks(row, "ce")
        and _leg_has_complete_greeks(row, "pe")
        for row in rows
    )


def _row_has_valid_strike(row: dict[str, Any]) -> bool:
    return _row_strike(row) is not None


def _chain_has_valid_strike(chain: dict[str, Any]) -> bool:
    rows = _chain_rows(chain)
    return rows is not None and _rows_have_unique_strikes(rows)


def _chain_has_authoritative_snapshot_inputs(chain: dict[str, Any]) -> bool:
    return _authoritative_chain_spot(chain) is not None and _chain_has_valid_strike(chain)


def _chain_has_required_rows(
    chain: dict[str, Any],
    *,
    require_authoritative_oi: bool,
    require_complete_greeks: bool,
) -> bool:
    rows = _chain_rows(chain)
    return rows is not None and _rows_have_unique_strikes(rows) and all(
        _row_has_valid_strike(row)
        and (not require_authoritative_oi or _row_has_authoritative_oi(row))
        and (
            not require_complete_greeks
            or (_leg_has_complete_greeks(row, "ce") and _leg_has_complete_greeks(row, "pe"))
        )
        for row in rows
    )


def _live_option_chain(
    symbol: str,
    exchange: str,
    expiry: str | None = None,
    *,
    require_authoritative_oi: bool = False,
    require_complete_greeks: bool = False,
) -> dict[str, Any] | None:
    """Fetch a REAL option chain via an existing configured broker read path.

    The OpenAlgo client's ``OptionChainStrike`` fields (strike_price, ce/pe ltp,
    oi, iv, greeks) match the keys the snapshot builder reads, so a ``model_dump``
    per strike is a direct fit. The legacy registry may also expose a compatible
    ``get_option_chain(account_id, params)`` method; use it only when present.
    Returns ``None`` when no live source is configured or the fetch fails — the
    caller then falls back to honest sample data.
    """
    underlying_exchange = _option_chain_underlying_exchange(symbol, exchange)
    candidates: list[dict[str, Any]] = []
    registry = _get_registry()
    native_adapters = current_app.config.get("NATIVE_ADAPTERS") or {}
    connected_sessions = getattr(registry, "list_connected_adapter_sessions", None)
    if registry is not None and callable(connected_sessions):
        for adapter_id, _account_id, session in connected_sessions():
            adapter = native_adapters.get(adapter_id)
            reader = getattr(adapter, "option_chain", None)
            if not callable(reader):
                continue
            try:
                chain = asyncio.run(
                    reader(
                        session,
                        {
                            "symbol": symbol,
                            "underlying": symbol,
                            "exchange": underlying_exchange,
                            "expiry": expiry or "",
                        },
                    )
                )
                if (normalised := _normalise_live_option_chain(chain)) is not None:
                    candidates.append(normalised)
            except Exception as exc:  # noqa: BLE001 - try the next connected read source
                logger.warning(
                    "Live option chain via native %s failed for %s %s: %s",
                    adapter_id,
                    symbol,
                    underlying_exchange,
                    exc,
                )

    if registry and registry.is_connected():
        try:
            if (normalised := _normalise_live_option_chain(
                broker_reads.get_option_chain(
                    registry,
                    symbol=symbol,
                    exchange=underlying_exchange,
                    expiry=expiry,
                )
            )) is not None:
                candidates.append(normalised)
        except Exception as exc:  # noqa: BLE001 - try the bridge/sample path
            logger.warning(
                "Live option chain via registry failed for %s %s: %s",
                symbol,
                underlying_exchange,
                exc,
            )

    client = current_app.config.get("OPENALGO_CLIENT")
    if client is not None:
        try:

            # One-owner-loop rule: the shared client's pooled connections are
            # loop-affine; run on its owner loop, never a fresh asyncio.run().
            from flinttrade_core.openalgo_client import client_call_sync  # noqa: PLC0415

            chain = client_call_sync(
                client,
                client.option_chain(symbol, underlying_exchange, expiry or ""),
            )
            if (
                (normalised := _normalise_live_option_chain(chain)) is not None
                and _chain_has_requested_expiry_identity(normalised, expiry)
            ):
                candidates.append(normalised)
        except Exception as exc:  # noqa: BLE001 - any failure degrades to the registry/sample path
            logger.warning(
                "Live option chain via OpenAlgo failed for %s %s: %s",
                symbol,
                underlying_exchange,
                exc,
            )

    candidates = [
        chain
        for chain in candidates
        if _chain_identity_matches(chain, symbol, exchange, expiry)
    ]
    preferred = next(
        (
            chain
            for chain in candidates
            if _authoritative_chain_spot(chain) is not None
            and _chain_has_required_rows(
                chain,
                require_authoritative_oi=require_authoritative_oi,
                require_complete_greeks=require_complete_greeks,
            )
        ),
        None,
    )
    if require_authoritative_oi or require_complete_greeks:
        return preferred
    return preferred or next(
        (chain for chain in candidates if _chain_has_authoritative_snapshot_inputs(chain)),
        None,
    )


def _authoritative_chain_spot(chain_data: dict[str, Any]) -> float | None:
    """Return an explicit finite positive underlying price, never a default."""
    for key in ("spot", "spot_price", "underlying_spot_price", "underlying_ltp"):
        raw = chain_data.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            spot = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(spot) and 0 < spot <= _MAX_MARKET_VALUE:
            return spot
    return None


# ---------------------------------------------------------------------------
# Sample data helpers (dev/fallback when no broker connected)
# ---------------------------------------------------------------------------


def _make_sample_strikes(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
) -> list[StrikeData]:
    """Generate synthetic strike data for dev/fallback mode.

    Args:
        spot: Center spot price.
        step: Strike step size.
        count: Number of strikes each side of ATM.

    Returns:
        List of StrikeData objects around the given spot.
    """
    safe_spot = _finite_number(spot)
    if safe_spot is None or not 0 < safe_spot <= _MAX_MARKET_VALUE:
        safe_spot = 1.0
    safe_count = max(0, min(int(count), 1000))
    safe_step = _sample_strike_step(safe_spot, step, safe_count)
    strikes: list[StrikeData] = []
    for i in range(-safe_count, safe_count + 1):
        k = safe_spot + i * safe_step
        dist = abs(i)
        ce_oi = max(1000, 50000 - dist * 4000)
        pe_oi = max(1000, 40000 - dist * 3500)
        ce_ltp = max(1.0, 200 - max(0, i) * 15)
        pe_ltp = max(1.0, 200 + min(0, i) * 15)
        iv = 15.0 + dist * 0.6
        gamma = max(0.0001, 0.005 - dist * 0.0003)
        strikes.append(StrikeData(
            strike_price=k,
            ce_ltp=ce_ltp,
            ce_oi=ce_oi,
            ce_volume=ce_oi // 10,
            ce_iv=iv,
            ce_delta=max(0.05, 0.5 - i * 0.05),
            ce_gamma=gamma,
            ce_theta=-5.0 - dist * 0.3,
            ce_vega=10.0 - dist * 0.4,
            pe_ltp=pe_ltp,
            pe_oi=pe_oi,
            pe_volume=pe_oi // 10,
            pe_iv=iv + 0.5,
            pe_delta=-max(0.05, 0.5 + i * 0.05),
            pe_gamma=gamma,
            pe_theta=-5.0 - dist * 0.3,
            pe_vega=10.0 - dist * 0.4,
        ))
    return strikes


def _sample_strike_step(spot: float, requested_step: float, count: int) -> float:
    """Choose a positive regular step that cannot cross zero on the lower wing."""
    step = _finite_number(requested_step)
    if step is None or step <= 0:
        step = max(spot * 0.01, 0.01)
    if count <= 0:
        return step
    return min(step, spot / (count + 1))


def _make_sample_snapshot(
    symbol: str = "NIFTY",
    exchange: str = "NFO",
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
) -> OptionChainSnapshot:
    """Create a synthetic OptionChainSnapshot for dev/fallback mode.

    Args:
        symbol: Underlying symbol.
        exchange: Exchange code.
        spot: Spot price.
        step: Strike step.
        count: Strikes per side.

    Returns:
        OptionChainSnapshot with synthetic data.
    """
    strikes = _make_sample_strikes(spot=spot, step=step, count=count)
    return OptionChainSnapshot(
        underlying=symbol,
        exchange=exchange,
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


def _make_sample_candles(
    spot: float = 24000.0,
    n: int = 48,
    base_ts: int = 1711900000,
    candle_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Generate synthetic futures OHLCV candles for dev/fallback mode.

    Args:
        spot: Starting spot price.
        n: Number of candles.
        base_ts: Base Unix timestamp.
        candle_seconds: Duration per candle in seconds.

    Returns:
        List of OHLCV candle dicts.
    """
    import math
    candles = []
    price = spot
    for i in range(n):
        # Sinusoidal price movement for realistic shape
        move = 50 * math.sin(i * 0.3)
        open_p = price
        close_p = price + move
        high_p = max(open_p, close_p) + abs(move) * 0.2
        low_p = min(open_p, close_p) - abs(move) * 0.2
        candles.append({
            "time": base_ts + i * candle_seconds,
            "open": round(open_p, 2),
            "high": round(high_p, 2),
            "low": round(low_p, 2),
            "close": round(close_p, 2),
            "volume": 10000 + i * 500,
        })
        price = close_p
    return candles


def _dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert dataclass instances to dicts for JSON serialization.

    Args:
        obj: A dataclass instance, list, or primitive value.

    Returns:
        JSON-serializable representation.
    """
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# GEX endpoint
# ---------------------------------------------------------------------------


def _chain_lot_size(chain_data: dict[str, Any] | None) -> int | None:
    if not chain_data:
        return None
    for key in ("lot_size", "lotsize"):
        if key not in chain_data:
            continue
        value = _finite_number(chain_data[key])
        if value is not None and 0 < value <= _MAX_LOT_SIZE and value.is_integer():
            return int(value)
        return None
    return None


def _resolve_gex_lot_size(
    symbol: str,
    exchange: str,
    chain_data: dict[str, Any] | None,
) -> int | None:
    """Resolve a GEX multiplier without inventing one for unknown symbols."""
    if chain_data is not None and any(key in chain_data for key in ("lot_size", "lotsize")):
        return _chain_lot_size(chain_data)

    normalised_symbol = symbol.strip().upper()
    client = current_app.config.get("OPENALGO_CLIENT")
    if client is None:
        return None
    resolution = LotSizeResolver(client).resolve(normalised_symbol, exchange)
    return (
        resolution.lot_size
        if resolution.source == "live" and 0 < resolution.lot_size <= _MAX_LOT_SIZE
        else None
    )


@analysis_bp.route("/gex", methods=["POST"])
def gex_endpoint() -> Any:
    """Gamma Exposure (GEX) calculation.

    Request JSON:
        symbol (str): Underlying symbol (e.g. 'NIFTY').
        exchange (str): Exchange code (e.g. 'NFO').
        expiry (str): Expiry label (e.g. '26MAR26').

    Returns:
        JSON with GEX result or error.
    """
    try:
        _body, symbol, exchange, expiry = _option_request("")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None

    # Live data via the OpenAlgo bridge (the functional adapter).
    chain_data = None
    authoritative_dte = _live_option_days_to_expiry(expiry)
    if authoritative_dte is not None:
        chain_data = _live_option_chain(
            symbol,
            exchange,
            expiry,
            require_authoritative_oi=True,
            require_complete_greeks=True,
        )
    chain_spot = _authoritative_chain_spot(chain_data) if chain_data else None
    if chain_data and chain_spot is not None and _chain_has_complete_greeks(chain_data):
        spot = chain_spot
        candidate = _snapshot_from_registry_data(
            chain_data,
            symbol,
            exchange,
            spot,
            require_authoritative_oi=True,
            require_complete_greeks=True,
        )
        snapshot = candidate if candidate.strikes else None

    authoritative_lot_size = _resolve_gex_lot_size(symbol, exchange, chain_data)
    lot_size = authoritative_lot_size
    used_sample = snapshot is None or authoritative_lot_size is None
    if lot_size is None:
        lot_size = FALLBACK_LOT_SIZES.get(symbol.strip().upper())
        if lot_size is not None:
            if snapshot is None:
                snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
            logger.info("GEX: using a sample-only fallback lot size for %s %s", symbol, exchange)
        else:
            snapshot = OptionChainSnapshot(
                underlying=symbol,
                exchange=exchange,
                spot_price=spot,
                atm_strike=spot,
                strikes=[],
            )
            logger.warning("GEX: no authoritative lot size for %s %s", symbol, exchange)
    elif snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("GEX: using sample data for %s %s", symbol, exchange)

    result = calculate_gex(snapshot, spot=spot, lot_size=lot_size or 0)

    # Shape ``data`` to the terminal's GEXData contract. The raw dataclass used
    # strike_price / total_net_gex and lacked atm_strike / gamma_flip_strike /
    # dealer_zone, so the widget read undefined for those.
    frontend_strikes = [
        {
            "strike": gs.strike_price,
            "call_gex": gs.call_gex,
            "put_gex": gs.put_gex,
            "net_gex": gs.net_gex,
            "call_oi": gs.call_oi,
            "put_oi": gs.put_oi,
        }
        for gs in result.strikes
    ]
    atm_strike = (
        min(result.strikes, key=lambda s: abs(s.strike_price - spot)).strike_price
        if result.strikes
        else spot
    )
    # A true gamma-flip level requires repricing the whole chain over a spot
    # sweep. A per-strike sign change at one fixed spot is not that quantity.
    gamma_flip_strike: float | None = None
    dealer_zone = (
        "Long Gamma"
        if result.total_net_gex > 0
        else "Short Gamma"
        if result.total_net_gex < 0
        else "Neutral Gamma"
    )

    gex_data = {
        "available": lot_size is not None and bool(snapshot.strikes),
        "underlying": symbol,
        "spot_price": spot,
        "atm_strike": atm_strike,
        "strikes": frontend_strikes,
        "gamma_flip_strike": gamma_flip_strike,
        "dealer_zone": dealer_zone,
        "total_call_gex": result.total_call_gex,
        "total_put_gex": result.total_put_gex,
        "net_gex": result.total_net_gex,
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "lot_size": lot_size,
        "data": gex_data,
        "is_sample_data": used_sample,
    })


@analysis_bp.route("/gammadensity", methods=["POST"])
def gamma_density_endpoint() -> Any:
    """Gamma Density surface (DP2).

    Per-strike Γ×OI density at two horizons (intraday, to-expiry) plus the
    convexity-zone expected-move bands. Reuses the same option-chain snapshot
    the GEX endpoint builds — no extra broker fetch.

    Request JSON:
        symbol (str): Underlying symbol (e.g. 'NIFTY').
        exchange (str): Exchange code (e.g. 'NFO').
        expiry (str): Expiry label (ISO ``YYYY-MM-DD`` or ``DDMMMYY``).
        interest_rate (float): Optional annualised risk-free rate, percent.

    Returns:
        JSON with the gamma density payload or sample fallback.
    """
    from .gamma_density import calculate_gamma_density  # noqa: PLC0415

    try:
        body, symbol, exchange, expiry = _option_request(_generated_future_expiries(7)[0])
        expiry_supplied = any(
            key in body for key in ("expiry", "expiry_date", "expiry_dates", "expiries")
        )
        interest_rate_pct = _request_number(
            body,
            "interest_rate",
            0.0,
            minimum=-100.0,
            maximum=100.0,
        )
        authoritative_dte = _live_option_days_to_expiry(expiry)
        if authoritative_dte is None:
            raise ValueError("expiry must be a valid bounded future option date")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None
    chain_data = None
    if expiry_supplied:
        chain_data = _live_option_chain(
            symbol,
            exchange,
            expiry,
            require_authoritative_oi=True,
            require_complete_greeks=True,
        )
    chain_spot = _authoritative_chain_spot(chain_data) if chain_data else None
    if (
        chain_data
        and chain_spot is not None
        and _chain_has_complete_greeks(chain_data)
    ):
        spot = chain_spot
        candidate = _snapshot_from_registry_data(
            chain_data,
            symbol,
            exchange,
            spot,
            require_authoritative_oi=True,
            require_complete_greeks=True,
        )
        snapshot = candidate if candidate.strikes else None

    used_sample = snapshot is None
    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("Gamma density: using sample data for %s %s", symbol, exchange)

    dte_days = float(authoritative_dte)

    rate = interest_rate_pct / 100.0

    result = calculate_gamma_density(snapshot, spot=spot, dte_days=dte_days, risk_free_rate=rate)

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "data": result.to_dict(),
        "is_sample_data": used_sample,
    })


@analysis_bp.route("/screener/arbitrage", methods=["POST"])
def arbitrage_scan_endpoint() -> Any:
    """Cash-future / cross-exchange arbitrage scanner (DP3).

    The caller supplies observed prices (from the terminal's live quotes); with
    no rows the endpoint returns a clearly-flagged sample scan.

    Request JSON:
        cash_future (list): rows of ``{underlying, spot, future_price,
            days_to_expiry, exchange?}``.
        cross_exchange (list): rows of ``{symbol, exchange_a, price_a,
            exchange_b, price_b}``.
        risk_free_rate (float): Annualised funding rate as a decimal (0.07).
        edge_threshold_pct (float): Minimum annualised edge over funding to flag.

    Returns:
        JSON with the ranked scan, or the sample scan when no rows are supplied.
    """
    from .cash_future_arbitrage import (  # noqa: PLC0415
        make_sample_arbitrage_scan,
        scan_arbitrage,
    )

    try:
        body = _request_json_object()
        cash_future_rows = body.get("cash_future") or []
        cross_exchange_rows = body.get("cross_exchange") or []
        if not isinstance(cash_future_rows, list) or not isinstance(cross_exchange_rows, list):
            raise ValueError("arbitrage rows must be lists")
        risk_free_rate = _request_number(
            body,
            "risk_free_rate",
            0.07,
            minimum=-1.0,
            maximum=10.0,
        )
        edge_threshold_pct = _request_number(
            body,
            "edge_threshold_pct",
            1.0,
            minimum=0.0,
            maximum=1_000_000.0,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    is_sample_data = not (cash_future_rows or cross_exchange_rows)
    if is_sample_data:
        result = make_sample_arbitrage_scan()
    else:
        result = scan_arbitrage(
            cash_future_rows=cash_future_rows,
            cross_exchange_rows=cross_exchange_rows,
            risk_free_rate=risk_free_rate,
            edge_threshold_pct=edge_threshold_pct,
        )

    return jsonify({
        "status": "success",
        "data": {
            "is_sample_data": is_sample_data,
            "scan": result.to_dict(),
        },
    })


@analysis_bp.route("/candlestick-patterns", methods=["POST"])
def candlestick_patterns_endpoint() -> Any:
    """Candlestick pattern detection (W4).

    Scans a supplied OHLCV bar series for the six candlestick patterns
    FlintTrade backtests (doji, hammer/shooting-star, engulfing, morning/evening
    star, three soldiers/crows) and returns markers for a chart overlay. With no
    bars a sample scan is returned.

    Request JSON:
        bars (list): ordered ``[{open, high, low, close, time?}, ...]``.

    Returns:
        JSON with the detected pattern markers or a sample scan.
    """
    from .candlestick_patterns import (  # noqa: PLC0415
        detect_patterns,
        make_sample_pattern_scan,
    )

    try:
        body = _request_json_object()
        bars = body.get("bars") or []
        if not isinstance(bars, list):
            raise ValueError("bars must be a list")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    is_sample_data = not bars
    result = make_sample_pattern_scan() if is_sample_data else detect_patterns(bars)

    return jsonify({
        "status": "success",
        "data": {
            "is_sample_data": is_sample_data,
            "scan": result.to_dict(),
        },
    })


# ---------------------------------------------------------------------------
# Vol Surface endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/volsurface", methods=["POST"])
def vol_surface_endpoint() -> Any:
    """Implied Volatility surface calculation.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiries (list[str]): List of expiry labels.
        strike_count (int): Max strikes in surface grid (default 20).

    Returns:
        JSON with 3-D vol surface data or error.
    """
    try:
        body = _request_json_object()
        symbol = _request_identity_string(body, "symbol", "NIFTY")
        exchange = _request_identity_string(body, "exchange", "NFO")
        _option_chain_underlying_exchange(symbol, exchange)
        expiries_supplied = any(
            key in body for key in ("expiry", "expiry_date", "expiry_dates", "expiries")
        )
        expiries = _body_expiries(body, _generated_future_expiries(7, 30))
        if len(expiries) > _MAX_VOL_SURFACE_EXPIRIES:
            raise ValueError(f"expiries must contain at most {_MAX_VOL_SURFACE_EXPIRIES} values")
        strike_count = _request_integer(body, "strike_count", 20, minimum=1)
        as_of = date.today()
        expiry_dtes: list[tuple[str, int]] = []
        for expiry in expiries:
            dte = _live_option_days_to_expiry(expiry, today=as_of)
            if dte is None:
                raise ValueError(f"Option expiry must be a valid future date: {expiry!r}")
            expiry_dtes.append((expiry, dte))
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    spot = 24000.0

    chains_by_expiry: dict[str, dict] = {}

    if expiries_supplied:
        try:
            for expiry, dte in expiry_dtes:
                chain_data = _live_option_chain(symbol, exchange, expiry)
                if not chain_data:
                    raise ValueError("No live option-chain data returned")
                chain_spot = _authoritative_chain_spot(chain_data)
                if chain_spot is None:
                    raise ValueError("Live option-chain data has no authoritative spot price")
                if not _chain_has_valid_strike(chain_data):
                    raise ValueError("Live option-chain data has no valid strike")
                spot = chain_spot
                formatted = _chain_to_vol_surface_format(
                    chain_data,
                    spot,
                    days_to_expiry=dte,
                )
                if not formatted["strikes"]:
                    raise ValueError("Live option-chain data has no usable volatility rows")
                chains_by_expiry[expiry] = formatted
        except Exception as exc:
            logger.warning("Live vol surface data unavailable, using sample: %s", exc)
            chains_by_expiry = {}

    used_sample = not chains_by_expiry
    if not chains_by_expiry:
        chains_by_expiry = _make_sample_chains_by_expiry(spot=spot, expiries=expiries)
        logger.info("VolSurface: using sample data for %s %s", symbol, exchange)

    result = calculate_vol_surface(chains_by_expiry, spot=spot, strike_count=strike_count)

    # Shape ``data`` to the terminal's VolSurfaceData contract (the widget read
    # undefined for expiries/days_to_expiry/atm_strike from the raw dataclass,
    # whose fields are expiry_labels/expiries_dte/atm_ivs).
    atm_strike = min(result.strikes, key=lambda s: abs(s - spot)) if result.strikes else spot
    vol_surface_data = {
        "underlying": symbol,
        "spot_price": spot,
        "strikes": result.strikes,
        "expiries": result.expiry_labels,
        "days_to_expiry": result.expiries_dte,
        "iv_matrix": result.iv_matrix,
        "atm_strike": atm_strike,
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "spot": spot,
        "is_sample_data": used_sample,
        "data": vol_surface_data,
    })


# ---------------------------------------------------------------------------
# IV Smile endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/ivsmile", methods=["POST"])
def iv_smile_endpoint() -> Any:
    """IV Smile curve extraction.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.

    Returns:
        JSON with IV smile data or error.
    """
    try:
        _body, symbol, exchange, expiry = _option_request("26MAR26")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    sample_spot = 24000.0
    spot = 0.0
    snapshot: OptionChainSnapshot | None = None
    authoritative_dte = _live_option_days_to_expiry(expiry)

    chain_data = None
    if authoritative_dte is not None:
        chain_data = _live_option_chain(
            symbol,
            exchange,
            expiry,
            require_complete_greeks=True,
        )
    if chain_data is not None:
        live_spot = _authoritative_chain_spot(chain_data)
        if live_spot is not None:
            spot = live_spot
            candidate = _snapshot_from_registry_data(
                chain_data,
                symbol,
                exchange,
                spot,
                require_authoritative_oi=False,
                require_complete_greeks=True,
            )
            snapshot = candidate if candidate.strikes else None
        else:
            logger.warning("IVSmile: live chain for %s %s omitted an authoritative spot", symbol, exchange)

    used_sample = snapshot is None
    if snapshot is None:
        spot = sample_spot
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("IVSmile: using sample data for %s %s", symbol, exchange)

    result = calculate_iv_smile(snapshot, spot=spot, expiry_date=expiry)

    # Shape ``data`` to the terminal's IVSmileData contract: a single expiry's
    # flat dataclass becomes one entry in a ``curves`` array of per-strike points.
    # (The widget read `curves`/`points` and got undefined from the raw dataclass.)
    curve = {
        "expiry": result.expiry_date or expiry,
        "days_to_expiry": (
            authoritative_dte
            if not used_sample and authoritative_dte is not None
            else _days_to_expiry(result.expiry_date or expiry)
        ),
        # ``calculate_iv_smile`` retains the screener's historical percentage-
        # point representation. The terminal contract is decimal IV and
        # strike/spot moneyness, matching its typed sample data and maths.
        "atm_iv": round(result.atm_iv / 100.0, 6),
        "atm_strike": result.atm_strike,
        "skew_25delta": round(result.skew / 100.0, 6),
        "points": [
            {
                "strike": p.strike_price,
                "call_iv": round(p.call_iv / 100.0, 6),
                "put_iv": round(p.put_iv / 100.0, 6),
                "moneyness": round(p.strike_price / spot, 6) if spot > 0 else 0.0,
            }
            for p in result.points
        ],
    }
    iv_smile_data = {
        "underlying": symbol,
        "spot_price": spot,
        "curves": [curve],
        "is_sample_data": used_sample,
    }

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "is_sample_data": used_sample,
        "data": iv_smile_data,
    })


# ---------------------------------------------------------------------------
# Straddle P&L endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/straddlepnl", methods=["POST"])
def straddle_pnl_endpoint() -> Any:
    """Straddle P&L simulation with re-hedging.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.
        interval (str): Candle interval (e.g. '5m', '15m').
        adjustment_points (float): P&L drawdown triggering re-hedge.
        strike (float, optional): Straddle strike. Default: ATM.
        ce_premium (float, optional): CE premium. Default: synthetic.
        pe_premium (float, optional): PE premium. Default: synthetic.
        adjustments (list, optional): Extra option legs the widget lets the
            user add — each ``{strike, type, action, premium, lots}``. Folded
            into the payoff curve, break-evens, max loss, and echoed ``legs``.

    Returns:
        JSON with P&L series, adjustments, and summary stats.
    """
    try:
        body, symbol, exchange, expiry = _option_request(_generated_future_expiries(7)[0])
        if _live_option_days_to_expiry(expiry) is None:
            raise ValueError("expiry must be a valid strictly future option expiry")
        interval = _request_identity_string(body, "interval", "5m")
        adjustment_points = _request_number(
            body,
            "adjustment_points",
            50.0,
            minimum=0.0,
            maximum=_MAX_MARKET_VALUE,
        )
        strike = _request_number(body, "strike", 24000.0, minimum=0.0, maximum=_MAX_MARKET_VALUE)
        ce_premium = _request_number(body, "ce_premium", 0.0, minimum=0.0, maximum=_MAX_MARKET_VALUE)
        pe_premium = _request_number(body, "pe_premium", 0.0, minimum=0.0, maximum=_MAX_MARKET_VALUE)
        adjustment_legs = _parse_adjustment_legs(body)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    lot_size = LOT_SIZES.get(symbol.upper(), 50)
    spot = 24000.0
    candles: list[dict[str, Any]] = []

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            hist = broker_reads.get_history(
                registry,
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                days=1,
            )
            candles = hist.get("candles", [])
            history_spot = _finite_number(hist.get("spot"))
            if history_spot is not None and 0 < history_spot <= _MAX_MARKET_VALUE:
                spot = history_spot
        except Exception as exc:
            logger.warning("Live straddle candle data unavailable, using sample: %s", exc)

    if not candles:
        candles = _make_sample_candles(spot=spot)
        logger.info("StraddlePnL: using sample candle data for %s", symbol)

    # The option premiums, strike selection, lot size, and time-value path are
    # proxy inputs. Live underlying candles alone cannot make this a live result.
    used_sample = True

    # Default strike/premiums from sample data if not provided
    if strike <= 0:
        strike = round(spot / 50) * 50
    if ce_premium <= 0:
        ce_premium = spot * 0.01  # ~1% of spot as rough ATM premium
    if pe_premium <= 0:
        pe_premium = spot * 0.0105  # slightly higher puts for skew

    result = simulate_straddle_pnl(
        candles=candles,
        strike=strike,
        ce_premium=ce_premium,
        pe_premium=pe_premium,
        adjustment_points=adjustment_points,
        lot_size=lot_size,
    )

    # Augment with the terminal's StraddlePnLData contract. The widget plots a
    # PAYOFF DIAGRAM (P&L at expiry vs underlying price) — a different object
    # from the dataclass's intraday P&L time series, which is retained for any
    # other consumer. The payoff is analytic from ALL legs: the base long
    # straddle plus any user-added adjustment legs from the widget.
    total_premium = ce_premium + pe_premium
    legs = [
        {"strike": strike, "type": "CE", "action": "BUY", "premium": ce_premium, "lots": 1},
        {"strike": strike, "type": "PE", "action": "BUY", "premium": pe_premium, "lots": 1},
        *adjustment_legs,
    ]

    def payoff_at(s: float) -> float:
        total = 0.0
        for leg in legs:
            intrinsic = max(s - leg["strike"], 0.0) if leg["type"] == "CE" else max(leg["strike"] - s, 0.0)
            per_unit = intrinsic - leg["premium"]
            if leg["action"] == "SELL":
                per_unit = -per_unit
            total += per_unit * leg["lots"] * lot_size
        return total

    # Widen the sampled range to cover every leg's strike, then derive
    # break-evens from the combined curve's zero crossings (the analytic
    # strike ± premium shortcut only holds for the bare straddle).
    strikes = [leg["strike"] for leg in legs]
    lo, hi, steps = min(strikes) * 0.9, max(strikes) * 1.1, 41
    payoff_curve = []
    crossings: list[float] = []
    prev_s: float | None = None
    prev_pnl: float | None = None
    for i in range(steps):
        s = lo + (hi - lo) * i / (steps - 1)
        pnl = payoff_at(s)
        payoff_curve.append({"spot_price": round(s, 2), "pnl": round(pnl, 2)})
        if prev_pnl is not None and prev_s is not None and (prev_pnl <= 0 < pnl or pnl <= 0 < prev_pnl):
            span = pnl - prev_pnl
            crossings.append(prev_s if span == 0 else prev_s + (0 - prev_pnl) * (s - prev_s) / span)
        prev_s, prev_pnl = s, pnl

    break_even_low = min(crossings) if crossings else strike - total_premium
    break_even_high = max(crossings) if crossings else strike + total_premium
    max_loss = min(point["pnl"] for point in payoff_curve)
    data = _dataclass_to_dict(result)
    data.update({
        "underlying": symbol,
        "atm_strike": strike,
        "call_premium": ce_premium,
        "put_premium": pe_premium,
        "break_even_low": round(break_even_low, 2),
        "break_even_high": round(break_even_high, 2),
        "max_loss": max_loss,
        "curve": payoff_curve,
        "legs": legs,
    })

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "interval": interval,
        "spot": spot,
        "is_sample_data": used_sample,
        "data": data,
    })


# ---------------------------------------------------------------------------
# OI Profile endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/oiprofile", methods=["POST"])
def oi_profile_endpoint() -> Any:
    """OI Profile with butterfly analysis.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.
        strike_count (int): Max strikes to return, ATM-centred (default 0 = all).
        interval (str): Futures candle interval.

    Returns:
        JSON with OI profile data, butterfly, and futures OHLCV.
    """
    try:
        body, symbol, exchange, expiry = _option_request("26MAR26")
        strike_count = _request_integer(body, "strike_count", 0, minimum=0)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None
    futures_candles: list[dict[str, Any]] = []

    chain_data = None
    authoritative_dte = _live_option_days_to_expiry(expiry)
    if authoritative_dte is not None:
        chain_data = _live_option_chain(
            symbol,
            exchange,
            expiry,
            require_authoritative_oi=True,
        )
    chain_spot = _authoritative_chain_spot(chain_data) if chain_data else None
    if chain_data and chain_spot is not None and _chain_has_valid_strike(chain_data):
        spot = chain_spot
        candidate = _snapshot_from_registry_data(
            chain_data,
            symbol,
            exchange,
            spot,
        )
        snapshot = candidate if candidate.strikes else None

    used_sample = snapshot is None
    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("OIProfile: using sample data for %s %s", symbol, exchange)

    if used_sample and not futures_candles:
        futures_candles = _make_sample_candles(spot=spot)

    result = calculate_oi_profile(snapshot, futures_candles=futures_candles)

    # Augment the raw dataclass with the terminal's OIProfileData contract. The
    # widget reads per-strike OBJECTS (strike/ce_oi/pe_oi/…) plus atm_strike,
    # max_pain_strike, total_ce_oi/pe_oi and pcr — none of which the column-
    # oriented dataclass exposed, so it rendered undefined. The dataclass's own
    # keys (oi_butterfly, oi_change, futures_ohlcv, …) are retained for any other
    # consumer; only ``strikes`` is overridden from a float list to the objects.
    data = _dataclass_to_dict(result)
    total_ce_oi = sum(result.ce_oi)
    total_pe_oi = sum(result.pe_oi)
    strikes = [
        {
            "strike": ps.strike_price,
            "ce_oi": ps.ce_oi,
            "pe_oi": ps.pe_oi,
            **(
                {
                    "ce_oi_change": ps.ce_oi_change,
                    "pe_oi_change": ps.pe_oi_change,
                }
                if result.oi_change_available or used_sample
                else {}
            ),
        }
        for ps in result.profile_strikes
    ]
    if not used_sample and not result.oi_change_available:
        for key in ("oi_change", "ce_oi_change", "pe_oi_change"):
            data.pop(key, None)
        for row in data.get("profile_strikes", []):
            if isinstance(row, dict):
                row.pop("ce_oi_change", None)
                row.pop("pe_oi_change", None)
    # Honour the caller's strike-count window (ATM-centred), mirroring volsurface.
    # 0 / absent keeps the full set. Every per-strike array is windowed by the
    # SAME indices so the parallel arrays (oi_butterfly/oi_change/…) stay aligned
    # with strikes; the chain-wide totals/PCR below are reported over the whole
    # chain regardless of how many strikes are displayed.
    n_strikes = len(result.profile_strikes)
    if strike_count > 0 and n_strikes > strike_count:
        atm = snapshot.atm_strike
        keep = sorted(
            sorted(range(n_strikes), key=lambda i: abs(strikes[i]["strike"] - atm))[:strike_count]
        )
        strikes = [strikes[i] for i in keep]
        for key in ("ce_oi", "pe_oi", "oi_butterfly", "oi_change",
                    "ce_oi_change", "pe_oi_change", "profile_strikes"):
            seq = data.get(key)
            if isinstance(seq, list) and len(seq) == n_strikes:
                data[key] = [seq[i] for i in keep]
    data.update({
        "underlying": symbol,
        "expiry": expiry,
        "spot_price": spot,
        "atm_strike": snapshot.atm_strike,
        "max_pain_strike": OIAnalysis.max_pain(snapshot).max_pain_strike,
        "strikes": strikes,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "pcr": (total_pe_oi / total_ce_oi) if total_ce_oi else None,
    })

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "is_sample_data": used_sample,
        "data": data,
    })


# ---------------------------------------------------------------------------
# Max Pain endpoint
# ---------------------------------------------------------------------------


@analysis_bp.route("/maxpain", methods=["POST"])
def max_pain_endpoint() -> Any:
    """Max Pain strike calculation.

    Request JSON:
        symbol (str): Underlying symbol.
        exchange (str): Exchange code.
        expiry (str): Expiry label.

    Returns:
        JSON with max pain strike, total loss at max pain, and per-strike losses.
    """
    try:
        _body, symbol, exchange, expiry = _option_request("26MAR26")
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    spot = 24000.0
    snapshot: OptionChainSnapshot | None = None

    chain_data = None
    authoritative_dte = _live_option_days_to_expiry(expiry)
    if authoritative_dte is not None:
        chain_data = _live_option_chain(
            symbol,
            exchange,
            expiry,
            require_authoritative_oi=True,
        )
    chain_spot = _authoritative_chain_spot(chain_data) if chain_data else None
    if chain_data and chain_spot is not None and _chain_has_valid_strike(chain_data):
        spot = chain_spot
        candidate = _snapshot_from_registry_data(
            chain_data,
            symbol,
            exchange,
            spot,
        )
        snapshot = candidate if candidate.strikes else None

    used_sample = snapshot is None
    if snapshot is None:
        snapshot = _make_sample_snapshot(symbol=symbol, exchange=exchange, spot=spot)
        logger.info("MaxPain: using sample data for %s %s", symbol, exchange)

    result = OIAnalysis.max_pain(snapshot)
    available = result.max_pain_strike > 0

    return jsonify({
        "status": "success",
        "symbol": symbol,
        "exchange": exchange,
        "expiry": expiry,
        "spot": spot,
        "is_sample_data": used_sample,
        "data": {
            "available": available,
            "max_pain_strike": result.max_pain_strike,
            "total_loss_at_max_pain": result.total_loss_at_max_pain,
            "strike_losses": result.strike_losses,
        },
    })


# ---------------------------------------------------------------------------
# RRG endpoint
# ---------------------------------------------------------------------------


def _make_sample_rrg_series(
    symbol: str,
    n_weeks: int = 60,
    base_level: float = 100.0,
    drift: float = 0.0,
    noise: float = 1.2,
) -> _Series:
    """Generate synthetic weekly close-price series for dev/fallback RRG.

    Prices are a random walk around base_level, seeded deterministically from
    the symbol string so the same symbol always produces the same sample path
    (reproducible dev mode).

    Args:
        symbol: Sector or benchmark symbol (used to seed the RNG).
        n_weeks: Number of weekly bars to generate.
        base_level: Starting index level (default 100 = relative to benchmark).
        drift: Weekly drift in percent (default 0 = no trend).
        noise: Weekly volatility in percent (default 1.2%).

    Returns:
        _Series with ISO-format weekly date strings and synthetic closes.
    """
    import hashlib
    import random
    from datetime import date, timedelta

    # Deterministic seed from symbol name so results are reproducible
    seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Weekly bars ending today, going backwards
    today = date.today()
    # Find nearest Monday
    monday = today - timedelta(days=today.weekday())
    dates: list[str] = []
    for i in range(n_weeks - 1, -1, -1):
        week_start = monday - timedelta(weeks=i)
        dates.append(week_start.isoformat())

    price = base_level
    prices: list[float] = []
    for _ in dates:
        change_pct = drift / 100.0 + rng.gauss(0, noise / 100.0)
        price = max(10.0, price * (1 + change_pct))
        prices.append(round(price, 2))

    return _Series(dates=dates, values=prices)


@analysis_bp.route("/rrg/sectors", methods=["GET"])
def rrg_sectors_endpoint() -> Any:
    """Relative Rotation Graph data for all 12 NIFTY sector indices.

    Query params:
        tail_length (int): Number of weekly tail points to return (default 12).
        interval (str): Price history interval — 'W' weekly (default) or '1M' monthly.

    Returns:
        JSON with list of SectorRRG objects plus benchmark info:
        {
          "status": "success",
          "benchmark": "NIFTY 50",
          "tail_length": 12,
          "is_sample_data": bool,
          "sectors": [ { symbol, name, tail: [{date, rs_ratio, rs_momentum}], current_quadrant }, ... ]
        }

    Notes:
        - Uses OpenAlgo /history endpoint (weekly) when broker is connected.
        - Falls back to deterministic synthetic data in dev/disconnected mode.
        - Benchmark is always NIFTY 50 (NSE_INDEX).
    """
    tail_length = int(request.args.get("tail_length", 12))
    # Clamp tail to 4-52 range
    tail_length = max(4, min(52, tail_length))
    n_bars = max(60, tail_length + 52)  # need enough history for 52-bar z-score window

    is_sample_data = True
    sector_prices: dict[str, _Series] = {}
    benchmark_prices: _Series | None = None

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            from datetime import date, timedelta  # noqa: PLC0415
            end_date = date.today().isoformat()
            start_date = (date.today() - timedelta(weeks=n_bars + 4)).isoformat()

            # Fetch benchmark (NIFTY 50) weekly history
            bench_hist = broker_reads.get_history(
                registry,
                symbol=BENCHMARK_SYMBOL,
                exchange=BENCHMARK_EXCHANGE,
                interval="W",
                start=start_date,
                end=end_date,
            )
            bench_candles = bench_hist.get("candles", [])
            if bench_candles:
                benchmark_prices = _candles_to_series(bench_candles)

            # Fetch each sector's weekly history
            if benchmark_prices:
                for symbol, _name in NIFTY_SECTORS:
                    try:
                        sec_hist = broker_reads.get_history(
                            registry,
                            symbol=symbol,
                            exchange=SECTOR_EXCHANGE,
                            interval="W",
                            start=start_date,
                            end=end_date,
                        )
                        candles = sec_hist.get("candles", [])
                        if candles:
                            sector_prices[symbol] = _candles_to_series(candles)
                    except Exception as exc:
                        logger.warning("RRG: sector %s history failed: %s", symbol, exc)

                if len(sector_prices) >= 3:
                    is_sample_data = False

        except Exception as exc:
            logger.warning("RRG: live history unavailable, using sample data: %s", exc)
            sector_prices = {}
            benchmark_prices = None

    # Fall back to synthetic data
    if is_sample_data or benchmark_prices is None:
        logger.info("RRG: using synthetic sample data")
        benchmark_prices = _make_sample_rrg_series(
            BENCHMARK_SYMBOL, n_weeks=n_bars, base_level=24000.0, drift=0.08, noise=1.5
        )
        # Each sector drifts differently so they end up in different quadrants
        sector_drifts = [0.12, 0.05, 0.09, -0.02, 0.15, -0.08, 0.03, 0.10, 0.01, -0.05, 0.07, 0.11]
        for i, (symbol, _name) in enumerate(NIFTY_SECTORS):
            drift = sector_drifts[i % len(sector_drifts)]
            sector_prices[symbol] = _make_sample_rrg_series(
                symbol, n_weeks=n_bars, base_level=24000.0, drift=drift, noise=1.8
            )

    results = build_sector_rrg(sector_prices, benchmark_prices, tail_length=tail_length)

    return jsonify({
        "status": "success",
        "data": {
            "benchmark": BENCHMARK_SYMBOL,
            "tail_length": tail_length,
            "is_sample_data": is_sample_data,
            "sectors": results,
        },
    })


@analysis_bp.route("/rrg/portfolio", methods=["GET"])
def rrg_portfolio_endpoint() -> Any:
    """Relative Rotation Graph data for a user-selected symbol list.

    Query params:
        symbols (str): Comma-separated NSE symbols.
        tail_length (int): Number of weekly tail points to return.

    The SectorMap Portfolio tab has long exposed this feature but pointed at a
    missing route. This endpoint reuses the same broker-history and synthetic
    fallback path as sector RRG, keeping sample data flagged explicitly.
    """
    raw_symbols = request.args.get("symbols", "")
    symbols = []
    seen: set[str] = set()
    for token in raw_symbols.split(","):
        symbol = token.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
        if len(symbols) >= 20:
            break

    tail_length = int(request.args.get("tail_length", 8))
    tail_length = max(4, min(52, tail_length))
    n_bars = max(60, tail_length + 52)

    if not symbols:
        return jsonify({
            "status": "success",
            "data": {
                "benchmark": BENCHMARK_SYMBOL,
                "tail_length": tail_length,
                "is_sample_data": False,
                "sectors": [],
            },
        })

    is_sample_data = True
    symbol_prices: dict[str, _Series] = {}
    benchmark_prices: _Series | None = None

    registry = _get_registry()
    if registry and registry.is_connected():
        try:
            from datetime import timedelta  # noqa: PLC0415

            end_date = date.today().isoformat()
            start_date = (date.today() - timedelta(weeks=n_bars + 4)).isoformat()
            bench_hist = broker_reads.get_history(
                registry,
                symbol=BENCHMARK_SYMBOL,
                exchange=BENCHMARK_EXCHANGE,
                interval="W",
                start=start_date,
                end=end_date,
            )
            bench_candles = bench_hist.get("candles", [])
            if bench_candles:
                benchmark_prices = _candles_to_series(bench_candles)

            if benchmark_prices:
                for symbol in symbols:
                    try:
                        hist = broker_reads.get_history(
                            registry,
                            symbol=symbol,
                            exchange="NSE",
                            interval="W",
                            start=start_date,
                            end=end_date,
                        )
                        candles = hist.get("candles", [])
                        if candles:
                            symbol_prices[symbol] = _candles_to_series(candles)
                    except Exception as exc:
                        logger.warning("Portfolio RRG: history failed for %s: %s", symbol, exc)

                if symbol_prices:
                    is_sample_data = False
        except Exception as exc:
            logger.warning("Portfolio RRG: live history unavailable, using sample data: %s", exc)
            symbol_prices = {}
            benchmark_prices = None

    if is_sample_data or benchmark_prices is None:
        logger.info("Portfolio RRG: using synthetic sample data")
        benchmark_prices = _make_sample_rrg_series(
            BENCHMARK_SYMBOL, n_weeks=n_bars, base_level=24000.0, drift=0.08, noise=1.5
        )
        for idx, symbol in enumerate(symbols):
            drift = 0.02 + (idx % 7) * 0.025
            symbol_prices[symbol] = _make_sample_rrg_series(
                symbol, n_weeks=n_bars, base_level=1000.0 + idx * 75.0, drift=drift, noise=2.0
            )

    sectors = []
    for symbol in symbols:
        prices = symbol_prices.get(symbol)
        if prices is None:
            continue
        tail = compute_rrg(prices, benchmark_prices, tail_length=tail_length)
        sectors.append({
            "symbol": symbol,
            "name": symbol,
            "tail": tail,
            "current_quadrant": classify_quadrant(tail),
        })

    return jsonify({
        "status": "success",
        "data": {
            "benchmark": BENCHMARK_SYMBOL,
            "tail_length": tail_length,
            "is_sample_data": is_sample_data,
            "sectors": sectors,
        },
    })


def _candles_to_series(candles: list[dict[str, Any]]) -> _Series:
    """Convert OpenAlgo OHLCV candle list to a dated close-price _Series.

    Candle format: {"time": unix_ts, "open": f, "high": f, "low": f, "close": f, "volume": i}
    or {"timestamp": unix_ts, ...} — handles both field names.

    Args:
        candles: List of OHLCV candle dicts from registry.get_history().

    Returns:
        _Series with ISO date strings and close prices, sorted ascending.
    """
    from datetime import datetime, timezone  # noqa: PLC0415

    dates: list[str] = []
    closes: list[float] = []

    for c in candles:
        ts_raw = c.get("time", c.get("timestamp"))
        close = float(c.get("close", 0))
        if ts_raw is None or close <= 0:
            continue
        try:
            ts = int(ts_raw)
            # Handle millisecond timestamps (> year 2100 in seconds)
            if ts > 4_102_444_800:
                ts = ts // 1000
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            dates.append(dt.date().isoformat())
            closes.append(close)
        except (ValueError, OSError):
            continue

    # Sort ascending by date
    paired = sorted(zip(dates, closes), key=lambda x: x[0])
    if not paired:
        return _Series(dates=[], values=[])
    sorted_dates, sorted_closes = zip(*paired)
    return _Series(dates=list(sorted_dates), values=list(sorted_closes))


# ---------------------------------------------------------------------------
# Internal helpers: registry data → screener models
# ---------------------------------------------------------------------------


def _optional_row_float(
    row: dict[str, Any],
    key: str,
    default: float | None = 0.0,
) -> float | None:
    if key not in row or row[key] is None:
        return default
    number = _finite_number(row[key])
    if number is None:
        return None
    if key.endswith("_ltp"):
        return number if 0 <= number <= _MAX_MARKET_VALUE else None
    if key.endswith("_iv"):
        return number if 0 <= number <= _MAX_IV_PERCENT else None
    if key.endswith("_delta"):
        return number if -1 <= number <= 1 else None
    if key.endswith("_gamma"):
        return number if 0 <= number <= _MAX_GAMMA else None
    if key.endswith("_vega"):
        return number if 0 <= number <= _MAX_ABS_GREEK else None
    if key.endswith("_theta"):
        return number if abs(number) <= _MAX_ABS_GREEK else None
    return number if abs(number) <= _MAX_MARKET_VALUE else None


def _optional_row_count(row: dict[str, Any], key: str) -> int | None:
    if key not in row or row[key] is None:
        return 0
    number = _finite_number(row[key])
    if number is None or number < 0 or number > _MAX_OPEN_INTEREST or not number.is_integer():
        return None
    return int(number)


def _snapshot_from_registry_data(
    chain_data: dict[str, Any],
    symbol: str,
    exchange: str,
    spot: float,
    *,
    require_authoritative_oi: bool = True,
    require_complete_greeks: bool = False,
) -> OptionChainSnapshot:
    """Convert BrokerRegistry option chain response to OptionChainSnapshot.

    Args:
        chain_data: Raw chain response dict from registry.
        symbol: Underlying symbol.
        exchange: Exchange code.
        spot: Spot price.
        require_authoritative_oi: Require explicit non-negative integer OI on
            both legs. IV-only consumers may set this false; supplied invalid
            OI is still rejected.
        require_complete_greeks: Require both option legs to explicitly attest
            complete, finite, physically possible IV and Greek values.

    Returns:
        OptionChainSnapshot populated from the registry data.
    """
    raw_strikes = chain_data.get("strikes", [])
    strike_data_list: list[StrikeData] = []

    def empty_snapshot() -> OptionChainSnapshot:
        return OptionChainSnapshot(
            underlying=symbol,
            exchange=exchange,
            spot_price=spot,
            atm_strike=spot,
            strikes=[],
        )

    if not isinstance(raw_strikes, list) or not raw_strikes:
        return empty_snapshot()

    seen_strikes: set[float] = set()

    for row in raw_strikes:
        if not isinstance(row, dict):
            return empty_snapshot()
        strike = _row_strike(row)
        if strike is None or strike in seen_strikes:
            return empty_snapshot()
        seen_strikes.add(strike)
        ce_oi = _row_open_interest(row, "ce")
        pe_oi = _row_open_interest(row, "pe")
        if ce_oi is None:
            if require_authoritative_oi or "ce_oi" in row:
                return empty_snapshot()
            ce_oi = 0
        if pe_oi is None:
            if require_authoritative_oi or "pe_oi" in row:
                return empty_snapshot()
            pe_oi = 0
        if require_complete_greeks and not (
            _leg_has_complete_greeks(row, "ce") and _leg_has_complete_greeks(row, "pe")
        ):
            return empty_snapshot()
        floats = {
            field: _optional_row_float(row, field)
            for field in (
                "ce_ltp",
                "ce_iv",
                "ce_delta",
                "ce_gamma",
                "ce_theta",
                "ce_vega",
                "pe_ltp",
                "pe_iv",
                "pe_delta",
                "pe_gamma",
                "pe_theta",
                "pe_vega",
            )
        }
        ce_volume = _optional_row_count(row, "ce_volume")
        pe_volume = _optional_row_count(row, "pe_volume")
        if any(value is None for value in floats.values()) or ce_volume is None or pe_volume is None:
            return empty_snapshot()
        sd = StrikeData(
            strike_price=strike,
            ce_ltp=floats["ce_ltp"],
            ce_oi=ce_oi,
            ce_volume=ce_volume,
            ce_iv=floats["ce_iv"],
            ce_delta=floats["ce_delta"],
            ce_gamma=floats["ce_gamma"],
            ce_theta=floats["ce_theta"],
            ce_vega=floats["ce_vega"],
            pe_ltp=floats["pe_ltp"],
            pe_oi=pe_oi,
            pe_volume=pe_volume,
            pe_iv=floats["pe_iv"],
            pe_delta=floats["pe_delta"],
            pe_gamma=floats["pe_gamma"],
            pe_theta=floats["pe_theta"],
            pe_vega=floats["pe_vega"],
        )
        strike_data_list.append(sd)

    return OptionChainSnapshot(
        underlying=symbol,
        exchange=exchange,
        spot_price=spot,
        atm_strike=spot,
        strikes=strike_data_list,
    )


def _leg_has_complete_greeks(row: dict[str, Any], prefix: str) -> bool:
    """Return whether one leg attests finite, physically possible Greeks."""
    if row.get(f"{prefix}_greeks_complete") is not True:
        return False
    values: list[float] = []
    for field in ("iv", "delta", "gamma", "theta", "vega"):
        raw = row.get(f"{prefix}_{field}")
        if raw is None or isinstance(raw, bool):
            return False
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
        values.append(value)
    iv, delta, gamma, theta, vega = values
    delta_valid = 0.0 <= delta <= 1.0 if prefix == "ce" else -1.0 <= delta <= 0.0
    return (
        0.0 < iv <= _MAX_IV_PERCENT
        and delta_valid
        and 0.0 <= gamma <= _MAX_GAMMA
        and abs(theta) <= _MAX_ABS_GREEK
        and 0.0 <= vega <= _MAX_ABS_GREEK
    )


def _chain_to_vol_surface_format(
    chain_data: dict[str, Any],
    spot: float,
    *,
    days_to_expiry: int,
) -> dict[str, Any]:
    """Convert BrokerRegistry chain response to vol surface input format.

    Args:
        chain_data: Raw chain response dict.
        spot: Spot price.
        days_to_expiry: Authoritatively parsed positive calendar DTE.

    Returns:
        Dict with 'dte', 'spot', and 'strikes' for vol surface calculation.
    """
    if isinstance(days_to_expiry, bool) or not isinstance(days_to_expiry, int) or days_to_expiry <= 0:
        raise ValueError("days_to_expiry must be an authoritative positive integer")

    strikes: list[dict[str, float]] = []
    seen_strikes: set[float] = set()
    raw_strikes = chain_data.get("strikes", [])
    if not isinstance(raw_strikes, list) or not raw_strikes:
        raise ValueError("option chain must contain source rows")
    for row in raw_strikes:
        if not isinstance(row, dict):
            raise ValueError("option chain source row is not an object")
        strike = _row_strike(row)
        if strike is None or strike in seen_strikes:
            raise ValueError("option chain source rows must have unique bounded strikes")
        seen_strikes.add(strike)
        ce_ltp = _optional_row_float(row, "ce_ltp", default=None)
        pe_ltp = _optional_row_float(row, "pe_ltp", default=None)
        ce_iv = _optional_row_float(row, "ce_iv", default=None)
        pe_iv = _optional_row_float(row, "pe_iv", default=None)
        observations = (ce_ltp, pe_ltp, ce_iv, pe_iv)
        if any(value is None or value <= 0 for value in observations):
            raise ValueError("option chain source row lacks positive finite price/IV observations")
        strikes.append({
            "strike": strike,
            "ce_ltp": ce_ltp,
            "pe_ltp": pe_ltp,
            "ce_iv": ce_iv,
            "pe_iv": pe_iv,
        })

    strikes.sort(key=lambda row: row["strike"])
    return {
        "dte": days_to_expiry,
        "spot": spot,
        "strikes": strikes,
    }


def _make_sample_chains_by_expiry(
    spot: float,
    expiries: list[str],
) -> dict[str, dict[str, Any]]:
    """Generate sample vol surface input for dev/fallback mode.

    Args:
        spot: Spot price.
        expiries: List of expiry labels.

    Returns:
        ChainsByExpiry dict with synthetic multi-expiry data.
    """
    result: dict[str, dict[str, Any]] = {}

    for i, expiry in enumerate(expiries):
        dte = _live_option_days_to_expiry(expiry)
        if dte is None:
            raise ValueError(f"Sample expiry must be a valid future date: {expiry!r}")
        iv_base = 15.0 + i * 1.5  # term structure: longer expiry = higher IV
        strikes_data = []
        step = _sample_strike_step(spot, 100.0, 10)
        for j in range(-10, 11):
            k = spot + j * step
            dist = abs(j)
            iv = iv_base + dist * 0.6
            strikes_data.append({
                "strike": k,
                "ce_ltp": max(1.0, 200 - max(0, j) * 15),
                "pe_ltp": max(1.0, 200 + min(0, j) * 15),
                "ce_iv": iv,
                "pe_iv": iv + 0.5,
            })
        result[expiry] = {"dte": dte, "spot": spot, "strikes": strikes_data}

    return result


# ---------------------------------------------------------------------------
# FII/DII endpoint (adapted from MarketCalls/fii-dii-data)
# ---------------------------------------------------------------------------


@analysis_bp.route("/screener/fii-dii", methods=["GET"])
def fii_dii_endpoint() -> Any:
    """FII/DII institutional flow data.

    Fetches latest FII/DII cash and F&O data from NSE, caches in DuckDB,
    and returns the result.  Pattern adapted from MarketCalls/fii-dii-data.

    Query params:
        days (int): Number of days for trend data (default 1 = latest only).
            Use ``days=30`` to get the last 30 trading days.
        refresh (bool): Force a fresh fetch from NSE (default false).

    Returns:
        JSON with latest FII/DII snapshot and optional trend data:
        {
          "status": "success",
          "is_sample_data": bool,
          "latest": { ... FiiDiiSnapshot fields ... },
          "trend": { ... FiiDiiTrend fields ... } | null
        }
    """
    from .fii_dii import (  # noqa: PLC0415
        FiiDiiTracker,
        make_sample_fii_dii,
        make_sample_trend,
    )

    days = int(request.args.get("days", 1))
    days = max(1, min(200, days))
    force_refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")

    is_sample_data = False
    tracker: FiiDiiTracker | None = None
    latest = None

    try:
        tracker = FiiDiiTracker()

        if force_refresh:
            latest = tracker.fetch_latest()
        else:
            latest = tracker.get_latest_cached()
            if latest is None:
                latest = tracker.fetch_latest()

    except Exception as exc:
        logger.warning("FII/DII live data unavailable: %s", exc)

    if latest is None:
        is_sample_data = True
        latest = make_sample_fii_dii()
        logger.info("FII/DII: using sample data")

    trend_data = None
    if days > 1:
        if tracker is not None and not is_sample_data:
            try:
                trend = tracker.get_trend(days=days)
                trend_data = trend.to_dict()
            except Exception as exc:
                logger.warning("FII/DII trend query failed: %s", exc)
                trend_data = make_sample_trend(days=days).to_dict()
                is_sample_data = True
        else:
            trend_data = make_sample_trend(days=days).to_dict()

    if tracker is not None:
        tracker.close()

    return jsonify({
        "status": "success",
        "data": {
            "is_sample_data": is_sample_data,
            "latest": latest.to_dict(),
            "trend": trend_data,
        },
    })


@analysis_bp.route("/screener/fii-long-short", methods=["GET"])
def fii_long_short_endpoint() -> Any:
    """FII long/short ratio surface (DP1).

    Derives per-segment FII long/short ratios (index futures, stock futures,
    index calls, index puts) plus an aggregate futures directional bias from the
    F&O participant-OI already captured by :class:`FiiDiiTracker`. No extra NSE
    round-trip beyond the shared FII/DII fetch.

    Query params:
        refresh (bool): Force a fresh NSE fetch (default false; uses cache).

    Returns:
        JSON with the derived ratio surface::

            {
              "status": "success",
              "data": {
                "is_sample_data": bool,
                "ratio": { ...FiiLongShortRatio fields... }
              }
            }
    """
    from .fii_dii import (  # noqa: PLC0415
        FiiDiiTracker,
        compute_fii_long_short,
        make_sample_fii_dii,
    )

    force_refresh = request.args.get("refresh", "false").lower() in ("true", "1", "yes")

    is_sample_data = False
    tracker: FiiDiiTracker | None = None
    latest = None

    try:
        tracker = FiiDiiTracker()
        if force_refresh:
            latest = tracker.fetch_latest()
        else:
            latest = tracker.get_latest_cached()
            if latest is None:
                latest = tracker.fetch_latest()
    except Exception as exc:
        logger.warning("FII long/short live data unavailable: %s", exc)

    if latest is None:
        is_sample_data = True
        latest = make_sample_fii_dii()
        logger.info("FII long/short: using sample data")

    if tracker is not None:
        tracker.close()

    ratio = compute_fii_long_short(latest)

    return jsonify({
        "status": "success",
        "data": {
            "is_sample_data": is_sample_data,
            "ratio": ratio.to_dict(),
        },
    })
