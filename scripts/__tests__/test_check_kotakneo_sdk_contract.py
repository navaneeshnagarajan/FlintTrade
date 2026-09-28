"""Offline tests for the Kotak Neo v3 dual-track compatibility gate."""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts import check_kotakneo_sdk_contract as checker


def _write_brokers_lock(
    root: Path,
    *,
    version: str = checker.KOTAK_VERSION,
    main_commit: str = checker.RUNTIME_MAIN_COMMIT,
    release_tag: str = checker.RELEASE_TAG,
    release_commit: str = checker.RELEASE_COMMIT,
    homepage: str = checker.KOTAK_REPO.removesuffix(".git"),
) -> None:
    (root / "brokers.lock").write_text(
        "\n".join(
            (
                "[[broker]]",
                'name = "kotakneoapi"',
                f'version = "{version}"',
                f'source_commit = "{main_commit}"',
                f'release_tag = "{release_tag}"',
                f'release_commit = "{release_commit}"',
                f'homepage = "{homepage}"',
                "",
            )
        ),
        encoding="utf-8",
    )


def test_gateway_declares_the_engine_it_imports_at_runtime() -> None:
    gateway = checker.REPO / "packages/integrations/gateway/pyproject.toml"
    dependencies = tomllib.loads(gateway.read_text(encoding="utf-8"))["project"]["dependencies"]

    assert "flinttrade-engine" in dependencies


def test_host_python_fails_closed_without_the_repository_environment(tmp_path: Path) -> None:
    with pytest.raises(checker.ContractError, match="repository-managed Python is missing"):
        checker.host_python(tmp_path)


def _snapshot(
    revision: str = checker.RUNTIME_MAIN_COMMIT,
    *,
    url: str = checker.KOTAK_REPO,
    requested_revision: str | None = None,
) -> dict[str, object]:
    requested = revision if requested_revision is None else requested_revision
    return {
        "distributions": {
            "kotakneoapi": {
                "version": "3.0.7",
                "direct_url": {
                    "url": url,
                    "vcs_info": {
                        "vcs": "git",
                        "commit_id": revision,
                        "requested_revision": requested,
                    },
                },
            }
        },
        "distribution_counts": {"kotakneoapi": 1},
        "namespace_owners": ["kotakneoapi"],
        "module_path": "/contract/env/lib/python3.12/site-packages/neo_api_client/__init__.py",
        "environment_root": "/contract/env",
        "cwd_files": [],
        "contract_ok": True,
    }


def test_validate_probe_accepts_exact_git_distribution() -> None:
    checker.validate_probe_result(_snapshot(), checker.TRACKS[0])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: row["distributions"]["kotakneoapi"].update(version="3.0.6"), "version"),
        (lambda row: row["distributions"]["kotakneoapi"].update(direct_url=None), "provenance"),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"].update(
                url="https://example.invalid/Kotak-Neo/kotak-neo-python.git"
            ),
            "origin",
        ),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"].update(
                url="git+https://github.com/Kotak-Neo/kotak-neo-python.git"
            ),
            "origin",
        ),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"].update(
                url="https://github.com:bad/Kotak-Neo/kotak-neo-python.git"
            ),
            "origin",
        ),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"]["vcs_info"].update(
                commit_id=checker.RUNTIME_MAIN_COMMIT[:12]
            ),
            "commit",
        ),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"]["vcs_info"].update(
                requested_revision=checker.RELEASE_COMMIT
            ),
            "requested revision",
        ),
        (
            lambda row: row["distributions"]["kotakneoapi"]["direct_url"]["vcs_info"].update(
                requested_revision="main"
            ),
            "requested revision",
        ),
        (lambda row: row.update(distribution_counts={"kotakneoapi": 2}), "ambiguous"),
        (lambda row: row.pop("distribution_counts"), "ambiguous"),
        (lambda row: row["namespace_owners"].append("some-other-dist"), "namespace"),
        (
            lambda row: row["distributions"].update(
                {"neo-api-client": {"version": "2.0.0", "direct_url": None}}
            ),
            "neo-api-client",
        ),
        (lambda row: row.update(module_path="/checkout/neo_api_client/__init__.py"), "environment"),
        (lambda row: row["cwd_files"].append("logs/neo-api-client.log"), "log"),
        (lambda row: row.update(contract_ok=False), "contract"),
    ],
)
def test_validate_probe_rejects_unattested_or_ambiguous_install(mutate, message: str) -> None:
    state = _snapshot()
    mutate(state)

    with pytest.raises(checker.ContractError, match=message):
        checker.validate_probe_result(state, checker.TRACKS[0])


def test_release_track_requires_the_peeled_release_commit() -> None:
    checker.validate_probe_result(_snapshot(checker.RELEASE_COMMIT), checker.TRACKS[1])

    with pytest.raises(checker.ContractError, match="commit"):
        checker.validate_probe_result(_snapshot(checker.RUNTIME_MAIN_COMMIT), checker.TRACKS[1])


