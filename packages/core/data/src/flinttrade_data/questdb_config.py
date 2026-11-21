"""Shared QuestDB connection and write-safety helpers.

QuestDB writes are off by default. Enable them with ``QUESTDB_WRITE_ENABLED=true``
or by passing ``allow_writes=True`` when constructing a client or bridge. Reads
are not affected.
"""

from __future__ import annotations

import os
import re

# Default endpoints when no constructor argument or environment override is set.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 9000
DEFAULT_ILP_PORT = 9009
DEFAULT_PG_PORT = 8812

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_COMMENT_RE = re.compile(r"(--[^\n]*|/\*.*?\*/)", re.DOTALL)
_STRING_RE = re.compile(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\$\$.*?\$\$)", re.DOTALL)
_LEADING_WORD_RE = re.compile(r"^\s*([A-Za-z]+)\b")
_READ_START = frozenset({"SELECT", "SHOW", "EXPLAIN", "DESCRIBE", "DESC", "WITH"})
_WRITE_WORD_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|RENAME|GRANT|REVOKE|COPY|"
    r"BACKUP|RESTORE|SNAPSHOT|VACUUM|REPAIR|EDIT|INTO)\b",
    re.IGNORECASE,
)


class QuestDBWritesDisabledError(Exception):
    """Raised when a QuestDB write is attempted while writes are disabled."""

    def __init__(self, operation: str = "write") -> None:
        self.operation = operation
        super().__init__(
            f"QuestDB writes are disabled; {operation} was refused. "
            "Enable writes by setting QUESTDB_WRITE_ENABLED=true "
            "or by passing allow_writes=True."
        )


def writes_enabled_from_env() -> bool:
    """Return whether ``QUESTDB_WRITE_ENABLED`` explicitly enables writes.

    Unset, empty, unrecognised, and false-like values all stay disabled
    (fail-closed). Only ``1``, ``true``, ``yes``, and ``on`` (any case) enable
    writes.
    """
    raw = os.environ.get("QUESTDB_WRITE_ENABLED", "")
    return raw.strip().lower() in _TRUTHY


def resolve_allow_writes(allow_writes: bool | None) -> bool:
    """Resolve the write flag from an explicit argument or the environment.

    Args:
        allow_writes: Explicit constructor override, or ``None`` to read
            ``QUESTDB_WRITE_ENABLED``.

    Returns:
        ``True`` only when writes have been explicitly enabled.
    """
    if allow_writes is not None:
        return bool(allow_writes)
    return writes_enabled_from_env()


def env_str(name: str, default: str) -> str:
    """Return a stripped environment string, or ``default`` when unset or empty."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def env_port(name: str, default: int) -> int:
    """Return an integer port from the environment, or ``default`` when unset.

    Raises:
        ValueError: If the variable is set to a non-integer or a value outside
            1–65535.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer port, got {raw!r}") from exc
    if not (1 <= value <= 65535):
        raise ValueError(f"{name} must be a port between 1 and 65535, got {value}")
    return value


def resolve_host(host: str | None) -> str:
    """Return ``host``, or ``QUESTDB_HOST``, or the default loopback address."""
    if host is not None:
        return host
    return env_str("QUESTDB_HOST", DEFAULT_HOST)


def resolve_http_port(port: int | None) -> int:
    """Return ``port``, or ``QUESTDB_HTTP_PORT``, or the default HTTP port."""
    if port is not None:
        return port
    return env_port("QUESTDB_HTTP_PORT", DEFAULT_HTTP_PORT)


def resolve_ilp_port(port: int | None) -> int:
    """Return ``port``, or ``QUESTDB_ILP_PORT``, or the default ILP port."""
    if port is not None:
        return port
    return env_port("QUESTDB_ILP_PORT", DEFAULT_ILP_PORT)


def resolve_pg_port(port: int | None) -> int:
    """Return ``port``, or ``QUESTDB_PG_PORT``, or the default PostgreSQL-wire port."""
    if port is not None:
        return port
    return env_port("QUESTDB_PG_PORT", DEFAULT_PG_PORT)


def require_writes(allow_writes: bool, operation: str) -> None:
    """Raise :class:`QuestDBWritesDisabledError` when writes are disabled."""
    if not allow_writes:
        raise QuestDBWritesDisabledError(operation)


def is_read_only_sql(sql: str) -> bool:
    """Return ``True`` when ``sql`` is a recognised read-only statement.

    Used to keep ``query()`` safe while writes are disabled. The check is
    fail-closed: comments and string literals are stripped, the statement must
    start with a read keyword (``SELECT``, ``SHOW``, ``EXPLAIN``, ``DESCRIBE``,
    ``DESC``, or ``WITH``), and it must not contain a write keyword.
    """
    if not isinstance(sql, str) or not sql.strip():
        return False
    stripped = _STRING_RE.sub(" ", _COMMENT_RE.sub(" ", sql)).strip()
    match = _LEADING_WORD_RE.match(stripped)
    if not match or match.group(1).upper() not in _READ_START:
        return False
    return _WRITE_WORD_RE.search(stripped) is None
