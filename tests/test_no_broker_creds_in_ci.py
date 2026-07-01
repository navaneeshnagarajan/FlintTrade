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


def _ci_env_snapshot(pytestconfig: pytest.Config) -> dict[str, str]:
    return getattr(pytestconfig, "_flinttrade_ci_env_at_start", dict(os.environ))


def _ci_env_value(env: dict[str, str], key: str) -> str:
    """Return the CI baseline value before any test fixture mutates os.environ."""
    return env.get(key, "").strip()


def test_no_broker_tokens_set_in_ci(pytestconfig: pytest.Config):
    env = _ci_env_snapshot(pytestconfig)
    if not env.get("FLINTTRADE_CI"):
        pytest.skip("local dev — credentials expected")
    leaked = [k for k in BROKER_CREDENTIAL_ENV_VARS if _ci_env_value(env, k)]
    assert not leaked, f"broker credentials unexpectedly set in CI: {leaked}"


def test_no_suffix_match_broker_envvars_set_in_ci(pytestconfig: pytest.Config):
    """Generic safety net: catch new-broker credential vars not yet enumerated."""
    env = _ci_env_snapshot(pytestconfig)
    if not env.get("FLINTTRADE_CI"):
        pytest.skip("local dev — credentials expected")
    suspicious = [
        k for k in env
        if any(k.upper().endswith(s) for s in GENERIC_SUFFIXES)
        and _ci_env_value(env, k)
        and not k.startswith(("GITHUB_", "RUNNER_", "ACTIONS_"))  # exclude CI infra
    ]
    assert not suspicious, (
        f"suspicious credential-shaped env vars in CI: {suspicious}. "
        f"add to BROKER_CREDENTIAL_ENV_VARS if intentional, else unset."
    )
