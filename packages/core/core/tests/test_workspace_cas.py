"""Workspace authority generations, immutable snapshots and conditional writes."""

from __future__ import annotations

import copy
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from flinttrade_core import workspace_migrations as persistence
from flinttrade_core.workspace import Workspace

_INSTANCE = "07920366-4cf4-4ec3-af37-14758cb19f5a"
_MAX = (1 << 63) - 1
_SERVICES = {"connection_epoch": 0, "connections": [], "routing": {}, "budgets": {}, "access_grants": {}}


def _current():
    return {
        "version": "1.3.0",
        "workspace_instance_id": _INSTANCE,
        "workspace_generation": 1,
        "broker_authority_generation": 1,
        "services": copy.deepcopy(_SERVICES),
    }


def _seed(tmp_path, config):
    path = tmp_path / "workspace.json"
    path.write_text(json.dumps(config))
    return path


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode protection; Windows DACL requires native evidence")
@pytest.mark.parametrize("version", ["0.1.0-alpha", "0.5.0", "0.5.2", "1.0.0", "1.1.0", "1.2.0"])
def test_current_read_hardens_every_supported_existing_rollback_file(tmp_path, version):
    _seed(tmp_path, _current())
    rollback = tmp_path / f"workspace.{version}.bak.json"
    rollback.write_text(json.dumps({"version": version, "openalgo": {"api_key": "1111"}}))
    rollback.chmod(0o644)
    persistence.read_workspace_snapshot(tmp_path)
    assert stat.S_IMODE(rollback.stat().st_mode) == 0o600


def test_snapshot_rejects_non_json_mutable_values():
    with pytest.raises(TypeError):
        persistence.WorkspaceSnapshot({"extension": {1, 2}}, None)


@pytest.mark.parametrize("override", ["FLINTTRADE_WORKSPACE_DIR", "FLINTTRADE_HOME"])
def test_workspace_resolution_can_avoid_directory_creation_and_permission_changes(tmp_path, monkeypatch, override):
    from flinttrade_core.workspace import workspace_dir

    target = tmp_path / "absent" / "workspace"
    monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
    monkeypatch.setenv(override, str(target))
    assert workspace_dir(ensure_exists=False) == target
    assert not target.parent.exists()
    target.mkdir(parents=True)
    if os.name == "posix":
        target.chmod(0o755)
    before = stat.S_IMODE(target.stat().st_mode)
    assert workspace_dir(ensure_exists=False) == target
    assert stat.S_IMODE(target.stat().st_mode) == before


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("invalid", [{1: "fixture"}, {"nested": [{False: "fixture"}]}, {"nested": {1, 2}}])
def test_invalid_complete_snapshot_is_rejected_before_any_persisted_change(tmp_path, existing, invalid):
    first = persistence.compare_and_swap_workspace(tmp_path, None, lambda _cfg: None) if existing else None
    path = tmp_path / "workspace.json"
    before = path.read_bytes() if existing else None

    with pytest.raises(TypeError):
        persistence.compare_and_swap_workspace(
            tmp_path, first.version if first else None, lambda config: config.update(extension=invalid)
        )

    if existing:
        assert path.read_bytes() == before
        current = persistence.read_workspace_snapshot(tmp_path)
        assert current.version == first.version
        assert current.config["broker_authority_generation"] == 1
    else:
        assert not path.exists()


def test_invalid_mapping_key_cannot_be_accepted_as_a_serialisation_noop(tmp_path):
    first = persistence.compare_and_swap_workspace(
        tmp_path, None, lambda config: config.update(extension={"1": "fixture"})
    )
    path = tmp_path / "workspace.json"
    before = path.read_bytes()
    with pytest.raises(TypeError, match="keys must be strings"):
        persistence.compare_and_swap_workspace(
            tmp_path, first.version, lambda config: config.update(extension={1: "fixture"})
        )
    assert path.read_bytes() == before
    assert persistence.read_workspace_snapshot(tmp_path).version == first.version


def test_persisted_uninitialised_workspace_can_finish_onboarding_without_replacing_identity(tmp_path):
    config = persistence.default_workspace_config(initialized=False)
    config["extension"] = {"kept": True}
    initial = persistence.compare_and_swap_workspace(tmp_path, None, lambda _: config)
    workspace = Workspace(tmp_path)
    workspace.initialise()
    saved = persistence.read_workspace_snapshot(tmp_path)
    assert saved.config["initialized"] is True
    assert saved.config["extension"]["kept"] is True
    assert saved.version.instance_id == initial.version.instance_id
    assert saved.version.generation == 2
    assert saved.config["broker_authority_generation"] == 1


