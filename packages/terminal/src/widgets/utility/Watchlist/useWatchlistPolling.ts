/**
 * useWatchlistPolling — batch quote fetching hook for WatchlistWidget.
 *
 * Polls at 5s during market hours, 60s off-hours.
 * Maintains SparkMap history (last SPARK_MAX samples per symbol).
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { getMultiQuotes } from "@/services/api";
import type { WsInstrument } from "@/types/api";
import { isMarketHours } from "@/lib/market";
import { SPARK_MAX } from "./types";
import type { WatchlistItem, QuoteMap, SparkMap, PartialQuote } from "./types";

interface UseWatchlistPollingResult {
  quotes:       QuoteMap;
  sparkHistory: SparkMap;
  fetchError:   string | null;
}

export function useWatchlistPolling(watchlist: WatchlistItem[]): UseWatchlistPollingResult {
  const [quotes, setQuotes]           = useState<QuoteMap>({});
  const [sparkHistory, setSparkHistory] = useState<SparkMap>({});
  const [fetchError, setFetchError]   = useState<string | null>(null);
  const pollRef                       = useRef<ReturnType<typeof setTimeout> | null>(null);

  const watchlistRef = useRef(watchlist);
  useEffect(() => {
    watchlistRef.current = watchlist;
  }, [watchlist]);

  const instrumentsMemo = useMemo(
    () => watchlist.map((w): WsInstrument => ({ symbol: w.symbol, exchange: w.exchange })),
    [watchlist],
  );
  const instrumentsRef = useRef(instrumentsMemo);
  useEffect(() => {
    instrumentsRef.current = instrumentsMemo;
  }, [instrumentsMemo]);

  const fetchQuotes = useCallback(async () => {
    const currentWatchlist = watchlistRef.current;
    const symbols = instrumentsRef.current;
    if (symbols.length === 0) return;

    try {
      const data = await getMultiQuotes(symbols);
      setFetchError(null);

      if (Array.isArray(data)) {
        const next: QuoteMap = {};
        setSparkHistory((prevSpark) => {
          const histNext: SparkMap = { ...prevSpark };
          data.forEach((q: PartialQuote, idx: number) => {
            const item = currentWatchlist[idx];
            if (!item) return;
            const key = `${item.symbol}:${item.exchange}`;
            next[key] = q;
            const ltp = q?.ltp ?? q?.close ?? null;
            if (ltp != null) {
              histNext[key] = [...(prevSpark[key] ?? []).slice(-(SPARK_MAX - 1)), Number(ltp)];
            }
          });
          return histNext;
        });
        setQuotes((prev) => ({ ...prev, ...next }));
      } else if (data && typeof data === "object") {
        const dataObj = data as Record<string, PartialQuote>;
        const next: QuoteMap = {};
        setSparkHistory((prevSpark) => {
          const histNext: SparkMap = { ...prevSpark };
          currentWatchlist.forEach((item) => {
            const key = `${item.symbol}:${item.exchange}`;
            const q =
              dataObj[key] ??
              dataObj[`${item.exchange}:${item.symbol}`] ??
              dataObj[item.symbol] ??
              null;
            if (q) {
              next[key] = q;
              const ltp = q?.ltp ?? q?.close ?? null;
              if (ltp != null) {
                histNext[key] = [...(prevSpark[key] ?? []).slice(-(SPARK_MAX - 1)), Number(ltp)];
              }
            }
          });
          return histNext;
        });
        setQuotes((prev) => ({ ...prev, ...next }));
      }
    } catch (err) {
      setFetchError(err instanceof Error ? err.message : "Quote fetch failed");
    }
  }, []);

  useEffect(() => {
    void fetchQuotes();

    function schedule() {
      const delay = isMarketHours() ? 5000 : 60000;
      pollRef.current = setTimeout(() => {
        void fetchQuotes();
        schedule();
      }, delay);
    }

    schedule();
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchQuotes, instrumentsMemo]);

  return { quotes, sparkHistory, fetchError };
}
