"""Extended tests for TelegramBot — send_message, command handling, formatting, kill switch.

All HTTP calls and external libraries are mocked. No real Telegram tokens needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch



# ---------------------------------------------------------------------------
# BotConfig
# ---------------------------------------------------------------------------


class TestBotConfig:
    def test_default_config_disabled(self):
        from packages.automation.src.telegram_bot import BotConfig
        cfg = BotConfig()
        assert cfg.token == ""
        assert cfg.chat_id == ""
        assert cfg.enabled is False

    def test_config_with_values(self):
        from packages.automation.src.telegram_bot import BotConfig
        cfg = BotConfig(token="abc", chat_id="999", enabled=True)
        assert cfg.token == "abc"
        assert cfg.chat_id == "999"
        assert cfg.enabled is True

    def test_from_env_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
        monkeypatch.setenv("TELEGRAM_ENABLED", "true")
        from packages.automation.src.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.token == "tok123"
        assert cfg.chat_id == "456"
        assert cfg.enabled is True

    def test_from_env_disabled_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("TELEGRAM_ENABLED", "false")
        from packages.automation.src.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_missing_vars_returns_defaults(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
        from packages.automation.src.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.token == ""
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_kill_command(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/kill")
        assert cmd == "kill"
        assert args == []

    def test_resume_with_strategy_name(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/resume SupertrendV2")
        assert cmd == "resume"
        assert args == ["SupertrendV2"]

    def test_status_uppercase_input(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/STATUS")
        assert cmd == "status"

    def test_command_with_multiple_args(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("/pause strategy1 extra")
        assert cmd == "pause"
        assert args[0] == "strategy1"

    def test_bot_name_suffix_stripped(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, _ = parse_command("/health@my_trading_bot")
        assert cmd == "health"

    def test_empty_string_returns_empty(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("")
        assert cmd == ""
        assert args == []

    def test_whitespace_only_returns_empty(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("   ")
        assert cmd == ""
        assert args == []

    def test_plain_text_returns_empty(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, args = parse_command("hello world")
        assert cmd == ""

    def test_pnl_command(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, _ = parse_command("/pnl")
        assert cmd == "pnl"

    def test_orders_command(self):
        from packages.automation.src.telegram_bot import parse_command
        cmd, _ = parse_command("/orders")
        assert cmd == "orders"


# ---------------------------------------------------------------------------
# TelegramBot.send_message — mocked httpx
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_send_message_success(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123", enabled=True))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = bot.send_message("Hello trading world")
        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "sendMessage" in call_kwargs[0][0]

    def test_send_message_payload_includes_text(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123", enabled=True))
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            bot.send_message("*Alert!* Price deviation detected")
        sent_json = mock_post.call_args[1]["json"]
        assert sent_json["text"] == "*Alert!* Price deviation detected"
        assert sent_json["chat_id"] == "123"
        assert sent_json["parse_mode"] == "Markdown"

    def test_send_message_returns_false_on_http_error(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123"))
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        with patch("httpx.post", return_value=mock_resp):
            result = bot.send_message("test")
        assert result is False

    def test_send_message_returns_false_on_exception(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123"))
        with patch("httpx.post", side_effect=Exception("network down")):
            result = bot.send_message("test")
        assert result is False

    def test_send_message_no_token_returns_false(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="", chat_id="123"))
        result = bot.send_message("test")
        assert result is False

    def test_send_message_no_chat_id_returns_false(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id=""))
        result = bot.send_message("test")
        assert result is False

    def test_send_message_not_called_when_unconfigured(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig())
        with patch("httpx.post") as mock_post:
            bot.send_message("test")
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# TelegramBot.handle_command — command routing
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    def _bot(self, chat_id: str = "12345") -> object:
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        return TelegramBot(config=BotConfig(chat_id=chat_id))

    def test_pnl_command_with_handler(self):
        bot = self._bot()
        bot.set_handler("get_pnl", lambda: {
            "total_pnl": 1500, "total_trades": 8, "winning_trades": 5,
        })
        result = bot.handle_command("/pnl", chat_id="12345")
        assert result.command == "pnl"
        assert "1500" in result.response or "+1500" in result.response
        assert "8" in result.response

    def test_pnl_command_no_handler(self):
        bot = self._bot()
        result = bot.handle_command("/pnl", chat_id="12345")
        assert "handler not configured" in result.response.lower()

    def test_orders_command_with_handler(self):
        bot = self._bot()
        bot.set_handler("get_orders", lambda: [
            {"symbol": "NIFTY", "action": "BUY", "quantity": "75", "price": "24000"},
        ])
        result = bot.handle_command("/orders", chat_id="12345")
        assert result.command == "orders"
        assert "NIFTY" in result.response

    def test_orders_command_empty_list(self):
        bot = self._bot()
        bot.set_handler("get_orders", lambda: [])
        result = bot.handle_command("/orders", chat_id="12345")
        assert "No pending orders" in result.response

    def test_orders_no_handler(self):
        bot = self._bot()
        result = bot.handle_command("/orders", chat_id="12345")
        assert "handler not configured" in result.response.lower()

    def test_health_command_with_handler(self):
        bot = self._bot()
        bot.set_handler("get_health", lambda: {
            "openalgo_connected": True,
            "websocket_connected": True,
            "disk_free_gb": 80.0,
        })
        result = bot.handle_command("/health", chat_id="12345")
        assert "Health" in result.response
        assert "OpenAlgo" in result.response

    def test_health_command_no_handler_uses_system(self):
        """When no health handler is set, falls back to system disk usage."""
        bot = self._bot()
        result = bot.handle_command("/health", chat_id="12345")
        assert "Health" in result.response

    def test_pause_no_args_returns_usage(self):
        bot = self._bot()
        bot.set_handler("pause_strategy", MagicMock())
        result = bot.handle_command("/pause", chat_id="12345")
        assert "Usage" in result.response

    def test_resume_no_args_returns_usage(self):
        bot = self._bot()
        bot.set_handler("resume_strategy", MagicMock())
        result = bot.handle_command("/resume", chat_id="12345")
        assert "Usage" in result.response

    def test_positions_delegates_to_status(self):
        """positions command is an alias for status."""
        bot = self._bot()
        bot.set_handler("get_positions", lambda: [
            {"symbol": "TCS", "quantity": "5", "pnl": "200", "ltp": "3500"},
        ])
        result = bot.handle_command("/positions", chat_id="12345")
        assert result.command == "positions"
        assert "TCS" in result.response

    def test_unknown_command_response(self):
        bot = self._bot()
        result = bot.handle_command("/xyz_unknown_command", chat_id="12345")
        assert "Unknown" in result.response

    def test_non_command_text_not_processed(self):
        bot = self._bot()
        result = bot.handle_command("this is a plain message", chat_id="12345")
        assert result.command == ""
        assert "Not a command" in result.response

    def test_command_result_has_no_error_on_success(self):
        bot = self._bot()
        bot.set_handler("get_positions", lambda: [])
        result = bot.handle_command("/status", chat_id="12345")
        assert result.error == ""
        assert result.authorized is True


# ---------------------------------------------------------------------------
# TelegramBot — authorization edge cases
# ---------------------------------------------------------------------------


class TestAuthorization:
    def test_integer_chat_id_matches_string_config(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="98765"))
        assert bot.is_authorized(98765)

    def test_string_chat_id_matches_integer_config(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="11111"))
        assert bot.is_authorized("11111")

    def test_unauthorized_result_not_logged_to_success_history(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        result = bot.handle_command("/status", chat_id="00000")
        assert not result.authorized
        log = bot.command_log
        assert len(log) == 1
        assert not log[0].authorized

    def test_no_chat_id_configured_rejects_numeric_zero(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id=""))
        assert not bot.is_authorized(0)


# ---------------------------------------------------------------------------
# TelegramBot — command log
# ---------------------------------------------------------------------------


class TestCommandLog:
    def test_log_accumulates_commands(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        bot.handle_command("/health", chat_id="12345")
        bot.handle_command("/orders", chat_id="12345")
        assert len(bot.command_log) == 3

    def test_log_records_command_names(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        log = bot.command_log
        assert log[0].command == "status"

    def test_log_is_copy_not_reference(self):
        """Modifying the returned log must not affect the bot's internal log."""
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        log = bot.command_log
        log.clear()  # modifying returned copy
        assert len(bot.command_log) == 1  # original unaffected

    def test_failed_command_still_logged(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", MagicMock(side_effect=RuntimeError("boom")))
        bot.handle_command("/status", chat_id="12345")
        log = bot.command_log
        assert len(log) == 1
        assert log[0].error == "boom"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


class TestFormattingHelpers:
    def test_format_positions_positive_pnl_has_green(self):
        from packages.automation.src.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "NIFTY", "quantity": "75", "pnl": "2000", "ltp": "24000"},
        ])
        assert "🟢" in msg

    def test_format_positions_negative_pnl_has_red(self):
        from packages.automation.src.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "BANKNIFTY", "quantity": "30", "pnl": "-1500", "ltp": "51000"},
        ])
        assert "🔴" in msg

    def test_format_positions_total_pnl_shown(self):
        from packages.automation.src.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "A", "quantity": "1", "pnl": "300", "ltp": "100"},
            {"symbol": "B", "quantity": "1", "pnl": "-100", "ltp": "200"},
        ])
        assert "Total P&L" in msg
        # Net P&L: 300 + (-100) = 200
        assert "+200" in msg

    def test_format_positions_multiple_entries(self):
        from packages.automation.src.telegram_bot import format_positions
        positions = [
            {"symbol": f"SYM{i}", "quantity": "10", "pnl": str(i * 100), "ltp": "100"}
            for i in range(5)
        ]
        msg = format_positions(positions)
        for i in range(5):
            assert f"SYM{i}" in msg

    def test_format_orders_shows_action_symbol(self):
        from packages.automation.src.telegram_bot import format_orders
        msg = format_orders([
            {"symbol": "INFY", "action": "BUY", "quantity": "20", "price": "1500"},
        ])
        assert "INFY" in msg
        assert "BUY" in msg
        assert "20" in msg
        assert "1500" in msg

    def test_format_health_shows_disk_warning(self):
        from packages.automation.src.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": True,
            "disk_free_gb": 1.5,  # below 2 GB → ❌
        })
        assert "❌" in msg

    def test_format_health_websocket_disconnected(self):
        from packages.automation.src.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": False,
            "disk_free_gb": 50.0,
        })
        assert "❌" in msg  # WS disconnected

    def test_format_health_uptime_shown(self):
        from packages.automation.src.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": True,
            "disk_free_gb": 30.0,
            "uptime": "2h 15m",
        })
        assert "2h 15m" in msg