def test_stale_resumed_onboarding_does_not_overwrite_another_writer(tmp_path):
    persistence.compare_and_swap_workspace(
        tmp_path, None, lambda _: persistence.default_workspace_config(initialized=False)
    )
    stale = Workspace(tmp_path)
    Workspace(tmp_path).set("services.connection_epoch", 1)
    before = (tmp_path / "workspace.json").read_bytes()
    with pytest.raises(persistence.WorkspaceVersionConflict):
        stale.initialise()
    assert (tmp_path / "workspace.json").read_bytes() == before


def test_credential_database_delete_recreate_does_not_change_workspace_identity(tmp_path):
    from flinttrade_gateway.credentials import CredentialStore

    Workspace(tmp_path).initialise()
    initial = persistence.read_workspace_snapshot(tmp_path)
    path = tmp_path / "credentials.db"
    CredentialStore(path, "controlled-test-password")
    path.unlink()
    CredentialStore(path, "controlled-test-password")
    assert persistence.read_workspace_snapshot(tmp_path).version == initial.version


@pytest.mark.parametrize("version", ["0.1.0-alpha", "0.5.0", "0.5.2", "1.0.0", "1.1.0", "1.2.0"])
def test_every_legacy_edge_mints_current_authority_once(tmp_path, version):
    _seed(tmp_path, {"version": version, "extension": {"preserved": [1, 2]}})
    config = persistence.run_migrations(tmp_path)
    assert config["version"] == "1.3.0"
    assert config["workspace_generation"] == 1
    assert config["broker_authority_generation"] == 1
    assert str(UUID(config["workspace_instance_id"])) == config["workspace_instance_id"]
    assert UUID(config["workspace_instance_id"]).version == 4
    assert config["services"] == _SERVICES
    assert config["extension"] == {"preserved": [1, 2]}


def test_120_additive_migration_preserves_full_llm_brokers_and_extensions(tmp_path):
    legacy = {
        "version": "1.2.0",
        "llm": {"provider": "custom", "host": "https://fixture.invalid", "unknown": ["kept"]},
        "brokers": {"registered": ["fixture:account"], "extension": {"enabled": False}},
        "services": {"extension": {"x": [1]}, **copy.deepcopy(_SERVICES)},
        "unknown": [1, {"nested": True}],
    }
    _seed(tmp_path, legacy)
    config = persistence.run_migrations(tmp_path)
    for key in ("llm", "brokers", "services", "unknown"):
        assert config[key] == legacy[key]


