"""Tests for the per-broker API rate limiter (deterministic — injected clock)."""

from __future__ import annotations

import pytest

from types import SimpleNamespace

from flinttrade_gateway.rate_limiter import BrokerRateLimiter

pytestmark = pytest.mark.unit


def _cap(order=None, data=None):
    # from_capabilities only reads these two attrs.
    return SimpleNamespace(rate_limit_orders_per_sec=order, rate_limit_data_per_sec=data)


class _FakeClock:
    """Manual monotonic clock + a sleep that advances it (no real time)."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_unlimited_when_no_limit_configured():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(100):
        await rl.acquire("dhan", "order")
    assert clock.slept == []  # never throttled


@pytest.mark.asyncio
async def test_throttles_once_burst_is_exhausted():
    clock = _FakeClock()
    # 2 orders/sec: a burst of 2 is free, the 3rd waits ~0.5s for a refill.
    rl = BrokerRateLimiter({"dhan": {"order": 2.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("dhan", "order")
    await rl.acquire("dhan", "order")
    assert clock.slept == []  # burst consumed, no wait yet
    await rl.acquire("dhan", "order")
    assert len(clock.slept) == 1 and clock.slept[0] == pytest.approx(0.5, abs=1e-6)


@pytest.mark.asyncio
async def test_refills_over_time():
    clock = _FakeClock()
    rl = BrokerRateLimiter({"dhan": {"order": 1.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("dhan", "order")  # consumes the 1-token burst
    clock.now += 1.0  # a second passes → one token refilled
    await rl.acquire("dhan", "order")
    assert clock.slept == []  # the refill covered it, no wait


@pytest.mark.asyncio
async def test_order_and_data_buckets_are_independent():
    clock = _FakeClock()
    rl = BrokerRateLimiter({"dhan": {"order": 1.0, "data": 1.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("dhan", "order")
    await rl.acquire("dhan", "data")  # different bucket — not throttled by the order one
    assert clock.slept == []


def test_from_capabilities_applies_overrides():
    caps = {
        "dhan": _cap(order=25, data=10),
        "kotakneo": _cap(order=10),
    }
    rl = BrokerRateLimiter.from_capabilities(caps, overrides={"dhan": {"order": 5}})
    assert rl._rate("dhan", "order") == 5.0  # override wins
    assert rl._rate("dhan", "data") == 10.0  # capability default kept
    assert rl._rate("kotakneo", "order") == 10.0
    assert rl._rate("kotakneo", "data") == 0.0  # no data limit → unlimited


def test_from_capabilities_tolerates_comment_keys():
    # workspace.json documents config blocks with a "_comment" string key. The
    # rate_limits override block carries one too, so from_capabilities must skip
    # non-dict override values instead of crashing on `"_comment".get(...)`.
    caps = {"dhan": _cap(order=25, data=10)}
    overrides = {
        "_comment": "Per-broker rate-limit overrides in requests/sec.",
        "dhan": {"order": 5},
    }
    rl = BrokerRateLimiter.from_capabilities(caps, overrides=overrides)
    assert rl._rate("dhan", "order") == 5.0  # real override still applied
    assert rl._rate("_comment", "order") == 0.0  # comment key ignored, no crash


def test_snapshot_returns_a_deep_copy():
    rl = BrokerRateLimiter({"dhan": {"order": 5.0, "data": 2.0}})
    snap = rl.snapshot()
    assert snap == {"dhan": {"order": 5.0, "data": 2.0}}
    snap["dhan"]["order"] = 999.0  # mutating the copy must not affect the limiter
    assert rl._rate("dhan", "order") == 5.0


def test_apply_override_updates_only_specified_kinds():
    rl = BrokerRateLimiter({"dhan": {"order": 5.0, "data": 2.0}})
    rl.apply_override("dhan", order=8.0)
    assert rl._rate("dhan", "order") == 8.0
    assert rl._rate("dhan", "data") == 2.0  # untouched
    # A previously-unknown broker can be configured too.
    rl.apply_override("newbroker", data=3.0)
    assert rl._rate("newbroker", "data") == 3.0
    assert rl._rate("newbroker", "order") == 0.0  # unset → unlimited


@pytest.mark.asyncio
async def test_override_takes_effect_on_the_next_acquire():
    # Lowering a limit must change throttle behaviour live (acquire rebuilds the
    # bucket when the configured rate changes).
    t = {"now": 0.0}
    slept: list[float] = []
    rl = BrokerRateLimiter(
        {"x": {"order": 100.0}},
        clock=lambda: t["now"],
        sleep=lambda s: slept.append(s) or _noop(),
    )
    await rl.acquire("x", "order")  # consumes from the 100/s bucket, no wait
    rl.apply_override("x", order=1.0)  # throttle hard
    await rl.acquire("x", "order")  # new 1/s bucket starts full → 1 token, no wait
    await rl.acquire("x", "order")  # second within the same instant → must wait
    assert slept and slept[-1] > 0


async def _noop() -> None:
    return None
