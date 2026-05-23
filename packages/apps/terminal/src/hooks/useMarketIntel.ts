import { useQuery } from "@tanstack/react-query";
import { getGex, getIVSmile, getMaxPain, getOIProfile } from "@/services/api";
import type { GexEntry, IVSmileEntry, MaxPainData, OIProfileEntry } from "@/types/api";
import { isMarketHours } from "@/lib/market";

export function useGex(symbol: string, exchange: string, expiry?: string) {
  return useQuery<GexEntry[]>({
    queryKey: ["gex", symbol, exchange, expiry],
    queryFn: () => getGex(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useIVSmile(symbol: string, exchange: string, expiry?: string) {
  return useQuery<IVSmileEntry[]>({
    queryKey: ["ivSmile", symbol, exchange, expiry],
    queryFn: () => getIVSmile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useMaxPain(symbol: string, exchange: string, expiry?: string) {
  return useQuery<MaxPainData>({
    queryKey: ["maxPain", symbol, exchange, expiry],
    queryFn: () => getMaxPain(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useOIProfile(symbol: string, exchange: string, expiry?: string) {
  return useQuery<OIProfileEntry[]>({
    queryKey: ["oiProfile", symbol, exchange, expiry],
    queryFn: () => getOIProfile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}
