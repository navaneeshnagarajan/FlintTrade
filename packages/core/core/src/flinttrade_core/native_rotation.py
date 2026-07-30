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
the 08:05 IST refresh for active registered native brokers (after Upstox's
~03:30 IST expiry, before the 09:15 open), and returns the admin blueprint
for the factory to mount. Coming-soon native selectors can stay registered
without creating false daily refresh failures. The APScheduler instance is
created UNSTARTED — the serve path starts it — so ``create_flask_app`` stays
side-effect-light.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from flask import Blueprint, current_app, request

logger = logging.getLogger("flinttrade.native_rotation")

_NATIVE_ROTATION_ADMISSION_CONFIG = "NATIVE_ROTATION_ADMISSION"
_ROTATION_ADMISSION_CONFIG_LOCK = threading.Lock()


class _RotationAdmissionRevoked(RuntimeError):
    """Raised when shutdown revokes a refresh before shared publication."""


class NativeRotationAdmission:
    """Generation-fence refresh admission and shared publication during shutdown."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._publication_lock = threading.Lock()
        self._generation = 0
        self._accepting = True
        self._active = 0

    def acquire(self) -> int:
        """Admit one refresh and return its publication generation."""
        with self._condition:
            if not self._accepting:
                raise RuntimeError("native session rotation is shutting down")
            generation = self._generation
            self._active += 1
            return generation

    def release(self, generation: int) -> None:
        """Release one admitted refresh, including a generation revoked in flight."""
        with self._condition:
            if generation > self._generation or self._active <= 0:
                raise RuntimeError("native session rotation admission ownership is invalid")
            self._active -= 1
            self._condition.notify_all()

    def assert_current(self, generation: int) -> None:
        """Reject work whose admission generation has been retired."""
        with self._condition:
            if not self._accepting or generation != self._generation:
                raise _RotationAdmissionRevoked("native session rotation ownership was revoked")

    def publish_if_current(
        self,
        generation: int,
        operation: Callable[[], Any],
    ) -> Any:
        """Run one shared mutation only while the admitted generation is current."""
        with self._publication_lock:
            self.assert_current(generation)
            return operation()

    def close_and_drain(self, timeout: float) -> bool:
        """Revoke admission and wait boundedly for publication and refresh owners."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            if self._accepting:
                self._accepting = False
                self._generation += 1
                self._condition.notify_all()

        remaining = max(0.0, deadline - time.monotonic())
        if not self._publication_lock.acquire(timeout=remaining):
            return False
        self._publication_lock.release()

        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    return False
                self._condition.wait(remaining)
            return True


def _rotation_admission(app: Any) -> NativeRotationAdmission:
    """Return the process owner shared by manual and scheduled refresh callers."""
    with _ROTATION_ADMISSION_CONFIG_LOCK:
        admission = app.config.get(_NATIVE_ROTATION_ADMISSION_CONFIG)
        if admission is None:
            admission = NativeRotationAdmission()
            app.config[_NATIVE_ROTATION_ADMISSION_CONFIG] = admission
        if not isinstance(admission, NativeRotationAdmission):
            raise RuntimeError("native session rotation admission owner is invalid")
        return admission


class _RotationAttemptOwner:
    """No-op cleanup owner for an unpublished rotation candidate."""

    def discard(self) -> None:
        """The candidate registry and credential copy die with the daemon attempt."""


