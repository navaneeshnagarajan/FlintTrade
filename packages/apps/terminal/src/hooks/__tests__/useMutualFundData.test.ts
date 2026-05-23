/**
 * Tests for useMutualFundData — mode-aware mutual fund hooks.
 *
 * Verifies that:
 *   1. useMFSearch returns fallback data in explore mode, filters client-side
 *   2. useMFCategories returns fallback categories in explore mode
 *   3. useMFNAV returns fallback fund data in explore mode
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock modeStore
// ---------------------------------------------------------------------------

let currentMode: "explore" | "practice" | "live" = "explore";
const modeListeners = new Set<() => void>();

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => {
    const [, setState] = React.useState(0);
    React.useEffect(() => {
      const cb = () => setState((n) => n + 1);
      modeListeners.add(cb);
      return () => { modeListeners.delete(cb); };
    }, []);
    return selector({ mode: currentMode });
  },
}));

// ---------------------------------------------------------------------------
// Mock ftApi service
// ---------------------------------------------------------------------------

const searchMock = vi.fn((_query: string, _category?: string) =>
  Promise.resolve({
    funds: [
      {
        scheme_code: 999999,
        scheme_name: "API Fund - Growth",
        amc: "API AMC",
        category: "Equity Scheme - Large Cap Fund",
        nav: 100.0,
        nav_date: "08-Apr-2026",
        scheme_type: "Open Ended",
      },
    ],
  }),
);

const categoriesMock = vi.fn(() =>
  Promise.resolve({ categories: ["API Category A", "API Category B"] }),
);

const navMock = vi.fn((_schemeCode: number) =>
  Promise.resolve({
    fund: {
      scheme_code: 120503,
      scheme_name: "Axis Bluechip Fund - Direct Plan - Growth",
      amc: "Axis Mutual Fund",
      category: "Equity Scheme - Large Cap Fund",
      nav: 63.0,
      nav_date: "08-Apr-2026",
      scheme_type: "Open Ended",
    },
  }),
);

vi.mock("@/services/ftApi", () => ({
  searchMutualFunds: (query: string, category?: string) => searchMock(query, category),
  getMFCategories: () => categoriesMock(),
  getMutualFundNAV: (schemeCode: number) => navMock(schemeCode),
}));

// ---------------------------------------------------------------------------
// Import hooks after mocks
// ---------------------------------------------------------------------------

import { useMFSearch, useMFCategories, useMFNAV } from "../useMutualFundData";

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  currentMode = "explore";
  modeListeners.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests: useMFSearch
// ---------------------------------------------------------------------------

describe("useMFSearch", () => {
  it("returns fallback funds in explore mode without API calls", () => {
    const { result } = renderHook(() => useMFSearch(""), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(false);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.funds.length).toBeGreaterThan(0);
    expect(result.current.funds[0].scheme_name).toContain("Axis Bluechip");
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("filters fallback funds client-side in explore mode when query >= 2 chars", () => {
    const { result } = renderHook(() => useMFSearch("SBI"), {
      wrapper: createWrapper(),
    });

    expect(result.current.funds.length).toBe(1);
    expect(result.current.funds[0].amc).toContain("SBI");
    expect(searchMock).not.toHaveBeenCalled();
  });

  it("calls API in live mode with query >= 2 chars", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useMFSearch("Axis"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(searchMock).toHaveBeenCalled();
    expect(result.current.funds[0].scheme_name).toBe("API Fund - Growth");
  });
});

// ---------------------------------------------------------------------------
// Tests: useMFCategories
// ---------------------------------------------------------------------------

describe("useMFCategories", () => {
  it("returns fallback categories in explore mode", () => {
    const { result } = renderHook(() => useMFCategories(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.categories.length).toBeGreaterThan(0);
    expect(result.current.categories).toContain("Equity Scheme - Large Cap Fund");
    expect(categoriesMock).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Tests: useMFNAV
// ---------------------------------------------------------------------------

describe("useMFNAV", () => {
  it("returns fallback fund by scheme code in explore mode", () => {
    const { result } = renderHook(() => useMFNAV(120503), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.fund).not.toBeNull();
    expect(result.current.fund?.scheme_name).toContain("Axis Bluechip");
    expect(navMock).not.toHaveBeenCalled();
  });

  it("returns null when scheme code is undefined", () => {
    const { result } = renderHook(() => useMFNAV(undefined), {
      wrapper: createWrapper(),
    });

    expect(result.current.fund).toBeNull();
    expect(result.current.isLoading).toBe(false);
  });
});
