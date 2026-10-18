"""Concurrent first sessions must share one signing authority."""
from __future__ import annotations

import importlib.util
import sys
import threading
from types import SimpleNamespace

from flask import Flask
import pytest

from flinttrade_core import auth_routes, auth_state


@pytest.fixture
def cold_auth_routes(monkeypatch, tmp_path):
    """Load the real module cold without resetting an incumbent authority."""
    name = "flinttrade_core._cold_jwt_concurrency_test"
    spec = importlib.util.spec_from_file_location(name, auth_routes.__file__)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    initially_cold = not module._JWT_SECRET_KEY
    assert initially_cold
    return module


@pytest.mark.unit
def test_concurrent_first_sessions_retain_one_signing_key(cold_auth_routes, monkeypatch, tmp_path):
    auth = cold_auth_routes
    owner = auth_state.get_auth_state()
    first_generated = threading.Event()
    second_attempted = threading.Event()
    release_first = threading.Event()
    real_lock = threading.Lock()
    results_lock = threading.Lock()
    real_generate = auth.secrets.token_urlsafe
    generated = []
    tokens = []
    errors = []

    class ObservedLock:
        """Observe contention while retaining the real lock's exclusion."""

        def __enter__(self):
            if threading.current_thread().name == "second-jwt":
                second_attempted.set()
            real_lock.acquire()
            return self

        def __exit__(self, *_exc):
            real_lock.release()

    def generate(size):
        key = real_generate(size)
        with results_lock:
            generated.append(key)
        if threading.current_thread().name == "first-jwt":
            first_generated.set()
            assert release_first.wait(5)
        else:
            # On the old code the second caller reaches generation rather
            # than the lock. Signal only after its distinct key is drawn.
            second_attempted.set()
        return key

    # The old implementation ignores this boundary. The repaired version
    # takes the real lock; neither path needs sleeps or favourable scheduling.
    monkeypatch.setattr(auth, "_JWT_SECRET_LOCK", ObservedLock(), raising=False)
    monkeypatch.setattr(auth, "secrets", SimpleNamespace(
        token_urlsafe=generate, token_hex=auth.secrets.token_hex,
    ))

    def mint():
        try:
            token = auth._create_token("operator", mode="practice")
            with results_lock:
                tokens.append(token)
        except BaseException as error:
            with results_lock:
                errors.append(error)

    first = threading.Thread(target=mint, name="first-jwt")
    second = threading.Thread(target=mint, name="second-jwt")
    started = []
    try:
        first.start()
        started.append(first)
        assert first_generated.wait(5)
        second.start()
        started.append(second)
        assert second_attempted.wait(5)
    finally:
        release_first.set()
        for thread in started:
            thread.join(5)
    assert all(not thread.is_alive() for thread in started)
    assert errors == []
    token_count = len(tokens)
    assert token_count == 2
    with Flask(__name__).app_context():
        subjects = [auth.decode_token(token)["sub"] for token in tokens]
        assert subjects == ["operator", "operator"]
    generated_count = len(generated)
    assert generated_count == 1
    consistent_key = (tmp_path / "jwt_secret").read_text() == generated[0] == auth._get_jwt_secret()
    assert consistent_key
    assert auth_state.get_auth_state() is owner
    assert not owner._closed