class NativeSessionRefresher:
    """``refresh_token(broker)`` over every stored selector of a native broker.

    The credentials-manager hook :class:`CredentialsRotator` calls from
    ``_do_refresh``. Raises on failure so the rotator reports an honest failed
    ``RotationResult`` (the scaffold's silent fake-success is impossible once
    this hook is wired).
    """

    def __init__(
        self,
        app: Any,
        admission: NativeRotationAdmission | None = None,
    ) -> None:
        self._app = app
        self._admission = admission or _rotation_admission(app)

    def refresh_token(self, broker: str) -> None:
        """Re-establish live sessions for every stored ``broker`` account.

        Args:
            broker: The native adapter id (e.g. ``"dhan"``).

        Raises:
            RuntimeError: When the adapter is not active, no accounts are
                stored, or any selector's refresh fails (per-selector detail
                also lands in ``NATIVE_SESSION_STATUS`` for the UI).
        """
        from .native_account_routes import NATIVE_ACCOUNT_MUTATION_LOCK  # noqa: PLC0415

        generation = self._admission.acquire()
        try:
            with NATIVE_ACCOUNT_MUTATION_LOCK:
                self._refresh_token_locked(broker, generation)
        finally:
            self._admission.release(generation)

    def _refresh_token_locked(self, broker: str, generation: int) -> None:
        """Run one broker refresh while native-account mutations are excluded."""
        from flinttrade_gateway.native_login import (  # noqa: PLC0415
            BROKER_LOGIN_RETRY_MESSAGE,
            SESSION_INVALID_RELOGIN_MESSAGE,
            establish_native_session,
            should_keep_session_after_probe_error,
        )
        from flinttrade_gateway.registry import BrokerRegistry  # noqa: PLC0415

        from .native_account_routes import (  # noqa: PLC0415
            _MISSING_REGISTRY_SESSION,
            _candidate_login_timeout_seconds,
            _compare_and_put_registry_session,
            _compare_and_remove_registry_session,
            _compare_and_update_selector_credentials,
            _registry_session_generation,
            _registry_session_generation_matches,
            _run_bounded_candidate_coroutine,
            _selector_credential_generation,
            _selector_credential_generation_matches,
        )

        app = self._app
        self._admission.assert_current(generation)
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

        failures: list[str] = []
        for row in rows:
            account_id = str(row.get("account_id") or "")
            selector = f"{broker}:{account_id}"
            credential_generation = None
            registry_generation = _MISSING_REGISTRY_SESSION

            try:
                credential_generation = _selector_credential_generation(
                    store,
                    broker,
                    account_id,
                )
                stored_credentials = store.retrieve_for(broker, account_id)
                if not _selector_credential_generation_matches(
                    store,
                    broker,
                    account_id,
                    credential_generation,
                ):
                    continue
                registry_generation = _registry_session_generation(
                    registry,
                    broker,
                    account_id,
                )
                # Authenticate and probe against a private registry. No shared
                # session, status, or vault surface changes until the selector is
                # revalidated after the broker call completes. The entire broker
                # call runs behind the daemon candidate boundary so an unkillable
                # SDK thread cannot hold APScheduler or process shutdown open.
                candidate_registry = BrokerRegistry()
                prior_session = (
                    None
                    if registry_generation is _MISSING_REGISTRY_SESSION
                    else registry_generation
                )

                async def authenticate_candidate() -> tuple[dict[str, Any], Any]:
                    credentials = dict(stored_credentials)
                    renew = getattr(adapter, "renew_token", None)
                    if callable(renew) and prior_session is not None:
                        try:
                            renewed = await renew(prior_session)
                            token = str(
                                (renewed or {}).get("accessToken")
                                or (renewed or {}).get("access_token")
                                or ""
                            )
                            if token:
                                credentials = {**credentials, "access_token": token}
                        except Exception as exc:  # noqa: BLE001 - fall back to replay
                            logger.info(
                                "renew_token failed for %s (%s) — replaying vault credentials",
                                broker,
                                type(exc).__name__,
                            )
                    candidate_session = await establish_native_session(
                        adapter,
                        candidate_registry,
                        credentials,
                        broker,
                        account_id,
                        verify=True,
                    )
                    return credentials, candidate_session

                credentials, candidate_session = _run_bounded_candidate_coroutine(
                    authenticate_candidate,
                    _RotationAttemptOwner(),
                    timeout=_candidate_login_timeout_seconds(app.config),
                )
                self._admission.assert_current(generation)

                replayable_credentials = credentials
                replay = getattr(adapter, "replay_credentials", None)
                if callable(replay):
                    try:
                        replayable = replay(dict(credentials), candidate_session)
                        if isinstance(replayable, dict):
                            replayable_credentials = replayable
                    except Exception as exc:  # noqa: BLE001 - write-back remains best-effort
                        logger.warning(
                            "Replayable-credential preparation failed for %s (%s)",
                            broker,
                            type(exc).__name__,
                        )

                committed_generation = credential_generation
                if replayable_credentials != stored_credentials:
                    try:
                        committed_generation = self._admission.publish_if_current(
                            generation,
                            lambda: _compare_and_update_selector_credentials(
                                store,
                                broker,
                                account_id,
                                credential_generation,
                                replayable_credentials,
                            ),
                        )
                    except _RotationAdmissionRevoked:
                        raise
                    except Exception as exc:  # noqa: BLE001 - session can remain live
                        logger.warning(
                            "Refreshed-token persist failed for %s (%s)",
                            broker,
                            type(exc).__name__,
                        )
                        continue
                    if committed_generation is None:
                        continue

                if not _selector_credential_generation_matches(
                    store,
                    broker,
                    account_id,
                    committed_generation,
                ):
                    continue
                registry_published = self._admission.publish_if_current(
                    generation,
                    lambda: _compare_and_put_registry_session(
                        registry,
                        broker,
                        account_id,
                        registry_generation,
                        candidate_session,
                    ),
                )
                if not registry_published:
                    continue
                self._admission.assert_current(generation)
                if (
                    not _selector_credential_generation_matches(
                        store,
                        broker,
                        account_id,
                        committed_generation,
                    )
                    or not _registry_session_generation_matches(
                        registry,
                        broker,
                        account_id,
                        candidate_session,
                    )
                ):
                    self._admission.publish_if_current(
                        generation,
                        lambda: _compare_and_remove_registry_session(
                            registry,
                            broker,
                            account_id,
                            candidate_session,
                        ),
                    )
                    continue
                self._admission.publish_if_current(
                    generation,
                    lambda: app.config.setdefault("NATIVE_SESSION_STATUS", {}).__setitem__(selector, "ok"),
                )
            except _RotationAdmissionRevoked:
                raise
            except Exception as exc:  # noqa: BLE001 - per-selector isolation
                message = (
                    BROKER_LOGIN_RETRY_MESSAGE
                    if should_keep_session_after_probe_error(exc)
                    else SESSION_INVALID_RELOGIN_MESSAGE
                )
                if credential_generation is None or not _selector_credential_generation_matches(
                    store,
                    broker,
                    account_id,
                    credential_generation,
                ):
                    continue
                if message == SESSION_INVALID_RELOGIN_MESSAGE:
                    registry_removed = self._admission.publish_if_current(
                        generation,
                        lambda: _compare_and_remove_registry_session(
                            registry,
                            broker,
                            account_id,
                            registry_generation,
                        ),
                    )
                    if not registry_removed:
                        continue
                elif not _registry_session_generation_matches(
                    registry,
                    broker,
                    account_id,
                    registry_generation,
                ):
                    continue
                self._admission.publish_if_current(
                    generation,
                    lambda: app.config.setdefault("NATIVE_SESSION_STATUS", {}).__setitem__(selector, message),
                )
                failures.append(f"{broker}: {message}")
        if failures:
            raise RuntimeError("; ".join(failures))


