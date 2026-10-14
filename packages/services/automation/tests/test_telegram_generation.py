"""Polling public path refuses commands from retired backend generations."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from flinttrade_automation.telegram_bot import BotConfig, TelegramBot

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("drain_failure", [False, True])
@pytest.mark.parametrize("command", ["kill", "pause alpha", "resume alpha"])
def test_queued_writes_are_fenced_after_initial_batch_or_failed_drain(monkeypatch, drain_failure, command):
    monkeypatch.setattr("flinttrade_automation.telegram_bot.time.time", lambda: 1000.5)
    bot = TelegramBot(config=BotConfig(token="fixture", chat_id="999", enabled=True))
    effects = []
    bot.set_handler("kill_switch", lambda: effects.append("kill"))
    bot.set_handler("pause_strategy", lambda name: effects.append("pause"))
    bot.set_handler("resume_strategy", lambda name: effects.append("resume"))
    client = MagicMock()
    batch = iter([
        [{"update_id": i, "message": {"text": "/" + command, "date": date, "chat": {"id": 999}}}]
        for i, date in enumerate([999, None, 1000, 1001], start=101)
    ])

    def get_updates(offset=None, timeout=30):
        if timeout == 0:
            if drain_failure:
                raise OSError("synthetic drain failure")
            return [{"update_id": 100}]
        try:
            return next(batch)
        except StopIteration:
            bot.stop()
            return []

    client.get_updates.side_effect = get_updates
    bot._running = True
    bot.run_polling(client)
    assert effects == [command.split()[0]]
    assert len(bot.command_log) == 1
