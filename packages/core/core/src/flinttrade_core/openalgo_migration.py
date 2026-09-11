"""Private, inert OpenAlgo upgrade inputs and exact desired-state parsing.

These values neither authenticate nor confer mutation authority. The account
coordinator must bind them to durable installation/source receipts before use.
No reader discovers paths, reads the process environment or creates clients.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from .broker_identity import BrokerSelector
from .broker_setup import BrokerSetupValidationError, normalise_broker_setup
from .secure_file import HeldOwnerDirectory
from .service_connection_transactions import decode
from .workspace_migrations import MIGRATIONS

_DEFAULT_SELECTOR = BrokerSelector("openalgo", "default")
_CONNECTION_FIELDS = frozenset({"host", "port", "ws_port", "api_key"})


class OpenAlgoMigrationInputError(ValueError):
    """Malformed private input; values are never reflected to callers."""

    def __init__(self) -> None:
        super().__init__("openalgo_migration_input_invalid")


class MixedOpenAlgoAuthoritiesError(ValueError):
    """Telegram and exact account setup require separate logical actions."""

    def __init__(self) -> None:
        super().__init__("mixed_authorities")


class OpenAlgoMigrationConflict(ValueError):
    """Legacy sources disagree; preserve originals for explicit reconciliation."""

    def __init__(self) -> None:
        super().__init__("openalgo_migration_conflict")


@dataclass(frozen=True, slots=True)
class LegacyOpenAlgoInput:
    """Unverified private source; not serialisable as a public config DTO."""

    source_kind: Literal["legacy_openalgo_env", "legacy_openalgo_workspace"]
    _setup_json: str = field(repr=False)
    credential: str | None = field(repr=False)

    @property
    def setup(self) -> dict[str, object]:
        """Return a detached copy so an admitted source cannot be mutated."""
        return json.loads(self._setup_json)


@dataclass(frozen=True, slots=True)
class OpenAlgoSelectorUpdate:
    """Only setup and optional replacement; omission always preserves a key."""

    _setup_json: str = field(repr=False)
    credential_action: Literal["preserve", "replace"]
    credential: str | None = field(repr=False)

    @property
    def setup(self) -> dict[str, object]:
        return json.loads(self._setup_json)


@dataclass(frozen=True, slots=True)
class TelegramUsernameUpdate:
    """Independent workspace change with no account setup/credential fields."""

    username: str


@dataclass(frozen=True, slots=True)
class LegacyFileIdentity:
    """Physical source observation; not a digest of credential material."""

    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True, slots=True)
class LegacyOpenAlgoFile:
    """Private original retained until durable canonical commit/retirement.

    Retirement must revalidate this observation under the writer fence. Merely
    constructing or reading this value never authorises replacing the source.
    """

    filename: str
    directory_device: int
    directory_inode: int
    identity: LegacyFileIdentity
    source: LegacyOpenAlgoInput | None = field(repr=False)
    original_text: str = field(repr=False)


def _port(value: object) -> int:
    if type(value) is str and re.fullmatch(r"[0-9]{1,5}", value):
        value = int(value)
    if type(value) is not int or not 1 <= value <= 65535:
        raise OpenAlgoMigrationInputError
    return value


def _credential(value: object) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > 16 * 1024:
        raise OpenAlgoMigrationInputError
    if value == "your_openalgo_api_key_here":
        raise OpenAlgoMigrationInputError
    return value


def _normalise(setup: dict[str, object]) -> str:
    try:
        return normalise_broker_setup(_DEFAULT_SELECTOR, setup)
    except BrokerSetupValidationError:
        raise OpenAlgoMigrationInputError from None


def _base_url(host: object, port: object | None, *, replace_port: bool = False) -> str:
    # Validate first: urllib must never silently discard whitespace or controls.
    canonical = json.loads(_normalise({"base_url": host}))["base_url"]
    if port is None:
        return canonical
    chosen_port = _port(port)
    parsed = urlsplit(canonical)
    if parsed.port is not None and not replace_port:
        return canonical
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = "[" + hostname + "]"
    return urlunsplit((parsed.scheme, f"{hostname}:{chosen_port}", "", "", ""))


def _legacy_input(
    values: Mapping[str, object], kind: Literal["legacy_openalgo_env", "legacy_openalgo_workspace"],
) -> LegacyOpenAlgoInput | None:
    fields = {key: values[key] for key in _CONNECTION_FIELDS if key in values and values[key] not in (None, "")}
    if not fields:
        return None
    if "host" not in fields:
        raise OpenAlgoMigrationInputError
    setup: dict[str, object] = {"base_url": _base_url(fields["host"], fields.get("port"))}
    if "ws_port" in fields:
        setup["ws_port"] = _port(fields["ws_port"])
    return LegacyOpenAlgoInput(
        kind, _normalise(setup), _credential(fields["api_key"]) if "api_key" in fields else None,
    )


def read_legacy_openalgo_env(
    environ: Mapping[str, object], *, consumed: bool = False,
) -> LegacyOpenAlgoInput | None:
    """Read only explicitly supplied env facts, once per installation lineage.

    ``consumed`` must come from the installation migration receipt, never from
    workspace configuration or the target vault's presence/incarnation.
    """
    if type(consumed) is not bool:
        raise OpenAlgoMigrationInputError
    if consumed:
        return None
    if not isinstance(environ, Mapping):
        raise OpenAlgoMigrationInputError
    return _legacy_input({
        name: environ.get("OPENALGO_" + name.upper()) for name in _CONNECTION_FIELDS
    }, "legacy_openalgo_env")


def read_legacy_openalgo_workspace(config: Mapping[str, object]) -> LegacyOpenAlgoInput | None:
    """Read one already owner-validated live or allowlisted rollback snapshot."""
    if not isinstance(config, Mapping):
        raise OpenAlgoMigrationInputError
    section = config.get("openalgo")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise OpenAlgoMigrationInputError
    return _legacy_input(section, "legacy_openalgo_workspace")


def read_legacy_openalgo_files(workspace_dir: Path) -> tuple[LegacyOpenAlgoFile, ...]:
    """Read exact supported originals without globbing, migration or deletion.

    Live authority versions and installation consumption are bound separately
    by the coordinator. The retained bytes belong only in its encrypted prior
    snapshot/quarantine, never in a journal, DTO, log or ordinary backup.
    """
    filenames = ("workspace.json", *(f"workspace.{version}.bak.json" for version in sorted(MIGRATIONS)))
    result = []
    try:
        with HeldOwnerDirectory(workspace_dir, require_hardened=False) as directory:
            root = directory.revalidate()
            for filename in filenames:
                if not directory.exists(filename):
                    continue
                original, observed = directory.read_text_with_identity(filename, max_bytes=1024 * 1024)
                source = read_legacy_openalgo_workspace(decode(original))
                result.append(LegacyOpenAlgoFile(
                    filename, root.st_dev, root.st_ino,
                    LegacyFileIdentity(observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns),
                    source, original,
                ))
    except (OSError, ValueError, TypeError, UnicodeError):
        raise OpenAlgoMigrationInputError from None
    return tuple(result)


def resolve_legacy_openalgo_inputs(
    sources: tuple[LegacyOpenAlgoInput | None, ...],
) -> OpenAlgoSelectorUpdate | None:
    """Compare source agreement only in private memory, retaining every fact."""
    setup: dict[str, object] = {}
    credential = None
    for source in sources:
        if source is None:
            continue
        if type(source) is not LegacyOpenAlgoInput:
            raise OpenAlgoMigrationInputError
        try:
            incoming = json.loads(_normalise(source.setup))
        except (ValueError, TypeError):
            raise OpenAlgoMigrationInputError from None
        for key, value in incoming.items():
            if key in setup and setup[key] != value:
                raise OpenAlgoMigrationConflict
            setup[key] = value
        if source.credential is not None:
            incoming_key = _credential(source.credential)
            if credential is not None and credential != incoming_key:
                raise OpenAlgoMigrationConflict
            credential = incoming_key
    if not setup:
        return None
    return OpenAlgoSelectorUpdate(_normalise(setup), "replace" if credential is not None else "preserve", credential)


def parse_openalgo_config_update(
    payload: dict[str, object], *, current_setup: dict[str, object] | None,
) -> OpenAlgoSelectorUpdate | TelegramUsernameUpdate:
    """Parse one desired state; never read fallback env or perform mutation."""
    if type(payload) is not dict or not payload:
        raise OpenAlgoMigrationInputError
    if "telegram_username" in payload:
        if _CONNECTION_FIELDS.intersection(payload):
            raise MixedOpenAlgoAuthoritiesError
        username = payload["telegram_username"]
        if set(payload) != {"telegram_username"} or type(username) is not str:
            raise OpenAlgoMigrationInputError
        if username and not re.fullmatch(r"@?[A-Za-z0-9_]{1,32}", username):
            raise OpenAlgoMigrationInputError
        return TelegramUsernameUpdate(username)
    if not set(payload) <= _CONNECTION_FIELDS:
        raise OpenAlgoMigrationInputError
    current = json.loads(_normalise(current_setup)) if current_setup is not None else {}
    host = _base_url(payload.get("host", current.get("base_url")), None)
    old_port = urlsplit(current["base_url"]).port if current else None
    port = _port(payload["port"]) if "port" in payload else old_port
    if "host" in payload and "port" in payload and urlsplit(host).port not in {None, port}:
        raise OpenAlgoMigrationInputError
    setup: dict[str, object] = {
        "base_url": _base_url(host, port, replace_port="host" not in payload),
    }
    if "ws_port" in payload:
        setup["ws_port"] = _port(payload["ws_port"])
    elif "ws_port" in current:
        setup["ws_port"] = current["ws_port"]
    replacement = _credential(payload["api_key"]) if "api_key" in payload else None
    return OpenAlgoSelectorUpdate(_normalise(setup), "replace" if replacement is not None else "preserve", replacement)
