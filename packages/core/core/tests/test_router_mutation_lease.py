"""Exact app-owned broker-router mutation lease tests."""

from __future__ import annotations

import threading
from uuid import UUID, uuid4

from flask import Flask
import pytest

from flinttrade_core.backend_instance import BackendLeaseUnavailable
from flinttrade_core.router_mutation_lease import (
    RouterMutationLeaseToken,
    RouterMutationLeaseUnavailable,
    require_router_mutation_token,
    router_mutation_lease,
)


pytestmark = pytest.mark.unit


def test_router_mutation_token_is_exact_and_expires_with_its_lease(
    backend_lease_factory,
) -> None:
    app = Flask("exact-router-mutation-token")
    proof = backend_lease_factory()
    operation_id = uuid4()

    with router_mutation_lease(
        app,
        operation_id,
        backend_lease_proof=proof,
        timeout=0.0,
    ) as token:
        assert type(token) is RouterMutationLeaseToken
        assert token.operation_id == operation_id
        assert token.backend_incarnation == proof.incarnation
        assert require_router_mutation_token(app, token, operation_id=operation_id) is token

        with pytest.raises(RouterMutationLeaseUnavailable):
            RouterMutationLeaseToken(object())
        with pytest.raises(RouterMutationLeaseUnavailable):
            require_router_mutation_token(Flask("foreign-app"), token)

    with pytest.raises(RouterMutationLeaseUnavailable):
        require_router_mutation_token(app, token, operation_id=operation_id)


def test_router_mutation_token_is_thread_bound_and_requires_a_live_backend(
    backend_lease_factory,
) -> None:
    app = Flask("thread-bound-router-mutation-token")
    proof = backend_lease_factory()
    result: list[type[BaseException] | None] = []

    with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0) as token:
        def inspect_from_foreign_thread() -> None:
            try:
                require_router_mutation_token(app, token)
            except BaseException as exc:  # noqa: BLE001 - record the exact refusal
                result.append(type(exc))
            else:
                result.append(None)

        thread = threading.Thread(target=inspect_from_foreign_thread)
        thread.start()
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert result == [RouterMutationLeaseUnavailable]

        proof.revoke()
        with pytest.raises(BackendLeaseUnavailable):
            require_router_mutation_token(app, token)


def test_same_thread_cannot_reenter_router_mutation_lease_without_current_token(
    backend_lease_factory,
) -> None:
    app = Flask("same-thread-router-mutation-reentry")
    proof = backend_lease_factory()

    with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0) as token:
        assert require_router_mutation_token(app, token) is token
        with pytest.raises(RouterMutationLeaseUnavailable):
            with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0):
                pytest.fail("a reentrant RLock must not forge nested lease ownership")


@pytest.mark.parametrize("operation_id", [UUID(int=0), UUID("00000000-0000-1000-8000-000000000001"), "not-a-uuid"])
def test_router_mutation_lease_requires_a_canonical_uuid4_operation(
    operation_id: object,
    backend_lease_factory,
) -> None:
    app = Flask("router-mutation-operation-id")

    with pytest.raises(RouterMutationLeaseUnavailable):
        with router_mutation_lease(
            app,
            operation_id,
            backend_lease_proof=backend_lease_factory(),
            timeout=0.0,
        ):
            pytest.fail("an invalid operation identity must not acquire the router lease")


def test_retirement_inside_a_mutation_requires_the_exact_active_token(
    backend_lease_factory,
) -> None:
    from flinttrade_core.app import retire_broker_dependencies

    app = Flask("nested-router-retirement")
    proof = backend_lease_factory()
    app.config.update(BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0)

    with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0) as token:
        assert retire_broker_dependencies(app, timeout=0.0) is False
        assert retire_broker_dependencies(app, timeout=0.0, router_mutation_token=token) is True


def test_standalone_retirement_can_clean_up_after_backend_proof_revocation(
    backend_lease_factory,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.app import retire_broker_dependencies

    app = Flask("revoked-backend-router-cleanup")
    proof = backend_lease_factory()

    class Router:
        def __init__(self) -> None:
            self.drained = False

        def revoke_and_drain(self, *, timeout: float) -> bool:
            assert timeout == 0.0
            self.drained = True
            return True

    router = Router()
    app.config.update(
        BACKEND_LEASE_PROOF=proof,
        BROKER_ROUTER=router,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0,
    )
    proof.revoke()

    assert retire_broker_dependencies(app, timeout=0.0) is True
    assert router.drained is True
    assert app.config["BROKER_ROUTER"] is None
    assert app.config["BROKER_ROUTER_DRAINING"] is None

    # Cleanup ownership cannot be promoted into rebuild authority.
    assert app_module.configure_broker_router(app, object(), object(), None) is False


def test_competing_thread_cannot_enter_retirement_while_mutation_lease_is_held(
    backend_lease_factory,
) -> None:
    from flinttrade_core.app import retire_broker_dependencies

    app = Flask("competing-router-retirement")
    proof = backend_lease_factory()
    app.config.update(BACKEND_LEASE_PROOF=proof, BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0)
    attempt_started = threading.Event()
    result: list[bool] = []

    def compete() -> None:
        attempt_started.set()
        result.append(retire_broker_dependencies(app, timeout=0.0))

    with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0):
        thread = threading.Thread(target=compete)
        thread.start()
        assert attempt_started.wait(1.0)
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        assert result == [False]

    assert retire_broker_dependencies(app, timeout=0.0) is True