def test_contract_config_is_derived_from_the_authoritative_broker_lock(tmp_path: Path) -> None:
    _write_brokers_lock(tmp_path)

    config = checker.load_contract_config(tmp_path)

    assert config == checker.ContractConfig(
        repo_url=checker.KOTAK_REPO,
        version=checker.KOTAK_VERSION,
        runtime_main_commit=checker.RUNTIME_MAIN_COMMIT,
        release_tag=checker.RELEASE_TAG,
        release_commit=checker.RELEASE_COMMIT,
    )
    assert checker.build_tracks(config)[1].release_tag == checker.RELEASE_TAG


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"release_tag": "v0.0.0"}, "tag"),
        ({"main_commit": "abc"}, "full Git hash"),
        ({"release_commit": "abc"}, "full Git hash"),
        ({"homepage": "https://example.invalid/kotak"}, "official upstream"),
    ],
)
def test_contract_config_rejects_stale_or_untrusted_lock_fields(
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    _write_brokers_lock(tmp_path, **overrides)

    with pytest.raises(checker.ContractError, match=message):
        checker.load_contract_config(tmp_path)


def test_subprocess_environment_scrubs_credentials_and_isolates_home(tmp_path: Path) -> None:
    source = {
        "PATH": "/synthetic/bin",
        "HTTPS_PROXY": "https://proxy.invalid",
        "KOTAK_MPIN": "broker-secret",
        "OPENAI_API_KEY": "api-secret",
        "AWS_SECRET_ACCESS_KEY": "cloud-secret",
        "GITHUB_TOKEN": "git-secret",
        "PIP_INDEX_URL": "https://user:pass@index.invalid/simple",
        "PYTHONPATH": "/untrusted",
    }

    environment = checker.build_subprocess_environment(tmp_path / "process", source=source)

    assert environment["PATH"] == "/synthetic/bin"
    assert environment["HTTPS_PROXY"] == "https://proxy.invalid"
    assert environment["HOME"] == str(tmp_path / "process/home")
    assert environment["UV_CACHE_DIR"] == str(tmp_path / "process/cache/uv")
    for forbidden in (
        "KOTAK_MPIN",
        "OPENAI_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "PIP_INDEX_URL",
        "PYTHONPATH",
    ):
        assert forbidden not in environment


def test_build_track_commands_install_locked_base_then_one_git_sdk_then_editables(tmp_path: Path) -> None:
    env_dir = tmp_path / "env"
    requirements = tmp_path / "base.txt"
    repo = tmp_path / "repo"
    managed_python = repo / ".venv" / ("Scripts/python.exe" if checker.IS_WINDOWS else "bin/python")
    managed_python.parent.mkdir(parents=True)
    managed_python.touch()

    commands = checker.build_track_commands(checker.TRACKS[0], env_dir, requirements, repo=repo)

    python = env_dir / ("Scripts/python.exe" if checker.IS_WINDOWS else "bin/python")
    assert commands == [
        ["uv", "venv", str(env_dir), "--python", str(managed_python)],
        ["uv", "pip", "install", "--python", str(python), "--require-hashes", "-r", str(requirements)],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--only-binary=:all:",
            "--no-deps",
            "-r",
            str(repo / "broker-sdk-build.lock"),
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-build-isolation",
            "--no-deps",
            f"git+{checker.KOTAK_REPO}@{checker.RUNTIME_MAIN_COMMIT}",
        ],
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "--editable",
            str(repo / "packages/core/core"),
            "--editable",
            str(repo / "packages/core/data"),
            "--editable",
            str(repo / "packages/services/engine"),
            "--editable",
            str(repo / "packages/integrations/gateway"),
        ],
        ["uv", "pip", "check", "--python", str(python)],
    ]


def test_export_command_is_frozen_and_excludes_workspace_and_sdk(tmp_path: Path) -> None:
    command = checker.build_export_command(tmp_path / "base.txt", repo=Path("/repo"))

    assert command == [
        "uv",
        "export",
        "--frozen",
        "--package",
        "flinttrade-gateway",
        "--no-dev",
        "--no-emit-workspace",
        "--no-emit-package",
        "kotakneoapi",
        "--output-file",
        str(tmp_path / "base.txt"),
    ]


def test_scan_result_rejects_warning_even_when_scanner_exits_zero() -> None:
    result = subprocess.CompletedProcess(
        ["scanner"],
        0,
        "[WARNING] adapter.py:1: stale\n\n0 error(s), 1 warning(s) across 7 file(s).\n",
        "",
    )

    with pytest.raises(checker.ContractError, match="1 warning"):
        checker.validate_scanner_result(result, expected_files=7)


def test_scan_result_rejects_conflicting_or_duplicate_summaries() -> None:
    result = subprocess.CompletedProcess(
        ["scanner"],
        0,
        (
            "0 error(s), 0 warning(s) across 7 file(s).\n"
            "1 error(s), 2 warning(s) across 7 file(s).\n"
        ),
        "",
    )

    with pytest.raises(checker.ContractError, match="exactly one"):
        checker.validate_scanner_result(result, expected_files=7)


