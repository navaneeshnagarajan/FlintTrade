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
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
for rel in ("packages/core/core/src", "packages/integrations/gateway/src"):
    path = str(ROOT / rel)
    if path not in sys.path:
        sys.path.insert(0, path)

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

READ_CHOICES = ("profile", "funds", "positions", "holdings", "orders", "trades")
DEFAULT_READS: dict[str, tuple[str, ...]] = {
    "dhan": READ_CHOICES,
    "groww": READ_CHOICES,
    "indmoney": READ_CHOICES,
    "kotakneo": ("funds", "positions", "holdings", "orders", "trades"),
    "upstox": READ_CHOICES,
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
            CredentialField(
                "consumer_key",
                "Kotak Neo Trade API access token (SDK consumer_key)",
                required=False,
            ),
            CredentialField("mobile_number", "Kotak Neo mobile number"),
            CredentialField("ucc", "Kotak Neo UCC"),
            CredentialField("totp", "Current Kotak Neo TOTP"),
            CredentialField("mpin", "Kotak Neo MPIN"),
            CredentialField("access_token", "Kotak Neo Trade API access token alias", required=False),
            CredentialField("neo_fin_key", "Optional Kotak neo_fin_key", required=False),
        ),
    },
    "upstox": {
        "access_token": (
            CredentialField("access_token", "Upstox access token"),
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
    return credentials


def _resolve_reads(broker: str, requested: list[str] | None) -> list[str]:
    if not requested or requested == ["default"]:
        return list(DEFAULT_READS[broker])
    if requested == ["all"]:
        return list(READ_CHOICES)
    reads: list[str] = []
    for read in requested:
        if read == "default":
            reads.extend(DEFAULT_READS[broker])
        elif read == "all":
            reads.extend(READ_CHOICES)
        else:
            reads.append(read)
    deduped: list[str] = []
    for read in reads:
        if read not in READ_CHOICES:
            raise ValueError(f"unknown read {read!r}; choose from: {', '.join(READ_CHOICES)}")
        if read not in deduped:
            deduped.append(read)
    return deduped


def _read_call(adapter: Any, broker: str, name: str) -> ReadCall | None:
    if name == "profile":
        if broker == "dhan":
            return adapter.user_profile
        return getattr(adapter, "profile", None)
    if name == "orders":
        return adapter.order_book
    if name == "trades":
        return adapter.trade_book
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
    )
    parser.add_argument("broker", choices=sorted(ADAPTER_FACTORIES))
    parser.add_argument(
        "--method",
        help="Credential method. Defaults per broker: dhan/groww/indmoney/upstox access_token, kotakneo totp_mpin.",
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
        help="Read-only calls: default, all, or any of profile funds positions holdings orders trades.",
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
