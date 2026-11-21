import { describe, expect, it, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { UNKNOWN_SUBMIT_SETTLE_READ_MS, useScheduledSettleRead } from "@/hooks/useOrderSubmitGuard";
import { UNKNOWN_SUBMIT_SETTLE_MS, type UnknownOrderSubmit } from "@/lib/orderSubmitGuard";

function lostAt(receivedAt: number): UnknownOrderSubmit {
  return {
    key: "NFO:NIFTY10APR2625000CE",
    symbol: "NIFTY10APR2625000CE",
    exchange: "NFO",
    action: "BUY",
    receivedAt,
    listUpdatedAt: 0,
    legs: { entry: "unknown" },
  } as UnknownOrderSubmit;
}

describe("useScheduledSettleRead", () => {
  it("reads the order book once, just after the settle delay", async () => {
    const refetch = vi.fn(() => Promise.resolve());
    const receivedAt = Date.now();
    renderHook(() => useScheduledSettleRead([lostAt(receivedAt)], false, refetch));
    expect(UNKNOWN_SUBMIT_SETTLE_READ_MS).toBeGreaterThan(UNKNOWN_SUBMIT_SETTLE_MS);
    await new Promise((resolve) => setTimeout(resolve, UNKNOWN_SUBMIT_SETTLE_MS - 200));
    expect(refetch).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(refetch).toHaveBeenCalledTimes(1), { timeout: 1_500, interval: 20 });
    expect(Date.now() - receivedAt).toBeGreaterThanOrEqual(UNKNOWN_SUBMIT_SETTLE_MS);
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(refetch).toHaveBeenCalledTimes(1);
  }, 10_000);

  it("waits for a read already in flight, then starts a fresh one", async () => {
    const calls: number[] = [];
    const refetch = vi.fn(() => {
      calls.push(Date.now());
      return new Promise<void>((resolve) => setTimeout(resolve, 50));
    });
    renderHook(() => useScheduledSettleRead([lostAt(Date.now() - UNKNOWN_SUBMIT_SETTLE_READ_MS)], true, refetch));
    await vi.waitFor(() => expect(refetch).toHaveBeenCalledTimes(2), { timeout: 1_000, interval: 10 });
    expect(calls[1]! - calls[0]!).toBeGreaterThanOrEqual(40);
  });

  it("schedules nothing without a lost submit", async () => {
    const refetch = vi.fn(() => Promise.resolve());
    renderHook(() => useScheduledSettleRead([], false, refetch));
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(refetch).not.toHaveBeenCalled();
  });
});
