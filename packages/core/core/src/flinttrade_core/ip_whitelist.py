"""IP Whitelist — per-user IP restrictions with CIDR support.

If a user enables the whitelist, only requests from whitelisted CIDRs/IPs
are allowed through.  If the whitelist is disabled (or empty), all IPs are
allowed (open-by-default for new installs).

Storage is backed by an in-memory dict keyed by ``user_id``.  An optional
``db_path`` argument is accepted for future persistent storage (currently
unused — the in-memory store survives for the lifetime of the process).

Usage::

    wl = IPWhitelist()
    wl.add_ip("alice", "10.0.0.1", label="Office")
    wl.add_ip("alice", "192.168.1.0/24", label="Home network")
    wl.enable("alice")
    wl.is_whitelisted("alice", "192.168.1.50")  # True
    wl.is_whitelisted("alice", "8.8.8.8")        # False
"""

from __future__ import annotations

import ipaddress
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request

logger = logging.getLogger("flinttrade.ip_whitelist")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class _WhitelistEntry:
    """A single whitelisted network or host.

    Attributes:
        ip: The original IP/CIDR string as supplied by the caller.
        label: Human-readable label (e.g. ``"Office"``).
        network: Parsed :class:`ipaddress.IPv4Network` or
            :class:`ipaddress.IPv6Network` for CIDR matching.
    """

    ip: str
    label: str
    network: ipaddress.IPv4Network | ipaddress.IPv6Network

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation.

        Returns:
            dict with ``ip`` and ``label`` keys.
        """
        return {"ip": self.ip, "label": self.label}


@dataclass
class _UserConfig:
    """Per-user whitelist configuration.

    Attributes:
        enabled: When ``True``, only whitelisted IPs are accepted.
        entries: Ordered list of whitelisted networks/hosts.
    """

    enabled: bool = False
    entries: list[_WhitelistEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# IPWhitelist
# ---------------------------------------------------------------------------


class IPWhitelist:
    """Thread-safe per-user IP whitelist with CIDR notation support.

    Args:
        db_path: Reserved for future persistent storage — currently unused.

    Example::

        wl = IPWhitelist()
        wl.add_ip("alice", "10.0.0.0/8", label="Corporate")
        wl.enable("alice")
        assert wl.is_whitelisted("alice", "10.1.2.3")
        assert not wl.is_whitelisted("alice", "8.8.8.8")
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path  # reserved for future persistence
        self._users: dict[str, _UserConfig] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_ip(self, user_id: str, ip: str, label: str = "") -> None:
        """Add an IP address or CIDR block to a user's whitelist.

        Duplicate entries (same CIDR) are silently skipped so the
        operation is idempotent.

        Args:
            user_id: The user whose whitelist to update.
            ip: An IPv4/IPv6 address (``"10.0.0.1"``) or CIDR block
                (``"10.0.0.0/24"``).
            label: Optional human-readable description.

        Raises:
            ValueError: If ``ip`` is not a valid address or CIDR.
        """
        network = _parse_network(ip)
        with self._lock:
            cfg = self._get_or_create(user_id)
            # Idempotency — skip if already present
            if any(e.network == network for e in cfg.entries):
                return
            cfg.entries.append(_WhitelistEntry(ip=ip, label=label, network=network))
        logger.debug("Added IP %s (%s) to whitelist for user %s", ip, label, user_id)

    def remove_ip(self, user_id: str, ip: str) -> bool:
        """Remove an IP/CIDR from a user's whitelist.

        Args:
            user_id: The user whose whitelist to update.
            ip: The address or CIDR to remove (must match the value
                originally passed to :meth:`add_ip`).

        Returns:
            ``True`` if the entry was found and removed, ``False``
            if it was not present.

        Raises:
            ValueError: If ``ip`` is not a valid address or CIDR.
        """
        network = _parse_network(ip)
        with self._lock:
            cfg = self._users.get(user_id)
            if cfg is None:
                return False
            before = len(cfg.entries)
            cfg.entries = [e for e in cfg.entries if e.network != network]
            removed = len(cfg.entries) < before
        if removed:
            logger.debug("Removed IP %s from whitelist for user %s", ip, user_id)
        return removed

    def enable(self, user_id: str) -> None:
        """Activate whitelist enforcement for a user.

        Args:
            user_id: The user to enable the whitelist for.
        """
        with self._lock:
            self._get_or_create(user_id).enabled = True
        logger.info("IP whitelist ENABLED for user %s", user_id)

    def disable(self, user_id: str) -> None:
        """Deactivate whitelist enforcement for a user.

        After calling this, :meth:`is_whitelisted` always returns
        ``True`` for this user (all IPs allowed).

        Args:
            user_id: The user to disable the whitelist for.
        """
        with self._lock:
            self._get_or_create(user_id).enabled = False
        logger.info("IP whitelist DISABLED for user %s", user_id)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_whitelisted(self, user_id: str, ip: str) -> bool:
        """Return whether *ip* is allowed for *user_id*.

        The check follows three rules in order:

        1. If the whitelist is **disabled** for the user → ``True`` (open).
        2. If the whitelist is **empty** → ``True`` (open).
        3. Otherwise → ``True`` iff *ip* falls within at least one
           whitelisted network/address.

        Args:
            user_id: The user to check against.
            ip: The client IP address to evaluate.

        Returns:
            ``True`` if the request should be allowed, ``False`` otherwise.
        """
        with self._lock:
            cfg = self._users.get(user_id)
        if cfg is None or not cfg.enabled or not cfg.entries:
            return True
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            logger.warning("Invalid IP address in whitelist check: %r", ip)
            return False
        return any(addr in entry.network for entry in cfg.entries)

    def list_ips(self, user_id: str) -> list[dict[str, str]]:
        """Return all whitelisted entries for a user.

        Args:
            user_id: The user whose entries to retrieve.

        Returns:
            List of dicts, each with ``ip`` and ``label`` keys.
            Empty list if the user has no whitelist configured.
        """
        with self._lock:
            cfg = self._users.get(user_id)
        if cfg is None:
            return []
        return [e.to_dict() for e in cfg.entries]

    def is_enabled(self, user_id: str) -> bool:
        """Return whether whitelist enforcement is active for a user.

        Args:
            user_id: The user to query.

        Returns:
            ``True`` if enforcement is enabled, ``False`` otherwise.
        """
        with self._lock:
            cfg = self._users.get(user_id)
        return cfg.enabled if cfg is not None else False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_or_create(self, user_id: str) -> _UserConfig:
        """Return existing config or create a new default one.

        Must be called while holding ``self._lock``.
        """
        if user_id not in self._users:
            self._users[user_id] = _UserConfig()
        return self._users[user_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_network(ip: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Parse an IP address or CIDR block into a network object.

    A bare host address (no prefix) is treated as a /32 (IPv4) or /128
    (IPv6) network so that it can be checked with ``addr in network``.

    Args:
        ip: IPv4/IPv6 address or CIDR string.

    Returns:
        Parsed network object.

    Raises:
        ValueError: If the string cannot be parsed.
    """
    ip = ip.strip()
    try:
        # ``strict=False`` allows e.g. "192.168.1.1/24" → "192.168.1.0/24"
        return ipaddress.ip_network(ip, strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid IP address or CIDR: {ip!r}") from exc


# ---------------------------------------------------------------------------
# Flask middleware
# ---------------------------------------------------------------------------


def check_ip_whitelist(
    whitelist: IPWhitelist,
    user_id_func: Any,
) -> Any | None:
    """Check the current request IP against the user's whitelist.

    Intended for use inside a ``@app.before_request`` handler.

    Args:
        whitelist: The :class:`IPWhitelist` instance to query.
        user_id_func: A zero-argument callable that returns the current
            user ID string (e.g. read from ``flask.g`` or JWT).

    Returns:
        ``None`` if the request is allowed, or a 403 Flask response
        tuple ``(response, 403)`` if it should be blocked.
    """
    try:
        user_id = user_id_func()
    except Exception:
        return None  # Cannot determine user — allow through

    if user_id is None:
        return None  # Unauthenticated requests handled by auth middleware

    client_ip = request.remote_addr or "unknown"
    if not whitelist.is_whitelisted(user_id, client_ip):
        logger.warning(
            "Blocked request from %s — not in whitelist for user %s", client_ip, user_id
        )
        return jsonify({"status": "error", "message": "IP not whitelisted"}), 403
    return None


# ---------------------------------------------------------------------------
# Admin Blueprint
# ---------------------------------------------------------------------------


def make_ip_whitelist_bp(whitelist: IPWhitelist) -> Blueprint:
    """Create and return the IP whitelist admin Blueprint.

    Mounts at ``/admin/ip-whitelist``.

    Routes:

    - ``GET  /admin/ip-whitelist/<user_id>``       — list entries + status
    - ``POST /admin/ip-whitelist/<user_id>``       — add an IP/CIDR
    - ``DELETE /admin/ip-whitelist/<user_id>/<ip>``— remove an entry
    - ``POST /admin/ip-whitelist/<user_id>/enable`` — enable enforcement
    - ``POST /admin/ip-whitelist/<user_id>/disable``— disable enforcement

    Args:
        whitelist: The shared :class:`IPWhitelist` instance.

    Returns:
        Configured :class:`flask.Blueprint`.
    """
    bp = Blueprint("ip_whitelist", __name__, url_prefix="/admin/ip-whitelist")

    @bp.route("/<user_id>", methods=["GET"])
    def list_entries(user_id: str) -> tuple[Response, int]:
        """List all whitelisted IPs for *user_id*.

        Returns:
            JSON ``{"status": "success", "enabled": bool, "ips": [...]}``.
        """
        return (
            jsonify(
                {
                    "status": "success",
                    "enabled": whitelist.is_enabled(user_id),
                    "ips": whitelist.list_ips(user_id),
                }
            ),
            200,
        )

    @bp.route("/<user_id>", methods=["POST"])
    def add_entry(user_id: str) -> tuple[Response, int]:
        """Add an IP/CIDR to *user_id*'s whitelist.

        Request body: ``{"ip": "10.0.0.1", "label": "optional"}``.

        Returns:
            JSON ``{"status": "success"}`` or error.
        """
        body: dict[str, Any] = request.get_json(silent=True) or {}
        ip: str = body.get("ip", "").strip()
        label: str = body.get("label", "")
        if not ip:
            return jsonify({"status": "error", "message": "ip is required"}), 400
        try:
            whitelist.add_ip(user_id, ip, label=label)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        return jsonify({"status": "success"}), 201

    @bp.route("/<user_id>/<path:ip>", methods=["DELETE"])
    def remove_entry(user_id: str, ip: str) -> tuple[Response, int]:
        """Remove an IP/CIDR from *user_id*'s whitelist.

        Returns:
            JSON ``{"status": "success"}`` or ``404`` if not found.
        """
        try:
            removed = whitelist.remove_ip(user_id, ip)
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        if not removed:
            return jsonify({"status": "error", "message": "IP not found"}), 404
        return jsonify({"status": "success"}), 200

    @bp.route("/<user_id>/enable", methods=["POST"])
    def enable_whitelist(user_id: str) -> tuple[Response, int]:
        """Enable whitelist enforcement for *user_id*.

        Returns:
            JSON ``{"status": "success"}``.
        """
        whitelist.enable(user_id)
        return jsonify({"status": "success"}), 200

    @bp.route("/<user_id>/disable", methods=["POST"])
    def disable_whitelist(user_id: str) -> tuple[Response, int]:
        """Disable whitelist enforcement for *user_id*.

        Returns:
            JSON ``{"status": "success"}``.
        """
        whitelist.disable(user_id)
        return jsonify({"status": "success"}), 200

    return bp
