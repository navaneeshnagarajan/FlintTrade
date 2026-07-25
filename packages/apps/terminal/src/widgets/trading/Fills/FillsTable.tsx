/**
 * FillsTable — the embeddable canonical fills surface (merge 2.11).
 *
 * One TanStack table over the union of broker tradebook rows and backend
 * auto-journal rows (see ``fillsModel.buildFillRows``), with side filter
 * pills, symbol search, CSV export, a stats footer and per-fill screenshot
 * annotations. The Fills widget wraps this component; the Trade Review tool
 * embeds it directly in its Log tab (optionally date-ranged).
 *
 * Data planes (each shape enters once, via TanStack Query):
 *   - Broker tradebook — ``useTradebook`` (canonical query key; sandbox in
 *     Practice, broker in Live). Disabled when a date range is supplied: the
 *     tradebook is session-only, so a historical view is journal-only.
 *   - Auto-journal fills — ``getTradeJournal`` under the same query keys the
 *     TradeLog widget and Trade Journal tool used, so caches are shared.
 *     Enabled in Live mode only: journalled fills are live-broker records and
 *     must never be unioned into the Practice sandbox's tradebook.
 *   - Screenshot metadata/bytes — ``ftApi.journal`` under the exact query
 *     keys the Trade Journal tool uses (one shared cache).
 *
 * Mode honesty:
 *   - Explore → badged sample fills only; every query disabled.
 *   - Practice → sandbox tradebook only.
 *   - Live → tradebook ∪ journal; without a broker the journal's recorded
 *     fills still render behind a "Broker required" chip (the retired
 *     TradeLog hid real local journal rows behind sample data — a bug, not a
 *     behaviour to preserve).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRightLeft,
  Clock,
  Download,
  Eye,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { cn } from "@/lib/utils";
import { formatNumber } from "@/lib/formatters";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";
import { useTradebook } from "@/hooks/useTradebook";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useModeStore } from "@/stores/modeStore";
import { getTradeJournal } from "@/services/ftApi";
import {
  addJournalScreenshot,
  deleteJournalScreenshot,
  listJournalScreenshots,
  type JournalScreenshot,
  type JournalScreenshotMeta,
} from "@/services/ftApi.journal";
import {
  buildFillRows,
  computeFillStats,
  downloadFillsCsv,
  legacyFillKey,
  SAMPLE_FILLS,
  type FillRow,
  type RawFillSource,
} from "./fillsModel";
import { importLegacyScreenshots, ScreenshotCell } from "./screenshots";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function fmtPnl(pnl: number): string {
  const sign = pnl >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(pnl).toLocaleString("en-IN")}`;
}

const RIGHT_COLS = new Set(["qty", "price", "value", "entryPrice", "exitPrice", "pnl", "fees"]);

// ---------------------------------------------------------------------------
// Side filter pill
// ---------------------------------------------------------------------------

const FILTER_ALL = "ALL";
const FILTER_BUY = "BUY";
const FILTER_SELL = "SELL";
type FilterValue = typeof FILTER_ALL | typeof FILTER_BUY | typeof FILTER_SELL;

interface FilterPillProps {
  value: FilterValue;
  label: string;
  count: number;
  activeFilter: FilterValue;
  onClick: (v: FilterValue) => void;
}

function FilterPill({ value, label, count, activeFilter, onClick }: FilterPillProps) {
  const active = activeFilter === value;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      onClick={() => onClick(value)}
      aria-pressed={active}
      className={cn(
        "h-auto px-2 py-0.5 rounded text-xs font-medium transition-colors",
        active
          ? value === FILTER_BUY
            ? "bg-profit/20 text-profit border border-profit/40"
            : value === FILTER_SELL
              ? "bg-loss/20 text-loss border border-loss/40"
              : "bg-surface-hover text-text-primary border border-border-default"
          : "text-text-muted border border-transparent hover:text-text-secondary hover:border-border-default",
      )}
    >
      {label}
      {count > 0 ? ` (${count})` : ""}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Skeleton rows (ported from the Trade Journal tool's StatCard)
// ---------------------------------------------------------------------------

function SkeletonRows({ count, cols }: { count: number; cols: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <TableRow key={i} className="border-border-subtle">
          {Array.from({ length: cols }).map((_, j) => (
            <TableCell key={j} className="py-1.5">
              <Skeleton className="h-3 w-full bg-surface-elevated" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

// ---------------------------------------------------------------------------
// FillsTable
// ---------------------------------------------------------------------------

export interface FillsTableProps {
  /**
   * Optional inclusive IST date range (``YYYY-MM-DD``) for the journal query.
   * When set, the session tradebook is not joined — historical views are
   * journal-only. Omit both for today's fills (the widget default).
   */
  startDate?: string;
  endDate?: string;
  className?: string;
}

