"""Network capture refusal must preserve supplied local tick persistence."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from flinttrade_data.tick_recorder import NATIVE_TICK_CAPTURE_UNAVAILABLE, TickRecorder


@pytest.mark.asyncio
async def test_unavailable_network_run_touches_no_storage_and_local_ingestion_still_persists() -> None:
    storage = MagicMock()
    recorder = TickRecorder(storage=storage)
    recorder.add_symbols([{"exchange": "NSE", "symbol": "INFY"}])

    with pytest.raises(RuntimeError, match="Native tick capture is unavailable"):
        await recorder.run()

    assert recorder.is_running is False
    assert recorder.is_connected is False
    assert recorder.last_error == NATIVE_TICK_CAPTURE_UNAVAILABLE
    assert storage.mock_calls == []

    recorder._process_tick(
        {"exchange": "NSE", "symbol": "INFY", "ltp": 100, "timestamp": datetime.now(UTC).isoformat()}
    )
    assert recorder.tick_count == 1
    assert recorder.pending_tick_count == 1
    assert recorder.flush_pending() is True
    assert recorder.persisted_tick_count == 1
    assert recorder.pending_tick_count == 0
    storage.insert_ticks_batch.assert_called_once()
