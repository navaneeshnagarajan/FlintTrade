/**
 * useTradebook tests — simple broker data hook with an explicit enabled gate.
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
import type { Trade } from "@/types/api";

const accountReadState = vi.hoisted(() => ({
  current: undefined as AccountReadContext | undefined,
}));
const mockGetTradebook = vi.fn<(
  context: AccountReadContext,
  signal?: AbortSignal,
) => Promise<Trade[]>>();

vi.mock("@/services/api", () => ({
  getTradebook: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetTradebook(context, signal),
}));

vi.mock("@/hooks/useAccountReadsEnabled", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAccountReadsEnabled")>()),
  useAccountReadContext: () => accountReadState.current,
}));

import { useTradebook } from "../useTradebook";

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

function makeTrade(overrides: Partial<Trade> = {}): Trade {
  return {
    tradeId: "T-1",
    orderId: "O-1",
    symbol: "NIFTY",
    exchange: "NFO",
    action: "BUY",
    quantity: 50,
    price: 22450.5,
    timestamp: "2026-04-08T09:16:32Z",
    ...overrides,
  };
}

beforeEach(() => {
  accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
  vi.clearAllMocks();
});

describe("useTradebook — immutable account authority", () => {
  it("passes the exact connected native context and AbortSignal to getTradebook", async () => {
    mockGetTradebook.mockResolvedValue([makeTrade()]);
    renderHook(() => useTradebook(), { wrapper: createWrapper() });
    await waitFor(() => expect(mockGetTradebook).toHaveBeenCalledOnce());
    expect(mockGetTradebook).toHaveBeenCalledWith(
      CONNECTED_NATIVE_READ_CONTEXT,
      expect.any(AbortSignal),
    );
  });

  it("stays idle and makes no transport call without selected Live authority", () => {
    accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;
    mockGetTradebook.mockResolvedValue([makeTrade()]);

    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetTradebook).not.toHaveBeenCalled();
  });

  it("uses Practice sandbox authority without a Live broker", async () => {
    accountReadState.current = PRACTICE_READ_CONTEXT;
    mockGetTradebook.mockResolvedValue([]);

    renderHook(() => useTradebook(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetTradebook).toHaveBeenCalledWith(
      PRACTICE_READ_CONTEXT,
      expect.any(AbortSignal),
    ));
  });

  it("does not call getTradebook when disabled", () => {
    mockGetTradebook.mockResolvedValue([makeTrade()]);
    const { result } = renderHook(() => useTradebook({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetTradebook).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useTradebook — response shape", () => {
  it("exposes a Trade[] array on success", async () => {
    const data = [
      makeTrade({ tradeId: "T-1", symbol: "NIFTY" }),
      makeTrade({ tradeId: "T-2", symbol: "BANKNIFTY", price: 50_120.25 }),
    ];
    mockGetTradebook.mockResolvedValue(data);

    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toStrictEqual(data);
    expect(result.current.data).toHaveLength(2);
  });
});

describe("useTradebook — error handling", () => {
  it("surfaces fetch errors via isError", async () => {
    mockGetTradebook.mockRejectedValue(new Error("server unreachable"));
    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.data).toBeUndefined();
  });
});
