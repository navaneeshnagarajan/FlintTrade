/**
 * useSectorMapData
 *
 * Fetches live sector/stock data via OpenAlgo's multiquotes API.
 * - Explore mode: returns null (widget falls back to synthetic demo data)
 * - Practice/Live mode: fetches LTP + change for predefined sectoral stocks
 * - Refreshes every 30s during market hours, every 120s otherwise
 */

import { useQuery } from "@tanstack/react-query";
import { getMultiQuotes, normaliseMultiQuotes } from "@/services/api";
import { useModeStore } from "@/stores/modeStore";
import { isMarketHours } from "@/lib/market";
import type { Quote } from "@/types/api";

// ---------------------------------------------------------------------------
// Sector → Stock mapping (top stocks per NSE sector)
// ---------------------------------------------------------------------------
export const SECTOR_STOCK_MAP: Record<string, Array<{ symbol: string; exchange: string }>> = {
  Banking: [
    { symbol: "HDFCBANK", exchange: "NSE" },
    { symbol: "ICICIBANK", exchange: "NSE" },
    { symbol: "SBIN", exchange: "NSE" },
    { symbol: "KOTAKBANK", exchange: "NSE" },
    { symbol: "AXISBANK", exchange: "NSE" },
  ],
  IT: [
    { symbol: "TCS", exchange: "NSE" },
    { symbol: "INFY", exchange: "NSE" },
    { symbol: "WIPRO", exchange: "NSE" },
    { symbol: "HCLTECH", exchange: "NSE" },
    { symbol: "TECHM", exchange: "NSE" },
  ],
  Energy: [
    { symbol: "RELIANCE", exchange: "NSE" },
    { symbol: "ONGC", exchange: "NSE" },
    { symbol: "IOC", exchange: "NSE" },
    { symbol: "BPCL", exchange: "NSE" },
    { symbol: "NTPC", exchange: "NSE" },
  ],
  Pharma: [
    { symbol: "SUNPHARMA", exchange: "NSE" },
    { symbol: "DRREDDY", exchange: "NSE" },
    { symbol: "CIPLA", exchange: "NSE" },
    { symbol: "DIVISLAB", exchange: "NSE" },
  ],
  Auto: [
    { symbol: "MARUTI", exchange: "NSE" },
    { symbol: "TATAMOTORS", exchange: "NSE" },
    { symbol: "M&M", exchange: "NSE" },
    { symbol: "BAJAJ-AUTO", exchange: "NSE" },
  ],
  FMCG: [
    { symbol: "HINDUNILVR", exchange: "NSE" },
    { symbol: "ITC", exchange: "NSE" },
    { symbol: "NESTLEIND", exchange: "NSE" },
    { symbol: "BRITANNIA", exchange: "NSE" },
  ],
  Metal: [
    { symbol: "TATASTEEL", exchange: "NSE" },
    { symbol: "HINDALCO", exchange: "NSE" },
    { symbol: "JSWSTEEL", exchange: "NSE" },
    { symbol: "COALINDIA", exchange: "NSE" },
  ],
  Infra: [
    { symbol: "LT", exchange: "NSE" },
    { symbol: "POWERGRID", exchange: "NSE" },
    { symbol: "ADANIPORTS", exchange: "NSE" },
  ],
  NBFC: [
    { symbol: "BAJFINANCE", exchange: "NSE" },
    { symbol: "BAJAJFINSV", exchange: "NSE" },
    { symbol: "HDFCLIFE", exchange: "NSE" },
    { symbol: "SBILIFE", exchange: "NSE" },
  ],
  Consumer: [
    { symbol: "TITAN", exchange: "NSE" },
    { symbol: "ASIANPAINT", exchange: "NSE" },
    { symbol: "TRENT", exchange: "NSE" },
  ],
  Realty: [
    { symbol: "DLF", exchange: "NSE" },
    { symbol: "GODREJPROP", exchange: "NSE" },
    { symbol: "OBEROIRLTY", exchange: "NSE" },
  ],
  Media: [
    { symbol: "ZEEL", exchange: "NSE" },
    { symbol: "PVR", exchange: "NSE" },
  ],
};

// Build a flat list of all symbols and a reverse lookup
const ALL_SYMBOLS: Array<{ symbol: string; exchange: string }> = [];
const SYMBOL_TO_SECTOR: Record<string, string> = {};
for (const [sector, stocks] of Object.entries(SECTOR_STOCK_MAP)) {
  for (const s of stocks) {
    ALL_SYMBOLS.push(s);
    SYMBOL_TO_SECTOR[s.symbol] = sector;
  }
}

export interface SectorStockData {
  symbol: string;
  ltp: number;
  change: number;
  sector: string;
}

function quotesToStockData(quotes: Quote[]): SectorStockData[] {
  return quotes
    .map((q) => {
      const prevClose = q.prev_close ?? q.close;
      const changePct =
        q.pct != null
          ? q.pct
          : prevClose > 0
          ? ((q.ltp - prevClose) / prevClose) * 100
          : 0;
      return {
        symbol: q.symbol,
        ltp: q.ltp,
        change: changePct,
        sector: SYMBOL_TO_SECTOR[q.symbol] ?? "Others",
      };
    })
    .filter((s) => s.ltp > 0);
}

export function useSectorMapData(): {
  data: SectorStockData[] | null;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
} {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode === "practice" || mode === "live";

  const query = useQuery<SectorStockData[]>({
    queryKey: ["sectormap-quotes"],
    queryFn: async () => {
      const raw = await getMultiQuotes(ALL_SYMBOLS);
      return quotesToStockData(normaliseMultiQuotes(raw));
    },
    enabled: isLive,
    staleTime: 15_000,
    refetchInterval: () => (isMarketHours() ? 30_000 : 120_000),
  });

  if (!isLive) {
    return { data: null, isLoading: false, isError: false, refetch: query.refetch };
  }

  return {
    data: query.data ?? null,
    isLoading: query.isLoading,
    isError: query.isError,
    refetch: query.refetch,
  };
}
