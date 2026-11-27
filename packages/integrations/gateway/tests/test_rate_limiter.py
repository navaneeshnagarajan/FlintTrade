"""Tests for the per-broker API rate limiter (deterministic — injected clock)."""

from __future__ import annotations

import pytest

from types import SimpleNamespace

from flinttrade_core.order_rules import OrderBudgetExceeded
from flinttrade_gateway.rate_limiter import ORDER_RATE_LIMIT, BrokerRateLimiter

pytestmark = pytest.mark.unit

ORDER_RATE_TEXT = "Not placed. Limit is 10 orders per second per exchange. Retry in 1 second."
ORDER_RATE_HEADLINE = f"Regulation · {ORDER_RATE_TEXT}"


def _assert_order_rate_refused(excinfo) -> None:
    error = excinfo.value
    assert str(error) == ORDER_RATE_HEADLINE
    assert error.results[0].rule_id == "order-rate-threshold"
    assert error.results[0].message == ORDER_RATE_TEXT
    assert error.results[0].level == "block"



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
async def test_data_is_unlimited_when_no_limit_configured():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(100):
        await rl.acquire("dhan", "data")
    assert clock.slept == []


@pytest.mark.asyncio
async def test_orders_are_held_to_ten_per_second_without_configured_limits():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        await rl.acquire("dhan", "order")
    assert clock.slept == []
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order")
    _assert_order_rate_refused(excinfo)
    assert clock.slept == []


@pytest.mark.parametrize("configured", [20, 0, -1])
def test_order_override_above_the_limit_or_disabled_is_clamped(configured, caplog):
    with caplog.at_level("WARNING", logger="flinttrade.gateway.rate_limiter"):
        rl = BrokerRateLimiter.from_capabilities(
            {"dhan": _cap(order=10, data=5)}, overrides={"dhan": {"order": configured}},
        )
    assert rl._rate("dhan", "order") == ORDER_RATE_LIMIT == 10.0
    assert "clamped to 10 orders per second per exchange" in caplog.text


def test_capability_order_rate_above_the_limit_is_clamped():
    rl = BrokerRateLimiter.from_capabilities({"fast": _cap(order=25)})
    assert rl.snapshot()["fast"]["order"] == 10.0


@pytest.mark.parametrize("configured", [20.0, 0.0])
def test_settings_change_cannot_raise_or_disable_the_order_limit(configured):
    rl = BrokerRateLimiter({"dhan": {"order": 5.0}})
    rl.apply_override("dhan", order=configured)
    assert rl._rate("dhan", "order") == 10.0
    rl.apply_override("dhan", order=3.0)
    assert rl._rate("dhan", "order") == 3.0


