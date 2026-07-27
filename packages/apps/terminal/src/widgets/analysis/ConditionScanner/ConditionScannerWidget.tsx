/**
 * ConditionScannerWidget — the canonical market scanner over /ft-api/v1/scanner/*.
 *
 * Runs the backend's prebuilt condition scans (RSI oversold/overbought, volume
 * breakout, pre-market movers, 52-week breakouts, …) across a symbol universe
 * and lists the matches with their matched conditions and a composite score.
 *
 * MERGE (2.17): absorbed the retired `scanner` widget ("Pre-Market Scanner").
 * That widget called the SAME `runPrebuiltScan` client against the SAME
 * `POST /v1/scanner/run`, rendered the same `ScannerResultRow` and derived the
 * same Live/Sample badge — it simply hard-coded two of the backend's eight
 * prebuilt keys (`pre_market_movers`, `volume_breakout`) into a tab enum while
 * this widget fetches the whole catalogue from `GET /v1/scanner/prebuilt`.
 * Choosing "Pre-Market Movers" here has always produced byte-identical results
 * to its Gap tab. What came across from it:
 *   - sortable TanStack result tables (this widget had no sorting at all);
 *   - the "Add to watchlist" row action, which writes through the Watchlist's
 *     own `addSymbolToWatchlist` helper (it used to write the legacy key and
 *     silently no-op on migrated installs while reporting success);
 *   - its per-tab provenance banners, kept where they say more than the badge:
 *     the sample banner names the remedy ("connect a broker read account"),
 *     which the badge only carries in a tooltip.
 *
 * ITS TWO NON-SCANNER TABS.
 *   - OI Change is NOT re-rendered here. It read `/v1/oi/unusual`, which is the
 *     very surface the retired OI Signals widget read and which now lives in
 *     OI Analytics (`oichart`, view "signals"). A third rendering of one
 *     endpoint is exactly the duplication this merge exists to remove, so the
 *     tab became a handoff that opens that widget on its signals view.
 *   - Sectors IS kept, verbatim, as the "sectors" view. It derives live
 *     per-sector movers from `useSectorMovers` and belongs with the
 *     market/sector family — but that merge has not happened yet, and a live
 *     surface must not be deleted for being out of family. THIS IS A TEMPORARY
 *     HOME: when Market Overview is merged, move this view (and the
 *     `useSectorMovers` sample module still parked under the retired scanner
 *     folder) there and drop it from this widget.
 *
 * PANEL PARAMS. `params.scan` preselects a scan by its BACKEND KEY and runs it
 * once on mount, so a saved panel reopens on the scan it was showing; that is
 * also how the retired `scanner` id restores its Gap tab
 * (`{ view: "scans", scan: "pre_market_movers" }`). `params.view` picks
 * "scans" (default) or "sectors". Both are written back through
 * `api.updateParameters` as the operator changes them.
 *
 * Honesty: the run response itself carries ``is_sample_data`` — the backend
 * scans live broker OHLCV when a broker is connected, deterministic synthetic
 * bars otherwise — so the Live/Sample badge reflects what the backend actually
 * scanned, not a connection guess. A failed run drops the badge, the banner
 * and the rows together: stale matches must never sit under a Live claim.
 */

import { useState, useMemo, useEffect, useCallback, useRef, memo } from "react";
import {
  Radar, Loader2, Play, RefreshCw, TrendingUp, TrendingDown, Plus, ArrowUpRight,
} from "lucide-react";
import type { WidgetProps } from "@/types/widgets";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { addSymbolToWatchlist } from "@/widgets/utility/Watchlist/types";
import { useSectorMovers, type UseSectorMoversResult } from "@/hooks/useSectorMovers";
import {
  getPrebuiltScans,
  runPrebuiltScan,
  type ScannerResultRow,
  type ScannerRunResponse,
} from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Panel params + views
// ---------------------------------------------------------------------------

type ScannerView = "scans" | "sectors";

interface ConditionScannerPanelParams {
  /** Initial view — "scans" (default) or "sectors". */
  view?: string;
  /** Backend prebuilt-scan key to preselect and run on mount. */
  scan?: string;
}

