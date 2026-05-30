"""Security: IP tracking, threat detection, and auto-ban.

Tracks per-IP request counts, authentication failures, and 404 floods.
Automatically bans IPs that exceed configurable thresholds.  All state is
in-memory and thread-safe; no external dependencies are required.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("flinttrade.security")


@dataclass
class IPRecord:
    """Per-IP tracking record.

    Attributes:
        ip: The IP address string being tracked.
        request_count: Total number of requests seen from this IP.
        failed_auth_count: Number of authentication failures from this IP.
        not_found_count: Number of 404 responses returned to this IP.
        first_seen: Unix timestamp of the first request from this IP.
        last_seen: Unix timestamp of the most recent request from this IP.
        is_banned: Whether this IP is currently banned.
        ban_reason: Human-readable reason the ban was applied, or ``None``.
        ban_expires: Unix timestamp when the ban expires, or ``None`` for
            a permanent ban.
    """

    ip: str
    request_count: int = 0
    failed_auth_count: int = 0
    not_found_count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    is_banned: bool = False
    ban_reason: str | None = None
    ban_expires: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict.

        Returns:
            dict with all fields using JSON-serialisable types.
        """
        return {
            "ip": self.ip,
            "request_count": self.request_count,
            "failed_auth_count": self.failed_auth_count,
            "not_found_count": self.not_found_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "is_banned": self.is_banned,
            "ban_reason": self.ban_reason,
            "ban_expires": self.ban_expires,
        }


