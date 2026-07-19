/**
 * useSectorMovers — mode-aware sector-mover data for the Scanner widget.
 *
 * - explore mode:  returns disclosed sample rows (no broker needed)
 * - practice/live: fetches multi-quotes for a curated NIFTY 50 universe and
 *   derives per-sector advancers/decliners, average change, top gainer/loser
 *   and a strength signal.
 *
 * `isLive` is true only when real quote data actually backs the rows — a
 * failed or pending fetch falls back to sample rows and reports `isLive:
 * false`, so the widget can never badge sample data as live.
 *
 * (The gap/volume halves of the old useScannerData hook were superseded by
 * the backend `/v1/scanner/run` prebuilt scans, which scan real OHLCV history
 * server-side; the client-side volume "ratio" here was a fabricated baseline
 * and was dropped rather than wired.)
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useModeStore } from "@/stores/modeStore";
import { getMultiQuotes, normaliseMultiQuotes } from "@/services/api";
import type { Quote } from "@/types/api";
import {
  SAMPLE_SECTOR_MOVERS,
  type SectorMoverEntry,
} from "@/widgets/utility/Scanner/sampleData";

// ---------------------------------------------------------------------------
// NIFTY 50 watchlist — curated for scanner coverage across sectors
// ---------------------------------------------------------------------------

const SCANNER_SYMBOLS: Array<{ symbol: string; exchange: string; sector: string }> = [
  // Auto
  { symbol: "TATAMOTORS", exchange: "NSE", sector: "Auto" },
  { symbol: "MARUTI", exchange: "NSE", sector: "Auto" },
  { symbol: "M&M", exchange: "NSE", sector: "Auto" },
  { symbol: "EICHERMOT", exchange: "NSE", sector: "Auto" },
  // Banking
  { symbol: "HDFCBANK", exchange: "NSE", sector: "Banking" },
  { symbol: "ICICIBANK", exchange: "NSE", sector: "Banking" },
  { symbol: "SBIN", exchange: "NSE", sector: "Banking" },
  { symbol: "KOTAKBANK", exchange: "NSE", sector: "Banking" },
  { symbol: "AXISBANK", exchange: "NSE", sector: "Banking" },
  // IT
  { symbol: "INFY", exchange: "NSE", sector: "IT" },
  { symbol: "TCS", exchange: "NSE", sector: "IT" },
  { symbol: "WIPRO", exchange: "NSE", sector: "IT" },
  { symbol: "HCLTECH", exchange: "NSE", sector: "IT" },
  { symbol: "TECHM", exchange: "NSE", sector: "IT" },
  // Energy
  { symbol: "RELIANCE", exchange: "NSE", sector: "Energy" },
  { symbol: "ONGC", exchange: "NSE", sector: "Energy" },
  { symbol: "NTPC", exchange: "NSE", sector: "Energy" },
  { symbol: "POWERGRID", exchange: "NSE", sector: "Energy" },
  // Finance
  { symbol: "BAJFINANCE", exchange: "NSE", sector: "Finance" },
  { symbol: "BAJFINSV", exchange: "NSE", sector: "Finance" },
  { symbol: "CHOLAFIN", exchange: "NSE", sector: "Finance" },
  // Metals
  { symbol: "TATASTEEL", exchange: "NSE", sector: "Metals" },
  { symbol: "HINDALCO", exchange: "NSE", sector: "Metals" },
  { symbol: "COALINDIA", exchange: "NSE", sector: "Metals" },
  { symbol: "JSWSTEEL", exchange: "NSE", sector: "Metals" },
  // Pharma
  { symbol: "SUNPHARMA", exchange: "NSE", sector: "Pharma" },
  { symbol: "DRREDDY", exchange: "NSE", sector: "Pharma" },
  { symbol: "CIPLA", exchange: "NSE", sector: "Pharma" },
  // Infra
  { symbol: "ADANIENT", exchange: "NSE", sector: "Infra" },
  { symbol: "ULTRACEMCO", exchange: "NSE", sector: "Infra" },
  { symbol: "ADANIPORTS", exchange: "NSE", sector: "Infra" },
  // FMCG
  { symbol: "ITC", exchange: "NSE", sector: "FMCG" },
  { symbol: "HINDUNILVR", exchange: "NSE", sector: "FMCG" },
  { symbol: "NESTLEIND", exchange: "NSE", sector: "FMCG" },
  // Telecom
  { symbol: "BHARTIARTL", exchange: "NSE", sector: "Telecom" },
];

const SYMBOLS_FOR_QUOTES = SCANNER_SYMBOLS.map(({ symbol, exchange }) => ({
  symbol,
  exchange,
}));

/** Map symbol to sector for quick lookup. */
const SECTOR_MAP = new Map(
  SCANNER_SYMBOLS.map(({ symbol, sector }) => [symbol, sector]),
);

// ---------------------------------------------------------------------------
// Derivation: Quote[] → sector movers
// ---------------------------------------------------------------------------

