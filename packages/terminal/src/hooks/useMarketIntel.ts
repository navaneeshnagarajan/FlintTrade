import { useQuery } from "@tanstack/react-query";
import { getGex, getIVSmile, getMaxPain, getOIProfile } from "@/services/api";
import type { GexEntry, IVSmileEntry, MaxPainData, OIProfileEntry } from "@/types/api";

function isMarketHours(): boolean {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 555 && mins <= 930;
}

export function useGex(symbol: string, exchange: string, expiry?: string) {
  return useQuery<GexEntry[]>({
    queryKey: ["gex", symbol, exchange, expiry],
    queryFn: () => getGex(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: isMarketHours() ? 30_000 : false,
  });
}

export function useIVSmile(symbol: string, exchange: string, expiry?: string) {
  return useQuery<IVSmileEntry[]>({
    queryKey: ["ivSmile", symbol, exchange, expiry],
    queryFn: () => getIVSmile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: isMarketHours() ? 30_000 : false,
  });
}

export function useMaxPain(symbol: string, exchange: string, expiry?: string) {
  return useQuery<MaxPainData>({
    queryKey: ["maxPain", symbol, exchange, expiry],
    queryFn: () => getMaxPain(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: isMarketHours() ? 30_000 : false,
  });
}

export function useOIProfile(symbol: string, exchange: string, expiry?: string) {
  return useQuery<OIProfileEntry[]>({
    queryKey: ["oiProfile", symbol, exchange, expiry],
    queryFn: () => getOIProfile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    refetchInterval: isMarketHours() ? 30_000 : false,
  });
}
