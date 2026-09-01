#!/usr/bin/env python3
"""Run redacted, read-only live probes for native broker adapters.

The script is intentionally interactive. It never accepts secrets on the command
line, never prints broker payloads, and performs no order writes.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
for rel in ("packages/core/core/src", "packages/integrations/gateway/src"):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: E402
from flinttrade_gateway.brokers.dhan import DhanAdapter  # noqa: E402
from flinttrade_gateway.brokers.groww import GrowwAdapter  # noqa: E402
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter  # noqa: E402
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter  # noqa: E402
from flinttrade_gateway.brokers.upstox import UpstoxAdapter  # noqa: E402
from flinttrade_gateway.native_login import should_keep_session_after_probe_error  # noqa: E402

AdapterFactory = Callable[[], Any]
ReadCall = Callable[[Any], Awaitable[Any]]

ADAPTER_FACTORIES: dict[str, AdapterFactory] = {
    "dhan": DhanAdapter,
    "groww": GrowwAdapter,
    "indmoney": IndMoneyAdapter,
    "kotakneo": KotakNeoAdapter,
    "upstox": UpstoxAdapter,
}

COMMON_READ_CHOICES = ("profile", "funds", "positions", "holdings", "orders", "trades")
ORDER_DETAIL_READ_CHOICES = ("orderstatus", "orderhistory", "ordertrades")
COMMON_MARKET_READ_CHOICES = ("quotes", "depth", "margin", "history")
DHAN_MARKET_READ_CHOICES = ("quotes", "ltp", "ohlc", "quote_details", "margin", "history")
DHAN_QUOTE_PROJECTION_READS = frozenset({"ltp", "ohlc", "quote_details"})
DHAN_SECURITY_RESOLVER_READ_CHOICES = frozenset(DHAN_MARKET_READ_CHOICES)
GROWW_MARKET_READ_CHOICES = ("quotes", "ltp", "ohlc", "margin", "history", "expiry")
INDMONEY_MARKET_READ_CHOICES = ("quotes", "ltp", "depth", "margin", "history")
UPSTOX_MARKET_READ_CHOICES = COMMON_MARKET_READ_CHOICES + ("ltp", "ohlc")
PROBE_EXCHANGE = "NSE"
PROBE_SYMBOL = "RELIANCE"
PROBE_QUOTE_SYMBOL = f"{PROBE_EXCHANGE}:{PROBE_SYMBOL}"
PROBE_UNDERLYING = "NIFTY"
PROBE_INDEX_EXCHANGE = "NSE_INDEX"
PROBE_OPTION_SYMBOL = "NFO:NIFTY25000CE"
KOTAK_PROBE_EXCHANGE = PROBE_EXCHANGE
KOTAK_PROBE_SYMBOL = PROBE_SYMBOL
KOTAK_READ_CHOICES = (
    "funds",
    "limits",
    "positions",
    "holdings",
    "orders",
    "trades",
    "orderhistory",
    "ordertrades",
    "margin",
    "scrip_master",
    "search_scrip",
    "quotes",
    "quote_details",
    "market_depth",
)
READ_CHOICES_BY_BROKER: dict[str, tuple[str, ...]] = {
    "dhan": COMMON_READ_CHOICES + DHAN_MARKET_READ_CHOICES + ("expiry", "optionchain"),
    "groww": COMMON_READ_CHOICES + ("orderstatus", "ordertrades") + GROWW_MARKET_READ_CHOICES + ("optionchain",),
    "indmoney": COMMON_READ_CHOICES + ("orderstatus", "ordertrades") + INDMONEY_MARKET_READ_CHOICES,
    "kotakneo": KOTAK_READ_CHOICES,
    "upstox": COMMON_READ_CHOICES + UPSTOX_MARKET_READ_CHOICES + (
        *ORDER_DETAIL_READ_CHOICES,
        "optiongreeks",
        "expiry",
        "optionchain",
        "search",
        "timings",
        "holidays",
    ),
}
READ_CHOICES = tuple(dict.fromkeys(read for choices in READ_CHOICES_BY_BROKER.values() for read in choices))
DEFAULT_READS: dict[str, tuple[str, ...]] = {
    # One Dhan marketfeed call is enough for bundled probes (default and all):
    # ltp/ohlc and quote_details project the same quote_data response and remain
    # explicitly selectable so the 1 req/s quote limit is not hit by redundancy.
    "dhan": COMMON_READ_CHOICES + ("quotes", "margin", "history"),
    "groww": COMMON_READ_CHOICES + GROWW_MARKET_READ_CHOICES,
    "indmoney": COMMON_READ_CHOICES + INDMONEY_MARKET_READ_CHOICES,
    "kotakneo": KOTAK_READ_CHOICES,
    "upstox": COMMON_READ_CHOICES + UPSTOX_MARKET_READ_CHOICES + ("search", "timings", "holidays"),
}
DEFAULT_METHOD: dict[str, str] = {
    "dhan": "access_token",
    "groww": "api_key_secret",
    "indmoney": "access_token",
    "kotakneo": "totp_mpin",
    "upstox": "access_token",
}


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    required: bool = True


CREDENTIAL_FIELDS: dict[str, dict[str, tuple[CredentialField, ...]]] = {
    "dhan": {
        "access_token": (
            CredentialField("client_id", "Dhan client ID"),
            CredentialField("access_token", "Dhan access token"),
        ),
        "pin_totp": (
            CredentialField("client_id", "Dhan client ID"),
            CredentialField("pin", "Dhan PIN"),
            CredentialField("totp", "Current Dhan TOTP"),
        ),
        "oauth_token_id": (
            CredentialField("client_id", "Dhan client ID"),
            CredentialField("app_id", "Dhan app ID"),
            CredentialField("app_secret", "Dhan app secret"),
            CredentialField("token_id", "Dhan OAuth tokenId"),
        ),
    },
    "groww": {
        "api_key_totp": (
            CredentialField("api_key", "Groww Trade API key"),
            CredentialField("totp", "Current Groww TOTP"),
            CredentialField("user_id", "Optional Groww user/account label", required=False),
        ),
        "api_key_secret": (
            CredentialField("api_key", "Groww Trade API key"),
            CredentialField("api_secret", "Groww Trade API secret"),
            CredentialField("user_id", "Optional Groww user/account label", required=False),
        ),
        "access_token": (
            CredentialField("access_token", "Groww Trade API access token"),
            CredentialField("user_id", "Optional Groww user/account label", required=False),
        ),
    },
    "indmoney": {
        "access_token": (
            CredentialField("access_token", "INDstocks access token"),
            CredentialField("user_id", "Optional INDstocks user/account label", required=False),
        ),
    },
    "kotakneo": {
        "totp_mpin": (
            CredentialField("access_token", "Kotak Neo Trade API access token"),
            CredentialField("mobile_number", "Kotak Neo mobile number"),
            CredentialField("ucc", "Kotak Neo UCC"),
            CredentialField("totp", "Current Kotak Neo TOTP"),
            CredentialField("mpin", "Kotak Neo MPIN"),
            CredentialField("neo_fin_key", "Optional Kotak neo_fin_key", required=False),
        ),
    },
    "upstox": {
        "access_token": (
            CredentialField("access_token", "Upstox access token"),
            CredentialField("client_id", "Optional Upstox account/client label", required=False),
        ),
        "analytics_access_token": (
            CredentialField("access_token", "Upstox Analytics access token"),
            CredentialField("client_id", "Optional Upstox account/client label", required=False),
        ),
        "oauth_code": (
            CredentialField("code", "Upstox OAuth code"),
            CredentialField("api_key", "Upstox API key"),
            CredentialField("api_secret", "Upstox API secret"),
            CredentialField("redirect_uri", "Registered redirect URI"),
            CredentialField("client_id", "Optional Upstox account/client label", required=False),
        ),
    },
}

def _credential_defaults(broker: str, method: str) -> dict[str, str]:
    """Auth-method credential defaults from the broker catalogue.

    The in-app connect flow merges the selected method's ``credential_defaults``
    (e.g. the Upstox analytics token's ``read_only``/``token_scope`` flags) into
    the captured credentials. The probe derives them from the SAME catalogue
    entry so the two paths can never drift.
    """
    info = BROKER_CATALOG.get(broker)
    for entry in info.auth_methods if info else []:
        if entry.id == method:
            return {str(key): str(value) for key, value in entry.credential_defaults.items()}
    return {}

SECRET_FIELD_NAMES = (
    "access[_ -]?token",
    "accessToken",
    "api[_ -]?key",
    "apiKey",
    "api[_ -]?secret",
    "apiSecret",
    "app[_ -]?id",
    "appId",
    "app[_ -]?secret",
    "appSecret",
    "client[_ -]?id",
    "clientId",
    "client[_ -]?secret",
    "clientSecret",
    "code",
    "consumer[_ -]?key",
    "consumerKey",
    "mobile[_ -]?number",
    "mobileNumber",
    "mpin",
    "neo[_ -]?fin[_ -]?key",
    "neoFinKey",
    "pin",
    "redirect[_ -]?uri",
    "redirectUri",
    "token[_ -]?id",
    "tokenId",
    "totp",
    "ucc",
    "user[_ -]?id",
    "userId",
)
SECRET_FIELDS_RE = re.compile(
    r"(?i)(['\"]?\b(?:"
    + "|".join(SECRET_FIELD_NAMES)
    + r")\b['\"]?\s*[:=]\s*)['\"]?[^,'\"\s)}\]]+['\"]?"
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
MOBILE_RE = re.compile(r"\b(?:\+?91[-\s]?)?[6-9]\d{9}\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"https?://[^\s,'\")\]}]+")
BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){1,2}\b")
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{18,}\b")
ACCOUNTISH_RE = re.compile(r"\b[A-Z0-9]{5,16}\b")
LONG_NUMBER_RE = re.compile(r"\b\d{4,}\b")


class PromptAborted(Exception):
    """Raised when the operator cancels a hidden-input prompt."""


class InconclusiveRead(Exception):
    """Raised when a read is supported but needs live state the account lacks."""


def broker_read_help(broker: str) -> str:
    """Return the exact read names accepted by the shared probe for one broker."""
    choices = READ_CHOICES_BY_BROKER[broker]
    return " ".join(choices)


def broker_method_help() -> str:
    """Return the exact credential methods accepted by the shared probe."""
    lines = []
    for broker in sorted(CREDENTIAL_FIELDS):
        methods = ", ".join(sorted(CREDENTIAL_FIELDS[broker]))
        default = DEFAULT_METHOD[broker]
        lines.append(f"{broker}: {methods} (default: {default})")
    return "\n".join(lines)


def broker_reads_help() -> str:
    """Return the exact read choices accepted by the shared probe."""
    lines = []
    for broker in sorted(READ_CHOICES_BY_BROKER):
        lines.append(f"{broker}: {broker_read_help(broker)}")
    return "\n".join(lines)


def redact(text: object) -> str:
    """Return a bounded string with broker/account identifiers removed."""
    value = str(text)
    value = SECRET_FIELDS_RE.sub(lambda match: f"{match.group(1)}[redacted]", value)
    value = EMAIL_RE.sub("[email]", value)
    value = MOBILE_RE.sub("[mobile]", value)
    value = IP_RE.sub("[ip]", value)
    value = URL_RE.sub("[url]", value)
    value = BEARER_RE.sub("Bearer [redacted]", value)
    value = JWT_RE.sub("[token]", value)
    value = LONG_TOKEN_RE.sub("[token]", value)
    value = ACCOUNTISH_RE.sub("[id]", value)
    value = LONG_NUMBER_RE.sub("[number]", value)
    return value[:500]


def summarise_payload(payload: Any) -> str:
    """Describe only the shape of a broker response, never its contents."""
    if isinstance(payload, list):
        return f"ok rows={len(payload)}"
    if isinstance(payload, tuple):
        return f"ok rows={len(payload)}"
    if isinstance(payload, dict):
        return f"ok object_keys={len(payload)}"
    if payload is None:
        return "ok empty"
    return f"ok type={type(payload).__name__}"


def _secret_prompt(label: str, *, required: bool = True) -> str:
    while True:
        try:
            value = getpass.getpass(f"{label}: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise PromptAborted from exc
        if value or not required:
            return value
        print(f"{label} is required.")


def _resolve_method(broker: str, method: str | None) -> str:
    selected = method or DEFAULT_METHOD[broker]
    if selected not in CREDENTIAL_FIELDS[broker]:
        allowed = ", ".join(sorted(CREDENTIAL_FIELDS[broker]))
        raise ValueError(f"{broker} method must be one of: {allowed}")
    return selected


def collect_credentials(broker: str, method: str, environment: str) -> dict[str, str]:
    """Collect broker credentials without shell history or terminal echo."""
    display = {
        "dhan": "Dhan",
        "groww": "Groww",
        "indmoney": "INDstocks",
        "kotakneo": "Kotak Neo",
        "upstox": "Upstox",
    }[broker]
    print(f"Enter {display} values locally. They will not be printed or stored by this script.")
    credentials: dict[str, str] = {}
    if broker == "kotakneo":
        credentials["environment"] = environment
    for field in CREDENTIAL_FIELDS[broker][method]:
        value = _secret_prompt(field.label, required=field.required)
        if value:
            credentials[field.name] = value
    credentials.update(_credential_defaults(broker, method))
    return credentials


def _bundled_reads(broker: str, requested: str) -> list[str]:
    """Expand ``default`` / ``all`` without repeating Dhan quote projections.

    Dhan ``ltp``, ``ohlc``, and ``quote_details`` all dispatch through
    ``quotes()`` to the same ``quote_data`` endpoint (1 req/s). Bundled
    inventories keep one representative quotes read; the projections stay
    individually selectable.
    """
    if requested == "default":
        return list(DEFAULT_READS[broker])
    reads = list(READ_CHOICES_BY_BROKER[broker])
    if broker == "dhan":
        return [read for read in reads if read not in DHAN_QUOTE_PROJECTION_READS]
    return reads


def _resolve_reads(broker: str, requested: list[str] | None) -> list[str]:
    allowed_reads = READ_CHOICES_BY_BROKER[broker]
    if not requested or requested == ["default"]:
        return _bundled_reads(broker, "default")
    if requested == ["all"]:
        return _bundled_reads(broker, "all")
    reads: list[str] = []
    for read in requested:
        if read == "default":
            reads.extend(_bundled_reads(broker, "default"))
        elif read == "all":
            reads.extend(_bundled_reads(broker, "all"))
        else:
            reads.append(read)
    deduped: list[str] = []
    for read in reads:
        if read not in allowed_reads:
            raise ValueError(f"unknown {broker} read {read!r}; choose from: {', '.join(allowed_reads)}")
        if read not in deduped:
            deduped.append(read)
    return deduped


def _dhan_reads_need_security_resolver(reads: list[str]) -> bool:
    return any(read in DHAN_SECURITY_RESOLVER_READ_CHOICES for read in reads)


async def _prepare_adapter_for_probe(broker: str, adapter: Any, reads: list[str]) -> None:
    if broker != "dhan" or not _dhan_reads_need_security_resolver(reads):
        return
    if getattr(adapter, "_security_resolver", None) is not None:
        return
    fetch_security_list = getattr(adapter, "fetch_security_list", None)
    if not callable(fetch_security_list):
        return

    try:
        from flinttrade_gateway.brokers.dhan_mapping import build_security_resolver  # noqa: PLC0415

        rows = await fetch_security_list("compact")
    except Exception as exc:  # noqa: BLE001 - market reads will report the actual resolver miss
        print(f"resolver: failed {type(exc).__name__}: {redact(exc)}")
        return
    adapter._security_resolver = build_security_resolver(rows)
    print(f"resolver: ok dhan scrip_master rows={len(rows)}")


def _today_ist() -> datetime:
    return datetime.now(ZoneInfo("Asia/Kolkata"))


def _history_request() -> dict[str, Any]:
    end = _today_ist().date()
    start = end - timedelta(days=7)
    return {
        "symbol": PROBE_SYMBOL,
        "exchange": PROBE_EXCHANGE,
        "interval": "1d",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def _sample_order() -> Any:
    from flinttrade_core.models import Order  # noqa: PLC0415

    return Order(
        symbol=PROBE_SYMBOL,
        exchange=PROBE_EXCHANGE,
        action="BUY",
        product="MIS",
        quantity="1",
        pricetype="MARKET",
        price="0",
        trigger_price="0",
    )


def _option_chain_request() -> dict[str, Any]:
    expiry = (_today_ist().date() + timedelta(days=30)).isoformat()
    return {
        "symbol": PROBE_UNDERLYING,
        "underlying": PROBE_UNDERLYING,
        "exchange": PROBE_INDEX_EXCHANGE,
        "expiry": expiry,
        "expiry_date": expiry,
    }


def _payload_rows(payload: Any) -> list[Any]:
    """Return likely table rows from a broker read payload."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, tuple):
        return list(payload)
    if hasattr(payload, "model_dump"):
        return [payload.model_dump()]
    if isinstance(payload, dict):
        for key in ("data", "orders", "order_list", "items", "rows"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return [payload]
    return []


def _read_field(row: Any, *names: str) -> str:
    if hasattr(row, "model_dump"):
        row = row.model_dump()
    if not isinstance(row, dict):
        return ""
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


async def _sample_order_id(adapter: Any, session: Any) -> str:
    """Find a broker order id from order_book for per-order read probes."""
    order_book = getattr(adapter, "order_book", None)
    if not callable(order_book):
        raise InconclusiveRead("adapter has no order book to sample an order id")
    rows = _payload_rows(await order_book(session))
    for row in rows:
        order_id = _read_field(
            row,
            "orderid",
            "order_id",
            "groww_order_id",
            "nOrdNo",
            "orderId",
            "id",
        )
        if order_id:
            return order_id
    raise InconclusiveRead("no sample order id available from order book")


def _read_call(adapter: Any, broker: str, name: str) -> ReadCall | None:
    if name == "profile":
        if broker == "dhan":
            return adapter.user_profile
        return getattr(adapter, "profile", None)
    if name == "orders":
        return adapter.order_book
    if name == "trades":
        return adapter.trade_book
    if name in {"orderstatus", "orderhistory", "ordertrades"}:
        method_by_name = {
            "orderstatus": "order_details",
            "orderhistory": "order_history",
            "ordertrades": "order_trades",
        }
        method = getattr(adapter, method_by_name[name], None)
        if not callable(method):
            if name == "ordertrades" and broker == "upstox":
                method = getattr(adapter, "trades_by_order", None)
            if not callable(method):
                return None

        async def _call_order_read(session: Any) -> Any:
            order_id = await _sample_order_id(adapter, session)
            return await method(session, order_id)

        return _call_order_read
    if name == "quotes":
        return lambda session: adapter.quotes(session, [PROBE_QUOTE_SYMBOL])
    if name == "ltp":
        call = getattr(adapter, "ltp", None) or getattr(adapter, "ltp_quotes", None)
        return (lambda session: call(session, [PROBE_QUOTE_SYMBOL])) if callable(call) else None
    if name == "ohlc":
        call = getattr(adapter, "ohlc", None) or getattr(adapter, "ohlc_quotes", None)
        return (
            (lambda session: call(session, [PROBE_QUOTE_SYMBOL]))
            if callable(call)
            else None
        )
    if name == "quote_details":
        call = getattr(adapter, "quote_details", None)
        return (
            (lambda session: call(session, [PROBE_QUOTE_SYMBOL], "ltp"))
            if callable(call)
            else None
        )
    if name in {"depth", "market_depth"}:
        return (
            (lambda session: adapter.market_depth(session, [PROBE_QUOTE_SYMBOL]))
            if callable(getattr(adapter, "market_depth", None))
            else None
        )
    if name == "margin":
        return (
            (lambda session: adapter.margin_calculator(session, _sample_order()))
            if callable(getattr(adapter, "margin_calculator", None))
            else None
        )
    if name == "history":
        return (
            (lambda session: adapter.historical(session, _history_request()))
            if callable(getattr(adapter, "historical", None))
            else None
        )
    if name == "expiry":
        return (
            (lambda session: adapter.expiry_list(session, PROBE_UNDERLYING, PROBE_INDEX_EXCHANGE))
            if callable(getattr(adapter, "expiry_list", None))
            else None
        )
    if name == "optionchain":
        return (
            (lambda session: adapter.option_chain(session, _option_chain_request()))
            if callable(getattr(adapter, "option_chain", None))
            else None
        )
    if name == "optiongreeks":
        return (
            (lambda session: adapter.option_greeks(session, [PROBE_OPTION_SYMBOL]))
            if callable(getattr(adapter, "option_greeks", None))
            else None
        )
    if name == "search":
        return (
            (lambda session: adapter.search_instruments(session, PROBE_SYMBOL))
            if callable(getattr(adapter, "search_instruments", None))
            else None
        )
    if name == "timings":
        return (
            (lambda session: adapter.market_timings(session, _today_ist().date().isoformat()))
            if callable(getattr(adapter, "market_timings", None))
            else None
        )
    if name == "holidays":
        return (
            (lambda session: adapter.market_holidays(session))
            if callable(getattr(adapter, "market_holidays", None))
            else None
        )
    if broker == "kotakneo":
        if name == "scrip_master":
            return lambda session: adapter.scrip_master(session, KOTAK_PROBE_EXCHANGE)
        if name == "search_scrip":
            return lambda session: adapter.search_scrip(session, KOTAK_PROBE_SYMBOL, KOTAK_PROBE_EXCHANGE)
    return getattr(adapter, name, None)


async def run_probe(
    broker: str,
    method: str | None = None,
    read_names: list[str] | None = None,
    environment: str = "prod",
    logout: bool = False,
) -> int:
    broker = broker.lower()
    if broker not in ADAPTER_FACTORIES:
        allowed = ", ".join(sorted(ADAPTER_FACTORIES))
        print(f"probe: unsupported broker {broker!r}; choose from: {allowed}")
        return 2
    try:
        selected_method = _resolve_method(broker, method)
        reads = _resolve_reads(broker, read_names)
    except ValueError as exc:
        print(f"probe: {exc}")
        return 2

    adapter = ADAPTER_FACTORIES[broker]()
    await _prepare_adapter_for_probe(broker, adapter, reads)
    session = None
    try:
        session = await adapter.login(collect_credentials(broker, selected_method, environment))
    except PromptAborted:
        print("probe: cancelled before login")
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary must report safely
        print(f"login: failed {type(exc).__name__}: {redact(exc)}")
        return 2

    print("login: ok")
    failures = 0
    for name in reads:
        call = _read_call(adapter, broker, name)
        if call is None:
            print(f"{name}: skipped unsupported")
            continue
        try:
            payload = await call(session)
        except InconclusiveRead as exc:
            print(f"{name}: inconclusive {redact(exc)}")
            continue
        except Exception as exc:  # noqa: BLE001 - continue to collect all read statuses
            if should_keep_session_after_probe_error(exc):
                print(f"{name}: inconclusive {type(exc).__name__}: {redact(exc)}")
                continue
            failures += 1
            print(f"{name}: failed {type(exc).__name__}: {redact(exc)}")
            continue
        print(f"{name}: {summarise_payload(payload)}")

    if logout:
        try:
            await adapter.logout(session)
        except Exception as exc:  # noqa: BLE001 - logout is best effort but must stay redacted
            failures += 1
            print(f"logout: failed {type(exc).__name__}: {redact(exc)}")
        else:
            print("logout: ok")
    else:
        print("logout: skipped (pass --logout to revoke/close the broker token)")
    return 1 if failures else 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only native broker adapter probe with redacted output.",
        epilog=(
            "Credential methods by broker:\n"
            f"{broker_method_help()}\n\n"
            "Read choices by broker:\n"
            f"{broker_reads_help()}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("broker", choices=sorted(ADAPTER_FACTORIES))
    parser.add_argument(
        "--method",
        help=(
            "Credential method. Defaults per broker: dhan/upstox/indmoney access_token, "
            "groww api_key_secret, kotakneo totp_mpin."
        ),
    )
    parser.add_argument(
        "--environment",
        default="prod",
        choices=("prod", "uat"),
        help="Kotak Neo SDK environment to use.",
    )
    parser.add_argument(
        "--reads",
        nargs="+",
        default=["default"],
        help=(
            "Read-only calls: default, all, or broker-supported names. Common names include "
            "profile funds positions holdings orders trades quotes ltp depth margin history. "
            "Broker extras include expiry optionchain optiongreeks search timings holidays "
            "limits scrip_master search_scrip quote_details market_depth."
        ),
    )
    parser.add_argument(
        "--logout",
        action="store_true",
        help="Call the broker logout endpoint after probing; this may revoke access tokens.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(run_probe(args.broker, args.method, args.reads, args.environment, logout=args.logout))
    except KeyboardInterrupt:
        print("probe: cancelled")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
