"""Inert migration uses real installation locks/journal and synthetic authorities."""

import importlib
from uuid import uuid4

import pytest


def recovery():
    return importlib.import_module("flinttrade_core.openalgo_migration_recovery")


@pytest.fixture
def owner(tmp_path, backend_lease_proof):
    from flinttrade_core.account_mutation_journal import AccountMutationJournal
    from flinttrade_core.account_mutation_locks import CoordinatorOperationLock
    from flinttrade_core.installation_state import InstallationState

    installation = InstallationState(tmp_path / "installation")
    with CoordinatorOperationLock(installation).hold(backend_lease_proof) as token:
        with AccountMutationJournal(installation, installation.root / "account-coordinator", token=token) as journal:
            yield installation, token, journal


def test_source_index_exists_and_allocates_once_outside_replaceable_targets(owner, tmp_path):
    module_name = "flinttrade_core.openalgo_migration_recovery"
    assert importlib.util.find_spec(module_name), "installation migration source index is missing"
    installation, token, journal = owner
    first = recovery().OpenAlgoMigrationIndex(installation, journal, token=token).operation_id()
    assert first.version == 4
    assert recovery().OpenAlgoMigrationIndex(installation, journal, token=token).operation_id() == first
    assert not list(tmp_path.glob("workspace*"))


@pytest.mark.parametrize("damage", ["remove", "replace", "symlink", "foreign"])
def test_source_index_loss_or_replacement_cannot_reallocate(owner, tmp_path, damage):
    installation, token, journal = owner
    module = recovery()
    index = module.OpenAlgoMigrationIndex(installation, journal, token=token)
    index.operation_id()
    path = installation.root / ".openalgo-migration-index.json"
    previous = path.read_text()
    path.unlink()
    if damage == "replace":
        path.write_text(previous)
        path.chmod(0o600)
    elif damage == "symlink":
        other = tmp_path / "foreign.json"
        other.write_text(previous)
        other.chmod(0o600)
        path.symlink_to(other)
    elif damage == "foreign":
        from flinttrade_core.secure_file import HeldOwnerDirectory
        with HeldOwnerDirectory(installation.root) as directory:
            directory.write_text(path.name, previous.replace(str(installation.installation_id), str(uuid4())))
    with pytest.raises(module.OpenAlgoMigrationUnavailable):
        module.OpenAlgoMigrationIndex(installation, journal, token=token).operation_id()


def test_source_index_revalidates_expired_coordinator_scope(tmp_path, backend_lease_proof):
    from flinttrade_core.account_mutation_journal import AccountMutationJournal
    from flinttrade_core.account_mutation_locks import CoordinatorOperationLock
    from flinttrade_core.installation_state import InstallationState

    installation = InstallationState(tmp_path / "installation")
    with CoordinatorOperationLock(installation).hold(backend_lease_proof) as token:
        with AccountMutationJournal(installation, installation.root / "account-coordinator", token=token) as journal:
            index = recovery().OpenAlgoMigrationIndex(installation, journal, token=token)
            index.operation_id()
    with pytest.raises(recovery().OpenAlgoMigrationUnavailable):
        index.operation_id()
