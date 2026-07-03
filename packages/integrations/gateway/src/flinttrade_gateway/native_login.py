"""Native credential-replay login step (Phase 1 G3).

The missing link between the encrypted credential vault and a live native
broker session. A native adapter (Dhan/Upstox/Kotak Neo/IndMoney) is
*constructed* by ``build_native_adapters`` once its SDK attests and the vault
holds credentials, but until something decrypts those credentials, calls the
adapter's ``login()``, and registers the resulting ``Session`` under the
adapter's ``(adapter_id, account_id)`` selector, the ``BrokerRouter`` has no
session to dispatch to — every read and write for that selector fails. This
module is that step.

It is deliberately broker-agnostic: it only speaks the ``BrokerAdapter.login``
contract and the ``BrokerRegistry.put_session`` selector store, so the same
code path serves boot-time re-establishment, an interactive "connect broker"
action, and daily token re-authentication.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.gateway.native_login")


async def establish_native_session(
    adapter: Any,
    registry: Any,
    credentials: dict[str, Any],
    adapter_id: str,
    account_id: str,
    credential_store: Any | None = None,
) -> Any:
    """Log a native adapter in and register its session under the selector.

    Args:
        adapter: The live native ``BrokerAdapter`` instance (already built by
            ``build_native_adapters`` — this does NOT construct it).
        registry: The ``BrokerRegistry`` whose selector-keyed session store the
            router resolves against.
        credentials: Decrypted broker credentials passed verbatim to
            ``adapter.login`` (shape is broker-specific; see each adapter's
            ``login`` docstring).
        adapter_id: The bare adapter name (e.g. ``"dhan"``).
        account_id: The account within that adapter (e.g. the client id).
        credential_store: Optional ``CredentialStore``. When supplied AND the
            adapter exposes ``replay_credentials`` (Dhan/Upstox/Kotak Neo), the
            vault payload is rewritten with the REPLAYABLE material after a
            successful login (G7): single-use artefacts (OAuth ``code``,
            30-second TOTP) are swapped for the minted ``access_token`` where
            one exists, so the next boot reconnects instead of replaying a
            dead credential. Best-effort — a write-back failure is logged and
            never fails the live session.

    Returns:
        The live adapter-layer ``Session`` (also registered in ``registry``).

    Raises:
        Whatever ``adapter.login`` raises (``BrokerError``/``AuthFlowError``) —
        fail-closed: on failure NO session is registered, so the selector stays
        sessionless and the router keeps returning "no session" rather than
        dispatching against a half-authenticated broker.
    """
    session = await adapter.login(credentials)
    registry.put_session(adapter_id, account_id, session)
    logger.info(
        "Native session established for %s:%s (expires_at=%s)",
        adapter_id,
        account_id,
        getattr(session, "expires_at", None),
    )
    replay = getattr(adapter, "replay_credentials", None)
    if credential_store is not None and callable(replay):
        try:
            replayable = replay(dict(credentials), session)
            if isinstance(replayable, dict) and replayable != credentials:
                credential_store.update_credentials_for(adapter_id, account_id, replayable)
                logger.info(
                    "Vault payload for %s:%s rewritten with replayable material (G7)",
                    adapter_id,
                    account_id,
                )
        except Exception as exc:  # noqa: BLE001 - write-back must never fail the live session
            logger.warning(
                "Replayable-credential write-back failed for %s:%s: %s",
                adapter_id,
                account_id,
                exc,
            )
    return session


async def establish_native_sessions(
    native_adapters: dict[str, Any],
    registry: Any,
    credential_store: Any,
    selectors: list[str],
) -> dict[str, Any]:
    """Re-establish sessions for every active native selector with vault creds.

    Called at boot (and after a router rebuild) so natives that authenticated
    previously — or whose credentials were just stored — come back online
    without an interactive step. Each selector is isolated: one broker's login
    failure (expired token, network) is logged and skipped, never blocking the
    others.

    Args:
        native_adapters: Live ``broker_id -> adapter`` map of ACTIVE natives
            (``app.config["NATIVE_ADAPTERS"]``).
        registry: The ``BrokerRegistry``.
        credential_store: The ``CredentialStore`` (``retrieve_for`` lookups).
        selectors: The registered ``<adapter_id>:<account_id>`` selectors.

    Returns:
        ``{selector: "ok" | "<error>"}`` for observability (never raises).
    """
    from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415

    results: dict[str, Any] = {}
    for selector in selectors:
        try:
            adapter_id, account_id = parse_selector(selector)
        except ValueError:
            continue
        adapter = native_adapters.get(adapter_id)
        if adapter is None:
            # Not an active native (bridge selector, or dormant) — skip quietly.
            continue
        try:
            credentials = credential_store.retrieve_for(adapter_id, account_id)
        except Exception as exc:  # noqa: BLE001 - a missing/undecryptable row must not brick boot
            logger.info("No usable vault credentials for %s (%s) — leaving sessionless", selector, exc)
            results[selector] = f"no-credentials: {exc}"
            continue
        try:
            await establish_native_session(
                adapter, registry, credentials, adapter_id, account_id,
                credential_store=credential_store,
            )
            results[selector] = "ok"
        except Exception as exc:  # noqa: BLE001 - per-selector isolation
            logger.warning("Native login failed for %s: %s", selector, exc)
            results[selector] = f"login-failed: {exc}"
    return results
