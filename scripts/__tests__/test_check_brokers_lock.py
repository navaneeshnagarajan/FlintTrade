from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap


REPO = pathlib.Path(__file__).resolve().parents[2]
SHA = "a" * 64


def _load_checker():
    spec = importlib.util.spec_from_file_location(
        "check_brokers_lock", REPO / "scripts" / "check-brokers-lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_inputs(tmp_path: pathlib.Path, *, notes: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    brokers_lock = tmp_path / "brokers.lock"
    requirements_lock = tmp_path / "requirements.lock"
    uv_lock = tmp_path / "uv.lock"
    brokers_lock.write_text(
        textwrap.dedent(
            f"""
            [[broker]]
            name = "dhanhq"
            version = "2.2.0"
            sha256 = "{SHA}"
            licence = "MIT"
            licence_source = "dhanhq-2.2.0.dist-info/LICENSE"
            sandbox_tested = "2026-05-23"
            approved_by = "navaneeshnagarajan"
            notes = "{notes}"
            """
        ).strip(),
        encoding="utf-8",
    )
    requirements_lock.write_text(
        textwrap.dedent(
            f"""
            dhanhq==2.2.0 \\
                --hash=sha256:{SHA}
            """
        ).strip(),
        encoding="utf-8",
    )
    uv_lock.write_text("version = 1\n", encoding="utf-8")
    return brokers_lock, requirements_lock, uv_lock


def test_brokers_lock_accepts_current_activated_sdk_entry(tmp_path, monkeypatch, capsys) -> None:
    checker = _load_checker()
    brokers_lock, requirements_lock, uv_lock = _write_inputs(
        tmp_path,
        notes="repo-managed through flinttrade-gateway dependency and requirements.lock",
    )
    monkeypatch.setattr(checker, "BROKERS_LOCK", brokers_lock)
    monkeypatch.setattr(checker, "REQUIREMENTS_LOCK", requirements_lock)
    monkeypatch.setattr(checker, "UV_LOCK", uv_lock)

    assert checker.main() == 0
    assert capsys.readouterr().err == ""


def test_brokers_lock_rejects_stale_placeholder_note(tmp_path, monkeypatch, capsys) -> None:
    checker = _load_checker()
    brokers_lock, requirements_lock, uv_lock = _write_inputs(
        tmp_path,
        notes="hash pending from initial SDK import",
    )
    monkeypatch.setattr(checker, "BROKERS_LOCK", brokers_lock)
    monkeypatch.setattr(checker, "REQUIREMENTS_LOCK", requirements_lock)
    monkeypatch.setattr(checker, "UV_LOCK", uv_lock)

    assert checker.main() == 1
    assert "stale placeholder text in notes" in capsys.readouterr().err
