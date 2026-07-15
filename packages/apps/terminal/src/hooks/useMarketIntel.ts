import { useQuery } from "@tanstack/react-query";
import { getGex, getIVSmile, getMaxPain, getOIProfile } from "@/services/api";
import type {
  GexEntry,
  IVSmileSeriesData,
  MaxPainData,
  OIProfileEntry,
  ProvenancedRows,
} from "@/types/api";
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

function getSampleGex(symbol: string): ProvenancedRows<GexEntry> {
  const { strikes } = getStrikeShape(symbol);
  const netGamma = [-0.42, -0.31, -0.12, 0.08, 0.21, 0.34, 0.18];
  return {
    is_sample_data: true,
    rows: strikes.map((strike, index) => ({
      strike,
      call_gex: 0.12 + index * 0.035,
      put_gex: -(0.34 - index * 0.028),
      net_gex: netGamma[index] ?? 0,
      call_oi: 82_000 + index * 18_500,
      put_oi: 156_000 - index * 13_250,
    })),
  };
}

function getSampleIVSmile(symbol: string): IVSmileSeriesData {
  const { centre, strikes } = getStrikeShape(symbol);
  return {
    is_sample_data: true,
    points: strikes.map((strike) => {
      const moneyness = strike / centre;
      const displacementPct = (moneyness - 1) * 100;
      const curvature = Math.abs(displacementPct) * 1.65;
      return {
        strike,
        call_iv: (11.8 + curvature + Math.max(displacementPct, 0) * 0.9) / 100,
        put_iv: (12.4 + curvature + Math.max(-displacementPct, 0) * 1.1) / 100,
        moneyness,
      };
    }),
  };
}

function getSampleMaxPain(symbol: string): MaxPainData {
  const { centre, strikes } = getStrikeShape(symbol);
  return {
    is_sample_data: true,
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

function getSampleOIProfile(symbol: string): ProvenancedRows<OIProfileEntry> {
  const { strikes } = getStrikeShape(symbol);
  return {
    is_sample_data: true,
    rows: strikes.flatMap((strike, index) => {
      const ceOi = 76_000 + index * 21_000;
      const peOi = 166_000 - index * 17_000;
      return [
        {
          strike,
          type: "PE" as const,
          oi: peOi,
          oi_delta_d: 4_800 - index * 1_150,
          ltp: 162.5 - index * 17.25,
          price_change: index % 2 === 0 ? 1.25 : -0.8,
        },
        {
          strike,
          type: "CE" as const,
          oi: ceOi,
          oi_delta_d: -3_600 + index * 1_700,
          ltp: 52.5 + index * 18.75,
          price_change: index % 2 === 0 ? -0.65 : 1.1,
        },
      ];
    }),
  };
}

export function useGex(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const selectedExpiry = typeof expiry === "string" ? expiry.trim() : "";
  const enabled = !!symbol && !!exchange && !!selectedExpiry;
  return useQuery<ProvenancedRows<GexEntry>>({
    queryKey: ["gex", isExplore ? "sample" : "live", symbol, exchange, selectedExpiry || null],
    queryFn: ({ signal }) => isExplore
      ? Promise.resolve(getSampleGex(symbol))
      : getGex(symbol, exchange, selectedExpiry, signal),
    enabled,
    initialData: isExplore && enabled ? getSampleGex(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useIVSmile(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const selectedExpiry = typeof expiry === "string" ? expiry.trim() : "";
  const enabled = !!symbol && !!exchange && !!selectedExpiry;
  return useQuery<IVSmileSeriesData>({
    queryKey: ["ivSmile", isExplore ? "sample" : "live", symbol, exchange, selectedExpiry || null],
    queryFn: ({ signal }) => isExplore
      ? Promise.resolve(getSampleIVSmile(symbol))
      : getIVSmile(symbol, exchange, selectedExpiry, signal),
    enabled,
    initialData: isExplore && enabled ? getSampleIVSmile(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}

export function useMaxPain(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const selectedExpiry = typeof expiry === "string" ? expiry.trim() : "";
  const enabled = !!symbol && !!exchange && !!selectedExpiry;
  return useQuery<MaxPainData>({
    queryKey: ["maxPain", isExplore ? "sample" : "live", symbol, exchange, selectedExpiry || null],
    queryFn: ({ signal }) => isExplore
      ? Promise.resolve(getSampleMaxPain(symbol))
      : getMaxPain(symbol, exchange, selectedExpiry, signal),
    enabled,
    initialData: isExplore && enabled ? getSampleMaxPain(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 60_000 : false),
  });
}

export function useOIProfile(symbol: string, exchange: string, expiry?: string) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  const selectedExpiry = typeof expiry === "string" ? expiry.trim() : "";
  const enabled = !!symbol && !!exchange && !!selectedExpiry;
  return useQuery<ProvenancedRows<OIProfileEntry>>({
    queryKey: ["oiProfile", isExplore ? "sample" : "live", symbol, exchange, selectedExpiry || null],
    queryFn: ({ signal }) => isExplore
      ? Promise.resolve(getSampleOIProfile(symbol))
      : getOIProfile(symbol, exchange, selectedExpiry, signal),
    enabled,
    initialData: isExplore && enabled ? getSampleOIProfile(symbol) : undefined,
    refetchInterval: () => (isMarketHours() ? 30_000 : false),
  });
}
