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
contract and the exact registry publication owner. The normal factory does not
invoke authentication during startup or GET requests: explicit CONNECT and
RECONNECT use the account transaction and lifecycle owners. Legacy replay
helpers remain guarded and cannot bypass that production cutover.
"""

from __future__ import annotations

import inspect
import logging
import math
import time
from collections.abc import Callable
from contextvars import ContextVar
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
        (
            "urllib3.exceptions",
            ("TimeoutError", "ConnectionError", "NewConnectionError", "MaxRetryError", "ProtocolError"),
        ),
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
    identity_evidence: object | None = field(default=None, repr=False)

    def require_identity(self, adapter: object, account: str) -> None:
        """Require this exact candidate's producer receipt for the selected account."""
        proof = self.identity_evidence
        if (type(proof) is not _VerifiedNativeIdentity or proof.adapter is not adapter
                or proof is not self.session.extra.get("_verified_native_identity")
                or verified_session_identity(self.session) != account):
            raise ValueError("candidate_native_identity_unavailable")

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


async def verify_native_session(
    adapter: Any,
    session: Any,
    *,
    strict_probe: bool = False,
    registry_publication_owner: Any | None = None,
    current_authority: Any | None = None,
) -> str | None:
    """Probe without publication, distinguishing admission from continuity.

    Args:
        adapter: External liveness provider, with funds as the legacy fallback.
        session: Exact unpublished candidate or current sealed registry handle.
        strict_probe: Require an actual successful probe for fresh admission.
            The default preserves legacy keep-session policy, not verification.
        registry_publication_owner: Exact existing owner for a shorter published lifetime.
        current_authority: Server-resolved current lookup witness; not caller flags.

    Returns:
        A legacy invalid-session message, or None after the applicable policy.
        None can mean that an expired observation was applied successfully; it
        is not an alive/ready flag. Callers making an authority decision must
        reacquire the current session through the existing registry lookup.

    Raises:
        RuntimeError: Strict verification has no callable probe.
        BaseException: A strict probe fails or either policy is cancelled.
    """
    reader = getattr(adapter, "liveness", None)
    if not callable(reader):
        reader = getattr(adapter, "funds", None)
    if not callable(reader):
        if strict_probe:
            raise RuntimeError("native_verification_unavailable")
        return None
    try:
        observation = await reader(session)
        from .registry import ConnectedRegistrySession, RegistryPublicationOwner

        if type(session) is ConnectedRegistrySession and getattr(adapter, "broker_id", None) == "dhan":
            # The adapter's continuity observation must not mutate a sealed view.
            # Only its existing registry owner can shorten and revoke a prior
            # generation; an absent owner cannot silently ignore new evidence.
            if type(observation) not in (int, float) or not math.isfinite(observation) or observation < 0:
                raise RuntimeError("native_continuity_observation_unavailable")
            if registry_publication_owner is not None or observation < session.expires_at:
                if type(registry_publication_owner) is not RegistryPublicationOwner:
                    raise RuntimeError("native_continuity_owner_unavailable")
                registry_publication_owner.shorten_session_expiry(
                    session,
                    min(observation, session.expires_at),
                    current_authority=current_authority,
                )
    except Exception as exc:
        if strict_probe:
            raise
        if not should_keep_session_after_probe_error(exc):
            return SESSION_INVALID_RELOGIN_MESSAGE
    from flinttrade_gateway.monday_read_smoke import MONDAY_READ_BROKERS, probe_monday_session_reads

    broker_id = str(getattr(adapter, "broker_id", "") or "")
    if broker_id in MONDAY_READ_BROKERS and not strict_probe:
        await probe_monday_session_reads(adapter, session)
    return None


_IDENTITY_SEAL = object()


class _VerifiedNativeIdentity:
    """Opaque provider result bound to the actual login resource and session."""

    __slots__ = ("session", "adapter", "resource", "account", "seal", "binding")

    def __init__(self) -> None:
        """Reject caller construction; only the active provider authentication frame issues receipts."""
        raise TypeError("provider identity is issued by authentication")


