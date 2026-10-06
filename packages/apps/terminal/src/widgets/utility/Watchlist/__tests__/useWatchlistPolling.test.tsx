import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
vi.mock("@/services/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/services/api")>(),
  getMultiQuotes: vi.fn(),
}));
vi.mock("@/lib/market", () => ({ isMarketHours: () => true }));
import { getMultiQuotes } from "@/services/api";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
import { useWatchlistPolling } from "../useWatchlistPolling";
import { SPARK_MAX, type WatchlistItem } from "../types";

type Response = Awaited<ReturnType<typeof getMultiQuotes>>;
interface Request {
  signal: AbortSignal;
  scope: string;
  symbols: WatchlistItem[];
  resolve: (response: Response) => void;
  reject: (error: Error) => void;
}
const requests: Request[] = [];
const instrument = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
function account(id: string): BrokerAccount {
  return {
    source: "native", broker: "dhan", account_id: id, label: id,
    status: "connected", connected_at: null, error_message: null, is_primary: false,
  };
}
const accountA = account("A");
const accountB = account("B");
function response(price: number, symbol = "NIFTY", exchange = "NSE_INDEX"): Response {
  return { results: [{ symbol, exchange, data: {
    symbol, exchange, ltp: price, open: price, high: price, low: price, close: price, volume: 1,
  } }] };
}

beforeEach(() => {
  vi.useFakeTimers();
  requests.length = 0;
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ accounts: [accountA, accountB], activeAccountId: brokerAccountKey(accountA) });
  vi.mocked(getMultiQuotes).mockImplementation((symbols, signal, scope) => {
    if (!signal || !scope) throw new Error("Polling must capture signal and scope");
    return new Promise((resolve, reject) => requests.push({ symbols, signal, scope, resolve, reject }));
  });
});
afterEach(() => vi.useRealTimers());

describe("Watchlist quote authority", () => {
  it("captures exact account scope and clears its prices and spark history on account change", async () => {
    const { result } = renderHook(() => useWatchlistPolling(instrument));
    expect(requests[0].scope).toBe("live:native:dhan:A");
    await act(async () => requests[0].resolve(response(101)));
    expect(result.current.quotes["NIFTY:NSE_INDEX"].ltp).toBe(101);
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual([101]);
    act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB)));
    expect(result.current.quotes).toEqual({});
    expect(result.current.sparkHistory).toEqual({});
    expect(result.current.isLoading).toBe(true);
    expect(requests[0].signal.aborted).toBe(true);
    expect(requests[1].scope).toBe("live:native:dhan:B");
    await act(async () => requests[1].resolve(response(202)));
    expect(result.current.quotes["NIFTY:NSE_INDEX"].ltp).toBe(202);
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual([202]);
  });

  it("discards an account-A response resolving after account-B data", async () => {
    const { result } = renderHook(() => useWatchlistPolling(instrument));
    act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB)));
    await act(async () => requests[1].resolve(response(202)));
    await act(async () => requests[0].resolve(response(101)));
    expect(result.current.quotes["NIFTY:NSE_INDEX"].ltp).toBe(202);
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual([202]);
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(requests).toHaveLength(3);
    expect(requests[2].scope).toBe("live:native:dhan:B");
  });

  it("clears source errors and refuses the old rejection after switching to Example", async () => {
    const { result } = renderHook(() => useWatchlistPolling(instrument));
    await act(async () => requests[0].reject(new Error("Account A unavailable")));
    expect(result.current.fetchError).toBe("Account A unavailable");
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    act(() => useModeStore.getState().setMode("explore"));
    expect(result.current.fetchError).toBeNull();
    expect(result.current.quotes).toEqual({});
    expect(requests[2].scope).toBe("explore:mock");
    await act(async () => requests[2].resolve(response(300)));
    await act(async () => requests[1].reject(new Error("Late account-A failure")));
    expect(result.current.quotes["NIFTY:NSE_INDEX"].ltp).toBe(300);
    expect(result.current.fetchError).toBeNull();
  });

  it("rejects an Example response after a Practice transition without preserving its samples", async () => {
    useModeStore.setState({ mode: "explore" });
    const { result } = renderHook(() => useWatchlistPolling(instrument));
    act(() => useModeStore.getState().setMode("practice"));
    expect(requests[1].scope).toBe("practice:native:dhan:A");
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => requests[0].resolve(response(111)));
    expect(result.current.quotes).toEqual({});
    expect(result.current.sparkHistory).toEqual({});
    await act(async () => requests[1].resolve(response(222)));
    expect(result.current.quotes["NIFTY:NSE_INDEX"].ltp).toBe(222);
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual([222]);
  });

  it("restarts after StrictMode cleanup and admits only the surviving request", async () => {
    const { result, unmount } = renderHook(() => useWatchlistPolling(instrument), { reactStrictMode: true });
    expect(requests).toHaveLength(2);
    expect(requests[0].signal.aborted).toBe(true);
    expect(requests[1].signal.aborted).toBe(false);
    await act(async () => requests[0].resolve(response(111)));
    expect(result.current.quotes).toEqual({});
    await act(async () => requests[1].resolve(response(222)));
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual([222]);
    unmount();
    expect(requests[1].signal.aborted).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(requests).toHaveLength(2);
  });

  it("keeps reads sequential even when a quote request takes several poll intervals", async () => {
    renderHook(() => useWatchlistPolling(instrument));
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(requests).toHaveLength(1);
    await act(async () => requests[0].resolve(response(100)));
    await act(async () => vi.advanceTimersByTimeAsync(4_999));
    expect(requests).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(requests).toHaveLength(2);
  });

  it("bounds admitted history and never assigns a named quote to another instrument", async () => {
    const { result } = renderHook(() => useWatchlistPolling(instrument));
    await act(async () => requests[0].resolve(response(999, "OTHER", "NSE")));
    expect(result.current.quotes).toEqual({});
    for (let index = 0; index < SPARK_MAX + 3; index++) {
      await act(async () => vi.advanceTimersByTimeAsync(5_000));
      await act(async () => requests.at(-1)!.resolve(response(100 + index)));
    }
    expect(result.current.sparkHistory["NIFTY:NSE_INDEX"]).toEqual(
      Array.from({ length: SPARK_MAX }, (_, index) => 103 + index),
    );
  });

  it("aborts a removed tab's read and returns an empty non-loading state", async () => {
    const { result, rerender } = renderHook(({ items }) => useWatchlistPolling(items), { initialProps: { items: instrument } });
    rerender({ items: [] });
    expect(requests[0].signal.aborted).toBe(true);
    expect(result.current).toMatchObject({ quotes: {}, sparkHistory: {}, fetchError: null, isLoading: false });
    await act(async () => requests[0].resolve(response(123)));
    expect(result.current.quotes).toEqual({});
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(requests).toHaveLength(1);
  });
});
