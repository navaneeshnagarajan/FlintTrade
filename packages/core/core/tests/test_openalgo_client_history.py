"""Focused OpenAlgo history-boundary contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_history_normalises_epoch_seconds_and_milliseconds() -> None:
    from flinttrade_core.config import Settings
    from flinttrade_core.openalgo_client import OpenAlgoClient

    client = OpenAlgoClient(
        Settings(openalgo_host="http://127.0.0.1", openalgo_api_key="test-key")
    )
    source_time = datetime(2026, 7, 10, 9, 15, tzinfo=timezone.utc)
    epoch_seconds = int(source_time.timestamp())
    client._post = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "status": "success",
            "data": [
                {
                    "timestamp": epoch_seconds,
                    "open": 100,
                    "high": 101,
                    "low": 99,
                    "close": 100.5,
                    "volume": 10,
                },
                {
                    "timestamp": epoch_seconds * 1000,
                    "open": 101,
                    "high": 102,
                    "low": 100,
                    "close": 101.5,
                    "volume": 20,
                },
            ],
        }
    )

    try:
        bars = await client.history("RELIANCE", "NSE")
    finally:
        await client.close()

    assert [bar.timestamp for bar in bars] == [source_time.isoformat()] * 2

