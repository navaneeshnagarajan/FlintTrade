/**
 * useArbitrageScanner — TanStack Query hook for the arbitrage scanner (DP3).
 *
 * Builds a REAL scan request from live observed prices before posting to the
 * FlintTrade backend /ft-api/api/v1/screener/arbitrage:
 *   1. resolves each universe underlying's nearest futures expiry,
 *   2. batch-fetches the spot, futures and NSE/BSE cross-listing quotes,
 *   3. posts the observed prices plus the operator's edge threshold.
 *
 * Honesty contract: with no usable quotes the hook THROWS (surfacing the
 * widget's error state) rather than posting an empty request — an empty
 * request makes the backend return its canned sample scan, which is only
 * acceptable as the widget's explicit disconnected fallback. The query is
 * disabled entirely while disconnected, so there is no background refetch
 * churn without a broker.
 */

import { useQuery } from "@tanstack/react-query";
import { getArbitrageScan } from "@/services/ftApi";
import type { ArbitrageScanRequest } from "@/services/ftApi";
import { getExpiry, getMultiQuotes, normaliseMultiQuotes } from "@/services/api";
import { isMarketHours } from "@/lib/market";

/** Scan parameters collected by the widget UI. */
export interface ArbitrageScanParams {
  /** Underlyings (scrips or indices) to scan for cash-future dislocations. */
  universe: string[];
  /** Minimum annualised edge over funding to flag a signal, in percent. */
  edgeThresholdPct: number;
}

/** Index underlyings quote their spot on the *_INDEX pseudo-exchanges. */
const INDEX_SPOT_EXCHANGE: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  MIDCPNIFTY: "NSE_INDEX",
  SENSEX: "BSE_INDEX",
};

/** Futures exchange per underlying (default NFO). */
const FUTURES_EXCHANGE: Record<string, string> = {
  SENSEX: "BFO",
};

const MONTHS: Record<string, number> = {
  JAN: 0, FEB: 1, MAR: 2, APR: 3, MAY: 4, JUN: 5,
  JUL: 6, AUG: 7, SEP: 8, OCT: 9, NOV: 10, DEC: 11,
};

