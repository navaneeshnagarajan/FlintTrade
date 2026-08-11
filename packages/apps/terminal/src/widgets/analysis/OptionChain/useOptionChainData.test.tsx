import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
}));
const dataScopeState = vi.hoisted(() => ({ value: "live:native:upstox:U1" }));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => dataScopeState.value,
  useMarketDataScope: () => dataScopeState.value,
}));

import { useOptionChainData } from "./useOptionChainData";
import type { SymbolDef } from "./types";

const NIFTY: SymbolDef = {
  label: "NIFTY",
  exchange: "NFO",
  spotSymbol: "NIFTY",
  spotExchange: "NSE_INDEX",
};

const BANKNIFTY: SymbolDef = {
  label: "BANKNIFTY",
  exchange: "NFO",
  spotSymbol: "BANKNIFTY",
  spotExchange: "NSE_INDEX",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("useOptionChainData", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    dataScopeState.value = "live:native:upstox:U1";
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2026-07-30"] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000, close: 24900 });
  });

  it("does not turn omitted OI into zero when deriving PCR", async () => {
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { ltp: 100 }, pe: { ltp: 90, oi: 100 } },
        { strike: 25100, ce: { ltp: 50, oi: 50 }, pe: { ltp: 140, oi: 50 } },
      ],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());

    expect(result.current.strikes[0]?.call).not.toHaveProperty("oi");
    expect(result.current.totalCallOI).toBeNull();
    expect(result.current.totalPutOI).toBe(150);
    expect(result.current.computedPCR).toBeNull();
    expect(result.current.pcr).toBeNull();
  });

  it("preserves explicit zero OI when deriving PCR", async () => {
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { oi: 10 }, pe: { oi: 0 } },
      ],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());

    expect(result.current.strikes[0]?.put?.oi).toBe(0);
    expect(result.current.totalCallOI).toBe(10);
    expect(result.current.totalPutOI).toBe(0);
    expect(result.current.computedPCR).toBe(0);
    expect(result.current.pcr).toBe(0);
  });

  it("withholds a legacy response PCR when call OI has a zero denominator", async () => {
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      pcr: 0,
      chain: [
        { strike: 25000, ce: { oi: 0 }, pe: { oi: 100 } },
      ],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());

    expect(result.current.totalCallOI).toBe(0);
    expect(result.current.totalPutOI).toBe(100);
    expect(result.current.computedPCR).toBeNull();
    expect(result.current.pcr).toBeNull();
  });

  it("drops legacy rows without a valid positive strike instead of creating strike zero", async () => {
    apiMocks.getOptionChain.mockResolvedValue({
      calls: [
        { oi: 100 },
        { strike: 0, oi: 100 },
        { strike: true, oi: 100 },
        { strike_price: 25000, oi: 0 },
      ],
      puts: [
        { strike_price: 25000, oi: 10 },
        { strike_price: 25100, oi: 20 },
      ],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());

    expect(result.current.strikes.map((row) => row.strike)).toEqual([25000, 25100]);
    expect(result.current.strikes.every((row) => row.strike > 0)).toBe(true);
    expect(result.current.strikes[0]?.call?.oi).toBe(0);
    expect(result.current.strikes[1]?.call).toBeNull();
  });

  it("keeps a missing or non-positive spot unavailable", async () => {
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0, close: 24900 });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());

    expect(result.current.spotLtp).toBeNull();
    expect(result.current.spotChange).toBeNull();
    expect(result.current.atmStrike).toBeNull();
  });

  it("derives ATM from the strike nearest live spot instead of backend atm_strike", async () => {
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25090, close: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } },
        { strike: 25100, ce: { oi: 30 }, pe: { oi: 40 } },
      ],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.chain).not.toBeNull());
    expect(result.current.atmStrike).toBe(25100);
  });

  it("trims expiries and does not enable a chain request for blank entries", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [null, "", "  ", " 2026-07-30 "] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(result.current.expiries).toEqual(["2026-07-30"]));
    expect(result.current.selectedExpiry).toBe("2026-07-30");
    expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    );
  });

  it("does not let a stale symbol response overwrite the current chain", async () => {
    const niftyChain = deferred<Record<string, unknown>>();
    const bankNiftyChain = deferred<Record<string, unknown>>();
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2026-07-30"] });
    apiMocks.getOptionChain.mockImplementation((symbol: string) => (
      symbol === "NIFTY" ? niftyChain.promise : bankNiftyChain.promise
    ));
    apiMocks.getQuotes.mockImplementation((symbol: string) => Promise.resolve({
      ltp: symbol === "NIFTY" ? 25000 : 55000,
      close: symbol === "NIFTY" ? 24900 : 54900,
    }));

    const { result, rerender } = renderHook(
      ({ symbol }) => useOptionChainData(symbol, "NFO"),
      { initialProps: { symbol: NIFTY } },
    );
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    ));

    rerender({ symbol: BANKNIFTY });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    ));

    await act(async () => {
      bankNiftyChain.resolve({
        atm_strike: 55000,
        chain: [{ strike: 55000, ce: { oi: 20 }, pe: { oi: 30 } }],
      });
      await bankNiftyChain.promise;
    });
    await waitFor(() => expect(result.current.atmStrike).toBe(55000));

    await act(async () => {
      niftyChain.resolve({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 15 } }],
      });
      await niftyChain.promise;
    });

    expect(result.current.atmStrike).toBe(55000);
    expect(result.current.strikes.map((row) => row.strike)).toEqual([55000]);
  });

  it("does not publish a late Live chain after the authority switches to Explore", async () => {
    const liveChain = deferred<Record<string, unknown>>();
    const exploreChain = deferred<Record<string, unknown>>();
    apiMocks.getOptionChain
      .mockReturnValueOnce(liveChain.promise)
      .mockReturnValueOnce(exploreChain.promise);

    const { result, rerender } = renderHook(
      ({ scopeProbe }) => {
        void scopeProbe;
        return useOptionChainData(NIFTY, "NFO");
      },
      { initialProps: { scopeProbe: "live" } },
    );
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1));

    dataScopeState.value = "explore:mock";
    rerender({ scopeProbe: "explore" });
    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      liveChain.resolve({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 15 } }],
      });
      await liveChain.promise;
    });

    expect(result.current.chain).toBeNull();
    expect(result.current.atmStrike).toBeNull();
    expect(result.current.strikes).toEqual([]);
  });

  it("withholds the prior authority chain and spot on the first scope-B result", async () => {
    const replacementChain = deferred<Record<string, unknown>>();
    apiMocks.getOptionChain
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 15 } }],
      })
      .mockReturnValueOnce(replacementChain.promise);

    const { result, rerender } = renderHook(
      ({ scopeProbe }) => {
        void scopeProbe;
        return useOptionChainData(NIFTY, "NFO");
      },
      { initialProps: { scopeProbe: "A" } },
    );
    await waitFor(() => expect(result.current.chain).not.toBeNull());
    expect(result.current.spot?.ltp).toBe(25000);

    dataScopeState.value = "explore:mock";
    rerender({ scopeProbe: "B" });

    expect(result.current.chain).toBeNull();
    expect(result.current.spot).toBeNull();
    expect(result.current.strikes).toEqual([]);
    expect(result.current.spotLtp).toBeNull();
  });

  it("never starts the next symbol with the previous identity expiry", async () => {
    const bankExpiry = deferred<{ expiry: string[] }>();
    apiMocks.getExpiry.mockImplementation((symbol: string) => (
      symbol === "NIFTY"
        ? Promise.resolve({ expiry: ["2026-07-30"] })
        : bankExpiry.promise
    ));
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    const { rerender } = renderHook(
      ({ symbol }) => useOptionChainData(symbol, "NFO"),
      { initialProps: { symbol: NIFTY } },
    );
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    ));

    rerender({ symbol: BANKNIFTY });
    await act(async () => { await Promise.resolve(); });
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    );

    await act(async () => {
      bankExpiry.resolve({ expiry: ["2026-08-06"] });
      await bankExpiry.promise;
    });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-08-06", expect.any(AbortSignal), dataScopeState.value,
    ));
  });

  it("does not let an abandoned hung request block the validated same key after an identity round trip", async () => {
    const hungNiftyChain = deferred<Record<string, unknown>>();
    let niftyCalls = 0;
    apiMocks.getExpiry.mockImplementation((symbol: string) => Promise.resolve({
      expiry: [symbol === "NIFTY" ? "2026-07-30" : "2026-08-06"],
    }));
    apiMocks.getOptionChain.mockImplementation((symbol: string) => {
      if (symbol === "NIFTY" && niftyCalls++ === 0) return hungNiftyChain.promise;
      return Promise.resolve({
        chain: [{ strike: symbol === "NIFTY" ? 25000 : 55000, ce: { oi: 10 }, pe: { oi: 20 } }],
      });
    });

    const { rerender } = renderHook(
      ({ symbol }) => useOptionChainData(symbol, "NFO"),
      { initialProps: { symbol: NIFTY } },
    );
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), dataScopeState.value,
    ));

    rerender({ symbol: BANKNIFTY });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-08-06", expect.any(AbortSignal), dataScopeState.value,
    ));

    rerender({ symbol: NIFTY });
    await waitFor(() => expect(
      apiMocks.getOptionChain.mock.calls.filter(([symbol]) => symbol === "NIFTY"),
    ).toHaveLength(2));
  });

  it("does not start another same-identity refresh while one is still pending", async () => {
    const pendingChain = deferred<Record<string, unknown>>();
    apiMocks.getOptionChain.mockReturnValue(pendingChain.promise);

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1));
    act(() => {
      void result.current.fetchData();
    });

    expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

    await act(async () => {
      pendingChain.resolve({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
      });
      await pendingChain.promise;
    });

    act(() => {
      void result.current.fetchData();
    });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2));
  });

  it("skips an auto-refresh interval while the same identity request is pending", async () => {
    vi.useFakeTimers();
    try {
      const pendingChain = deferred<Record<string, unknown>>();
      apiMocks.getOptionChain.mockReturnValue(pendingChain.promise);

      renderHook(() => useOptionChainData(NIFTY, "NFO"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        pendingChain.resolve({
          atm_strike: 25000,
          chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
        });
        await pendingChain.promise;
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears the retained chain when the current refresh fails", async () => {
    apiMocks.getOptionChain
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
      })
      .mockRejectedValueOnce(new Error("chain unavailable"));

    const { result } = renderHook(() => useOptionChainData(NIFTY, "NFO"));
    await waitFor(() => expect(result.current.chain).not.toBeNull());

    act(() => {
      result.current.fetchData();
    });

    await waitFor(() => expect(result.current.error).toContain("chain unavailable"));
    expect(result.current.chain).toBeNull();
  });
});
