"""Native-adapter activation factory (the dormant -> live bridge).

The native SDK adapters (Dhan / Upstox / Kotak Neo) are written, gated and
mock-tested, but stay dormant until two prerequisites hold for a broker:

1. its non-placeholder SDK pin is installed and attested (``broker_sdk_attest``), and
2. the operator has stored credentials for it (the encrypted vault).

This module owns the decision of *which* natives to construct and register, so
``build_broker_router`` can activate them the moment those prerequisites are met
without the adapters themselves knowing anything about attestation or the vault.

Construction is deliberately SDK-free: every native adapter imports its SDK only
inside ``login()`` (when no ``client_factory`` is injected), so a broker can be
*registered* here even before a live session exists — the session is established
later by the credential-replay login step. That also makes this factory fully
unit-testable without any broker SDK installed.
"""

from __future__ import annotations

from typing import Any, Callable

from ._base import BrokerAdapter
from .dhan import DhanAdapter
from .groww import GrowwAdapter
from .indmoney import IndMoneyAdapter
from .kotakneo import KotakNeoAdapter
from .upstox import UpstoxAdapter

# broker_id -> native adapter class. ``openalgo`` is intentionally absent: it is
# the bridge adapter, wired separately in ``build_broker_router``.
NATIVE_ADAPTER_CLASSES: dict[str, type[BrokerAdapter]] = {
    "dhan": DhanAdapter,
    "upstox": UpstoxAdapter,
    "kotakneo": KotakNeoAdapter,
    "indmoney": IndMoneyAdapter,
    "groww": GrowwAdapter,
}

# broker_id -> the ``brokers.lock`` SDK pin name that gates its activation. Lets
# the router map an attestation result (keyed by SDK package) back to a broker.
# Placeholder pins intentionally attest as ``skipped`` and keep future waves dormant.
# ``None`` marks REST-only natives with NO third-party SDK (IndMoney/Groww):
# there is nothing to attest, so activation is gated by stored credentials alone.
SDK_PIN_BY_BROKER: dict[str, str | None] = {
    "dhan": "dhanhq",
    "upstox": "upstox-python-sdk",
    "kotakneo": "neo-api-client",
    "indmoney": None,
    "groww": None,
}


def is_native_broker(broker_id: str) -> bool:
    """True if ``broker_id`` has a native FlintTrade adapter (not the bridge)."""
    return broker_id in NATIVE_ADAPTER_CLASSES


def build_native_adapters(
    broker_ids: list[str],
    *,
    attest_ok: Callable[[str], bool],
    has_credentials: Callable[[str], bool],
    adapter_kwargs: Callable[[str], dict[str, Any]] | None = None,
    on_skip: Callable[[str, str], None] | None = None,
) -> dict[str, BrokerAdapter]:
    """Construct the native adapters whose prerequisites are met.

    For each requested ``broker_id`` that names a native adapter, the adapter is
    constructed only when BOTH ``attest_ok(broker_id)`` (its SDK is installed and
    pinned-match) and ``has_credentials(broker_id)`` (the vault holds creds) are
    true. Non-native ids (e.g. ``openalgo``) and brokers failing either gate are
    skipped — reported via ``on_skip(broker_id, reason)`` — so the result holds
    exactly the natives that are safe to register.

    Args:
        broker_ids: candidate broker ids (e.g. the native selectors in the
            routing config's ``registered`` set).
        attest_ok: ``broker_id -> bool`` SDK-attestation check.
        has_credentials: ``broker_id -> bool`` vault-presence check.
        adapter_kwargs: optional ``broker_id -> kwargs`` supplying per-broker
            constructor arguments (e.g. an instrument/symbol resolver). The
            adapter builds its live SDK facade lazily at ``login`` when no
            ``client_factory`` is supplied.
        on_skip: optional ``(broker_id, reason)`` sink for observability.

    Returns:
        ``{broker_id: adapter}`` for every native that passed both gates. Empty
        when nothing is attested + credentialled — the correct dormant state.
    """
    out: dict[str, BrokerAdapter] = {}
    seen: set[str] = set()
    for broker_id in broker_ids:
        if broker_id in seen:
            continue
        seen.add(broker_id)
        cls = NATIVE_ADAPTER_CLASSES.get(broker_id)
        if cls is None:
            continue  # not a native broker (bridge / unknown)
        if not attest_ok(broker_id):
            if on_skip is not None:
                on_skip(broker_id, "sdk-not-attested")
            continue
        if not has_credentials(broker_id):
            if on_skip is not None:
                on_skip(broker_id, "no-credentials")
            continue
        kwargs = adapter_kwargs(broker_id) if adapter_kwargs is not None else {}
        out[broker_id] = cls(**kwargs)
    return out
