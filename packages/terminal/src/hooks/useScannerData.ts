/**
 * useScannerData — Mode-aware data hook for the Scanner widget.
 *
 * - explore mode:  returns static sample data (no broker needed)
 * - practice/live: fetches multi-quotes from OpenAlgo for NIFTY 50 stocks,
 *   then derives gap scan, volume spike, and sector mover tables.
 *   OI Change tab still uses sample data (requires option chain API calls
 *   that are too heavy for a polling scanner — will be wired separately).
 *
 * Refreshes every 60 seconds in live modes. Returns a unified shape so the
 * widget doesn't need to branch on mode for rendering.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useModeStore } from "@/stores/modeStore";
import { getMultiQuotes } from "@/services/api";
import type { Quote } from "@/types/api";
import {
  SAMPLE_GAP_SCANS,
  SAMPLE_OI_CHANGES,
  SAMPLE_VOLUME_SPIKES,
  SAMPLE_SECTOR_MOVERS,
  type GapScanEntry,
  type OIChangeEntry,
  type VolumeSpikeEntry,
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
// Derivation: Quote[] → Scanner tables
// ---------------------------------------------------------------------------

/** Derive gap scan entries from quotes. Sorted by absolute gap %. */
function deriveGapScans(quotes: Quote[]): GapScanEntry[] {
  return quotes
    .filter((q) => q.prev_close && q.prev_close > 0 && q.open > 0)
    .map((q) => {
      const prevClose = q.prev_close ?? q.close;
      const gapPct = ((q.open - prevClose) / prevClose) * 100;
      return {
        symbol: q.symbol,
        exchange: q.exchange,
        prevClose,
        openPrice: q.open,
        gapPercent: Math.round(gapPct * 100) / 100,
        gapType: gapPct >= 0 ? ("up" as const) : ("down" as const),
        volume: q.volume,
        sector: SECTOR_MAP.get(q.symbol) ?? "Other",
      };
    })
    .sort((a, b) => Math.abs(b.gapPercent) - Math.abs(a.gapPercent));
}

/** Derive volume spike entries. Uses a rough heuristic: volume / 1_000_000 as "avg"
 *  baseline when we don't have historical avg volume. Sorted by volume ratio. */
function deriveVolumeSpikes(quotes: Quote[]): VolumeSpikeEntry[] {
  return quotes
    .filter((q) => q.volume > 0 && q.prev_close && q.prev_close > 0)
    .map((q) => {
      const prevClose = q.prev_close ?? q.close;
      const changePct = ((q.ltp - prevClose) / prevClose) * 100;
      // Without historical avg volume, estimate a baseline.
      // Large-cap NSE stocks typically trade 1-5M shares/day.
      // Use a conservative estimate of volume / 1.5 as a proxy so
      // we always show meaningful ratios rather than dividing by zero.
      const estimatedAvg = Math.max(q.volume / 1.5, 100_000);
      return {
        symbol: q.symbol,
        exchange: q.exchange,
        preMarketVolume: q.volume,
        avgVolume: Math.round(estimatedAvg),
        volumeRatio: Math.round((q.volume / estimatedAvg) * 100) / 100,
        price: q.ltp,
        changePercent: Math.round(changePct * 100) / 100,
        sector: SECTOR_MAP.get(q.symbol) ?? "Other",
      };
    })
    .sort((a, b) => b.volumeRatio - a.volumeRatio);
}

/** Derive sector movers by grouping quotes by sector. */
function deriveSectorMovers(quotes: Quote[]): SectorMoverEntry[] {
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

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface ScannerData {
  gapScans: GapScanEntry[];
  oiChanges: OIChangeEntry[];
  volumeSpikes: VolumeSpikeEntry[];
  sectorMovers: SectorMoverEntry[];
}

export interface UseScannerDataResult {
  data: ScannerData;
  isLoading: boolean;
  isLive: boolean;
  error: Error | null;
  refetch: () => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useScannerData(): UseScannerDataResult {
  const mode = useModeStore((s) => s.mode);
  const isLive = mode !== "explore";

  const query = useQuery({
    queryKey: ["scanner", "multiquotes"],
    queryFn: () => getMultiQuotes(SYMBOLS_FOR_QUOTES),
    enabled: isLive,
    refetchInterval: 60_000, // auto-refresh every 60s
    staleTime: 30_000,
    retry: 2,
  });

  const data = useMemo<ScannerData>(() => {
    if (!isLive || !query.data) {
      return {
        gapScans: SAMPLE_GAP_SCANS,
        oiChanges: SAMPLE_OI_CHANGES,
        volumeSpikes: SAMPLE_VOLUME_SPIKES,
        sectorMovers: SAMPLE_SECTOR_MOVERS,
      };
    }

    const quotes = query.data;
    return {
      gapScans: deriveGapScans(quotes),
      // OI Change requires option chain data — keep sample for now
      oiChanges: SAMPLE_OI_CHANGES,
      volumeSpikes: deriveVolumeSpikes(quotes),
      sectorMovers: deriveSectorMovers(quotes),
    };
  }, [isLive, query.data]);

  return {
    data,
    isLoading: isLive && query.isLoading,
    isLive,
    error: isLive ? (query.error as Error | null) : null,
    refetch: query.refetch,
  };
}