# ---------------------------------------------------------------------------
# TelegramBot — set_handler / handler registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    def test_set_handler_stores_callable(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="1"))
        fn = MagicMock()
        bot.set_handler("kill_switch", fn)
        assert bot._handlers["kill_switch"] is fn

    def test_set_handler_overwrites_existing(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="1"))
        fn1 = MagicMock()
        fn2 = MagicMock()
        bot.set_handler("kill_switch", fn1)
        bot.set_handler("kill_switch", fn2)
        assert bot._handlers["kill_switch"] is fn2

    def test_multiple_handlers_independent(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="1"))
        kill_fn = MagicMock()
        pause_fn = MagicMock()
        bot.set_handler("kill_switch", kill_fn)
        bot.set_handler("pause_strategy", pause_fn)
        assert bot._handlers["kill_switch"] is kill_fn
        assert bot._handlers["pause_strategy"] is pause_fn


# ---------------------------------------------------------------------------
# Kill switch — error path
# ---------------------------------------------------------------------------


class TestKillSwitchErrors:
    def test_kill_without_any_handlers_shows_error_message(self):
        """Kill switch with no handlers configured reports the issue."""
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        result = bot.handle_command("/kill", chat_id="12345")
        assert "KILL" in result.response
        # No safety system, no router, no handler → errors listed
        assert "not configured" in result.response.lower()

    def test_kill_switch_response_includes_timestamp(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        kill_fn = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("kill_switch", kill_fn)
        result = bot.handle_command("/kill", chat_id="12345")
        # Response should contain "IST" time marker
        assert "IST" in result.response

    def test_kill_switch_with_username_recorded(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        mock_audit = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"), audit_logger=mock_audit)
        bot.handle_command("/kill", chat_id="12345", username="alice")
        mock_audit.log_event.assert_called_once_with(
            "KILL_SWITCH",
            source="telegram",
            triggered_by="alice",
        )

    def test_kill_uses_operator_when_no_username(self):
        from packages.automation.src.telegram_bot import BotConfig, TelegramBot
        mock_audit = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"), audit_logger=mock_audit)
        bot.handle_command("/kill", chat_id="12345", username="")
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["triggered_by"] == "operator"