class SecurityMonitor:
    """Thread-safe IP tracking and threat detection monitor.

    Tracks every IP that interacts with the server.  IPs that exceed
    either the *auth_ban_threshold* (failed logins) or the
    *notfound_ban_threshold* (404 floods) are automatically banned for
    *ban_duration* seconds.  Bans can also be applied and lifted manually.

    Args:
        auth_ban_threshold: Number of authentication failures before an IP
            is auto-banned.  Defaults to 10.
        notfound_ban_threshold: Number of 404 responses before an IP is
            auto-banned.  Defaults to 50.
        ban_duration: How long (seconds) an auto-ban lasts.  Defaults to
            3600 (1 hour).  Pass ``None`` for permanent auto-bans.

    Example:
        >>> sm = SecurityMonitor(auth_ban_threshold=3)
        >>> sm.record_request("1.2.3.4")
        >>> sm.record_auth_failure("1.2.3.4")
        >>> sm.record_auth_failure("1.2.3.4")
        >>> sm.record_auth_failure("1.2.3.4")
        >>> sm.is_banned("1.2.3.4")
        True
    """

    def __init__(
        self,
        auth_ban_threshold: int = 10,
        notfound_ban_threshold: int = 50,
        ban_duration: int = 3600,
    ) -> None:
        self._auth_ban_threshold = auth_ban_threshold
        self._notfound_ban_threshold = notfound_ban_threshold
        self._ban_duration = ban_duration
        self._records: dict[str, IPRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_request(self, ip: str) -> None:
        """Increment the request counter for *ip*.

        Creates a new :class:`IPRecord` if this is the first request from
        the given IP.

        Args:
            ip: The client IP address.
        """
        with self._lock:
            rec = self._get_or_create(ip)
            rec.request_count += 1
            rec.last_seen = time.time()

    def record_auth_failure(self, ip: str) -> None:
        """Increment the authentication failure counter for *ip*.

        Automatically bans the IP if *auth_ban_threshold* is reached.

        Args:
            ip: The client IP address that submitted bad credentials.
        """
        with self._lock:
            rec = self._get_or_create(ip)
            rec.failed_auth_count += 1
            rec.last_seen = time.time()
            if rec.failed_auth_count >= self._auth_ban_threshold and not rec.is_banned:
                self._apply_ban(
                    rec,
                    f"Exceeded {self._auth_ban_threshold} authentication failures",
                    self._ban_duration,
                )

    def record_not_found(self, ip: str) -> None:
        """Increment the 404 counter for *ip*.

        Automatically bans the IP if *notfound_ban_threshold* is reached.

        Args:
            ip: The client IP address that triggered the 404.
        """
        with self._lock:
            rec = self._get_or_create(ip)
            rec.not_found_count += 1
            rec.last_seen = time.time()
            if rec.not_found_count >= self._notfound_ban_threshold and not rec.is_banned:
                self._apply_ban(
                    rec,
                    f"Exceeded {self._notfound_ban_threshold} not-found (404) responses",
                    self._ban_duration,
                )

    # ------------------------------------------------------------------
    # Ban management
    # ------------------------------------------------------------------

    def ban_ip(self, ip: str, reason: str, duration: int | None = None) -> None:
        """Manually ban an IP address.

        Args:
            ip: The IP address to ban.
            reason: Human-readable justification for the ban.
            duration: Ban length in seconds, or ``None`` for a permanent ban.
        """
        with self._lock:
            rec = self._get_or_create(ip)
            self._apply_ban(rec, reason, duration)

    def unban_ip(self, ip: str) -> None:
        """Lift the ban on an IP address.

        Does nothing if the IP is not currently banned or not tracked.

        Args:
            ip: The IP address to unban.
        """
        with self._lock:
            rec = self._records.get(ip)
            if rec is not None and rec.is_banned:
                rec.is_banned = False
                rec.ban_reason = None
                rec.ban_expires = None
                logger.info("Unbanned IP %s", ip)

    def is_banned(self, ip: str) -> bool:
        """Check whether *ip* is currently banned.

        Expired bans are automatically lifted before the check is performed.

        Args:
            ip: The IP address to check.

        Returns:
            ``True`` if the IP has an active ban, ``False`` otherwise.
        """
        with self._lock:
            rec = self._records.get(ip)
            if rec is None:
                return False
            # Lift expired bans
            if rec.is_banned and rec.ban_expires is not None:
                if time.time() >= rec.ban_expires:
                    rec.is_banned = False
                    rec.ban_reason = None
                    rec.ban_expires = None
                    logger.debug("Ban on %s has expired — lifted automatically", ip)
            return rec.is_banned

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about tracked IPs.

        Returns:
            dict with keys:
                ``total_ips`` (int): total IPs tracked.
                ``banned_count`` (int): number currently banned.
                ``top_offenders`` (list[dict]): up to 10 IPs ordered by
                    ``failed_auth_count`` descending, each as a dict.
        """
        with self._lock:
            self._expire_all_bans()
            total = len(self._records)
            banned = sum(1 for r in self._records.values() if r.is_banned)
            top_offenders = sorted(
                self._records.values(),
                key=lambda r: r.failed_auth_count,
                reverse=True,
            )[:10]
            return {
                "total_ips": total,
                "banned_count": banned,
                "top_offenders": [r.to_dict() for r in top_offenders],
            }

    def get_banned_ips(self) -> list[IPRecord]:
        """Return all currently banned IP records.

        Expired bans are lifted before the list is built.

        Returns:
            List of :class:`IPRecord` where ``is_banned`` is ``True``.
        """
        with self._lock:
            self._expire_all_bans()
            return [r for r in self._records.values() if r.is_banned]

    def get_all_records(self) -> list[IPRecord]:
        """Return all tracked IP records.

        Returns:
            List of every :class:`IPRecord`, ordered by ``last_seen`` descending.
        """
        with self._lock:
            self._expire_all_bans()
            return sorted(self._records.values(), key=lambda r: r.last_seen, reverse=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, ip: str) -> IPRecord:
        """Return existing record for *ip* or create a new one.

        Must be called while holding ``self._lock``.

        Args:
            ip: The IP address key.

        Returns:
            The :class:`IPRecord` for the given IP.
        """
        if ip not in self._records:
            self._records[ip] = IPRecord(ip=ip)
        return self._records[ip]

    def _apply_ban(self, rec: IPRecord, reason: str, duration: int | None) -> None:
        """Apply a ban to an existing record.

        Must be called while holding ``self._lock``.

        Args:
            rec: The :class:`IPRecord` to ban.
            reason: Human-readable reason for the ban.
            duration: Ban length in seconds, or ``None`` for permanent.
        """
        rec.is_banned = True
        rec.ban_reason = reason
        rec.ban_expires = (time.time() + duration) if duration is not None else None
        expires_in = f"{duration}s" if duration is not None else "permanent"
        logger.warning("Banned IP %s — reason: %s — duration: %s", rec.ip, reason, expires_in)

    def _expire_all_bans(self) -> None:
        """Lift all expired timed bans.

        Must be called while holding ``self._lock``.
        """
        now = time.time()
        for rec in self._records.values():
            if rec.is_banned and rec.ban_expires is not None and now >= rec.ban_expires:
                rec.is_banned = False
                rec.ban_reason = None
                rec.ban_expires = None
