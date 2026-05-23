/**
 * useMutualFundData — Mode-aware data hook for the Mutual Fund Explorer tab.
 *
 * - explore mode:  returns hardcoded fallback data (no backend needed)
 * - practice/live: fetches from /ft-api/api/v1/mf/* via TanStack Query
 *
 * Provides search, category listing, and single-fund NAV lookup.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useModeStore } from "@/stores/modeStore";
import {
  searchMutualFunds,
  getMFCategories,
  getMutualFundNAV,
  type MutualFundEntry,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Explore-mode fallback data (representative Indian mutual funds)
// ---------------------------------------------------------------------------

const FALLBACK_FUNDS: MutualFundEntry[] = [
  {
    scheme_code: 120503,
    scheme_name: "Axis Bluechip Fund - Direct Plan - Growth",
    amc: "Axis Mutual Fund",
    category: "Equity Scheme - Large Cap Fund",
    nav: 62.45,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 122639,
    scheme_name: "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
    amc: "PPFAS Mutual Fund",
    category: "Equity Scheme - Flexi Cap Fund",
    nav: 89.12,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 120587,
    scheme_name: "SBI Small Cap Fund - Direct Plan - Growth",
    amc: "SBI Mutual Fund",
    category: "Equity Scheme - Small Cap Fund",
    nav: 178.34,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 118989,
    scheme_name: "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
    amc: "HDFC Mutual Fund",
    category: "Equity Scheme - Mid Cap Fund",
    nav: 145.67,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 119551,
    scheme_name: "Mirae Asset Large Cap Fund - Direct Plan - Growth",
    amc: "Mirae Asset Mutual Fund",
    category: "Equity Scheme - Large Cap Fund",
    nav: 105.23,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 125354,
    scheme_name: "UTI Nifty 50 Index Fund - Direct Plan - Growth",
    amc: "UTI Mutual Fund",
    category: "Other Scheme - Index Funds",
    nav: 156.89,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 119598,
    scheme_name: "Kotak Emerging Equity Fund - Direct Plan - Growth",
    amc: "Kotak Mahindra Mutual Fund",
    category: "Equity Scheme - Mid Cap Fund",
    nav: 112.56,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
  {
    scheme_code: 120716,
    scheme_name: "ICICI Prudential Bluechip Fund - Direct Plan - Growth",
    amc: "ICICI Prudential Mutual Fund",
    category: "Equity Scheme - Large Cap Fund",
    nav: 98.41,
    nav_date: "08-Apr-2026",
    scheme_type: "Open Ended",
  },
];

const FALLBACK_CATEGORIES: string[] = [
  "Debt Scheme - Banking and PSU Fund",
  "Debt Scheme - Corporate Bond Fund",
  "Debt Scheme - Gilt Fund",
  "Debt Scheme - Liquid Fund",
  "Debt Scheme - Short Duration Fund",
  "Equity Scheme - Flexi Cap Fund",
  "Equity Scheme - Large Cap Fund",
  "Equity Scheme - Large & Mid Cap Fund",
  "Equity Scheme - Mid Cap Fund",
  "Equity Scheme - Multi Cap Fund",
  "Equity Scheme - Small Cap Fund",
  "Equity Scheme - Value Fund",
  "Hybrid Scheme - Balanced Advantage Fund",
  "Hybrid Scheme - Conservative Hybrid Fund",
  "Other Scheme - FoF Domestic",
  "Other Scheme - Index Funds",
];

// ---------------------------------------------------------------------------
// Return types
// ---------------------------------------------------------------------------

export interface UseMFSearchResult {
  funds: MutualFundEntry[];
  isLoading: boolean;
  isLive: boolean;
  error: Error | null;
}

export interface UseMFCategoriesResult {
  categories: string[];
  isLoading: boolean;
}

export interface UseMFNAVResult {
  fund: MutualFundEntry | null;
  isLoading: boolean;
  error: Error | null;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/**
 * Search mutual funds by name/AMC.
 * Debounce the query string in the caller component, not here.
 */
export function useMFSearch(query: string, category?: string): UseMFSearchResult {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode !== "explore";
  const trimmed = query.trim();
  const enabled = isLive && trimmed.length >= 2;

  const searchQuery = useQuery({
    queryKey: ["mf", "search", trimmed, category ?? ""],
    queryFn: () => searchMutualFunds(trimmed, category),
    enabled,
    staleTime: 60_000, // 1 minute (NAV changes once daily, but search is cheap)
    retry: 2,
  });

  const funds = useMemo<MutualFundEntry[]>(() => {
    if (!isLive) {
      // Filter fallback data client-side for explore mode
      if (trimmed.length < 2) return FALLBACK_FUNDS;
      const q = trimmed.toLowerCase();
      return FALLBACK_FUNDS.filter(
        (f) =>
          f.scheme_name.toLowerCase().includes(q) ||
          f.amc.toLowerCase().includes(q),
      );
    }
    return searchQuery.data?.funds ?? [];
  }, [isLive, trimmed, searchQuery.data]);

  return {
    funds,
    isLoading: enabled && searchQuery.isLoading,
    isLive,
    error: enabled ? (searchQuery.error as Error | null) : null,
  };
}

/**
 * Get all SEBI mutual fund categories.
 */
export function useMFCategories(): UseMFCategoriesResult {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode !== "explore";

  const catQuery = useQuery({
    queryKey: ["mf", "categories"],
    queryFn: getMFCategories,
    enabled: isLive,
    staleTime: 24 * 60 * 60_000, // 24 hours
    retry: 2,
  });

  const categories = useMemo<string[]>(() => {
    if (!isLive) return FALLBACK_CATEGORIES;
    return catQuery.data?.categories ?? FALLBACK_CATEGORIES;
  }, [isLive, catQuery.data]);

  return {
    categories,
    isLoading: isLive && catQuery.isLoading,
  };
}

/**
 * Get NAV for a single mutual fund by scheme code.
 * Pass schemeCode=0 or undefined to disable the query.
 */
export function useMFNAV(schemeCode: number | undefined): UseMFNAVResult {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode !== "explore";
  const enabled = isLive && schemeCode !== undefined && schemeCode > 0;

  const navQuery = useQuery({
    queryKey: ["mf", "nav", schemeCode],
    queryFn: () => getMutualFundNAV(schemeCode as number),
    enabled,
    staleTime: 5 * 60_000, // 5 minutes
    retry: 2,
  });

  const fund = useMemo<MutualFundEntry | null>(() => {
    if (!isLive && schemeCode) {
      return FALLBACK_FUNDS.find((f) => f.scheme_code === schemeCode) ?? null;
    }
    return navQuery.data?.fund ?? null;
  }, [isLive, schemeCode, navQuery.data]);

  return {
    fund,
    isLoading: enabled && navQuery.isLoading,
    error: enabled ? (navQuery.error as Error | null) : null,
  };
}
