# packages/core/tests/test_user_manager.py
"""Tests for multi-user management scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest

from packages.core.src.user_manager import UserManager


class TestCreateUser:
    """User creation and validation."""

    def test_create_user_returns_dict(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        user = mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        assert user["username"] == "alice"
        assert user["email"] == "alice@example.com"
        assert user["role"] == "trader"
        assert user["is_active"] is True
        assert "password_hash" not in user

    def test_create_user_with_role(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        user = mgr.create_user("bob", "Str0ng!Pass", "bob@example.com", role="admin")
        assert user["role"] == "admin"

    def test_duplicate_username_rejected(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        with pytest.raises(RuntimeError, match="already exists"):
            mgr.create_user("alice", "An0therP@ss!", "alice2@example.com")

    def test_weak_password_rejected(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        with pytest.raises(ValueError, match="minimum 8"):
            mgr.create_user("alice", "short", "alice@example.com")

    def test_invalid_role_rejected(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        with pytest.raises(ValueError, match="Invalid role"):
            mgr.create_user("alice", "Str0ng!Pass", "alice@example.com", role="superadmin")

    def test_short_username_rejected(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        with pytest.raises(ValueError, match="3-32 characters"):
            mgr.create_user("ab", "Str0ng!Pass", "ab@example.com")


class TestGetUser:
    """User retrieval."""

    def test_get_existing_user(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        user = mgr.get_user("alice")
        assert user is not None
        assert user["username"] == "alice"

    def test_get_nonexistent_user_returns_none(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        assert mgr.get_user("nobody") is None


class TestListUsers:
    """User listing."""

    def test_list_users_empty(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        assert mgr.list_users() == []

    def test_list_users_returns_all(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        mgr.create_user("bob", "Str0ng!Pass", "bob@example.com", role="admin")
        users = mgr.list_users()
        assert len(users) == 2
        names = {u["username"] for u in users}
        assert names == {"alice", "bob"}


class TestUpdateUser:
    """User updates."""

    def test_update_email(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        assert mgr.update_user("alice", email="newalice@example.com") is True
        user = mgr.get_user("alice")
        assert user is not None
        assert user["email"] == "newalice@example.com"

    def test_update_role(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        mgr.update_user("alice", role="viewer")
        user = mgr.get_user("alice")
        assert user is not None
        assert user["role"] == "viewer"

    def test_update_nonexistent_user(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        assert mgr.update_user("nobody", email="x@x.com") is False

    def test_update_invalid_role_rejected(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        with pytest.raises(ValueError, match="Invalid role"):
            mgr.update_user("alice", role="superadmin")


class TestDeleteUser:
    """Soft deletion."""

    def test_delete_user_soft_deletes(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        assert mgr.delete_user("alice") is True
        user = mgr.get_user("alice")
        assert user is not None
        assert user["is_active"] is False

    def test_delete_nonexistent_user(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        assert mgr.delete_user("nobody") is False


class TestVerifyPassword:
    """Password verification."""

    def test_correct_password(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        assert mgr.verify_password("alice", "Str0ng!Pass") is True

    def test_wrong_password(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        assert mgr.verify_password("alice", "WrongPassword!") is False

    def test_inactive_user_cannot_authenticate(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        mgr.create_user("alice", "Str0ng!Pass", "alice@example.com")
        mgr.delete_user("alice")  # soft-delete
        assert mgr.verify_password("alice", "Str0ng!Pass") is False

    def test_nonexistent_user_returns_false(self, tmp_path: Path):
        mgr = UserManager(db_path=tmp_path / "users.db")
        assert mgr.verify_password("nobody", "anything") is False