def verified_session_identity(session: object) -> str | None:
    """Read only a genuine, still-bound authentication receipt, never extra flags."""
    from .brokers._base import Session
    from .brokers.dhan import DhanAdapter
    from .brokers.kotakneo import KotakNeoAdapter
    from .brokers.kotakneo_sdk import KotakNeoSdkSession

    if type(session) is not Session:
        return None
    proof = session.extra.get("_verified_native_identity")
    if (type(proof) is not _VerifiedNativeIdentity or proof.seal is not _IDENTITY_SEAL
            or proof.session is not session or proof.account != session.account_id
            or proof.binding != (session.access_token, session.expires_at, session.account_id,
                                  session.adapter_id, id(session.extra.get("client")))):
        return None
    if type(proof.adapter) is DhanAdapter and proof.resource is session and session.adapter_id == "dhan":
        return proof.account
    if (type(proof.adapter) is KotakNeoAdapter and type(proof.resource) is KotakNeoSdkSession
            and proof.resource is session.extra.get("client") and not proof.resource._closed
            and session.adapter_id == "kotakneo"):
        return proof.account
    return None


_IDENTITY_FRAME: ContextVar[Any] = ContextVar("native_authentication_identity", default=None)


def observe_provider_identity(producer: object, resource: object, native_account: str) -> None:
    """Retain validated profile/UCC facts only inside their actual auth producer.

    Dhan calls this after profile validation. Kotak calls it after both installed
    View/Trade steps. Continuity probes outside candidate authentication do not
    issue a new identity receipt or change an existing historical binding.
    """
    from .brokers.dhan import DhanAdapter
    from .brokers.kotakneo import KotakNeoAdapter
    from .brokers.kotakneo_sdk import KotakNeoSdkSession

    frame = _IDENTITY_FRAME.get()
    if frame is None:
        return
    adapter, observations = frame
    valid = (type(adapter) is DhanAdapter and producer is adapter)
    valid = valid or (type(adapter) is KotakNeoAdapter and producer is resource
                      and type(resource) is KotakNeoSdkSession)
    if not valid or type(native_account) is not str or not native_account or observations:
        raise ValueError("native authentication identity producer mismatch")
    observations.append((resource, native_account))


async def prepare_native_session(
    adapter: Any, credentials: dict[str, Any], *, verify: bool,
    mutation_admission: MutationAdmission = require_broker_account_mutations,
    strict_probe: bool = False, accept_candidate: Callable[[NativeSessionCandidate], None] | None = None,
) -> NativeSessionCandidate:
    """Preserve early cleanup custody and bind genuine provider identity to its candidate."""
    observations: list[tuple[object, str]] = []
    token = _IDENTITY_FRAME.set((adapter, observations))
    try:
        candidate = await _prepare_native_session(
            adapter, credentials, verify=verify, mutation_admission=mutation_admission,
            strict_probe=strict_probe, accept_candidate=accept_candidate,
        )
        if len(observations) == 1 and candidate.probe_error is None:
            resource, account = observations[0]
            proof = object.__new__(_VerifiedNativeIdentity)
            proof.session, proof.adapter, proof.resource = candidate.session, adapter, resource
            proof.account, proof.seal = account, _IDENTITY_SEAL
            proof.binding = (candidate.session.access_token, candidate.session.expires_at, candidate.session.account_id,
                             candidate.session.adapter_id, id(candidate.session.extra.get("client")))
            candidate.session.extra["_verified_native_identity"] = proof
            candidate.identity_evidence = proof
        return candidate
    finally:
        _IDENTITY_FRAME.reset(token)