def test_native_mutation_keeps_one_token_from_drain_through_every_publication_gap(
    backend_lease_factory,
) -> None:
    import flinttrade_core.native_account_routes as routes

    app = Flask("continuous-native-router-mutation")
    proof = backend_lease_factory()
    app.config.update(
        BACKEND_LEASE_PROOF=proof,
        BROKER_ACCOUNT_MUTATION_ADMISSION=lambda: None,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=1.0,
    )
    drain_entered = threading.Event()
    release_old_write = threading.Event()
    mutation_started = threading.Event()
    phases = [threading.Event() for _ in range(3)]
    attempts_finished = [threading.Event() for _ in range(3)]
    wrapper_finished = threading.Event()
    outcomes: list[type[BaseException] | None] = []
    worker_errors: list[BaseException] = []

    class OldRouter:
        def revoke_and_drain(self, *, timeout: float) -> bool:
            drain_entered.set()
            return release_old_write.wait(timeout)

    app.config["BROKER_ROUTER"] = OldRouter()

    def compete() -> None:
        for phase, finished in zip(phases, attempts_finished, strict=True):
            assert phase.wait(2.0)
            try:
                with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0):
                    outcomes.append(None)
            except BaseException as exc:  # noqa: BLE001 - record exact refusal
                outcomes.append(type(exc))
            finally:
                finished.set()
        assert wrapper_finished.wait(2.0)
        try:
            with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0):
                outcomes.append(None)
        except BaseException as exc:  # noqa: BLE001 - record exact refusal
            outcomes.append(type(exc))

    @routes._serialized
    def mutate(*, router_mutation_token: RouterMutationLeaseToken) -> None:
        assert require_router_mutation_token(app, router_mutation_token) is router_mutation_token
        assert routes._quiesce_current_router(router_mutation_token=router_mutation_token) is True
        mutation_started.set()
        for phase, finished in zip(phases, attempts_finished, strict=True):
            phase.set()
            assert finished.wait(2.0)

    competitor = threading.Thread(target=compete)
    competitor.start()
    # Use an explicit context runner because LocalProxy state is thread-local.
    def run_mutation() -> None:
        try:
            with app.app_context():
                mutate()
        except BaseException as exc:  # noqa: BLE001 - surface worker failure on the main thread
            worker_errors.append(exc)
            for phase in phases:
                phase.set()
        finally:
            wrapper_finished.set()

    worker = threading.Thread(target=run_mutation)
    worker.start()
    assert drain_entered.wait(2.0)
    assert mutation_started.is_set() is False
    release_old_write.set()
    worker.join(timeout=2.0)
    competitor.join(timeout=2.0)

    assert not worker.is_alive()
    assert not competitor.is_alive()
    assert worker_errors == []
    assert mutation_started.is_set() is True
    assert outcomes == [RouterMutationLeaseUnavailable] * 3 + [None]


def test_rate_limit_mutation_wrapper_passes_an_active_non_reentrant_token(
    backend_lease_factory,
) -> None:
    from flinttrade_gateway.auth import _rate_limit_generation_lease

    app = Flask("continuous-rate-limit-router-mutation")
    proof = backend_lease_factory()
    app.config.update(
        BACKEND_LEASE_PROOF=proof,
        BROKER_ACCOUNT_MUTATION_ADMISSION=lambda: None,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0,
    )

    @_rate_limit_generation_lease
    def mutate(*, router_mutation_token: RouterMutationLeaseToken) -> RouterMutationLeaseToken:
        assert require_router_mutation_token(app, router_mutation_token) is router_mutation_token
        with pytest.raises(RouterMutationLeaseUnavailable):
            with router_mutation_lease(app, uuid4(), backend_lease_proof=proof, timeout=0.0):
                pytest.fail("the rate-limit mutation must not reenter via the raw RLock")
        return router_mutation_token

    with app.test_request_context("/v1/rate-limits", method="PUT"):
        expired = mutate()

    with pytest.raises(RouterMutationLeaseUnavailable):
        require_router_mutation_token(app, expired)


def test_update_rate_limits_reuses_one_token_for_retirement_and_rebuild(
    backend_lease_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    import flinttrade_core.workspace as workspace_module
    from flinttrade_gateway.auth import update_rate_limits

    app = Flask("continuous-rate-limit-rebuild")
    proof = backend_lease_factory()
    registry = object()
    app.config.update(
        BACKEND_LEASE_PROOF=proof,
        BROKER_ACCOUNT_MUTATION_ADMISSION=lambda: None,
        BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS=0.0,
        CREDENTIAL_STORE=object(),
        REGISTRY=registry,
    )
    received: list[RouterMutationLeaseToken] = []

    class Workspace:
        def update(self, mutation) -> None:
            mutation({})

    def retire(application, *, router_mutation_token) -> bool:
        received.append(require_router_mutation_token(application, router_mutation_token))
        return True

    def rebuild(application, exact_registry, *_args, router_mutation_token) -> bool:
        assert exact_registry is registry
        received.append(require_router_mutation_token(application, router_mutation_token))
        return True

    monkeypatch.setattr(workspace_module, "Workspace", Workspace)
    monkeypatch.setattr(app_module, "retire_broker_dependencies", retire)
    monkeypatch.setattr(app_module, "configure_broker_router", rebuild)

    with app.test_request_context(
        "/v1/rate-limits",
        method="PUT",
        json={"broker_id": "upstox", "order": 2},
    ):
        response = update_rate_limits()

    assert response.get_json() == {"status": "success", "limits": {}}
    assert len(received) == 2
    assert received[0] is received[1]
    with pytest.raises(RouterMutationLeaseUnavailable):
        require_router_mutation_token(app, received[0])
