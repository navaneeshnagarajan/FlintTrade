/** Batch quotes and bounded local sparkline history owned by one market authority. */
import { useEffect, useMemo, useState } from "react";
import { getMultiQuotes, normaliseMultiQuotes } from "@/services/api";
import { requireCurrentMarketDataScope, useMarketDataScope } from "@/hooks/useDataScope";
import { isMarketHours } from "@/lib/market";
import { SPARK_MAX } from "./types";
import type { WatchlistItem, QuoteMap, SparkMap, PartialQuote } from "./types";

interface UseWatchlistPollingResult {
  quotes: QuoteMap;
  sparkHistory: SparkMap;
  fetchError: string | null;
  isLoading: boolean;
}
interface PollState extends UseWatchlistPollingResult {
  identity: string;
}

function emptyState(identity: string, isLoading: boolean): PollState {
  return { identity, quotes: {}, sparkHistory: {}, fetchError: null, isLoading };
}

export function useWatchlistPolling(watchlist: WatchlistItem[]): UseWatchlistPollingResult {
  const dataScope = useMarketDataScope();
  const symbolsKey = JSON.stringify(watchlist.map(({ symbol, exchange }) => [symbol, exchange]));
  const symbols = useMemo(() => (JSON.parse(symbolsKey) as Array<[string, string]>)
    .map(([symbol, exchange]) => ({ symbol, exchange })), [symbolsKey]);
  const identity = JSON.stringify([dataScope, symbolsKey]);
  const [state, setState] = useState<PollState>(() => emptyState(identity, symbols.length > 0));

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    setState(emptyState(identity, symbols.length > 0));

    const isCurrent = () => {
      if (!active || controller.signal.aborted) return false;
      try {
        requireCurrentMarketDataScope(dataScope);
        return true;
      } catch {
        return false;
      }
    };

    async function poll() {
      if (!symbols.length || !isCurrent()) return;
      try {
        const response = await getMultiQuotes(symbols, controller.signal, dataScope);
        if (!isCurrent()) return;
        const next: QuoteMap = {};
        if (Array.isArray(response) || (response && "results" in response)) {
          const flat = normaliseMultiQuotes(response);
          const byKey = new Map<string, PartialQuote>();
          flat.forEach((quote) => {
            if (quote.symbol && quote.exchange) byKey.set(`${quote.symbol}:${quote.exchange}`, quote);
          });
          symbols.forEach((item, index) => {
            const key = `${item.symbol}:${item.exchange}`;
            const positional = flat[index];
            // Named responses must match the requested instrument. Positional
            // fallback is only for adapters omitting instrument identity.
            const quote = byKey.get(key) ?? (positional && !positional.symbol && !positional.exchange ? positional : undefined);
            if (quote) next[key] = quote;
          });
        } else if (response && typeof response === "object") {
          const keyed = response as unknown as Record<string, PartialQuote>;
          symbols.forEach(({ symbol, exchange }) => {
            const key = `${symbol}:${exchange}`;
            const quote = keyed[key] ?? keyed[`${exchange}:${symbol}`] ?? keyed[symbol];
            if (quote) next[key] = quote;
          });
        }
        setState((previous) => {
          if (!isCurrent() || previous.identity !== identity) return previous;
          const history: SparkMap = { ...previous.sparkHistory };
          Object.entries(next).forEach(([key, quote]) => {
            const price = Number(quote.ltp ?? quote.close);
            if ((quote.ltp != null || quote.close != null) && Number.isFinite(price)) {
              history[key] = [...(history[key] ?? []).slice(-(SPARK_MAX - 1)), price];
            }
          });
          return { identity, quotes: { ...previous.quotes, ...next }, sparkHistory: history, fetchError: null, isLoading: false };
        });
      } catch (error) {
        if (!isCurrent()) return;
        setState((previous) => isCurrent() && previous.identity === identity
          ? { ...previous, fetchError: error instanceof Error ? error.message : "Quote fetch failed", isLoading: false }
          : previous);
      } finally {
        // Schedule after completion, so slow reads cannot overlap. An old
        // authority or retired StrictMode effect owns no future poll.
        if (isCurrent()) timer = setTimeout(() => void poll(), isMarketHours() ? 5_000 : 60_000);
      }
    }
    void poll();
    return () => {
      active = false;
      controller.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [dataScope, identity, symbols]);

  // This render guard removes prior-source figures before effect cleanup.
  return state.identity === identity ? state : emptyState(identity, symbols.length > 0);
}
