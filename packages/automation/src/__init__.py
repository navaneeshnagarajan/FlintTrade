"""FlintTrade automation package — TOTP login, cron, Telegram, OpenClaw, post-market."""

__version__ = "0.1.0-alpha"

from .cron_manager import CronManager, JobDefinition, JobHistory, JobStatus
from .openclaw_bridge import OpenClawBridge, OpenClawConfig, Skill, SkillResult
from .post_market import (
    DailyReport,
    PostMarketAnalysis,
    StrategyPerformance,
    TradeEntry,
)
from .telegram_bot import BotConfig, CommandResult, TelegramBot
from .totp_login import LoginResult, TOTPLogin

__all__ = [
    # TOTP
    "TOTPLogin",
    "LoginResult",
    # Cron
    "CronManager",
    "JobDefinition",
    "JobHistory",
    "JobStatus",
    # Telegram
    "TelegramBot",
    "BotConfig",
    "CommandResult",
    # OpenClaw
    "OpenClawBridge",
    "OpenClawConfig",
    "Skill",
    "SkillResult",
    # Post-market
    "PostMarketAnalysis",
    "DailyReport",
    "TradeEntry",
    "StrategyPerformance",
]
