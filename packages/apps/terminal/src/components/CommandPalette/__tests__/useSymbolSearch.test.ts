import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useSymbolSearch } from "../useSymbolSearch";

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn(),
}));

import { searchSymbol } from "@/services/api";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useSymbolSearch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns empty results for empty query", () => {
    const { result } = renderHook(() => useSymbolSearch(""), {
      wrapper: createWrapper(),
    });
    expect(result.current.results).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  });

  it("debounces the API call by 300ms", async () => {
    const mockResults = [{ symbol: "RELIANCE", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValue(mockResults);

    vi.useFakeTimers();

    const { result } = renderHook(() => useSymbolSearch("REL"), {
      wrapper: createWrapper(),
    });

    // Before debounce fires, API must not be called
    expect(searchSymbol).not.toHaveBeenCalled();

    // Advance past the 300ms debounce — this triggers setDebouncedQuery
    act(() => {
      vi.advanceTimersByTime(350);
    });

    // Restore real timers before waitFor so its polling can work
    vi.useRealTimers();

    // Now waitFor can poll with real timers while TQ resolves the query
    await waitFor(() => {
      expect(searchSymbol).toHaveBeenCalledWith("REL");
      expect(result.current.results).toEqual(mockResults);
    });
  });

  it("does not call API for queries shorter than 2 characters", async () => {
    vi.useFakeTimers();

    renderHook(() => useSymbolSearch("R"), { wrapper: createWrapper() });

    act(() => {
      vi.advanceTimersByTime(500);
    });

    vi.useRealTimers();

    expect(searchSymbol).not.toHaveBeenCalled();
  });

  it("clears prior-query results immediately when the query becomes too short", async () => {
    const firstResults = [{ symbol: "RELIANCE", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValue(firstResults);
    vi.useFakeTimers();

    const { result, rerender } = renderHook(
      ({ query }) => useSymbolSearch(query),
      {
        initialProps: { query: "REL" },
        wrapper: createWrapper(),
      },
    );

    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(result.current.results).toEqual(firstResults);
    });

    rerender({ query: "R" });

    expect(result.current.results).toEqual([]);
  });

  it("suppresses prior-query results during the debounce for a new query", async () => {
    const firstResults = [{ symbol: "RELIANCE", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValue(firstResults);
    vi.useFakeTimers();

    const { result, rerender } = renderHook(
      ({ query }) => useSymbolSearch(query),
      {
        initialProps: { query: "REL" },
        wrapper: createWrapper(),
      },
    );

    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(result.current.results).toEqual(firstResults);
    });

    rerender({ query: "INFY" });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.results).toEqual([]);
  });

  it("suppresses cached results after a refetch fails", async () => {
    const cachedResults = [{ symbol: "RELIANCE", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValue(cachedResults);
    vi.useFakeTimers();

    const { result } = renderHook(() => useSymbolSearch("REL"), {
      wrapper: createWrapper(),
    });

    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(result.current.results).toEqual(cachedResults);
    });

    vi.mocked(searchSymbol).mockRejectedValueOnce(new Error("network error"));
    await act(async () => {
      await result.current.retry();
    });

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
      expect(result.current.results).toEqual([]);
    });

    const recoveredResults = [{ symbol: "INFY", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValueOnce(recoveredResults);
    await act(async () => {
      await result.current.retry();
    });

    await waitFor(() => {
      expect(result.current.isError).toBe(false);
      expect(result.current.results).toEqual(recoveredResults);
    });
  });

  it("preserves the error alert state while an initial-error retry is in flight", async () => {
    vi.mocked(searchSymbol).mockRejectedValueOnce(new Error("network error"));
    vi.useFakeTimers();

    const { result } = renderHook(() => useSymbolSearch("REL"), {
      wrapper: createWrapper(),
    });

    act(() => {
      vi.advanceTimersByTime(350);
    });
    vi.useRealTimers();

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
    });

    let resolveRetry!: (value: Array<{ symbol: string; exchange: string }>) => void;
    const retryResponse = new Promise<Array<{ symbol: string; exchange: string }>>(
      (resolve) => {
        resolveRetry = resolve;
      },
    );
    vi.mocked(searchSymbol).mockReturnValueOnce(retryResponse);

    let retryPromise: Promise<unknown> | undefined;
    act(() => {
      retryPromise = result.current.retry();
    });

    await waitFor(() => {
      expect(result.current.isRetrying).toBe(true);
      expect(result.current.isError).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.results).toEqual([]);
    });

    const recoveredResults = [{ symbol: "INFY", exchange: "NSE" }];
    resolveRetry(recoveredResults);
    await act(async () => {
      await retryPromise;
    });

    await waitFor(() => {
      expect(result.current.isRetrying).toBe(false);
      expect(result.current.isError).toBe(false);
      expect(result.current.results).toEqual(recoveredResults);
    });
  });

  it("exposes a rejected search as an error with a retry action", async () => {
    vi.mocked(searchSymbol).mockRejectedValue(new Error("network error"));

    vi.useFakeTimers();

    const { result } = renderHook(() => useSymbolSearch("REL"), {
      wrapper: createWrapper(),
    });

    act(() => {
      vi.advanceTimersByTime(350);
    });

    vi.useRealTimers();

    await waitFor(() => {
      expect(result.current.isError).toBe(true);
      expect(typeof result.current.retry).toBe("function");
    });
  });
});
