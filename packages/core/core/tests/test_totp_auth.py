# packages/core/core/tests/test_totp_auth.py
"""Tests for TOTPAuth — user-facing TOTP 2FA.

Coverage:
- Secret generation: returns valid base32, correct backup code count,
  uniqueness, regeneration replaces old secret and codes
- Provisioning URI: format, secret presence, issuer, user label
- Token verification: valid/invalid/wrong user/disabled
- Backup code consumption: valid, one-time use, decrements count
- Disable flow: valid token disables, invalid token rejected, re-enable
- QR code SVG generation
- Persistence across DB reopen
- Workspace resolution and the paired legacy migration (store + install key)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pyotp
import pytest

from flinttrade_core import totp_auth
from flinttrade_core.totp_auth import TOTPAuth, _BACKUP_CODE_COUNT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _never_probe_the_real_home(monkeypatch, tmp_path: Path) -> None:
    """Point both legacy probes at a temp directory for every test in the file.

    Without this the suite's first ``generate_secret`` call used to create a
    real ``totp_install_key`` in the developer's home directory. The workspace
    path swap already fixes that (pytest always exports
    ``FLINTTRADE_WORKSPACE_DIR``); this fixture makes it structural, so no test
    — however it is reordered by pytest-randomly, and whatever it does to the
    environment — can reach the real home directory.
    """
    legacy = tmp_path / "legacy-home" / ".flinttrade"
    monkeypatch.setattr(totp_auth, "_legacy_db_path", lambda: legacy / "totp_auth.duckdb")
    monkeypatch.setattr(totp_auth, "_legacy_install_key_path", lambda: legacy / "totp_install_key")


@pytest.fixture()
def auth(tmp_path: Path) -> TOTPAuth:
    """Fresh TOTPAuth backed by a temp DuckDB file."""
    instance = TOTPAuth(db_path=tmp_path / "totp.duckdb")
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Secret generation
# ---------------------------------------------------------------------------


def test_generate_returns_valid_base32_secret(auth: TOTPAuth) -> None:
    """generate_secret returns a secret that pyotp accepts."""
    secret, _ = auth.generate_secret("u1")
    totp = pyotp.TOTP(secret)
    assert len(totp.now()) == 6


def test_generate_returns_correct_backup_code_count(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u2")
    assert len(codes) == _BACKUP_CODE_COUNT


def test_backup_codes_are_8_char_uppercase_hex(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u3")
    for code in codes:
        assert len(code) == 8
        assert code == code.upper()
        int(code, 16)  # Raises ValueError if not valid hex


def test_backup_codes_are_unique(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("u4")
    assert len(set(codes)) == len(codes)


def test_regenerating_replaces_secret(auth: TOTPAuth) -> None:
    secret1, _ = auth.generate_secret("u5")
    secret2, _ = auth.generate_secret("u5")
    assert secret1 != secret2


def test_regenerating_replaces_backup_codes(auth: TOTPAuth) -> None:
    _, codes1 = auth.generate_secret("u6")
    _, codes2 = auth.generate_secret("u6")
    assert set(codes1).isdisjoint(set(codes2))


def test_is_enabled_true_after_generate(auth: TOTPAuth) -> None:
    auth.generate_secret("u7")
    assert auth.is_enabled("u7") is True


def test_is_enabled_false_for_unknown_user(auth: TOTPAuth) -> None:
    assert auth.is_enabled("nonexistent") is False


# ---------------------------------------------------------------------------
# Provisioning URI
# ---------------------------------------------------------------------------


def test_provisioning_uri_starts_with_otpauth(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri1")
    uri = auth.provisioning_uri("uri1", secret)
    assert uri.startswith("otpauth://totp/")


def test_provisioning_uri_contains_secret(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri2")
    uri = auth.provisioning_uri("uri2", secret)
    assert f"secret={secret}" in uri


def test_provisioning_uri_contains_issuer(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("uri3")
    uri = auth.provisioning_uri("uri3", secret, issuer="FlintTrade")
    assert "FlintTrade" in uri


def test_provisioning_uri_contains_user_id(auth: TOTPAuth) -> None:
    user_id = "trader@example.com"
    secret, _ = auth.generate_secret(user_id)
    uri = auth.provisioning_uri(user_id, secret)
    assert "trader" in uri


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def test_valid_token_returns_true(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("vt1")
    token = pyotp.TOTP(secret).now()
    assert auth.verify_token("vt1", token) is True


def test_invalid_token_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt2")
    assert auth.verify_token("vt2", "000000") is False


def test_wrong_user_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt3")
    assert auth.verify_token("nonexistent_user", "123456") is False


def test_token_after_disable_returns_false(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("vt4")
    token = pyotp.TOTP(secret).now()
    auth.disable("vt4", token)
    # After disable, even a fresh token must fail
    fresh_token = pyotp.TOTP(secret).now()
    assert auth.verify_token("vt4", fresh_token) is False


def test_token_wrong_length_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("vt5")
    assert auth.verify_token("vt5", "12345") is False


# ---------------------------------------------------------------------------
# Backup code consumption
# ---------------------------------------------------------------------------


def test_valid_backup_code_returns_true(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc1")
    assert auth.consume_backup_code("bc1", codes[0]) is True


def test_same_backup_code_cannot_be_used_twice(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc2")
    auth.consume_backup_code("bc2", codes[0])
    assert auth.consume_backup_code("bc2", codes[0]) is False


def test_invalid_backup_code_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("bc3")
    assert auth.consume_backup_code("bc3", "FFFFFFFF") is False


def test_remaining_backup_codes_decrements_on_consume(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc4")
    before = auth.remaining_backup_codes("bc4")
    auth.consume_backup_code("bc4", codes[0])
    assert auth.remaining_backup_codes("bc4") == before - 1


def test_all_backup_codes_usable_exactly_once(auth: TOTPAuth) -> None:
    _, codes = auth.generate_secret("bc5")
    for code in codes:
        assert auth.consume_backup_code("bc5", code) is True
    assert auth.remaining_backup_codes("bc5") == 0


def test_remaining_backup_codes_zero_for_unknown_user(auth: TOTPAuth) -> None:
    assert auth.remaining_backup_codes("nobody") == 0


# ---------------------------------------------------------------------------
# Disable flow
# ---------------------------------------------------------------------------


def test_disable_with_valid_token_returns_true(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d1")
    token = pyotp.TOTP(secret).now()
    assert auth.disable("d1", token) is True


def test_disable_with_invalid_token_returns_false(auth: TOTPAuth) -> None:
    auth.generate_secret("d2")
    assert auth.disable("d2", "000000") is False


def test_is_enabled_false_after_disable(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d3")
    token = pyotp.TOTP(secret).now()
    auth.disable("d3", token)
    assert auth.is_enabled("d3") is False


def test_is_enabled_true_after_regenerate_following_disable(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("d4")
    token = pyotp.TOTP(secret).now()
    auth.disable("d4", token)
    auth.generate_secret("d4")
    assert auth.is_enabled("d4") is True


# ---------------------------------------------------------------------------
# QR code generation
# ---------------------------------------------------------------------------


def test_qr_code_svg_returns_svg_markup(auth: TOTPAuth) -> None:
    pytest.importorskip("qrcode", reason="qrcode[svg] not installed")
    secret, _ = auth.generate_secret("qr1")
    uri = auth.provisioning_uri("qr1", secret)
    svg = auth.qr_code_svg(uri)
    assert "svg" in svg.lower()


def test_qr_code_svg_raises_import_error_without_qrcode(auth: TOTPAuth) -> None:
    secret, _ = auth.generate_secret("qr2")
    uri = auth.provisioning_uri("qr2", secret)
    with patch.dict(sys.modules, {"qrcode": None, "qrcode.image.svg": None}):
        with pytest.raises(ImportError, match="qrcode"):
            auth.qr_code_svg(uri)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_secret_persists_across_db_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist.duckdb"
    auth1 = TOTPAuth(db_path=db)
    user_id = "persist_user"
    secret, _ = auth1.generate_secret(user_id)
    auth1.close()

    auth2 = TOTPAuth(db_path=db)
    token = pyotp.TOTP(secret).now()
    assert auth2.verify_token(user_id, token) is True
    auth2.close()


def test_backup_codes_persist_across_db_reopen(tmp_path: Path) -> None:
    db = tmp_path / "persist2.duckdb"
    auth1 = TOTPAuth(db_path=db)
    user_id = "persist_bc"
    _, codes = auth1.generate_secret(user_id)
    auth1.close()

    auth2 = TOTPAuth(db_path=db)
    assert auth2.consume_backup_code(user_id, codes[1]) is True
    auth2.close()


# ---------------------------------------------------------------------------
# Workspace resolution + the paired legacy migration
# ---------------------------------------------------------------------------


def _seed_legacy_pair(legacy_db: Path, legacy_key: Path, key_material: str, monkeypatch) -> str:
    """Create a legacy TOTP store enrolled under *key_material*.

    Enrolment runs with ``FLINTTRADE_TOTP_KEY`` pinned to *key_material* so the
    resulting ciphertext is byte-for-byte what the install-key branch produces
    once the key file has travelled across — that is exactly the pairing the
    migration must preserve.

    Args:
        legacy_db: Path the legacy DuckDB store is created at.
        legacy_key: Path the legacy install key is written to.
        key_material: Secret written to the key file and used for enrolment.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The base32 TOTP secret enrolled for user ``legacy_user``.
    """
    legacy_db.parent.mkdir(parents=True, exist_ok=True)
    legacy_key.write_text(key_material, encoding="utf-8")
    monkeypatch.setenv("FLINTTRADE_TOTP_KEY", key_material)
    seeder = TOTPAuth(db_path=legacy_db)
    try:
        secret, _ = seeder.generate_secret("legacy_user")
    finally:
        seeder.close()
    monkeypatch.delenv("FLINTTRADE_TOTP_KEY", raising=False)
    return secret


@pytest.mark.unit
class TestWorkspaceResolution:
    """``totp_auth.duckdb`` and ``totp_install_key`` resolve under the workspace.

    The two files are one cryptographic unit: the key derives the Fernet key
    that decrypts every enrolled secret, so a store that arrives without its
    matching key is a permanent 2FA lockout rather than a lost preference.
    """

    @staticmethod
    def _default_workspace(monkeypatch, tmp_path: Path) -> Path:
        """Make ``workspace_dir()`` resolve to a tmp dir with no env override.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
            tmp_path: Per-test temporary directory.

        Returns:
            The directory ``workspace_dir()`` will now return.
        """
        import flinttrade_core.workspace as ws

        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.delenv("FLINTTRADE_TOTP_KEY", raising=False)
        workspace = tmp_path / "workspace"
        monkeypatch.setattr(ws, "_default_home", lambda: workspace)
        return workspace

    @staticmethod
    def _legacy_pair(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
        """Redirect both legacy probes into tmp_path and return their paths."""
        legacy_dir = tmp_path / "legacy" / ".flinttrade"
        legacy_db = legacy_dir / "totp_auth.duckdb"
        legacy_key = legacy_dir / "totp_install_key"
        monkeypatch.setattr(totp_auth, "_legacy_db_path", lambda: legacy_db)
        monkeypatch.setattr(totp_auth, "_legacy_install_key_path", lambda: legacy_key)
        return legacy_db, legacy_key

    def test_import_time_constant_is_gone(self) -> None:
        """``_DEFAULT_DB_PATH`` froze the location before pytest could redirect it."""
        assert not hasattr(totp_auth, "_DEFAULT_DB_PATH")

    def test_import_creates_no_directories(self, monkeypatch, tmp_path: Path) -> None:
        """Re-importing the module must resolve nothing and touch no disk."""
        import importlib

        workspace = self._default_workspace(monkeypatch, tmp_path)
        importlib.reload(totp_auth)

        assert not workspace.exists()

    def test_install_key_no_longer_lands_in_the_real_home(self) -> None:
        """The suite used to create a real ``~/.flinttrade/totp_install_key``.

        Under pytest ``FLINTTRADE_WORKSPACE_DIR`` is always exported, so the
        key must now be written inside the throw-away pytest workspace.
        """
        from flinttrade_core.workspace import legacy_dotdir, workspace_dir

        key_path = totp_auth._install_key_path()

        assert key_path == workspace_dir() / "totp_install_key"
        assert key_path.parent != legacy_dotdir()

    def test_default_construction_writes_the_key_inside_the_workspace(self, monkeypatch, tmp_path: Path) -> None:
        """The end-to-end proof: enrolment persists its key under the workspace."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        self._legacy_pair(monkeypatch, tmp_path)

        instance = TOTPAuth()
        try:
            instance.generate_secret("key_user")
        finally:
            instance.close()

        assert (workspace / "totp_auth.duckdb").exists()
        assert (workspace / "totp_install_key").exists()

    def test_explicit_store_keeps_its_key_beside_itself(self, monkeypatch, tmp_path: Path) -> None:
        """A caller-supplied store enrols against a key in its own directory.

        The store and its key are one cryptographic unit, so the pair must not
        be split across two directories — and resolving the key beside the
        store is what keeps the legacy probe out of an explicit path.

        ``FLINTTRADE_TOTP_KEY`` is cleared explicitly: it supersedes the install
        key entirely, so with it set no key file is ever written and this
        assertion would depend on which other modules an xdist worker happened
        to import first.
        """
        monkeypatch.delenv("FLINTTRADE_TOTP_KEY", raising=False)
        instance = TOTPAuth(db_path=tmp_path / "totp.duckdb")
        try:
            instance.generate_secret("key_user")
        finally:
            instance.close()

        assert (tmp_path / "totp_install_key").exists()

    def test_fresh_install_resolves_under_workspace(self, monkeypatch, tmp_path: Path) -> None:
        """No legacy pair: both paths are the workspace ones and nothing is copied."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        self._legacy_pair(monkeypatch, tmp_path)

        assert totp_auth._default_db_path() == workspace / "totp_auth.duckdb"
        assert totp_auth._install_key_path() == workspace / "totp_install_key"
        assert not (workspace / "totp_auth.duckdb").exists()
        assert not (workspace / "totp_install_key").exists()

    def test_legacy_pair_travels_together_and_is_retained(self, monkeypatch, tmp_path: Path) -> None:
        """Both halves are copied across, and the legacy pair stays as a backup."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        resolved = totp_auth._default_db_path()

        assert resolved == workspace / "totp_auth.duckdb"
        assert resolved.exists()
        assert (workspace / "totp_install_key").read_text(encoding="utf-8") == "install-key-material"
        # Copy, not move — the legacy pair stays behind as a backup.
        assert legacy_db.exists()
        assert legacy_key.exists()

    def test_migrated_pair_still_verifies_a_live_token(self, monkeypatch, tmp_path: Path) -> None:
        """The whole point: an enrolled authenticator keeps working after upgrade."""
        self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        secret = _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        migrated = TOTPAuth()
        try:
            assert migrated.verify_token("legacy_user", pyotp.TOTP(secret).now()) is True
        finally:
            migrated.close()

    def test_wal_sidecar_travels_with_the_store(self, monkeypatch, tmp_path: Path) -> None:
        """A DuckDB ``.wal`` left by an unclean shutdown must not be stranded."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        legacy_db.with_name("totp_auth.duckdb.wal").write_bytes(b"legacy-wal")

        totp_auth._default_db_path()

        assert (workspace / "totp_auth.duckdb.wal").exists()

    def test_store_with_nothing_enrolled_migrates_without_verification(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """An un-enrolled store has no pairing to prove, so it must not be deleted.

        Verification exists to catch a mispaired key, not to judge the store's
        integrity — treating "no secrets table" as a failure would discard a
        perfectly good migration.
        """
        import duckdb

        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        legacy_db.parent.mkdir(parents=True, exist_ok=True)
        duckdb.connect(str(legacy_db)).close()
        legacy_key.write_text("install-key-material", encoding="utf-8")

        totp_auth._default_db_path()

        assert (workspace / "totp_auth.duckdb").exists()
        assert (workspace / "totp_install_key").exists()

    def test_half_migrated_workspace_skips_both_halves(self, monkeypatch, tmp_path: Path) -> None:
        """Exactly one target present: never guess which key decrypts which store."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "totp_install_key").write_text("a-different-key", encoding="utf-8")

        totp_auth._default_db_path()

        assert not (workspace / "totp_auth.duckdb").exists()
        assert (workspace / "totp_install_key").read_text(encoding="utf-8") == "a-different-key"
        assert legacy_db.exists()

    def test_half_present_legacy_state_skips_both_halves(self, monkeypatch, tmp_path: Path) -> None:
        """A legacy store with no legacy key is not migrated on a guess either."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        legacy_key.unlink()

        totp_auth._default_db_path()

        assert not (workspace / "totp_auth.duckdb").exists()
        assert not (workspace / "totp_install_key").exists()

    def test_existing_workspace_pair_is_never_clobbered(self, monkeypatch, tmp_path: Path) -> None:
        """Both halves already present: the workspace pair wins untouched."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "totp_auth.duckdb").write_bytes(b"already-here")
        (workspace / "totp_install_key").write_text("already-here-key", encoding="utf-8")

        totp_auth._default_db_path()

        assert (workspace / "totp_auth.duckdb").read_bytes() == b"already-here"
        assert (workspace / "totp_install_key").read_text(encoding="utf-8") == "already-here-key"

    def test_mismatched_pair_is_rolled_back_and_raises(self, monkeypatch, tmp_path: Path) -> None:
        """A copied key that cannot decrypt the copied store is not left behind.

        Publishing an unverified pair would lock the operator out of their own
        account permanently, and the ``target exists`` idempotency marker would
        stop any later boot from repairing it.
        """
        from flinttrade_core.workspace import WorkspaceStateMigrationError

        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "enrolled-under-this-key", monkeypatch)
        # The key file no longer matches the ciphertext in the store.
        legacy_key.write_text("a-completely-different-key", encoding="utf-8")

        with pytest.raises(WorkspaceStateMigrationError, match="does not decrypt"):
            totp_auth._default_db_path()

        assert not (workspace / "totp_auth.duckdb").exists()
        assert not (workspace / "totp_auth.duckdb.wal").exists()
        assert not (workspace / "totp_install_key").exists()
        # The legacy pair is retained, so the operator can still recover.
        assert legacy_db.exists()
        assert legacy_key.exists()

    def test_explicit_app_key_skips_pair_verification(self, monkeypatch, tmp_path: Path) -> None:
        """With ``FLINTTRADE_TOTP_KEY`` in force the install key decrypts nothing."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "enrolled-under-this-key", monkeypatch)
        legacy_key.write_text("a-completely-different-key", encoding="utf-8")
        monkeypatch.setenv("FLINTTRADE_TOTP_KEY", "enrolled-under-this-key")

        totp_auth._default_db_path()

        assert (workspace / "totp_auth.duckdb").exists()
        assert (workspace / "totp_install_key").exists()

    def test_migration_locks_land_inside_the_workspace(self, monkeypatch, tmp_path: Path) -> None:
        """Root-level targets must not drop locks in the parent of the workspace."""
        import flinttrade_core.workspace as ws

        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        seen: list[Path] = []
        real_lock = ws.FileLock

        def _recording_lock(path, *args, **kwargs):  # noqa: ANN001, ANN202
            seen.append(Path(path))
            return real_lock(path, *args, **kwargs)

        monkeypatch.setattr(ws, "FileLock", _recording_lock)
        totp_auth._default_db_path()

        # One lock for the whole pair: the halves are staged and published by
        # the module itself, so there is nothing for a per-file lock to do.
        assert seen == [workspace / ".totp-migration.lock"]

    def test_environment_override_keeps_the_probe_inert(self, monkeypatch, tmp_path: Path) -> None:
        """``FLINTTRADE_WORKSPACE_DIR`` set: no copy, and both paths follow the override."""
        override = tmp_path / "override"
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(override))
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        assert totp_auth._default_db_path() == override.resolve() / "totp_auth.duckdb"
        assert not (override.resolve() / "totp_auth.duckdb").exists()

    def test_explicit_db_path_skips_the_probe(self, monkeypatch, tmp_path: Path) -> None:
        """An explicit ``db_path`` opens exactly that file and never migrates."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        explicit = tmp_path / "explicit" / "totp.duckdb"

        instance = TOTPAuth(db_path=explicit)
        try:
            assert instance._db_path == explicit
            assert explicit.exists()
        finally:
            instance.close()
        assert not (workspace / "totp_auth.duckdb").exists()

    def test_explicit_db_path_skips_the_probe_for_the_key_half_too(self, monkeypatch, tmp_path: Path) -> None:
        """Both halves of the pair skip the probe, not just the store.

        ``__init__`` bypassed ``_default_db_path()`` correctly, but the install
        key was still resolved through the probing path — so a caller who
        supplied an explicit path had the installer migrate their legacy
        directory anyway, contradicting the constructor's own contract.
        """
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        explicit = tmp_path / "explicit" / "totp.duckdb"

        instance = TOTPAuth(db_path=explicit)
        try:
            instance.generate_secret("explicit_user")
            assert instance._key_path == explicit.parent / "totp_install_key"
        finally:
            instance.close()

        assert (explicit.parent / "totp_install_key").exists()
        # Nothing was resolved under the workspace at all, so neither half of
        # the legacy pair was probed, copied, or published.
        assert not workspace.exists()
        assert legacy_db.exists()
        assert legacy_key.exists()

    def test_in_memory_store_borrows_the_workspace_key_without_probing(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """``:memory:`` has no directory of its own, and still must not probe."""
        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        instance = TOTPAuth(db_path=":memory:")
        try:
            assert instance._key_path == workspace / "totp_install_key"
        finally:
            instance.close()

        assert not (workspace / "totp_auth.duckdb").exists()
        assert not (workspace / "totp_install_key").exists()

    def test_failed_second_copy_leaves_neither_half_and_retries(self, monkeypatch, tmp_path: Path) -> None:
        """A copy that fails part-way must not publish half the pair.

        The install key used to be published the instant it was copied, so a
        store copy that then failed (a full disk, a lock timeout) left exactly
        one half in the workspace — and the "exactly one of the pair exists"
        guard would then skip BOTH halves on every later boot. That is a
        permanent 2FA lockout created by the very failure path meant to
        prevent one, with the legacy pair still sitting on disk.
        """
        import shutil

        from flinttrade_core.workspace import WorkspaceStateMigrationError

        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        secret = _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)

        genuine_copy = shutil.copy2
        failed: list[Path] = []

        def _fail_once_copying_the_store(source, destination, *args, **kwargs):  # noqa: ANN001, ANN202
            if Path(source) == legacy_db and not failed:
                failed.append(Path(source))
                raise OSError(28, "No space left on device")
            return genuine_copy(source, destination, *args, **kwargs)

        monkeypatch.setattr(totp_auth.shutil, "copy2", _fail_once_copying_the_store)

        with pytest.raises(WorkspaceStateMigrationError):
            totp_auth._default_db_path()

        assert failed, "the injected failure never fired"
        assert not (workspace / "totp_auth.duckdb").exists()
        assert not (workspace / "totp_install_key").exists()
        assert list(workspace.glob(".*.migrating*")) == []
        assert legacy_db.exists()
        assert legacy_key.exists()

        # The next run sees neither half, so it retries and completes.
        assert totp_auth._default_db_path() == workspace / "totp_auth.duckdb"
        assert (workspace / "totp_install_key").read_text(encoding="utf-8") == "install-key-material"
        migrated = TOTPAuth()
        try:
            assert migrated.verify_token("legacy_user", pyotp.TOTP(secret).now()) is True
        finally:
            migrated.close()

    def test_failed_publish_unpublishes_the_half_that_landed(self, monkeypatch, tmp_path: Path) -> None:
        """The second rename failing must take the first one back out again."""
        from flinttrade_core.workspace import WorkspaceStateMigrationError

        workspace = self._default_workspace(monkeypatch, tmp_path)
        legacy_db, legacy_key = self._legacy_pair(monkeypatch, tmp_path)
        _seed_legacy_pair(legacy_db, legacy_key, "install-key-material", monkeypatch)
        target_db = workspace / "totp_auth.duckdb"

        genuine_replace = Path.replace

        def _fail_publishing_the_store(self, target):  # noqa: ANN001, ANN202
            if Path(target) == target_db:
                raise OSError(5, "Input/output error")
            return genuine_replace(self, target)

        monkeypatch.setattr(Path, "replace", _fail_publishing_the_store)

        with pytest.raises(WorkspaceStateMigrationError):
            totp_auth._default_db_path()

        # The key half had already been renamed into place when the store's
        # rename failed; leaving it there is the lockout.
        assert not target_db.exists()
        assert not (workspace / "totp_install_key").exists()
        assert legacy_db.exists()
        assert legacy_key.exists()
