"""Declarative catalogue of every login method each native broker supports.

The single source of truth the connect UI renders its forms from and the connect
route validates against, so an operator can pick their preferred login method per
broker (full broker support). Grounded in the per-broker auth maps under
``.local/specs/broker-auth/``. Each method lists the exact credential fields the
adapter's ``login()`` consumes (or the OAuth start needs), whether they are
secret (masked in the UI, never logged), and the flow kind so the frontend knows
whether to render a form (``direct``) or launch the OAuth redirect (``oauth``).
"""

from __future__ import annotations

from typing import Any

# kind values: "direct" — POST the fields to /native/accounts; "oauth" — POST
# api_key/api_secret to /native/oauth/start then follow the returned auth_url.

_FIELD = dict[str, Any]


def _f(name: str, label: str, *, secret: bool = False, required: bool = True, help_: str = "") -> _FIELD:
    return {"name": name, "label": label, "secret": secret, "required": required, "help": help_}


# Proper display names for the connect UI. The adapter ids are lower-case
# identifiers ("kotakneo", "indmoney") whose .capitalize() forms read wrong —
# and the bridge catalogue's Kotak entry is "kotak" (BROKER_CATALOG aliases the
# native "kotakneo"), so this map is the native UI's naming source of truth.
NATIVE_DISPLAY_NAMES: dict[str, str] = {
    "dhan": "Dhan",
    "upstox": "Upstox",
    "kotakneo": "Kotak Neo",
    "indmoney": "INDmoney",
}


# broker_id -> list of auth methods. Only methods the native adapter actually
# supports today are listed as connectable; read-only/out-of-band methods
# (Upstox extended/analytics/app-based/MCP, Dhan partner OAuth) are documented in
# the auth maps but omitted here until wired, so the UI never offers a method
# that can't complete.
NATIVE_AUTH_METHODS: dict[str, list[dict[str, Any]]] = {
    "dhan": [
        {
            "id": "access_token",
            "label": "Access token",
            "kind": "direct",
            "description": "Paste a 24h access token from web.dhan.co → Profile → Access DhanHQ APIs.",
            "fields": [
                _f("client_id", "Dhan client ID"),
                _f("access_token", "Access token", secret=True),
            ],
        },
        {
            "id": "pin_totp",
            "label": "PIN + TOTP",
            "kind": "direct",
            "description": "Mint a fresh 24h token from your PIN and authenticator code (TOTP must be enabled on the account).",
            "fields": [
                _f("client_id", "Dhan client ID"),
                _f("pin", "PIN", secret=True),
                _f("totp", "6-digit TOTP"),
            ],
        },
    ],
    "upstox": [
        {
            "id": "oauth",
            "label": "Log in with Upstox (OAuth)",
            "kind": "oauth",
            "description": "Approve access on upstox.com. Register the shown redirect URL in your Upstox app (Developer → Apps).",
            "fields": [
                _f("api_key", "API key (client ID)"),
                _f("api_secret", "API secret", secret=True),
            ],
        },
        {
            "id": "access_token",
            "label": "Access token",
            "kind": "direct",
            "description": "Paste a token you already generated (e.g. via a prior OAuth login or a sandbox app).",
            "fields": [
                _f("client_id", "Client ID", required=False),
                _f("access_token", "Access token", secret=True),
            ],
        },
    ],
    "kotakneo": [
        {
            "id": "totp_mpin",
            "label": "TOTP + MPIN",
            "kind": "direct",
            "description": "Kotak NEO two-step 2FA. Consumer key from NEO → Invest → Trade API; TOTP from your authenticator; MPIN is your NEO PIN.",
            "fields": [
                _f("consumer_key", "Consumer key", secret=True),
                _f("mobile_number", "Mobile number (with country code)"),
                _f("ucc", "UCC (client code)"),
                _f("totp", "6-digit TOTP"),
                _f("mpin", "MPIN", secret=True),
                _f("neo_fin_key", "Neo fin key", required=False),
            ],
        },
    ],
    "indmoney": [
        {
            "id": "access_token",
            "label": "Access token",
            "kind": "direct",
            "description": "Generate an access token on the INDstocks API dashboard and paste it here.",
            "fields": [
                _f("user_id", "User ID", required=False),
                _f("access_token", "Access token", secret=True),
            ],
        },
    ],
}


def auth_methods_for(broker_id: str) -> list[dict[str, Any]]:
    """Return the connectable auth methods for a native broker (empty if none)."""
    return NATIVE_AUTH_METHODS.get(broker_id, [])
