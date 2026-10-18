"""Local/OSS provider acquisition; tokens never cross the service owner boundary.

The existing encrypted connection files and cross-process lock own every grant
and one-shot transition. Network calls release that lock; durable unknown claims
prevent replay after a crash. Local disconnect remains independent of revocation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, NoReturn, NotRequired, TypedDict
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
import jwt

from .service_connection_audit import ConnectionActorContext
from .service_connection_transactions import TransactionFiles, canonical, decode, uuid_text, version_dict
from .service_task_contracts import TaskRefused
from .workspace_migrations import read_workspace_snapshot

if TYPE_CHECKING:
    from .service_connection_store import ConnectionCollectionSnapshot, ServiceConnectionStore
    from .service_connections import ServiceConnection


class OAuthSettings(TypedDict, total=False):
    deployment: str
    redirect_uri: str
    desktop_bound: bool


class OAuthCapabilities(TypedDict):
    configured: bool
    providers: list[str]
    desktop_activation: NotRequired[bool]


class OAuthRegistration(TypedDict):
    client_id: str
    subject: str
    scopes: list[str]


class OAuthTokens(TypedDict):
    access_token: str
    expires_at: float | None
    refresh_token: NotRequired[str]
    id_token: NotRequired[str]
    client_id: NotRequired[str]
    subject: NotRequired[str]
    scopes: NotRequired[list[str]]


class OAuthTransaction(TypedDict):
    transaction_id: str
    connection_id: str
    etag: str
    provider: str
    actor: str
    session: str
    redirect: str
    expires: float
    status: str
    state_hash: str
    browser_hash: str
    nonce: str
    verifier: NotRequired[str]
    code: NotRequired[str]
    registration: OAuthRegistration | None
    client_id: NotRequired[str]
    activation_id: NotRequired[str | None]
    launch_hash: NotRequired[str]
    launch_url: NotRequired[str]


class OAuthGrant(TypedDict):
    grant_id: str
    connection_id: str
    provider: str
    actor: str
    session: str
    status: str
    tokens: OAuthTokens | None
    rotation: int
    binding: NotRequired[dict[str, Any]]
    remote_revocation: NotRequired[str]
    credential_retired: NotRequired[bool]


class OAuthState(TypedDict):
    schema: int
    root: dict[str, Any]
    host: str
    transactions: dict[str, OAuthTransaction]
    grants: dict[str, OAuthGrant]
    registrations: dict[str, OAuthRegistration]
    deployment: NotRequired[str]
    activation_id: NotRequired[str]


class OAuthAttempt(TypedDict):
    transaction_id: str
    authorization_url: str
    expires_at: float


class OAuthOutcome(TypedDict):
    status: str
    rotation: NotRequired[int]
    remote_revocation: NotRequired[str | None]


CALLBACK_PATH = "/v1/services/connections/oauth/callback"
LAUNCH_PATH = "/v1/services/connections/oauth/launch"
ISSUER = "https://auth.openai.com"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
REQUIRED = frozenset({"openid", "offline_access", "resource.invoke", "chatgpt.tokens.use.direct"})


def refused(code: str = "oauth_unavailable", status: int = 409) -> NoReturn:
    raise TaskRefused(code, status)


def _text(value, maximum=8192):
    if type(value) is not str or not value or len(value) > maximum or any(ord(c) < 32 for c in value):
        refused("oauth_contract_invalid", 502)
    return value


def _issuer_url(value):
    value = _text(value, 2048)
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or url.netloc != "auth.openai.com"
        or url.query
        or url.fragment
        or not url.path.startswith("/")
    ):
        refused("oauth_metadata_invalid", 502)
    return value


class ServiceOAuth:
    """Borrow the service connection owner. No threads, clients or lazy owners."""

    def __init__(
        self,
        store: ServiceConnectionStore,
        *,
        config: Callable[[], OAuthSettings] = dict,
        transport: Callable[[], httpx.BaseTransport | None] = lambda: None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.store, self.config, self.transport, self.clock = store, config, transport, clock

    def settings(self, state: OAuthState | None = None) -> str:
        value = self.config()
        if value.get("desktop_bound") is True:
            if state is None:
                with self.locked(initialise=True) as (_, _, stored):
                    return self.settings(stored)
            value = {**value, "deployment": state.get("deployment", "api_only")}
        uri = value.get("redirect_uri")
        if value.get("deployment") != "local_oss" or type(uri) is not str:
            refused("oauth_not_configured", 422)
        parsed = urlsplit(uri)
        if (
            parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username
            or parsed.password
            or parsed.path != CALLBACK_PATH
            or parsed.query
            or parsed.fragment
            or parsed.port is None
        ):
            refused("oauth_not_configured", 422)
        return uri

    def capabilities(self) -> OAuthCapabilities:
        activation = {"desktop_activation": True} if self.config().get("desktop_bound") is True else {}
        try:
            self.settings()
        except (TaskRefused, ValueError):
            return {"configured": False, "providers": [], **activation}
        return {"configured": True, "providers": ["llm:openai", "llm:openrouter"], **activation}

    def configure(self, deployment: str, etag: str, check: Callable[[], None]) -> None:
        if deployment not in {"api_only", "local_oss"}:
            refused("invalid_request", 400)
        if self.config().get("desktop_bound") is not True:
            refused("oauth_not_configured", 422)
        check()
        with self.locked(initialise=True) as (files, snapshot, state):
            if snapshot.etag != etag:
                refused("connection_revision_conflict", 412)
            check()
            if state.get("deployment", "api_only") != deployment:
                state["deployment"] = deployment
                state["activation_id"] = str(uuid4())
                for tx in state["transactions"].values():
                    if tx["status"] in {"pending", "callback"}:
                        tx["status"] = "cancelled"
                    for field in ("code", "verifier", "launch_url"):
                        tx.pop(field, None)
                self.save(files, state)

    @contextmanager
    def locked(
        self, *, initialise: bool = False
    ) -> Iterator[tuple[TransactionFiles, ConnectionCollectionSnapshot, OAuthState]]:
        with TransactionFiles(self.store.workspace_dir) as files:
            self.store._recover(files)
            snapshot = self.store._snapshot(files, read_workspace_snapshot(self.store.workspace_dir))
            if files.bootstrap is None:
                refused("oauth_not_configured", 422)
            if files.control.exists("oauth-state.json"):
                raw = files.read(files.control, "oauth-state.json", 4_000_000)
                if set(raw) != {"ciphertext"}:
                    refused()
                state = decode(files.cipher.decrypt(raw["ciphertext"].encode()).decode())
                if state.get("schema") != 1 or state.get("root") != files.root_evidence():
                    refused()
            elif initialise:
                state = {
                    "schema": 1,
                    "root": files.root_evidence(),
                    "host": "urn:uuid:" + str(uuid4()),
                    "transactions": {},
                    "grants": {},
                    "registrations": {},
                }
            else:
                refused("oauth_not_connected", 409)
            yield files, snapshot, state

    @staticmethod
    def save(files: TransactionFiles, state: OAuthState) -> None:
        files.revalidate()
        raw = canonical(state).encode()
        if len(raw) > 2_000_000:
            refused("oauth_capacity", 429)
        files.write(files.control, "oauth-state.json", {"ciphertext": files.cipher.encrypt(raw).decode()}, 4_000_000)

    @staticmethod
    def selected(snapshot: ConnectionCollectionSnapshot, identifier: str, etag: str) -> ServiceConnection:
        uuid_text(identifier)
        if snapshot.etag != etag:
            refused("connection_revision_conflict", 412)
        row = next((r for r in snapshot.connections if str(r.connection_id) == identifier), None)
        if row is None:
            refused("connection_not_found", 404)
        return row

    @staticmethod
    def identity(actor: ConnectionActorContext) -> dict[str, str]:
        if type(actor) is not ConnectionActorContext:
            refused("operator_session_required", 403)
        return {"actor": actor.actor, "session": actor.session_binding}

    def start(
        self,
        identifier: str,
        etag: str,
        actor: ConnectionActorContext,
        check: Callable[[], None],
        *,
        external_browser: bool = False,
    ) -> tuple[OAuthAttempt, str | None]:
        redirect = self.settings()
        check()
        with self.locked(initialise=True) as (files, snapshot, state):
            redirect = self.settings(state)
            row = self.selected(snapshot, identifier, etag)
            if (row.provider_id, row.auth_mode) not in {("llm:openai", "chatgpt_oauth"), ("llm:openrouter", "api_key")}:
                refused("oauth_provider_unsupported", 422)
            # One bounded active attempt per connection; retain tombstones for replay.
            if len(state["transactions"]) >= 512:
                refused("oauth_capacity", 429)
            for tx in state["transactions"].values():
                if tx["connection_id"] == identifier and tx["status"] in {"pending", "callback"}:
                    tx["status"] = "cancelled"
            tid = str(uuid4())
            verifier = secrets.token_urlsafe(48)
            nonce = secrets.token_urlsafe(32)
            marker = secrets.token_urlsafe(32)
            browser = secrets.token_urlsafe(32)
            registration = state["registrations"].get(identifier)
            tx = {
                "transaction_id": tid,
                "connection_id": identifier,
                "etag": etag,
                "provider": row.provider_id,
                **self.identity(actor),
                "redirect": redirect,
                "expires": self.clock() + 600,
                "status": "pending",
                "state_hash": hashlib.sha256(marker.encode()).hexdigest(),
                "browser_hash": hashlib.sha256(browser.encode()).hexdigest(),
                "nonce": nonce,
                "verifier": verifier,
                "registration": registration,
                "activation_id": state.get("activation_id"),
            }
            state["transactions"][tid] = tx
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
            params = {"state": marker, "code_challenge": challenge, "code_challenge_method": "S256"}
            if row.provider_id == "llm:openai":
                params.update(
                    client_id=registration["client_id"] if registration else "dynamic_agent_client",
                    ext_agent_host_id=state["host"],
                    response_type="code",
                    redirect_uri=redirect,
                    scope=SCOPES,
                    resource=RESOURCE,
                    nonce=nonce,
                )
                if not registration:
                    params["agent_name_hint"] = "FlintTrade"
                url = ISSUER + "/api/accounts/authorize"
            else:
                params.update(callback_url=redirect, key_label="FlintTrade")
                url = "https://openrouter.ai/auth"
            authorization_url = url + "?" + urlencode(params)
            if external_browser:
                ticket = secrets.token_urlsafe(32)
                tx["launch_hash"] = hashlib.sha256(ticket.encode()).hexdigest()
                tx["launch_url"] = authorization_url
                tx["browser_hash"] = ""
                browser = None
                authorization_url = redirect.removesuffix(CALLBACK_PATH) + LAUNCH_PATH + "?ticket=" + ticket
            self.save(files, state)
            return {
                "transaction_id": tid,
                "authorization_url": authorization_url,
                "expires_at": tx["expires"],
            }, browser

    def launch(self, ticket: str, actual_uri: str) -> tuple[str, str]:
        """Consume one scoped handoff and bind a new HttpOnly browser cookie."""
        ticket = _text(ticket, 256)
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        with self.locked() as (files, snapshot, state):
            tx = next(
                (t for t in state["transactions"].values() if hmac.compare_digest(t.get("launch_hash", ""), digest)),
                None,
            )
            if tx is None:
                refused("oauth_launch_invalid", 400)
            if tx["status"] != "pending" or "launch_url" not in tx:
                refused("oauth_replayed", 409)
            if tx["expires"] <= self.clock():
                refused("oauth_expired", 410)
            if (
                tx["redirect"] != self.settings(state)
                or tx.get("activation_id") != state.get("activation_id")
                or actual_uri != tx["redirect"].removesuffix(CALLBACK_PATH) + LAUNCH_PATH
            ):
                refused("oauth_authority_changed", 403)
            self.selected(snapshot, tx["connection_id"], tx["etag"])
            browser = secrets.token_urlsafe(32)
            tx["browser_hash"] = hashlib.sha256(browser.encode()).hexdigest()
            url = tx.pop("launch_url")
            self.save(files, state)
            return url, browser

    def callback(self, query: Mapping[str, str], browser: str | None, actual_uri: str) -> None:
        if set(query) - {"state", "code", "client_id", "scope", "error", "error_description"}:
            refused("oauth_callback_invalid", 400)
        marker = _text(query.get("state"), 256)
        with self.locked() as (files, snapshot, state):
            tx = next(
                (
                    t
                    for t in state["transactions"].values()
                    if hmac.compare_digest(t["state_hash"], hashlib.sha256(marker.encode()).hexdigest())
                ),
                None,
            )
            if (
                tx is None
                or not browser
                or not hmac.compare_digest(tx["browser_hash"], hashlib.sha256(browser.encode()).hexdigest())
            ):
                refused("oauth_callback_invalid", 400)
            if (
                actual_uri != tx["redirect"]
                or self.settings(state) != tx["redirect"]
                or tx.get("activation_id") != state.get("activation_id")
            ):
                refused("oauth_callback_invalid", 400)
            if tx["status"] != "pending":
                refused("oauth_replayed", 409)
            if tx["expires"] <= self.clock():
                tx["status"] = "expired"
                self.save(files, state)
                refused("oauth_expired", 410)
            self.selected(snapshot, tx["connection_id"], tx["etag"])
            if "error" in query:
                tx["status"] = "denied"
                self.save(files, state)
                return
            tx["code"] = _text(query.get("code"))
            if tx["provider"] == "llm:openai":
                registered = tx["registration"]
                cid = query.get("client_id", registered["client_id"] if registered else None)
                if not isinstance(cid, str) or not cid.startswith("oaiapp_") or len(cid) > 256:
                    refused("oauth_registration_incomplete", 400)
                if registered and cid != registered["client_id"]:
                    refused("oauth_identity_changed", 403)
                tx["client_id"] = cid
            tx["status"] = "callback"
            self.save(files, state)

    def transaction(
        self, state: OAuthState, tid: str, identifier: str, etag: str, actor: ConnectionActorContext
    ) -> OAuthTransaction:
        uuid_text(tid)
        tx = state["transactions"].get(tid)
        if tx is None:
            refused("oauth_transaction_not_found", 404)
        if (
            any(tx[k] != v for k, v in self.identity(actor).items())
            or tx["connection_id"] != identifier
            or tx["etag"] != etag
            or tx.get("activation_id") != state.get("activation_id")
        ):
            refused("oauth_authority_changed", 403)
        return tx

    def cancel(
        self, identifier: str, etag: str, tid: str, actor: ConnectionActorContext, check: Callable[[], None]
    ) -> OAuthOutcome:
        check()
        with self.locked() as (files, snapshot, state):
            self.selected(snapshot, identifier, etag)
            tx = self.transaction(state, tid, identifier, etag, actor)
            if tx["status"] == "connected":
                refused("oauth_replayed", 409)
            tx["status"] = "cancelled"
            tx.pop("code", None)
            tx.pop("verifier", None)
            tx.pop("launch_url", None)
            self.save(files, state)
        return {"status": "cancelled"}

    def _http(self, method, url, **kwargs):
        # No environment proxy, redirect, retry, error-body reflection or logging.
        try:
            with httpx.Client(
                transport=self.transport(), trust_env=False, follow_redirects=False, timeout=15
            ) as client:
                with client.stream(method, url, **kwargs) as response:
                    raw = bytearray()
                    for part in response.iter_bytes():
                        raw.extend(part)
                        if len(raw) > 131072:
                            refused("oauth_contract_invalid", 502)
                    if response.status_code != 200:
                        refused("oauth_provider_refused", 502)
                    return json.loads(raw) if raw else {}
        except TaskRefused:
            raise
        except Exception:
            refused("oauth_outcome_unknown", 502)

    def metadata(self) -> dict[str, Any]:
        doc = self._http("GET", ISSUER + "/.well-known/openid-configuration")
        if doc.get("issuer") != ISSUER:
            refused("oauth_metadata_invalid", 502)
        return doc

    def tokens(
        self,
        data: Mapping[str, object],
        cid: str,
        nonce: str | None,
        previous: OAuthRegistration | OAuthTokens | None = None,
    ) -> OAuthTokens:
        if type(data) is not dict or data.get("token_type") != "Bearer":
            refused("oauth_contract_invalid", 502)
        access = _text(data.get("access_token"))
        refresh = _text(data.get("refresh_token"))
        identity = _text(data.get("id_token"))
        expires = data.get("expires_in")
        if type(expires) is not int or not 0 < expires <= 86400:
            refused("oauth_contract_invalid", 502)
        scopes = set(_text(data.get("scope"), 2048).split())
        if not REQUIRED <= scopes:
            refused("oauth_scope_denied", 403)
        if previous and not scopes <= set(previous["scopes"]):
            refused("oauth_scope_expanded", 403)
        doc = self.metadata()
        keys = self._http("GET", _issuer_url(doc.get("jwks_uri")))
        try:
            header = jwt.get_unverified_header(identity)
            matches = [k for k in keys["keys"] if k.get("kid") == header.get("kid") and k.get("kty") == "RSA"]
            if header.get("alg") != "RS256" or len(matches) != 1:
                refused("oauth_identity_invalid", 403)
            key = jwt.PyJWK.from_dict(matches[0], algorithm="RS256").key
            claims = jwt.decode(
                identity,
                key,
                algorithms=["RS256"],
                audience=cid,
                issuer=ISSUER,
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "require": ["sub", "exp", "iat", "aud", "iss"],
                },
            )
            if (
                type(claims["exp"]) is not int
                or claims["exp"] <= self.clock()
                or type(claims["iat"]) is not int
                or claims["iat"] > self.clock() + 60
            ):
                refused("oauth_identity_invalid", 403)
            if claims.get("nbf", 0) > self.clock() + 60:
                refused("oauth_identity_invalid", 403)
            if nonce is not None and claims.get("nonce") != nonce:
                refused("oauth_identity_invalid", 403)
            subject = _text(claims["sub"], 512)
            if previous and subject != previous["subject"]:
                refused("oauth_identity_changed", 403)
        except TaskRefused:
            raise
        except Exception:
            refused("oauth_identity_invalid", 403)
        return {
            "access_token": access,
            "refresh_token": refresh,
            "id_token": identity,
            "client_id": cid,
            "subject": subject,
            "scopes": sorted(scopes),
            "expires_at": self.clock() + expires,
        }

    def complete(
        self, identifier: str, etag: str, tid: str, actor: ConnectionActorContext, check: Callable[[], None]
    ) -> OAuthOutcome:
        check()
        with self.locked() as (files, snapshot, state):
            row = self.selected(snapshot, identifier, etag)
            tx = self.transaction(state, tid, identifier, etag, actor)
            if tx["status"] in {"denied", "expired", "cancelled"}:
                return {"status": tx["status"]}
            if tx["status"] != "callback":
                refused("oauth_replayed" if tx["status"] != "pending" else "oauth_callback_pending", 409)
            if tx["expires"] <= self.clock():
                refused("oauth_expired", 410)
            if tx["redirect"] != self.settings(state):
                refused("oauth_authority_changed", 403)
            tx["status"] = "exchange_unknown"
            self.save(files, state)
            pending = dict(tx)
        if pending["provider"] == "llm:openai":
            data = self._http(
                "POST",
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": pending["client_id"],
                    "code": pending["code"],
                    "code_verifier": pending["verifier"],
                    "redirect_uri": pending["redirect"],
                    "resource": RESOURCE,
                },
            )
            tokens = self.tokens(data, pending["client_id"], pending["nonce"], pending["registration"])
        else:
            data = self._http(
                "POST",
                "https://openrouter.ai/api/v1/auth/keys",
                json={"code": pending["code"], "code_verifier": pending["verifier"], "code_challenge_method": "S256"},
            )
            tokens = {"access_token": _text(data.get("key")), "expires_at": None}
        check()
        with self.locked() as (files, snapshot, state):
            check()
            row = self.selected(snapshot, identifier, etag)
            tx = self.transaction(state, tid, identifier, etag, actor)
            if (
                tx["status"] != "exchange_unknown"
                or tx["expires"] <= self.clock()
                or pending["redirect"] != self.settings(state)
            ):
                refused("oauth_authority_changed", 403)
            grant = {
                "grant_id": tid,
                "connection_id": identifier,
                "provider": row.provider_id,
                **self.identity(actor),
                "status": "ready",
                "tokens": tokens,
                "rotation": 0,
            }
            # Publish encrypted grant before installing its opaque binding. A crash
            # cannot expose a credential without the store's durable secret version.
            state["grants"][tid] = grant
            if pending["provider"] == "llm:openai":
                state["registrations"][identifier] = {
                    "client_id": tokens["client_id"],
                    "subject": tokens["subject"],
                    "scopes": tokens["scopes"],
                }
            self.save(files, state)
            result = self.store._mutate(
                "update",
                {"credential": canonical({"service_oauth": tid})},
                connection_id=identifier,
                expected_etag=etag,
                idempotency_key=tid,
                actor_context=actor,
                _files=files,
            )
            if result.status != 200:
                refused("oauth_commit_unknown", 503)
            # The store's committed retirement hook may have stripped older
            # payloads. Never overwrite it with the pre-mutation in-memory copy.
            state = load_oauth_state(files)
            grant = state["grants"][tid]
            tx = state["transactions"][tid]
            committed = self.store._snapshot(files, read_workspace_snapshot(self.store.workspace_dir))
            grant["binding"] = version_dict(self.selected(committed, identifier, result.etag).secret_version)
            tx["status"] = "connected"
            tx.pop("code", None)
            tx.pop("verifier", None)
            self.save(files, state)
        return {"status": "connected"}

    def grant(
        self, files: TransactionFiles, state: OAuthState, row: ServiceConnection, actor: ConnectionActorContext | None
    ) -> OAuthGrant:
        if not row.credential_configured or row.secret_version is None:
            refused("oauth_not_connected", 409)
        secret = files.cipher.decrypt(files.live(row.secret_version)["ciphertext"].encode()).decode()
        try:
            handle = json.loads(secret)
        except Exception:
            refused("oauth_not_connected", 409)
        if type(handle) is not dict or set(handle) != {"service_oauth"}:
            refused("oauth_not_connected", 409)
        grant = state["grants"].get(handle["service_oauth"])
        if not grant or grant["connection_id"] != str(row.connection_id) or grant["provider"] != row.provider_id:
            refused("oauth_binding_invalid", 403)
        if grant.get("binding") != version_dict(row.secret_version):
            refused("oauth_binding_invalid", 403)
        if actor is not None and any(grant[k] != v for k, v in self.identity(actor).items()):
            refused("oauth_authority_changed", 403)
        return grant

    def access(
        self, files: TransactionFiles, row: ServiceConnection, secret: str | None, actor: ConnectionActorContext
    ) -> str | None:
        if row.auth_mode != "chatgpt_oauth" and not (secret and secret.startswith('{"service_oauth":')):
            return secret
        # Called only inside canonical dispatch's existing credential fence.
        if not files.control.exists("oauth-state.json"):
            refused("oauth_not_connected", 401)
        state = decode(
            files.cipher.decrypt(
                files.read(files.control, "oauth-state.json", 4_000_000)["ciphertext"].encode()
            ).decode()
        )
        if state.get("schema") != 1 or state.get("root") != files.root_evidence():
            refused("oauth_binding_invalid", 403)
        grant = self.grant(files, state, row, actor)
        if grant["status"] != "ready":
            refused("oauth_reauthorization_required", 401)
        if grant["tokens"]["expires_at"] is not None and grant["tokens"]["expires_at"] <= self.clock():
            refused("oauth_refresh_required", 401)
        return grant["tokens"]["access_token"]

    def prepare(self, identifier: str, etag: str, actor: ConnectionActorContext, check: Callable[[], None]) -> None:
        """Called by canonical dispatch after eligibility and before invocation."""
        self.settings()
        check()
        with self.locked() as (files, snapshot, state):
            row = self.selected(snapshot, identifier, etag)
            grant = self.grant(files, state, row, actor)
            if grant["status"] != "ready":
                refused("oauth_reauthorization_required", 401)
            expiry = grant["tokens"]["expires_at"]
            due = expiry is not None and expiry <= self.clock() + 60
        if due:
            self.refresh(identifier, etag, actor, check)

    def refresh(
        self, identifier: str, etag: str, actor: ConnectionActorContext, check: Callable[[], None]
    ) -> OAuthOutcome:
        redirect = self.settings()
        check()
        with self.locked() as (files, snapshot, state):
            row = self.selected(snapshot, identifier, etag)
            grant = self.grant(files, state, row, actor)
            if row.provider_id != "llm:openai":
                refused("oauth_refresh_unsupported", 422)
            if grant["status"] != "ready":
                refused("oauth_reauthorization_required", 401)
            # No explicit force refresh: concurrent readers consume the same fresh
            # rotation instead of sending a second refresh token.
            if grant["tokens"]["expires_at"] > self.clock() + 60:
                return {"status": "current", "rotation": grant["rotation"]}
            check()
            grant["status"] = "refresh_unknown"
            self.save(files, state)
            old = dict(grant["tokens"])
            gid = grant["grant_id"]
            rotation = grant["rotation"]
            binding = version_dict(row.secret_version)
            activation = state.get("activation_id")
        data = self._http(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": old["client_id"],
                "refresh_token": old["refresh_token"],
                "resource": RESOURCE,
            },
        )
        tokens = self.tokens(data, old["client_id"], None, old)
        check()
        with self.locked() as (files, snapshot, state):
            check()
            row = self.selected(snapshot, identifier, etag)
            grant = self.grant(files, state, row, actor)
            if (
                grant["grant_id"] != gid
                or grant["rotation"] != rotation
                or grant["status"] != "refresh_unknown"
                or binding != version_dict(row.secret_version)
                or activation != state.get("activation_id")
                or redirect != self.settings(state)
            ):
                refused("oauth_authority_changed", 403)
            grant.update(tokens=tokens, status="ready", rotation=rotation + 1)
            self.save(files, state)
        return {"status": "refreshed", "rotation": rotation + 1}

    def disconnect(
        self, identifier: str, etag: str, actor: ConnectionActorContext, check: Callable[[], None]
    ) -> OAuthOutcome:
        check()
        with self.locked() as (files, snapshot, state):
            row = self.selected(snapshot, identifier, etag)
            grant = self.grant(files, state, row, actor)
            tokens = grant["tokens"]
            provider = grant["provider"]
            grant["status"] = "disconnected"
            grant["tokens"] = None
            grant["remote_revocation"] = "unconfirmed"
            gid = grant["grant_id"]
            for tx in state["transactions"].values():
                if tx["connection_id"] == identifier and tx["status"] != "connected":
                    tx["status"] = "cancelled"
                    tx.pop("code", None)
                    tx.pop("verifier", None)
            self.save(files, state)
            result = self.store._mutate(
                "update",
                {"clear_credential": True},
                connection_id=identifier,
                expected_etag=etag,
                idempotency_key=str(uuid4()),
                actor_context=actor,
                _files=files,
            )
            if result.status != 200:
                refused("oauth_commit_unknown", 503)
        remote = "unsupported"
        if provider == "llm:openai":
            try:
                doc = self.metadata()
                self._http(
                    "POST",
                    _issuer_url(doc.get("revocation_endpoint")),
                    data={
                        "token": tokens["refresh_token"],
                        "token_type_hint": "refresh_token",
                        "client_id": tokens["client_id"],
                    },
                )
                remote = "confirmed"
            except Exception:
                remote = "unconfirmed"
        with self.locked() as (files, snapshot, state):
            retained = state["grants"].get(gid)
            if retained is None or retained["status"] != "disconnected":
                refused("oauth_commit_unknown", 503)
            retained["remote_revocation"] = remote
            self.save(files, state)
        # No automatic retry; a local disconnect cannot assert remote cancellation.
        return {"status": "disconnected", "remote_revocation": remote}

    def status(self, identifier: str, actor: ConnectionActorContext) -> tuple[OAuthOutcome, str]:
        with self.locked() as (files, snapshot, state):
            row = self.selected(snapshot, identifier, snapshot.etag)
            if row.credential_configured:
                grant = self.grant(files, state, row, actor)
                result = {"status": grant["status"], "rotation": grant["rotation"], "remote_revocation": None}
            else:
                grants = [
                    g
                    for g in state["grants"].values()
                    if g["connection_id"] == identifier
                    and g["status"] == "disconnected"
                    and all(g[k] == v for k, v in self.identity(actor).items())
                ]
                result = {"status": "not_connected", "rotation": 0, "remote_revocation": None}
                if grants:
                    grant = grants[-1]
                    result = {
                        "status": "disconnected",
                        "rotation": grant["rotation"],
                        "remote_revocation": grant.get("remote_revocation", "unconfirmed"),
                    }
            return result, snapshot.etag


def load_oauth_state(files: TransactionFiles) -> OAuthState:
    raw = files.read(files.control, "oauth-state.json", 4_000_000)
    if set(raw) != {"ciphertext"}:
        refused()
    state = decode(files.cipher.decrypt(raw["ciphertext"].encode()).decode())
    if state.get("schema") != 1 or state.get("root") != files.root_evidence():
        refused()
    return state


def retire_obsolete_oauth_payloads(
    files: TransactionFiles, snapshot: ConnectionCollectionSnapshot, *, publishing_grant: str | None = None
) -> None:
    """Finish credential retirement under the store's existing durable lock.

    The journal stays pending if this fails, so recovery retries cleanup before
    claiming success. Keep identity, replay and uncertain outcome records intact.
    An in-progress newly published grant is retained by its actual live handle,
    including the interval before complete() records the final version binding.
    """
    if not files.control.exists("oauth-state.json"):
        return
    state = load_oauth_state(files)
    active = set()
    for row in snapshot.connections:
        if not row.credential_configured or row.secret_version is None:
            continue
        secret = files.cipher.decrypt(files.live(row.secret_version)["ciphertext"].encode()).decode()
        try:
            handle = json.loads(secret)
        except ValueError:
            continue
        if type(handle) is dict and set(handle) == {"service_oauth"} and type(handle["service_oauth"]) is str:
            grant = state["grants"].get(handle["service_oauth"])
            if (
                grant
                and grant["connection_id"] == str(row.connection_id)
                and grant["provider"] == row.provider_id
                and (
                    grant.get("binding") == version_dict(row.secret_version)
                    or ("binding" not in grant and grant["grant_id"] == publishing_grant)
                )
            ):
                active.add(handle["service_oauth"])
    changed = False
    for gid, grant in state["grants"].items():
        if gid not in active and grant.get("tokens") is not None:
            grant["tokens"] = None
            grant["credential_retired"] = True
            changed = True
    for tx in state["transactions"].values():
        if tx["etag"] != snapshot.etag:
            for field in ("code", "verifier", "launch_url"):
                if field in tx:
                    tx.pop(field)
                    changed = True
            if tx["status"] in {"pending", "callback"}:
                tx["status"] = "cancelled"
                changed = True
    if changed:
        ServiceOAuth.save(files, state)
