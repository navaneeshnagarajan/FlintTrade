/**
 * useFunds tests
 *
 * Covers:
 *   - URL called (getFunds invoked exactly once on mount)
 *   - Response shape unwraps correctly (data is Funds, not wrapped)
 *   - Error surfaces (isError true, error is an Error instance)
 *
 * Pattern (carried over to the sibling hook tests in this folder):
 * mock the service module, wrap renderHook in QueryClientProvider with
 * `retry: false` and `gcTime: 0` so the test never depends on real
 * fetch / timing.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { Funds } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks — declared BEFORE the hook import so vi.mock hoisting applies.
// ---------------------------------------------------------------------------

const mockGetFunds = vi.fn<() => Promise<Funds>>();

vi.mock("@/services/api", () => ({
  getFunds: () => mockGetFunds(),
}));

// Account discovery itself is covered by the broker-account suites. Keep this
// hook test network-free while driving the real account/read stores below.
vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ data: [] }),
}));

// ---------------------------------------------------------------------------
// Hook import — after mocks so the hook resolves the mocked module.
// ---------------------------------------------------------------------------

import { useFunds } from "../useFunds";
import {
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        refetchOnWindowFocus: false,
      },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeFunds(overrides: Partial<Funds> = {}): Funds {
  return {
    availableCash: 50000,
    usedMargin: 12000,
    totalBalance: 62000,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  setAccountRuntime();
});

afterEach(() => {
  resetAccountRuntime();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useFunds — URL is called", () => {
  it("calls getFunds exactly once on mount", async () => {
    mockGetFunds.mockResolvedValue(makeFunds());

    renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetFunds).toHaveBeenCalledTimes(1));
  });

  it("does not call getFunds when disabled", () => {
    mockGetFunds.mockResolvedValue(makeFunds());

    const { result } = renderHook(() => useFunds({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetFunds).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useFunds — response shape", () => {
  it("exposes a Funds object with the three numeric fields", async () => {
    const funds = makeFunds({
      availableCash: 100_000,
      usedMargin: 25_000,
      totalBalance: 125_000,
    });
    mockGetFunds.mockResolvedValue(funds);

    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toStrictEqual(funds);
    expect(typeof result.current.data?.availableCash).toBe("number");
    expect(typeof result.current.data?.usedMargin).toBe("number");
    expect(typeof result.current.data?.totalBalance).toBe("number");
  });

  it("starts in loading state before the query resolves", () => {
    mockGetFunds.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });
});

describe("useFunds — error handling", () => {
  it("transitions to error state when getFunds rejects", async () => {
    mockGetFunds.mockRejectedValue(
      new Error("API key invalid. Check Settings → Connection."),
    );

    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeInstanceOf(Error);
    expect((result.current.error as Error).message).toContain("API key invalid");
  });

  it("leaves data undefined when the query fails", async () => {
    mockGetFunds.mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(result.current.data).toBeUndefined();
  });
});
