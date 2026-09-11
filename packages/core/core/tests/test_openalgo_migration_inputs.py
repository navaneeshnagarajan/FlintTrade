"""Private upgrade inputs never activate clients or invent missing settings."""

import importlib
import json

import pytest


def migration():
    return importlib.import_module("flinttrade_core.openalgo_migration")


def test_env_source_is_explicit_private_and_preserves_absent_websocket():
    source = migration().read_legacy_openalgo_env({
        "OPENALGO_HOST": "https://bridge.example.test",
        "OPENALGO_API_KEY": "synthetic-upgrade-key",
    })
    assert source.setup == {"base_url": "https://bridge.example.test"}
    assert source.credential == "synthetic-upgrade-key"
    assert "synthetic-upgrade-key" not in repr(source)
    assert source.source_kind == "legacy_openalgo_env"


def test_empty_env_is_not_a_default_connection():
    assert migration().read_legacy_openalgo_env({}) is None


def test_explicit_legacy_port_is_retained_without_overriding_host_port():
    reader = migration().read_legacy_openalgo_env
    assert reader({"OPENALGO_HOST": "http://bridge.example.test", "OPENALGO_PORT": "5050"}).setup == {
        "base_url": "http://bridge.example.test:5050",
    }
    assert reader({"OPENALGO_HOST": "http://bridge.example.test:7070", "OPENALGO_PORT": "5050"}).setup == {
        "base_url": "http://bridge.example.test:7070",
    }


@pytest.mark.parametrize("fields", [
    {"OPENALGO_API_KEY": "synthetic-only-key"},
    {"OPENALGO_HOST": "https://bridge.example.test/path"},
    {"OPENALGO_HOST": "https://token@bridge.example.test"},
    {"OPENALGO_HOST": "https://bridge.example.test", "OPENALGO_WS_PORT": "0"},
    {"OPENALGO_HOST": "https://bridge.example.test", "OPENALGO_PORT": True},
])
def test_invalid_source_is_redacted_and_never_receives_fallback_endpoint(fields):
    module = migration()
    with pytest.raises(module.OpenAlgoMigrationInputError) as error:
        module.read_legacy_openalgo_env(fields)
    assert str(error.value) == "openalgo_migration_input_invalid"


def test_workspace_source_keeps_telegram_out_of_selector_setup():
    source = migration().read_legacy_openalgo_workspace({"openalgo": {
        "host": "http://bridge.example.test:5050",
        "api_key": "synthetic-workspace-key",
        "ws_port": 9090,
        "telegram_username": "operator",
    }})
    assert source.setup == {"base_url": "http://bridge.example.test:5050", "ws_port": 9090}
    assert source.credential == "synthetic-workspace-key"
    assert "synthetic-workspace-key" not in repr(source)


def test_partial_update_preserves_exact_setup_and_has_no_implicit_key_replacement():
    change = migration().parse_openalgo_config_update(
        {"ws_port": 9091},
        current_setup={"base_url": "https://bridge.example.test:5050", "ws_port": 9090},
    )
    assert change.setup == {"base_url": "https://bridge.example.test:5050", "ws_port": 9091}
    assert change.credential_action == "preserve"
    assert change.credential is None


def test_telegram_is_a_separate_action_not_a_selector_rebuild():
    change = migration().parse_openalgo_config_update({"telegram_username": "new_operator"}, current_setup=None)
    assert change.username == "new_operator"
    assert not hasattr(change, "setup")
    module = migration()
    with pytest.raises(module.MixedOpenAlgoAuthoritiesError) as error:
        module.parse_openalgo_config_update({"telegram_username": "operator", "api_key": "synthetic-key"}, current_setup=None)
    assert str(error.value) == "mixed_authorities"


def test_key_replacement_is_private_and_does_not_change_setup():
    change = migration().parse_openalgo_config_update(
        {"api_key": "synthetic-replacement"}, current_setup={"base_url": "https://bridge.example.test"},
    )
    assert change.setup == {"base_url": "https://bridge.example.test"}
    assert change.credential_action == "replace"
    assert change.credential == "synthetic-replacement"
    assert "synthetic-replacement" not in repr(change)


def test_consumed_env_is_not_read_or_compared_to_new_target():
    class UnreadableEnv(dict):
        def get(self, *_args, **_kwargs):
            pytest.fail("consumed legacy env was consulted")

    assert migration().read_legacy_openalgo_env(UnreadableEnv(), consumed=True) is None


