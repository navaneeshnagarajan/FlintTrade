"""Native credential-replay login step (Phase 1 G3).

The missing link between the encrypted credential vault and a live native
broker session. A native adapter (Dhan/Upstox/Kotak Neo/INDmoney/Groww) is
*constructed* by ``build_native_adapters`` once its SDK attests and the vault
holds credentials, but until something decrypts those credentials, calls the
adapter's ``login()``, and registers the resulting ``Session`` under the
adapter's ``(adapter_id, account_id)`` selector, the ``BrokerRouter`` has no
session to dispatch to — every read and write for that selector fails. This
module is that step.

It is deliberately broker-agnostic: it only speaks the ``BrokerAdapter.login``
contract and the exact registry publication owner, so the same
code path serves boot-time re-establishment, an interactive "connect broker"
action, and daily token re-authentication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from flinttrade_core.broker_account_cutover import MutationAdmission, require_broker_account_mutations
from flinttrade_core.broker_identity import CredentialVersion

logger = logging.getLogger("flinttrade.gateway.native_login")

SESSION_INVALID_RELOGIN_MESSAGE = "Broker session expired or invalid; re-login required."
CREDENTIALS_UNAVAILABLE_MESSAGE = "Broker credentials unavailable; re-login required."
BROKER_LOGIN_RETRY_MESSAGE = "Broker login is temporarily unavailable; retry later."


def _is_transient_probe_error(exc: BaseException) -> bool:
    """True for transport hiccups that are NOT proof a token is dead.

    A connect/timeout/network error means we could not reach the broker — the
    token may be perfectly valid — so the liveness probe must keep the session
    rather than false-alarming ``needs_relogin``. A 4xx (auth) or a broker
    error payload, by contrast, is a real "this token does not work".

    The current natives use three HTTP stacks — INDmoney/Groww raw ``httpx``,
    Upstox ``urllib3`` (via ``upstox_client``), Dhan/Kotak Neo ``requests`` —
    so transport errors surface as different exception classes. All three
    families' timeout/connection errors (plus the stdlib fallbacks) are
    classified transient; a real 4xx auth error is a distinct exception on every
    stack (``httpx.HTTPStatusError`` / ``ApiException`` / a broker error dict),
    so it is never misclassified as transient.
    """
    # stdlib transport/timeout (also the base of some SDK errors)
    import socket  # noqa: PLC0415

    if isinstance(exc, (socket.timeout, ConnectionError, TimeoutError)):
        return True
    for module, names in (
        ("httpx", ("ConnectError", "ConnectTimeout", "ReadTimeout", "WriteTimeout", "PoolTimeout", "NetworkError")),
        ("requests.exceptions", ("ConnectionError", "Timeout", "ConnectTimeout", "ReadTimeout")),
        ("urllib3.exceptions", ("TimeoutError", "ConnectionError", "NewConnectionError", "MaxRetryError", "ProtocolError")),
    ):
        try:
            mod = __import__(module, fromlist=["*"])
        except ImportError:  # pragma: no cover - optional per adapter SDK
            continue
        classes = tuple(getattr(mod, n) for n in names if hasattr(mod, n))
        if classes and isinstance(exc, classes):
            return True
    return False


# Substrings (compared case-insensitively) that mark a probe read failure as a
# genuine *service-window* closure — the venue/endpoint is shut for its nightly
# maintenance window — which does NOT prove the access token is dead. Upstox's
# funds endpoint, for instance, is offline 12:00 AM–5:30 AM IST nightly and
# replies "The Funds service is accessible from 5:30 AM to 12:00 AM IST daily.
# Please try again during these service hours." Treating that as a dead token
# would throw a freshly-minted, valid session away every night. Matched on text
# because such closures surface as a generic ``BrokerError`` with no distinct
# type. Kept deliberately NARROW: broad retry/throttle phrasing ("rate limit",
# "too many requests", "try again later") is intentionally absent because it
# collides with genuine auth/lockout messages — rate limiting is recognised by
# its typed ``RateLimitError`` in :func:`verify_native_session` instead.
_SERVICE_WINDOW_MARKERS = (
    "accessible from",  # "... service is accessible from 5:30 AM to 12:00 AM ..."
    "service hours",  # "... try again during these service hours"
    "try again during",
    "under maintenance",
    "maintenance window",
    "temporarily unavailable",
    "service unavailable",
    "service is unavailable",
)


def _is_service_window_error(exc: BaseException) -> bool:
    """True when a probe read failed because the broker service window was closed.

    A closed venue/maintenance window is not proof the token is dead, so — like a
    transport blip — it must KEEP the session rather than false-alarm
    ``needs_relogin``. Matched on the error text because such closures surface as
    a generic ``BrokerError`` with no distinct type. Auth failures take
    precedence (see :func:`_is_auth_failure`), so a dead token whose message also
    carries maintenance phrasing is still evicted.
    """
    return any(marker in str(exc).lower() for marker in _SERVICE_WINDOW_MARKERS)


# Substrings that unambiguously mark a DEAD credential (evict + surface
# ``needs_relogin``). Used only as a fallback for adapters that raise a generic
# exception instead of the typed ``AuthError`` subtree.
_AUTH_FAILURE_MARKERS = (
    "unauthorized",
    "401",
    "403",
    "forbidden",
    "invalid token",
    "token expired",
    "expired token",
    "access token",
    "invalid credential",
    "authentication failed",
    "session expired",
    "please login",
    "please log in",
    "account locked",
    "too many failed",
)


def _is_auth_failure(exc: BaseException) -> bool:
    """True when a probe error proves the token is DEAD — evict + ``needs_relogin``.

    Takes precedence over every keep path (transient / service-window / rate
    limit), so a genuine 401 / lockout whose broker message happens to carry
    retry or maintenance phrasing is surfaced rather than masked. Typed first —
    adapters map 401/403/expired to the :class:`AuthError` subtree — with an
    unambiguous-message fallback for adapters that raise a generic exception.
    ``BrokerSessionDegraded`` is excluded: its credentials are authentic (only a
    runtime constraint blocks writes), so its session must be kept.
    """
    from flinttrade_core.exceptions import AuthError, BrokerSessionDegraded  # noqa: PLC0415

    if isinstance(exc, AuthError):
        return not isinstance(exc, BrokerSessionDegraded)
    return any(marker in str(exc).lower() for marker in _AUTH_FAILURE_MARKERS)


def should_keep_session_after_probe_error(exc: BaseException) -> bool:
    """Return True when a liveness-probe error does not prove auth is dead."""
    from flinttrade_core.exceptions import NetworkError, RateLimitError  # noqa: PLC0415

    return not _is_auth_failure(exc) and (
        _is_transient_probe_error(exc)
        or _is_service_window_error(exc)
        or isinstance(exc, (RateLimitError, NetworkError))
    )


def should_drop_session_after_probe_error(exc: BaseException) -> bool:
    """Return True when an error proves the native broker session is dead."""
    return _is_auth_failure(exc)


@dataclass(repr=False)
class NativeSessionCandidate:
    """Owner-held unpublished authentication result; never renders replay material."""

    session: Any
    replay_credentials: dict[str, Any] = field(repr=False)
    probe_error: str | None = None
    registry_version: Any = None

    @property
    def expires_at(self) -> float:
        return self.session.expires_at

    @property
    def is_read_only(self) -> bool:
        return self.session.is_read_only

    def __repr__(self) -> str:
        return "<NativeSessionCandidate>"

    def __reduce_ex__(self, protocol: int) -> Any:
        raise TypeError("native_candidate_not_serialisable")


_QUARANTINED_CANDIDATES: list[NativeSessionCandidate] = []


def quarantine_native_candidate(candidate: NativeSessionCandidate) -> None:
    """Retain unclaimed payloads without guessing SDK disposal semantics."""
    if not any(owned is candidate for owned in _QUARANTINED_CANDIDATES):
        _QUARANTINED_CANDIDATES.append(candidate)


async def verify_native_session(adapter: Any, session: Any) -> str | None:
    """Probe an unpublished payload; this function never mutates a registry."""
    reader = getattr(adapter, "funds", None)
    if not callable(reader):
        return None
    try:
        await reader(session)
    except Exception as exc:
        if not should_keep_session_after_probe_error(exc):
            return SESSION_INVALID_RELOGIN_MESSAGE
    return None


async def prepare_native_session(
    adapter: Any, credentials: dict[str, Any], *, verify: bool,
    mutation_admission: MutationAdmission = require_broker_account_mutations,
) -> NativeSessionCandidate:
    """Authenticate outside the registry; production remains denied before work."""
    mutation_admission()
    session = await adapter.login(credentials)
    candidate = NativeSessionCandidate(session, dict(credentials))
    try:
        if verify:
            candidate.probe_error = await verify_native_session(adapter, session)
        replay = getattr(adapter, "replay_credentials", None)
        if callable(replay) and candidate.probe_error is None:
            value = replay(dict(credentials), session)
            if isinstance(value, dict):
                candidate.replay_credentials = value
    except BaseException:
        quarantine_native_candidate(candidate)
        raise
    if candidate.probe_error is not None:
        quarantine_native_candidate(candidate)
    return candidate


async def establish_native_session(
    adapter: Any, registry: Any, credentials: dict[str, Any],
    adapter_id: str, account_id: str, credential_store: Any | None = None,
    verify: bool = False, *,
    mutation_admission: MutationAdmission = require_broker_account_mutations,
    registry_publication_owner: Any | None = None,
    workspace_path: Any | None = None,
    credential_version: CredentialVersion | None = None,
) -> Any:
    """Replay material read under an explicitly captured credential version.

    The caller captures the version before retrieval. Fresh reads only validate
    that witness; missing authority is refused after the production guard.
    """
    mutation_admission()
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
    from flinttrade_core.broker_identity import BrokerSelector
    from flinttrade_core.workspace_migrations import broker_workspace_version, read_workspace_snapshot

    from .registry import ManagedSessionAuthority, RegistryPublicationOwner

    owner = registry_publication_owner
    if (type(owner) is not RegistryPublicationOwner or not owner.owns(registry)
            or workspace_path is None or credential_store is None):
        raise RegistrySessionUnavailable
    selector = BrokerSelector(adapter_id, account_id)
    if type(credential_version) is not CredentialVersion:
        raise RegistrySessionUnavailable
    credential_version.__post_init__()
    if credential_version.selector != selector or credential_version.generation == 0:
        raise RegistrySessionUnavailable
    expected = registry.snapshot_selector(selector)
    before = credential_store.selector_state(selector)
    if (not before.present or not before.credential_present or before.origin != "managed"
            or before.version != credential_version):
        raise RegistrySessionUnavailable
    candidate = None
    try:
        candidate = await prepare_native_session(adapter, credentials, verify=verify, mutation_admission=mutation_admission)
        if candidate.probe_error is not None:
            from .exceptions import AuthFlowError
            raise AuthFlowError(candidate.probe_error)
        if credential_store.selector_state(selector).version != credential_version:
            raise RegistrySessionUnavailable
        final_version = credential_version
        if candidate.replay_credentials != credentials:
            final_version = credential_store.update_credentials(
                selector, candidate.replay_credentials, expected=credential_version)
        state = credential_store.selector_state(selector)
        if (not state.present or not state.credential_present or state.origin != "managed"
                or state.version != final_version):
            raise RegistrySessionUnavailable
        workspace = read_workspace_snapshot(workspace_path)
        authority = ManagedSessionAuthority(final_version, workspace.version, broker_workspace_version(workspace))
        metadata = credential_store.account_for_selector(selector)
        receipt = owner.prepare_session_candidate(selector, candidate.session, expected_registry=expected,
            authority=authority, broker=metadata.broker, label=metadata.label)
        try:
            current = read_workspace_snapshot(workspace_path)
            state = credential_store.selector_state(selector)
            if (not state.present or not state.credential_present or state.origin != "managed"
                    or state.version != final_version):
                raise RegistrySessionUnavailable
        except BaseException:
            owner.abandon_prepared_candidate(receipt)
            raise
        result = owner.publish_prepared_candidate(receipt, current_authority=ManagedSessionAuthority(
            final_version, current.version, broker_workspace_version(current)))
        candidate.registry_version = result.version.registry_version
    except BaseException:
        if candidate is not None:
            quarantine_native_candidate(candidate)
        from flinttrade_core.account_mutation_contracts import RegistryVersionConflict
        try:
            owner.remove_session_for_exact(selector, expected_registry=expected)
        except RegistryVersionConflict:
            pass  # A concurrent successor is never ours to retire.
        raise
    return candidate


async def establish_native_sessions(
    native_adapters: dict[str, Any],
    registry: Any,
    credential_store: Any,
    selectors: list[str],
    verify: bool = False,
    *,
    mutation_admission: MutationAdmission = require_broker_account_mutations,
    registry_publication_owner: Any | None = None,
    workspace_path: Any | None = None,
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
        verify: When True, probe each freshly-established session with a cheap
            authenticated read so a dead token surfaces as a failure rather than
            a false "ok". Transient probe failures keep the session; transient
            login failures leave the selector sessionless with a retry message.

    Returns:
        ``{selector: "ok" | "<error>"}`` for admitted replay attempts.

    Raises:
        BrokerAccountCutoverUnavailable: Before any lookup while cutover is active.
    """
    mutation_admission()
    from flinttrade_core.account_mutation_contracts import RegistrySessionUnavailable
    from flinttrade_core.broker_identity import BrokerSelector
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
            exact_selector = BrokerSelector(adapter_id, account_id)
            before = credential_store.selector_state(exact_selector)
            if not before.present or not before.credential_present or before.origin != "managed":
                raise RegistrySessionUnavailable
            credentials = credential_store.retrieve_for(adapter_id, account_id)
            after = credential_store.selector_state(exact_selector)
            if (not after.present or not after.credential_present or after.origin != "managed"
                    or after.version != before.version):
                raise RegistrySessionUnavailable
        except Exception as exc:  # noqa: BLE001 - a missing/undecryptable row must not brick boot
            logger.info(
                "No usable vault credentials for %s (%s) — leaving sessionless",
                adapter_id, type(exc).__name__,
            )
            results[selector] = CREDENTIALS_UNAVAILABLE_MESSAGE
            continue
        try:
            await establish_native_session(
                adapter, registry, credentials, adapter_id, account_id,
                credential_store=credential_store, verify=verify, mutation_admission=mutation_admission,
                registry_publication_owner=registry_publication_owner, workspace_path=workspace_path,
                credential_version=before.version,
            )
            results[selector] = "ok"
        except Exception as exc:  # noqa: BLE001 - per-selector isolation
            logger.warning("Native login failed for %s (%s)", adapter_id, type(exc).__name__)
            if should_keep_session_after_probe_error(exc):
                results[selector] = BROKER_LOGIN_RETRY_MESSAGE
            else:
                results[selector] = SESSION_INVALID_RELOGIN_MESSAGE
    return results
