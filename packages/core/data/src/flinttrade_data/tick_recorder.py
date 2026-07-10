"""WebSocket tick recorder — connects to OpenAlgo WS and stores ticks in DuckDB.

Supports all exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, DELTA.
MCX ticks arrive until 11:55 PM IST, DELTA ticks are 24/7.

Protocol:
  authenticate → API-key authentication
  subscribe    → LTP, quote, or depth market data
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Callable

import websockets
import websockets.exceptions

from .storage import StorageManager

logger = logging.getLogger("flinttrade.data.tick_recorder")

_DEFAULT_WS_URL = f"ws://127.0.0.1:{os.getenv('OPENALGO_WS_PORT', '8765')}"

# Subscription modes
MODE_LTP = "ltp"
MODE_QUOTE = "quote"
MODE_DEPTH = "depth"

_MODE_LABELS = {
    MODE_LTP: "LTP",
    MODE_QUOTE: "QUOTE",
    MODE_DEPTH: "DEPTH",
}
_NUMERIC_MODES = {1: MODE_LTP, 2: MODE_QUOTE, 3: MODE_DEPTH}

LtpSink = Callable[[str, str, float, int], None]


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
        orderflow_aggregator: Any | None = None,
        api_key: str = "",
        ltp_sink: LtpSink | None = None,
        auth_response_timeout: float = 10.0,
    ) -> None:
        self._storage = storage
        # Optional live order-flow aggregator fed from each tick (None = off).
        self._orderflow = orderflow_aggregator
        self._ws_url = ws_url or _DEFAULT_WS_URL
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        # Serialises access to the (single) DuckDB connection this recorder shares
        # with the nightly maintenance job, which runs on the scheduler thread —
        # DuckDB connections are not safe for concurrent use. None = no sharing.
        self._storage_lock = storage_lock
        self._api_key = api_key
        self._ltp_sink = ltp_sink
        self._auth_response_timeout = auth_response_timeout
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
        self._stop_event: asyncio.Event | None = None
        self._connected = False
        self._last_error = ""
        self._tick_count = 0

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def is_running(self) -> bool:
        """Whether the run() loop is active (set on start, cleared by stop())."""
        return self._running

    @property
    def is_connected(self) -> bool:
        """Whether the recorder has an authenticated WebSocket connection."""
        return self._connected

    @property
    def last_error(self) -> str:
        """Most recent sanitised OpenAlgo connection or control error."""
        return self._last_error

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
            raise ValueError(f"Invalid mode: {mode}. Use {list(_MODE_LABELS)}")
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
        self._stop_event = asyncio.Event()
        delay = self._reconnect_delay

        try:
            while self._running:
                try:
                    try:
                        async with websockets.connect(self._ws_url) as ws:
                            logger.info("WebSocket connected: %s", self._sanitise(self._ws_url))
                            await self._authenticate(ws)
                            self._connected = True
                            self._last_error = ""
                            delay = self._reconnect_delay  # reset on successful authentication

                            await self._subscribe_all(ws)
                            await self._consume(ws)
                    finally:
                        self._connected = False

                except (
                    websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.InvalidURI,
                    OSError,
                    RuntimeError,
                ) as exc:
                    self._set_last_error(exc)
                else:
                    if not self._running:
                        break
                    self._set_last_error("WebSocket stream ended")

                if not self._running:
                    break
                logger.warning(
                    "WebSocket disconnected: %s; reconnecting in %.0fs",
                    self._sanitise(self._last_error),
                    delay,
                )
                await self._wait_for_reconnect_delay(delay)
                delay = min(delay * 2, self._max_reconnect_delay)
        finally:
            self._connected = False
            self._running = False
            self._stop_event = None
            self._flush()
            logger.info("TickRecorder stopped. Total ticks recorded: %d", self._tick_count)

    def stop(self) -> None:
        """Signal the recorder to stop after the current iteration."""
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()

    # ------------------------------------------------------------------
    # Internal: subscribe / consume / flush
    # ------------------------------------------------------------------

    async def _authenticate(self, ws: Any) -> None:
        """Authenticate and wait for the OpenAlgo control response."""
        await ws.send(json.dumps({"action": "authenticate", "api_key": self._api_key}))
        try:
            raw_response = await asyncio.wait_for(ws.recv(), timeout=self._auth_response_timeout)
            response = json.loads(raw_response)
        except TimeoutError as exc:
            self._set_last_error("Authentication response timed out")
            raise RuntimeError(self._last_error) from exc
        except UnicodeDecodeError as exc:
            self._set_last_error("Invalid authentication response: invalid UTF-8")
            raise RuntimeError(self._last_error) from exc
        except (TypeError, json.JSONDecodeError) as exc:
            self._set_last_error("Invalid authentication response")
            raise RuntimeError(self._last_error) from exc

        if not isinstance(response, dict):
            self._set_last_error("Invalid authentication response: expected JSON object")
            raise RuntimeError(self._last_error)

        status = str(response.get("status", "")).lower()
        if status not in {"authenticated", "success"}:
            self._set_last_error(response.get("message") or response.get("error") or "Authentication failed")
            raise RuntimeError(self._last_error)

    async def _subscribe_all(self, ws: Any) -> None:
        """Send subscription messages for all configured watchlists."""
        for mode, instruments in self._subscriptions.items():
            if not instruments:
                continue
            msg = json.dumps({"action": "subscribe", "symbols": instruments, "mode": _MODE_LABELS[mode]})
            await ws.send(msg)
            logger.info("Subscribed %s: %d instruments", self._sanitise(mode), len(instruments))

    async def _consume(self, ws: Any) -> None:
        """Read messages until disconnected or stopped."""
        last_flush = asyncio.get_event_loop().time()

        async for raw in ws:
            if not self._running:
                break

            try:
                data = json.loads(raw)
            except UnicodeDecodeError:
                self._set_last_error("Invalid WebSocket message: invalid UTF-8")
                logger.debug("Invalid UTF-8 message: %s", self._sanitise(raw)[:100])
                continue
            except (TypeError, json.JSONDecodeError):
                logger.debug("Non-JSON message: %s", self._sanitise(raw)[:100])
                continue

            if not isinstance(data, dict):
                self._set_last_error("Invalid WebSocket message: expected JSON object")
                logger.debug("Ignored non-object JSON message: %s", self._sanitise(raw)[:100])
                continue

            self._process_tick(data)

            # Periodic flush
            now = asyncio.get_event_loop().time()
            if len(self._buffer) >= self._batch_size or (now - last_flush) >= self._flush_interval:
                self._flush()
                last_flush = now

    def _process_tick(self, data: dict[str, Any]) -> None:
        """Parse a WebSocket message into a tick tuple and buffer it."""
        if self._handle_control_message(data):
            return

        symbol = data.get("symbol", "")
        exchange = data.get("exchange", "")
        if not symbol or not exchange:
            return

        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        ts = datetime.now(timezone.utc)
        mode = self._detect_mode(payload, data.get("mode"))

        depth_json = None
        if "depth" in payload:
            depth_json = json.dumps(payload["depth"])
        elif "bids" in payload or "asks" in payload:
            depth_json = json.dumps({"bids": payload.get("bids", []), "asks": payload.get("asks", [])})

        row = (
            ts,
            symbol,
            exchange,
            mode,
            payload.get("ltp"),
            payload.get("open"),
            payload.get("high"),
            payload.get("low"),
            payload.get("close"),
            payload.get("volume"),
            payload.get("bid"),
            payload.get("ask"),
            payload.get("oi"),
            payload.get("prev_close"),
            depth_json,
        )
        self._buffer.append(row)
        self._tick_count += 1

        self._dispatch_ltp(exchange, symbol, payload.get("ltp"), payload.get("volume"))

        # Feed the live order-flow aggregator (best-effort — must never break
        # tick recording). LTP + cumulative volume drive the footprint; bid/ask
        # sharpen the aggressor classification when present.
        if self._orderflow is not None:
            ltp = payload.get("ltp")
            volume = payload.get("volume")
            if ltp is not None and volume is not None:
                bid = payload.get("bid")
                ask = payload.get("ask")
                try:
                    self._orderflow.feed_market_tick(
                        symbol,
                        float(ltp),
                        int(volume),
                        bid=float(bid) if bid is not None else None,
                        ask=float(ask) if ask is not None else None,
                    )
                except Exception as exc:  # noqa: BLE001 - feeding never breaks recording
                    logger.debug(
                        "order-flow feed skipped for %s: %s",
                        self._sanitise(symbol),
                        self._sanitise(exc),
                    )

    @staticmethod
    def _detect_mode(data: dict[str, Any], reported_mode: Any = None) -> str:
        """Infer subscription mode from the fields present."""
        if isinstance(reported_mode, str) and reported_mode.lower() in _MODE_LABELS:
            return reported_mode.lower()
        if type(reported_mode) is int and reported_mode in _NUMERIC_MODES:
            return _NUMERIC_MODES[reported_mode]
        if "depth" in data or "bids" in data or "asks" in data:
            return MODE_DEPTH
        if "bid" in data or "volume" in data:
            return MODE_QUOTE
        return MODE_LTP

    def _dispatch_ltp(self, exchange: str, symbol: str, ltp: Any, volume: Any) -> None:
        """Best-effort synchronous delivery of a valid LTP to the signal sink."""
        if self._ltp_sink is None:
            return
        try:
            ltp_value = float(ltp)
        except (TypeError, ValueError):
            return
        if not math.isfinite(ltp_value) or ltp_value <= 0:
            return
        try:
            volume_value = max(0, int(volume)) if volume is not None else 0
        except (TypeError, ValueError, OverflowError):
            volume_value = 0
        try:
            self._ltp_sink(exchange, symbol, ltp_value, volume_value)
        except Exception as exc:  # noqa: BLE001 - callbacks must not interrupt recording
            logger.debug(
                "LTP sink skipped for %s:%s: %s",
                self._sanitise(exchange),
                self._sanitise(symbol),
                self._sanitise(exc),
            )

    def _handle_control_message(self, data: dict[str, Any]) -> bool:
        """Record OpenAlgo control errors without treating them as market ticks."""
        status = str(data.get("status", "")).lower()
        if data.get("type") == "subscribe" and status == "partial":
            subscriptions = data.get("subscriptions")
            if not isinstance(subscriptions, list):
                self._set_last_error("Partial subscription failure: invalid subscriptions response")
                return True
            failures = [
                entry
                for entry in subscriptions
                if isinstance(entry, dict) and str(entry.get("status", "")).lower() in {"error", "failed", "failure"}
            ]
            details = []
            for failure in failures:
                identity = ":".join(
                    part for part in (str(failure.get("exchange", "")), str(failure.get("symbol", ""))) if part
                )
                message = failure.get("message") or failure.get("error") or "subscription failed"
                details.append(f"{identity}: {message}" if identity else str(message))
            self._set_last_error(
                "Partial subscription failure: " + "; ".join(details)
                if details
                else data.get("message") or "Partial subscription failure"
            )
            return True
        if data.get("type") == "error" or status in {"error", "failed", "failure"}:
            self._set_last_error(data.get("message") or data.get("error") or "OpenAlgo control error")
            return True
        return False

    def _set_last_error(self, message: Any) -> None:
        """Store an observable error while preventing configured credentials leaking."""
        self._last_error = self._sanitise(message)

    def _sanitise(self, value: Any) -> str:
        """Return display-safe text without changing recorder state."""
        text = str(value)
        if self._api_key:
            text = text.replace(self._api_key, "[redacted]")
        return text

    async def _wait_for_reconnect_delay(self, delay: float) -> None:
        """Wait for backoff completion or an explicit stop, whichever comes first."""
        stop_event = self._stop_event
        if stop_event is None:
            await asyncio.sleep(delay)
            return

        delay_task = asyncio.create_task(asyncio.sleep(delay))
        stop_task = asyncio.create_task(stop_event.wait())
        tasks = (delay_task, stop_task)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
                # This blocking lock is shared with the nightly maintenance job
                # (scheduler thread). If that job is mid-CHECKPOINT the event loop
                # briefly parks here — bounded and acceptable: maintenance runs
                # off-market (00:30 IST) when tick flow is idle, and the insert is
                # atomic so a retained batch is safe to retry.
                with self._storage_lock:
                    self._storage.insert_ticks_batch(self._buffer)
            else:
                self._storage.insert_ticks_batch(self._buffer)
        except Exception as exc:
            logger.error(
                "Failed to flush %d ticks (retaining for retry): %s",
                len(self._buffer),
                self._sanitise(exc),
            )
            if len(self._buffer) > self._max_buffer:
                dropped = len(self._buffer) - self._max_buffer
                del self._buffer[:dropped]
                logger.warning(
                    "Tick buffer exceeded %d; dropped %d oldest ticks",
                    self._max_buffer,
                    dropped,
                )
            return
        logger.debug("Flushed %d ticks to DuckDB", len(self._buffer))
        self._buffer.clear()
