from __future__ import annotations

import importlib.util
import pathlib
import sys
import textwrap
import tomllib
from importlib import metadata

import pytest

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


@pytest.mark.parametrize(
    "missing_field",
    [
        "source_commit", "source_tree", "release_tag", "release_commit", "release_tree",
        "release_wheel_sha256", "release_sdist_sha256", "licence_sha256",
    ],
)
def test_kotak_git_pin_requires_both_runtime_and_release_evidence(
    tmp_path, monkeypatch, capsys, missing_field: str,
) -> None:
    checker = _load_checker()
    fields = {
        "source_commit": "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c",
        "source_tree": "bb8f8ab64b39ef7a650f1547f5def044cceadd61",
        "release_tag": "v3.0.7",
        "release_commit": "53cccc45fe56a193b30ffce3c03c71c5c0378538",
        "release_tree": "c45da6af1223cdeb211ea680ff3582edcbbbc6c9",
        "release_wheel_sha256": "71b661634a88e83859f86a38822ebae69f529d3fbf1246f1a53505092da41d2f",
        "release_sdist_sha256": "4c47aa09bc8c6f348f9280f95c9205609206b69fa7e91f0569d7c1e6302bc80b",
        "licence_sha256": "1baead7c445324d04c894f4499c790d8d6e93ad2b821192034ec11fb3c3d737a",
    }
    fields.pop(missing_field)
    lock = tmp_path / "brokers.lock"
    lock.write_text(
        '[[broker]]\nname = "kotakneoapi"\nversion = "3.0.7"\n'
        f'sha256 = "{'a' * 64}"\nlicence = "MIT"\n'
        'licence_source = "kotakneoapi-3.0.7.dist-info/licenses/LICENSE"\n'
        'sandbox_tested = "2026-09-20"\napproved_by = "maintainer"\n'
        + "".join(f'{key} = "{value}"\n' for key, value in fields.items()),
        encoding="utf-8",
    )
    req = tmp_path / "requirements.lock"
    req.write_text("", encoding="utf-8")
    uv = tmp_path / "uv.lock"
    uv.write_text(
        '[[package]]\nname = "kotakneoapi"\nversion = "3.0.7"\n'
        'source = { git = "https://github.com/Kotak-Neo/kotak-neo-python.git?rev='
        '5bb34fae39c4a52a0e6b59d7e2d17090cafc340c#5bb34fae39c4a52a0e6b59d7e2d17090cafc340c" }\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "BROKERS_LOCK", lock)
    monkeypatch.setattr(checker, "REQUIREMENTS_LOCK", req)
    monkeypatch.setattr(checker, "UV_LOCK", uv)

    assert checker.main() == 1
    assert missing_field in capsys.readouterr().err


def test_repo_kotak_pin_is_the_reviewed_runtime_and_release() -> None:
    entries = tomllib.loads((REPO / "brokers.lock").read_text(encoding="utf-8"))["broker"]
    neo = next(entry for entry in entries if entry["name"] == "kotakneoapi")
    uv_lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    runtime = next(package for package in uv_lock["package"] if package["name"] == "kotakneoapi")

    assert neo["source_commit"] == "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"
    assert neo["release_tag"] == "v3.0.7"
    assert neo["release_commit"] == "53cccc45fe56a193b30ffce3c03c71c5c0378538"
    assert runtime["source"]["git"] == (
        "https://github.com/Kotak-Neo/kotak-neo-python.git?rev="
        "5bb34fae39c4a52a0e6b59d7e2d17090cafc340c#5bb34fae39c4a52a0e6b59d7e2d17090cafc340c"
    )


def test_licence_gate_rejects_changed_installed_kotak_mit_file(tmp_path, monkeypatch, capsys) -> None:
    checker = _load_checker()
    lock = tmp_path / "brokers.lock"
    lock.write_text(
        '[[broker]]\nname = "kotakneoapi"\nversion = "3.0.7"\n'
        f'sha256 = "{"a" * 64}"\nlicence = "MIT"\n'
        'licence_source = "kotakneoapi-3.0.7.dist-info/licenses/LICENSE"\n'
        'sandbox_tested = "2026-09-20"\napproved_by = "maintainer"\n'
        f'source_commit = "{"b" * 40}"\nsource_tree = "{"c" * 40}"\n'
        f'release_tag = "v3.0.7"\nrelease_commit = "{"d" * 40}"\nrelease_tree = "{"e" * 40}"\n'
        f'release_wheel_sha256 = "{"a" * 64}"\nrelease_sdist_sha256 = "{"f" * 64}"\n'
        f'licence_sha256 = "{"0" * 64}"\n', encoding="utf-8",
    )
    req = tmp_path / "requirements.lock"
    req.write_text("", encoding="utf-8")
    uv = tmp_path / "uv.lock"
    uv.write_text(
        '[[package]]\nname = "kotakneoapi"\nversion = "3.0.7"\n'
        f'source = {{ git = "https://github.com/Kotak-Neo/kotak-neo-python.git?rev={"b" * 40}#{"b" * 40}" }}\n',
        encoding="utf-8",
    )

    licence = tmp_path / "LICENSE"
    licence.write_bytes(b"MIT licence content")

    class InstalledDistribution:
        def locate_file(self, _name: str) -> pathlib.Path:
            return licence

    monkeypatch.setattr(checker, "BROKERS_LOCK", lock)
    monkeypatch.setattr(checker, "REQUIREMENTS_LOCK", req)
    monkeypatch.setattr(checker, "UV_LOCK", uv)
    monkeypatch.setattr(metadata, "distribution", lambda _name: InstalledDistribution())

    assert checker.main() == 1
    assert "licence_sha256" in capsys.readouterr().err
