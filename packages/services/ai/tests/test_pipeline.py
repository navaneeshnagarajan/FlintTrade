"""Tests for SignalPipeline — init, EMA, fallback, latest signals."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


class TestSignalPipeline:
    """Test signal pipeline initialisation and helpers."""

    def test_init_defaults(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline(openalgo_host="http://localhost:5000")
        assert p.host == "http://localhost:5000"
        assert p.instruments is not None
        assert len(p.instruments) >= 2
        assert p.interval == "5m"

    def test_init_custom_instruments(self):
        from flinttrade_ai.pipeline import SignalPipeline

        instruments = [{"symbol": "RELIANCE", "exchange": "NSE"}]
        p = SignalPipeline(instruments=instruments)
        assert len(p.instruments) == 1
        assert p.instruments[0]["symbol"] == "RELIANCE"

    def test_init_uses_workspace_openalgo_settings(self, monkeypatch, tmp_path):
        from flinttrade_ai.pipeline import SignalPipeline
        from flinttrade_core.workspace import Workspace

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
        monkeypatch.delenv("OPENALGO_HOST", raising=False)

        workspace = Workspace()
        workspace.initialise()
        config = workspace.as_dict()
        config["openalgo"] = {
            "api_key": "workspace-ai-key",
            "host": "http://127.0.0.1:5003",
            "ws_port": 8767,
        }
        workspace.save(config)

        p = SignalPipeline()

        assert p.host == "http://127.0.0.1:5003"
        assert p.api_key == "workspace-ai-key"

    def test_fetch_bars_uses_injected_openalgo_client(self):
        from flinttrade_ai.pipeline import SignalPipeline

        class _Row:
            def model_dump(self):
                return {"timestamp": "2026-07-06", "close": 100.5}

        openalgo_client = MagicMock()
        openalgo_client.history = AsyncMock(return_value=[_Row()])
        openalgo_client.close = AsyncMock()
        p = SignalPipeline(openalgo_client=openalgo_client)

        rows = p.fetch_bars("RELIANCE", "NSE")

        assert rows == [{"timestamp": "2026-07-06", "close": 100.5}]
        openalgo_client.history.assert_awaited_once()
        openalgo_client.close.assert_not_awaited()

    def test_ema_basic(self):
        from flinttrade_ai.pipeline import SignalPipeline

        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        ema = SignalPipeline._ema(data, 3)
        assert len(ema) == 5
        assert ema[0] == 1.0
        # EMA should trend towards the data
        assert ema[-1] > ema[0]

    def test_ema_empty(self):
        from flinttrade_ai.pipeline import SignalPipeline

        assert SignalPipeline._ema([], 3) == []

    def test_ema_single(self):
        from flinttrade_ai.pipeline import SignalPipeline

        ema = SignalPipeline._ema([42.0], 5)
        assert ema == [42.0]

    def test_ema_crossover_signal_hold(self):
        from flinttrade_ai.pipeline import SignalPipeline

        # Flat data => no crossover => HOLD
        closes = [100.0] * 50
        assert SignalPipeline._ema_crossover_signal(closes) == "HOLD"

    def test_ema_crossover_signal_too_short(self):
        from flinttrade_ai.pipeline import SignalPipeline

        closes = [100.0] * 10
        assert SignalPipeline._ema_crossover_signal(closes) == "HOLD"

    def test_get_latest_signals_empty(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        assert p.get_latest_signals() == {}

    def test_get_latest_signals_returns_stored(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline()
        p.latest_signals = {"NSE_INDEX:NIFTY": {"signal": "BUY"}}
        assert p.get_latest_signals() == {"NSE_INDEX:NIFTY": {"signal": "BUY"}}

    def test_model_path_default(self, monkeypatch, tmp_path):
        from flinttrade_ai.pipeline import SignalPipeline

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        p = SignalPipeline()
        assert "signal_model.joblib" in p.model_path
        assert str(tmp_path / "models") in p.model_path

    def test_model_path_custom(self):
        from flinttrade_ai.pipeline import SignalPipeline

        p = SignalPipeline(model_path="/tmp/my_model.joblib")
        assert p.model_path == "/tmp/my_model.joblib"

    def test_export_in_init(self):
        from flinttrade_ai import __all__

        assert "SignalPipeline" in __all__

    def test_import_from_package(self):
        from flinttrade_ai import SignalPipeline

        assert SignalPipeline is not None


class TestWorkspaceRestPort:
    """U20: the fallback client must carry the workspace REST-port override."""

    def _seed_workspace(self, tmp_path, monkeypatch):
        from flinttrade_core.workspace import Workspace

        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
        for var in ("OPENALGO_API_KEY", "OPENALGO_HOST", "OPENALGO_PORT"):
            monkeypatch.delenv(var, raising=False)

        workspace = Workspace()
        workspace.initialise()
        config = workspace.as_dict()
        config["openalgo"] = {
            "api_key": "workspace-port-key",
            "host": "http://127.0.0.1",
            "port": 5055,
        }
        workspace.save(config)

    def test_init_retains_full_settings_including_port(self, monkeypatch, tmp_path):
        from flinttrade_ai.pipeline import SignalPipeline
        from flinttrade_core.config import openalgo_rest_base_url

        self._seed_workspace(tmp_path, monkeypatch)
        p = SignalPipeline()

        assert p._settings.openalgo_port == 5055
        assert p._settings.openalgo_api_key == "workspace-port-key"
        assert openalgo_rest_base_url(p._settings) == "http://127.0.0.1:5055"

    def test_fetch_bars_fallback_client_receives_full_settings(self, monkeypatch, tmp_path):
        """The fallback client is built from the FULL retained Settings — the
        old partial rebuild (host+key only) silently reverted the configured
        REST port to :5000."""
        from flinttrade_core import openalgo_client as oc
        from flinttrade_ai.pipeline import SignalPipeline

        self._seed_workspace(tmp_path, monkeypatch)

        captured: dict = {}

        class _StubClient:
            def __init__(self, settings):
                captured["settings"] = settings

            async def history(self, **_kwargs):
                return []

            async def close(self):
                return None

        monkeypatch.setattr(oc, "OpenAlgoClient", _StubClient)

        p = SignalPipeline()
        p.fetch_bars("NIFTY", "NSE_INDEX")

        assert captured["settings"].openalgo_port == 5055
        assert captured["settings"].openalgo_api_key == "workspace-port-key"

    def test_constructor_overrides_still_win(self, monkeypatch, tmp_path):
        from flinttrade_ai.pipeline import SignalPipeline

        self._seed_workspace(tmp_path, monkeypatch)
        p = SignalPipeline(openalgo_host="http://10.0.0.9:6000/", openalgo_api_key="explicit")

        assert p.host == "http://10.0.0.9:6000"
        assert p.api_key == "explicit"
        assert p._settings.openalgo_host == "http://10.0.0.9:6000"
        assert p._settings.openalgo_api_key == "explicit"


class TestLegacyModelMigration:
    """One-shot ~/.flinttrade → workspace_dir() migration for the trained model."""

    def test_legacy_model_copied_into_workspace(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"trained-model-bytes")

        p = SignalPipeline()

        migrated = workspace / "models" / "signal_model.joblib"
        assert p.model_path == str(migrated)
        assert migrated.read_bytes() == b"trained-model-bytes"
        # Copy, not move — the legacy file stays behind as a backup.
        assert (legacy_home / "models" / "signal_model.joblib").exists()

    def test_existing_workspace_model_not_clobbered(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"legacy")
        (workspace / "models").mkdir(parents=True)
        (workspace / "models" / "signal_model.joblib").write_bytes(b"current")

        SignalPipeline()

        assert (workspace / "models" / "signal_model.joblib").read_bytes() == b"current"

    def test_explicit_model_path_skips_migration(self, monkeypatch, tmp_path):
        import flinttrade_ai.pipeline as pipeline_mod
        from flinttrade_ai.pipeline import SignalPipeline

        legacy_home = tmp_path / "legacy-home" / ".flinttrade"
        workspace = tmp_path / "workspace"
        monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
        monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

        (legacy_home / "models").mkdir(parents=True)
        (legacy_home / "models" / "signal_model.joblib").write_bytes(b"legacy")

        p = SignalPipeline(model_path=str(tmp_path / "explicit.joblib"))

        assert p.model_path == str(tmp_path / "explicit.joblib")
        assert not (workspace / "models" / "signal_model.joblib").exists()
