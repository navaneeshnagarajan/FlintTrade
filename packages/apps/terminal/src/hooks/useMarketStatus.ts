import { useQuery } from "@tanstack/react-query";
import { getHolidays, getTimings } from "@/services/api";
import type { Holiday, MarketTiming } from "@/types/api";

export function useHolidays() {
  return useQuery<Holiday[]>({
    queryKey: ["holidays"],
    queryFn: getHolidays,
    staleTime: 24 * 60 * 60_000, // 24h — holidays don't change often
  });
}

export function useTimings() {
  return useQuery<MarketTiming[]>({
    queryKey: ["timings"],
    queryFn: getTimings,
    staleTime: 60 * 60_000, // 1h
  });
}