@pytest.mark.parametrize("payload", [{"port": None}, {"port": True}, {"ws_port": None}, {"api_key": ""}])
def test_invalid_explicit_fields_are_not_silently_treated_as_omitted(payload):
    module = migration()
    with pytest.raises(module.OpenAlgoMigrationInputError):
        module.parse_openalgo_config_update(payload, current_setup={"base_url": "https://bridge.example.test"})


def test_host_only_update_preserves_previous_explicit_rest_port():
    change = migration().parse_openalgo_config_update(
        {"host": "https://new-bridge.example.test"},
        current_setup={"base_url": "http://bridge.example.test:5050", "ws_port": 9090},
    )
    assert change.setup == {"base_url": "https://new-bridge.example.test:5050", "ws_port": 9090}


def test_conflicting_explicit_host_and_port_does_not_silently_drop_a_field():
    module = migration()
    with pytest.raises(module.OpenAlgoMigrationInputError):
        module.parse_openalgo_config_update(
            {"host": "https://bridge.example.test:5050", "port": 6060}, current_setup=None,
        )


def test_setup_projection_is_detached_from_immutable_input():
    change = migration().parse_openalgo_config_update(
        {"ws_port": 9090}, current_setup={"base_url": "https://bridge.example.test"},
    )
    projection = change.setup
    projection["base_url"] = "https://changed.example.test"
    assert change.setup == {"base_url": "https://bridge.example.test", "ws_port": 9090}


def test_agreeing_sources_merge_only_explicit_facts_without_erasing_credentials():
    module = migration()
    env = module.read_legacy_openalgo_env({"OPENALGO_HOST": "https://bridge.example.test"})
    workspace = module.read_legacy_openalgo_workspace({"openalgo": {
        "host": "https://bridge.example.test", "api_key": "synthetic-key", "ws_port": 9090,
    }})
    result = module.resolve_legacy_openalgo_inputs((env, workspace))
    assert result.setup == {"base_url": "https://bridge.example.test", "ws_port": 9090}
    assert result.credential_action == "replace"
    assert result.credential == "synthetic-key"
    assert "synthetic-key" not in repr(result)


@pytest.mark.parametrize("changed", [
    {"host": "https://different.example.test"},
    {"ws_port": 9091},
    {"api_key": "synthetic-different-key"},
])
def test_disagreeing_live_and_rollback_sources_require_reconciliation(changed):
    module = migration()
    fields = {"host": "https://bridge.example.test", "api_key": "synthetic-key", "ws_port": 9090}
    live = module.read_legacy_openalgo_workspace({"openalgo": fields})
    rollback = module.read_legacy_openalgo_workspace({"openalgo": fields | changed})
    with pytest.raises(module.OpenAlgoMigrationConflict) as error:
        module.resolve_legacy_openalgo_inputs((live, rollback))
    assert str(error.value) == "openalgo_migration_conflict"
    assert live.credential == "synthetic-key"
    assert "synthetic" not in str(error.value)


def test_owner_validated_reader_includes_allowlisted_sole_rollback_copy(tmp_path):
    from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory

    harden_directory(tmp_path)
    with HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("workspace.1.2.0.bak.json", json.dumps({"openalgo": {
            "host": "https://bridge.example.test", "api_key": "synthetic-sole-copy",
        }}))
        directory.write_text("workspace.unknown.bak.json", "not a supported source")
    files = migration().read_legacy_openalgo_files(tmp_path)
    assert len(files) == 1
    assert files[0].filename == "workspace.1.2.0.bak.json"
    assert files[0].source.credential == "synthetic-sole-copy"
    assert files[0].identity.inode > 0
    assert "synthetic-sole-copy" not in repr(files)
    # Planning cannot consume the sole original source.
    assert "synthetic-sole-copy" in (tmp_path / files[0].filename).read_text()


def test_reader_rejects_symlinked_allowlisted_source(tmp_path):
    from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory

    harden_directory(tmp_path)
    with HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("original.json", "{}")
    (tmp_path / "workspace.1.2.0.bak.json").symlink_to(tmp_path / "original.json")
    module = migration()
    with pytest.raises(module.OpenAlgoMigrationInputError):
        module.read_legacy_openalgo_files(tmp_path)


def test_reader_rejects_duplicate_members_without_reflecting_private_values(tmp_path):
    from flinttrade_core.secure_file import HeldOwnerDirectory, harden_directory

    harden_directory(tmp_path)
    with HeldOwnerDirectory(tmp_path) as directory:
        directory.write_text("workspace.1.2.0.bak.json", '{"openalgo": {}, "openalgo": "synthetic-secret"}')
    module = migration()
    with pytest.raises(module.OpenAlgoMigrationInputError) as error:
        module.read_legacy_openalgo_files(tmp_path)
    assert str(error.value) == "openalgo_migration_input_invalid"
