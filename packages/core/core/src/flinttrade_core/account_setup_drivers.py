"""Reviewed local account drivers; construction performs no external I/O.

Authentication is invoked only by the owned account transaction. Disposing a
local HTTP pool is not broker logout, token revocation or claim settlement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession
from flinttrade_gateway.brokers.kotakneo_streaming import STREAM_RUNTIME_KEY, KotakNeoStreamRuntime

from .account_lifecycle_contracts import AccountContractError
from .account_setup import AccountSetupDriver
from .broker_account_cutover import BrokerAccountCutoverUnavailable
from .broker_identity import BrokerSelector


def _validate_dhan(selector: BrokerSelector, credentials: Mapping[str, object]) -> None:
    token = credentials.get("access_token")
    if (
        set(credentials) != {"client_id", "access_token"}
        or type(credentials.get("client_id")) is not str
        or credentials["client_id"] != selector.account_id
        or type(token) is not str
        or not token.strip()
    ):
        raise AccountContractError


def production_account_drivers(
    *,
    adapter_kwargs: Callable[[str], dict[str, Any]] | None = None,
) -> tuple[AccountSetupDriver, ...]:
    """Construct inert descriptors; SDK clients remain lazy until CONNECT.

    Args:
        adapter_kwargs: Factory-owned constructor dependencies. Reference resolvers
            must consume already-acquired snapshots, never acquire data on lookup.

    Returns:
        Dhan and Kotak descriptors with explicit local-only disposal contracts.
        Construction grants no account permission or broker qualification.
    """
    dhan = DhanAdapter(**(adapter_kwargs("dhan") if adapter_kwargs is not None else {}))
    kotak = KotakNeoAdapter(**(adapter_kwargs("kotakneo") if adapter_kwargs is not None else {}))
    return (
        AccountSetupDriver("dhan", dhan, dhan.dispose_session, _validate_dhan),
        AccountSetupDriver("kotakneo", kotak, _dispose_kotak, _validate_kotak),
    )


def _validate_kotak(selector: BrokerSelector, credentials: Mapping[str, object]) -> None:
    required = {"consumer_key", "mobile_number", "ucc", "totp", "mpin"}
    if (
        set(credentials) != required
        or any(type(value) is not str or not value.strip() for value in (credentials.get(key) for key in required))
        or credentials["ucc"] != selector.account_id
    ):
        raise AccountContractError


def _dispose_kotak(payload: object) -> None:
    """Close only the pin's local REST pool, never NeoAPI.logout.

    Account setup admits REST reads, not streaming. Unexpected feed custody
    remains held rather than guessing a foreign loop's disposal protocol.
    """
    import httpx

    if type(payload) is not Session or payload.adapter_id != "kotakneo":
        raise BrokerAccountCutoverUnavailable
    if payload.extra.get("account_local_disposed") is True:
        return
    facade = payload.extra["client"]
    runtime = payload.extra[STREAM_RUNTIME_KEY]
    if type(facade) is not KotakNeoSdkSession or type(runtime) is not KotakNeoStreamRuntime:
        raise BrokerAccountCutoverUnavailable
    if (
        runtime._market_feed is not None
        or runtime._order_feed is not None
        or runtime._market_candidate is not None
        or runtime._order_candidate is not None
        or runtime._owned_tasks
        or runtime._mutation_tasks
        or runtime._feed_close_tasks
    ):
        raise BrokerAccountCutoverUnavailable
    client = facade._neo.api_client.rest_client.session
    if type(client) is not httpx.Client:
        raise BrokerAccountCutoverUnavailable
    if not client.is_closed:
        client.close()
    else:
        # HTTPX sets its Client closed flag BEFORE closing transports. A raised
        # pool close therefore needs these same owned transports retried, not
        # another Client.close() which would silently do nothing. The pinned
        # HTTPTransport pools have idempotent local close; custom transports
        # and live feeds are deliberately not guessed at.
        transports = {id(value): value for value in (client._transport, *client._mounts.values()) if value is not None}
        if any(type(value) is not httpx.HTTPTransport for value in transports.values()):
            raise BrokerAccountCutoverUnavailable
        for transport in transports.values():
            transport.close()
    facade._closed = True
    facade._neo = None
    runtime._closed = True
    payload.extra.pop("client")
    payload.extra.pop(STREAM_RUNTIME_KEY)
    payload.access_token = ""
    payload.extra["account_local_disposed"] = True
