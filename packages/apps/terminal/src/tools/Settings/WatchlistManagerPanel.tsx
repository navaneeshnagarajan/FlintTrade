/**
 * WatchlistManagerPanel — manage the historify download watchlist.
 *
 * The bulk-download manager only downloads ENABLED watchlist symbols, but the
 * watchlist had no terminal surface at all — a fresh operator's "Download 30d"
 * hit an empty list (HTTP 400) with no way to fix it from the UI. This panel
 * closes the loop: list / add / remove symbols feeding the same watchlist.
 *
 *   GET    /ft-api/v1/historify/watchlist
 *   POST   /ft-api/v1/historify/watchlist
 *   DELETE /ft-api/v1/historify/watchlist
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListPlus, Trash2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { buildHeaders } from "@/services/ftApi.helpers";
import { SectionTitle } from "./shared";

const BASE = "/ft-api/v1/historify";

interface WatchlistItem {
  symbol: string;
  exchange: string;
  interval: string;
  enabled?: boolean;
}

async function fetchWatchlist(): Promise<WatchlistItem[]> {
  const res = await fetch(`${BASE}/watchlist`, { headers: buildHeaders(false) });
  if (!res.ok) throw new Error(`Watchlist fetch failed (${res.status})`);
  const json = (await res.json()) as { data: WatchlistItem[] };
  return json.data ?? [];
}

async function addItem(item: { symbol: string; exchange: string; interval: string }): Promise<void> {
  const res = await fetch(`${BASE}/watchlist`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(item),
  });
  if (!res.ok) {
    const json = (await res.json().catch(() => null)) as { message?: string } | null;
    throw new Error(json?.message ?? `Add failed (${res.status})`);
  }
}

async function removeItem(item: { symbol: string; exchange: string }): Promise<void> {
  const res = await fetch(`${BASE}/watchlist`, {
    method: "DELETE",
    headers: buildHeaders(true),
    body: JSON.stringify(item),
  });
  if (!res.ok) {
    const json = (await res.json().catch(() => null)) as { message?: string } | null;
    throw new Error(json?.message ?? `Remove failed (${res.status})`);
  }
}

export function WatchlistManagerPanel() {
  const queryClient = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [interval, setInterval] = useState("1d");

  const watchlistQuery = useQuery({
    queryKey: ["historify", "watchlist"],
    queryFn: fetchWatchlist,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["historify", "watchlist"] });

  const addMutation = useMutation({
    mutationFn: addItem,
    onSuccess: () => {
      setSymbol("");
      refresh();
    },
  });

  const removeMutation = useMutation({
    mutationFn: removeItem,
    onSuccess: refresh,
  });

  const items = watchlistQuery.data ?? [];

  return (
    <div className="space-y-3">
      <SectionTitle>Download Watchlist</SectionTitle>

      <div className="p-3 rounded-lg bg-surface-card border border-border-default space-y-3">
        <p className="text-xs text-text-muted leading-snug">
          Symbols the historical download manager fetches. Add and remove them here.
        </p>

        {/* Add form */}
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const s = symbol.trim().toUpperCase();
            const x = exchange.trim().toUpperCase();
            if (!s || !x) return;
            addMutation.mutate({ symbol: s, exchange: x, interval: interval.trim() || "1d" });
          }}
        >
          <Input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol (e.g. RELIANCE)"
            aria-label="Watchlist symbol"
            className="h-7 w-40 text-xs"
          />
          <Input
            value={exchange}
            onChange={(e) => setExchange(e.target.value)}
            placeholder="Exchange"
            aria-label="Watchlist exchange"
            className="h-7 w-24 text-xs"
          />
          <Input
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
            placeholder="Interval"
            aria-label="Watchlist interval"
            className="h-7 w-20 text-xs"
          />
          <Button
            type="submit"
            size="sm"
            variant="outline"
            disabled={addMutation.isPending || !symbol.trim()}
            className="gap-1.5"
          >
            {addMutation.isPending ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <ListPlus size={13} />
            )}
            Add
          </Button>

        </form>

        {addMutation.isError && (
          <p role="alert" className="text-xs text-loss">
            {addMutation.error instanceof Error ? addMutation.error.message : "Failed to add symbol"}
          </p>
        )}
        {/* Watchlist table */}
        {watchlistQuery.isLoading ? (
          <p className="text-xs text-text-muted">Loading watchlist…</p>
        ) : watchlistQuery.isError ? (
          <p role="alert" className="text-xs text-loss">
            Could not load the watchlist — is the FlintTrade backend running?
          </p>
        ) : items.length === 0 ? (
          <p className="text-xs text-text-muted">
            No symbols yet — the download manager has nothing to fetch until you add some.
          </p>
        ) : (
          <ul className="divide-y divide-border-subtle" aria-label="Download watchlist symbols">
            {items.map((item) => (
              <li
                key={`${item.symbol}:${item.exchange}`}
                className="flex items-center justify-between gap-2 py-1.5"
              >
                <span className="text-xs font-mono text-text-primary">
                  {item.symbol}
                  <span className="text-text-muted"> · {item.exchange} · {item.interval}</span>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => removeMutation.mutate({ symbol: item.symbol, exchange: item.exchange })}
                  disabled={removeMutation.isPending}
                  aria-label={`Remove ${item.symbol} (${item.exchange}) from the watchlist`}
                  className="h-6 w-6 p-0 text-text-muted hover:text-loss"
                >
                  <Trash2 size={12} />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
