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
        from flinttrade_automation.telegram_bot import BotConfig
        cfg = BotConfig()
        assert cfg.token == ""
        assert cfg.chat_id == ""
        assert cfg.enabled is False

    def test_config_with_values(self):
        from flinttrade_automation.telegram_bot import BotConfig
        cfg = BotConfig(token="abc", chat_id="999", enabled=True)
        assert cfg.token == "abc"
        assert cfg.chat_id == "999"
        assert cfg.enabled is True

    def test_from_env_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "456")
        monkeypatch.setenv("TELEGRAM_ENABLED", "true")
        from flinttrade_automation.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.token == "tok123"
        assert cfg.chat_id == "456"
        assert cfg.enabled is True

    def test_from_env_disabled_when_flag_false(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
        monkeypatch.setenv("TELEGRAM_ENABLED", "false")
        from flinttrade_automation.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_missing_vars_returns_defaults(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
        from flinttrade_automation.telegram_bot import BotConfig
        cfg = BotConfig.from_env()
        assert cfg.token == ""
        assert cfg.enabled is False


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_kill_command(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("/kill")
        assert cmd == "kill"
        assert args == []

    def test_resume_with_strategy_name(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("/resume SupertrendV2")
        assert cmd == "resume"
        assert args == ["SupertrendV2"]

    def test_status_uppercase_input(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("/STATUS")
        assert cmd == "status"

    def test_command_with_multiple_args(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("/pause strategy1 extra")
        assert cmd == "pause"
        assert args[0] == "strategy1"

    def test_bot_name_suffix_stripped(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, _ = parse_command("/health@my_trading_bot")
        assert cmd == "health"

    def test_empty_string_returns_empty(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("")
        assert cmd == ""
        assert args == []

    def test_whitespace_only_returns_empty(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("   ")
        assert cmd == ""
        assert args == []

    def test_plain_text_returns_empty(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, args = parse_command("hello world")
        assert cmd == ""

    def test_pnl_command(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, _ = parse_command("/pnl")
        assert cmd == "pnl"

    def test_orders_command(self):
        from flinttrade_automation.telegram_bot import parse_command
        cmd, _ = parse_command("/orders")
        assert cmd == "orders"


# ---------------------------------------------------------------------------
# TelegramBot.send_message — mocked httpx
# ---------------------------------------------------------------------------


class TestSendMessage:
    def test_send_message_success(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
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
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
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
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123"))
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        with patch("httpx.post", return_value=mock_resp):
            result = bot.send_message("test")
        assert result is False

    def test_send_message_returns_false_on_exception(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id="123"))
        with patch("httpx.post", side_effect=Exception("network down")):
            result = bot.send_message("test")
        assert result is False

    def test_send_message_no_token_returns_false(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="", chat_id="123"))
        result = bot.send_message("test")
        assert result is False

    def test_send_message_no_chat_id_returns_false(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="tok", chat_id=""))
        result = bot.send_message("test")
        assert result is False

    def test_send_message_not_called_when_unconfigured(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig())
        with patch("httpx.post") as mock_post:
            bot.send_message("test")
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# TelegramBot.handle_command — command routing
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    def _bot(self, chat_id: str = "12345") -> object:
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
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

    def test_positions_returns_detailed_position_list(self):
        """/positions is the focused position book, not a /status alias."""
        bot = self._bot()
        bot.set_handler("get_positions", lambda: [
            {"symbol": "TCS", "quantity": "5", "pnl": "200", "ltp": "3500"},
        ])
        result = bot.handle_command("/positions", chat_id="12345")
        assert result.command == "positions"
        assert "TCS" in result.response
        assert "Open Positions" in result.response  # format_positions header

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
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="98765"))
        assert bot.is_authorized(98765)

    def test_string_chat_id_matches_integer_config(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="11111"))
        assert bot.is_authorized("11111")

    def test_unauthorized_result_not_logged_to_success_history(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        result = bot.handle_command("/status", chat_id="00000")
        assert not result.authorized
        log = bot.command_log
        assert len(log) == 1
        assert not log[0].authorized

    def test_no_chat_id_configured_rejects_numeric_zero(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id=""))
        assert not bot.is_authorized(0)


# ---------------------------------------------------------------------------
# TelegramBot — command log
# ---------------------------------------------------------------------------


class TestCommandLog:
    def test_log_accumulates_commands(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        bot.handle_command("/health", chat_id="12345")
        bot.handle_command("/orders", chat_id="12345")
        assert len(bot.command_log) == 3

    def test_log_records_command_names(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        log = bot.command_log
        assert log[0].command == "status"

    def test_log_is_copy_not_reference(self):
        """Modifying the returned log must not affect the bot's internal log."""
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("get_positions", lambda: [])
        bot.handle_command("/status", chat_id="12345")
        log = bot.command_log
        log.clear()  # modifying returned copy
        assert len(bot.command_log) == 1  # original unaffected

    def test_failed_command_still_logged(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
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
        from flinttrade_automation.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "NIFTY", "quantity": "75", "pnl": "2000", "ltp": "24000"},
        ])
        assert "🟢" in msg

    def test_format_positions_negative_pnl_has_red(self):
        from flinttrade_automation.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "BANKNIFTY", "quantity": "30", "pnl": "-1500", "ltp": "51000"},
        ])
        assert "🔴" in msg

    def test_format_positions_total_pnl_shown(self):
        from flinttrade_automation.telegram_bot import format_positions
        msg = format_positions([
            {"symbol": "A", "quantity": "1", "pnl": "300", "ltp": "100"},
            {"symbol": "B", "quantity": "1", "pnl": "-100", "ltp": "200"},
        ])
        assert "Total P&L" in msg
        # Net P&L: 300 + (-100) = 200
        assert "+200" in msg

    def test_format_positions_multiple_entries(self):
        from flinttrade_automation.telegram_bot import format_positions
        positions = [
            {"symbol": f"SYM{i}", "quantity": "10", "pnl": str(i * 100), "ltp": "100"}
            for i in range(5)
        ]
        msg = format_positions(positions)
        for i in range(5):
            assert f"SYM{i}" in msg

    def test_format_orders_shows_action_symbol(self):
        from flinttrade_automation.telegram_bot import format_orders
        msg = format_orders([
            {"symbol": "INFY", "action": "BUY", "quantity": "20", "price": "1500"},
        ])
        assert "INFY" in msg
        assert "BUY" in msg
        assert "20" in msg
        assert "1500" in msg

    def test_format_health_shows_disk_warning(self):
        from flinttrade_automation.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": True,
            "disk_free_gb": 1.5,  # below 2 GB → ❌
        })
        assert "❌" in msg

    def test_format_health_websocket_disconnected(self):
        from flinttrade_automation.telegram_bot import format_health
        msg = format_health({
            "openalgo_connected": True,
            "websocket_connected": False,
            "disk_free_gb": 50.0,
        })
        assert "❌" in msg  # WS disconnected

    def test_format_health_uptime_shown(self):
        from flinttrade_automation.telegram_bot import format_health
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
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="1"))
        fn = MagicMock()
        bot.set_handler("kill_switch", fn)
        assert bot._handlers["kill_switch"] is fn

    def test_set_handler_overwrites_existing(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="1"))
        fn1 = MagicMock()
        fn2 = MagicMock()
        bot.set_handler("kill_switch", fn1)
        bot.set_handler("kill_switch", fn2)
        assert bot._handlers["kill_switch"] is fn2

    def test_multiple_handlers_independent(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
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
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        result = bot.handle_command("/kill", chat_id="12345")
        assert "KILL" in result.response
        # No safety system, no router, no handler → errors listed
        assert "not configured" in result.response.lower()

    def test_kill_switch_response_includes_timestamp(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        kill_fn = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"))
        bot.set_handler("kill_switch", kill_fn)
        result = bot.handle_command("/kill", chat_id="12345")
        # Response should contain "IST" time marker
        assert "IST" in result.response

    def test_kill_switch_with_username_recorded(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        mock_audit = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"), audit_logger=mock_audit)
        bot.handle_command("/kill", chat_id="12345", username="alice")
        mock_audit.log_event.assert_called_once_with(
            "KILL_SWITCH",
            source="telegram",
            triggered_by="alice",
        )

    def test_kill_uses_operator_when_no_username(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        mock_audit = MagicMock()
        bot = TelegramBot(config=BotConfig(chat_id="12345"), audit_logger=mock_audit)
        bot.handle_command("/kill", chat_id="12345", username="")
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["triggered_by"] == "operator"


# ---------------------------------------------------------------------------
# Native Bot API client + long-polling loop (G30)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, result):
        self._result = result
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True, "result": self._result}


class TestTelegramClient:
    def test_client_calls_are_native_bot_api(self):
        from flinttrade_automation.telegram_bot import TelegramClient
        import httpx

        seen = []

        def fake_post(url, json=None, timeout=None):
            seen.append((url.rsplit("/", 1)[-1], json))
            if url.endswith("getUpdates"):
                return _FakeResp([{"update_id": 5}])
            return _FakeResp(True)

        with patch.object(httpx, "post", fake_post):
            c = TelegramClient("TOKEN")
            c.delete_webhook()
            c.set_my_commands([{"command": "status", "description": "s"}])
            updates = c.get_updates(offset=3, timeout=1)
            c.send_message("999", "hi")

        methods = [m for m, _ in seen]
        assert methods == ["deleteWebhook", "setMyCommands", "getUpdates", "sendMessage"]
        assert updates == [{"update_id": 5}]
        # getUpdates carried the offset; sendMessage carried the chat + text.
        assert dict(seen)["getUpdates"]["offset"] == 3
        assert dict(seen)["sendMessage"] == {"chat_id": "999", "text": "hi", "parse_mode": "Markdown"}

    def test_client_raises_on_not_ok(self):
        from flinttrade_automation.telegram_bot import TelegramClient, TelegramApiError
        import httpx

        class NotOk(_FakeResp):
            def json(self):
                return {"ok": False, "description": "bad token"}

        with patch.object(httpx, "post", lambda *a, **k: NotOk(None)):
            import pytest
            with pytest.raises(TelegramApiError, match="bad token"):
                TelegramClient("TOKEN").send_message("1", "x")


def _mock_client(*, poll_updates=None):
    """A MagicMock TelegramClient whose get_updates returns [] on the startup
    drain (timeout=0) and ``poll_updates`` on the live long-poll."""
    client = MagicMock()
    batches = list(poll_updates or [])

    def get_updates(offset=None, timeout=30):
        if timeout == 0:  # startup drain — nothing pending
            return []
        return batches.pop(0) if batches else []

    client.get_updates.side_effect = get_updates
    return client


class TestPollingLoop:
    def _bot(self, **kw):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        return TelegramBot(config=BotConfig(token="T", chat_id="999", enabled=True), **kw)

    def _msg(self, text, chat=999, user="owner", uid=10):
        return {"update_id": uid, "message": {"text": text, "chat": {"id": chat}, "from": {"username": user}}}

    def test_start_background_no_op_when_unconfigured(self):
        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        assert TelegramBot(config=BotConfig(enabled=False)).start_background() is False
        assert TelegramBot(config=BotConfig(token="T", enabled=True)).start_background() is False  # no chat_id
        assert TelegramBot(config=BotConfig(chat_id="1", enabled=True)).start_background() is False  # no token

    def test_run_polling_dispatches_and_replies(self):
        bot = self._bot()
        client = _mock_client(poll_updates=[[self._msg("/status")]])
        captured = {}
        orig = bot.handle_command

        def wrapped(text, chat_id="", username=""):
            captured["args"] = (text, str(chat_id), username)
            bot.stop()
            return orig(text, chat_id, username=username)

        bot.handle_command = wrapped
        bot._running = True
        bot.run_polling(client=client)

        assert captured["args"] == ("/status", "999", "owner")
        client.send_message.assert_called_once()
        assert client.send_message.call_args[0][0] == 999  # replied to the sender

    def test_startup_drain_skips_pending_updates(self):
        # A /kill queued while the app was down (returned by the timeout=0 drain)
        # must NOT be dispatched — only commands sent after startup are acted on.
        bot = self._bot()
        client = MagicMock()
        stale = [self._msg("/kill", uid=7)]

        def get_updates(offset=None, timeout=30):
            if timeout == 0:
                return stale  # pending at startup
            bot.stop()
            return []

        client.get_updates.side_effect = get_updates
        dispatched = []
        bot.handle_command = lambda *a, **k: dispatched.append(a) or type(bot).handle_command(bot, *a, **k)
        bot._running = True
        bot.run_polling(client=client)
        assert dispatched == []  # the stale /kill was drained, never dispatched

    def test_run_polling_survives_getupdates_error(self):
        bot = self._bot()
        client = MagicMock()
        calls = {"n": 0}

        def flaky(offset=None, timeout=30):
            if timeout == 0:
                return []  # drain
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("network blip")
            bot.stop()
            return []

        client.get_updates.side_effect = flaky
        with patch("flinttrade_automation.telegram_bot.time.sleep", lambda _s: None):
            bot._running = True
            bot.run_polling(client=client)
        assert calls["n"] == 2  # retried after the error rather than dying

    def test_unauthorised_chat_gets_no_reply_and_no_action(self):
        bot = self._bot()  # authorised chat is 999
        client = _mock_client(poll_updates=[[self._msg("/kill", chat=111, user="attacker", uid=1)]])
        killed = MagicMock()
        bot.set_handler("kill_switch", killed)
        seen = {}
        real = bot.handle_command

        def wrapped(text, chat_id="", username=""):
            r = real(text, chat_id, username=username)
            seen["auth"] = r.authorized
            bot.stop()
            return r

        bot.handle_command = wrapped
        bot._running = True
        bot.run_polling(client=client)
        assert seen["auth"] is False
        killed.assert_not_called()  # kill switch NOT fired for an unauthorised chat
        client.send_message.assert_not_called()  # and NO reply echoed back (no reflector)

    def test_reply_falls_back_to_plain_on_markdown_error(self):
        from flinttrade_automation.telegram_bot import TelegramApiError, TelegramBot
        client = MagicMock()
        client.send_message.side_effect = [TelegramApiError("can't parse entities"), {"message_id": 1}]
        TelegramBot._reply(client, 999, "Strategy 'iron_condor' paused")
        assert client.send_message.call_count == 2
        # the retry dropped Markdown parsing
        assert client.send_message.call_args_list[1].kwargs.get("parse_mode") == ""

    def test_setup_failure_does_not_log_the_token(self, caplog):
        # deleteWebhook raising an httpx error whose str embeds the bot URL must
        # not leak the token — only the exception type is logged.
        import logging

        from flinttrade_automation.telegram_bot import TelegramBot
        bot = TelegramBot.__new__(TelegramBot)
        from flinttrade_automation.telegram_bot import BotConfig
        bot.config = BotConfig(token="123:SECRETTOKEN", chat_id="9", enabled=True)
        bot._running = False  # exit immediately after setup
        bot._poll_timeout = 30
        client = MagicMock()
        client.delete_webhook.side_effect = RuntimeError("... for url 'https://api.telegram.org/bot123:SECRETTOKEN/x'")
        client.get_updates.return_value = []
        with caplog.at_level(logging.WARNING):
            bot.run_polling(client=client)
        assert "SECRETTOKEN" not in caplog.text


class TestWiredCommands:
    """/positions and /orders read the broker book via the client's run_sync."""

    def _wired_bot(self, positions=None, orders=None):
        import asyncio

        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot

        client = MagicMock()

        async def _pb():
            return positions or []

        async def _ob():
            return orders or []

        client.positionbook.side_effect = _pb
        client.orderbook.side_effect = _ob

        # The real OpenAlgoClient exposes run_sync (its own persistent loop); the
        # bot MUST use it, not ad-hoc asyncio.run. Run the coroutine faithfully.
        def _run_sync(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        client.run_sync.side_effect = _run_sync
        router = MagicMock()
        router.client = client
        return TelegramBot(config=BotConfig(token="T", chat_id="9", enabled=True), router=router), client

    def test_positions_wired_uses_run_sync(self):
        bot, client = self._wired_bot(positions=[{"symbol": "INFY", "quantity": 10, "pnl": 500, "ltp": 1500}])
        result = bot.handle_command("/positions", chat_id="9")
        assert "INFY" in result.response
        assert "Open Positions" in result.response
        client.run_sync.assert_called()  # went through the client's own loop, not asyncio.run

    def test_orders_wired_uses_run_sync(self):
        bot, client = self._wired_bot(orders=[{"symbol": "SBIN", "action": "BUY", "quantity": 100, "price": 800}])
        result = bot.handle_command("/orders", chat_id="9")
        assert "SBIN" in result.response
        assert "Pending Orders" in result.response
        client.run_sync.assert_called()


class TestSendAlertNative:
    def test_send_alert_uses_native_send_message(self):
        # Regression: send_alert once referenced self._bot (removed with
        # python-telegram-bot); it must now go through the native send_message.
        import asyncio

        from flinttrade_automation.telegram_bot import BotConfig, TelegramBot
        bot = TelegramBot(config=BotConfig(token="T", chat_id="9", enabled=True))
        with patch.object(bot, "send_message", return_value=True) as send:
            asyncio.run(bot.send_alert("kill switch fired", severity="P0"))
        send.assert_called_once()
        assert "kill switch fired" in send.call_args[0][0]