@pytest.mark.parametrize(
    "stdout",
    [
        "0 error(s), 0 warning(s) across 6 file(s).\n",
        "1 error(s), 0 warning(s) across 7 file(s).\n",
        "No known v2 -> kotakneoapi migration issues found.\n",
    ],
)
def test_scan_result_requires_an_exact_clean_seven_file_summary(stdout: str) -> None:
    with pytest.raises(checker.ContractError):
        checker.validate_scanner_result(subprocess.CompletedProcess(["scanner"], 0, stdout, ""), expected_files=7)


def test_scan_result_allows_information_only_findings() -> None:
    result = subprocess.CompletedProcess(
        ["scanner"],
        0,
        "[INFO] sdk.py:1: package rename\n\n0 error(s), 0 warning(s) across 7 file(s).\n",
        "",
    )

    checker.validate_scanner_result(result, expected_files=7)


def test_required_scanner_targets_are_exact_unique_and_extant(tmp_path: Path) -> None:
    for relative in checker.SCANNER_TARGETS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture\n", encoding="utf-8")

    targets = checker.resolve_scanner_targets(tmp_path)

    assert len(targets) == 7
    assert len(set(targets)) == 7


def test_required_scanner_target_missing_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(checker.ContractError, match="missing"):
        checker.resolve_scanner_targets(tmp_path)


def test_scanner_is_read_from_the_exact_runtime_commit(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(args, **kwargs):
        command = list(map(str, args))
        calls.append(command)
        if command[-1] == f"{checker.RUNTIME_MAIN_COMMIT}:docs/scripts/migrate_from_v2.py":
            return subprocess.CompletedProcess(command, 0, "print('scanner')\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    scanner = checker.materialise_scanner(tmp_path, run=run)

    assert scanner.read_text(encoding="utf-8") == "print('scanner')\n"
    assert calls == [
        ["git", "init", "--bare", str(tmp_path / "kotak-upstream.git")],
        [
            "git",
            f"--git-dir={tmp_path / 'kotak-upstream.git'}",
            "fetch",
            "--depth=1",
            checker.KOTAK_REPO,
            checker.RUNTIME_MAIN_COMMIT,
        ],
        [
            "git",
            f"--git-dir={tmp_path / 'kotak-upstream.git'}",
            "show",
            f"{checker.RUNTIME_MAIN_COMMIT}:docs/scripts/migrate_from_v2.py",
        ],
    ]


def test_contract_workspace_is_removed_when_a_command_fails(tmp_path: Path) -> None:
    _write_brokers_lock(tmp_path)

    def fail(_args, **_kwargs):
        return subprocess.CompletedProcess([], 9, "", "synthetic failure")

    with pytest.raises(checker.ContractError, match="synthetic failure"):
        checker.run_contract(repo=tmp_path, run=fail, temporary_parent=tmp_path)

    assert list(tmp_path.glob("kotakneo-contract-*")) == []


def test_probe_output_must_be_one_json_object() -> None:
    with pytest.raises(checker.ContractError, match="JSON"):
        checker.parse_probe_output("SDK banner\n{}")

    assert checker.parse_probe_output(json.dumps(_snapshot()))["contract_ok"] is True


def test_probe_uses_the_same_fail_closed_feed_factory_kwargs_as_runtime() -> None:
    assert "facade.create_websocket(\n    max_reconnect_attempts=0," in checker._PROBE_SCRIPT
    assert "facade.create_order_feed(\n    max_reconnect_attempts=0," in checker._PROBE_SCRIPT
    assert 'url="wss://example.invalid' not in checker._PROBE_SCRIPT


def test_probe_installs_a_process_wide_python_network_guard_before_sdk_import() -> None:
    guard = checker._PROBE_SCRIPT.index("sys.addaudithook(deny_network_and_process)")
    sdk_import = checker._PROBE_SCRIPT.index("import neo_api_client")

    assert guard < sdk_import
    assert 'event.startswith("socket.")' in checker._PROBE_SCRIPT
    assert '"subprocess.Popen"' in checker._PROBE_SCRIPT
    assert "socket.socket(socket.AF_INET, socket.SOCK_DGRAM)" in checker._PROBE_SCRIPT
    compile(checker._PROBE_SCRIPT, "<kotak-contract-probe>", "exec")


def test_probe_attests_every_feed_method_signature_used_by_the_runtime() -> None:
    assert "feed_signatures = {" in checker._PROBE_SCRIPT
    for method in (
        "connect",
        "close",
        "subscribe_scrips",
        "unsubscribe_scrips",
        "subscribe_depth",
        "unsubscribe_depth",
        "subscribe_index",
        "unsubscribe_index",
        "__aiter__",
    ):
        assert f'"{method}"' in checker._PROBE_SCRIPT
