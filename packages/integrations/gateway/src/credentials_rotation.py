"""Broker credential rotation scheduler.

Some brokers require daily token refresh; others need periodic API-key
rotation.  :class:`CredentialsRotator` wraps a credentials manager and an
APScheduler instance to automate this.

The ``RotationResult`` dataclass records whether each rotation succeeded and
any error detail.

Usage::

    from flinttrade_gateway.credentials_rotation import CredentialsRotator, RotationResult

    rotator = CredentialsRotator(credentials_manager=store, scheduler=scheduler)
    rotator.schedule_daily_refresh("zerodha", time_ist="08:05")
    result = rotator.rotate_now("zerodha")
    print(result.success, result.broker)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("flinttrade.gateway.credentials_rotation")

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class RotationResult:
    """Result of a single credential rotation attempt.

    Attributes:
        broker: Broker identifier (e.g. ``"zerodha"``).
        success: Whether the rotation completed without error.
        rotated_at: Timestamp of the attempt (IST).
        error: Error message if *success* is ``False``, else ``None``.
        rotation_type: ``"refresh"`` (token only) or ``"rotate"`` (new API key).
    """

    broker: str
    success: bool
    rotated_at: datetime = field(default_factory=lambda: datetime.now(IST))
    error: str | None = None
    rotation_type: str = "refresh"


class CredentialsRotator:
    """Rotate broker API credentials on a schedule.

    Some brokers (e.g. Zerodha, Angel) require daily re-authentication to
    refresh the access token.  This class manages automatic token refreshes
    and periodic full API-key rotations via APScheduler.

    Thread-safe: all state mutations are protected by a lock.

    Args:
        credentials_manager: An object that exposes ``list_accounts()`` and
            ``store(account_id, broker, label, credentials, is_primary)``
            methods compatible with
            :class:`~flinttrade_gateway.credentials.CredentialStore`.
        scheduler: An APScheduler ``BackgroundScheduler`` (or compatible)
            instance.  The caller is responsible for starting it before
            scheduling jobs.

    Example::

        rotator = CredentialsRotator(store, scheduler)
        rotator.schedule_daily_refresh("zerodha", "08:05")
        result = rotator.rotate_now("zerodha")
    """

    def __init__(
        self,
        credentials_manager: Any,
        scheduler: Any,
    ) -> None:
        self._manager = credentials_manager
        self._scheduler = scheduler
        self._lock = threading.Lock()

        # Tracks last/next rotation per broker.
        self._last_rotation: dict[str, datetime] = {}
        self._next_rotation: dict[str, datetime | None] = {}

        # Registered job IDs per broker/type so we can replace them.
        self._job_ids: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def schedule_daily_refresh(
        self, broker: str, time_ist: str = "08:00"
    ) -> None:
        """Schedule a daily token refresh for *broker* at *time_ist* (IST).

        Replaces any previously registered daily-refresh job for this broker.

        Args:
            broker: Canonical broker identifier (e.g. ``"zerodha"``).
            time_ist: Time of day in ``"HH:MM"`` 24-hour format (IST).
                Defaults to ``"08:00"``.
        """
        try:
            hour, minute = self._parse_time(time_ist)
        except ValueError as exc:
            raise ValueError(
                f"Invalid time_ist {time_ist!r}: expected HH:MM"
            ) from exc

        job_id = f"cred_refresh_{broker}"

        def _refresh() -> None:
            result = self._do_refresh(broker)
            if result.success:
                logger.info(
                    "Daily credential refresh succeeded for broker=%s", broker
                )
            else:
                logger.error(
                    "Daily credential refresh FAILED for broker=%s: %s",
                    broker,
                    result.error,
                )

        with self._lock:
            self._scheduler.add_job(
                _refresh,
                trigger="cron",
                hour=hour,
                minute=minute,
                id=job_id,
                replace_existing=True,
                timezone="Asia/Kolkata",
            )
            self._job_ids[job_id] = job_id

            # Compute next run time (approximate — IST today or tomorrow).
            now_ist = datetime.now(IST)
            next_run = now_ist.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if next_run <= now_ist:
                next_run = next_run.replace(day=next_run.day + 1)
            self._next_rotation[broker] = next_run

        logger.info(
            "Scheduled daily credential refresh for broker=%s at %s IST",
            broker,
            time_ist,
        )

    def schedule_weekly_rotation(
        self, broker: str, day: int, time_ist: str
    ) -> None:
        """Schedule a weekly full API-key rotation for *broker*.

        Args:
            broker: Canonical broker identifier.
            day: Day of week (0=Monday … 6=Sunday).
            time_ist: Time of day in ``"HH:MM"`` format (IST).

        Raises:
            ValueError: If *day* is out of range or *time_ist* is malformed.
        """
        if not 0 <= day <= 6:
            raise ValueError(f"day must be 0–6 (Mon–Sun), got {day}")

        try:
            hour, minute = self._parse_time(time_ist)
        except ValueError as exc:
            raise ValueError(
                f"Invalid time_ist {time_ist!r}: expected HH:MM"
            ) from exc

        job_id = f"cred_rotate_{broker}"

        def _rotate() -> None:
            result = self._do_rotation(broker)
            if result.success:
                logger.info(
                    "Weekly API-key rotation succeeded for broker=%s", broker
                )
            else:
                logger.error(
                    "Weekly API-key rotation FAILED for broker=%s: %s",
                    broker,
                    result.error,
                )

        with self._lock:
            self._scheduler.add_job(
                _rotate,
                trigger="cron",
                day_of_week=day,
                hour=hour,
                minute=minute,
                id=job_id,
                replace_existing=True,
                timezone="Asia/Kolkata",
            )
            self._job_ids[job_id] = job_id

        logger.info(
            "Scheduled weekly rotation for broker=%s day=%d at %s IST",
            broker,
            day,
            time_ist,
        )

    # ------------------------------------------------------------------
    # Immediate rotation
    # ------------------------------------------------------------------

    def rotate_now(self, broker: str) -> RotationResult:
        """Immediately trigger a credential refresh for *broker*.

        Args:
            broker: Canonical broker identifier.

        Returns:
            :class:`RotationResult` describing the outcome.
        """
        result = self._do_refresh(broker)
        if result.success:
            logger.info("Manual rotation succeeded for broker=%s", broker)
        else:
            logger.warning(
                "Manual rotation failed for broker=%s: %s", broker, result.error
            )
        return result

    # ------------------------------------------------------------------
    # Status queries
    # ------------------------------------------------------------------

    def last_rotation(self, broker: str) -> datetime | None:
        """Return the timestamp of the last successful rotation.

        Args:
            broker: Canonical broker identifier.

        Returns:
            IST :class:`~datetime.datetime` or ``None`` if never rotated.
        """
        with self._lock:
            return self._last_rotation.get(broker)

    def next_rotation(self, broker: str) -> datetime | None:
        """Return the scheduled time of the next rotation.

        Args:
            broker: Canonical broker identifier.

        Returns:
            IST :class:`~datetime.datetime` or ``None`` if no job is
            scheduled for this broker.
        """
        with self._lock:
            return self._next_rotation.get(broker)

    def rotation_status(self) -> list[dict[str, Any]]:
        """Return status information for all brokers that have been configured.

        Returns:
            List of dicts with ``broker``, ``last_rotation``, ``next_rotation``,
            and ``jobs`` fields.
        """
        with self._lock:
            all_brokers = set(self._last_rotation) | set(self._next_rotation)
            return [
                {
                    "broker": broker,
                    "last_rotation": (
                        self._last_rotation[broker].isoformat()
                        if broker in self._last_rotation
                        else None
                    ),
                    "next_rotation": (
                        self._next_rotation[broker].isoformat()
                        if self._next_rotation.get(broker) is not None
                        else None
                    ),
                    "jobs": [
                        jid
                        for jid in self._job_ids
                        if broker in jid
                    ],
                }
                for broker in sorted(all_brokers)
            ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_refresh(self, broker: str) -> RotationResult:
        """Perform a token refresh for *broker*.

        In the current implementation this marks the rotation as successful
        and records the timestamp.  A real implementation would call the
        broker's re-auth endpoint via the credentials manager.

        Args:
            broker: Canonical broker identifier.

        Returns:
            :class:`RotationResult` with ``rotation_type="refresh"``.
        """
        now = datetime.now(IST)
        try:
            # Hook: try to call a ``refresh_token`` method if the manager
            # exposes one.  This keeps the rotator decoupled from any
            # specific broker API.
            if hasattr(self._manager, "refresh_token"):
                self._manager.refresh_token(broker)

            with self._lock:
                self._last_rotation[broker] = now

            return RotationResult(
                broker=broker,
                success=True,
                rotated_at=now,
                rotation_type="refresh",
            )
        except Exception as exc:
            logger.exception(
                "Credential refresh error for broker=%s", broker
            )
            return RotationResult(
                broker=broker,
                success=False,
                rotated_at=now,
                error=str(exc),
                rotation_type="refresh",
            )

    def _do_rotation(self, broker: str) -> RotationResult:
        """Perform a full API-key rotation for *broker*.

        Args:
            broker: Canonical broker identifier.

        Returns:
            :class:`RotationResult` with ``rotation_type="rotate"``.
        """
        now = datetime.now(IST)
        try:
            if hasattr(self._manager, "rotate_api_key"):
                self._manager.rotate_api_key(broker)

            with self._lock:
                self._last_rotation[broker] = now

            return RotationResult(
                broker=broker,
                success=True,
                rotated_at=now,
                rotation_type="rotate",
            )
        except Exception as exc:
            logger.exception(
                "API-key rotation error for broker=%s", broker
            )
            return RotationResult(
                broker=broker,
                success=False,
                rotated_at=now,
                error=str(exc),
                rotation_type="rotate",
            )

    @staticmethod
    def _parse_time(time_ist: str) -> tuple[int, int]:
        """Parse a ``"HH:MM"`` string into (hour, minute).

        Args:
            time_ist: Time string in 24-hour ``"HH:MM"`` format.

        Returns:
            Tuple of ``(hour, minute)`` integers.

        Raises:
            ValueError: If the string is not in the expected format or
                the values are out of range.
        """
        parts = time_ist.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Expected HH:MM, got {time_ist!r}")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(
                f"Time out of range: hour={hour}, minute={minute}"
            )
        return hour, minute