@pytest.mark.parametrize(
    "key,value",
    [
        ("workspace_instance_id", _INSTANCE),
        ("workspace_generation", 1),
        ("broker_authority_generation", 1),
    ],
)
def test_legacy_reserved_top_level_collision_leaves_original_bytes(tmp_path, key, value):
    path = _seed(tmp_path, {"version": "1.2.0", key: value})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persistence.run_migrations(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "services",
    [
        None,
        [],
        {"connection_epoch": False},
        {"connection_epoch": 1},
        {"connections": [{}]},
        {"routing": {"model": "injected"}},
        {"budgets": [1]},
        {"access_grants": {"x": True}},
    ],
)
def test_legacy_reserved_service_collision_leaves_original_bytes(tmp_path, services):
    path = _seed(tmp_path, {"version": "1.2.0", "services": services})
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persistence.run_migrations(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["workspace_generation", "broker_authority_generation"])
@pytest.mark.parametrize("value", [None, False, True, 0, -1, 1.0, "1", _MAX + 1])
def test_malformed_current_generations_fail_before_recovery(tmp_path, monkeypatch, field, value):
    config = _current()
    config[field] = value
    path = _seed(tmp_path, config)
    before = path.read_bytes()

    def forbidden_recovery(*_args):
        pytest.fail("malformed current workspace reached secret recovery")

    monkeypatch.setattr(persistence, "_recover_staged_lmstudio_secret", forbidden_recovery)
    with pytest.raises(ValueError):
        persistence.run_migrations(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", [None, "", "not-a-uuid", _INSTANCE.upper(), 1])
def test_current_invalid_identity_is_not_normalised(tmp_path, value):
    config = _current()
    config["workspace_instance_id"] = value
    path = _seed(tmp_path, config)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persistence.run_migrations(tmp_path)
    assert path.read_bytes() == before


def test_absent_snapshot_has_no_identity_and_first_creation_mints_it(tmp_path):
    assert callable(getattr(persistence, "read_workspace_snapshot", None)), "public snapshot API is absent"
    snapshot = persistence.read_workspace_snapshot(tmp_path)
    assert snapshot.version is None
    assert not (tmp_path / "workspace.json").exists()
    for key in ("workspace_instance_id", "workspace_generation", "broker_authority_generation"):
        assert key not in persistence.default_workspace_config()
    created = persistence.compare_and_swap_workspace(tmp_path, None, lambda config: config.update(label="first"))
    assert created.version.generation == 1
    assert created.config["broker_authority_generation"] == 1
    assert created.version.instance_id.version == 4
    with pytest.raises(persistence.WorkspaceVersionConflict):
        persistence.compare_and_swap_workspace(tmp_path, None, lambda config: config.update(label="second"))
    assert json.loads((tmp_path / "workspace.json").read_text())["label"] == "first"


def test_snapshot_is_deeply_immutable_and_detached(tmp_path):
    ws = Workspace(tmp_path)
    ws.initialise()
    assert callable(getattr(persistence, "read_workspace_snapshot", None)), "public snapshot API is absent"
    snapshot = persistence.read_workspace_snapshot(tmp_path)
    with pytest.raises(TypeError):
        snapshot.config["ui"]["theme"] = "light"
    with pytest.raises((AttributeError, TypeError)):
        snapshot.config["brokers"]["registered"].append("fixture:account")
    ws.set("ui.theme", "light")
    assert snapshot.config["ui"]["theme"] == "dark"


def test_two_first_creators_have_exactly_one_winner(tmp_path):
    assert callable(getattr(persistence, "compare_and_swap_workspace", None)), "public CAS API is absent"
    barrier = Barrier(2)

    def create(label):
        barrier.wait(timeout=5)
        try:
            persistence.compare_and_swap_workspace(tmp_path, None, lambda config: config.update(label=label))
        except persistence.WorkspaceVersionConflict:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, ["first", "second"])) == [False, True]
    assert persistence.read_workspace_snapshot(tmp_path).version.generation == 1


def test_true_aba_and_foreign_instance_refuse_stale_save(tmp_path):
    ws = Workspace(tmp_path)
    ws.initialise()
    stale = Workspace(tmp_path)
    ws.set("ui.theme", "light")
    ws.set("ui.theme", "dark")
    with pytest.raises(RuntimeError):
        stale.save()
    stale.load()
    foreign = json.loads(ws.config_path.read_text())
    foreign["workspace_instance_id"] = str(uuid4())
    _seed(tmp_path, foreign)
    with pytest.raises(persistence.WorkspaceVersionConflict):
        stale.save()
    assert json.loads(ws.config_path.read_text()) == foreign


@pytest.mark.parametrize(
    "field,value",
    [
        ("workspace_instance_id", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"),
        ("workspace_generation", 2),
        ("broker_authority_generation", 2),
    ],
)
@pytest.mark.parametrize("remove", [False, True])
def test_updater_cannot_replace_or_remove_reserved_values(tmp_path, field, value, remove):
    ws = Workspace(tmp_path)
    ws.initialise()
    before = ws.config_path.read_bytes()

    def tamper(config):
        if remove:
            config.pop(field, None)
        else:
            config[field] = value

    with pytest.raises(ValueError):
        ws.update(tamper)
    assert ws.config_path.read_bytes() == before


def test_noop_and_failed_writes_do_not_advance_authority(tmp_path, monkeypatch):
    ws = Workspace(tmp_path)
    ws.initialise()
    before = ws.config_path.read_bytes()
    ws.update(lambda config: None)
    assert ws.config_path.read_bytes() == before

    def fail(*_args):
        raise OSError("injected atomic failure")

    monkeypatch.setattr(persistence, "_atomic_write", fail)
    with pytest.raises(OSError, match="injected atomic failure"):
        ws.set("ui.theme", "light")
    assert ws.config_path.read_bytes() == before


@pytest.mark.parametrize(
    "key,value,broker_generation",
    [
        ("ui.theme", "light", 1),
        ("services.connection_epoch", 1, 1),
        ("llm.model", "fixture", 1),
        ("openalgo.telegram_username", "fixture-user", 1),
        ("openalgo.host", "https://fixture.invalid", 2),
        ("openalgo.port", 9000, 2),
        ("openalgo.ws_port", 9001, 2),
        ("openalgo.api_key", "fixture-key", 2),
        ("openalgo.unknown", True, 2),
        ("brokers.execution.default", "fixture:account", 2),
        ("brokers.account_acls.fixture.account", ["operator"], 2),
        ("brokers.data.ticks", "fixture:account", 2),
    ],
)
def test_only_classified_broker_authority_changes_advance_broker_generation(tmp_path, key, value, broker_generation):
    ws = Workspace(tmp_path)
    ws.initialise()
    ws.set(key, value)
    current = json.loads(ws.config_path.read_text())
    assert current["workspace_generation"] == 2
    assert current["broker_authority_generation"] == broker_generation


@pytest.mark.parametrize("field,key", [("workspace_generation", "label"), ("broker_authority_generation", "brokers.x")])
def test_counter_exhaustion_fails_without_mutation(tmp_path, field, key):
    config = _current()
    config[field] = _MAX
    path = _seed(tmp_path, config)
    ws = Workspace(tmp_path)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ws.set(key, "changed")
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "services",
    [
        None,
        [],
        {},
        {**_SERVICES, "connections": {}},
        {**_SERVICES, "routing": []},
        {**_SERVICES, "connection_epoch": False},
        {**_SERVICES, "connection_epoch": -1},
        {**_SERVICES, "connection_epoch": _MAX + 1},
    ],
)
def test_malformed_current_services_rejected_on_every_snapshot_read(tmp_path, services):
    config = _current()
    config["services"] = services
    path = _seed(tmp_path, config)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persistence.read_workspace_snapshot(tmp_path)
    assert path.read_bytes() == before