/** Resolves the workspace `params.view` panel parameter, defaulting to scans. */
function resolveView(view: string | undefined): ScannerView {
  return view === "sectors" ? "sectors" : "scans";
}

/**
 * One sector-mover row. Derived from the hook's own result type rather than
 * imported from the retired scanner folder, so the sample module can move with
 * the Market Overview merge without touching this widget.
 */
type SectorMoverRow = UseSectorMoversResult["data"][number];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

function fmtPrice(v: number): string {
  return INR.format(v);
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

// ---------------------------------------------------------------------------
// Sortable table (absorbed from the retired scanner)
// ---------------------------------------------------------------------------

interface SortableTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  label: string;
}

function SortableTable<T>({ data, columns, label }: SortableTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Table aria-label={label}>
      <TableHeader>
        {table.getHeaderGroups().map((hg) => (
          <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
            {hg.headers.map((header) => {
              const sorted = header.column.getIsSorted();
              return (
                <TableHead
                  key={header.id}
                  className="h-7 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none whitespace-nowrap"
                  onClick={header.column.getToggleSortingHandler()}
                  aria-sort={
                    sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none"
                  }
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                  {sorted === "asc" && " ↑"}
                  {sorted === "desc" && " ↓"}
                </TableHead>
              );
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow
            key={row.id}
            className="border-border-subtle hover:bg-surface-hover transition-colors"
          >
            {row.getVisibleCells().map((cell) => (
              <TableCell key={cell.id} className="py-1.5 text-xs">
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

// ---------------------------------------------------------------------------
// Add to Watchlist (absorbed — keeps the write-through fix)
// ---------------------------------------------------------------------------

function AddToWatchlistBtn({ symbol, exchange }: { symbol: string; exchange: string }) {
  const [added, setAdded] = useState(false);
  const [failed, setFailed] = useState(false);

  const handleAdd = useCallback(() => {
    // Writes through the Watchlist's own helper. This used to write straight
    // to the LEGACY localStorage key, which the Watchlist only reads when the
    // canonical multi-tab key is absent — so on any already-migrated install
    // the symbol silently never appeared, while the button still reported
    // success.
    const ok = addSymbolToWatchlist({ symbol, exchange });
    setAdded(ok);
    setFailed(!ok);
  }, [symbol, exchange]);

  if (failed) {
    return (
      <Badge variant="outline" className="text-xxs h-5 text-loss border-loss/30">
        Not saved
      </Badge>
    );
  }

  if (added) {
    return (
      <Badge variant="outline" className="text-xxs h-5 text-profit border-profit/30">
        Added
      </Badge>
    );
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleAdd}
            className="h-5 w-5 p-0 text-text-muted hover:text-accent"
            aria-label={`Add ${symbol} to watchlist`}
          >
            <Plus className="size-3" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left" className="text-xs">
          Add to Watchlist
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

function scanColumns(): ColumnDef<ScannerResultRow, unknown>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          {row.original.change_pct >= 0 ? (
            <TrendingUp className="size-3 text-profit shrink-0" aria-hidden="true" />
          ) : (
            <TrendingDown className="size-3 text-loss shrink-0" aria-hidden="true" />
          )}
          <div>
            <div className="text-xs font-semibold text-text-primary font-mono">
              {row.original.symbol}
            </div>
            <div className="text-xxs text-text-muted">{row.original.exchange}</div>
          </div>
        </div>
      ),
    },
    {
      accessorKey: "ltp",
      header: () => <span className="block text-right">LTP</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
          {fmtPrice(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "change_pct",
      header: () => <span className="block text-right">Chg %</span>,
      cell: ({ row }) => {
        const v = row.original.change_pct;
        return (
          <div
            className={cn(
              "text-right font-mono tabular-nums text-xs font-semibold",
              v >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {fmtPct(v)}
          </div>
        );
      },
    },
    {
      accessorKey: "score",
      header: () => <span className="block text-right">Score</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toFixed(2)}
        </div>
      ),
    },
    {
      accessorKey: "matched_conditions",
      header: "Matched",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-1">
          {row.original.matched_conditions.map((label) => (
            <Badge
              key={label}
              variant="outline"
              className="text-xxs h-4 px-1 text-text-secondary border-border-default"
            >
              {label}
            </Badge>
          ))}
        </div>
      ),
      enableSorting: false,
    },
    {
      id: "actions",
      header: "",
      cell: ({ row }) => (
        <div className="flex justify-end">
          <AddToWatchlistBtn symbol={row.original.symbol} exchange={row.original.exchange} />
        </div>
      ),
      enableSorting: false,
    },
  ];
}

function sectorColumns(): ColumnDef<SectorMoverRow, unknown>[] {
  return [
    {
      accessorKey: "sector",
      header: "Sector",
      cell: ({ row }) => (
        <div className="text-xs font-semibold text-text-primary">{row.original.sector}</div>
      ),
    },
    {
      accessorKey: "avgChange",
      header: () => <span className="block text-right">Avg Change</span>,
      cell: ({ row }) => {
        const v = row.original.avgChange;
        return (
          <div
            className={cn(
              "text-right font-mono tabular-nums text-xs font-semibold",
              v >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {fmtPct(v)}
          </div>
        );
      },
    },
    {
      accessorKey: "advancers",
      header: () => <span className="block text-center">A/D</span>,
      cell: ({ row }) => (
        <div className="text-center text-xs font-mono tabular-nums">
          <span className="text-profit">{row.original.advancers}</span>
          <span className="text-text-muted">/</span>
          <span className="text-loss">{row.original.decliners}</span>
        </div>
      ),
    },
    {
      accessorKey: "topGainer",
      header: "Top Gainer",
      cell: ({ row }) => (
        <div className="text-xs font-mono text-profit">{row.original.topGainer}</div>
      ),
    },
    {
      accessorKey: "topLoser",
      header: "Top Loser",
      cell: ({ row }) => (
        <div className="text-xs font-mono text-loss">{row.original.topLoser}</div>
      ),
    },
    {
      accessorKey: "signal",
      header: "Signal",
      cell: ({ row }) => {
        const s = row.original.signal;
        return (
          <Badge
            variant="outline"
            className={cn(
              "text-xxs h-5 font-medium",
              s === "strong" && "text-profit border-profit/30 bg-profit/5",
              s === "moderate" && "text-warning border-warning/30 bg-warning/5",
              s === "weak" && "text-text-muted border-border-default",
              s === "bearish" && "text-loss border-loss/30 bg-loss/5",
            )}
          >
            {s}
          </Badge>
        );
      },
    },
  ];
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function ConditionScannerWidget(props: WidgetProps) {
  const panelParams = props.params as ConditionScannerPanelParams | undefined;
  const initialScan = typeof panelParams?.scan === "string" ? panelParams.scan : "";

  const [view, setView] = useState<ScannerView>(() => resolveView(panelParams?.view));
  const [scanKey, setScanKey] = useState<string>(initialScan);

  const scanCols = useMemo(() => scanColumns(), []);
  const sectorCols = useMemo(() => sectorColumns(), []);

  const prebuiltQuery = useQuery({
    queryKey: ["scannerPrebuilt"],
    queryFn: getPrebuiltScans,
  });
  const scans = prebuiltQuery.data?.scans ?? [];

  const runMutation = useMutation<ScannerRunResponse, Error, string>({
    mutationFn: runPrebuiltScan,
  });
  const runScan = runMutation.mutate;

  // A mutation keeps the previous success payload while it errors, so gate the
  // rows, the badge and the banner on the error state — the retired widget's
  // hardest-won honesty invariant was that a failed re-run must never leave a
  // green Live claim above frozen matches.
  const run = runMutation.isError ? undefined : runMutation.data;

  // A saved panel (and the retired `scanner` id) carries the scan it was
  // showing; run it once on mount so the panel reopens on real rows rather
  // than on the "press Run" hint.
  const autoRanRef = useRef(false);
  useEffect(() => {
    if (autoRanRef.current || !initialScan) return;
    autoRanRef.current = true;
    runScan(initialScan);
  }, [initialScan, runScan]);

  // Sector movers derive from live NIFTY 50 multi-quotes outside Explore;
  // `isLive` is true only when real quote data actually backs the rows.
  const sectorMovers = useSectorMovers();

  const selectedScan = scans.find((s) => s.key === scanKey);

  const handleScanChange = useCallback((next: string) => {
    setScanKey(next);
    props.api.updateParameters({ scan: next });
  }, [panelParams, props.api]);

  const handleViewChange = useCallback((next: ScannerView) => {
    setView((current) => (current === next ? current : next));
    props.api.updateParameters({ view: next });
  }, [panelParams, props.api]);

  const handleRun = useCallback(() => {
    if (scanKey) runScan(scanKey);
  }, [runScan, scanKey]);

  // The retired widget's OI Change tab read /v1/oi/unusual — the same endpoint
  // OI Analytics' signals view reads. Hand off instead of rendering it a third
  // time.
  const openOISignals = useCallback(() => {
    window.dispatchEvent(
      new CustomEvent("flinttrade:addWidget", {
        detail: {
          widgetId: "oichart",
          title: "OI Analytics",
          props: { view: "signals" },
        },
      }),
    );
  }, []);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Radar size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Condition Scanner</span>
        {view === "scans" && run && (
          // Fails closed: only an explicit `false` earns the affirmative "Live" claim.
          run.is_sample_data !== false ? (
            <span
              className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
              role="status"
              aria-label="Scan ran on sample data; connect a broker to scan live prices"
              title="The backend scanned deterministic sample bars — connect a broker to scan live OHLCV."
            >
              Sample data
            </span>
          ) : (
            <span
              className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
              role="status"
              aria-label="Scan ran on live broker data"
              title="Live — the backend scanned real OHLCV from the connected broker."
            >
              Live
            </span>
          )
        )}
        <div className="flex-1" />
        {view === "scans" ? (
          <>
            <Select value={scanKey} onValueChange={handleScanChange}>
              <SelectTrigger
                className="h-7 w-48 text-xs bg-surface-hover border-border-default text-text-primary"
                aria-label="Prebuilt scan"
              >
                <SelectValue placeholder={prebuiltQuery.isLoading ? "Loading scans…" : "Choose a scan"} />
              </SelectTrigger>
              <SelectContent>
                {scans.map((s) => (
                  <SelectItem key={s.key} value={s.key} className="text-xs">
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              size="sm"
              onClick={handleRun}
              disabled={!scanKey || runMutation.isPending}
              className="h-7 px-3 text-xs"
            >
              {runMutation.isPending
                ? <Loader2 size={12} className="animate-spin mr-1" aria-hidden="true" />
                : <Play size={11} className="mr-1" aria-hidden="true" />}
              Run
            </Button>
          </>
        ) : sectorMovers.isLive ? (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-accent"
            onClick={() => sectorMovers.refetch()}
            aria-label="Refresh sector movers"
          >
            <RefreshCw className="size-3" aria-hidden="true" />
          </Button>
        ) : null}
      </div>

      {/* View bar — the OI entry is a handoff, not a tab: unusual OI has a
          single home in OI Analytics. */}
      <nav
        aria-label="Scanner views"
        className="flex-none flex items-end gap-0 px-2 border-b border-border-default bg-surface-card"
      >
        <button
          type="button"
          onClick={() => handleViewChange("scans")}
          aria-current={view === "scans" ? "true" : undefined}
          className={cn(
            "flex items-center gap-1 px-2.5 py-1.5 text-xxs font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
            view === "scans"
              ? "text-accent border-accent"
              : "text-text-muted hover:text-text-primary border-transparent hover:border-border-default",
          )}
        >
          Scans
        </button>
        <button
          type="button"
          onClick={() => handleViewChange("sectors")}
          aria-current={view === "sectors" ? "true" : undefined}
          className={cn(
            "flex items-center gap-1 px-2.5 py-1.5 text-xxs font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
            view === "sectors"
              ? "text-accent border-accent"
              : "text-text-muted hover:text-text-primary border-transparent hover:border-border-default",
          )}
        >
          Sectors
        </button>
        <div className="flex-1" />
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={openOISignals}
                aria-label="Open unusual OI in OI Analytics"
                className="flex items-center gap-1 px-2.5 py-1.5 text-xxs font-medium text-text-muted hover:text-accent transition-colors whitespace-nowrap shrink-0"
              >
                OI Change
                <ArrowUpRight className="size-3" aria-hidden="true" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="text-xs">
              Unusual OI lives in OI Analytics — opens its Signals view
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </nav>

      {/* Provenance banner — per view, and only for data actually on screen. */}
      {view === "scans" ? (
        run && (
          run.is_sample_data !== false ? (
            <div className="flex-none px-2 py-1 bg-warning/5 border-b border-warning/20">
              <span className="text-xxs text-warning" role="status">
                Sample scan — connect a broker read account to scan live prices
              </span>
            </div>
          ) : (
            <div className="flex-none px-2 py-1 bg-profit/5 border-b border-profit/20">
              <span className="text-xxs text-profit" role="status">
                Live scan — the backend scanned real broker OHLCV
              </span>
            </div>
          )
        )
      ) : sectorMovers.isLive ? (
        <div className="flex-none px-2 py-1 bg-profit/5 border-b border-profit/20">
          <span className="text-xxs text-profit" role="status">
            Live sectors — derived from NIFTY 50 quotes, refreshed every minute
          </span>
        </div>
      ) : (
        <div className="flex-none px-2 py-1 bg-warning/5 border-b border-warning/20">
          <span className="text-xxs text-warning" role="status">
            {sectorMovers.wantsLive
              ? sectorMovers.error
                ? "Sample data — the live sector feed is unavailable right now"
                : "Sample data — waiting for live NIFTY 50 quotes"
              : "Sample data — leave Explore and connect OpenAlgo for live sector movers"}
          </span>
        </div>
      )}

      {/* Selected-scan conditions */}
      {view === "scans" && selectedScan && (
        <div className="flex-none px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex items-center gap-1.5 flex-wrap">
          <span className="text-xxs text-text-muted uppercase tracking-wide">
            {selectedScan.universe} · {selectedScan.timeframe}
          </span>
          {selectedScan.conditions.map((c) => (
            <span
              key={c.label}
              className="inline-flex items-center rounded border border-border-default px-1.5 py-0.5 text-xxs text-text-secondary"
              title={`${c.indicator} ${c.operator} ${c.value}`}
            >
              {c.label}
            </span>
          ))}
        </div>
      )}

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-auto">
        {view === "sectors" ? (
          // TEMPORARY HOME. Sector movers belong with the market/sector family;
          // they stay here until the Market Overview merge gives them one.
          <SortableTable data={sectorMovers.data} columns={sectorCols} label="Sector movers" />
        ) : (
          <>
            {prebuiltQuery.isError && (
              <p className="text-xs text-loss text-center py-8">
                Failed to load scans. Backend may be offline.
              </p>
            )}
            {runMutation.isError && (
              <p className="text-xs text-loss text-center py-8">
                Scan failed: {runMutation.error.message}
              </p>
            )}
            {runMutation.isPending && !run && (
              <p className="flex items-center justify-center gap-2 py-8 text-xs text-text-muted">
                <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                Scanning {selectedScan ? `the ${selectedScan.universe} universe` : "the universe"}…
              </p>
            )}
            {!run && !runMutation.isPending && !runMutation.isError && !prebuiltQuery.isError && (
              <p className="text-xs text-text-muted text-center py-8">
                Choose a prebuilt scan and press Run to screen the universe.
              </p>
            )}
            {run && run.results.length === 0 && (
              <p className="text-xs text-text-muted text-center py-8">
                No symbols matched “{run.scan_name}” ({run.total_universe} scanned).
              </p>
            )}
            {run && run.results.length > 0 && (
              <>
                <div className="text-xxs text-text-muted px-2 pt-1.5">
                  {run.matched_count} of {run.total_universe} matched · {run.scan_name}
                </div>
                <SortableTable data={run.results} columns={scanCols} label="Scan matches" />
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default memo(ConditionScannerWidget);
