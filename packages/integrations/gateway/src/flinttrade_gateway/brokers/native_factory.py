"""Native-adapter activation factory (the dormant -> live bridge).

The native adapters (Dhan / Upstox / Kotak Neo / INDmoney / Groww) are written,
gated and mock-tested, but stay dormant until every activation requirement holds
for a broker:

1. the catalogue marks it ``connectable=True`` only after every declared
   ``native_connect_blocker`` has been cleared,
2. its non-placeholder SDK pin is installed and attested (``broker_sdk_attest``),
3. the operator has stored credentials for it (the encrypted vault), and
4. the adapter exposes authoritative emergency reduction planning.

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

from flinttrade_gateway.adapter import BROKER_CATALOG

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

# broker_id -> the ``brokers.lock`` SDK pin name that gates native activation.
# The pin itself lives on BROKER_CATALOG so the operator-facing native flag and
# the repo-local SDK attestation gate cannot drift.
SDK_PIN_BY_BROKER: dict[str, str | None] = {
    broker_id: info.sdk_pin
    for broker_id, info in BROKER_CATALOG.items()
    if info.native
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
    constructed only when the public catalogue says every activation blocker is
    cleared and it is connectable, ``attest_ok(broker_id)`` says its SDK is
    installed and pinned-match, and ``has_credentials(broker_id)`` says the vault
    holds creds.
    Non-native ids (e.g. ``openalgo``) and brokers failing any gate are skipped
    — reported via ``on_skip(broker_id, reason)`` — so the result holds exactly
    the natives that are safe to register.

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
        ``{broker_id: adapter}`` for every native that passed all gates. Empty
        when nothing is activation-cleared, attested, and credentialled — the
        correct dormant state.
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
        info = BROKER_CATALOG.get(broker_id)
        if info is not None and not info.connectable:
            if on_skip is not None:
                on_skip(broker_id, "coming-soon-activation-blocked")
            continue
        if not attest_ok(broker_id):
            if on_skip is not None:
                on_skip(broker_id, "sdk-not-attested")
            continue
        if not has_credentials(broker_id):
            if on_skip is not None:
                on_skip(broker_id, "no-credentials")
            continue
        kwargs = adapter_kwargs(broker_id) if adapter_kwargs is not None else {}
        adapter = cls(**kwargs)
        if not callable(getattr(adapter, "plan_emergency_reduction", None)):
            if on_skip is not None:
                on_skip(broker_id, "authoritative-emergency-planner-unavailable")
            continue
        out[broker_id] = adapter
    return out