async def _prepare_native_session(
    adapter: Any,
    credentials: dict[str, Any],
    *,
    verify: bool,
    mutation_admission: MutationAdmission = require_broker_account_mutations,
    strict_probe: bool = False,
    accept_candidate: Callable[[NativeSessionCandidate], None] | None = None,
) -> NativeSessionCandidate:
    """Prepare under explicit custody, without publishing or granting authority.

    Args:
        adapter: External authentication and optional replay-export provider.
        credentials: Detached credential input for this attempt only.
        verify: Optional authentication probe, never a TLS verification setting.
            Provisional sessions always require successful strict verification.
        mutation_admission: Existing fail-closed admission check before login.
        strict_probe: Require successful verification rather than legacy
            session-continuity policy. Requires verify to be True.
        accept_candidate: Synchronous custody transfer immediately after login,
            before any probe/export. A successful None return means the caller
            retains this exact session even if later preparation raises.

    Returns:
        The actual unpublished candidate; legacy probe errors remain explicit.

    Raises:
        ValueError: Strict probing is requested without verification.
        TypeError: The supplied custody callback is not synchronous or returns
            a non-None value; the unclaimed payload stays quarantined.
        BaseException: Admission, login, custody, probe or export fails. Original
            failure/cancellation propagates; accepted custody stays caller-owned.
    """
    mutation_admission()
    if strict_probe and not verify:
        raise ValueError("native_verification_required")
    if accept_candidate is not None and (
        not callable(accept_candidate) or inspect.iscoroutinefunction(accept_candidate)
    ):
        raise TypeError("native_candidate_custody_invalid")
    session = await adapter.login(credentials)
    candidate = NativeSessionCandidate(session, dict(credentials))
    accepted = False
    try:
        if accept_candidate is not None:
            result = accept_candidate(candidate)
            if result is not None:
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("native_candidate_custody_incomplete")
            accepted = True
        expiry = session.expires_at
        provisional = type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time()
        # Optional legacy probing is not evidence for a newly created provisional
        # session. Strict success and provider-derived future expiry are required
        # even when verify=False; prior-session continuity remains separate.
        if verify or provisional:
            candidate.probe_error = await verify_native_session(
                adapter, session, strict_probe=strict_probe or provisional
            )
        expiry = session.expires_at
        if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time():
            raise RuntimeError("native_session_expiry_unverified")
        replay = getattr(adapter, "replay_credentials", None)
        if callable(replay) and candidate.probe_error is None:
            value = replay(dict(credentials), session)
            if isinstance(value, dict):
                candidate.replay_credentials = value
    except BaseException:
        if not accepted:
            quarantine_native_candidate(candidate)
        raise
    if candidate.probe_error is not None and not accepted:
        quarantine_native_candidate(candidate)
    return candidate


