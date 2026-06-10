/**
 * WatchlistManagerPanel — manage the historify download watchlist.
 *
 * The bulk-download manager only downloads ENABLED watchlist symbols, but the
 * watchlist had no terminal surface at all — a fresh operator's "Download 30d"
 * hit an empty list (HTTP 400) with no way to fix it from the UI. This panel
 * closes the loop: list / add / remove symbols, plus an Excel import
 * (symbol, exchange, optional interval columns) feeding the same watchlist.
 *
 *   GET    /ft-api/v1/historify/watchlist
 *   POST   /ft-api/v1/historify/watchlist
 *   DELETE /ft-api/v1/historify/watchlist
 *   POST   /api/v1/integration/excel/import/upload  (via uploadExcel)
 */

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListPlus, Trash2, Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { uploadExcel } from "@/services/ftApi";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { SectionTitle } from "./shared";

const BASE = "/ft-api/v1/historify";

interface WatchlistItem {
  symbol: string;
  exchange: string;
  interval: string;
  enabled?: boolean;
}

async function fetchWatchlist(): Promise<WatchlistItem[]> {
  const res = await fetch(`${BASE}/watchlist`);
  if (!res.ok) throw new Error(`Watchlist fetch failed (${res.status})`);
  const json = (await res.json()) as { data: WatchlistItem[] };
  return json.data ?? [];
}

async function addItem(item: { symbol: string; exchange: string; interval: string }): Promise<void> {
  const res = await fetch(`${BASE}/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(item),
  });
  if (!res.ok) {
    const json = (await res.json().catch(() => null)) as { message?: string } | null;
    throw new Error(json?.message ?? `Remove failed (${res.status})`);
  }
}

/**
 * Map imported Excel rows onto watchlist entries. Header matching is
 * case-insensitive; rows without a symbol AND exchange are skipped (counted
 * so the operator sees exactly what was ignored — nothing silent).
 */
export function rowsToWatchlistEntries(rows: Record<string, unknown>[]): {
  entries: { symbol: string; exchange: string; interval: string }[];
  skipped: number;
} {
  const entries: { symbol: string; exchange: string; interval: string }[] = [];
  let skipped = 0;
  for (const row of rows) {
    const lookup: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(row)) lookup[key.toLowerCase().trim()] = value;
    const symbol = String(lookup["symbol"] ?? "").trim().toUpperCase();
    const exchange = String(lookup["exchange"] ?? "").trim().toUpperCase();
    const interval = String(lookup["interval"] ?? "1d").trim() || "1d";
    if (!symbol || !exchange) {
      skipped += 1;
      continue;
    }
    entries.push({ symbol, exchange, interval });
  }
  return { entries, skipped };
}

export function WatchlistManagerPanel() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState("NSE");
  const [interval, setInterval] = useState("1d");
  const [importError, setImportError] = useState<string | null>(null);

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

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      const rows = await uploadExcel(file); // backend reads the FIRST sheet
      const { entries, skipped } = rowsToWatchlistEntries(rows);
      if (entries.length === 0) {
        throw new Error(
          "No usable rows — the sheet needs 'symbol' and 'exchange' columns.",
        );
      }
      // Add each entry independently: one bad row must not report the whole
      // import as failed after earlier rows already landed.
      let added = 0;
      const failures: string[] = [];
      for (const entry of entries) {
        try {
          await addItem(entry);
          added += 1;
        } catch (err) {
          failures.push(`${entry.symbol} (${err instanceof Error ? err.message : "failed"})`);
        }
      }
      return { added, skipped, failures };
    },
    onSuccess: ({ added, skipped, failures }) => {
      const parts = [
        `Added ${added} symbol${added === 1 ? "" : "s"} to the download watchlist`,
      ];
      if (skipped > 0) parts.push(`${skipped} row${skipped === 1 ? "" : "s"} skipped (missing symbol/exchange)`);
      if (failures.length > 0) parts.push(`${failures.length} failed: ${failures.join(", ")}`);
      const body = parts.join("; ") + ".";

      setImportError(failures.length > 0 ? body : null);
      emitNotification({
        category: failures.length > 0 ? "alert" : "system",
        title: failures.length > 0 ? "Watchlist import partly failed" : "Watchlist import complete",
        body,
      });
    },
    onError: (err: Error) => {
      setImportError(err.message);
      emitNotification({
        category: "alert",
        title: "Watchlist import failed",
        body: err.message,
      });
    },
    // Refresh regardless — a partial import HAS changed the list.
    onSettled: refresh,
  });

  const items = watchlistQuery.data ?? [];

  return (
    <div className="space-y-3">
      <SectionTitle>Download Watchlist</SectionTitle>

      <div className="p-3 rounded-lg bg-surface-card border border-border-default space-y-3">
        <p className="text-xs text-text-muted leading-snug">
          Symbols the historical download manager fetches. Add them here, or import a
          spreadsheet with <code className="font-mono">symbol</code>,{" "}
          <code className="font-mono">exchange</code> and optional{" "}
          <code className="font-mono">interval</code> columns.
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
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={importMutation.isPending}
            className="gap-1.5"
          >
            {importMutation.isPending ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Upload size={13} />
            )}
            Import from Excel
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            className="sr-only"
            aria-label="Import watchlist from Excel"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) importMutation.mutate(file);
              e.target.value = "";
            }}
          />
        </form>

        {addMutation.isError && (
          <p role="alert" className="text-xs text-loss">
            {addMutation.error instanceof Error ? addMutation.error.message : "Failed to add symbol"}
          </p>
        )}
        {importError && (
          <p role="alert" className="text-xs text-loss">
            {importError}
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
