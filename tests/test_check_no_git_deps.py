"""Regression tests for dependency provenance gate edge cases."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

import pytest


REPO = pathlib.Path(__file__).resolve().parents[1]
COMMIT = "8cee5bda63bd9334f8501bb23b7f1d2945f93397"
REPO_URL = "https://github.com/Kotak-Neo/Kotak-neo-api-v2"


def _load_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_no_git_deps", REPO / "scripts" / "check-no-git-deps.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_uv_policy_fixture(tmp_path: pathlib.Path, git_url: str) -> None:
    (tmp_path / "brokers.lock").write_text(
        f"""
[[broker]]
name = "neo-api-client"
version = "2.0.0"
source_commit = "{COMMIT}"
homepage = "{REPO_URL}"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        f"""
[[package]]
name = "neo-api-client"
version = "2.0.0"
source = {{ git = "{git_url}" }}
""".lstrip(),
        encoding="utf-8",
    )


def test_uv_git_exception_accepts_https_github_repo_and_commit(tmp_path, monkeypatch) -> None:
    check = _load_check_module()
    monkeypatch.setattr(check, "REPO", tmp_path)
    _write_uv_policy_fixture(tmp_path, f"{REPO_URL}.git?rev={COMMIT}#{COMMIT}")

    assert check.check_uv_lock() == []


@pytest.mark.parametrize(
    ("git_url", "reason"),
    [
        (f"ssh://git@github.com/Kotak-Neo/Kotak-neo-api-v2.git?rev={COMMIT}#{COMMIT}", "scheme 'ssh'"),
        (f"https://github.com.evil.example/Kotak-Neo/Kotak-neo-api-v2.git?rev={COMMIT}#{COMMIT}", "host 'github.com.evil.example'"),
    ],
)
def test_uv_git_exception_rejects_unapproved_scheme_or_host(tmp_path, monkeypatch, git_url: str, reason: str) -> None:
    check = _load_check_module()
    monkeypatch.setattr(check, "REPO", tmp_path)
    _write_uv_policy_fixture(tmp_path, git_url)

    failures = check.check_uv_lock()
    assert failures
    assert "unapproved git source for neo-api-client" in failures[0]
    assert reason in failures[0]
