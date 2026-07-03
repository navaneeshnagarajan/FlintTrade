"""Native broker daily session refresh (Phase 1 G5).

The real refresh hook the ``CredentialsRotator`` scaffold was built for.
Indian broker tokens are day-scoped (SEBI daily re-auth): Dhan's 24h token is
the only one renewable in place (``GET /RenewToken``); Upstox/Kotak Neo/
IndMoney need a fresh login at expiry. The morning refresh therefore:

1. renews-in-place where the adapter exposes ``renew_token`` AND a live
   session still exists, then re-runs ``login()`` with the new token — which
   also rewrites the vault with the replayable material (G7);
2. otherwise replays the vault credentials — succeeds while the stored token
   is still valid, and otherwise fails INTO the ``NATIVE_SESSION_STATUS``
   surface so the accounts UI shows "needs fresh login: <reason>" instead of
   silently trading on a dead session.

``configure_session_rotation`` builds the rotator over this hook, schedules
the 08:05 IST refresh for every registered native broker (after Upstox's
~03:30 IST expiry, before the 09:15 open), and returns the admin blueprint
for the factory to mount. The APScheduler instance is created UNSTARTED —
the serve path starts it — so ``create_flask_app`` stays side-effect-light.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, current_app, request

logger = logging.getLogger("flinttrade.native_rotation")


class NativeSessionRefresher:
    """``refresh_token(broker)`` over every stored selector of a native broker.

    The credentials-manager hook :class:`CredentialsRotator` calls from
    ``_do_refresh``. Raises on failure so the rotator reports an honest failed
    ``RotationResult`` (the scaffold's silent fake-success is impossible once
    this hook is wired).
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    def refresh_token(self, broker: str) -> None:
        """Re-establish live sessions for every stored ``broker`` account.

        Args:
            broker: The native adapter id (e.g. ``"dhan"``).

        Raises:
            RuntimeError: When the adapter is not active, no accounts are
                stored, or any selector's refresh fails (per-selector detail
                also lands in ``NATIVE_SESSION_STATUS`` for the UI).
        """
        import asyncio  # noqa: PLC0415

        from flinttrade_gateway.native_login import establish_native_session  # noqa: PLC0415

        app = self._app
        adapter = (app.config.get("NATIVE_ADAPTERS") or {}).get(broker)
        registry = app.config.get("REGISTRY")
        store = app.config.get("CREDENTIAL_STORE")
        if adapter is None or registry is None or store is None:
            raise RuntimeError(f"native adapter {broker!r} is not active")

        rows = [
            r for r in store.list_accounts()
            if str(r.get("adapter_id") or r.get("broker") or "") == broker
        ]
        if not rows:
            raise RuntimeError(f"no stored accounts for {broker!r}")

        status: dict[str, Any] = app.config.setdefault("NATIVE_SESSION_STATUS", {})
        failures: list[str] = []
        for row in rows:
            account_id = str(row.get("account_id") or "")
            selector = f"{broker}:{account_id}"
            try:
                credentials = store.retrieve_for(broker, account_id)
                renewed_token = False
                # Renew-in-place when the broker supports it (Dhan RenewToken
                # extends the 24h window without a fresh 2FA) — needs the still-
                # live session; best-effort, falling back to a plain replay.
                renew = getattr(adapter, "renew_token", None)
                if callable(renew):
                    try:
                        session = registry.get_session_for(broker, account_id)
                    except Exception:  # noqa: BLE001 - no live session to renew
                        session = None
                    if session is not None:
                        try:
                            renewed = asyncio.run(renew(session))
                            token = str(
                                (renewed or {}).get("accessToken")
                                or (renewed or {}).get("access_token")
                                or ""
                            )
                            if token:
                                credentials = {**credentials, "access_token": token}
                                renewed_token = True
                        except Exception as exc:  # noqa: BLE001 - fall back to replay
                            logger.info(
                                "renew_token failed for %s (%s) — replaying vault credentials",
                                selector, exc,
                            )
                # verify=True: the token-replay logins (Upstox/IndMoney) build a
                # Session without contacting the broker, so a DEAD token would
                # report success. establish_native_session probes a cheap
                # authenticated read and raises (dropping the session) on a hard
                # auth failure — the SAME probe the interactive routes use.
                asyncio.run(
                    establish_native_session(
                        adapter, registry, credentials, broker, account_id,
                        credential_store=store, verify=True,
                    )
                )
                # Persist the renewed token: establish_native_session's write-back
                # compares the replayable payload against the (already-merged)
                # in-memory credentials and would skip the write, leaving the OLD
                # token in the vault to be replayed next boot. Force the write.
                if renewed_token:
                    try:
                        store.update_credentials_for(broker, account_id, credentials)
                    except Exception as exc:  # noqa: BLE001 - session is live regardless
                        logger.warning("Renewed-token persist failed for %s: %s", selector, exc)
                status[selector] = "ok"
            except Exception as exc:  # noqa: BLE001 - per-selector isolation
                status[selector] = f"login-failed: {exc}"
                failures.append(f"{selector}: {exc}")
        if failures:
            raise RuntimeError("; ".join(failures))


def configure_session_rotation(app: Any) -> Blueprint | None:
    """Build the rotator, schedule the morning refresh, return the admin routes.

    Stores the rotator on ``app.config["CREDENTIALS_ROTATOR"]`` and its
    UNSTARTED scheduler on ``app.config["ROTATION_SCHEDULER"]`` (the serve
    path calls ``.start()`` — tests never spawn the thread). Every registered
    native broker gets a daily 08:05 IST refresh job. Returns ``None`` (and
    logs) when APScheduler is unavailable — rotation then simply stays off.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415

        from flinttrade_gateway.brokers.native_factory import is_native_broker  # noqa: PLC0415
        from flinttrade_gateway.credentials_rotation import CredentialsRotator  # noqa: PLC0415
        from flinttrade_gateway.rotation_routes import create_rotation_blueprint  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - optional scheduling dep
        logger.warning("Session rotation unavailable (%s)", exc)
        return None

    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    rotator = CredentialsRotator(NativeSessionRefresher(app), scheduler)
    app.config["CREDENTIALS_ROTATOR"] = rotator
    app.config["ROTATION_SCHEDULER"] = scheduler

    # Morning re-auth for every registered native (jobs queue on the unstarted
    # scheduler and arm when the serve path starts it).
    try:
        from .app import _read_workspace_brokers  # noqa: PLC0415

        registered = [str(s) for s in ((_read_workspace_brokers() or {}).get("registered") or [])]
        native_brokers = sorted({
            s.split(":", 1)[0] for s in registered if is_native_broker(s.split(":", 1)[0])
        })
        for broker in native_brokers:
            rotator.schedule_daily_refresh(broker, "08:05")
    except Exception as exc:  # noqa: BLE001 - scheduling must not brick the factory
        logger.warning("Could not schedule native session refresh jobs: %s", exc)

    bp = create_rotation_blueprint(rotator)

    @bp.before_request
    def _guard_rotation_writes() -> Any | None:
        """G9 — rotation schedule/rotate-now writes need the operator session."""
        if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return None
        guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
        if guard is None:
            return None
        return guard()

    return bp
