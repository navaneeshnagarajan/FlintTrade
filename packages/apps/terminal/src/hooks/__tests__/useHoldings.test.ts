/**
 * useHoldings tests — mirrors `useFunds.test.ts` plus an explicit check that
 * the `retry: false` override in `useHoldings` short-circuits to error state
 * on the FIRST failed call (the other simple hooks default to 3 retries).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";
import type { Holding } from "@/types/api";

const accountReadState = vi.hoisted(() => ({
  current: undefined as AccountReadContext | undefined,
}));
const mockGetHoldings = vi.fn<(
  context: AccountReadContext,
  signal?: AbortSignal,
) => Promise<Holding[]>>();

vi.mock("@/services/api", () => ({
  getHoldings: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetHoldings(context, signal),
}));

vi.mock("@/hooks/useAccountReadsEnabled", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAccountReadsEnabled")>()),
  useAccountReadContext: () => accountReadState.current,
}));

import { useHoldings } from "../useHoldings";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    symbol: "RELIANCE",
    exchange: "NSE",
    quantity: 10,
    averagePrice: 2900,
    ltp: 2980,
    pnl: 800,
    pnlPercent: 2.76,
    ...overrides,
  };
}

beforeEach(() => {
  accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
  vi.clearAllMocks();
});

describe("useHoldings — immutable account authority", () => {
  it("passes the exact connected native context and AbortSignal to getHoldings", async () => {
    mockGetHoldings.mockResolvedValue([makeHolding()]);
    renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(mockGetHoldings).toHaveBeenCalledOnce());
    expect(mockGetHoldings).toHaveBeenCalledWith(
      CONNECTED_NATIVE_READ_CONTEXT,
      expect.any(AbortSignal),
    );
  });

  it("stays idle and makes no transport call without selected Live authority", () => {
    accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;
    mockGetHoldings.mockResolvedValue([makeHolding()]);

    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetHoldings).not.toHaveBeenCalled();
  });

  it("uses Practice sandbox authority without a Live broker", async () => {
    accountReadState.current = PRACTICE_READ_CONTEXT;
    mockGetHoldings.mockResolvedValue([]);

    renderHook(() => useHoldings(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetHoldings).toHaveBeenCalledWith(
      PRACTICE_READ_CONTEXT,
      expect.any(AbortSignal),
    ));
  });

  it("does not call getHoldings when disabled", () => {
    mockGetHoldings.mockResolvedValue([makeHolding()]);
    const { result } = renderHook(() => useHoldings({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetHoldings).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useHoldings — response shape", () => {
  it("exposes a Holding[] array on success", async () => {
    const data: Holding[] = [
      makeHolding({ symbol: "TCS", quantity: 5 }),
      makeHolding({ symbol: "INFY", quantity: 20 }),
    ];
    mockGetHoldings.mockResolvedValue(data);

    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toStrictEqual(data);
    expect(result.current.data).toHaveLength(2);
  });
});

describe("useHoldings — retry: false override", () => {
  it("transitions to error state after a SINGLE failure (no retry)", async () => {
    mockGetHoldings.mockRejectedValue(new Error("HTTP 500"));
    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    // Hook override means exactly one call — no automatic retries.
    expect(mockGetHoldings).toHaveBeenCalledTimes(1);
    expect((result.current.error as Error).message).toContain("HTTP 500");
  });
});
