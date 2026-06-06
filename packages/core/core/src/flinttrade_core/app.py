"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5100) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/core/src/app.py
    # or: make start
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# UTF-8 stdout/stderr reconfigure — must happen BEFORE any import that may
# emit to the console (structlog, Flask, etc.).  On Windows the default
# console encoding is cp1252, which crashes when log records contain emojis
# or ANSI colour codes.  We flip stdout/stderr to UTF-8 early; if the
# attribute is not available (Python <3.7 / non-stream stdout) we fall back
# silently so this never breaks startup.
# ---------------------------------------------------------------------------
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

import asyncio
import json
import logging
import os
import secrets
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path for cross-package imports.
_REPO_ROOT = str(Path(__file__).resolve().parents[5])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Add sibling package ``src`` directories after the stdlib/site paths.  Keeping
# these as appends avoids local modules such as ``statistics.py`` shadowing
# Python's standard library while still supporting non-installed source runs.
for _package_src in [
    "packages/core/data/src",
    "packages/core/historical/src",
    "packages/core/indicators/src",
    "packages/core/ticks/python",
    "packages/services/engine/src",
    "packages/services/screener/src",
    "packages/services/backtest/src",
    "packages/services/ai/src",
    "packages/services/ditto/src",
    "packages/services/automation/src",
    "packages/services/journal/src",
    "packages/integrations/gateway/src",
    "packages/integrations/webhooks/src",
]:
    _src_path = str(Path(_REPO_ROOT) / _package_src)
    if _src_path not in sys.path:
        sys.path.append(_src_path)

import hmac  # noqa: E402
import time  # noqa: E402

import structlog  # noqa: E402
from flask import Flask, g as _flask_g, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.flask import FlaskIntegration  # noqa: E402

from .config import Settings  # noqa: E402
from .csp import (  # noqa: E402
    build_csp_header as _build_csp_header,
    csp_report_bp as _csp_report_bp,
    generate_nonce as _generate_csp_nonce,
    inject_csp_nonce as _inject_csp_nonce,
)
from .openalgo_client import OpenAlgoClient  # noqa: E402
from .secure_file import harden as _harden_secret  # noqa: E402
from .version import APP_VERSION_TAG  # noqa: E402
from .workspace import workspace_dir as _workspace_dir  # noqa: E402
from flinttrade_data.audit_logger import AuditLogger  # noqa: E402
# engine imports are deferred into FlintTradeApp.__init__() to break the
# core↔engine circular import.  See PLC0415 comments throughout this file.
# Heavy optional modules are imported lazily inside FlintTradeApp.__init__()
# to avoid a 2-5 s startup penalty when ChromaDB / LLM / Telegram deps load.
# CronManager, TelegramBot, LLMClient, LLMConfig, RAGEngine

# Ensure the gateway src directory is on sys.path so bare gateway imports resolve.
_GATEWAY_SRC = str(Path(_REPO_ROOT) / "packages" / "integrations" / "gateway" / "src")
if _GATEWAY_SRC not in sys.path:
    sys.path.append(_GATEWAY_SRC)

from flinttrade_gateway.registry import BrokerRegistry  # noqa: E402
from flinttrade_gateway.credentials import CredentialStore  # noqa: E402
from flinttrade_gateway.auth import gateway_bp  # noqa: E402
from flinttrade_gateway.contracts import ContractManager  # noqa: E402

logger = logging.getLogger("flinttrade")


