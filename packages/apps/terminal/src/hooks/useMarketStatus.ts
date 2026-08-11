import { useQuery } from "@tanstack/react-query";
import { getHolidays, getTimings } from "@/services/api";
import type { Holiday, MarketTiming } from "@/types/api";

export const MARKET_TIMINGS_MAX_AGE_MS = 60 * 60_000;
export const MARKET_TIMINGS_REFRESH_INTERVAL_MS = 45 * 60_000;

export function useHolidays(enabled = true) {
  return useQuery<Holiday[]>({
    queryKey: ["holidays"],
    queryFn: getHolidays,
    staleTime: 24 * 60 * 60_000, // 24h — holidays don't change often
    enabled,
  });
}

export function useTimings(enabled = true) {
  return useQuery<MarketTiming[]>({
    queryKey: ["timings"],
    queryFn: getTimings,
    staleTime: MARKET_TIMINGS_MAX_AGE_MS,
    refetchInterval: enabled ? MARKET_TIMINGS_REFRESH_INTERVAL_MS : false,
    refetchIntervalInBackground: true,
    enabled,
  });
}