/** Derive sector movers by grouping quotes by sector. */
export function deriveSectorMovers(quotes: Quote[]): SectorMoverEntry[] {
  const sectors = new Map<
    string,
    { changes: number[]; symbols: Array<{ symbol: string; change: number }> }
  >();

  for (const q of quotes) {
    const sector = SECTOR_MAP.get(q.symbol);
    if (!sector) continue;
    const prevClose = q.prev_close ?? q.close;
    if (!prevClose || prevClose <= 0) continue;
    const changePct = ((q.ltp - prevClose) / prevClose) * 100;

    let entry = sectors.get(sector);
    if (!entry) {
      entry = { changes: [], symbols: [] };
      sectors.set(sector, entry);
    }
    entry.changes.push(changePct);
    entry.symbols.push({ symbol: q.symbol, change: changePct });
  }

  const result: SectorMoverEntry[] = [];

  for (const [sector, { changes, symbols }] of sectors) {
    if (changes.length === 0) continue;
    const avgChange =
      Math.round((changes.reduce((s, c) => s + c, 0) / changes.length) * 100) / 100;
    const advancers = changes.filter((c) => c > 0).length;
    const decliners = changes.filter((c) => c < 0).length;
    const unchanged = changes.filter((c) => c === 0).length;

    // Sort symbols to find top gainer/loser
    const sorted = [...symbols].sort((a, b) => b.change - a.change);
    const topGainer = sorted[0]?.symbol ?? "-";
    const topLoser = sorted[sorted.length - 1]?.symbol ?? "-";

    let signal: SectorMoverEntry["signal"] = "moderate";
    if (avgChange > 1) signal = "strong";
    else if (avgChange < -0.5) signal = "bearish";
    else if (Math.abs(avgChange) < 0.3) signal = "weak";

    result.push({
      sector,
      advancers,
      decliners,
      unchanged,
      avgChange,
      topGainer,
      topLoser,
      signal,
    });
  }

  return result.sort((a, b) => Math.abs(b.avgChange) - Math.abs(a.avgChange));
}

/** One top gainer/loser row derived from the quote sweep. */
export interface TopMover {
  symbol: string;
  ltp: number;
  changePct: number;
}

/** Top-N gainers and losers by percentage change from the quote sweep. */
export function deriveTopMovers(quotes: Quote[], topN = 5): {
  gainers: TopMover[];
  losers: TopMover[];
} {
  const rows: TopMover[] = [];
  for (const q of quotes) {
    const prevClose = q.prev_close ?? q.close;
    if (!prevClose || prevClose <= 0) continue;
    rows.push({
      symbol: q.symbol,
      ltp: q.ltp,
      changePct: ((q.ltp - prevClose) / prevClose) * 100,
    });
  }
  rows.sort((a, b) => b.changePct - a.changePct);
  return {
    gainers: rows.slice(0, topN).filter((r) => r.changePct > 0),
    losers: rows.slice(-topN).reverse().filter((r) => r.changePct < 0),
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseSectorMoversResult {
  data: SectorMoverEntry[];
  /** Top gainers/losers from the same quote sweep (empty in sample mode —
   *  consumers supply their own disclosed samples). */
  movers: { gainers: TopMover[]; losers: TopMover[] };
  isLoading: boolean;
  /** True only when a HEALTHY live fetch backs the rows — never for the
   *  sample fallback, and never once the feed has gone into error (frozen
   *  quotes must not keep a live badge). */
  isLive: boolean;
  /** True outside Explore — the hook is trying for live data. */
  wantsLive: boolean;
  error: Error | null;
  refetch: () => void;
}

export function useSectorMovers(): UseSectorMoversResult {
  const mode = useModeStore((s) => s.mode);
  const wantsLive = mode !== "explore";

  const query = useQuery({
    queryKey: ["scanner", "multiquotes"],
    queryFn: () => getMultiQuotes(SYMBOLS_FOR_QUOTES).then(normaliseMultiQuotes),
    enabled: wantsLive,
    refetchInterval: 60_000, // auto-refresh every 60s
    staleTime: 30_000,
    retry: 2,
  });

  // A feed that has gone into error keeps its last data in the query cache,
  // but frozen quotes must not be presented as live — fall back to the
  // disclosed sample rows until the next successful refetch.
  const hasLiveData =
    wantsLive && !query.isError && query.data !== undefined && query.data.length > 0;

  const data = useMemo<SectorMoverEntry[]>(() => {
    if (!hasLiveData || !query.data) return SAMPLE_SECTOR_MOVERS;
    return deriveSectorMovers(query.data);
  }, [hasLiveData, query.data]);

  const movers = useMemo(
    () =>
      hasLiveData && query.data
        ? deriveTopMovers(query.data)
        : { gainers: [], losers: [] },
    [hasLiveData, query.data],
  );

  return {
    data,
    movers,
    isLoading: wantsLive && query.isLoading,
    isLive: hasLiveData,
    wantsLive,
    error: wantsLive ? (query.error as Error | null) : null,
    refetch: () => {
      void query.refetch();
    },
  };
}