def _rag_auto_index_enabled() -> bool:
    """Return whether startup should auto-index docs into the RAG store."""
    raw = os.environ.get("FLINTTRADE_RAG_AUTO_INDEX", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _rag_runtime_enabled() -> bool:
    """Return whether the startup path should construct the RAG runtime."""
    raw = os.environ.get("FLINTTRADE_RAG_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return _rag_auto_index_enabled()


def _tick_capture_enabled() -> bool:
    """Return whether the startup path should launch live tick capture.

    Off by default — the recorder opens an OpenAlgo WebSocket on boot, so it is
    opt-in via ``FLINTTRADE_TICK_CAPTURE`` to avoid an unwanted connection on
    deployments that do not want disk-backed tick storage.
    """
    return os.environ.get("FLINTTRADE_TICK_CAPTURE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _index_rag_docs_safely(rag: Any) -> None:
    """Index docs for RAG without letting background thread errors escape."""
    try:
        count = rag.index_directory("docs/")
        logger.info("RAG background indexing completed (%s document chunks)", count)
    except Exception as exc:
        logger.warning("RAG background indexing failed: %s", exc)


def _reconnect_saved_accounts(
    registry: BrokerRegistry,
    credential_store: CredentialStore,
    reconnect_logger: logging.Logger,
) -> None:
    """Reconnect previously saved broker accounts on startup.

    Iterates over every account persisted in the CredentialStore and attempts
    to re-authenticate each one against the registry.  Failures are logged as
    warnings so that a single bad account does not block the rest.

    Args:
        registry: The live BrokerRegistry to populate with sessions.
        credential_store: The CredentialStore that holds persisted credentials.
        reconnect_logger: Logger instance to use for progress messages.
    """
    from flinttrade_gateway.session import BrokerSession  # noqa: PLC0415

    saved = credential_store.list_accounts()
    if not saved:
        reconnect_logger.info("No saved broker accounts to reconnect")
        return

    reconnect_logger.info("Reconnecting %d saved broker account(s)...", len(saved))
    for acct in saved:
        account_id: str = acct["account_id"]
        broker: str = acct["broker"]
        label: str = acct["label"]
        try:
            creds = credential_store.retrieve(account_id)
            session = BrokerSession(account_id, broker, label)
            session.authenticate(creds)
            registry._sessions[account_id] = session
            if acct.get("is_primary"):
                registry._primary = account_id
            reconnect_logger.info("  Connected: %s (%s)", label, broker)
        except Exception as exc:
            reconnect_logger.warning("  Failed: %s (%s): %s", label, broker, exc)


def _read_version() -> str:
    """Return the central FlintTrade product version tag."""
    return APP_VERSION_TAG


# ---------------------------------------------------------------------------
# Master password — cached module-level so all call-sites share a single
# value within a process.  File-backed so it survives restarts.
# ---------------------------------------------------------------------------

_MASTER_PASSWORD: str | None = None
_API_KEY_PEPPER: str | None = None
_SAFETY_GATE_SECRET: bytes | None = None


def _get_api_key_pepper() -> str:
    """Get or generate the OpenAlgo-compatible ``API_KEY_PEPPER``.

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/api_key_pepper``.
      2. Generate a fresh ``secrets.token_urlsafe(64)``, persist it hardened.
    The value is re-exported to ``os.environ`` only as an in-process transport
    for the upstream OpenAlgo modules (their ``utils.config`` reads env).

    Upstream OpenAlgo's v2.0.0.6 hardening rejected the publicly leaked
    placeholder pepper and auto-rotates on first run. FlintTrade's broker
    shim (``packages/integrations/gateway/src/shims/config_shim.py``) re-exports this
    value as ``utils.config.API_KEY_PEPPER`` so the OpenAlgo broker
    modules get the same pepper on both code paths.

    Returns the secret string; subsequent calls within the same process
    return the cached value. A best-effort persist on disk is attempted
    so restarts pick up the same pepper.
    """
    global _API_KEY_PEPPER
    if _API_KEY_PEPPER:
        return _API_KEY_PEPPER

    # Source of truth is the hardened at-rest file — NEVER the API_KEY_PEPPER env
    # var (secrets out of env, decision B/C). The pepper is an app-generated
    # random, so auto-generating it on first run is fine (unlike the operator's
    # master passphrase). It IS re-exported into os.environ below purely as an
    # in-process transport for the upstream OpenAlgo broker modules, whose
    # ``utils.config`` can only read API_KEY_PEPPER from the environment — the
    # value originates from the hardened file, never from a committed .env.
    pepper_file = _workspace_dir() / "api_key_pepper"
    try:
        if pepper_file.exists():
            stored = pepper_file.read_text().strip()
            if stored:
                _API_KEY_PEPPER = stored
                os.environ["API_KEY_PEPPER"] = stored  # in-process OpenAlgo transport
                return _API_KEY_PEPPER
    except OSError:
        pass

    new_pepper = secrets.token_urlsafe(64)
    try:
        pepper_file.parent.mkdir(parents=True, exist_ok=True)
        pepper_file.write_text(new_pepper)
        _harden_secret(pepper_file)  # SC-04: icacls/0600 owner-only
        logger.info("Generated new API_KEY_PEPPER (hardened) at %s", pepper_file)
    except OSError as exc:
        logger.warning(
            "Could not persist API_KEY_PEPPER to %s: %s — using ephemeral value",
            pepper_file,
            exc,
        )

    _API_KEY_PEPPER = new_pepper
    os.environ["API_KEY_PEPPER"] = new_pepper  # in-process OpenAlgo transport
    return _API_KEY_PEPPER


def _get_safety_gate_secret_bytes() -> bytes:
    """Get or generate the dedicated safety-gate HMAC secret (contract §8.0b).

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/safety_gate_secret`` (hex).
      2. Generate a fresh 32 random bytes, persist it hex-encoded and hardened.

    This MUST be a SEPARATE key from jwt_secret / webhook_hmac_secret /
    api_key_pepper: it signs every one-shot :class:`SafetyContext`, so reusing
    another subsystem's secret would let a leak there forge order-gate tickets.
    Like the pepper it is app-generated random (not operator material), so
    auto-generating on first run is safe; an ephemeral fallback is acceptable
    because the short SafetyContext TTL drains in-flight tickets across a restart.
    """
    global _SAFETY_GATE_SECRET
    if _SAFETY_GATE_SECRET is not None:
        return _SAFETY_GATE_SECRET

    secret_file = _workspace_dir() / "safety_gate_secret"
    try:
        if secret_file.exists():
            stored = secret_file.read_text().strip()
            if stored:
                candidate = bytes.fromhex(stored)
                if len(candidate) >= 32:
                    _SAFETY_GATE_SECRET = candidate
                    return _SAFETY_GATE_SECRET
                logger.warning(
                    "safety_gate_secret at %s is too short (<32 bytes) — regenerating",
                    secret_file,
                )
    except (OSError, ValueError):
        # Unreadable or non-hex file — regenerate rather than fail closed forever.
        logger.warning("safety_gate_secret at %s unreadable/invalid — regenerating", secret_file)

    new_secret = secrets.token_bytes(32)
    try:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(new_secret.hex())
        _harden_secret(secret_file)  # SC-04: icacls/0600 owner-only
        logger.info("Generated new safety-gate secret (hardened) at %s", secret_file)
    except OSError as exc:
        logger.warning(
            "Could not persist safety_gate_secret to %s: %s — using ephemeral value",
            secret_file,
            exc,
        )

    _SAFETY_GATE_SECRET = new_secret
    return _SAFETY_GATE_SECRET


def set_master_password(password: str) -> None:
    """Inject the master password into the process cache (TTY/fd readers, tests).

    The only supported inputs are an operator-typed passphrase (TTY getpass),
    a file descriptor (``FLINTTRADE_MASTER_PASSWORD_FD``), or the hardened
    at-rest file. NEVER an environment variable or an auto-generated default
    (locked decision #13)."""
    global _MASTER_PASSWORD
    _MASTER_PASSWORD = password


def _read_master_password_interactive() -> str:
    """Read the master passphrase from a pipe FD or a TTY prompt (locked #13).

    NEVER from ``MASTER_PASSWORD`` env var — env leaks to process listings,
    shell history, CI logs, and tracebacks that dump ``os.environ``.
    """
    import getpass  # noqa: PLC0415

    fd_env = os.environ.get("FLINTTRADE_MASTER_PASSWORD_FD")
    if fd_env:
        with os.fdopen(int(fd_env), "r") as fd:
            return fd.readline().rstrip("\n")
    if not sys.stdin.isatty():
        raise RuntimeError(
            "master password required but no TTY available; set the hardened "
            "~/.flinttrade/master_password file or pass FLINTTRADE_MASTER_PASSWORD_FD"
        )
    return getpass.getpass("FlintTrade master password: ")


def _get_master_password() -> str:
    """Return the credential-store master password (locked decision #13).

    Resolution order — NO environment variable, NO auto-generated default:
      1. process cache (set via TTY/fd reader or ``set_master_password``)
      2. the hardened at-rest file ``<workspace>/master_password`` (operator
         material per data-layer §8.1; ACL-hardened via ``secure_file.harden``)
      3. operator prompt — TTY getpass or ``FLINTTRADE_MASTER_PASSWORD_FD`` —
         then persisted to the hardened at-rest file for subsequent starts.
    """
    global _MASTER_PASSWORD
    if _MASTER_PASSWORD:
        return _MASTER_PASSWORD

    password_file = _workspace_dir() / "master_password"
    try:
        if password_file.exists():
            stored = password_file.read_text().strip()
            if stored:
                _MASTER_PASSWORD = stored
                return _MASTER_PASSWORD
    except OSError:
        pass

    password = _read_master_password_interactive()
    if not password:
        raise RuntimeError("master password required (empty input rejected)")

    try:
        password_file.parent.mkdir(parents=True, exist_ok=True)
        password_file.write_text(password)
        _harden_secret(password_file)  # SC-04: icacls/0600 owner-only
        logger.info("Persisted credential-store master password (hardened) at %s", password_file)
    except OSError as exc:
        logger.warning(
            "Could not persist master_password to %s: %s — using session value",
            password_file, exc,
        )

    _MASTER_PASSWORD = password
    return _MASTER_PASSWORD


# ---------------------------------------------------------------------------
# workspace.json reader — OpenAlgo overrides from user config
# ---------------------------------------------------------------------------


def _read_openalgo_from_workspace() -> dict[str, Any]:
    """Read OpenAlgo overrides from ``~/.flinttrade/workspace.json``.

    Returns a dict with any of ``api_key``, ``host``, ``ws_port`` keys that
    are present and non-empty.  Returns an empty dict if the file is
    missing, unreadable, or doesn't contain an ``openalgo`` section.

    workspace.json wins over .env because it's user-edited through the UI
    (Setup wizard, Settings page) while .env is the dev-machine fallback.
    """
    import json  # noqa: PLC0415

    try:
        from .workspace import Workspace  # noqa: PLC0415
        ws = Workspace()
        path = ws.config_path
    except Exception:
        # Fallback: direct workspace.json path (respects FLINTTRADE_WORKSPACE_DIR)
        path = _workspace_dir() / "workspace.json"

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json at %s: %s", path, exc)
        return {}

    openalgo = data.get("openalgo") or {}
    if not isinstance(openalgo, dict):
        return {}

    result: dict[str, Any] = {}
    for key in ("api_key", "host", "ws_port"):
        val = openalgo.get(key)
        if val:
            result[key] = val
    return result


def _apply_workspace_openalgo_overrides() -> None:
    """Apply workspace.json OpenAlgo overrides to process environment.

    Called once during ``create_flask_app()`` — writes values into
    ``os.environ`` so that subsequent ``Settings.from_env()`` calls pick
    them up.  workspace.json takes precedence over .env.
    """
    overrides = _read_openalgo_from_workspace()
    if not overrides:
        return

    if "api_key" in overrides:
        os.environ["OPENALGO_API_KEY"] = str(overrides["api_key"])
    if "host" in overrides:
        os.environ["OPENALGO_HOST"] = str(overrides["host"])
    if "ws_port" in overrides:
        os.environ["OPENALGO_WS_PORT"] = str(overrides["ws_port"])

    logger.info(
        "Applied OpenAlgo overrides from workspace.json (%s)",
        ", ".join(sorted(overrides.keys())),
    )


# ---------------------------------------------------------------------------
# DuckDB stale .wal cleanup — remove orphan write-ahead-log files on boot
# ---------------------------------------------------------------------------


def _cleanup_stale_duckdb_wals() -> None:
    """Remove ``*.wal`` lock files whose ``.db`` is not actively locked.

    When the backend crashes ungracefully DuckDB's write-ahead-log files
    can linger and block the next startup with ``IOException: The process
    cannot access the file because it is being used by another process``.

    For every ``*.wal`` in ``~/.flinttrade/`` we probe the sibling ``.db``
    by opening it read-only.  If that succeeds the lock is stale and we
    delete the ``.wal``; if it fails another process holds the lock and
    we leave it alone.
    """
    flinttrade_dir = _workspace_dir()
    if not flinttrade_dir.exists():
        return

    try:
        wal_files = list(flinttrade_dir.glob("*.wal"))
    except OSError:
        return

    if not wal_files:
        return

    try:
        import duckdb  # noqa: PLC0415
    except ImportError:
        # DuckDB not installed — nothing to validate against
        return

    cleaned = 0
    for wal in wal_files:
        db_file = wal.with_suffix("")  # strip .wal → leaves .db / .duckdb etc.
        # If the .wal pairs with a file that doesn't exist, just clear it.
        if not db_file.exists():
            try:
                wal.unlink()
                cleaned += 1
            except OSError:
                pass
            continue

        # Probe: can we open the DB read-only?  If yes → no live process
        # holds the write lock → the .wal is stale.
        try:
            conn = duckdb.connect(str(db_file), read_only=True)
            conn.close()
        except Exception as exc:
            # Another process holds the lock, or the DB is corrupt — skip.
            logger.warning(
                "Skipping stale-WAL cleanup for %s (DB appears locked or broken): %s",
                db_file.name,
                exc,
            )
            continue

        try:
            wal.unlink()
            cleaned += 1
        except OSError as exc:
            logger.warning("Could not delete stale WAL %s: %s", wal, exc)

    if cleaned:
        logger.info("Cleaned %d stale DuckDB write-ahead-log file(s)", cleaned)


# ---------------------------------------------------------------------------
# Broker router wiring (selector-bound principal; contract §13 / §11.4)
# ---------------------------------------------------------------------------


def _read_workspace_brokers() -> dict[str, Any] | None:
    """Return the ``brokers`` block from workspace.json, or ``None`` if absent.

    ``None`` (no real config) lets the caller fall back to the spec defaults
    without writing a rollback snapshot for an empty config.
    """
    try:
        path = _workspace_dir() / "workspace.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        brokers = data.get("brokers")
        return brokers if isinstance(brokers, dict) and brokers else None
    except Exception as exc:
        logger.warning("Could not read brokers from workspace.json: %s", exc)
        return None


def _snapshot_brokers_bak(brokers_config: dict[str, Any]) -> None:
    """Write the last-known-good brokers config to ``workspace.brokers.bak.json``.

    Atomic (tmp -> fsync -> os.replace, with the same Windows retry as the
    workspace writer) so a crash mid-write can never leave a torn rollback
    artefact: the file is always either the previous-complete or the
    new-complete config — which is exactly when the operator needs it
    (contract §13.3).
    """
    from .workspace_migrations import _atomic_write  # noqa: PLC0415

    bak = _workspace_dir() / "workspace.brokers.bak.json"
    _atomic_write(bak, json.dumps(brokers_config, indent=2))


def _native_activation_checks(
    credential_store: CredentialStore | None,
) -> tuple[Callable[[str], bool], Callable[[str], bool]]:
    """Build the ``(attest_ok, has_credentials)`` gates for native activation.

    ``attest_ok(broker_id)`` is true only when the broker's pinned SDK
    (``brokers.lock``) is installed at the exact pinned version; ``has_credentials``
    is true only when the encrypted vault holds an account for that broker. Both
    fail closed: any error (no lock, no vault) yields ``False`` so a native stays
    dormant. In the default no-SDK / no-creds environment every native is
    correctly skipped.
    """
    from flinttrade_gateway.brokers.native_factory import SDK_PIN_BY_BROKER  # noqa: PLC0415

    try:
        from .broker_sdk_attest import STATUS_OK, attest_all  # noqa: PLC0415

        attest_status = {r.broker: r.status for r in attest_all()}
    except Exception as exc:  # pragma: no cover - attestation must never brick boot
        logger.warning("Native attestation unavailable (%s) — natives stay dormant", exc)
        attest_status = {}

    def attest_ok(broker_id: str) -> bool:
        pin = SDK_PIN_BY_BROKER.get(broker_id)
        return pin is not None and attest_status.get(pin) == STATUS_OK

    credentialled: set[str] = set()
    if credential_store is not None:
        try:
            for account in credential_store.list_accounts():
                adapter_id = account.get("adapter_id") or account.get("broker")
                if adapter_id:
                    credentialled.add(str(adapter_id))
        except Exception as exc:  # pragma: no cover - vault read must never brick boot
            logger.warning("Credential vault read failed (%s) — natives stay dormant", exc)

    def has_credentials(broker_id: str) -> bool:
        return broker_id in credentialled

    return attest_ok, has_credentials


def build_broker_router(
    registry: BrokerRegistry,
    brokers_config: dict[str, Any],
    *,
    adapters: dict[str, Any] | None = None,
    openalgo_client: Any | None = None,
    native_attest_ok: Callable[[str], bool] | None = None,
    native_has_credentials: Callable[[str], bool] | None = None,
    native_adapter_kwargs: Callable[[str], dict[str, Any]] | None = None,
) -> Any:
    """Construct a config-driven :class:`BrokerRouter` (contract §13 / §11.4).

    Parses ``brokers_config`` into a :class:`RoutingConfig` (raising
    ``RoutingConfigError`` on a malformed block), wires an
    :class:`AuthenticatingSessionProvider` over the config's ``account_acls`` and
    a process-local one-shot :class:`SafetyGate`.

    When ``openalgo_client`` is supplied, an :class:`OpenAlgoAdapter` is
    registered under the ``openalgo`` adapter id and a Session is put in the
    registry for every ``openalgo:<account>`` selector in ``registered`` — so the
    gated path can dispatch to ALL of the operator's brokers through OpenAlgo
    (the actor still needs an entry in ``account_acls`` to be authorised).

    Native SDK adapters activate the moment their prerequisites hold: when both
    ``native_attest_ok`` (SDK installed + pinned-match) and
    ``native_has_credentials`` (vault holds creds) are supplied, the native
    selectors in ``registered`` are run through ``build_native_adapters`` and the
    survivors registered alongside OpenAlgo. With either callable omitted — the
    default — no native is constructed, so the natives stay dormant exactly as
    before. ``adapters`` still lets a caller inject adapters directly (and wins
    over the factory for the same id). A registered native has no live Session
    until the credential-replay login step establishes one; an unauthenticated
    native selector simply has no session to dispatch to.

    Raises:
        RoutingConfigError: If ``brokers_config`` is malformed.
    """
    from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import SafetyGate  # noqa: PLC0415
    from flinttrade_gateway.brokers.native_factory import (  # noqa: PLC0415
        build_native_adapters,
    )
    from flinttrade_gateway.router import BrokerRouter  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingConfig  # noqa: PLC0415
    from flinttrade_gateway.session_provider import (  # noqa: PLC0415
        AuthenticatingSessionProvider,
    )

    config = RoutingConfig.from_workspace(brokers_config)
    session_provider = AuthenticatingSessionProvider(registry, config.account_acls)
    gate = SafetyGate()

    resolved_adapters: dict[str, Any] = dict(adapters or {})

    # Native-adapter activation (dormant -> live bridge). Only runs when the
    # caller supplies both prerequisite checks; otherwise natives stay dormant.
    if native_attest_ok is not None and native_has_credentials is not None:
        native_ids: list[str] = []
        for selector in config.registered:
            try:
                adapter_id, _account = parse_selector(selector)
            except ValueError:
                continue
            native_ids.append(adapter_id)
        activated = build_native_adapters(
            native_ids,
            attest_ok=native_attest_ok,
            has_credentials=native_has_credentials,
            adapter_kwargs=native_adapter_kwargs,
            on_skip=lambda bid, why: logger.info("Native adapter %s dormant: %s", bid, why),
        )
        for adapter_id, adapter in activated.items():
            resolved_adapters.setdefault(adapter_id, adapter)
        if activated:
            logger.info("Native adapters activated: %s", ", ".join(sorted(activated)))
    if openalgo_client is not None and "openalgo" not in resolved_adapters:
        from flinttrade_gateway.brokers._base import Session as _AdapterSession  # noqa: PLC0415
        from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter  # noqa: PLC0415

        resolved_adapters["openalgo"] = OpenAlgoAdapter(default_client=openalgo_client)
        # Register a Session for each openalgo:<account> selector so the
        # AuthenticatingSessionProvider can resolve it (the actor still has to be
        # authorised in account_acls).
        for selector in config.registered:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            if adapter_id == "openalgo":
                registry.put_session(
                    "openalgo",
                    account_id,
                    _AdapterSession(
                        access_token="",
                        expires_at=4_102_444_800.0,
                        account_id=account_id,
                        adapter_id="openalgo",
                    ),
                )

    # Per-broker API rate limiter (DATA & INFRA: customizable rate limits). Built
    # from each registered adapter's capability metadata, with operator overrides
    # from workspace.json brokers.rate_limits[broker_id].{order,data}. A pure
    # below-the-gate throttle — it only delays a dispatch, never bypasses safety.
    rate_limiter = None
    try:
        from flinttrade_gateway.rate_limiter import BrokerRateLimiter  # noqa: PLC0415

        caps = {
            aid: adapter.capabilities
            for aid, adapter in resolved_adapters.items()
            if hasattr(adapter, "capabilities")
        }
        overrides = brokers_config.get("rate_limits", {}) if isinstance(brokers_config, dict) else {}
        if caps or overrides:
            rate_limiter = BrokerRateLimiter.from_capabilities(caps, overrides=overrides)
    except Exception as exc:  # pragma: no cover - a bad limit must not brick routing
        logger.warning("Broker rate limiter not built (%s); dispatch will be unthrottled", exc)

    return BrokerRouter(
        resolved_adapters, session_provider, consume_gate=gate.consume, config=config,
        rate_limiter=rate_limiter,
    )


# ---------------------------------------------------------------------------
# Flask API server — FlintTrade-specific endpoints (port 5100)
# ---------------------------------------------------------------------------


def create_flask_app(
    safety: Any | None = None,
    scheduler: Any | None = None,
    cron: Any | None = None,
    audit: AuditLogger | None = None,
    client: OpenAlgoClient | None = None,
    registry: BrokerRegistry | None = None,
    credential_store: CredentialStore | None = None,
    contract_manager: ContractManager | None = None,
    rag: Any | None = None,
) -> Flask:
    """Create the Flask app with FlintTrade API routes.

    Args:
        safety: SafetySystem instance to expose via safety endpoints.
        scheduler: StrategyScheduler instance for strategy lifecycle endpoints.
        cron: CronManager instance for cron job management endpoints.
        audit: AuditLogger instance for audit log endpoints.
        client: OpenAlgoClient instance for MCP bridge and backtest data.
        registry: BrokerRegistry for multi-broker account management.
        credential_store: CredentialStore for encrypted credential persistence.
        contract_manager: ContractManager for broker symbol contract data.
        rag: RAGEngine instance for knowledge base queries.

    Returns:
        Flask application with all FlintTrade API endpoints registered.
    """
    # ------------------------------------------------------------------
    # Pre-init hygiene:
    #   * Clear stale DuckDB .wal files from a previous crashed process.
    #   * Apply workspace.json overrides for OpenAlgo (host/api_key/ws_port)
    #     so Settings.from_env() reads the fresh UI-written values.
    # Both are best-effort — failures here must never prevent startup.
    # ------------------------------------------------------------------
    try:
        _cleanup_stale_duckdb_wals()
    except Exception as exc:
        logger.warning("DuckDB WAL cleanup failed: %s", exc)

    try:
        _apply_workspace_openalgo_overrides()
    except Exception as exc:
        logger.warning("workspace.json override failed: %s", exc)

    # ------------------------------------------------------------------
    # Static frontend — serve the built React bundle from
    # packages/apps/terminal/dist/ with SPA fallback for client-side routes.
    # If the build output is missing we fall back to API-only mode and
    # log a clear warning.
    # ------------------------------------------------------------------
    _dist_path = Path(_REPO_ROOT) / "packages" / "apps" / "terminal" / "dist"
    _dist_index = _dist_path / "index.html"
    _frontend_available = _dist_index.exists()

    if _frontend_available:
        # Point Flask's built-in static_folder at the React build.  We use
        # a dedicated static_url_path (``/_static_flask``) so Flask's
        # default catch-all route does not pre-empt the SPA fallback
        # registered later — we serve all of the root-level dist files
        # (assets/, favicon.svg, index.html) through our fallback so
        # the NotFound → index.html redirect can work cleanly.
        app = Flask(
            __name__,
            static_folder=str(_dist_path),
            static_url_path="/_static_flask",
        )
    else:
        app = Flask(__name__)
        logger.warning(
            "Frontend not built — run `npm run build` in packages/apps/terminal. "
            "Backend will serve API only."
        )
    app.config["_FRONTEND_AVAILABLE"] = _frontend_available
    app.config["_DIST_PATH"] = _dist_path

    # ------------------------------------------------------------------
    # Structured logging — ONE pipeline for both structlog calls and
    # stdlib logging calls.  Dual-emit bug (same event logged twice,
    # once pretty + once JSON) was caused by PrintLoggerFactory writing
    # to stdout *and* a bridge handler on root *also* writing to stdout.
    # Fix: route structlog through stdlib (LoggerFactory), then format
    # at the stdlib handler using ProcessorFormatter.  One event → one
    # line.
    #
    # Also disable click's ANSI colouring so Werkzeug's request log
    # doesn't embed escape codes in the log file.  Must be set BEFORE
    # werkzeug's first import triggers click initialisation.
    # ------------------------------------------------------------------
    os.environ.setdefault("ANSI_COLORS_DISABLED", "1")
    os.environ.setdefault("NO_COLOR", "1")

    _render_processor = (
        structlog.dev.ConsoleRenderer(colors=False)
        if app.debug
        else structlog.processors.JSONRenderer()
    )

    # Shared pre-chain applied to every event from either source.
    _shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    structlog.configure(
        processors=[
            *_shared_processors,
            # Hand off to stdlib's ProcessorFormatter for the final render.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _sentinel_attr = "_flinttrade_structlog_bridge"
    _root_logger = logging.getLogger()
    # Kill any pre-existing handler (e.g. from an earlier basicConfig call
    # or a previous create_flask_app() invocation) so we can't double-emit.
    for _h in list(_root_logger.handlers):
        _root_logger.removeHandler(_h)

    _formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            # Drop the raw LogRecord and _from_structlog meta keys before
            # rendering, otherwise JSON output leaks the absolute install
            # path (C:\Users\...\app.py, line numbers) into every event.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _render_processor,
        ],
        foreign_pre_chain=_shared_processors,
    )
    _handler = logging.StreamHandler()
    _handler.setFormatter(_formatter)
    setattr(_handler, _sentinel_attr, True)
    _root_logger.addHandler(_handler)
    _root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # Production-mode path rewrite (WSGI-level, runs before URL dispatch).
    # In dev, Vite strips the `/ft-api` prefix before requests reach us
    # (see packages/apps/terminal/vite.config.ts server.proxy). When the
    # backend serves the built frontend directly, no such proxy exists,
    # so the backend receives the full `/ft-api/v1/...` path while all
    # blueprints are registered under `/v1/...` or `/api/v1/...`.
    # A before_request handler runs AFTER Flask's URL match, so we wrap
    # wsgi_app instead to mutate the environ before routing.
    # ------------------------------------------------------------------
    _inner_wsgi = app.wsgi_app

    def _ft_api_prefix_stripper(environ: dict, start_response: Any) -> Any:
        raw_path = environ.get("PATH_INFO", "") or ""
        if raw_path.startswith("/ft-api/"):
            environ["PATH_INFO"] = raw_path[len("/ft-api"):]
        elif raw_path == "/ft-api":
            environ["PATH_INFO"] = "/"
        return _inner_wsgi(environ, start_response)

    app.wsgi_app = _ft_api_prefix_stripper  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Trusted forwarded-IP handling — gated behind TRUST_PROXY_HEADERS.
    # Without this, deployments behind Nginx see `request.remote_addr ==
    # 127.0.0.1` for every request, which collapses rate-limit buckets,
    # brute-force tracking, and 404 flood guards onto the loopback origin.
    # When the env flag is truthy we wrap wsgi_app with Werkzeug's ProxyFix
    # so `request.remote_addr` reflects the original client IP.
    # Default is FALSE because trusting forwarded headers from an
    # untrusted upstream would let any client spoof its source IP.
    # Mirrors the upstream OpenAlgo behaviour added in v2.0.0.7
    # (see TRUST_PROXY_HEADERS in .local/external/openalgo/utils/ip_helper.py).
    # ------------------------------------------------------------------
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: PLC0415

            _proxy_for = int(os.environ.get("TRUST_PROXY_HEADERS_X_FOR", "1") or "1")
            _proxy_proto = int(os.environ.get("TRUST_PROXY_HEADERS_X_PROTO", "1") or "1")
            _proxy_host = int(os.environ.get("TRUST_PROXY_HEADERS_X_HOST", "0") or "0")
            _proxy_port = int(os.environ.get("TRUST_PROXY_HEADERS_X_PORT", "0") or "0")
            _proxy_prefix = int(os.environ.get("TRUST_PROXY_HEADERS_X_PREFIX", "0") or "0")
            app.wsgi_app = ProxyFix(  # type: ignore[assignment]
                app.wsgi_app,
                x_for=_proxy_for,
                x_proto=_proxy_proto,
                x_host=_proxy_host,
                x_port=_proxy_port,
                x_prefix=_proxy_prefix,
            )
            logger.info(
                "TRUST_PROXY_HEADERS active — ProxyFix: x_for=%d x_proto=%d "
                "x_host=%d x_port=%d x_prefix=%d",
                _proxy_for, _proxy_proto, _proxy_host, _proxy_port, _proxy_prefix,
            )
        except Exception as exc:  # pragma: no cover - import/config edge case
            logger.warning(
                "TRUST_PROXY_HEADERS requested but ProxyFix could not be installed: %s",
                exc,
            )

    # ------------------------------------------------------------------
    # CORS — allow requests from the Vite dev server and any origins
    # configured via the CORS_ORIGINS environment variable.
    # ------------------------------------------------------------------
    CORS(
        app,
        origins=os.environ.get(
            "CORS_ORIGINS", "http://127.0.0.1:5173"
        ).split(","),
        methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-API-Key",
            "X-FlintTrade-Mode",
            "Authorization",
        ],
    )

    # ------------------------------------------------------------------
    # Rate limiting — 50 req/s default; tighter limits applied per-route
    # via @limiter.limit() on individual blueprints/views.
    # ------------------------------------------------------------------
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["50 per second"],
        storage_uri="memory://",
    )
    app.config["LIMITER"] = limiter

    # Custom token-bucket rate limiter — finer-grained per-(user, endpoint)
    # control. Consumed via the ``@rate_limit("endpoint", user_rate, global_rate)``
    # decorator from ``flinttrade_core.rate_limiter``. Applied to order,
    # bracket, strategy-start, and webhook routes to enforce the documented
    # caps: orders 10/s per user (100/s global), smart orders 2/s (20/s),
    # webhooks 5/s (50/s).
    from .rate_limiter import RateLimiter as _RateLimiter  # noqa: PLC0415
    _rate_limiter = _RateLimiter(global_rate=100, per_user_rate=10)
    _rate_limiter.set_limit("orders", user_rate=10, global_rate=100)
    _rate_limiter.set_limit("smart_orders", user_rate=2, global_rate=20)
    _rate_limiter.set_limit("webhook", user_rate=5, global_rate=50)
    app.config["RATE_LIMITER"] = _rate_limiter

    # ------------------------------------------------------------------
    # Error tracking — Sentry SDK pointing at a Glitchtip instance (MIT).
    # Only initialised when GLITCHTIP_DSN is set in the environment; safe
    # to leave unset in development.
    # ------------------------------------------------------------------
    _glitchtip_dsn = os.environ.get("GLITCHTIP_DSN", "")
    if _glitchtip_dsn:
        sentry_sdk.init(
            dsn=_glitchtip_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            environment="production" if not app.debug else "development",
        )
        logger.info("Glitchtip error tracking initialised")

    # Store injected instances on app.config so endpoint closures can access them
    app.config["SAFETY"] = safety
    app.config["SCHEDULER"] = scheduler
    app.config["CRON"] = cron
    app.config["AUDIT"] = audit
    app.config["CLIENT"] = client

    # --- Gateway initialization ---
    if registry is None:
        registry = BrokerRegistry()

    # Ensure API_KEY_PEPPER is set in os.environ BEFORE the OpenAlgo
    # broker modules are imported via the gateway shim. Upstream's
    # ``utils.config.API_KEY_PEPPER`` is captured at import time, so a
    # later os.environ tweak is too late.
    _get_api_key_pepper()

    # Bind the dedicated safety-gate HMAC secret (contract §8.0b) BEFORE the
    # broker router is built and before any SafetyContext can be minted/verified.
    # Without it gate_order() fails closed and every live routed order would 403.
    from flinttrade_engine.safety import set_safety_gate_secret  # noqa: PLC0415

    set_safety_gate_secret(_get_safety_gate_secret_bytes())

    if credential_store is None:
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)

    if contract_manager is None:
        flinttrade_dir = _workspace_dir()
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        contract_manager = ContractManager(contracts_dir)

    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = credential_store
    app.config["CONTRACT_MANAGER"] = contract_manager
    app.config["OAUTH_STATES"] = {}

    # --- Broker router (selector-bound principal; contract §13 / §11.4) ---
    # Best-effort like the other startup steps: a malformed brokers block must
    # NOT brick the app — the operator needs the UI up to fix it. On failure we
    # log loudly and leave BROKER_ROUTER as None so the gated order path returns
    # a clear 503 rather than dispatching. A successfully-parsed config is
    # snapshotted to workspace.brokers.bak.json for operator rollback (§13.3).
    app.config["BROKER_ROUTER"] = None
    try:
        from .workspace_migrations import default_workspace_config  # noqa: PLC0415

        _brokers_cfg = _read_workspace_brokers()
        _effective_brokers = _brokers_cfg or default_workspace_config()["brokers"]
        _native_attest_ok, _native_has_credentials = _native_activation_checks(credential_store)
        # Expose the OpenAlgo client so sync analysis routes (the screener) can
        # fetch a real option chain through the functional bridge adapter rather
        # than always falling back to sample data.
        app.config["OPENALGO_CLIENT"] = client
        app.config["BROKER_ROUTER"] = build_broker_router(
            registry,
            _effective_brokers,
            openalgo_client=client,
            native_attest_ok=_native_attest_ok,
            native_has_credentials=_native_has_credentials,
        )
        if _brokers_cfg is not None:
            _snapshot_brokers_bak(_brokers_cfg)
    except Exception as exc:
        logger.critical(
            "BrokerRouter not built — workspace.json brokers routing is invalid: %s. "
            "Order routing is unavailable until you fix brokers.routing; the rest of "
            "the app is up. Last known-good config: ~/.flinttrade/workspace.brokers.bak.json",
            exc,
        )

    # Store RAG instance
    app.config["RAG"] = rag

    # Register gateway blueprint (mounts at /v1/)
    app.register_blueprint(gateway_bp)

    # Register analysis blueprint (/api/v1/gex, /api/v1/volsurface, etc.)
    from flinttrade_screener.analysis_routes import analysis_bp  # noqa: PLC0415
    app.register_blueprint(analysis_bp)

    # Register sample-data placeholder blueprint — eight endpoints whose real
    # implementations are not yet built. Each returns is_sample_data=true so
    # widgets show their "Demo" badge instead of 404-ing. See
    # packages/services/screener/src/sample_data_routes.py.
    from flinttrade_screener.sample_data_routes import sample_data_bp  # noqa: PLC0415
    app.register_blueprint(sample_data_bp)

    # Register stock screener blueprint (/v1/stocks/*)
    from flinttrade_screener.stock_routes import stock_bp  # noqa: PLC0415
    app.register_blueprint(stock_bp)

    # Register market scanner blueprint (/v1/scanner/* — external: /ft-api/v1/scanner/*)
    from flinttrade_screener.scanner_routes import scanner_bp  # noqa: PLC0415
    app.register_blueprint(scanner_bp)

    # Register OI analytics blueprint (/v1/oi/* — external: /ft-api/v1/oi/*)
    from flinttrade_screener.oi_analytics_routes import oi_analytics_bp  # noqa: PLC0415
    app.register_blueprint(oi_analytics_bp)

    # Register Mutual Fund NAV blueprint (/api/v1/mf/search, /mf/nav, /mf/categories)
    from flinttrade_screener.mf_routes import mf_bp  # noqa: PLC0415
    app.register_blueprint(mf_bp)

    # Register breadth + volatility cone blueprints (/v1/breadth/*, /v1/analytics/volcone — external: /ft-api/v1/*)
    from flinttrade_screener.breadth_routes import breadth_bp  # noqa: PLC0415
    app.register_blueprint(breadth_bp)

    # Register Action Center blueprint (/api/v1/action-center/*)
    from flinttrade_engine.action_center import ActionCenter  # noqa: PLC0415
    from flinttrade_engine.action_center_routes import action_center_bp  # noqa: PLC0415
    action_center = ActionCenter()
    app.config["ACTION_CENTER"] = action_center
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/api/v1/security/*)
    from .security import SecurityMonitor  # noqa: PLC0415
    from .security_routes import register_security_middleware, security_bp  # noqa: PLC0415
    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register persistent SecurityTracker (DuckDB-backed 404/IP-ban log)
    from flinttrade_data.security_tracker import SecurityTracker as _SecurityTracker  # noqa: PLC0415
    _security_db = _workspace_dir() / "security.db"
    app.config["SECURITY_TRACKER"] = _SecurityTracker(str(_security_db))

    # Register LoginActivity + SessionTracker (DuckDB-backed)
    from flinttrade_data.activity_log import LoginActivity as _LoginActivity  # noqa: PLC0415
    from flinttrade_data.activity_log import SessionTracker as _SessionTracker  # noqa: PLC0415
    _login_db = _workspace_dir() / "activity.db"
    app.config["LOGIN_ACTIVITY"] = _LoginActivity(str(_login_db))
    app.config["SESSION_TRACKER"] = _SessionTracker(str(_login_db))

    # Shared trade-journal store (DuckDB). The gated order dispatch writes every
    # executed live order here and the /trades/journal route reads the SAME
    # store, so the journal + P&L analytics populate in Live (previously the
    # producer was missing → permanently empty journal). One shared, pre-
    # initialised connection keeps the per-order cost to a single INSERT (latency
    # is paramount). A lock serialises the writer against the route's reads —
    # DuckDB connections are not safe for concurrent use. Best-effort: a storage
    # failure degrades to "no journalling", never blocks boot.
    try:
        from flinttrade_data.storage import StorageManager as _TradeStore  # noqa: PLC0415

        _trade_storage = _TradeStore()
        _trade_storage.initialise()
        app.config["TRADE_STORAGE"] = _trade_storage
        app.config["TRADE_STORAGE_LOCK"] = threading.Lock()
    except Exception:  # pragma: no cover — defensive: never let storage break boot
        logger.warning(
            "Trade journal storage unavailable; live trades will not be journalled",
            exc_info=True,
        )
        app.config["TRADE_STORAGE"] = None
        app.config["TRADE_STORAGE_LOCK"] = None

    # Register P&L tracker blueprint (/api/v1/pnl-tracker/*)
    from flinttrade_data.pnl_routes import pnl_bp  # noqa: PLC0415
    app.register_blueprint(pnl_bp)

    # Register Order Flow blueprint (synthetic footprint data)
    from flinttrade_data.orderflow_routes import orderflow_bp  # noqa: PLC0415
    app.register_blueprint(orderflow_bp)

    # Register Tax Report blueprint (/v1/tax/*)
    from flinttrade_data.tax_routes import tax_bp  # noqa: PLC0415
    app.register_blueprint(tax_bp)

    # Register Historify watchlist blueprint
    from flinttrade_historical.watchlist_routes import historify_bp  # noqa: PLC0415
    app.register_blueprint(historify_bp)

    # Register TradingView signals blueprint (/v1/tv/*)
    from flinttrade_screener.tv_routes import tv_bp  # noqa: PLC0415
    app.register_blueprint(tv_bp)

    # Register monitoring blueprint (/api/v1/traffic/*, /api/v1/latency/*).
    # Aggregated /api/v1/health lives in health_bp (the canonical health surface).
    from .monitoring_routes import monitoring_bp  # noqa: PLC0415
    app.register_blueprint(monitoring_bp)

    # Register frontend error ingestion + changelog reader (/v1/errors, /v1/changelog
    # — external URLs: /ft-api/v1/errors, /ft-api/v1/changelog). Previously referenced
    # by the terminal but not wired, causing 404s on fire-and-forget error reports.
    # Initialise the persistent error log ONCE (always active — not gated by
    # dev mode). The try/except guard means a DuckDB failure degrades to
    # warning-only logging rather than crashing startup. The same instance is
    # stored on app.config (so admin_routes and frontend_errors_bp can reach
    # it) and reused by the global error handler below.
    from .error_log import ErrorLog as _ErrorLog  # noqa: PLC0415
    from .frontend_error_routes import frontend_errors_bp  # noqa: PLC0415
    _error_db = _workspace_dir() / "error_log.duckdb"
    try:
        _error_log = _ErrorLog(db_path=str(_error_db))
    except Exception as exc:
        logger.warning("ErrorLog initialisation failed (%s); /v1/errors will log warnings only", exc)
        _error_log = None
    app.config["ERROR_LOG"] = _error_log
    app.register_blueprint(frontend_errors_bp)

    # Register Strategy Runner blueprint (/api/v1/strategies/*)
    from flinttrade_engine.strategy_routes import strategy_bp  # noqa: PLC0415
    app.register_blueprint(strategy_bp)

    # Wire the Strategy Runner + Cron scheduler the strategy routes require so
    # upload/start/stop/logs/schedule work in production — without these config
    # keys every /api/v1/strategies write returned 503 "Strategy runner not
    # configured" (feature audit H1/M13). Construction is side-effect-light: the
    # runner only creates its own dirs, and CronStrategyScheduler does not start
    # APScheduler until .start() is called.
    if "STRATEGY_RUNNER" not in app.config:
        try:
            from flinttrade_engine.strategy_runner import UserStrategyRunner  # noqa: PLC0415

            app.config["STRATEGY_RUNNER"] = UserStrategyRunner(_workspace_dir() / "strategies")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Strategy runner wiring failed (%s); /strategies writes will 503", exc)
    if "CRON_SCHEDULER" not in app.config:
        try:
            from flinttrade_engine.scheduler import CronStrategyScheduler  # noqa: PLC0415

            app.config["CRON_SCHEDULER"] = CronStrategyScheduler()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Cron scheduler wiring failed (%s); strategy scheduling will 503", exc)

    # Execution-quality analytics (POST /api/v1/analytics/execution) and strategy
    # comparison (POST /api/v1/backtest/compare) — both fully built + tested but were
    # never registered (404 in production; feature audit H6/M2). Their blueprints
    # carry no prefix, so register under /api/v1 to match the frontend convention.
    from flinttrade_journal.order_analytics import order_analytics_bp  # noqa: PLC0415
    app.register_blueprint(order_analytics_bp, url_prefix="/api/v1")
    from flinttrade_backtest.strategy_comparison import strategy_comparison_bp  # noqa: PLC0415
    app.register_blueprint(strategy_comparison_bp, url_prefix="/api/v1")

    # Register Engine Sandbox blueprint (/v1/sandbox-config/*) — config/leverage/squareoff.
    # Uses the /v1/sandbox-config prefix to avoid collision with the data sandbox
    # blueprint below, which owns /v1/sandbox.
    from flinttrade_engine.sandbox_routes import sandbox_bp  # noqa: PLC0415
    from flinttrade_engine.sandbox import SandboxEngine as _EngineSandboxEngine  # noqa: PLC0415
    app.config["SANDBOX_ENGINE"] = _EngineSandboxEngine(account_id="default")
    app.register_blueprint(sandbox_bp)

    # Register Data Sandbox blueprint (/v1/sandbox/*) — paper trading engine
    # (capital, orders, positions, P&L, reset, export/import)
    from flinttrade_data.sandbox_routes import data_sandbox_bp  # noqa: PLC0415
    from flinttrade_data.sandbox_engine import SandboxEngine as _DataSandboxEngine  # noqa: PLC0415
    app.config["DATA_SANDBOX_ENGINE"] = _DataSandboxEngine()
    app.register_blueprint(data_sandbox_bp)

    # ------------------------------------------------------------------
    # Global unhandled-exception handler — persists errors to DuckDB
    # before re-raising so Flask's default 500 handler takes over.
    # ------------------------------------------------------------------
    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception) -> Any:
        """Persist every unhandled exception to the structured error log.

        Werkzeug ``HTTPException`` instances (404, 405, 415, …) are not
        real errors — they represent deliberately returned HTTP status
        codes and must be passed straight through with their own payload,
        otherwise a simple 404 bubbles up as a misleading 500.  Real
        exceptions are logged and converted to a plain HTTP 500 JSON
        response so we never leak internal tracebacks to clients.
        """
        from werkzeug.exceptions import HTTPException  # noqa: PLC0415

        if isinstance(exc, HTTPException):
            return exc  # Flask will render the HTTPException normally.

        try:
            if _error_log is not None:
                _error_log.log(
                    route=request.path,
                    method=request.method,
                    status_code=500,
                    request_body=request.get_json(silent=True, force=True),
                    error=exc,
                    user_id=None,  # user context not available at this layer
                )
        except Exception:
            # Never let the error logger itself crash the request.
            pass
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    # Initialise TrafficLogger (DuckDB-backed, always active).
    # @before_request / @after_request hooks record every HTTP request.
    from .traffic_logger import TrafficLogger as _TrafficLogger, should_skip_path as _skip_path  # noqa: PLC0415

    _traffic_log_path = _workspace_dir() / "traffic_log.duckdb"
    _traffic_logger = _TrafficLogger(_traffic_log_path)
    app.config["TRAFFIC_LOGGER"] = _traffic_logger

    @app.before_request
    def _traffic_start() -> None:
        """Record the request start time for traffic duration measurement."""
        import time as _time  # noqa: PLC0415
        _flask_g._traffic_start = _time.monotonic()

    @app.after_request
    def _traffic_log(response: Any) -> Any:
        """Persist request details to TrafficLogger after each response."""
        try:
            if not _skip_path(request.path):
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _traffic_logger.log(
                    ip=request.remote_addr or "unknown",
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    user_agent=request.headers.get("User-Agent"),
                    request_size=request.content_length,
                    response_size=response.content_length,
                )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let traffic logging break the response
        return response

    # Initialise LatencyMonitor (DuckDB-backed, always active).
    # The order router wraps this via monitoring_routes.get_latency_tracker()
    # for in-memory stats; this provides persistent DuckDB-backed storage.
    from flinttrade_engine.latency_monitor import LatencyMonitor as _LatencyMonitor  # noqa: PLC0415

    _latency_log_path = _workspace_dir() / "latency_log.duckdb"
    _latency_monitor = _LatencyMonitor(_latency_log_path)
    app.config["LATENCY_MONITOR"] = _latency_monitor

    # Initialise APIAnalyzer (DuckDB-backed, opt-in via ENABLE_ANALYZER=true).
    _analyzer_enabled = os.environ.get("ENABLE_ANALYZER", "").lower() in ("1", "true", "yes")
    if _analyzer_enabled:
        from .api_analyzer import APIAnalyzer as _APIAnalyzer  # noqa: PLC0415

        _analyzer_path = _workspace_dir() / "api_analyzer.duckdb"
        _api_analyzer = _APIAnalyzer(_analyzer_path)
        app.config["API_ANALYZER"] = _api_analyzer

        @app.after_request
        def _analyzer_log(response: Any) -> Any:
            """Persist full request + response to APIAnalyzer when enabled."""
            try:
                import time as _time  # noqa: PLC0415
                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _api_analyzer.log_call(
                    route=request.path,
                    method=request.method,
                    request_body=request.get_json(silent=True, force=True),
                    response_status=response.status_code,
                    response_body=None,  # Not parsing response body to avoid re-reading stream
                    duration_ms=duration_ms,
                )
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return response

        logger.info("API Analyser enabled — capturing all requests")

    # Initialise module-level EventBus singleton.
    from .event_bus import bus as _event_bus  # noqa: PLC0415
    app.config["EVENT_BUS"] = _event_bus
    logger.info("EventBus initialised")

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from .admin_routes import admin_bp  # noqa: PLC0415
        app.register_blueprint(admin_bp)
        # Register infrastructure admin routes (traffic/latency/analyzer)
        from .infra_routes import infra_bp  # noqa: PLC0415
        app.register_blueprint(infra_bp)
        logger.info("Admin endpoints registered (dev mode)")

    # Register Activity Log blueprint (/api/v1/admin/activity)
    # Always registered — audit access is not restricted to dev mode.
    from flinttrade_data.activity_routes import activity_bp  # noqa: PLC0415
    _activity_db = _workspace_dir() / "activity.db"
    from flinttrade_data.activity_log import ActivityLog as _ActivityLog  # noqa: PLC0415
    app.config["ACTIVITY_LOG"] = _ActivityLog(str(_activity_db))
    app.register_blueprint(activity_bp)
    logger.info("Activity log endpoint registered at /api/v1/admin/activity")

    # Register extracted inline-route blueprints
    from .indicators_routes import indicators_bp  # noqa: PLC0415
    app.register_blueprint(indicators_bp)

    from flinttrade_ai.advisor_routes import advisor_bp  # noqa: PLC0415
    app.register_blueprint(advisor_bp)

    from flinttrade_ai.ai_routes import ai_bp  # noqa: PLC0415
    app.register_blueprint(ai_bp)

    from flinttrade_ai.obsidian_routes import obsidian_bp  # noqa: PLC0415
    app.register_blueprint(obsidian_bp)

    from flinttrade_ai.signal_routes import signal_bp  # noqa: PLC0415
    app.register_blueprint(signal_bp)

    from .backtest_routes import backtest_bp  # noqa: PLC0415
    app.register_blueprint(backtest_bp)

    from .operations_routes import operations_bp  # noqa: PLC0415
    app.register_blueprint(operations_bp)

    # Register Order proxy blueprint (/v1/orders/*) — CRITICAL SAFETY LAYER.
    # All order requests from the frontend must pass through here so that
    # mode enforcement (explore/practice/live) is applied before any
    # real-money order reaches OpenAlgo.
    from .order_routes import orders_bp  # noqa: PLC0415
    app.register_blueprint(orders_bp)

    # Register AI Team blueprint (/api/v1/ai/team/*)
    from flinttrade_ai.team_routes import team_bp  # noqa: PLC0415
    app.register_blueprint(team_bp)

    # Register Fundamental Screener blueprint (/api/v1/fundamentals/*)
    from flinttrade_screener.fundamental_routes import fundamental_bp  # noqa: PLC0415
    app.register_blueprint(fundamental_bp)

    # Register IPO Tracker blueprint (/api/v1/ipo/*)
    from flinttrade_screener.ipo_routes import ipo_bp  # noqa: PLC0415
    app.register_blueprint(ipo_bp)

    # Register Earnings Calendar blueprint (/api/v1/earnings/* — external:
    # /ft-api/api/v1/earnings/*). Prefix flipped 2026-05-19 (was /v1/) so the
    # frontend's ftApi.helpers /api/v1 path lines up with the registered route.
    from flinttrade_screener.earnings_routes import earnings_bp  # noqa: PLC0415
    app.register_blueprint(earnings_bp)

    # Register Pivot Calculator blueprint (/v1/pivots/* — external: /ft-api/v1/pivots/*)
    from flinttrade_screener.pivot_routes import pivot_bp  # noqa: PLC0415
    app.register_blueprint(pivot_bp)

    # Register Economic Calendar blueprint (/v1/economic/* — external: /ft-api/v1/economic/*)
    from flinttrade_screener.economic_routes import economic_bp  # noqa: PLC0415
    app.register_blueprint(economic_bp)

    # Register Audit Trail blueprint (/v1/audit/* — external: /ft-api/v1/audit/*)
    from flinttrade_data.audit_routes import audit_bp  # noqa: PLC0415
    app.register_blueprint(audit_bp)

    # Register Analytics extensions blueprint (/v1/indicators/vwap, /v1/analytics/pairs,
    # /v1/analytics/mtf — external: /ft-api/v1/indicators/*, /ft-api/v1/analytics/*)
    from flinttrade_screener.analytics_routes import analytics_bp  # noqa: PLC0415
    app.register_blueprint(analytics_bp)

    # Register WhatsApp Alerts blueprint (/api/v1/alerts/whatsapp/*)
    from flinttrade_automation.whatsapp_routes import whatsapp_bp  # noqa: PLC0415
    app.register_blueprint(whatsapp_bp)

    # Register Historical Expiry Tracker blueprint (/api/v1/historical/*)
    from flinttrade_historical.expiry_tracker_routes import expiry_tracker_bp  # noqa: PLC0415
    app.register_blueprint(expiry_tracker_bp)

    # Register Holidays + Market Timings blueprint (/api/v1/holidays, /api/v1/market/timings)
    from flinttrade_historical.holidays_routes import holidays_bp  # noqa: PLC0415
    app.register_blueprint(holidays_bp)

    # Register Intervals blueprint (/api/v1/intervals)
    from flinttrade_historical.intervals_routes import intervals_bp  # noqa: PLC0415
    app.register_blueprint(intervals_bp)

    # Register Instruments blueprint (/api/v1/instruments)
    from flinttrade_historical.instruments_routes import instruments_bp  # noqa: PLC0415
    app.register_blueprint(instruments_bp)

    # Register Symbol Search blueprint (/api/v1/search)
    from flinttrade_historical.search_routes import search_bp  # noqa: PLC0415
    app.register_blueprint(search_bp)

    # Register Broker Capabilities blueprint (/api/v1/broker/capabilities)
    from flinttrade_gateway.capabilities_routes import capabilities_bp  # noqa: PLC0415
    app.register_blueprint(capabilities_bp)

    # Register Leverage / Margin blueprint (/api/v1/leverage/margin/current)
    from flinttrade_engine.leverage_routes import leverage_bp  # noqa: PLC0415
    app.register_blueprint(leverage_bp)

    # Register PNL by Symbols blueprint (/api/v1/pnl/symbols)
    from flinttrade_data.pnl_symbols_routes import pnl_symbols_bp  # noqa: PLC0415
    app.register_blueprint(pnl_symbols_bp)

    # Register Bracket Order blueprint (/api/v1/orders/bracket*)
    from flinttrade_engine.bracket_routes import bracket_bp  # noqa: PLC0415
    app.register_blueprint(bracket_bp)

    # Register Position Sizer blueprint (/api/v1/position/*)
    from flinttrade_engine.position_sizer_routes import position_bp  # noqa: PLC0415
    app.register_blueprint(position_bp)

    # Register Voice Orders blueprint (/api/v1/voice/*)
    from flinttrade_webhooks.voice_orders import voice_bp  # noqa: PLC0415
    app.register_blueprint(voice_bp)

    # Register n8n bridge blueprint (/api/v1/automation/n8n/*)
    from flinttrade_automation.n8n_routes import n8n_bp  # noqa: PLC0415
    app.register_blueprint(n8n_bp)

    # Register QuestDB bridge blueprint (/api/v1/data/questdb/*)
    from flinttrade_data.questdb_routes import questdb_bp  # noqa: PLC0415
    app.register_blueprint(questdb_bp)

    # Register Excel bridge blueprint (/api/v1/integration/excel/*)
    from flinttrade_webhooks.excel_routes import excel_bp  # noqa: PLC0415
    app.register_blueprint(excel_bp)

    # ------------------------------------------------------------------
    # Blueprints discovered as defined-but-not-registered during the
    # 2026-05-19 multi-agent audit (Python audit, API contract audit).
    # Registering them activates their routes:
    #
    #   webhook_bp                — /v1/webhook/<source>, /v1/webhook/log
    #                               (TradingView + ChartInk webhook receivers)
    #   payoff_bp                 — /api/v1/payoff/{analyse,curve}, /api/v1/regime/current,
    #                               /api/v1/analytics/correlation
    #                               (prefix flipped 2026-05-19 to align with ftApi.helpers)
    #   health_bp                 — /health, /health/detail, /healthz, /readyz,
    #                               /api/v1/ping, /api/v1/health (K8s + LB probes
    #                               + aggregated subsystem health; canonical health
    #                               surface; /api/v1/ping is already in
    #                               `_PUBLIC_V1_PREFIXES`)
    #   optimiser_bp              — /v1/portfolio/{optimise,frontier}
    #   permutation_bp            — /v1/backtest/{permutation,walkforward}
    #   admin_action_center_bp    — /admin/action-center/{pending,approve,reject,history}
    #                               (separate from `action_center_bp` which lives
    #                               under /api/v1/action-center for normal users)
    #   engine order_bp           — /api/v1/orders/{basket,split,options-strategy}
    #                               (advanced orders; distinct from core's safety
    #                               proxy `orders_bp` which currently lives at
    #                               /v1/orders/* — frontend uses the /api/v1/
    #                               form, so these route additions reduce the
    #                               apparent 404 surface today.)
    # ------------------------------------------------------------------
    from flinttrade_webhooks.webhook_routes import webhook_bp  # noqa: PLC0415
    app.register_blueprint(webhook_bp)

    from flinttrade_screener.payoff_routes import payoff_bp  # noqa: PLC0415
    app.register_blueprint(payoff_bp)

    from .health_routes import health_bp  # noqa: PLC0415
    app.register_blueprint(health_bp)

    # Backtest route blueprints — imported from the installed flinttrade_backtest
    # package (no sys.path injection: the workspace package is installed editable).
    from flinttrade_backtest.optimiser_routes import optimiser_bp  # noqa: PLC0415
    app.register_blueprint(optimiser_bp)
    from flinttrade_backtest.permutation_routes import permutation_bp  # noqa: PLC0415
    app.register_blueprint(permutation_bp)

    from flinttrade_engine.action_center_routes import admin_action_center_bp  # noqa: PLC0415
    app.register_blueprint(admin_action_center_bp)

    from flinttrade_engine.order_routes import order_bp as engine_order_bp  # noqa: PLC0415
    app.register_blueprint(engine_order_bp)

    # Register Workspace Preset blueprint (/v1/presets/* — external: /ft-api/v1/presets/*)
    from .preset_routes import preset_bp  # noqa: PLC0415
    app.register_blueprint(preset_bp)

    # Register Log Stream blueprint (/v1/logs/*) — SSE + REST log streaming
    from .log_stream import log_stream_bp  # noqa: PLC0415
    app.register_blueprint(log_stream_bp)

    # Register Keyboard Shortcuts blueprint (/v1/shortcuts/*) — per-user DuckDB persistence
    from .shortcuts_routes import shortcuts_bp  # noqa: PLC0415
    app.register_blueprint(shortcuts_bp)

    # Register Docs Search blueprint (/v1/docs/*) — full-text search + changelog
    from .docs_search_routes import docs_search_bp  # noqa: PLC0415
    app.register_blueprint(docs_search_bp)

    # Register the CSP violation-report endpoint (POST /csp-report; matches the
    # report-uri the nonce-based CSP header declares) — DS-CSP-09.
    app.register_blueprint(_csp_report_bp)

    # Register Auth blueprint (/v1/auth/*) — public endpoints, no API key required
    from .auth_service import AuthService as _AuthService  # noqa: PLC0415
    from .auth_routes import auth_bp  # noqa: PLC0415
    _auth_db = _workspace_dir() / "auth.db"
    app.config["AUTH_SERVICE"] = _AuthService(db_path=_auth_db)
    app.register_blueprint(auth_bp)

    # Register Multi-user blueprint (/api/v1/users/*) — opt-in via FLINTTRADE_MULTI_USER=1
    if os.environ.get("FLINTTRADE_MULTI_USER", "").strip() in ("1", "true", "yes"):
        from .user_manager import UserManager as _UserManager  # noqa: PLC0415
        from .user_routes import users_bp  # noqa: PLC0415
        app.config["USER_MANAGER"] = _UserManager(db_path=_auth_db)
        app.register_blueprint(users_bp)
        logger.info("Multi-user mode enabled — /api/v1/users/* endpoints registered")

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed: %s", exc)

    # Paths that are legitimately public (no API key needed):
    # - Health check endpoint (also exempted by endpoint name in require_auth)
    # - Admin introspect (already gated by FLINTTRADE_DEV in admin_routes)
    # - OAuth callbacks (browser redirect — no API key in URL)
    # - Frontend error reporting (/api/v1/errors — must be reachable before auth)
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/",          # Auth endpoints are public (login, setup, status)
        "/v1/auth/callback",
        "/v1/errors",         # Frontend error reporting — public, rate-limited.
                              # Blueprint mounted at /v1/errors (see
                              # frontend_error_routes.py:Blueprint(..., url_prefix="/v1")).
                              # Persists to ErrorLog (DuckDB) for post-mortem.
        "/api/v1/errors",     # Same purpose, different sink: this path is
                              # handled by `operations_bp.receive_frontend_error`
                              # which forwards to structlog + Sentry/Glitchtip
                              # instead of DuckDB. Kept public so the React app,
                              # the Chrome extension, and external automation
                              # can all fire-and-forget error reports without
                              # an API key — neither sink leaks sensitive data
                              # back to the caller.
        "/v1/changelog",      # Frontend changelog viewer — public, paired with /v1/errors.
        "/api/v1/ping",       # Liveness probe — no auth required
        "/v1/config/openalgo",          # Setup wizard — public, localhost-only
        "/v1/test-connection",          # Setup wizard — public, localhost-only
    )

    @app.before_request
    def _bind_request_context() -> None:
        """Bind per-request fields into the structlog context variable store.

        Attaches a unique request ID (from the X-Request-ID header, or a
        freshly generated hex token), the HTTP method, and the path so that
        every log line emitted during this request carries them automatically.
        """
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get(
                "X-Request-ID", secrets.token_hex(8)
            ),
            method=request.method,
            path=request.path,
        )

    @app.after_request
    def _log_request(response: Any) -> Any:
        """Emit a structured log line for every completed HTTP response."""
        _req_log = structlog.get_logger()
        _req_log.info(
            "request",
            status=response.status_code,
            content_length=response.content_length,
        )
        return response

    @app.before_request
    def _set_csp_nonce() -> None:
        """Mint a fresh per-request CSP nonce for the served HTML + CSP header.

        Read by :func:`_add_security_headers` (header) and the SPA fallback
        (``<script nonce>`` injection) so the bootstrap script the gateway serves
        carries the same nonce the policy declares (DS-CSP-09).
        """
        _flask_g.csp_nonce = _generate_csp_nonce()

    @app.after_request
    def _add_security_headers(response: Any) -> Any:
        """Add security headers to every response (only when not already set).

        CSP is delivered here, as a per-request HTTP header carrying a fresh nonce
        (DS-CSP-09). It is an HTTP header — not a <meta> tag — because only the gateway
        can mint a per-render nonce and weave it into both the policy and the served
        index.html's <script> tags. The script directive forbids inline scripts (DS-CSP-01).
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            _build_csp_header(getattr(_flask_g, "csp_nonce", None)),
        )
        return response

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Only specific public paths are exempted:
        - Health check and admin introspect (dev-gated)
        - OAuth callback (browser redirect, no API key in URL)
        - Static files and SPA HTML fallback (React bundle)
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check, static files, and SPA fallback without auth
        if request.endpoint in ("health_detail.health_aggregated", "static", "_spa_fallback"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # Allow specific public /v1/ paths only
        if any(request.path.startswith(prefix) for prefix in _PUBLIC_V1_PREFIXES):
            return None

        api_key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )

        expected_key = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            remote = request.remote_addr or ""
            if remote in ("127.0.0.1", "::1", "localhost"):
                logger.debug(
                    "FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — allowing loopback local request",
                )
                return None
            logger.warning("FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — remote requests will be rejected")
            return jsonify({"status": "error", "message": "Backend API key not configured"}), 503

        if not api_key or not hmac.compare_digest(api_key, expected_key):
            # Record auth failure for brute-force detection
            try:
                sec = app.config.get("SECURITY_MONITOR")
                if sec:
                    sec.record_auth_failure(request.remote_addr or "unknown")
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        return None

    @app.before_request
    def _require_json_content_type() -> Any:
        """Reject POST/PUT/PATCH requests that don't send JSON."""
        if request.method in ("POST", "PUT", "PATCH") and request.content_length:
            content_type = request.content_type or ""
            if "json" not in content_type and "text/event-stream" not in content_type:
                return jsonify({
                    "status": "error",
                    "message": "Content-Type must be application/json",
                }), 415
        return None

    @app.before_request
    def _record_request_start() -> None:
        """Store request start time for latency calculation."""
        _flask_g._request_start = time.monotonic()

    @app.after_request
    def _record_traffic(response: Any) -> Any:
        """Record method, path, status, and duration in TrafficCounter."""
        try:
            from .monitoring_routes import get_traffic_counter  # noqa: PLC0415

            start = getattr(_flask_g, "_request_start", None)
            duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
            get_traffic_counter().record(
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let monitoring break the response
        return response

    @app.after_request
    def _track_404s(response: Any) -> Any:
        """Persist 404 events in SecurityTracker for flood detection.

        Runs after the response is built so we know the real status code.
        Best-effort — never disrupts the response pipeline.
        """
        if response.status_code == 404:
            try:
                skt = app.config.get("SECURITY_TRACKER")
                if skt is not None:
                    skt.track_404(request.remote_addr or "unknown", request.path)
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
        return response

    @app.before_request
    def _session_heartbeat() -> None:
        """Update last_active for the session carried in the Authorization header.

        Only fires when a valid Bearer token is present AND a SessionTracker
        has been registered.  Best-effort — never blocks the request.
        """
        try:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return
            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                return
            st = app.config.get("SESSION_TRACKER")
            if st is not None:
                st.heartbeat(token)
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)

    # --- inline route handlers extracted to blueprints ---
    # indicators_bp  → packages/core/core/src/indicators_routes.py
    # advisor_bp     → packages/services/ai/src/advisor_routes.py
    # ai_bp          → packages/services/ai/src/ai_routes.py
    # signal_bp      → packages/services/ai/src/signal_routes.py
    # backtest_bp    → packages/core/core/src/backtest_routes.py
    # operations_bp  → packages/core/core/src/operations_routes.py

    # ------------------------------------------------------------------
    # MCP bridge — intentionally NOT wired here.
    #
    # A dormant bridge used to register an UNGATED ``place_order`` handler that
    # built a fresh OpenAlgoClient and submitted live orders without passing
    # through the SafetySystem / gate_order / BrokerRouter and mode guard. It
    # was unreachable today but a latent ungated-order risk, so it has been
    # removed. Any future MCP order path MUST route through the gated execution
    # layer rather than calling OpenAlgoClient.place_order directly.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Config persistence endpoint — /ft-api/v1/config/openalgo
    # Accepts {api_key, host, ws_port} from the Setup wizard, persists
    # them to workspace.json, and hot-reloads app.config["CLIENT"] so no
    # process restart is needed.
    # ------------------------------------------------------------------
    # Registered at /v1/... (not /ft-api/v1/...) because the WSGI prefix
    # stripper normalises /ft-api/v1/X → /v1/X before URL dispatch, and the
    # Vite dev proxy does the same rewrite. So a single /v1/... registration
    # is reachable from both environments.
    @app.route("/v1/config/openalgo", methods=["POST"])
    @limiter.limit("10 per minute")
    def _set_openalgo_config() -> Any:
        """Persist OpenAlgo connection settings from the UI.

        Security: only accept requests from loopback (127.0.0.1) since the
        payload includes the OpenAlgo API key. The default require_auth
        layer still applies unless the caller is already authenticated —
        however the Setup wizard runs *before* the user has an API key,
        so we also permit requests that originate from localhost without
        an API-key header.

        Request JSON: ``{"api_key": "...", "host": "...", "ws_port": 8765}``
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        payload = request.get_json(silent=True) or {}
        api_key = str(payload.get("api_key", "")).strip()
        host = str(payload.get("host", "")).strip()
        ws_port = payload.get("ws_port")

        if not api_key and not host and ws_port is None:
            return jsonify({
                "status": "error",
                "message": "At least one of api_key, host, ws_port is required",
            }), 400

        # Persist to workspace.json
        try:
            from .workspace import Workspace  # noqa: PLC0415
            ws = Workspace()
            if not ws.config_path.exists():
                ws.initialize()
            if api_key:
                ws.set("openalgo.api_key", api_key)
            if host:
                ws.set("openalgo.host", host)
            if ws_port is not None:
                ws.set("openalgo.ws_port", int(ws_port))
        except Exception as exc:
            logger.error("Failed to persist OpenAlgo config to workspace.json: %s", exc)
            return jsonify({
                "status": "error",
                "message": f"Could not persist config: {exc}",
            }), 500

        # Re-apply overrides into process env so any code reading .env picks
        # up the new values immediately.
        try:
            _apply_workspace_openalgo_overrides()
        except Exception:
            pass

        # Hot-reload OpenAlgoClient so subsequent backend→OpenAlgo calls
        # use the fresh credentials without requiring a restart.
        try:
            new_settings = Settings.from_env()
            new_client = OpenAlgoClient(new_settings)
            old_client = app.config.get("CLIENT")
            app.config["CLIENT"] = new_client
            # Best-effort close of the previous client's HTTP pool.
            if old_client is not None:
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(old_client.close())
                    finally:
                        loop.close()
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(
                "OpenAlgo config saved but client reinitialisation failed: %s", exc
            )
            return jsonify({
                "status": "partial",
                "message": f"Config saved but client not reloaded: {exc}",
            }), 200

        return jsonify({
            "status": "ok",
            "message": "OpenAlgo config saved and client reloaded",
        }), 200

    # ------------------------------------------------------------------
    # Connection-test endpoint — /ft-api/v1/test-connection
    # Used by the Setup wizard + Settings › Connection. The browser cannot
    # call OpenAlgo's /api/v1/ping directly because OpenAlgo does not send
    # CORS headers for our origin (and we will not modify OpenAlgo). We
    # proxy the test through our backend so it runs server-to-server with
    # no CORS involvement.
    # ------------------------------------------------------------------
    @app.route("/v1/test-connection", methods=["POST"])
    @limiter.limit("10 per minute")
    def _test_openalgo_connection() -> Any:
        """Server-side OpenAlgo connectivity + auth test.

        Accepts the exact ``{host, api_key}`` the user typed in the wizard,
        pings OpenAlgo, and returns a structured result. HTTP status is
        always 200 — the real outcome lives in the JSON body so the
        frontend can distinguish reachable/unreachable/auth-failed without
        tripping on HTTP error handling.
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify({
                "status": "error",
                "message": "This endpoint is only reachable from localhost",
            }), 403

        payload = request.get_json(silent=True) or {}
        # Strip one or more trailing slashes; setup wizard sometimes posts
        # the host with "/" or "//".
        host = str(payload.get("host", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", "")).strip()

        if not host or not api_key:
            return jsonify({
                "status": "error",
                "message": "host and api_key are required",
            }), 400

        import httpx as _httpx  # noqa: PLC0415

        try:
            resp = _httpx.post(
                f"{host}/api/v1/ping",
                json={"apikey": api_key},
                timeout=5.0,
            )
        except (_httpx.ConnectError, _httpx.ConnectTimeout) as exc:
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"Cannot reach OpenAlgo at {host}: {exc}",
            }), 200
        except _httpx.TimeoutException:
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"OpenAlgo at {host} did not respond within 5s",
            }), 200
        except Exception as exc:  # noqa: BLE001
            return jsonify({
                "status": "error",
                "reachable": False,
                "message": f"Connection test failed ({type(exc).__name__}): {exc}",
            }), 200

        if resp.status_code == 200:
            broker = "unknown"
            try:
                data = resp.json()
                if isinstance(data, dict):
                    broker = data.get("data", {}).get("broker") or data.get("broker") or "unknown"
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "ok",
                "reachable": True,
                "authenticated": True,
                "broker": broker,
                "message": f"Connected — broker: {broker}",
            }), 200

        if resp.status_code in (401, 403):
            msg = "Invalid API key"
            try:
                body = resp.json()
                if isinstance(body, dict):
                    msg = body.get("message", msg)
            except Exception:  # noqa: BLE001
                pass
            return jsonify({
                "status": "error",
                "reachable": True,
                "authenticated": False,
                "http_status": resp.status_code,
                "message": f"Reachable but auth failed (HTTP {resp.status_code}): {msg}",
            }), 200

        return jsonify({
            "status": "error",
            "reachable": True,
            "authenticated": False,
            "http_status": resp.status_code,
            "message": f"OpenAlgo returned unexpected HTTP {resp.status_code}",
        }), 200

    # ------------------------------------------------------------------
    # SPA fallback — registered LAST so it only matches unclaimed routes.
    # Returns 404 for API paths (so unknown /api/ or /v1/ endpoints still
    # look like 404s to clients) and serves the React bundle for every
    # other path.  Matches at most one path segment so deep React-router
    # paths like `/trade/scalper` all fall through to index.html.
    # ------------------------------------------------------------------
    if _frontend_available:
        from flask import Response as _Response, send_from_directory  # noqa: PLC0415

        _API_PREFIXES = ("/api/", "/ft-api/", "/v1/")

        def _serve_index_with_nonce() -> Any:
            """Serve index.html with the per-request CSP nonce woven into <script> tags.

            The matching ``'nonce-…'`` is added to the response's CSP header by
            ``_add_security_headers``; together they let the bootstrap script run under a
            nonce-based policy that forbids inline scripts (DS-CSP-01/09).
            """
            html = _dist_index.read_text(encoding="utf-8")
            nonce = getattr(_flask_g, "csp_nonce", None)
            if nonce:
                html = _inject_csp_nonce(html, nonce)
            return _Response(html, mimetype="text/html")

        @app.route("/", defaults={"path": ""}, endpoint="_spa_fallback")
        @app.route("/<path:path>", endpoint="_spa_fallback")
        def _spa_fallback(path: str) -> Any:
            """Serve the React SPA for any non-API path."""
            # API paths must never be intercepted — let Flask 404 them.
            req_path = request.path
            if any(req_path.startswith(p) for p in _API_PREFIXES):
                return jsonify({
                    "status": "error",
                    "message": "Not found",
                }), 404

            # If the exact file exists under dist/, serve it (favicon, assets/*).
            if path:
                candidate = _dist_path / path
                try:
                    # Guard against path traversal: resolved path must be
                    # inside _dist_path.
                    resolved = candidate.resolve()
                    if (
                        resolved.is_file()
                        and _dist_path.resolve() in resolved.parents
                    ):
                        return send_from_directory(
                            str(_dist_path), path
                        )
                except Exception:
                    pass

            # Otherwise serve index.html (SPA client-side routing) with the CSP nonce.
            return _serve_index_with_nonce()

    return app


def _run_flask_server(app: Flask, port: int = 5100) -> None:
    """Run the Flask API server in a daemon thread.

    Uses Waitress — a pure-Python, cross-platform production WSGI server
    (works identically on Windows, macOS, Linux).  Replaces Flask's
    built-in Werkzeug dev server, which emits a loud "this is a
    development server" warning and is not production-safe.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5100).
    """
    try:
        from waitress import serve as _waitress_serve  # noqa: PLC0415
    except ImportError:
        # Graceful fallback if waitress isn't installed — still works
        # for local dev, just prints the dev-server warning.
        logger.warning(
            "Waitress not installed; falling back to Werkzeug dev server. "
            "Install with: pip install waitress"
        )

        def _run() -> None:
            app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
    else:
        # Quiet Waitress's per-request access log — our structlog middleware
        # already logs requests via the traffic logger at a structured level.
        logging.getLogger("waitress").setLevel(logging.WARNING)

        def _run() -> None:
            # ident="FlintTrade" sets the Server: header instead of "waitress".
            # threads=8 is enough for a single-user dev/desktop setup.
            _waitress_serve(
                app,
                host="127.0.0.1",
                port=port,
                ident="FlintTrade",
                threads=8,
            )

    thread = threading.Thread(target=_run, name="flinttrade-api", daemon=True)
    thread.start()
    logger.info("FlintTrade API server started on http://127.0.0.1:%d", port)


class FlintTradeApp:
    """Main application — creates and wires all FlintTrade subsystems.

    Startup is resilient: if OpenAlgo is unreachable or optional services
    (Telegram, AI) are not configured, the app starts with warnings
    instead of crashing.

    Usage::

        app = FlintTradeApp()
        app.run()  # blocking — runs until Ctrl+C or SIGTERM
    """

    def __init__(self) -> None:
        # Load environment
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass

        self.version = _read_version()

        # Audit logger first — must be available before anything else
        self.audit = AuditLogger()
        self.audit.log_event("APP_START", version=self.version)

        # Core — settings + API client
        self.settings = Settings.from_env()
        self.client = OpenAlgoClient(self.settings)

        # Engine — safety + router + scheduler (deferred to avoid circular import
        # between core↔engine at module level).
        from flinttrade_engine.router import OrderRouter  # noqa: PLC0415
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415
        from flinttrade_engine.scheduler import StrategyScheduler, TimeScheduler  # noqa: PLC0415

        self.safety = SafetySystem(SafetyConfig(check_market_hours=True))
        self.router = OrderRouter(
            client=self.client,
            safety=self.safety,
            audit_logger=self.audit,
        )
        self.time_scheduler = TimeScheduler(client=self.client)
        self.scheduler = StrategyScheduler(
            client=self.client,
            time_scheduler=self.time_scheduler,
        )

        # Automation — cron manager (lazy import avoids loading APScheduler at
        # module level, which accounts for ~0.3 s of the startup penalty).
        from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
        )

        # Automation — Telegram bot (optional — token may not be set).
        # Lazy import avoids pulling in the python-telegram-bot dependency
        # (and its event-loop initialisation) until it is actually needed.
        from flinttrade_automation.telegram_bot import TelegramBot  # noqa: PLC0415

        self.telegram = TelegramBot(
            router=self.router,
            safety_system=self.safety,
            scheduler=self.scheduler,
            audit_logger=self.audit,
        )
        # Wire Telegram into cron so jobs can send alerts
        self.cron.telegram_bot = self.telegram

        # Gateway — broker registry + credential store + contract manager
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        self.credential_store = CredentialStore(
            flinttrade_dir / "credentials.db", master_password
        )
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        self.contract_manager = ContractManager(contracts_dir)
        self.registry = BrokerRegistry()

        # RAG — knowledge base (persistent).
        # LLMClient and RAGEngine are imported lazily here to avoid loading
        # ChromaDB, sentence-transformers, and the LLM HTTP client at module
        # level, which would add 2-5 s to startup time even when the AI
        # features are not yet used.
        if _rag_runtime_enabled():
            rag_dir = flinttrade_dir / "rag"
            rag_dir.mkdir(exist_ok=True)
            try:
                from flinttrade_ai.llm_client import LLMClient, LLMConfig  # noqa: PLC0415
                from flinttrade_ai.rag import RAGEngine  # noqa: PLC0415

                try:
                    _cfg = LLMConfig.from_env()
                    _llm_ok = bool(_cfg.provider)
                except Exception:
                    _llm_ok = False
                llm_client = LLMClient() if _llm_ok else None
                self.rag = RAGEngine(llm_client=llm_client, persist_directory=str(rag_dir))
                if self.rag.document_count() == 0:
                    if _rag_auto_index_enabled():
                        logger.info("RAG database empty — indexing docs/ directory in background...")
                        # Index documentation in background — do not block startup.
                        threading.Thread(
                            target=lambda: _index_rag_docs_safely(self.rag),
                            daemon=True,
                            name="rag-indexer",
                        ).start()
                    else:
                        logger.info(
                            "RAG database empty — automatic docs indexing disabled "
                            "(set FLINTTRADE_RAG_AUTO_INDEX=true to enable)",
                        )
            except Exception as exc:
                logger.warning("RAG initialisation failed: %s", exc)
                self.rag = None
        else:
            logger.info("RAG runtime disabled (set FLINTTRADE_RAG_ENABLED=true to enable)")
            self.rag = None

        # Live tick capture (opt-in via FLINTTRADE_TICK_CAPTURE) — wired in start().
        self._tick_recorder: Any | None = None
        self._tick_recorder_task: Any | None = None

        self._stop_event = asyncio.Event()

        logger.info("FlintTradeApp initialised — v%s", self.version)

    async def start(self) -> None:
        """Start all services and wait until stopped."""
        # Start FlintTrade API server (Flask, port 5100)
        flask_app = create_flask_app(
            safety=self.safety,
            scheduler=self.scheduler,
            cron=self.cron,
            audit=self.audit,
            client=self.client,
            registry=self.registry,
            credential_store=self.credential_store,
            contract_manager=self.contract_manager,
            rag=self.rag,
        )
        _run_flask_server(flask_app, port=5100)

        # Load market holidays (graceful — warns if OpenAlgo unreachable)
        try:
            await self.cron.load_holidays()
        except Exception as exc:
            logger.warning("Could not load holidays (OpenAlgo may be starting): %s", exc)

        # Hand the cron manager the shared trade store (created by the Flask
        # factory above) so the nightly DuckDB maintenance job can CHECKPOINT +
        # ANALYZE the same connection under its lock.
        self.cron.trade_storage = flask_app.config.get("TRADE_STORAGE")
        self.cron.trade_storage_lock = flask_app.config.get("TRADE_STORAGE_LOCK")

        # Wire the "optimise overnight" feature to a real engine. The cron slot
        # (make_overnight_optimise_job) existed but nothing injected an optimiser,
        # so the nightly job never ran. Build an OvernightOptimiser over the
        # registered strategies + a rule-based StrategyRefiner and inject its
        # run() as the job. Best-effort: a missing runner/refiner just leaves the
        # job unregistered (as before) rather than failing boot.
        try:
            from flinttrade_ai.optimiser_report_store import OptimiserReportStore  # noqa: PLC0415
            from flinttrade_ai.overnight_optimiser import (  # noqa: PLC0415
                OvernightOptimiser,
                enrich_strategies,
            )
            from flinttrade_ai.strategy_refiner import StrategyRefiner  # noqa: PLC0415
            from flinttrade_backtest.result_store import BacktestResultStore  # noqa: PLC0415

            # The report store is created unconditionally so the Lab UI can read
            # past reports even when the optimiser isn't wired this boot.
            _report_store = OptimiserReportStore(_workspace_dir() / "optimiser-reports")
            flask_app.config["OPTIMISER_REPORT_STORE"] = _report_store

            # Per-strategy backtest-results store: written on every backtest run
            # (backtest_routes), read here so the optimiser refines on REAL
            # metrics instead of an empty dict. Before this the refiner only ever
            # saw {} and produced generic rule-based output (R16).
            _bt_result_store = BacktestResultStore(_workspace_dir() / "backtest-results")
            flask_app.config["BACKTEST_RESULT_STORE"] = _bt_result_store

            _runner = flask_app.config.get("STRATEGY_RUNNER")

            def _strategy_provider() -> list[dict[str, Any]]:
                """Live roster joined to each strategy's latest backtest metrics."""
                roster: list[dict[str, Any]] = []
                if _runner is not None and hasattr(_runner, "list_strategies"):
                    try:
                        roster = _runner.list_strategies()
                    except Exception:  # noqa: BLE001 - a broken runner falls back to stored-only
                        roster = []
                return enrich_strategies(roster, _bt_result_store)

            # Wired unconditionally now: even with no uploaded strategies, any
            # strategy that has been backtested gets refined overnight.
            _optimiser = OvernightOptimiser(
                strategy_provider=_strategy_provider,
                refiner=StrategyRefiner(),  # rule-based by default (no LLM required)
                report_sink=_report_store.write,  # persist each night's report
            )
            self.cron.overnight_optimiser = _optimiser.run
        except Exception as exc:
            logger.warning("Overnight optimiser not wired (%s); nightly optimisation will not run", exc)

        # Register built-in cron jobs AND start the scheduler. Without start()
        # APScheduler never runs, so none of the built-in jobs fire — the
        # nightly DuckDB CHECKPOINT+ANALYZE (db_optimise_job), square-off
        # warning, EOD logout, and health check were all inert. Wrapped so a
        # missing/broken APScheduler degrades to "no cron" instead of failing
        # the whole boot.
        self.cron.register_builtin_jobs()
        try:
            self.cron.start()
        except Exception as exc:
            logger.warning(
                "Cron scheduler failed to start (%s); scheduled jobs will not run",
                exc,
            )

        # Live tick capture (opt-in). Uses its OWN StorageManager (a separate
        # DuckDB file) so the recorder's async-loop writes never share a
        # connection with the Flask-thread trade journal (DuckDB connections are
        # not safe for concurrent use). Launched as a background task on this
        # loop; auto-reconnects to the OpenAlgo WebSocket.
        if _tick_capture_enabled():
            try:
                from flinttrade_data.storage import StorageManager as _TickStore  # noqa: PLC0415
                from flinttrade_data.tick_recorder import TickRecorder  # noqa: PLC0415

                tick_db = str(_workspace_dir() / "ticks.duckdb")
                tick_storage = _TickStore(tick_db)
                tick_storage.initialise()
                # One lock guards this tick store's single DuckDB connection: the
                # recorder writes on the async loop, the nightly db_optimise job
                # CHECKPOINTs it on the scheduler thread. Both must serialise.
                tick_lock = threading.Lock()
                # Live order-flow aggregator: fed from each tick and exposed to
                # the orderflow route so the footprint widget shows REAL buy/sell
                # delta (not synthetic) while tick capture is running.
                from flinttrade_data.orderflow_aggregator import OrderFlowAggregator  # noqa: PLC0415
                orderflow = OrderFlowAggregator()
                flask_app.config["ORDERFLOW_AGGREGATOR"] = orderflow
                recorder = TickRecorder(
                    storage=tick_storage, storage_lock=tick_lock, orderflow_aggregator=orderflow
                )
                # Hand the tick store to the cron so nightly maintenance keeps the
                # highest-volume DuckDB file from growing unbounded. register_
                # builtin_jobs already ran, but the job resolves this lazily.
                self.cron.tick_storage = tick_storage
                self.cron.tick_storage_lock = tick_lock
                # Keep ~90 days of ticks by default so the store stays bounded;
                # the nightly tick_retention_job prunes older rows.
                self.cron.tick_retention_days = 90
                # Default watchlist — the major indices in quote mode. Operators
                # can extend this; an empty watchlist would capture nothing.
                recorder.add_symbols(
                    [
                        {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
                        {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},
                        {"exchange": "BSE_INDEX", "symbol": "SENSEX"},
                    ],
                    mode="quote",
                )
                self._tick_recorder = recorder
                self._tick_recorder_task = asyncio.create_task(recorder.run())
                logger.info("Live tick capture started → %s", tick_db)
            except Exception as exc:
                logger.warning("Tick capture failed to start (%s); not recording ticks", exc)

        # Broker SDK attestation — log which native broker SDKs match brokers.lock
        # so the operator can see what is / isn't ready to go live. No native
        # adapter is wired into the router yet, so this is informational here;
        # the halt loop (attest_loop + on_failure) is ready for when they are.
        try:
            from .broker_sdk_attest import attest_all, log_report  # noqa: PLC0415

            log_report(attest_all())
        except Exception as exc:  # pragma: no cover - never let attestation break boot
            logger.warning("Broker SDK attestation failed (%s)", exc)

        # Verify OpenAlgo connectivity (non-fatal). Distinguish three
        # cases so the boot log is not misleading: REACHABLE_AUTHENTICATED,
        # REACHABLE_AUTH_FAILED, UNREACHABLE.
        try:
            import httpx  # noqa: PLC0415
            from .exceptions import OpenAlgoAuthError  # noqa: PLC0415

            try:
                result = await self.client.ping()
                broker = (
                    result.get("data", {}).get("broker", "unknown")
                    if isinstance(result, dict)
                    else "unknown"
                )
                logger.info(
                    "FlintTrade v%s started — OpenAlgo %s REACHABLE, authenticated (broker: %s)",
                    self.version, self.settings.openalgo_host, broker,
                )
            except OpenAlgoAuthError as exc:
                # Server responded but rejected the API key — reachable,
                # auth failed.  Don't confuse users with "UNREACHABLE".
                logger.warning(
                    "FlintTrade v%s started — OpenAlgo %s REACHABLE but AUTH FAILED "
                    "(status %d): %s. Configure the API key in /setup or ~/.flinttrade/workspace.json.",
                    self.version,
                    self.settings.openalgo_host,
                    exc.status_code,
                    exc.message,
                )
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
                logger.warning(
                    "FlintTrade v%s started — OpenAlgo %s UNREACHABLE (%s: %s). "
                    "Start OpenAlgo on that host/port and FlintTrade will reconnect on next call.",
                    self.version,
                    self.settings.openalgo_host,
                    type(exc).__name__,
                    exc,
                )
        except Exception as exc:
            # Any other unexpected error — log full class + message so we
            # don't pretend we know what happened.
            logger.warning(
                "FlintTrade v%s started — OpenAlgo %s verification failed (%s: %s).",
                self.version,
                self.settings.openalgo_host,
                type(exc).__name__,
                exc,
            )

        # Wait for shutdown signal
        await self._stop_event.wait()

    async def stop(self) -> None:
        """Gracefully shut down all services."""
        logger.info("FlintTrade shutting down...")

        # Stop strategies
        await self.scheduler.stop_all()

        # Stop cron
        self.cron.stop()

        # Stop tick capture (signal the loop to exit, then cancel the task)
        if self._tick_recorder is not None:
            self._tick_recorder.stop()
        if self._tick_recorder_task is not None:
            self._tick_recorder_task.cancel()

        # Log shutdown to audit before closing
        self.audit.log_event("APP_STOP", version=self.version)

        # Close API client
        await self.client.close()

        # Close audit logger
        self.audit.close()

        logger.info("FlintTrade v%s stopped", self.version)

        self._stop_event.set()

    def run(self) -> None:
        """Run the application (blocking). Handles Ctrl+C gracefully."""
        # NOTE: stdlib logging is already configured by create_flask_app()
        # with a structlog-backed formatter. Calling basicConfig() here
        # would add a second root handler and re-introduce the dual-emit
        # bug. Don't do it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Handle signals
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: loop.create_task(self.stop()))
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            loop.run_until_complete(self.start())
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            loop.close()


if __name__ == "__main__":
    FlintTradeApp().run()


# ---------------------------------------------------------------------------
# Module-level ``app`` for gunicorn / WSGI servers.
#   Usage: ``gunicorn 'flinttrade_core.app:app'``
#
# The Flask app is created LAZILY the first time ``app`` is imported from
# this module.  We avoid eagerly building it at module import because
# running ``python -m flinttrade_core.app`` would create one instance
# here and another inside ``FlintTradeApp.start()``, printing every
# startup log line twice and tripping the CPython "RuntimeWarning: ...
# found in sys.modules after import of package ..." warning.
#
# Python 3.7+ supports module-level ``__getattr__`` (PEP 562) which gives
# us lazy attribute access with no change to the consumer API — WSGI
# servers do ``from flinttrade_core.app import app`` and still get a
# real Flask instance on first use.
# ---------------------------------------------------------------------------

_APP_CACHE: Flask | None = None


def _get_wsgi_app() -> Flask:
    """Lazily construct (and cache) the WSGI Flask app."""
    global _APP_CACHE
    if _APP_CACHE is None:
        _APP_CACHE = create_flask_app()
    return _APP_CACHE


def __getattr__(name: str) -> Any:
    """PEP 562 module __getattr__ — produce ``app`` on first access only."""
    if name == "app":
        return _get_wsgi_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
