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
import { z } from "zod";
import { Activity, Database, Download, Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { get, getV1, postV1 } from "@/services/ftApi.helpers";
import { SectionTitle } from "./shared";

// --- Tick capture status -----------------------------------------------------

const tickInstrumentSchema = z.object({
  exchange: z.string().min(1),
  symbol: z.string().min(1),
});

const tickStatusSchema = z.object({
  enabled: z.boolean(),
  running: z.boolean(),
  connected: z.boolean(),
  tick_count: z.number().int().nonnegative(),
  persisted_tick_count: z.number().int().nonnegative().optional(),
  pending_tick_count: z.number().int().nonnegative().optional(),
  dropped_tick_count: z.number().int().nonnegative().optional(),
  watchlist: z.record(z.string(), z.array(tickInstrumentSchema)),
  hint: z.string().optional(),
  last_error: z.string().optional(),
});

type TickInstrument = z.infer<typeof tickInstrumentSchema>;
type TickStatus = z.infer<typeof tickStatusSchema>;

async function fetchTickStatus(): Promise<TickStatus> {
  const payload = await get<unknown>("data/ticks/status");
  const result = tickStatusSchema.safeParse(payload);
  if (!result.success) throw new Error("Tick capture status response was malformed.");
  return result.data;
}

const CAPTURE_WATCHLIST_MODES = ["ltp", "quote", "depth"] as const;

function getCaptureWatchlist(watchlist?: Record<string, TickInstrument[]>): TickInstrument[] {
  const instruments: TickInstrument[] = [];
  const seen = new Set<string>();

  for (const mode of CAPTURE_WATCHLIST_MODES) {
    for (const instrument of watchlist?.[mode] ?? []) {
      const identity = `${instrument.exchange}:${instrument.symbol}`.toUpperCase();
      if (seen.has(identity)) continue;
      seen.add(identity);
      instruments.push(instrument);
    }
  }
  return instruments;
}

// --- Local OHLCV store summary ----------------------------------------------

interface StoreTable {
  rows: number;
  symbols: number;
  first: string | null;
  last: string | null;
}

async function fetchStoreSummary(): Promise<Record<string, StoreTable>> {
  const data = await getV1<{ tables: Record<string, StoreTable> }>(
    "historify/bars/summary",
  );
  return data.tables;
}

// --- Bhavcopy download --------------------------------------------------------

const bhavcopyResultSchema = z.object({
  saved_count: z.number().int().nonnegative(),
  error_count: z.number().int().nonnegative(),
  dest_dir: z.string().min(1),
});

type BhavcopyResult = z.infer<typeof bhavcopyResultSchema>;

async function startBhavcopyDownload(start: string, end: string): Promise<BhavcopyResult> {
  const payload = await postV1<unknown>("historify/bhavcopy/download", { start, end });
  const result = bhavcopyResultSchema.safeParse(payload);
  if (!result.success) throw new Error("Bhavcopy response was malformed.");
  return result.data;
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
  const captureWatchlist = getCaptureWatchlist(tick?.watchlist);
  const persistedTickCount = tick?.persisted_tick_count ?? tick?.tick_count ?? 0;
  const pendingTickCount = tick?.pending_tick_count ?? Math.max(0, (tick?.tick_count ?? 0) - persistedTickCount);
  const droppedTickCount = tick?.dropped_tick_count ?? 0;
  const nonEmptyTables = Object.entries(storeQuery.data ?? {}).filter(([, t]) => t.rows > 0);
  const tickState = tickQuery.isPending
    ? { label: "checking", className: "bg-surface-hover text-text-muted" }
    : tickQuery.isError
      ? { label: "unavailable", className: "bg-red-500/15 text-loss" }
      : !tick?.enabled
        ? { label: "off", className: "bg-surface-hover text-text-muted" }
        : tick.last_error && tick.running && tick.connected
          ? { label: "degraded", className: "bg-red-500/15 text-loss" }
          : tick.running && tick.connected
            ? { label: "recording", className: "bg-green-500/15 text-green-500" }
            : tick.running
              ? {
                  label: tick.last_error ? "reconnecting" : "connecting",
                  className: "bg-amber-500/15 text-amber-500",
                }
              : tick.last_error
                ? { label: "error", className: "bg-red-500/15 text-loss" }
                : { label: "stopped", className: "bg-amber-500/15 text-amber-500" };

  return (
    <div className="space-y-4">
      <SectionTitle>Local Data</SectionTitle>

      {/* Tick capture status */}
      <div className="p-3 rounded bg-surface-card border border-border-default space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <Activity size={13} /> Tick capture
          <span className={`text-[10px] px-1.5 py-0.5 rounded ${tickState.className}`}>{tickState.label}</span>
        </div>
        {tickQuery.isPending ? (
          <div className="text-xs text-text-muted flex items-center gap-1">
            <Loader2 size={11} className="animate-spin" /> Checking tick capture status…
          </div>
        ) : tickQuery.isError ? (
          <div className="text-xs text-loss">Tick capture status unavailable.</div>
        ) : tick?.enabled ? (
          <div className="text-xs text-text-muted">
            {persistedTickCount.toLocaleString("en-IN")} persisted ·{" "}
            {tick.tick_count.toLocaleString("en-IN")} received ·{" "}
            {pendingTickCount.toLocaleString("en-IN")} pending ·{" "}
            {droppedTickCount.toLocaleString("en-IN")} dropped ·{" "}
            {captureWatchlist.map((i) => i.symbol).join(", ") || "no symbols"}
          </div>
        ) : (
          <div className="text-xs text-text-muted">
            {tick?.hint ??
              "Set FLINTTRADE_TICK_CAPTURE=1 and restart the backend to record live ticks to DuckDB."}
          </div>
        )}
        {!tickQuery.isPending && !tickQuery.isError && tick?.last_error && (
          <div className="text-xs text-loss break-words">{tick.last_error}</div>
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
        ) : storeQuery.isError ? (
          <div role="alert" className="text-xs text-loss flex items-center gap-1">
            <AlertTriangle size={12} className="shrink-0" />
            {storeQuery.error instanceof Error
              ? storeQuery.error.message
              : "Local OHLCV store unavailable"}
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
