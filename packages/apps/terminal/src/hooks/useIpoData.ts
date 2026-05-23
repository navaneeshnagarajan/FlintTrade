/**
 * useIpoData — Mode-aware data hook for the IPO tab.
 *
 * - explore mode:  returns hardcoded fallback data (no backend needed)
 * - practice/live: fetches from /ft-api/api/v1/ipo/upcoming and /ipo/recent
 *   via TanStack Query, cached for 5 minutes (IPO data changes infrequently)
 *
 * Returns a unified shape so IpoTab doesn't branch on mode for rendering.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useModeStore } from "@/stores/modeStore";
import { getUpcomingIPOs, getRecentIPOs, type IpoEntry } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Explore-mode fallback data (real historical IPOs, no backend needed)
// ---------------------------------------------------------------------------

const FALLBACK_UPCOMING: IpoEntry[] = [
  {
    name: "LG Electronics India",
    symbol: "LGINDIA",
    issue_size: "\u20B915,000 Cr",
    price_band: "\u20B91,550 - \u20B91,600",
    lot_size: 9,
    open_date: "2026-05-12",
    close_date: "2026-05-14",
    listing_date: "",
    status: "upcoming",
    listing_gain: undefined,
  },
];

const FALLBACK_RECENT: IpoEntry[] = [
  {
    name: "Hexaware Technologies",
    symbol: "HEXAWARE",
    issue_size: "\u20B99,950 Cr",
    price_band: "\u20B9674 - \u20B9708",
    lot_size: 21,
    open_date: "2025-02-12",
    close_date: "2025-02-14",
    listing_date: "2025-02-19",
    status: "listed",
    listing_gain: 2.6,
  },
  {
    name: "Dr Agarwal's Health Care",
    symbol: "DRAGARWAL",
    issue_size: "\u20B93,027 Cr",
    price_band: "\u20B9382 - \u20B9402",
    lot_size: 37,
    open_date: "2025-01-29",
    close_date: "2025-01-31",
    listing_date: "2025-02-05",
    status: "listed",
    listing_gain: 11.4,
  },
  {
    name: "Stallion India Fluorochemicals",
    symbol: "STALFLUO",
    issue_size: "\u20B9600 Cr",
    price_band: "\u20B9375 - \u20B9395",
    lot_size: 38,
    open_date: "2025-01-16",
    close_date: "2025-01-20",
    listing_date: "2025-01-23",
    status: "listed",
    listing_gain: 18.2,
  },
  {
    name: "Capital Infra Trust InvIT",
    symbol: "CAPITALIT",
    issue_size: "\u20B92,488 Cr",
    price_band: "\u20B999 - \u20B9100",
    lot_size: 150,
    open_date: "2025-01-07",
    close_date: "2025-01-09",
    listing_date: "2025-01-14",
    status: "listed",
    listing_gain: -3.0,
  },
  {
    name: "Indo Farm Equipment",
    symbol: "INDOFARM",
    issue_size: "\u20B9260 Cr",
    price_band: "\u20B9204 - \u20B9215",
    lot_size: 69,
    open_date: "2024-12-31",
    close_date: "2025-01-02",
    listing_date: "2025-01-07",
    status: "listed",
    listing_gain: 20.5,
  },
  {
    name: "Ventive Hospitality",
    symbol: "VENTIVE",
    issue_size: "\u20B91,600 Cr",
    price_band: "\u20B9610 - \u20B9643",
    lot_size: 23,
    open_date: "2024-12-20",
    close_date: "2024-12-24",
    listing_date: "2024-12-30",
    status: "listed",
    listing_gain: -1.2,
  },
  {
    name: "Transrail Lighting",
    symbol: "TRANSRAIL",
    issue_size: "\u20B9839 Cr",
    price_band: "\u20B9410 - \u20B9432",
    lot_size: 34,
    open_date: "2024-12-19",
    close_date: "2024-12-23",
    listing_date: "2024-12-27",
    status: "listed",
    listing_gain: 32.0,
  },
  {
    name: "Unimech Aerospace",
    symbol: "UNIMECH",
    issue_size: "\u20B9500 Cr",
    price_band: "\u20B91,381 - \u20B91,455",
    lot_size: 10,
    open_date: "2024-12-23",
    close_date: "2024-12-26",
    listing_date: "2024-12-31",
    status: "listed",
    listing_gain: 88.8,
  },
  {
    name: "DAM Capital Advisors",
    symbol: "DAMCAPITAL",
    issue_size: "\u20B9840 Cr",
    price_band: "\u20B9269 - \u20B9283",
    lot_size: 53,
    open_date: "2024-12-19",
    close_date: "2024-12-23",
    listing_date: "2024-12-27",
    status: "listed",
    listing_gain: 30.5,
  },
  {
    name: "Carraro India",
    symbol: "CARRARO",
    issue_size: "\u20B91,250 Cr",
    price_band: "\u20B9668 - \u20B9704",
    lot_size: 21,
    open_date: "2024-12-20",
    close_date: "2024-12-24",
    listing_date: "2024-12-30",
    status: "listed",
    listing_gain: -4.6,
  },
];

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface IpoData {
  upcoming: IpoEntry[];
  recent: IpoEntry[];
  lastUpdated: string;
}

export interface UseIpoDataResult {
  data: IpoData;
  isLoading: boolean;
  isLive: boolean;
  error: Error | null;
  refetch: () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useIpoData(): UseIpoDataResult {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode !== "explore";

  const upcomingQuery = useQuery({
    queryKey: ["ipo", "upcoming"],
    queryFn: getUpcomingIPOs,
    enabled: isLive,
    staleTime: 5 * 60_000, // 5 minutes
    refetchInterval: 10 * 60_000, // refresh every 10 minutes
    retry: 2,
  });

  const recentQuery = useQuery({
    queryKey: ["ipo", "recent"],
    queryFn: getRecentIPOs,
    enabled: isLive,
    staleTime: 5 * 60_000,
    refetchInterval: 10 * 60_000,
    retry: 2,
  });

  const data = useMemo<IpoData>(() => {
    if (!isLive) {
      return {
        upcoming: FALLBACK_UPCOMING,
        recent: FALLBACK_RECENT,
        lastUpdated: "",
      };
    }

    return {
      upcoming: upcomingQuery.data?.ipos ?? FALLBACK_UPCOMING,
      recent: recentQuery.data?.ipos ?? FALLBACK_RECENT,
      lastUpdated: recentQuery.data?.last_updated ?? upcomingQuery.data?.last_updated ?? "",
    };
  }, [isLive, upcomingQuery.data, recentQuery.data]);

  const isLoading = isLive && (upcomingQuery.isLoading || recentQuery.isLoading);
  const error = isLive
    ? ((upcomingQuery.error ?? recentQuery.error) as Error | null)
    : null;

  const refetch = () => {
    upcomingQuery.refetch();
    recentQuery.refetch();
  };

  return { data, isLoading, isLive, error, refetch };
}