export function FillsTable({ startDate, endDate, className }: FillsTableProps) {
  const track = useTrackBehavior();
  const mode = useModeStore((s) => s.mode);
  const isExplore = mode === "explore";
  const isLive = mode === "live";
  const accountReadsEnabled = useAccountReadsEnabled();
  const queryClient = useQueryClient();

  const ranged = Boolean(startDate && endDate);

  const [sorting, setSorting] = useState<SortingState>([]);
  const [sideFilter, setSideFilter] = useState<FilterValue>(FILTER_ALL);
  const [symbolSearch, setSymbolSearch] = useState("");

  // --- Data plane 1: broker tradebook (session fills) ---
  const tradebookEnabled = accountReadsEnabled && !ranged;
  const tradebookQuery = useTradebook({ enabled: tradebookEnabled });

  // --- Data plane 2: auto-journal fills (live-mode enrichment + history) ---
  const journalQuery = useQuery({
    queryKey: ranged
      ? ["tradeJournal", startDate, endDate, ""]
      : ["tradeJournal", "today"],
    queryFn: () =>
      ranged ? getTradeJournal(startDate, endDate, undefined, 200) : getTradeJournal(),
    enabled: isLive,
    refetchInterval: isLive && !ranged ? 15_000 : false,
  });

  // --- Data plane 3: screenshot metadata (bytes fetched lazily per-id) ---
  const screenshotsQuery = useQuery({
    queryKey: ["journalScreenshots"],
    queryFn: listJournalScreenshots,
    enabled: isLive,
  });

  const screenshotsByKey = useMemo(() => {
    const map: Record<string, JournalScreenshotMeta> = {};
    for (const shot of screenshotsQuery.data ?? []) {
      if (!(shot.trade_key in map)) map[shot.trade_key] = shot;
    }
    return map;
  }, [screenshotsQuery.data]);

  const [viewingScreenshot, setViewingScreenshot] = useState<{
    screenshot: JournalScreenshot;
    symbol: string;
  } | null>(null);

  const attachMutation = useMutation({
    mutationFn: ({ tradeKey, dataUrl }: { tradeKey: string; dataUrl: string }) =>
      addJournalScreenshot(tradeKey, dataUrl),
    onSuccess: (row) => {
      // The POST response already carries the image bytes — seed the new id's
      // data query with them so the fresh thumbnail never refetches, then
      // invalidate ONLY the metadata list (cheap; no image payloads).
      queryClient.setQueryData<JournalScreenshot>(["journalScreenshot", row.id], row);
      void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
    },
    onError: () => {
      alert("Screenshot not saved — backend unreachable.");
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => deleteJournalScreenshot(id),
    onSuccess: (_result, id) => {
      // Drop the deleted image's cached bytes and refresh ONLY the metadata
      // list — surviving thumbnails keep their immutable cached data.
      queryClient.removeQueries({ queryKey: ["journalScreenshot", id] });
      void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
      setViewingScreenshot(null);
    },
    onError: () => {
      alert("Screenshot not removed — backend unreachable.");
    },
  });

  // One-time legacy localStorage import (Live only — journal rows only exist
  // there). Permanently rejected entries are surfaced below the filters —
  // silence would read as the screenshot having vanished.
  const importAttemptedRef = useRef(false);
  const [legacyRejectedCount, setLegacyRejectedCount] = useState(0);
  useEffect(() => {
    if (!isLive || importAttemptedRef.current) return;
    importAttemptedRef.current = true;
    void importLegacyScreenshots().then(({ imported, rejectedCount }) => {
      if (rejectedCount > 0) setLegacyRejectedCount(rejectedCount);
      if (imported) {
        void queryClient.invalidateQueries({ queryKey: ["journalScreenshots"] });
      }
    });
  }, [isLive, queryClient]);

  // --- Row model: one union, newest first ---
  const allRows = useMemo<FillRow[]>(() => {
    if (isExplore) return [...SAMPLE_FILLS];
    return buildFillRows(
      tradebookEnabled ? ((tradebookQuery.data ?? []) as RawFillSource[]) : [],
      isLive ? (journalQuery.data?.trades ?? []) : [],
    );
  }, [isExplore, isLive, tradebookEnabled, tradebookQuery.data, journalQuery.data]);

  const counts = useMemo(
    () => ({
      all: allRows.length,
      buy: allRows.filter((r) => r.side === FILTER_BUY).length,
      sell: allRows.filter((r) => r.side === FILTER_SELL).length,
    }),
    [allRows],
  );

  const filteredRows = useMemo<FillRow[]>(() => {
    let rows = allRows;
    if (sideFilter !== FILTER_ALL) rows = rows.filter((r) => r.side === sideFilter);
    const q = symbolSearch.trim().toLowerCase();
    if (q) rows = rows.filter((r) => r.symbol.toLowerCase().includes(q));
    return rows;
  }, [allRows, sideFilter, symbolSearch]);

  /**
   * Legacy screenshot-key index per filtered row: the running position among
   * journal-backed rows in default (newest-first) order — the closest match
   * to where the Trade Journal tool's filtered list minted those keys.
   */
  const legacyIdxByFilteredIndex = useMemo<number[]>(() => {
    let next = 0;
    return filteredRows.map((r) => (r.tradeKey !== null ? next++ : -1));
  }, [filteredRows]);

  const stats = useMemo(() => computeFillStats(filteredRows), [filteredRows]);

  const handleExport = useCallback(() => {
    track("trade", "fills_export_csv");
    downloadFillsCsv(filteredRows);
  }, [track, filteredRows]);

  const handleRefresh = useCallback(() => {
    if (tradebookEnabled) void tradebookQuery.refetch();
    if (isLive) void journalQuery.refetch();
  }, [tradebookEnabled, isLive, tradebookQuery, journalQuery]);

  // --- Columns ---
  const columns = useMemo<ColumnDef<FillRow>[]>(
    () => [
      {
        accessorKey: "timeSortMs",
        id: "time",
        header: "Time",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-muted whitespace-nowrap">
            {row.original.dateDisplay !== "—" && (
              <span className="text-text-disabled mr-1">{row.original.dateDisplay}</span>
            )}
            {row.original.timeDisplay}
          </span>
        ),
      },
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium truncate max-w-32 inline-block align-bottom" title={row.original.symbol}>
            {row.original.symbol}
          </span>
        ),
      },
      {
        accessorKey: "exchange",
        header: "Exch",
        cell: ({ row }) => (
          <span className="text-text-muted">{row.original.exchange ?? "—"}</span>
        ),
      },
      {
        accessorKey: "side",
        header: "Side",
        cell: ({ row }) => (
          <Badge
            variant={row.original.side === "BUY" ? "default" : "destructive"}
            className={cn(
              "text-xs font-semibold",
              row.original.side === "BUY"
                ? "bg-profit/15 text-profit border border-profit/30"
                : "bg-loss/15 text-loss border border-loss/30",
            )}
          >
            {row.original.side || "—"}
          </Badge>
        ),
      },
      {
        accessorKey: "qty",
        header: "Qty",
        cell: ({ row }) => <span className="font-mono tabular-nums">{row.original.qty}</span>,
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-primary">{INR.format(row.original.price)}</span>
        ),
      },
      {
        accessorKey: "value",
        header: "Value",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{INR.format(row.original.value)}</span>
        ),
      },
      {
        accessorKey: "entryPrice",
        header: "Entry",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-primary">
            {row.original.entryPrice !== null ? formatNumber(row.original.entryPrice, 2) : "—"}
          </span>
        ),
      },
      {
        accessorKey: "exitPrice",
        header: "Exit",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-primary">
            {row.original.exitPrice !== null ? formatNumber(row.original.exitPrice, 2) : "—"}
          </span>
        ),
      },
      {
        accessorKey: "pnl",
        header: "P&L",
        cell: ({ row }) => {
          const { pnl } = row.original;
          // A 0 on an opening leg means "no realised P&L recorded", not
          // breakeven — shown honestly as a dash (the tool's convention).
          if (pnl === null || pnl === 0) return <span className="text-text-muted">—</span>;
          return (
            <span
              className={cn(
                "font-mono tabular-nums font-medium",
                pnl >= 0 ? "text-profit" : "text-loss",
              )}
            >
              {fmtPnl(pnl)}
            </span>
          );
        },
      },
      {
        accessorKey: "fees",
        header: "Fees",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-muted">
            {row.original.fees !== null ? formatNumber(row.original.fees, 2) : "—"}
          </span>
        ),
      },
      {
        accessorKey: "strategy",
        header: "Strategy",
        cell: ({ row }) => (
          <span className="text-text-muted truncate max-w-20 inline-block align-bottom" title={row.original.strategy ?? undefined}>
            {row.original.strategy ?? "—"}
          </span>
        ),
      },
      {
        id: "screenshot",
        header: "Shot",
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          const legacyIdx = legacyIdxByFilteredIndex[row.index] ?? -1;
          const legacyKey = legacyIdx >= 0 ? legacyFillKey(r, legacyIdx) : null;
          const shot =
            r.tradeKey !== null
              ? (screenshotsByKey[r.tradeKey] ??
                (legacyKey !== null ? screenshotsByKey[legacyKey] : undefined))
              : undefined;
          return (
            <ScreenshotCell
              shot={shot}
              attachDisabled={isExplore || r.tradeKey === null}
              disabledReason={
                isExplore
                  ? "Sample data — attaching is disabled in Explore mode"
                  : "Screenshots attach to journalled fills — this fill has no journal record yet"
              }
              onAttach={(dataUrl) => {
                if (r.tradeKey !== null) {
                  attachMutation.mutate({ tradeKey: r.tradeKey, dataUrl });
                }
              }}
              onView={(s) => setViewingScreenshot({ screenshot: s, symbol: r.symbol })}
            />
          );
        },
      },
    ],
    [screenshotsByKey, legacyIdxByFilteredIndex, isExplore, attachMutation],
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // --- Derived UI state ---
  const showBrokerRequired = isLive && !accountReadsEnabled;
  const tradebookErrored = tradebookEnabled && tradebookQuery.isError;
  const journalErrored = isLive && journalQuery.isError;
  const isFetching = tradebookQuery.isFetching || journalQuery.isFetching;
  const isInitialLoading =
    !isExplore &&
    allRows.length === 0 &&
    (tradebookQuery.isLoading || journalQuery.isLoading);
  const lastFetchMs = Math.max(
    tradebookEnabled ? tradebookQuery.dataUpdatedAt : 0,
    isLive ? journalQuery.dataUpdatedAt : 0,
  );
  const lastFetch = lastFetchMs > 0 ? new Date(lastFetchMs) : null;

  const emptyMessage = tradebookErrored
    ? "Fills unavailable — retry above"
    : showBrokerRequired
      ? "Connect a broker to load fills"
      : ranged
        ? "No fills in this period"
        : "No fills today";

  return (
    <div className={cn("h-full flex flex-col overflow-hidden text-xs bg-surface-base", className)}>
      {/* Screenshot viewer dialog */}
      <Dialog
        open={viewingScreenshot !== null}
        onOpenChange={(open) => {
          if (!open) setViewingScreenshot(null);
        }}
      >
        <DialogContent className="max-w-2xl bg-surface-card border-border-default">
          <DialogHeader>
            <DialogTitle className="text-sm font-semibold text-text-primary flex items-center gap-2">
              <Eye size={14} />
              Trade Screenshot
              {viewingScreenshot && (
                <span className="text-text-muted font-mono text-xs font-normal ml-1">
                  {viewingScreenshot.symbol}
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          {viewingScreenshot && (
            <div className="relative">
              <img
                src={viewingScreenshot.screenshot.data_url}
                alt="Trade screenshot"
                className="w-full rounded border border-border-default object-contain max-h-[60vh]"
              />
              <Button
                variant="ghost"
                size="sm"
                disabled={removeMutation.isPending}
                onClick={() => removeMutation.mutate(viewingScreenshot.screenshot.id)}
                className="absolute top-2 right-2 flex items-center gap-1 px-2 py-1 h-auto rounded bg-loss/80 text-white text-xs hover:bg-loss transition-colors"
                aria-label="Remove screenshot"
              >
                <X size={11} />
                Remove
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
            Fills
          </span>
          <span className="text-xxs text-text-secondary font-mono tabular-nums">({counts.all})</span>
          {isExplore && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
            >
              Sample data
            </span>
          )}
          {showBrokerRequired && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live fills"
            >
              Broker required
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {lastFetch && (
            <span className="text-xxs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          {!isExplore && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={handleRefresh}
              disabled={isFetching}
              className="h-auto w-auto p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
              aria-label="Refresh fills"
            >
              <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            className="flex items-center gap-1 h-auto px-2 py-0.5 text-xs bg-surface-hover border-border-default text-text-muted hover:text-text-primary hover:border-accent/40 transition-colors"
            aria-label="Export CSV"
            title="Export filtered rows as CSV"
          >
            <Download size={10} />
            CSV
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div
        className="flex items-center gap-1.5 px-3 py-1 border-b border-border-default shrink-0 flex-wrap"
        aria-label="Fills filters"
      >
        <FilterPill value={FILTER_ALL} label="All" count={counts.all} activeFilter={sideFilter} onClick={setSideFilter} />
        <FilterPill value={FILTER_BUY} label="Buy" count={counts.buy} activeFilter={sideFilter} onClick={setSideFilter} />
        <FilterPill value={FILTER_SELL} label="Sell" count={counts.sell} activeFilter={sideFilter} onClick={setSideFilter} />
        <div className="relative">
          <Search
            size={10}
            className="absolute left-1.5 top-1/2 -translate-y-1/2 text-text-disabled pointer-events-none"
          />
          <Input
            type="text"
            value={symbolSearch}
            onChange={(e) => setSymbolSearch(e.target.value)}
            placeholder="Symbol…"
            className="pl-5 pr-2 py-0.5 text-xs bg-surface-hover border-border-default rounded text-text-primary placeholder:text-text-muted focus-visible:ring-0 focus-visible:border-accent/50 w-28 h-auto"
            aria-label="Search symbol"
          />
        </div>
        <span className="text-xxs text-text-muted font-mono ml-auto">
          {filteredRows.length} fills
        </span>
      </div>

      {/* Error banner — a failed tradebook fetch must never masquerade as "No fills today" */}
      {tradebookErrored && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load fills
            {tradebookQuery.error instanceof Error ? `: ${tradebookQuery.error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void tradebookQuery.refetch()}
            disabled={tradebookQuery.isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {tradebookQuery.isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Journal enrichment failure is non-blocking — fills still render. */}
      {journalErrored && (
        <div className="flex items-center gap-2 px-3 py-1.5 mx-3 mt-2 bg-warning/10 border border-warning/30 rounded-md text-xs text-warning">
          <AlertCircle size={12} className="shrink-0" />
          <span className="flex-1">
            Journal details unavailable — entry/exit, fees and screenshots may be missing
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void journalQuery.refetch()}
            disabled={journalQuery.isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-warning hover:text-warning/80 disabled:opacity-50"
          >
            {journalQuery.isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Legacy-import honesty: permanently rejected screenshots are retained
          in local browser storage but will never reach the backend. */}
      {legacyRejectedCount > 0 && (
        <div className="px-3 pt-1 text-xs text-text-muted shrink-0">
          {legacyRejectedCount} legacy screenshot
          {legacyRejectedCount === 1 ? "" : "s"} could not be migrated — the
          original{legacyRejectedCount === 1 ? " remains" : "s remain"} in
          local browser storage.
        </div>
      )}

      {/* Body */}
      {isInitialLoading ? (
        <div className="flex-1 overflow-auto" role="status" aria-label="Loading fills">
          <Table>
            <TableBody>
              <SkeletonRows count={8} cols={6} />
            </TableBody>
          </Table>
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <ArrowRightLeft size={24} className="text-text-disabled" />
          <span className="text-sm">
            {allRows.length > 0 ? "No fills match the current filters" : emptyMessage}
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className={cn(
                        "text-xxs text-text-muted uppercase tracking-wider select-none px-2 py-1 whitespace-nowrap",
                        header.column.getCanSort() && "cursor-pointer",
                        RIGHT_COLS.has(header.column.id) && "text-right",
                      )}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() === "asc"
                        ? " ↑"
                        : header.column.getIsSorted() === "desc"
                          ? " ↓"
                          : ""}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row, idx) => (
                <TableRow
                  key={row.id}
                  className={cn(
                    "border-t border-border-subtle hover:bg-surface-hover/50",
                    idx % 2 === 1 && "bg-surface-stripe",
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn("px-2 py-1", RIGHT_COLS.has(cell.column.id) && "text-right")}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Stats footer */}
      <div
        className="flex-none flex items-center gap-4 px-3 py-2 bg-surface-card border-t border-border-default flex-wrap"
        aria-label="Fills statistics"
      >
        <div className="flex items-center gap-1.5">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Fills</span>
          <span className="text-xs font-semibold font-mono text-text-primary">{stats.fills}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Realised P&L</span>
          <span
            className={cn(
              "text-xs font-semibold font-mono tabular-nums",
              stats.realisedPnl >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {fmtPnl(stats.realisedPnl)}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Fees</span>
          <span className="text-xs font-semibold font-mono text-text-secondary">
            {stats.totalFees !== null ? `₹${INR.format(stats.totalFees)}` : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
