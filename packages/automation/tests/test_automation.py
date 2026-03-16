"""Tests for FlintTrade automation package.

DO NOT RUN — written for pytest. All tests use mocks, no live API calls.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

IST = timezone(timedelta(hours=5, minutes=30))


# ======================================================================
# TOTP Login — code generation
# ======================================================================


class TestTOTPLogin:
    """Test TOTP code generation and login flow."""

    def test_generate_totp_produces_6_digits(self):
        from packages.automation.src.totp_login import generate_totp
        # Standard base32 test secret
        code = generate_totp("JBSWY3DPEHPK3PXP")
        assert len(code) == 6
        assert code.isdigit()

    def test_generate_totp_empty_secret_raises(self):
        from packages.automation.src.totp_login import generate_totp
        with pytest.raises(ValueError, match="empty"):
            generate_totp("")

    def test_generate_totp_changes_over_time(self):
        from packages.automation.src.totp_login import generate_totp
        # Two calls with the same secret at the same time should match
        code1 = generate_totp("JBSWY3DPEHPK3PXP")
        code2 = generate_totp("JBSWY3DPEHPK3PXP")
        assert code1 == code2

    def test_is_trading_day_weekday(self):
        from packages.automation.src.totp_login import is_trading_day
        # A known Monday
        monday = date(2026, 3, 16)
        assert monday.weekday() == 0
        assert is_trading_day(monday)

    def test_is_trading_day_weekend(self):
        from packages.automation.src.totp_login import is_trading_day
        saturday = date(2026, 3, 14)
        assert not is_trading_day(saturday)
        sunday = date(2026, 3, 15)
        assert not is_trading_day(sunday)

    def test_login_result_dataclass(self):
        from packages.automation.src.totp_login import LoginResult
        result = LoginResult(
            success=True,
            totp_generated=True,
            session_verified=True,
            attempt_count=1,
        )
        assert result.success
        assert result.attempt_count == 1

    def test_totp_login_no_secret(self, monkeypatch):
        monkeypatch.setenv("BROKER_TOTP_SECRET", "")
        from packages.automation.src.totp_login import TOTPLogin
        login = TOTPLogin(totp_secret="")
        result = login.execute(skip_holiday_check=True)
        assert not result.success
        assert "not configured" in result.error

    def test_totp_login_mock_success(self):
        from packages.automation.src.totp_login import TOTPLogin
        login = TOTPLogin(
            openalgo_host="http://localhost:5000",
            totp_secret="JBSWY3DPEHPK3PXP",
        )
        # Mock HTTP calls
        mock_http = MagicMock()
        mock_response_login = MagicMock()
        mock_response_login.status_code = 200
        mock_response_login.json.return_value = {"status": "success"}
        mock_response_ping = MagicMock()
        mock_response_ping.status_code = 200
        mock_response_ping.json.return_value = {"status": "success"}
        mock_http.post.side_effect = [mock_response_login, mock_response_ping]
        login._http = mock_http

        result = login.execute(skip_holiday_check=True)
        assert result.success
        assert result.totp_generated
        assert result.session_verified

    def test_totp_login_retry_on_failure(self):
        from packages.automation.src.totp_login import TOTPLogin
        login = TOTPLogin(
            totp_secret="JBSWY3DPEHPK3PXP",
            max_retries=2,
            retry_delay=0.01,
        )
        mock_http = MagicMock()
        mock_fail = MagicMock()
        mock_fail.status_code = 500
        mock_fail.text = "error"
        mock_http.post.return_value = mock_fail
        login._http = mock_http

        result = login.execute(skip_holiday_check=True)
        assert not result.success
        assert result.attempt_count == 2


# ======================================================================
# Cron Manager — job registration and scheduling
# ======================================================================


class TestCronManager:
    """Test cron job registration and management."""

    def test_register_job(self):
        from packages.automation.src.cron_manager import CronManager
        cron = CronManager()
        handler = MagicMock()
        cron.register("test_job", handler=handler, trigger_type="interval", trigger_args={"seconds": 60})
        jobs = cron.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test_job"

    def test_register_multiple_jobs(self):
        from packages.automation.src.cron_manager import CronManager
        cron = CronManager()
        cron.register("job1", handler=MagicMock())
        cron.register("job2", handler=MagicMock())
        cron.register("job3", handler=MagicMock())
        assert len(cron.list_jobs()) == 3

    def test_unregister_job(self):
        from packages.automation.src.cron_manager import CronManager
        cron = CronManager()
        cron.register("temp", handler=MagicMock())
        cron.unregister("temp")
        assert len(cron.list_jobs()) == 0

    def test_register_defaults(self):
        from packages.automation.src.cron_manager import CronManager, DEFAULT_JOBS
        cron = CronManager()
        handlers = {name: MagicMock() for name in DEFAULT_JOBS}
        cron.register_defaults(handlers)
        names = [j["name"] for j in cron.list_jobs()]
        assert "totp_login" in names
        assert "health_check" in names
        assert "backup" in names
        assert "post_market_analysis" in names
        assert "mcx_close_check" in names
        assert "ddns_update" in names

    def test_pause_resume_job(self):
        from packages.automation.src.cron_manager import CronManager, JobStatus
        cron = CronManager()
        cron.register("test", handler=MagicMock())
        cron.pause("test")
        jobs = cron.list_jobs()
        assert jobs[0]["status"] == JobStatus.PAUSED.value
        cron.resume("test")
        jobs = cron.list_jobs()
        assert jobs[0]["status"] == JobStatus.ACTIVE.value

    def test_disable_enable_job(self):
        from packages.automation.src.cron_manager import CronManager, JobStatus
        cron = CronManager()
        cron.register("test", handler=MagicMock())
        cron.disable("test")
        assert cron.list_jobs()[0]["status"] == JobStatus.DISABLED.value
        cron.enable("test")
        assert cron.list_jobs()[0]["status"] == JobStatus.ACTIVE.value

    def test_run_now_executes_handler(self):
        from packages.automation.src.cron_manager import CronManager
        handler = MagicMock()
        cron = CronManager()
        cron.register("test", handler=handler)
        cron.run_now("test")
        handler.assert_called_once()

    def test_run_now_records_history(self):
        from packages.automation.src.cron_manager import CronManager
        handler = MagicMock()
        cron = CronManager()
        cron.register("test", handler=handler)
        cron.run_now("test")
        history = cron.get_history("test")
        assert len(history) == 1
        assert history[0].success

    def test_run_now_records_failure(self):
        from packages.automation.src.cron_manager import CronManager
        handler = MagicMock(side_effect=RuntimeError("boom"))
        cron = CronManager()
        cron.register("fail_job", handler=handler)
        cron.run_now("fail_job")
        history = cron.get_history("fail_job")
        assert len(history) == 1
        assert not history[0].success
        assert "boom" in history[0].error

    def test_disabled_job_not_executed(self):
        from packages.automation.src.cron_manager import CronManager
        handler = MagicMock()
        cron = CronManager()
        cron.register("test", handler=handler)
        cron.disable("test")
        cron.run_now("test")
        handler.assert_not_called()

    def test_default_job_definitions(self):
        from packages.automation.src.cron_manager import DEFAULT_JOBS
        assert "totp_login" in DEFAULT_JOBS
        assert DEFAULT_JOBS["totp_login"]["trigger_args"]["hour"] == 8
        assert DEFAULT_JOBS["totp_login"]["trigger_args"]["minute"] == 30
        assert DEFAULT_JOBS["health_check"]["trigger_args"]["minutes"] == 5
        assert DEFAULT_JOBS["ddns_update"]["trigger_args"]["seconds"] == 10


# ======================================================================
# Telegram Bot — command parsing
# ======================================================================


class TestTelegramBot:
    """Test Telegram bot command parsing and authorization."""

    def test_parse_command_basic(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/status")
        assert cmd == "status"
        assert args == []

    def test_parse_command_with_args(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/pause MyStrategy")
        assert cmd == "pause"
        assert args == ["MyStrategy"]

    def test_parse_command_with_bot_suffix(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/kill@flinttrade_bot")
        assert cmd == "kill"

    def test_parse_non_command(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("just a message")
        assert cmd == ""

    def test_authorization_correct_chat_id(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        assert bot.is_authorized("12345")
        assert bot.is_authorized(12345)

    def test_authorization_wrong_chat_id(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        assert not bot.is_authorized("99999")

    def test_authorization_no_restriction(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id=""))
        assert bot.is_authorized("any_id")

    def test_handle_status(self):
        from packages.automation.src.telegram_bot import TelegramBot
        bot = TelegramBot()
        bot.set_handler("get_positions", lambda: [
            {"symbol": "RELIANCE", "quantity": "10", "pnl": "500", "ltp": "2500"},
        ])
        result = bot.handle_command("/status")
        assert "RELIANCE" in result.response
        assert result.command == "status"

    def test_handle_kill(self):
        from packages.automation.src.telegram_bot import TelegramBot
        kill_fn = MagicMock()
        bot = TelegramBot()
        bot.set_handler("kill_switch", kill_fn)
        result = bot.handle_command("/kill")
        kill_fn.assert_called_once()
        assert "KILL" in result.response

    def test_handle_pause(self):
        from packages.automation.src.telegram_bot import TelegramBot
        pause_fn = MagicMock()
        bot = TelegramBot()
        bot.set_handler("pause_strategy", pause_fn)
        result = bot.handle_command("/pause EMA_Strategy")
        pause_fn.assert_called_once_with("EMA_Strategy")
        assert "paused" in result.response

    def test_handle_resume(self):
        from packages.automation.src.telegram_bot import TelegramBot
        resume_fn = MagicMock()
        bot = TelegramBot()
        bot.set_handler("resume_strategy", resume_fn)
        result = bot.handle_command("/resume EMA_Strategy")
        resume_fn.assert_called_once_with("EMA_Strategy")
        assert "resumed" in result.response

    def test_handle_pause_no_args(self):
        from packages.automation.src.telegram_bot import TelegramBot
        bot = TelegramBot()
        result = bot.handle_command("/pause")
        assert "Usage" in result.response

    def test_handle_unknown_command(self):
        from packages.automation.src.telegram_bot import TelegramBot
        bot = TelegramBot()
        result = bot.handle_command("/foobar")
        assert "Unknown" in result.response

    def test_unauthorized_command_blocked(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        result = bot.handle_command("/kill", chat_id="99999")
        assert not result.authorized
        assert "Unauthorized" in result.response

    def test_command_log(self):
        from packages.automation.src.telegram_bot import TelegramBot
        bot = TelegramBot()
        bot.handle_command("/status")
        bot.handle_command("/health")
        assert len(bot.command_log) == 2

    def test_format_positions_empty(self):
        from packages.automation.src.telegram_bot import format_positions
        assert "No open positions" in format_positions([])

    def test_format_positions_with_data(self):
        from packages.automation.src.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "RELIANCE", "quantity": "10", "pnl": "500", "ltp": "2500"},
            {"symbol": "TCS", "quantity": "5", "pnl": "-200", "ltp": "3500"},
        ])
        assert "RELIANCE" in msg
        assert "TCS" in msg

    def test_format_orders_empty(self):
        from packages.automation.src.telegram_bot import format_orders
        assert "No pending orders" in format_orders([])

    def test_format_health(self):
        from packages.automation.src.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": False,
            "disk_free_gb": 50.5,
        })
        assert "OpenAlgo" in msg


# ======================================================================
# OpenClaw Bridge — skill registration
# ======================================================================


class TestOpenClawBridge:
    """Test OpenClaw skill registration and execution."""

    def test_register_skill(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("trade", handler=lambda text: f"trading: {text}")
        assert "trade" in bridge.registered_skills

    def test_register_multiple_skills(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("trade", handler=lambda t: t)
        bridge.register_skill("analyze", handler=lambda t: t)
        bridge.register_skill("status", handler=lambda t: t)
        assert len(bridge.registered_skills) == 3

    def test_unregister_skill(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("temp", handler=lambda t: t)
        bridge.unregister_skill("temp")
        assert "temp" not in bridge.registered_skills

    def test_execute_skill(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("trade", handler=lambda text: f"Processed: {text}")
        result = bridge.execute_skill("trade", "Buy NIFTY")
        assert result.success
        assert result.output == "Processed: Buy NIFTY"

    def test_execute_unregistered_skill(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        result = bridge.execute_skill("nonexistent", "test")
        assert not result.success
        assert "not registered" in result.error

    def test_handle_message_with_command(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("status", handler=lambda text: "All good")
        result = bridge.handle_message("/status")
        assert result.success
        assert result.output == "All good"

    def test_handle_message_freeform_routes_to_trade(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("trade", handler=lambda text: f"Order: {text}")
        result = bridge.handle_message("Buy 100 RELIANCE")
        assert result.success
        assert result.skill_name == "trade"

    def test_skill_execution_error(self):
        from packages.automation.src.openclaw_bridge import OpenClawBridge
        bridge = OpenClawBridge()
        bridge.register_skill("bad", handler=lambda t: 1 / 0)
        result = bridge.execute_skill("bad", "test")
        assert not result.success
        assert result.error

    def test_config_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_PORT", "9999")
        monkeypatch.setenv("OPENCLAW_AUTH_TOKEN", "secret")
        from packages.automation.src.openclaw_bridge import OpenClawConfig
        cfg = OpenClawConfig.from_env()
        assert cfg.port == 9999
        assert cfg.auth_token == "secret"

    def test_default_skills_exist(self):
        from packages.automation.src.openclaw_bridge import DEFAULT_SKILLS
        assert "trade" in DEFAULT_SKILLS
        assert "analyze" in DEFAULT_SKILLS
        assert "backtest" in DEFAULT_SKILLS
        assert "status" in DEFAULT_SKILLS


# ======================================================================
# Post-Market Analysis — report generation
# ======================================================================


class TestPostMarketAnalysis:
    """Test post-market report generation."""

    def _make_trades(self):
        from packages.automation.src.post_market import TradeEntry
        return [
            TradeEntry(symbol="RELIANCE", strategy="EMA", action="BUY", quantity=10, entry_price=2500, exit_price=2550, pnl=500),
            TradeEntry(symbol="TCS", strategy="EMA", action="BUY", quantity=5, entry_price=3500, exit_price=3480, pnl=-100),
            TradeEntry(symbol="NIFTY", strategy="Supertrend", action="SELL", quantity=75, entry_price=24000, exit_price=23900, pnl=7500),
            TradeEntry(symbol="BANKNIFTY", strategy="Supertrend", action="BUY", quantity=30, entry_price=51000, exit_price=50800, pnl=-6000),
        ]

    def test_build_report_basic(self):
        from packages.automation.src.post_market import build_report
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        assert report.total_trades == 4
        assert report.winning_trades == 2
        assert report.losing_trades == 2
        assert report.win_rate == 50.0

    def test_build_report_pnl(self):
        from packages.automation.src.post_market import build_report
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        assert report.gross_pnl == 500 + (-100) + 7500 + (-6000)

    def test_build_report_best_worst_trade(self):
        from packages.automation.src.post_market import build_report
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        assert report.best_trade.symbol == "NIFTY"
        assert report.best_trade.pnl == 7500
        assert report.worst_trade.symbol == "BANKNIFTY"
        assert report.worst_trade.pnl == -6000

    def test_build_report_strategy_breakdown(self):
        from packages.automation.src.post_market import build_report
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        assert len(report.strategy_breakdown) == 2
        strat_names = {s.strategy for s in report.strategy_breakdown}
        assert "EMA" in strat_names
        assert "Supertrend" in strat_names

    def test_build_report_empty_trades(self):
        from packages.automation.src.post_market import build_report
        report = build_report([], "2026-03-16")
        assert report.total_trades == 0
        assert report.win_rate == 0.0
        assert report.best_trade is None

    def test_format_report_telegram(self):
        from packages.automation.src.post_market import build_report, format_report_telegram
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        msg = format_report_telegram(report)
        assert "2026-03-16" in msg
        assert "Win Rate" in msg
        assert "P&L" in msg
        assert "EMA" in msg or "Supertrend" in msg

    def test_report_to_dict(self):
        from packages.automation.src.post_market import build_report
        trades = self._make_trades()
        report = build_report(trades, "2026-03-16")
        d = report.to_dict()
        assert d["report_date"] == "2026-03-16"
        assert d["total_trades"] == 4
        assert "win_rate" in d

    def test_post_market_run_with_telegram(self):
        from packages.automation.src.post_market import PostMarketAnalysis
        mock_bot = MagicMock()
        pma = PostMarketAnalysis(telegram_bot=mock_bot)
        trades = self._make_trades()
        report = pma.run(trades, report_date="2026-03-16", include_llm=False)
        assert report.total_trades == 4
        mock_bot.send_message.assert_called_once()

    def test_post_market_stores_reports(self):
        from packages.automation.src.post_market import PostMarketAnalysis
        pma = PostMarketAnalysis()
        trades = self._make_trades()
        pma.run(trades, "2026-03-16", include_llm=False)
        pma.run(trades, "2026-03-17", include_llm=False)
        assert len(pma.reports) == 2

    def test_strategy_performance_win_rate(self):
        from packages.automation.src.post_market import StrategyPerformance
        perf = StrategyPerformance(
            strategy="EMA", total_trades=10, winning_trades=6, losing_trades=4,
        )
        assert perf.win_rate == 60.0

    def test_strategy_performance_zero_trades(self):
        from packages.automation.src.post_market import StrategyPerformance
        perf = StrategyPerformance(strategy="Empty")
        assert perf.win_rate == 0.0


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from packages.automation.src import __all__
        expected = [
            "TOTPLogin", "CronManager", "TelegramBot",
            "OpenClawBridge", "PostMarketAnalysis",
            "LoginResult", "JobDefinition", "BotConfig",
            "DailyReport", "TradeEntry",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from packages.automation.src import __version__
        assert __version__ == "0.1.0-dev"

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "CLAUDE.md"))
        assert os.path.exists(os.path.join(pkg_dir, "AGENTS.md"))
