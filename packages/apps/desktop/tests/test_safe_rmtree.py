"""Subprocess tests for the packaged POSIX identity-bound tree remover."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(os.name != "posix", reason="the safe tree remover is POSIX-only"),
]

HELPER = Path(__file__).parents[1] / "resources" / "bootstrap" / "flinttrade-safe-rmtree.py"


def _run_helper(
    parent: Path,
    target: str,
    quarantine: str,
    expected_dev: int,
    expected_ino: int,
    *,
    prepare_private_parent: bool = True,
) -> subprocess.CompletedProcess[str]:
    if prepare_private_parent:
        parent.chmod(0o700)
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--parent",
            str(parent),
            "--target",
            target,
            "--quarantine",
            quarantine,
            "--expected-dev",
            str(expected_dev),
            "--expected-ino",
            str(expected_ino),
        ],
        capture_output=True,
        check=False,
        text=True,
    )


def _identity(directory: Path) -> tuple[int, int]:
    value = directory.stat(follow_symlinks=False)
    return value.st_dev, value.st_ino


def test_removes_exact_tree_without_following_symlinks(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    target = parent / ".FlintTrade.last-known-good"
    quarantine_name = ".FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000"
    outside = tmp_path / "outside"
    (target / "nested" / "deeper").mkdir(parents=True)
    outside.mkdir()
    (target / "root.txt").write_text("root", encoding="utf-8")
    os.link(target / "root.txt", target / "root-hardlink.txt")
    (target / "nested" / "deeper" / "leaf.txt").write_text("leaf", encoding="utf-8")
    (outside / "must-survive.txt").write_text("outside", encoding="utf-8")
    (target / "outside-link").symlink_to(outside, target_is_directory=True)
    (target / "file-link").symlink_to(target / "root.txt")
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(parent, target.name, quarantine_name, expected_dev, expected_ino)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"ok": True, "status": "removed"}
    assert result.stderr == ""
    assert not target.exists()
    assert not (parent / quarantine_name).exists()
    assert (outside / "must-survive.txt").read_text(encoding="utf-8") == "outside"


def test_resumes_an_exact_already_quarantined_tree(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    parent.mkdir()
    target_name = ".FlintTrade.last-known-good"
    quarantine_name = ".FlintTrade.stale-quarantine-123e4567-e89b-42d3-a456-426614174000"
    quarantine = parent / quarantine_name
    (quarantine / "nested").mkdir(parents=True)
    (quarantine / "nested" / "file.txt").write_text("retry", encoding="utf-8")
    expected_dev, expected_ino = _identity(quarantine)

    result = _run_helper(parent, target_name, quarantine_name, expected_dev, expected_ino)

    assert result.returncode == 0, result.stderr
    assert not (parent / target_name).exists()
    assert not quarantine.exists()


@pytest.mark.parametrize("layout", ["both", "neither"])
def test_rejects_ambiguous_evidence_without_removal(tmp_path: Path, layout: str) -> None:
    parent = tmp_path / "source-parent"
    parent.mkdir()
    target = parent / "target"
    quarantine = parent / "quarantine"
    if layout == "both":
        target.mkdir()
        quarantine.mkdir()
        expected_dev, expected_ino = _identity(target)
    else:
        expected_dev, expected_ino = _identity(parent)

    result = _run_helper(parent, target.name, quarantine.name, expected_dev, expected_ino)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "AMBIGUOUS_EVIDENCE"}
    assert target.exists() is (layout == "both")
    assert quarantine.exists() is (layout == "both")


def test_rejects_identity_mismatch_and_preserves_target(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    target = parent / "target"
    target.mkdir(parents=True)
    (target / "evidence.txt").write_text("retain", encoding="utf-8")
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(parent, target.name, "quarantine", expected_dev, expected_ino + 1)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "IDENTITY_MISMATCH"}
    assert (target / "evidence.txt").read_text(encoding="utf-8") == "retain"
    assert not (parent / "quarantine").exists()


def test_rejects_shared_parent_namespace_without_removal(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    target = parent / "target"
    target.mkdir(parents=True)
    (target / "evidence.txt").write_text("retain", encoding="utf-8")
    parent.chmod(0o750)
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(
        parent,
        target.name,
        "quarantine",
        expected_dev,
        expected_ino,
        prepare_private_parent=False,
    )

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "UNTRUSTED_PARENT"}
    assert (target / "evidence.txt").read_text(encoding="utf-8") == "retain"
    assert not (parent / "quarantine").exists()


@pytest.mark.skipif(sys.platform != "darwin", reason="extended ACL probe is Darwin-specific")
def test_rejects_mode_0700_parent_with_extended_acl(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    target = parent / "target"
    target.mkdir(parents=True)
    (target / "evidence.txt").write_text("retain", encoding="utf-8")
    subprocess.run(
        [
            "chmod",
            "+a",
            "everyone allow list,search,add_file,add_subdirectory,delete_child",
            str(parent),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    parent.chmod(0o700)
    assert parent.stat().st_mode & 0o777 == 0o700
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(
        parent,
        target.name,
        "quarantine",
        expected_dev,
        expected_ino,
        prepare_private_parent=False,
    )

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "UNTRUSTED_PARENT"}
    assert (target / "evidence.txt").read_text(encoding="utf-8") == "retain"
    assert not (parent / "quarantine").exists()


def test_rejects_symlink_target_without_following_it(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    outside = tmp_path / "outside"
    parent.mkdir()
    outside.mkdir()
    (outside / "evidence.txt").write_text("retain", encoding="utf-8")
    target = parent / "target"
    target.symlink_to(outside, target_is_directory=True)
    expected = target.stat(follow_symlinks=False)

    result = _run_helper(parent, target.name, "quarantine", expected.st_dev, expected.st_ino)

    assert result.returncode != 0
    assert json.loads(result.stderr)["code"] in {"FILESYSTEM_ERROR", "IDENTITY_MISMATCH"}
    assert target.is_symlink()
    assert (outside / "evidence.txt").read_text(encoding="utf-8") == "retain"


def test_rejects_unconfined_entry_name_without_touching_sibling(tmp_path: Path) -> None:
    parent = tmp_path / "source-parent"
    parent.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    (sibling / "evidence.txt").write_text("retain", encoding="utf-8")
    expected_dev, expected_ino = _identity(sibling)

    result = _run_helper(parent, "../sibling", "quarantine", expected_dev, expected_ino)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "INVALID_ENTRY_NAME"}
    assert (sibling / "evidence.txt").read_text(encoding="utf-8") == "retain"


def test_rejects_symlink_parent_without_following_it(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    target = real_parent / "target"
    target.mkdir()
    alias = tmp_path / "parent-alias"
    alias.symlink_to(real_parent, target_is_directory=True)
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(alias, target.name, "quarantine", expected_dev, expected_ino)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "FILESYSTEM_ERROR"}
    assert target.exists()


def test_rejects_symlink_in_parent_chain_without_following_it(tmp_path: Path) -> None:
    real_ancestor = tmp_path / "real-ancestor"
    real_parent = real_ancestor / "source-parent"
    real_parent.mkdir(parents=True)
    target = real_parent / "target"
    target.mkdir()
    alias_ancestor = tmp_path / "ancestor-alias"
    alias_ancestor.symlink_to(real_ancestor, target_is_directory=True)
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(alias_ancestor / "source-parent", target.name, "quarantine", expected_dev, expected_ino)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "FILESYSTEM_ERROR"}
    assert target.exists()


def test_error_output_never_contains_private_arguments(tmp_path: Path) -> None:
    secret_parent = tmp_path / "PRIVATE-path-token"
    secret_parent.mkdir()
    target_name = "PRIVATE-target-token"
    quarantine_name = "PRIVATE-quarantine-token"
    target = secret_parent / target_name
    target.mkdir()
    expected_dev, expected_ino = _identity(target)

    result = _run_helper(secret_parent, target_name, quarantine_name, expected_dev, expected_ino + 1)

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "IDENTITY_MISMATCH"}
    combined = result.stdout + result.stderr
    assert str(secret_parent) not in combined
    assert target_name not in combined
    assert quarantine_name not in combined


def test_argument_parser_does_not_echo_rejected_private_value(tmp_path: Path) -> None:
    private_value = str(tmp_path / "PRIVATE-invalid-parent")
    result = subprocess.run(
        [sys.executable, str(HELPER), "--parent", private_value, "--unknown-private-option"],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert json.loads(result.stderr) == {"ok": False, "code": "INVALID_ARGUMENTS"}
    assert private_value not in result.stdout + result.stderr