def test_corrupt_current_workspace_load_fails_without_default_fallback(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text('{"version":"1.3.0",broken')
    before = path.read_bytes()
    with pytest.raises(json.JSONDecodeError):
        Workspace(tmp_path)
    assert path.read_bytes() == before


def test_caller_cannot_use_boolean_generation_as_expected_version(tmp_path):
    _seed(tmp_path, _current())
    forged = persistence.WorkspaceVersion(UUID(_INSTANCE), True)
    with pytest.raises(ValueError):
        persistence.compare_and_swap_workspace(tmp_path, forged, lambda config: config.update(label="changed"))


def test_noop_never_replaces_the_document(tmp_path, monkeypatch):
    ws = Workspace(tmp_path)
    ws.initialise()

    def forbidden_write(*_args):
        pytest.fail("no-op reached atomic replacement")

    monkeypatch.setattr(persistence, "_atomic_write", forbidden_write)
    ws.save()
    ws.update(lambda _config: None)


def test_rejected_cas_never_migrates_a_restored_legacy_file(tmp_path):
    ws = Workspace(tmp_path)
    ws.initialise()
    snapshot = persistence.read_workspace_snapshot(tmp_path)
    path = _seed(tmp_path, {"version": "1.2.0", "extension": "restored"})
    before = path.read_bytes()
    with pytest.raises(persistence.WorkspaceVersionConflict):
        persistence.compare_and_swap_workspace(tmp_path, snapshot.version, lambda config: config.update(label="stale"))
    assert path.read_bytes() == before
    assert not (tmp_path / "workspace.1.2.0.bak.json").exists()


def test_snapshot_freezes_nested_mapping_and_tuple_inputs():
    source = {"value": ["original"]}
    config = MappingProxyType({"nested": (MappingProxyType(source),)})
    snapshot = persistence.WorkspaceSnapshot(config, None)
    source["value"].append("mutated")
    assert tuple(snapshot.config["nested"][0]["value"]) == ("original",)


def test_workspace_load_io_failure_does_not_return_defaults(tmp_path, monkeypatch):
    ws = Workspace(tmp_path)
    ws.initialise()

    def fail(_path):
        raise OSError("injected read failure")

    monkeypatch.setattr(persistence, "_run_migrations_locked", fail)
    with pytest.raises(OSError, match="injected read failure"):
        ws.load()


@pytest.mark.parametrize("malformed", [None, [], 1, {"version": []}])
def test_existing_nonobject_cas_cannot_be_mistaken_for_absence(tmp_path, malformed):
    config = _current()
    _seed(tmp_path, config)
    snapshot = persistence.read_workspace_snapshot(tmp_path)
    path = _seed(tmp_path, malformed)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        persistence.compare_and_swap_workspace(tmp_path, snapshot.version, lambda item: item.update(label="changed"))
    assert path.read_bytes() == before
