"""Tests for the canonical, static publisher RSS profiles."""

from dataclasses import FrozenInstanceError

import pytest

from flinttrade_core.news_provider_profiles import NEWS_PROVIDER_BY_ID, NEWS_PROVIDER_PROFILES


def test_moneycontrol_preserves_both_consumed_channels() -> None:
    moneycontrol = NEWS_PROVIDER_BY_ID["news:rss.moneycontrol"]

    assert dict(moneycontrol.channels) == {
        "latest": "https://www.moneycontrol.com/rss/latestnews.xml",
        "market_reports": "https://www.moneycontrol.com/rss/marketreports.xml",
    }


def test_publisher_profiles_are_frozen_and_cover_the_three_publishers() -> None:
    assert tuple(profile.provider_id for profile in NEWS_PROVIDER_PROFILES) == (
        "news:rss.moneycontrol",
        "news:rss.economictimes",
        "news:rss.livemint",
    )
    with pytest.raises(FrozenInstanceError):
        NEWS_PROVIDER_PROFILES[0].display_name = "Changed"  # type: ignore[misc]
