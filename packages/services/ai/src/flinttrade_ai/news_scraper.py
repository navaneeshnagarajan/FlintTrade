"""Compatibility imports for the canonical sentiment news layer.

The RSS implementation lives in :mod:`flinttrade_ai.sentiment`. This module
retains the former import surface without carrying a second implementation.
"""

from .sentiment import (
    _CACHE_TTL_SECS,
    IST,
    RSS_SOURCES,
    NewsArticle,
    NewsScraper,
    _link,
    _parse_rss_xml,
    _strip_html,
    _text,
)

__all__ = [
    "IST",
    "RSS_SOURCES",
    "NewsArticle",
    "NewsScraper",
    "_CACHE_TTL_SECS",
    "_link",
    "_parse_rss_xml",
    "_strip_html",
    "_text",
]
