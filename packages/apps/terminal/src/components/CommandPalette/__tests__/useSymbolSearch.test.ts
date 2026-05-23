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
});
