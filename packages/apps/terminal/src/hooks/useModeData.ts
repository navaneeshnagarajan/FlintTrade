/**
 * useModeData — Mode-aware data routing hook.
 *
 * Returns data from the appropriate source based on the current app mode:
 *   - explore:  static mock data from MockDataEngine (no broker needed)
 *   - practice: delegates to TanStack Query hooks (backend enforces sandbox)
 *   - live:     delegates to TanStack Query hooks (real broker)
 *
 * Usage:
 *   const { data, isLoading, error, refetch } = useModeData("positions");
 *
 * The return shape mirrors TanStack Query's UseQueryResult so widgets
 * can consume it without branching on mode.
 */

import { useMemo, useCallback, useState } from "react";
import { useModeStore } from "@/stores/modeStore";
import { mockDataEngine } from "@/services/mockDataEngine";
import { usePositions } from "@/hooks/usePositions";
import { useOrders } from "@/hooks/useOrders";
import { useHoldings } from "@/hooks/useHoldings";
import { useFunds } from "@/hooks/useFunds";
import { useTradebook } from "@/hooks/useTradebook";
import type { AppMode } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Data keys supported by useModeData. */
export type ModeDataKey =
  | "positions"
  | "orders"
  | "holdings"
  | "funds"
  | "tradebook"
  | "watchlist";

/** Normalised return shape — mirrors the subset of UseQueryResult that widgets need. */
export interface ModeDataResult<T> {
  data: T | undefined;
  isLoading: boolean;
  error: Error | null;
  refetch: () => void;
}

// ---------------------------------------------------------------------------
// Mock data helpers
// ---------------------------------------------------------------------------

/** Static mock funds for explore mode (MockDataEngine doesn't provide funds). */
const MOCK_FUNDS = {
  available_balance: 250_000,
  utilized_margin: 48_500,
  total_balance: 298_500,
};

/** Static mock watchlist for explore mode. */
const MOCK_WATCHLIST = mockDataEngine.getSnapshot().map((t) => ({
  symbol: t.symbol,
  exchange: t.exchange,
  ltp: t.ltp,
  change: t.change,
  changePct: t.changePct,
}));

function getMockData(key: ModeDataKey): unknown {
  switch (key) {
    case "positions":
      return mockDataEngine.getMockPositions();
    case "orders":
      return mockDataEngine.getMockOrders();
    case "holdings":
      return mockDataEngine.getMockHoldings();
    case "funds":
      return MOCK_FUNDS;
    case "tradebook":
      // Re-use orders as trades for explore mode (same shape is close enough)
      return mockDataEngine.getMockOrders();
    case "watchlist":
      return MOCK_WATCHLIST;
  }
}

// ---------------------------------------------------------------------------
// Hook — explore mode (returns static mock data)
// ---------------------------------------------------------------------------

function useExploreModeData<T>(key: ModeDataKey): ModeDataResult<T> {
  // useState to allow refetch to trigger a re-render with fresh mock data
  const [revision, setRevision] = useState(0);

  const data = useMemo(() => getMockData(key) as T, [key, revision]);

  const refetch = useCallback(() => {
    setRevision((r) => r + 1);
  }, []);

  return { data, isLoading: false, error: null, refetch };
}

// ---------------------------------------------------------------------------
// Hook — live/practice mode (delegates to TanStack Query)
// ---------------------------------------------------------------------------

/**
 * Calls the appropriate TanStack Query hook for the given key.
 *
 * React rules of hooks require that hooks are called unconditionally,
 * so we call ALL hooks every render and pick the right result.
 * The unused hooks still run but are lightweight (staleTime prevents
 * unnecessary refetches).
 */
function useApiModeData<T>(key: ModeDataKey): ModeDataResult<T> {
  const positions = usePositions();
  const orders = useOrders();
  const holdings = useHoldings();
  const funds = useFunds();
  const tradebook = useTradebook();

  // Pick the result for the requested key
  const selected = useMemo(() => {
    switch (key) {
      case "positions":
        return positions;
      case "orders":
        return orders;
      case "holdings":
        return holdings;
      case "funds":
        return funds;
      case "tradebook":
        return tradebook;
      case "watchlist":
        // No dedicated TanStack Query hook for watchlist yet;
        // return empty array. Widgets should use Jotai atoms for live ticks.
        return {
          data: [] as unknown,
          isLoading: false,
          error: null,
          refetch: () => {},
        };
    }
  }, [key, positions, orders, holdings, funds, tradebook]);

  return {
    data: selected.data as T | undefined,
    isLoading: "isLoading" in selected ? (selected.isLoading as boolean) : false,
    error: ("error" in selected ? selected.error : null) as Error | null,
    refetch: "refetch" in selected ? (selected.refetch as () => void) : () => {},
  };
}

// ---------------------------------------------------------------------------
// Public hook
// ---------------------------------------------------------------------------

/**
 * Mode-aware data hook. Returns data from the appropriate source
 * based on current app mode (explore/practice/live).
 *
 * - explore: returns mock data from MockDataEngine
 * - practice/live: fetches from API (backend enforces mode safety)
 *
 * @param key - The data key to fetch (e.g. "positions", "orders")
 * @returns { data, isLoading, error, refetch } matching TanStack Query shape
 */
export function useModeData<T = unknown>(key: ModeDataKey): ModeDataResult<T> {
  const mode: AppMode = useModeStore((s) => s.mode);

  // We must call both branches unconditionally (rules of hooks).
  // The unused branch is a no-op in terms of network calls because
  // explore mode returns static data and API hooks respect staleTime.
  const exploreResult = useExploreModeData<T>(key);
  const apiResult = useApiModeData<T>(key);

  return mode === "explore" ? exploreResult : apiResult;
}
