"""Isolated import-phase inertness probe for service-connection wiring tests."""

from __future__ import annotations

import asyncio
import importlib
import importlib.abc
import importlib.machinery
import json
import os
import socket
import subprocess
import sys
from contextlib import ExitStack
from types import ModuleType
from typing import Any
from unittest.mock import patch


class _ForbiddenCallable:
    def __init__(self, label: str, attempts: list[str]) -> None:
        self._label = label
        self._attempts = attempts

    def __call__(self, *_args: object, **_kwargs: object) -> None:
        self._attempts.append(self._label)
        raise AssertionError(f"forbidden import-phase attempt: {self._label}")


_NAMED_GUARDS = {
    "flinttrade_ai.llm_client": (
        ("LLMClient", "flinttrade_ai.llm_client.LLMClient"),
        ("LLMConfig.from_env", "flinttrade_ai.llm_client.LLMConfig.from_env"),
    ),
    "flinttrade_core.ollama_runtime": (
        ("OllamaRuntime.start", "flinttrade_core.ollama_runtime.OllamaRuntime.start"),
        ("OllamaRuntime.start_async", "flinttrade_core.ollama_runtime.OllamaRuntime.start_async"),
    ),
    "flinttrade_ai.agent_backends.codex_session": (
        (
            "CodexAppServerSession.ensure_started",
            "flinttrade_ai.agent_backends.codex_session.CodexAppServerSession.ensure_started",
        ),
    ),
    "flinttrade_ai.agent_backends.hermes_session": (
        (
            "HermesACPSession.ensure_started",
            "flinttrade_ai.agent_backends.hermes_session.HermesACPSession.ensure_started",
        ),
    ),
    "flinttrade_gateway.adapter": (
        ("load_broker_adapter", "flinttrade_gateway.adapter.load_broker_adapter"),
    ),
    "flinttrade_gateway.session": (
        ("load_broker_adapter", "flinttrade_gateway.session.load_broker_adapter"),
    ),
    "flinttrade_gateway.registry": (("BrokerRegistry", "flinttrade_gateway.registry.BrokerRegistry"),),
    "flinttrade_gateway.credentials": (
        ("CredentialStore", "flinttrade_gateway.credentials.CredentialStore"),
    ),
    "flinttrade_gateway.contracts": (("ContractManager", "flinttrade_gateway.contracts.ContractManager"),),
}


def _replace_named_callable(module: ModuleType, path: str, replacement: object) -> None:
    owner: Any = module
    parts = path.split(".")
    for part in parts[:-1]:
        owner = getattr(owner, part)
    setattr(owner, parts[-1], replacement)


def _resolve_named_callable(module: ModuleType, path: str) -> object:
    value: Any = module
    for part in path.split("."):
        value = getattr(value, part)
    return value


class _GuardingLoader(importlib.abc.Loader):
    def __init__(self, loader: importlib.abc.Loader, fullname: str, attempts: list[str]) -> None:
        self._loader = loader
        self._fullname = fullname
        self._attempts = attempts

    def create_module(self, spec):  # noqa: ANN001, ANN201
        creator = getattr(self._loader, "create_module", None)
        return creator(spec) if creator is not None else None

    def exec_module(self, module: ModuleType) -> None:
        self._loader.exec_module(module)
        for path, label in _NAMED_GUARDS[self._fullname]:
            _replace_named_callable(module, path, _ForbiddenCallable(label, self._attempts))


class _GuardingFinder(importlib.abc.MetaPathFinder):
    def __init__(self, attempts: list[str]) -> None:
        self._attempts = attempts

    def find_spec(self, fullname: str, path, target=None):  # noqa: ANN001, ANN201
        if fullname not in _NAMED_GUARDS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path, target)
        if spec is None or spec.loader is None:
            return spec
        spec.loader = _GuardingLoader(spec.loader, fullname, self._attempts)
        return spec


def _run() -> None:
    expected_credentials = frozenset(json.loads(os.environ.pop("FLINTTRADE_TEST_PROVIDER_CREDENTIAL_NAMES")))
    mode = sys.argv[1]
    attempts: list[str] = []
    environment_get = os.environ.get
    environment_getitem = type(os.environ).__getitem__

    def forbidden(label: str) -> _ForbiddenCallable:
        return _ForbiddenCallable(label, attempts)

    def guarded_environment_get(name, default=None):  # noqa: ANN001, ANN202
        if name in expected_credentials:
            return forbidden(f"os.environ.get:{name}")()
        return environment_get(name, default)

    def guarded_environment_getitem(environ, name):  # noqa: ANN001, ANN202
        if name in expected_credentials:
            return forbidden(f"os.environ.__getitem__:{name}")()
        return environment_getitem(environ, name)

    with ExitStack() as guards:
        guards.enter_context(patch.object(os.environ, "get", side_effect=guarded_environment_get))
        guards.enter_context(patch.object(type(os.environ), "__getitem__", guarded_environment_getitem))
        guards.enter_context(patch.object(socket.socket, "connect", side_effect=forbidden("socket.socket.connect")))
        guards.enter_context(patch.object(subprocess, "Popen", side_effect=forbidden("subprocess.Popen")))
        guards.enter_context(patch.object(subprocess, "run", side_effect=forbidden("subprocess.run")))
        guards.enter_context(
            patch.object(
                asyncio,
                "create_subprocess_exec",
                side_effect=forbidden("asyncio.create_subprocess_exec"),
            )
        )

        import httpx

        guards.enter_context(patch.object(httpx, "get", side_effect=forbidden("httpx.get")))
        guards.enter_context(patch.object(httpx, "post", side_effect=forbidden("httpx.post")))
        guards.enter_context(patch.object(httpx.Client, "get", side_effect=forbidden("httpx.Client.get")))
        guards.enter_context(patch.object(httpx.Client, "post", side_effect=forbidden("httpx.Client.post")))

        finder = _GuardingFinder(attempts)
        sys.meta_path.insert(0, finder)
        try:
            from flinttrade_core.llm_provider_profiles import LLM_PROVIDER_PROFILES

            actual_credentials = frozenset(
                profile.api_key_env for profile in LLM_PROVIDER_PROFILES if profile.api_key_env
            )
            assert actual_credentials == expected_credentials

            guarded_labels: list[str] = []
            for module_name, named_guards in _NAMED_GUARDS.items():
                guarded_module = importlib.import_module(module_name)
                for path, label in named_guards:
                    assert isinstance(_resolve_named_callable(guarded_module, path), _ForbiddenCallable)
                    guarded_labels.append(label)

            if mode == "caught-transport":
                try:
                    httpx.get("https://example.invalid")
                except Exception:
                    pass
            elif mode == "caught-environment-index":
                try:
                    os.environ["HERMES_API_KEY"]
                except Exception:
                    pass
            elif mode == "caught-named":
                from flinttrade_ai.llm_client import LLMClient

                try:
                    LLMClient()
                except Exception:
                    pass
            elif mode != "clean":
                raise AssertionError(f"unknown probe mode: {mode}")

            import flinttrade_core.service_connection_routes  # noqa: F401
            import flinttrade_core.app  # noqa: F401
        finally:
            sys.meta_path.remove(finder)

    print(json.dumps({"attempts": attempts, "named_guards": guarded_labels}, sort_keys=True), flush=True)
    assert attempts == []


if __name__ == "__main__":
    _run()
