"""FlintTrade automation package — cron, Telegram and post-market analysis."""

from flinttrade_core.version import APP_VERSION

__version__ = APP_VERSION

from .cron_manager import CronManager, JobDefinition, JobHistory, JobStatus
from .post_market import (
    DailyReport,
    PostMarketAnalysis,
    StrategyPerformance,
    TradeEntry,
)
from .telegram_bot import BotConfig, CommandResult, TelegramApiError, TelegramBot, TelegramClient
from .totp_login import LoginResult, is_trading_day

__all__ = [
    # Trading day utilities (retained from totp_login)
    "LoginResult",
    "is_trading_day",
    # Cron
    "CronManager",
    "JobDefinition",
    "JobHistory",
    "JobStatus",
    # Telegram
    "TelegramBot",
    "TelegramClient",
    "TelegramApiError",
    "BotConfig",
    "CommandResult",
    # Post-market
    "PostMarketAnalysis",
    "DailyReport",
    "TradeEntry",
    "StrategyPerformance",
]