/** Parse an expiry like "26-AUG-25" into whole calendar days from today. */
export function daysToExpiry(expiry: string, now: Date = new Date()): number | null {
  const m = /^(\d{1,2})-([A-Z]{3})-(\d{2}|\d{4})$/.exec(expiry.trim().toUpperCase());
  if (!m) return null;
  const month = MONTHS[m[2]];
  if (month === undefined) return null;
  const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
  const target = new Date(year, month, Number(m[1]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((target.getTime() - today.getTime()) / 86_400_000);
  return days >= 0 ? days : null;
}

/** Normalise the raw universe input: trimmed, upper-cased, de-duplicated. */
export function normaliseUniverse(universe: string[]): string[] {
  return [...new Set(universe.map((u) => u.trim().toUpperCase()).filter(Boolean))];
}

interface ResolvedFuture {
  underlying: string;
  futuresExchange: string;
  futuresSymbol: string;
  daysToExpiry: number;
}

/** Resolve each underlying's nearest futures contract (failures skip it). */
async function resolveFutures(universe: string[]): Promise<ResolvedFuture[]> {
  const settled = await Promise.allSettled(
    universe.map(async (underlying): Promise<ResolvedFuture | null> => {
      const futuresExchange = FUTURES_EXCHANGE[underlying] ?? "NFO";
      const resp = await getExpiry(underlying, futuresExchange, "futures");
      const expiries = Array.isArray(resp) ? (resp as unknown as string[]) : resp.expiry ?? [];
      let best: { expiry: string; days: number } | null = null;
      for (const e of expiries) {
        const days = daysToExpiry(e);
        if (days !== null && (best === null || days < best.days)) best = { expiry: e, days };
      }
      if (!best) return null;
      return {
        underlying,
        futuresExchange,
        futuresSymbol: `${underlying}${best.expiry.replace(/-/g, "").toUpperCase()}FUT`,
        daysToExpiry: best.days,
      };
    }),
  );
  return settled
    .filter((r): r is PromiseFulfilledResult<ResolvedFuture | null> => r.status === "fulfilled")
    .map((r) => r.value)
    .filter((r): r is ResolvedFuture => r !== null);
}

/**
 * Build the scan request from live quotes for the given universe.
 *
 * @throws Error when no usable quotes could be observed — the caller must NOT
 *   fall back to posting an empty request (that returns fabricated data).
 */
export async function buildScanRequest(params: ArbitrageScanParams): Promise<ArbitrageScanRequest> {
  const universe = normaliseUniverse(params.universe);
  const futures = await resolveFutures(universe);

  // Assemble the batch quote list: spot + future per underlying, plus the BSE
  // cross-listing for non-index scrips (cross-exchange gap scan).
  const instruments: Array<{ symbol: string; exchange: string }> = [];
  for (const u of universe) {
    instruments.push({ symbol: u, exchange: INDEX_SPOT_EXCHANGE[u] ?? "NSE" });
    if (!(u in INDEX_SPOT_EXCHANGE)) instruments.push({ symbol: u, exchange: "BSE" });
  }
  for (const f of futures) {
    instruments.push({ symbol: f.futuresSymbol, exchange: f.futuresExchange });
  }

  const priceByKey = new Map<string, number>();
  if (instruments.length > 0) {
    try {
      const quotes = normaliseMultiQuotes(await getMultiQuotes(instruments));
      for (const q of quotes) {
        // LTP is the observed price; off-market fall back to the session close
        // (both are real prices, never fabricated).
        const px = q.ltp > 0 ? q.ltp : q.close;
        if (px > 0) priceByKey.set(`${q.exchange}:${q.symbol}`, px);
      }
    } catch {
      // Quote fetch failed wholesale — fall through to the honest error below.
    }
  }

  const cashFuture: NonNullable<ArbitrageScanRequest["cash_future"]> = [];
  for (const f of futures) {
    const spotExchange = INDEX_SPOT_EXCHANGE[f.underlying] ?? "NSE";
    const spot = priceByKey.get(`${spotExchange}:${f.underlying}`);
    const future = priceByKey.get(`${f.futuresExchange}:${f.futuresSymbol}`);
    if (spot !== undefined && future !== undefined) {
      cashFuture.push({
        underlying: f.underlying,
        spot,
        future_price: future,
        days_to_expiry: f.daysToExpiry,
        exchange: f.futuresExchange,
      });
    }
  }

  const crossExchange: NonNullable<ArbitrageScanRequest["cross_exchange"]> = [];
  for (const u of universe) {
    if (u in INDEX_SPOT_EXCHANGE) continue;
    const nse = priceByKey.get(`NSE:${u}`);
    const bse = priceByKey.get(`BSE:${u}`);
    if (nse !== undefined && bse !== undefined) {
      crossExchange.push({
        symbol: u,
        exchange_a: "NSE",
        price_a: nse,
        exchange_b: "BSE",
        price_b: bse,
      });
    }
  }

  if (cashFuture.length === 0 && crossExchange.length === 0) {
    throw new Error(
      "No live quotes available for the scan universe — scan not performed.",
    );
  }

  return {
    cash_future: cashFuture,
    cross_exchange: crossExchange,
    edge_threshold_pct: params.edgeThresholdPct,
  };
}

export function useArbitrageScanner(params: ArbitrageScanParams, isConnected = false) {
  const universe = normaliseUniverse(params.universe);
  return useQuery({
    queryKey: ["arbitrage-scan", universe, params.edgeThresholdPct],
    queryFn: async () =>
      getArbitrageScan(await buildScanRequest({ ...params, universe })),
    // Disabled while disconnected (the widget shows its clearly-badged local
    // sample instead) and with an empty universe (nothing to scan).
    enabled: isConnected && universe.length > 0,
    // Rescan every 30s during market hours only — each refetch re-observes
    // live prices, so this is a real rescan, not sample churn.
    refetchInterval: isConnected && isMarketHours() ? 30_000 : false,
    staleTime: 25_000,
  });
}
