"""Assert no real broker credentials are accessible during a CI run (Security L4).

Every broker credential variable from every broker sub-spec is enumerated here. When a
new broker is onboarded its sub-spec MUST cross-reference this list. The generic-suffix
net catches credential-shaped vars added before the explicit list is updated.

Skipped on local-dev machines (no FLINTTRADE_CI) where credentials are expected.
Sub-spec §14.3; acceptance gate #19.
"""

from __future__ import annotations

import os

import pytest

# Per-broker credential variables — mirror every name referenced in the broker adapter
# sub-specs (`<BROKER>_<FIELD>`).
BROKER_CREDENTIAL_ENV_VARS = (
    # OpenAlgo bridge path
    "OPENALGO_API_KEY",
    # Dhan (wave 1)
    "DHAN_ACCESS_TOKEN", "DHAN_API_KEY", "DHAN_API_SECRET", "DHAN_CLIENT_ID",
    "DHAN_PARTNER_ID", "DHAN_PARTNER_SECRET", "DHAN_TOKEN",
    # Upstox (wave 2)
    "UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_ACCESS_TOKEN",
    "UPSTOX_REDIRECT_URI", "UPSTOX_REFRESH_TOKEN", "UPSTOX_TOKEN",
    # Kotak Neo (wave 3)
    "KOTAK_NEO_CONSUMER_KEY", "KOTAK_NEO_CONSUMER_SECRET",
    "KOTAK_NEO_MOBILE_NUMBER", "KOTAK_NEO_PASSWORD",
    "KOTAK_NEO_MPIN", "KOTAK_NEO_TOTP", "KOTAK_NEO_TOTP_SECRET",
    "KOTAK_NEO_ACCESS_TOKEN", "KOTAK_NEO_SESSION_TOKEN", "KOTAK_NEO_TOKEN",
    "KOTAK_NEO_VIEW_TOKEN", "KOTAK_NEO_SID", "KOTAK_NEO_USER_ID",
    # IndMoney (wave 4)
    "INDMONEY_API_KEY", "INDMONEY_API_SECRET", "INDMONEY_ACCESS_TOKEN",
    "INDMONEY_CLIENT_ID", "INDMONEY_TOKEN", "INDMONEY_REFRESH_TOKEN",
    # Zerodha (community wave)
    "KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN", "KITE_REQUEST_TOKEN",
    "ZERODHA_API_KEY", "ZERODHA_ACCESS_TOKEN",
    # Angel One (deferred wave)
    "ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD",
    "ANGEL_TOTP_SECRET", "SMARTAPI_KEY", "SMARTAPI_TOKEN",
    # Fyers (deferred wave)
    "FYERS_APP_ID", "FYERS_SECRET_KEY", "FYERS_ACCESS_TOKEN",
    "FYERS_CLIENT_ID", "FYERS_TOTP_SECRET", "FYERS_TOKEN",
)

GENERIC_SUFFIXES = ("_TOKEN", "_API_KEY", "_API_SECRET",
                    "_ACCESS_TOKEN", "_REFRESH_TOKEN", "_MPIN", "_TOTP")


@pytest.mark.skipif(not os.environ.get("FLINTTRADE_CI"),
                    reason="local dev — credentials expected")
def test_no_broker_tokens_set_in_ci():
    leaked = [k for k in BROKER_CREDENTIAL_ENV_VARS if os.environ.get(k)]
    assert not leaked, f"broker credentials unexpectedly set in CI: {leaked}"


@pytest.mark.skipif(not os.environ.get("FLINTTRADE_CI"),
                    reason="local dev — credentials expected")
def test_no_suffix_match_broker_envvars_set_in_ci():
    """Generic safety net: catch new-broker credential vars not yet enumerated."""
    suspicious = [
        k for k in os.environ
        if any(k.upper().endswith(s) for s in GENERIC_SUFFIXES)
        and os.environ.get(k)
        and not k.startswith(("GITHUB_", "RUNNER_", "ACTIONS_"))  # exclude CI infra
    ]
    assert not suspicious, (
        f"suspicious credential-shaped env vars in CI: {suspicious}. "
        f"add to BROKER_CREDENTIAL_ENV_VARS if intentional, else unset."
    )
