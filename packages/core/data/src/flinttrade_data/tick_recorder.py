"""WebSocket tick recorder — connects to OpenAlgo WS and stores ticks in DuckDB.

Supports all exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, DELTA.
MCX ticks arrive until 11:55 PM IST, DELTA ticks are 24/7.

Protocol (from docs/references/OPENALGO_API.md):
  subscribe_ltp   → LTP only
  subscribe_quote → LTP + bid/ask + volume + OI
  subscribe_depth → full order book (top 5)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import websockets
import websockets.exceptions

from .storage import StorageManager

logger = logging.getLogger("flinttrade.data.tick_recorder")

_DEFAULT_WS_URL = f"ws://127.0.0.1:{os.getenv('OPENALGO_WS_PORT', '8765')}"

# Subscription modes
MODE_LTP = "ltp"
MODE_QUOTE = "quote"
MODE_DEPTH = "depth"

_ACTION_MAP = {
    MODE_LTP: "subscribe_ltp",
    MODE_QUOTE: "subscribe_quote",
    MODE_DEPTH: "subscribe_depth",
}

_UNSUB_ACTION_MAP = {
    MODE_LTP: "unsubscribe_ltp",
    MODE_QUOTE: "unsubscribe_quote",
    MODE_DEPTH: "unsubscribe_depth",
}


class TickRecorder:
    """Connects to OpenAlgo WebSocket and records ticks to DuckDB.

    Usage::

        recorder = TickRecorder(storage=storage)
        recorder.add_symbols([
            {"exchange": "NSE", "symbol": "RELIANCE"},
            {"exchange": "NFO", "symbol": "NIFTY26MAR2524000CE"},
        ], mode="quote")
        await recorder.run()   # blocks, auto-reconnects
    """

    def __init__(
        self,
        storage: StorageManager,
        ws_url: str | None = None,
        batch_size: int = 100,
        flush_interval: float = 1.0,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
        storage_lock: Any | None = None,
    ) -> None:
        self._storage = storage
        self._ws_url = ws_url or _DEFAULT_WS_URL
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        # Serialises access to the (single) DuckDB connection this recorder shares
        # with the nightly maintenance job, which runs on the scheduler thread —
        # DuckDB connections are not safe for concurrent use. None = no sharing.
        self._storage_lock = storage_lock
        # On a persistent write failure the buffer is RETAINED for retry (a
        # transient lock/disk error must not silently lose ticks), but capped so
        # it cannot grow without bound — drop the oldest beyond this.
        self._max_buffer = max(batch_size * 100, 10_000)

        # Instruments keyed by mode
        self._subscriptions: dict[str, list[dict[str, str]]] = {
            MODE_LTP: [],
            MODE_QUOTE: [],
            MODE_DEPTH: [],
        }

        self._buffer: list[tuple] = []
        self._running = False
        self._tick_count = 0

    @property
    def tick_count(self) -> int:
        return self._tick_count

    # ------------------------------------------------------------------
    # Watchlist management
    # ------------------------------------------------------------------

    def add_symbols(
        self,
        instruments: list[dict[str, str]],
        mode: str = MODE_QUOTE,
    ) -> None:
        """Add instruments to the subscription watchlist.

        Each instrument: {"exchange": "NSE", "symbol": "RELIANCE"}
        """
        if mode not in self._subscriptions:
            raise ValueError(f"Invalid mode: {mode}. Use {list(_ACTION_MAP)}")
        for inst in instruments:
            if inst not in self._subscriptions[mode]:
                self._subscriptions[mode].append(inst)

    def remove_symbols(
        self,
        instruments: list[dict[str, str]],
        mode: str = MODE_QUOTE,
    ) -> None:
        """Remove instruments from the watchlist."""
        for inst in instruments:
            try:
                self._subscriptions[mode].remove(inst)
            except ValueError:
                pass

    def get_watchlist(self) -> dict[str, list[dict[str, str]]]:
        """Return current subscription watchlist by mode."""
        return {m: list(insts) for m, insts in self._subscriptions.items()}

    # ------------------------------------------------------------------
    # WebSocket loop with auto-reconnect
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop — connect, subscribe, consume ticks. Auto-reconnects."""
        self._running = True
        delay = self._reconnect_delay

        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    logger.info("WebSocket connected: %s", self._ws_url)
                    delay = self._reconnect_delay  # reset on success

                    await self._subscribe_all(ws)
                    await self._consume(ws)

            except (
                websockets.exceptions.ConnectionClosed,
                websockets.exceptions.InvalidURI,
                OSError,
            ) as exc:
                if not self._running:
                    break
                logger.warning("WebSocket disconnected: %s — reconnecting in %.0fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

        # Flush remaining buffer on shutdown
        self._flush()
        logger.info("TickRecorder stopped. Total ticks recorded: %d", self._tick_count)

    def stop(self) -> None:
        """Signal the recorder to stop after the current iteration."""
        self._running = False

    # ------------------------------------------------------------------
    # Internal: subscribe / consume / flush
    # ------------------------------------------------------------------

    async def _subscribe_all(self, ws: Any) -> None:
        """Send subscription messages for all configured watchlists."""
        for mode, instruments in self._subscriptions.items():
            if not instruments:
                continue
            action = _ACTION_MAP[mode]
            msg = json.dumps({"action": action, "instruments": instruments})
            await ws.send(msg)
            logger.info("Subscribed %s: %d instruments", mode, len(instruments))

    async def _consume(self, ws: Any) -> None:
        """Read messages until disconnected or stopped."""
        last_flush = asyncio.get_event_loop().time()

        async for raw in ws:
            if not self._running:
                break

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.debug("Non-JSON message: %s", raw[:100])
                continue

            self._process_tick(data)

            # Periodic flush
            now = asyncio.get_event_loop().time()
            if len(self._buffer) >= self._batch_size or (now - last_flush) >= self._flush_interval:
                self._flush()
                last_flush = now

    def _process_tick(self, data: dict[str, Any]) -> None:
        """Parse a WebSocket message into a tick tuple and buffer it."""
        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "")
        if not symbol or not exchange:
            return

        ts = datetime.now(timezone.utc)
        mode = self._detect_mode(data)

        depth_json = None
        if "bids" in data or "asks" in data:
            depth_json = json.dumps({"bids": data.get("bids", []), "asks": data.get("asks", [])})

        row = (
            ts,
            symbol,
            exchange,
            mode,
            data.get("ltp"),
            data.get("open"),
            data.get("high"),
            data.get("low"),
            data.get("close"),
            data.get("volume"),
            data.get("bid"),
            data.get("ask"),
            data.get("oi"),
            data.get("prev_close"),
            depth_json,
        )
        self._buffer.append(row)
        self._tick_count += 1

    @staticmethod
    def _detect_mode(data: dict[str, Any]) -> str:
        """Infer subscription mode from the fields present."""
        if "bids" in data or "asks" in data:
            return MODE_DEPTH
        if "bid" in data or "volume" in data:
            return MODE_QUOTE
        return MODE_LTP

    def _flush(self) -> None:
        """Write buffered ticks to DuckDB.

        Clears the buffer ONLY after a successful insert. On failure the batch is
        retained for the next flush (so a transient lock/disk error cannot
        silently discard captured ticks), bounded by ``_max_buffer`` so a
        persistent failure cannot grow memory without limit.
        """
        if not self._buffer:
            return
        try:
            if self._storage_lock is not None:
                with self._storage_lock:
                    self._storage.insert_ticks_batch(self._buffer)
            else:
                self._storage.insert_ticks_batch(self._buffer)
        except Exception as exc:
            logger.error(
                "Failed to flush %d ticks (retaining for retry): %s", len(self._buffer), exc,
            )
            if len(self._buffer) > self._max_buffer:
                dropped = len(self._buffer) - self._max_buffer
                del self._buffer[:dropped]
                logger.warning(
                    "Tick buffer exceeded %d; dropped %d oldest ticks", self._max_buffer, dropped,
                )
            return
        logger.debug("Flushed %d ticks to DuckDB", len(self._buffer))
        self._buffer.clear()
