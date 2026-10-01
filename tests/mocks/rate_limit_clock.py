"""Manually stepped, cross-event-loop clock for real limiter regression tests."""

from __future__ import annotations

import asyncio
import threading


class RateLimitClock:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self.now = 0.0
        self._sleepers = []
        self.admissions: list[float] = []

    def time(self) -> float:
        with self._condition:
            return self.now

    async def sleep(self, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._condition:
            entry = (self.now + seconds, loop, future)
            self._sleepers.append(entry)
            self._condition.notify_all()
        try:
            await future
        finally:
            with self._condition:
                if entry in self._sleepers:
                    self._sleepers.remove(entry)
                self._condition.notify_all()

    def admitted(self) -> None:
        with self._condition:
            self.admissions.append(self.now)
            self._condition.notify_all()

    def wait_for_settled(self, count: int) -> None:
        with self._condition:
            assert self._condition.wait_for(
                lambda: len(self._sleepers) + len(self.admissions) == count, timeout=5
            ), "limiter callers did not settle at admissions or sleeps"

    def advance(self, seconds: float) -> None:
        with self._condition:
            self.now += seconds
            ready = [entry for entry in self._sleepers if entry[0] <= self.now]
            self._sleepers = [entry for entry in self._sleepers if entry[0] > self.now]
        for _, loop, future in ready:
            loop.call_soon_threadsafe(self._wake, future)

    @staticmethod
    def _wake(future) -> None:
        if not future.done():
            future.set_result(None)
