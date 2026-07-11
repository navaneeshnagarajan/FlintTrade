"""Tests for FlintTrade workspace configuration."""

import json
import platform
from pathlib import Path

import pytest



class TestWorkspaceResolution:
    """Test workspace directory resolution across platforms."""

    def test_flinttrade_home_env_override(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_WORKSPACE_DIR", raising=False)
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "custom"))
        from flinttrade_core.workspace import Workspace
        ws = Workspace()
        assert ws.workspace_dir == (tmp_path / "custom").resolve()

    def test_workspace_dir_env_wins_over_home_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "home"))
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
        from flinttrade_core.workspace import Workspace, workspace_dir
        ws = Workspace()
        assert ws.workspace_dir == workspace_dir()
        assert ws.workspace_dir == (tmp_path / "workspace").resolve()

    def test_default_linux_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / ".flinttrade"

    def test_default_darwin_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / "Library" / "Application Support" / "flinttrade"

    def test_default_windows_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.setenv("APPDATA", "/fake/appdata")
        from flinttrade_core.workspace import _default_home
        result = _default_home()
        assert result == Path("/fake/appdata/flinttrade")


class TestWorkspaceInit:
    """Test workspace initialization and directory creation."""

    def test_initialize_creates_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "ws"))
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.is_initialized
        assert ws.config_path.exists()
        assert ws.fast_data_dir.exists()
        assert ws.archive_dir.exists()
        assert ws.log_dir.exists()

    def test_initialize_writes_workspace_json(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        with open(ws.config_path) as f:
            config = json.load(f)
        assert config["initialized"] is True
        assert config["version"] == WORKSPACE_VERSION
        assert "modules" in config
        assert "storage" in config

    def test_not_initialized_before_init(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "empty")
        assert not ws.is_initialized

    def test_cli_provision_master_password_creates_hardened_file(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.secure_file import assert_hardened
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()

        assert _provision_master_password(ws) is True
        password_file = ws.workspace_dir / "master_password"
        assert password_file.read_text(encoding="utf-8").strip()
        ok, reason = assert_hardened(password_file)
        assert ok, reason

    def test_cli_provision_master_password_never_overwrites_existing_secret(self, tmp_path):
        from flinttrade_core.cli import _provision_master_password
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        password_file = ws.workspace_dir / "master_password"
        password_file.write_text("operator-owned-secret", encoding="utf-8")

        assert _provision_master_password(ws) is False
        assert password_file.read_text(encoding="utf-8") == "operator-owned-secret"


class TestWorkspaceLoadSave:
    """Test load/save/get/set operations."""

    def test_save_and_load(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise({"version": WORKSPACE_VERSION, "initialized": True, "data": "hello"})
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.load()["data"] == "hello"

    def test_get_dot_notation(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.get("ui.theme") == "dark"
        assert ws.get("sebi.max_ops_per_second") == 10

    def test_get_missing_key_returns_default(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        assert ws.get("nonexistent.key", "fallback") == "fallback"

    def test_set_and_persist(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        ws.set("ui.theme", "light")
        # Reload from disk
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.get("ui.theme") == "light"

    def test_stale_workspace_instances_do_not_clobber_unrelated_updates(self, tmp_path):
        from flinttrade_core.workspace import Workspace

        first = Workspace(home_dir=tmp_path / "ws")
        first.initialise()
        stale = Workspace(home_dir=tmp_path / "ws")

        first.set("ui.theme", "light")
        stale.set("llm.model", "local-model")

        reloaded = Workspace(home_dir=tmp_path / "ws")
        assert reloaded.get("ui.theme") == "light"
        assert reloaded.get("llm.model") == "local-model"

    def test_failed_atomic_save_preserves_previous_workspace(self, tmp_path, monkeypatch):
        from flinttrade_core import workspace_migrations
        from flinttrade_core.workspace import Workspace

        workspace = Workspace(home_dir=tmp_path / "ws")
        workspace.initialise()
        before = workspace.config_path.read_text(encoding="utf-8")
        workspace._config["ui"]["theme"] = "light"

        monkeypatch.setattr(
            workspace_migrations.os,
            "replace",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("rename failed")),
        )

        with pytest.raises(OSError, match="rename failed"):
            workspace.save()

        assert workspace.config_path.read_text(encoding="utf-8") == before

    def test_path_expansion(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        # fast_data_dir should be an absolute path (~ expanded)
        assert ws.fast_data_dir.is_absolute()
        assert "~" not in str(ws.fast_data_dir)

    def test_explicit_home_keeps_default_storage_inside_workspace(self, tmp_path):
        from flinttrade_core.workspace import Workspace

        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()

        assert ws.fast_data_dir == (tmp_path / "ws" / "data").resolve()
        assert ws.archive_dir == (tmp_path / "ws" / "archive").resolve()

    def test_ensure_directories(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws._config = {"storage": {"fast": str(tmp_path / "ws" / "data"), "archive": str(tmp_path / "ws" / "archive")}}
        ws.ensure_directories()
        assert (tmp_path / "ws" / "data").exists()
        assert (tmp_path / "ws" / "archive").exists()

    def test_as_dict_returns_copy(self, tmp_path):
        from flinttrade_core.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialise()
        d = ws.as_dict()
        d["version"] = "modified"
        assert ws.get("version") != "modified"

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        from flinttrade_core.workspace_migrations import WORKSPACE_VERSION
        from flinttrade_core.workspace import Workspace
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "workspace.json").write_text("not valid json{{{")
        ws = Workspace(home_dir=ws_dir)
        assert ws.get("version") == WORKSPACE_VERSION  # fell back to current defaults
