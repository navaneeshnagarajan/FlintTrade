"""Regression tests for Identity H8 CLA GPG binding.

The gate is for external contributor pull requests. Push-to-main after a
cursor[bot] squash-merge must not treat the merger as a CLA subject.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_cla_gpg_binding", REPO / "scripts" / "check-cla-gpg-binding.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _clear_author_env(monkeypatch) -> None:
    for key in ("PR_AUTHOR", "GITHUB_ACTOR", "GITHUB_EVENT_NAME", "GITHUB_BASE_REF"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.unit
def test_push_event_with_cursor_bot_actor_is_not_enforced(monkeypatch, capsys) -> None:
    """Reproduce the 2026-08-23 main Supply Chain failure and require skip."""
    checker = _load_checker()
    _clear_author_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "cursor[bot]")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert checker.main() == 0
    assert "CLA binding not enforced" in capsys.readouterr().out


@pytest.mark.unit
def test_schedule_event_does_not_use_github_actor(monkeypatch, capsys) -> None:
    checker = _load_checker()
    _clear_author_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "github-actions[bot]")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")

    assert checker.main() == 0
    assert "CLA binding not enforced" in capsys.readouterr().out


@pytest.mark.unit
def test_external_pr_author_without_cla_record_fails(monkeypatch, capsys) -> None:
    checker = _load_checker()
    _clear_author_env(monkeypatch)
    monkeypatch.setenv("PR_AUTHOR", "external-contributor")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    assert checker.main() == 1
    assert "unsigned_cla" in capsys.readouterr().err


@pytest.mark.unit
def test_owner_record_auto_attests_on_pull_request(monkeypatch, capsys) -> None:
    checker = _load_checker()
    _clear_author_env(monkeypatch)
    monkeypatch.setenv("PR_AUTHOR", "navaneeshnagarajan")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    assert checker.main() == 0
    assert "auto-attested" in capsys.readouterr().out


@pytest.mark.unit
def test_local_github_actor_fallback_still_resolves_owner(monkeypatch, capsys) -> None:
    checker = _load_checker()
    _clear_author_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTOR", "navaneeshnagarajan")

    assert checker.main() == 0
    assert "auto-attested" in capsys.readouterr().out


@pytest.mark.unit
def test_supply_chain_cla_job_requires_external_fork_pull_request() -> None:
    """Pin the workflow `if:` so push-to-main cannot re-arm Identity H8."""
    workflow = (REPO / ".github" / "workflows" / "supply-chain.yml").read_text(encoding="utf-8")
    assert "cla-gpg-binding:" in workflow
    assert (
        "if: ${{ github.event_name == 'pull_request' && !github.event.pull_request.draft && "
        "github.event.pull_request.head.repo.full_name != github.repository }}"
    ) in workflow
