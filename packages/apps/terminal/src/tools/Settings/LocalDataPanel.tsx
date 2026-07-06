/**
 * LocalDataPanel — local data-store status + full-market downloads.
 *
 * Three cards inside Settings → Data:
 *   1. Tick capture — recorder status (enabled/running/count) + capture
 *      watchlist from /api/v1/data/ticks/status. Capture itself is opt-in at
 *      boot (FLINTTRADE_TICK_CAPTURE); this surface makes its state visible.
 *   2. Local OHLCV store — per-interval row/symbol counts from
 *      /v1/historify/bars/summary (what the downloader has actually saved).
 *   3. Bhavcopy download — fetch NSE full-market EOD archives (equity/F&O/
 *      index/full) for a date range into local storage.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, Database, Download, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionTitle } from "./shared";

const FT_BASE = "/ft-api";

// --- Tick capture status -----------------------------------------------------

interface TickStatus {
  enabled: boolean;
  running: boolean;
  tick_count: number;
  watchlist: Record<string, Array<{ exchange: string; symbol: string }>>;
  hint?: string;
}

async function fetchTickStatus(): Promise<TickStatus> {
  const res = await fetch(`${FT_BASE}/api/v1/data/ticks/status`);
  if (!res.ok) throw new Error("Tick status unavailable");
  const json = (await res.json()) as { data?: TickStatus };
  if (!json.data) throw new Error("Tick status malformed");
  return json.data;
}

// --- Local OHLCV store summary ----------------------------------------------

interface StoreTable {
  rows: number;
  symbols: number;
  first: string | null;
  last: string | null;
}

async function fetchStoreSummary(): Promise<Record<string, StoreTable>> {
  const res = await fetch(`${FT_BASE}/v1/historify/bars/summary`);
  if (!res.ok) throw new Error("Store summary unavailable");
  const json = (await res.json()) as { data?: { tables: Record<string, StoreTable> } };
  if (!json.data) throw new Error("Store summary malformed");
  return json.data.tables;
}

// --- Bhavcopy download --------------------------------------------------------

interface BhavcopyResult {
  saved_count: number;
  error_count: number;
  dest_dir: string;
}

async function startBhavcopyDownload(start: string, end: string): Promise<BhavcopyResult> {
  const res = await fetch(`${FT_BASE}/v1/historify/bhavcopy/download`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, end }),
  });
  const json = (await res.json().catch(() => null)) as
    | { data?: BhavcopyResult; message?: string }
    | null;
  if (!res.ok || !json?.data) {
    throw new Error(json?.message ?? "Bhavcopy download failed");
  }
  return json.data;
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

// --- Panel --------------------------------------------------------------------

export function LocalDataPanel() {
  const [start, setStart] = useState(() => isoDaysAgo(5));
  const [end, setEnd] = useState(() => isoDaysAgo(0));

  const tickQuery = useQuery({
    queryKey: ["tick-capture-status"],
    queryFn: fetchTickStatus,
    refetchInterval: 30_000,
    retry: false,
  });

  const storeQuery = useQuery({
    queryKey: ["local-store-summary"],
    queryFn: fetchStoreSummary,
    staleTime: 60_000,
    retry: false,
  });

  const bhavcopy = useMutation({ mutationFn: () => startBhavcopyDownload(start, end) });

  const tick = tickQuery.data;
  const quoteWatchlist = tick?.watchlist?.quote ?? [];
  const nonEmptyTables = Object.entries(storeQuery.data ?? {}).filter(([, t]) => t.rows > 0);

  return (
    <div className="space-y-4">
      <SectionTitle>Local Data</SectionTitle>

      {/* Tick capture status */}
      <div className="p-3 rounded bg-surface-card border border-border-default space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Activity size={13} /> Tick capture
          {tick?.running ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-500">recording</span>
          ) : tick?.enabled ? (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-500">enabled, not running</span>
          ) : (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-hover text-text-muted">off</span>
          )}
        </div>
        {tick?.enabled ? (
          <div className="text-xs text-text-muted">
            {tick.tick_count.toLocaleString("en-IN")} ticks this session ·{" "}
            {quoteWatchlist.map((i) => i.symbol).join(", ") || "no symbols"}
          </div>
        ) : (
          <div className="text-xs text-text-muted">
            {tick?.hint ??
              "Set FLINTTRADE_TICK_CAPTURE=1 and restart the backend to record live ticks to DuckDB."}
          </div>
        )}
      </div>

      {/* Local OHLCV store summary */}
      <div className="p-3 rounded bg-surface-card border border-border-default space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Database size={13} /> Local OHLCV store
        </div>
        {storeQuery.isLoading ? (
          <div className="text-xs text-text-muted flex items-center gap-1">
            <Loader2 size={11} className="animate-spin" /> Loading…
          </div>
        ) : nonEmptyTables.length === 0 ? (
          <div className="text-xs text-text-muted">
            Nothing downloaded yet — use the download button above or the bhavcopy fetch below.
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted">
                <th className="text-left font-medium py-0.5">Table</th>
                <th className="text-right font-medium py-0.5">Rows</th>
                <th className="text-right font-medium py-0.5">Symbols</th>
                <th className="text-right font-medium py-0.5">Last bar</th>
              </tr>
            </thead>
            <tbody>
              {nonEmptyTables.map(([name, t]) => (
                <tr key={name} className="border-t border-border-default/50">
                  <td className="py-0.5 font-mono">{name}</td>
                  <td className="py-0.5 text-right font-mono tabular-nums">{t.rows.toLocaleString("en-IN")}</td>
                  <td className="py-0.5 text-right font-mono tabular-nums">{t.symbols}</td>
                  <td className="py-0.5 text-right font-mono tabular-nums">{t.last ? t.last.slice(0, 10) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Bhavcopy download */}
      <div className="p-3 rounded bg-surface-card border border-border-default space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Download size={13} /> NSE bhavcopy archive
        </div>
        <p className="text-xs text-text-muted">
          Downloads the full-market EOD bhavcopies (equity, F&amp;O, index, full incl. delivery)
          for the date range into local storage. Weekends are skipped; holidays report per-day
          errors. Max 31 days per fetch.
        </p>
        <div className="flex items-center gap-2">
          <Input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-label="Bhavcopy start date"
            className="h-7 w-36 text-xs"
          />
          <span className="text-xs text-text-muted">to</span>
          <Input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-label="Bhavcopy end date"
            className="h-7 w-36 text-xs"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={bhavcopy.isPending}
            onClick={() => bhavcopy.mutate()}
            className="h-7 text-xs"
          >
            {bhavcopy.isPending ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Download size={12} />
            )}
            Fetch bhavcopies
          </Button>
        </div>
        {bhavcopy.isSuccess && (
          <div className="text-xs text-green-500 flex items-center gap-1">
            <CheckCircle2 size={12} />
            Saved {bhavcopy.data.saved_count} file(s)
            {bhavcopy.data.error_count > 0 && (
              <span className="text-amber-500">· {bhavcopy.data.error_count} day-error(s) (holidays?)</span>
            )}
            <span className="text-text-muted">→ {bhavcopy.data.dest_dir}</span>
          </div>
        )}
        {bhavcopy.isError && (
          <div className="text-xs text-loss flex items-center gap-1">
            <AlertTriangle size={12} /> {(bhavcopy.error as Error).message}
          </div>
        )}
      </div>
    </div>
  );
}