async def establish_native_session(
    adapter: Any,
    registry: Any,
    credentials: dict[str, Any],
    adapter_id: str,
    account_id: str,
    credential_store: Any | None = None,
    verify: bool = False,
    *,
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
    if (
        type(owner) is not RegistryPublicationOwner
        or not owner.owns(registry)
        or workspace_path is None
        or credential_store is None
    ):
        raise RegistrySessionUnavailable
    selector = BrokerSelector(adapter_id, account_id)
    if type(credential_version) is not CredentialVersion:
        raise RegistrySessionUnavailable
    credential_version.__post_init__()
    if credential_version.selector != selector or credential_version.generation == 0:
        raise RegistrySessionUnavailable
    expected = registry.snapshot_selector(selector)
    before = credential_store.selector_state(selector)
    if (
        not before.present
        or not before.credential_present
        or before.origin != "managed"
        or before.version != credential_version
    ):
        raise RegistrySessionUnavailable
    workspace = read_workspace_snapshot(workspace_path)
    initial_authority = ManagedSessionAuthority(
        credential_version, workspace.version, broker_workspace_version(workspace)
    )
    metadata = credential_store.account_for_selector(selector)
    candidate = None
    receipt = None

    def retain_prepared(value: NativeSessionCandidate) -> None:
        nonlocal candidate, receipt
        candidate = value
        receipt = owner.prepare_session_candidate(
            selector,
            value.session,
            expected_registry=expected,
            authority=initial_authority,
            broker=metadata.broker,
            label=metadata.label,
        )

    try:
        candidate = await prepare_native_session(
            adapter, credentials, verify=verify, mutation_admission=mutation_admission, accept_candidate=retain_prepared
        )
        if candidate.probe_error is not None:
            from .exceptions import AuthFlowError

            raise AuthFlowError(candidate.probe_error)
        if credential_store.selector_state(selector).version != credential_version:
            raise RegistrySessionUnavailable
        final_version = credential_version
        if candidate.replay_credentials != credentials:
            final_version = credential_store.update_credentials(
                selector, candidate.replay_credentials, expected=credential_version
            )
        state = credential_store.selector_state(selector)
        if (
            not state.present
            or not state.credential_present
            or state.origin != "managed"
            or state.version != final_version
        ):
            raise RegistrySessionUnavailable
        workspace = read_workspace_snapshot(workspace_path)
        authority = ManagedSessionAuthority(final_version, workspace.version, broker_workspace_version(workspace))
        owner.rebind_prepared_credentials(receipt, expected_authority=initial_authority, current_authority=authority)
        current = read_workspace_snapshot(workspace_path)
        state = credential_store.selector_state(selector)
        if (
            not state.present
            or not state.credential_present
            or state.origin != "managed"
            or state.version != final_version
        ):
            raise RegistrySessionUnavailable
        publishing, receipt = receipt, None  # publication consumes or retires this capability
        result = owner.publish_prepared_candidate(
            publishing,
            current_authority=ManagedSessionAuthority(
                final_version, current.version, broker_workspace_version(current)
            ),
        )
        candidate.registry_version = result.version.registry_version
    except BaseException as exc:
        if receipt is not None:
            owner.abandon_prepared_candidate(receipt)
        elif (
            candidate is not None
            and not owner.owns_live_candidate(candidate.session)
            and owner.retirement_for_candidate(candidate.session) is None
        ):
            quarantine_native_candidate(candidate)
        from flinttrade_core.account_mutation_contracts import RegistryVersionConflict

        try:
            # A failed fresh probe is not evidence that an already verified
            # prior session died. Keep that exact generation on transient error;
            # genuine invalid-auth and changed-authority refusals remain intact.
            if not (expected.present and should_keep_session_after_probe_error(exc)):
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
    """Re-establish sessions only through an explicitly admitted legacy replay.

    Production startup and automatic refresh retain the default cutover refusal.
    The normal factory's CONNECT/RECONNECT path instead borrows the canonical
    account transaction and lifecycle owners. An explicitly composed caller must
    supply the existing publication owner and current durable witnesses. Each
    selector's failure is reported separately; an unknown result is not ready.

    Args:
        native_adapters: Live ``broker_id -> adapter`` map of ACTIVE natives
            (``app.config["NATIVE_ADAPTERS"]``).
        registry: The ``BrokerRegistry``.
        credential_store: The ``CredentialStore`` (``retrieve_for`` lookups).
        selectors: The registered ``<adapter_id>:<account_id>`` selectors.
        verify: Optional legacy probe policy for nonprovisional sessions. A new
            provisional session always requires strict successful verification;
            the flag cannot turn an unknown token into an authenticated session.

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
            if (
                not after.present
                or not after.credential_present
                or after.origin != "managed"
                or after.version != before.version
            ):
                raise RegistrySessionUnavailable
        except Exception as exc:  # noqa: BLE001 - a missing/undecryptable row must not brick boot
            logger.info(
                "No usable vault credentials for %s (%s) — leaving sessionless",
                adapter_id,
                type(exc).__name__,
            )
            results[selector] = CREDENTIALS_UNAVAILABLE_MESSAGE
            continue
        try:
            await establish_native_session(
                adapter,
                registry,
                credentials,
                adapter_id,
                account_id,
                credential_store=credential_store,
                verify=verify,
                mutation_admission=mutation_admission,
                registry_publication_owner=registry_publication_owner,
                workspace_path=workspace_path,
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
