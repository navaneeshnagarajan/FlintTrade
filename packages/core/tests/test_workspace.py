"""Tests for FlintTrade workspace configuration."""

import json
import platform
from pathlib import Path



class TestWorkspaceResolution:
    """Test workspace directory resolution across platforms."""

    def test_flinttrade_home_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "custom"))
        from packages.core.src.workspace import Workspace
        ws = Workspace()
        assert ws.workspace_dir == (tmp_path / "custom").resolve()

    def test_default_linux_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Linux")
        from packages.core.src.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / ".flinttrade"

    def test_default_darwin_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        from packages.core.src.workspace import _default_home
        result = _default_home()
        assert result == Path.home() / "Library" / "Application Support" / "flinttrade"

    def test_default_windows_path(self, monkeypatch):
        monkeypatch.delenv("FLINTTRADE_HOME", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        monkeypatch.setenv("APPDATA", "/fake/appdata")
        from packages.core.src.workspace import _default_home
        result = _default_home()
        assert result == Path("/fake/appdata/flinttrade")


class TestWorkspaceInit:
    """Test workspace initialization and directory creation."""

    def test_initialize_creates_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLINTTRADE_HOME", str(tmp_path / "ws"))
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        assert ws.is_initialized
        assert ws.config_path.exists()
        assert ws.fast_data_dir.exists()
        assert ws.archive_dir.exists()
        assert ws.log_dir.exists()

    def test_initialize_writes_workspace_json(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        with open(ws.config_path) as f:
            config = json.load(f)
        assert config["initialized"] is True
        assert config["version"] == "0.1.0-alpha"
        assert "modules" in config
        assert "storage" in config

    def test_not_initialized_before_init(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "empty")
        assert not ws.is_initialized


class TestWorkspaceLoadSave:
    """Test load/save/get/set operations."""

    def test_save_and_load(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize({"version": "test", "initialized": True, "data": "hello"})
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.load()["data"] == "hello"

    def test_get_dot_notation(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        assert ws.get("ui.theme") == "dark"
        assert ws.get("sebi.max_ops_per_second") == 10

    def test_get_missing_key_returns_default(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        assert ws.get("nonexistent.key", "fallback") == "fallback"

    def test_set_and_persist(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        ws.set("ui.theme", "light")
        # Reload from disk
        ws2 = Workspace(home_dir=tmp_path / "ws")
        assert ws2.get("ui.theme") == "light"

    def test_path_expansion(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        # fast_data_dir should be an absolute path (~ expanded)
        assert ws.fast_data_dir.is_absolute()
        assert "~" not in str(ws.fast_data_dir)

    def test_ensure_directories(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws._config = {"storage": {"fast": str(tmp_path / "ws" / "data"), "archive": str(tmp_path / "ws" / "archive")}}
        ws.ensure_directories()
        assert (tmp_path / "ws" / "data").exists()
        assert (tmp_path / "ws" / "archive").exists()

    def test_as_dict_returns_copy(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws = Workspace(home_dir=tmp_path / "ws")
        ws.initialize()
        d = ws.as_dict()
        d["version"] = "modified"
        assert ws.get("version") != "modified"

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        from packages.core.src.workspace import Workspace
        ws_dir = tmp_path / "ws"
        ws_dir.mkdir()
        (ws_dir / "workspace.json").write_text("not valid json{{{")
        ws = Workspace(home_dir=ws_dir)
        assert ws.get("version") == "0.1.0-alpha"  # fell back to defaults
