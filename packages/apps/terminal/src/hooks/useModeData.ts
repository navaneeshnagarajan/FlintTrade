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
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import type { AppMode } from "@/stores/modeStore";
import type { Position, Order, Holding, Funds } from "@/types/api";

// ---------------------------------------------------------------------------
// Canonical demo data — maps the MockDataEngine's internal shapes onto the
// REST contract types (types/api.ts) the widgets actually read. The engine's
// fields differ (avgPrice vs averagePrice, side vs action, pnlPct vs
// pnlPercent), so feeding its raw output to a widget would render `undefined`.
// Exported so dashboard cards can show demo data without the useModeData
// fan-out (which calls every query hook). KEEP these in sync with types/api.ts.
// ---------------------------------------------------------------------------

/** Demo positions in the canonical {@link Position} shape (explore mode). */
export function getDemoPositions(): Position[] {
  return mockDataEngine.getMockPositions().map((p) => {
    const cost = Math.abs(p.avgPrice * p.quantity);
    return {
      symbol: p.symbol,
      exchange: p.exchange,
      product: p.product,
      quantity: p.quantity,
      averagePrice: p.avgPrice,
      ltp: p.ltp,
      pnl: p.pnl,
      pnlPercent: cost !== 0 ? (p.pnl / cost) * 100 : 0,
    };
  });
}

/** Demo orders in the canonical {@link Order} shape (explore mode). */
export function getDemoOrders(): Order[] {
  return mockDataEngine.getMockOrders().map((o) => ({
    orderId: o.orderId,
    symbol: o.symbol,
    exchange: o.exchange,
    action: o.side,
    quantity: o.quantity,
    price: o.price,
    orderType: o.orderType,
    status: o.status,
    product: o.product,
    strategy: "demo",
    timestamp: o.timestamp,
  }));
}

/** Demo holdings in the canonical {@link Holding} shape (explore mode). */
export function getDemoHoldings(): Holding[] {
  return mockDataEngine.getMockHoldings().map((h) => ({
    symbol: h.symbol,
    exchange: h.exchange,
    quantity: h.quantity,
    averagePrice: h.avgPrice,
    ltp: h.ltp,
    pnl: h.pnl,
    pnlPercent: h.pnlPct,
  }));
}

/** Demo funds in the canonical {@link Funds} shape (explore mode). */
export function getDemoFunds(): Funds {
  return { availableCash: 250_000, usedMargin: 48_500, totalBalance: 298_500 };
}

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
      return getDemoPositions();
    case "orders":
      return getDemoOrders();
    case "holdings":
      return getDemoHoldings();
    case "funds":
      return getDemoFunds();
    case "tradebook":
      // Re-use orders as trades for explore mode (same shape is close enough)
      return getDemoOrders();
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

  // `revision` is the refetch trigger, not an input: `getMockData` regenerates
  // its rows on every call, so bumping the counter is exactly how a refetch
  // produces fresh explore-mode data.
  // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
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
 * React rules of hooks require that hooks are called unconditionally, so we
 * call all hook wrappers every render. Only the selected key is enabled, and
 * explore mode disables the API branch entirely.
 */
function useApiModeData<T>(key: ModeDataKey, enabled: boolean): ModeDataResult<T> {
  const positions = usePositions({ enabled: enabled && key === "positions" });
  const orders = useOrders({ enabled: enabled && key === "orders" });
  const holdings = useHoldings({ enabled: enabled && key === "holdings" });
  const funds = useFunds({ enabled: enabled && key === "funds" });
  const tradebook = useTradebook({ enabled: enabled && key === "tradebook" });

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
  const isBrokerConnected = useBrokerConnected();

  // We must call both branches unconditionally (rules of hooks).
  // The unused API branch is disabled, so explore mode remains broker-free.
  const exploreResult = useExploreModeData<T>(key);
  const apiResult = useApiModeData<T>(
    key,
    resolveAccountReadsEnabled(mode, isBrokerConnected),
  );

  return mode === "explore" ? exploreResult : apiResult;
}