def configure_session_rotation(app: Any) -> Blueprint | None:
    """Build the rotator, schedule the morning refresh, return the admin routes.

    Stores the rotator on ``app.config["CREDENTIALS_ROTATOR"]`` and its
    UNSTARTED scheduler on ``app.config["ROTATION_SCHEDULER"]`` (the serve
    path calls ``.start()`` — tests never spawn the thread). Every active
    registered native broker gets a daily 08:05 IST refresh job. Returns
    ``None`` (and logs) when APScheduler is unavailable — rotation then simply
    stays off.
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
    admission = _rotation_admission(app)
    rotator = CredentialsRotator(NativeSessionRefresher(app, admission), scheduler)
    app.config["CREDENTIALS_ROTATOR"] = rotator
    app.config["ROTATION_SCHEDULER"] = scheduler

    # Morning re-auth for active registered natives (jobs queue on the
    # unstarted scheduler and arm when the serve path starts it).
    try:
        from .app import _read_workspace_brokers  # noqa: PLC0415

        registered = [str(s) for s in ((_read_workspace_brokers() or {}).get("registered") or [])]
        active_adapters = set((app.config.get("NATIVE_ADAPTERS") or {}).keys())
        native_brokers = sorted({
            s.split(":", 1)[0]
            for s in registered
            if is_native_broker(s.split(":", 1)[0]) and s.split(":", 1)[0] in active_adapters
        })
        for broker in native_brokers:
            rotator.schedule_daily_refresh(broker, "08:05")
    except Exception as exc:  # noqa: BLE001 - scheduling must not brick the factory
        logger.warning("Could not schedule native session refresh jobs: %s", exc)

    bp = create_rotation_blueprint(rotator)

    @bp.before_request
    def _guard_rotation_writes() -> Any | None:
        """G9 + broker truth — writes need auth and an active native adapter."""
        if request.method not in ("POST", "PUT", "DELETE", "PATCH"):
            return None
        guard = current_app.config.get("BROKER_MGMT_WRITE_GUARD")
        if guard is not None:
            guard_result = guard()
            if guard_result is not None:
                return guard_result

        broker = (request.view_args or {}).get("broker")
        if not broker:
            return None
        active_adapters = set((current_app.config.get("NATIVE_ADAPTERS") or {}).keys())
        if str(broker) not in active_adapters:
            return {
                "status": "error",
                "message": f"'{broker}' is not active for native session refresh.",
            }, 400
        if request.endpoint == "rotation_admin.rotation_schedule":
            body = request.get_json(silent=True) or {}
            if str(body.get("interval", "daily")).lower() == "weekly":
                return {
                    "status": "error",
                    "message": "Native broker sessions support daily refresh only.",
                }, 400
        return None

    return bp
