import { useQuery } from "@tanstack/react-query";
import { getGex, getIVSmile, getMaxPain, getOIProfile } from "@/services/api";
import type { GexEntry, IVSmileEntry, MaxPainData, OIProfileEntry } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { useModeStore } from "@/stores/modeStore";

const STRIKE_CENTRES: Record<string, number> = {
  NIFTY: 23500,
  BANKNIFTY: 51000,
  FINNIFTY: 22200,
  MIDCPNIFTY: 12800,
  SENSEX: 78000,
};

function getStrikeShape(symbol: string) {
  const centre = STRIKE_CENTRES[symbol] ?? STRIKE_CENTRES.NIFTY;
  const step = symbol === "BANKNIFTY" || symbol === "SENSEX" ? 100 : 50;
  const strikes = [-3, -2, -1, 0, 1, 2, 3].map((offset) => centre + offset * step);
  return { centre, step, strikes };
}

function getSampleGex(symbol: string): GexEntry[] {
  const { strikes } = getStrikeShape(symbol);
  const netGamma = [-0.42, -0.31, -0.12, 0.08, 0.21, 0.34, 0.18];
  return strikes.map((strike, index) => ({
    strike,
    call_gamma: 0.12 + index * 0.035,
    put_gamma: -(0.34 - index * 0.028),
    net_gamma: netGamma[index] ?? 0,
    call_oi: 82_000 + index * 18_500,
    put_oi: 156_000 - index * 13_250,
  }));
}

function getSampleIVSmile(symbol: string): IVSmileEntry[] {
  const { centre, strikes } = getStrikeShape(symbol);
  return strikes.map((strike) => {
    const moneyness = ((strike - centre) / centre) * 100;
    const curvature = Math.abs(moneyness) * 1.65;
    return {
      strike,
      call_iv: 11.8 + curvature + Math.max(moneyness, 0) * 0.9,
      put_iv: 12.4 + curvature + Math.max(-moneyness, 0) * 1.1,
      moneyness,
    };
  });
}

function getSampleMaxPain(symbol: string): MaxPainData {
  const { centre, strikes } = getStrikeShape(symbol);
  return {
    max_pain_strike: centre,
    strikes: strikes.map((strike, index) => {
      const distance = Math.abs(strike - centre);
      const callOi = 96_000 + index * 17_500;
      const putOi = 172_000 - index * 15_000;
      const callPain = callOi * Math.max(1, distance / 10);
      const putPain = putOi * Math.max(1, distance / 10);
      return {
        strike,
        call_oi: callOi,
        put_oi: putOi,
        call_pain: Math.round(callPain),
        put_pain: Math.round(putPain),
        total_pain: Math.round(callPain + putPain),
      };
    }),
  };
}

function getSampleOIProfile(symbol: string): OIProfileEntry[] {
  const { strikes } = getStrikeShape(symbol);
  return strikes.flatMap((strike, index) => {
    const ceOi = 76_000 + index * 21_000;
    const peOi = 166_000 - index * 17_000;
    return [
      {
        strike,
        type: "PE" as const,
        oi: peOi,
        oi_delta_d: 4_800 - index * 1_150,
        ltp: 162.5 - index * 17.25,
      },
      {
        strike,
        type: "CE" as const,
        oi: ceOi,
        oi_delta_d: -3_600 + index * 1_700,
        ltp: 52.5 + index * 18.75,
      },
    ];
  });
}

export function useGex(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  return useQuery<GexEntry[]>({
    queryKey: ["gex", isExplore ? "sample" : "live", symbol, exchange, expiry],
    queryFn: () => isExplore ? Promise.resolve(getSampleGex(symbol)) : getGex(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    initialData: isExplore && symbol && exchange ? getSampleGex(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useIVSmile(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  return useQuery<IVSmileEntry[]>({
    queryKey: ["ivSmile", isExplore ? "sample" : "live", symbol, exchange, expiry],
    queryFn: () => isExplore ? Promise.resolve(getSampleIVSmile(symbol)) : getIVSmile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    initialData: isExplore && symbol && exchange ? getSampleIVSmile(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useMaxPain(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  return useQuery<MaxPainData>({
    queryKey: ["maxPain", isExplore ? "sample" : "live", symbol, exchange, expiry],
    queryFn: () => isExplore ? Promise.resolve(getSampleMaxPain(symbol)) : getMaxPain(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    initialData: isExplore && symbol && exchange ? getSampleMaxPain(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useOIProfile(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  return useQuery<OIProfileEntry[]>({
    queryKey: ["oiProfile", isExplore ? "sample" : "live", symbol, exchange, expiry],
    queryFn: () => isExplore ? Promise.resolve(getSampleOIProfile(symbol)) : getOIProfile(symbol, exchange, expiry),
    enabled: !!symbol && !!exchange,
    initialData: isExplore && symbol && exchange ? getSampleOIProfile(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}
