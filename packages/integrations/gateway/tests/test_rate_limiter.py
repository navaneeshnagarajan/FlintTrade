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
    clock = _FakeClock()
    rl = BrokerRateLimiter({"x": {"order": 100.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("x", "order")
    rl.apply_override("x", order=1.0)
    await rl.acquire("x", "order")  # Existing credit is capped to the new capacity.
    await rl.acquire("x", "order")
    assert clock.slept == [1.0]


@pytest.mark.asyncio
async def test_every_waiting_acquire_consumes_its_refilled_token():
    clock = _FakeClock()
    limiter = BrokerRateLimiter({"dhan": {"data": 1}}, clock=clock.time, sleep=clock.sleep)
    admitted = []
    for _ in range(4):
        await limiter.acquire("dhan", "data")
        admitted.append(clock.now)
    assert admitted == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_concurrent_waiters_recompete_for_each_refilled_token():
    import asyncio

    from tests.mocks.rate_limit_clock import RateLimitClock

    clock = RateLimitClock()
    limiter = BrokerRateLimiter({"dhan": {"data": 1}}, clock=clock.time, sleep=clock.sleep)
    await limiter.acquire("dhan", "data")

    async def acquire():
        await limiter.acquire("dhan", "data")
        clock.admitted()

    tasks = [asyncio.create_task(acquire()) for _ in range(3)]
    try:
        await asyncio.to_thread(clock.wait_for_settled, 3)
        for expected in range(1, 4):
            clock.advance(1)
            await asyncio.to_thread(clock.wait_for_settled, 3)
            assert clock.admissions == list(range(1, expected + 1))
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_concurrent_event_loops_share_one_token_budget():
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from tests.mocks.rate_limit_clock import RateLimitClock

    clock = RateLimitClock()
    limiter = BrokerRateLimiter({"dhan": {"order": 1}}, clock=clock.time, sleep=clock.sleep)
    asyncio.run(limiter.acquire("dhan"))

    async def acquire():
        await asyncio.wait_for(limiter.acquire("dhan"), timeout=5)
        clock.admitted()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(asyncio.run, acquire()) for _ in range(3)]
        clock.wait_for_settled(3)
        for expected in range(1, 4):
            clock.advance(1)
            clock.wait_for_settled(3)
            assert clock.admissions == list(range(1, expected + 1))
        for future in futures:
            future.result(timeout=5)


@pytest.mark.asyncio
async def test_fractional_positive_rate_can_admit_one_call_then_spaces_refills():
    clock = _FakeClock()
    limiter = BrokerRateLimiter({"dhan": {"data": 0.5}}, clock=clock.time, sleep=clock.sleep)
    admitted = []
    for _ in range(3):
        await limiter.acquire("dhan", "data")
        admitted.append(clock.now)
    assert admitted == [0, 2, 4]


@pytest.mark.asyncio
async def test_quote_consumes_both_quote_and_generic_data_budgets():
    clock = _FakeClock()
    limiter = BrokerRateLimiter(
        {"dhan": {"data": 1, "quote": 2}}, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire("dhan", "quote")
    await limiter.acquire("dhan", "data")
    assert clock.now == 1
    await limiter.acquire("dhan", "quote")
    assert clock.now == 2


def test_from_capabilities_retains_the_quote_limit():
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES

    limiter = BrokerRateLimiter.from_capabilities({"dhan": DHAN_CAPABILITIES})
    assert limiter.snapshot()["dhan"]["quote"] == 1


@pytest.mark.asyncio
async def test_override_does_not_mint_fresh_tokens_for_an_empty_bucket():
    clock = _FakeClock()
    limiter = BrokerRateLimiter({"dhan": {"data": 1}}, clock=clock.time, sleep=clock.sleep)
    await limiter.acquire("dhan", "data")
    limiter.apply_override("dhan", data=2)
    await limiter.acquire("dhan", "data")
    assert clock.now == 0.5


@pytest.mark.asyncio
async def test_waiter_uses_rate_override_after_its_original_sleep():
    import asyncio

    from tests.mocks.rate_limit_clock import RateLimitClock

    clock = RateLimitClock()
    limiter = BrokerRateLimiter({"dhan": {"data": 1}}, clock=clock.time, sleep=clock.sleep)
    await limiter.acquire("dhan", "data")

    async def acquire():
        await limiter.acquire("dhan", "data")
        clock.admitted()

    task = asyncio.create_task(acquire())
    try:
        await asyncio.to_thread(clock.wait_for_settled, 1)
        limiter.apply_override("dhan", data=0.5)
        clock.advance(1)
        await asyncio.to_thread(clock.wait_for_settled, 1)
        assert clock.admissions == []
        clock.advance(1)
        await task
        assert clock.admissions == [2]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_quote_waiter_does_not_consume_partial_data_budget():
    import asyncio

    from tests.mocks.rate_limit_clock import RateLimitClock

    clock = RateLimitClock()
    limiter = BrokerRateLimiter(
        {"dhan": {"data": 5, "quote": 1}}, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire("dhan", "quote")
    task = asyncio.create_task(limiter.acquire("dhan", "quote"))
    await asyncio.to_thread(clock.wait_for_settled, 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(4):
        await asyncio.wait_for(limiter.acquire("dhan", "data"), timeout=1)
    assert clock.time() == 0


@pytest.mark.asyncio
async def test_quote_waiting_on_generic_budget_does_not_spend_its_quote_token_early():
    import asyncio

    from tests.mocks.rate_limit_clock import RateLimitClock

    clock = RateLimitClock()
    limiter = BrokerRateLimiter(
        {"dhan": {"data": 1, "quote": 1}}, clock=clock.time, sleep=clock.sleep
    )
    await limiter.acquire("dhan", "data")

    async def acquire():
        await limiter.acquire("dhan", "quote")
        clock.admitted()

    tasks = [asyncio.create_task(acquire()) for _ in range(2)]
    try:
        await asyncio.to_thread(clock.wait_for_settled, 2)
        for expected in range(1, 3):
            clock.advance(1)
            await asyncio.to_thread(clock.wait_for_settled, 2)
            assert clock.admissions == list(range(1, expected + 1))
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_rates_are_rejected_instead_of_bypassing_or_stalling(rate):
    with pytest.raises(ValueError, match="finite"):
        BrokerRateLimiter({"dhan": {"data": rate}})
    limiter = BrokerRateLimiter({"dhan": {"data": 1}})
    with pytest.raises(ValueError, match="finite"):
        limiter.apply_override("dhan", data=rate)
    assert limiter.snapshot()["dhan"]["data"] == 1


@pytest.mark.parametrize("invalid", ["inf", "1e309", "nan", "not-a-rate", None, 10 ** 400])
def test_invalid_persisted_override_keeps_capability_caps_and_other_overrides(invalid):
    from flinttrade_gateway.brokers.dhan import DHAN_CAPABILITIES

    limiter = BrokerRateLimiter.from_capabilities(
        {"dhan": DHAN_CAPABILITIES},
        overrides={"dhan": {"data": invalid, "order": 2}, "custom": {"data": 3, "quote": invalid}},
    )
    assert limiter.snapshot()["dhan"] == {"order": 2, "data": 5, "quote": 1}
    assert limiter.snapshot()["custom"] == {"order": 0, "data": 3, "quote": 0}