@pytest.mark.asyncio
async def test_override_of_twenty_still_admits_ten_orders_per_second():
    clock = _FakeClock()
    rl = BrokerRateLimiter({"dhan": {"order": 20.0}}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        await rl.acquire("dhan", "order")
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order")
    _assert_order_rate_refused(excinfo)
    clock.now += 1.0
    await rl.acquire("dhan", "order")
    assert clock.slept == []


@pytest.mark.asyncio
async def test_refuses_once_the_order_burst_is_exhausted():
    clock = _FakeClock()
    rl = BrokerRateLimiter({"dhan": {"order": 2.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("dhan", "order")
    await rl.acquire("dhan", "order")
    assert clock.slept == []
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order")
    _assert_order_rate_refused(excinfo)
    clock.now += 0.5
    await rl.acquire("dhan", "order")
    assert clock.slept == []


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
    assert "_comment" not in rl.snapshot()  # comment key ignored, no crash


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
    assert rl._rate("newbroker", "order") == 10.0  # unset orders still get the order limit


@pytest.mark.asyncio
async def test_override_takes_effect_on_the_next_acquire():
    clock = _FakeClock()
    rl = BrokerRateLimiter({"x": {"order": 100.0}}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("x", "order")
    rl.apply_override("x", order=1.0)
    await rl.acquire("x", "order")  # Existing credit is capped to the new capacity.
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("x", "order")
    _assert_order_rate_refused(excinfo)
    assert clock.slept == []


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
    limiter = BrokerRateLimiter({"dhan": {"data": 1}}, clock=clock.time, sleep=clock.sleep)
    asyncio.run(limiter.acquire("dhan", "data"))

    async def acquire():
        await asyncio.wait_for(limiter.acquire("dhan", "data"), timeout=5)
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
    assert limiter.snapshot()["custom"] == {"order": 10, "data": 3, "quote": 0}


@pytest.mark.asyncio
async def test_nse_and_bse_each_get_ten_orders_per_second_per_broker():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        await rl.acquire("dhan", "order", exchange="NSE")
        await rl.acquire("dhan", "order", exchange="BSE")
        await rl.acquire("kotakneo", "order", exchange="NSE")
    assert clock.slept == []
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order", exchange="BSE")
    _assert_order_rate_refused(excinfo)
    with pytest.raises(OrderBudgetExceeded):
        await rl.acquire("dhan", "order", exchange="NSE")
    with pytest.raises(OrderBudgetExceeded):
        await rl.acquire("kotakneo", "order", exchange="NSE")
    assert clock.slept == []


async def test_an_eleventh_order_on_one_exchange_leaves_the_other_unaffected():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        rl.admit_order("dhan", exchange="NSE")
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        rl.admit_order("dhan", exchange="NSE")
    _assert_order_rate_refused(excinfo)
    rl.admit_order("dhan", exchange="BSE")
    assert clock.slept == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("cash", "derivatives"), [("NSE", "NFO"), ("NSE", "CDS"), ("BSE", "BFO"), ("BSE", "BCD")])
async def test_derivatives_orders_share_the_budget_of_their_exchange(cash, derivatives):
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(5):
        await rl.acquire("dhan", "order", exchange=cash)
        await rl.acquire("dhan", "order", exchange=derivatives.lower())
    assert clock.slept == []
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order", exchange=derivatives)
    _assert_order_rate_refused(excinfo)
    assert clock.slept == []


@pytest.mark.asyncio
async def test_order_override_applies_to_every_exchange_bucket():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    await rl.acquire("dhan", "order", exchange="NSE")
    await rl.acquire("dhan", "order", exchange="BSE")
    rl.apply_override("dhan", order=2)
    assert {key[2]: bucket.rate for key, bucket in rl._buckets.items()} == {"NSE": 2.0, "BSE": 2.0}


@pytest.mark.asyncio
async def test_an_order_with_no_exchange_is_refused_when_either_budget_is_spent():
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        await rl.acquire("dhan", "order", exchange="BSE")
    assert clock.slept == []
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        await rl.acquire("dhan", "order")
    _assert_order_rate_refused(excinfo)
    assert {key[2] for key in rl._buckets} == {"NSE", "BSE"}
    assert clock.slept == []


@pytest.mark.parametrize(
    ("action", "text"),
    [
        ("place", "Not placed. Limit is 10 orders per second per exchange. Retry in 1 second."),
        ("modify", "Not modified. Limit is 10 orders per second per exchange. Retry in 1 second."),
        ("cancel", "Not cancelled. Limit is 10 orders per second per exchange. Retry in 1 second."),
    ],
)
def test_admit_order_refusal_uses_the_action_message(action: str, text: str) -> None:
    clock = _FakeClock()
    rl = BrokerRateLimiter({}, clock=clock.time, sleep=clock.sleep)
    for _ in range(10):
        rl.admit_order("dhan", exchange="NSE")
    with pytest.raises(OrderBudgetExceeded) as excinfo:
        rl.admit_order("dhan", exchange="NSE", action=action)
    error = excinfo.value
    assert str(error) == f"Regulation · {text}"
    assert error.results[0].rule_id == "order-rate-threshold"
    assert error.results[0].message == text
    assert error.results[0].level == "block"
