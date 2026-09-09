/**
 * InvestContext.tsx
 *
 * Single data-fetching layer for the entire Invest route.
 * All portfolio data is fetched once here and consumed by tabs via context.
 * Tabs never call useHoldings/useFunds directly — they read from this context.
 *
 * Boundary: TanStack Query (REST) → derived state → context → tabs.
 */

import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { useHoldings } from "@/hooks/useHoldings";
import { useFunds } from "@/hooks/useFunds";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { getDemoFunds, getDemoHoldings } from "@/hooks/useModeData";
import { classifySector } from "@/lib/sectors";
import { useModeStore, type AppMode } from "@/stores/modeStore";
import type { Holding } from "@/types/api";

// ─── Public shape ─────────────────────────────────────────────────────────────

export interface PortfolioSummary {
  currentValue: number;
  totalInvested: number;
  totalPnl: number;
  totalPnlPercent: number;
  availableCash: number;
  sectorCount: number;
  holdingCount: number;
}

export interface InvestContextValue {
  /** Holdings shown on the Invest route (demo book in Explore, live otherwise). */
  holdings: Holding[];
  /** Aggregated portfolio numbers derived from holdings + funds. */
  summary: PortfolioSummary;
  /** True while either holdings or funds query is in-flight. */
  isLoading: boolean;
  /** True when holdings query has errored. */
  isError: boolean;
  /** True when the exposed book is the labelled Explore sample feed. */
  isSampleData: boolean;
  /** Force-refetch holdings from the active broker data source. */
  refetchHoldings: () => void;
}

/**
 * Resolve the Invest-route holdings book.
 *
 * Explore owns a labelled sample feed (`getDemoHoldings`) so the dashboard
 * header count matches the listed sample stocks. Practice and Live keep the
 * live query result — an empty funded book stays at 0.
 */
export function resolveInvestHoldings(
  mode: AppMode,
  liveHoldings: Holding[],
): { holdings: Holding[]; isSampleData: boolean } {
  if (mode === "explore") {
    return { holdings: getDemoHoldings(), isSampleData: true };
  }
  return { holdings: liveHoldings, isSampleData: false };
}

// ─── Context ──────────────────────────────────────────────────────────────────

const InvestContext = createContext<InvestContextValue | null>(null);

// ─── Provider ─────────────────────────────────────────────────────────────────

export function InvestProvider({ children }: { children: ReactNode }) {
  const mode = useModeStore((s) => s.mode);
  const accountReadsEnabled = useAccountReadsEnabled();
  const {
    data: liveHoldings = [],
    isLoading: holdingsLoading,
    isError: holdingsError,
    refetch: refetchHoldings,
  } = useHoldings({ enabled: accountReadsEnabled });

  const { data: funds, isLoading: fundsLoading } = useFunds({ enabled: accountReadsEnabled });

  const { holdings, isSampleData } = resolveInvestHoldings(mode, liveHoldings);
  const isLoading = mode === "explore" ? false : holdingsLoading || fundsLoading;
  const availableCash = mode === "explore" ? getDemoFunds().availableCash : (funds?.availableCash ?? 0);

  // Derive portfolio totals — memoised so tabs get stable references
  const totalInvested = useMemo(
    () => holdings.reduce((acc, h) => acc + h.averagePrice * h.quantity, 0),
    [holdings],
  );

  const currentValue = useMemo(
    () => holdings.reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );

  const totalPnl = useMemo(
    () => holdings.reduce((acc, h) => acc + h.pnl, 0),
    [holdings],
  );

  const totalPnlPercent = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  const sectorCount = useMemo(
    () => new Set(holdings.map((h) => classifySector(h.symbol))).size,
    [holdings],
  );

  const summary: PortfolioSummary = useMemo(
    () => ({
      currentValue,
      totalInvested,
      totalPnl,
      totalPnlPercent,
      availableCash,
      sectorCount,
      holdingCount: holdings.length,
    }),
    [currentValue, totalInvested, totalPnl, totalPnlPercent, availableCash, sectorCount, holdings.length],
  );

  const value: InvestContextValue = useMemo(
    () => ({
      holdings,
      summary,
      isLoading,
      isError: holdingsError,
      isSampleData,
      refetchHoldings,
    }),
    [holdings, summary, isLoading, holdingsError, isSampleData, refetchHoldings],
  );

  return <InvestContext.Provider value={value}>{children}</InvestContext.Provider>;
}

// ─── Consumer hook ────────────────────────────────────────────────────────────

export function useInvest(): InvestContextValue {
  const ctx = useContext(InvestContext);
  if (!ctx) {
    throw new Error("useInvest must be used inside <InvestProvider>");
  }
  return ctx;
}
