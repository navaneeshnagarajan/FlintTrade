"""Canonical static RSS publisher profiles shared by core and AI consumers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class NewsProviderProfile:
    """A publisher and its semantically distinct RSS channels."""

    provider_id: str
    display_name: str
    channels: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        channels = tuple((name.strip(), url.strip()) for name, url in self.channels)
        if not self.provider_id.strip() or not self.display_name.strip():
            raise ValueError("publisher profile fields must be non-blank")
        if not channels or any(not name or not url for name, url in channels):
            raise ValueError("publisher channels must be non-blank")
        if len({name for name, _url in channels}) != len(channels):
            raise ValueError("publisher channel names must be unique")
        object.__setattr__(self, "channels", channels)

    def channel_url(self, channel_name: str) -> str:
        """Return one named RSS channel URL."""
        return dict(self.channels)[channel_name]


NEWS_PROVIDER_PROFILES: tuple[NewsProviderProfile, ...] = (
    NewsProviderProfile(
        provider_id="news:rss.moneycontrol",
        display_name="MoneyControl",
        channels=(
            ("latest", "https://www.moneycontrol.com/rss/latestnews.xml"),
            ("market_reports", "https://www.moneycontrol.com/rss/marketreports.xml"),
        ),
    ),
    NewsProviderProfile(
        provider_id="news:rss.economictimes",
        display_name="ET Markets",
        channels=(("market", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),),
    ),
    NewsProviderProfile(
        provider_id="news:rss.livemint",
        display_name="LiveMint",
        channels=(("market", "https://www.livemint.com/rss/markets"),),
    ),
)

NEWS_PROVIDER_BY_ID = MappingProxyType({profile.provider_id: profile for profile in NEWS_PROVIDER_PROFILES})

SENTIMENT_NEWS_CHANNELS: tuple[tuple[str, str], ...] = (
    ("moneycontrol", NEWS_PROVIDER_BY_ID["news:rss.moneycontrol"].channel_url("market_reports")),
    ("economictimes", NEWS_PROVIDER_BY_ID["news:rss.economictimes"].channel_url("market")),
    ("livemint", NEWS_PROVIDER_BY_ID["news:rss.livemint"].channel_url("market")),
)

OPERATIONS_NEWS_FEEDS: tuple[tuple[str, str], ...] = (
    ("MoneyControl", NEWS_PROVIDER_BY_ID["news:rss.moneycontrol"].channel_url("latest")),
    ("ET Markets", NEWS_PROVIDER_BY_ID["news:rss.economictimes"].channel_url("market")),
    ("LiveMint", NEWS_PROVIDER_BY_ID["news:rss.livemint"].channel_url("market")),
)
