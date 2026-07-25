/**
 * ScannerWidget — Pre-Market Scanner for FlintTrade terminal.
 *
 * Features:
 *   - 4 tabs: Gap Scan | OI Change | Volume | Sectors
 *   - Gap Scan and Volume run REAL backend scans (`/v1/scanner/run` prebuilt
 *     `pre_market_movers` / `volume_breakout` over the NIFTY 50 universe) —
 *     the response's own `is_sample_data` flag drives the Live / Sample badge,
 *     live when a broker read account is connected, deterministic sample bars
 *     otherwise.
 *   - Sectors derives live per-sector movers from NIFTY 50 multi-quotes
 *     outside Explore (useSectorMovers); sample rows, disclosed, otherwise.
 *   - OI Change surfaces unusual-OI outliers from the shared /v1/oi family
 *     (live broker chain when connected; the response flag drives the badge).
 *   - Sortable TanStack Tables per tab.
 */

import { useState, useMemo, useCallback, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import {
  ScanLine,
  TrendingUp,
  TrendingDown,
  BarChart3,
  Activity,
  Map,
  Plus,
  Loader2,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { addSymbolToWatchlist } from "@/widgets/utility/Watchlist/types";
import { type SectorMoverEntry } from "./sampleData";
import { runPrebuiltScan, type ScannerResultRow } from "@/services/ftApi";
import { getUnusualOI, type UnusualOIRow } from "@/services/ftApi.analysis";
import { useSectorMovers } from "@/hooks/useSectorMovers";

// ─── Constants ──────────────────────────────────────────────────────────────────

type ScannerTab = "gap" | "oi" | "volume" | "sectors";

/** Backend prebuilt-scan key backing each live tab. */
const LIVE_TAB_SCANS: Partial<Record<ScannerTab, string>> = {
  gap: "pre_market_movers",
  volume: "volume_breakout",
};

interface TabDef {
  id: ScannerTab;
  label: string;
  icon: typeof TrendingUp;
}

const SCANNER_TABS: TabDef[] = [
  { id: "gap", label: "Gap Scan", icon: TrendingUp },
  { id: "oi", label: "OI Change", icon: BarChart3 },
  { id: "volume", label: "Volume", icon: Activity },
  { id: "sectors", label: "Sectors", icon: Map },
];

// ─── Formatters ─────────────────────────────────────────────────────────────────

const INR = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

const NUM = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtPrice(v: number): string {
  return INR.format(v);
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

function fmtVolume(v: number): string {
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(2)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return NUM.format(v);
}

// ─── Sortable Table component ───────────────────────────────────────────────────

interface SortableTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  onAddToWatchlist?: (symbol: string, exchange: string) => void;
}

function SortableTable<T>({ data, columns }: SortableTableProps<T>) {
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
    <div className="flex-1 overflow-auto">
      <Table aria-label="Scanner results">
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
                    {sorted === "asc" && " \u2191"}
                    {sorted === "desc" && " \u2193"}
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
              className="border-border-default hover:bg-surface-card transition-colors"
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
    </div>
  );
}

// ─── Add to Watchlist button ────────────────────────────────────────────────────

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

// ─── Column definitions ─────────────────────────────────────────────────────────

function scanColumns(): ColumnDef<ScannerResultRow, unknown>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          {row.original.change_pct >= 0 ? (
            <TrendingUp className="size-3 text-profit shrink-0" />
          ) : (
            <TrendingDown className="size-3 text-loss shrink-0" />
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
          {(getValue() as number).toFixed(0)}
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

function unusualOIColumns(): ColumnDef<UnusualOIRow, unknown>[] {
  return [
    {
      accessorKey: "strike",
      header: "Strike",
      cell: ({ row }) => (
        <div className="text-xs font-semibold text-text-primary font-mono">
          {row.original.strike} {row.original.option_type}
        </div>
      ),
    },
    {
      accessorKey: "oi",
      header: () => <span className="block text-right">OI</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {fmtVolume(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "oi_change",
      header: () => <span className="block text-right">OI Chg</span>,
      cell: ({ row }) => {
        const v = row.original.oi_change;
        return (
          <div
            className={cn(
              "text-right font-mono tabular-nums text-xs font-semibold",
              v >= 0 ? "text-profit" : "text-loss",
            )}
          >
            {v >= 0 ? "+" : ""}{fmtVolume(v)}
          </div>
        );
      },
    },
    {
      accessorKey: "z_score",
      header: () => <span className="block text-right">Z</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toFixed(1)}
        </div>
      ),
    },
    {
      accessorKey: "direction",
      header: "Signal",
      cell: ({ row }) => (
        <Badge
          variant="outline"
          className={cn(
            "text-xxs h-5",
            row.original.direction === "addition"
              ? "text-profit border-profit/30 bg-profit/5"
              : "text-loss border-loss/30 bg-loss/5",
          )}
        >
          {row.original.direction}
        </Badge>
      ),
      enableSorting: false,
    },
  ];
}


function sectorColumns(): ColumnDef<SectorMoverEntry, unknown>[] {
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

// ─── Main Widget ────────────────────────────────────────────────────────────────

function ScannerWidget() {
  const [activeTab, setActiveTab] = useState<ScannerTab>("gap");

  // Memoize columns
  const liveCols = useMemo(() => scanColumns(), []);
  const unusualCols = useMemo(() => unusualOIColumns(), []);
  const sectorCols = useMemo(() => sectorColumns(), []);

  // Gap and Volume run real backend scans; the response's own is_sample_data
  // flag drives the badge, so the widget never guesses connection state.
  const liveScanKey = LIVE_TAB_SCANS[activeTab];
  const scanQuery = useQuery({
    queryKey: ["scannerPrebuiltRun", liveScanKey],
    queryFn: () => runPrebuiltScan(liveScanKey ?? ""),
    enabled: liveScanKey !== undefined,
    staleTime: 60_000,
    retry: 1,
  });

  // Sectors derive from live multi-quotes outside Explore; isLive is true only
  // when real quote data actually backs the rows.
  const sectorMovers = useSectorMovers();

  // OI Change: unusual-OI outliers from the shared /v1/oi family — the same
  // client OISignals uses; the response's own is_sample_data drives the badge.
  const unusualOIQuery = useQuery({
    queryKey: ["scannerUnusualOI"],
    queryFn: () => getUnusualOI("NIFTY", "NFO", ""),
    enabled: activeTab === "oi",
    staleTime: 60_000,
    retry: 1,
  });

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <ScanLine className="size-3.5 text-accent shrink-0" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Scanner
        </span>

        <div className="flex-1" />
        {liveScanKey !== undefined && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-accent"
            onClick={() => void scanQuery.refetch()}
            disabled={scanQuery.isFetching}
            aria-label="Re-run scan"
          >
            <RefreshCw className={cn("size-3", scanQuery.isFetching && "animate-spin")} />
          </Button>
        )}
        {activeTab === "sectors" && sectorMovers.isLive && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-accent"
            onClick={() => sectorMovers.refetch()}
            aria-label="Refresh sector movers"
          >
            <RefreshCw className="size-3" />
          </Button>
        )}
      </div>

      {/* Tab bar */}
      <nav
        aria-label="Scanner tabs"
        className="flex items-end gap-0 px-2 border-b border-border-default bg-surface-card shrink-0"
      >
        {SCANNER_TABS.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              aria-current={isActive ? "true" : undefined}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 text-xxs font-medium transition-colors border-b-2 whitespace-nowrap shrink-0",
                isActive
                  ? "text-accent border-accent"
                  : "text-text-muted hover:text-text-primary border-transparent hover:border-border-default",
              )}
            >
              <Icon className="size-3 shrink-0" />
              {tab.label}
            </button>
          );
        })}
      </nav>

      {/* Provenance notice — per-tab, honest. Banners render only for the
          data actually on screen: a failed refetch (TanStack keeps stale data
          in the error state) must never leave a green Live banner above an
          error body or frozen rows. */}
      {liveScanKey !== undefined ? (
        !scanQuery.isError && scanQuery.data && (
          scanQuery.data.is_sample_data ? (
            <div className="px-2 py-1 bg-warning/5 border-b border-warning/20 shrink-0">
              <span className="text-xxs text-warning" role="status">
                Sample scan — connect a broker read account to scan live prices
              </span>
            </div>
          ) : (
            <div className="px-2 py-1 bg-profit/5 border-b border-profit/20 shrink-0">
              <span className="text-xxs text-profit" role="status">
                Live scan — {scanQuery.data.scan_name} · {scanQuery.data.matched_count} of{" "}
                {scanQuery.data.total_universe} matched
              </span>
            </div>
          )
        )
      ) : activeTab === "oi" ? (
        !unusualOIQuery.isError && unusualOIQuery.data && (
          unusualOIQuery.data.is_sample_data ? (
            <div className="px-2 py-1 bg-warning/5 border-b border-warning/20 shrink-0">
              <span className="text-xxs text-warning" role="status">
                Sample OI data — connect a broker read account for live chain OI
              </span>
            </div>
          ) : (
            <div className="px-2 py-1 bg-profit/5 border-b border-profit/20 shrink-0">
              <span className="text-xxs text-profit" role="status">
                Live unusual OI — NIFTY · {unusualOIQuery.data.count} outliers
              </span>
            </div>
          )
        )
      ) : activeTab === "sectors" ? (
        sectorMovers.isLive ? (
          <div className="px-2 py-1 bg-profit/5 border-b border-profit/20 shrink-0">
            <span className="text-xxs text-profit" role="status">
              Live sectors — derived from NIFTY 50 quotes, refreshed every minute
            </span>
          </div>
        ) : (
          <div className="px-2 py-1 bg-warning/5 border-b border-warning/20 shrink-0">
            <span className="text-xxs text-warning" role="status">
              {sectorMovers.wantsLive
                ? sectorMovers.error
                  ? "Sample data — the live sector feed is unavailable right now"
                  : "Sample data — waiting for live NIFTY 50 quotes"
                : "Sample data — leave Explore and connect OpenAlgo for live sector movers"}
            </span>
          </div>
        )
      ) : (
        <div className="px-2 py-1 bg-warning/5 border-b border-warning/20 shrink-0">
          <span className="text-xxs text-warning">
            Sample data — no live source exists for this scan yet
          </span>
        </div>
      )}

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {liveScanKey !== undefined && (
          scanQuery.isLoading ? (
            <div className="flex items-center justify-center h-full gap-2 text-text-muted">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              <span className="text-xs">Scanning the NIFTY 50 universe…</span>
            </div>
          ) : scanQuery.isError ? (
            <div className="flex flex-col items-center justify-center h-full gap-1 text-center px-4">
              <span className="text-loss text-xs">Scan failed.</span>
              <span className="text-text-muted text-xxs">
                {scanQuery.error instanceof Error
                  ? scanQuery.error.message
                  : "Backend may be offline."}
              </span>
            </div>
          ) : (scanQuery.data?.results.length ?? 0) === 0 ? (
            <div className="flex items-center justify-center h-full px-4 text-center">
              <span className="text-xs text-text-muted">
                No matches in the scan universe right now.
              </span>
            </div>
          ) : (
            <SortableTable data={scanQuery.data?.results ?? []} columns={liveCols} />
          )
        )}
        {activeTab === "oi" && (
          unusualOIQuery.isLoading ? (
            <div className="flex items-center justify-center h-full gap-2 text-text-muted">
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              <span className="text-xs">Scanning the option chain…</span>
            </div>
          ) : unusualOIQuery.isError ? (
            <div className="flex flex-col items-center justify-center h-full gap-1 text-center px-4">
              <span className="text-loss text-xs">OI scan failed.</span>
              <span className="text-text-muted text-xxs">
                {unusualOIQuery.error instanceof Error
                  ? unusualOIQuery.error.message
                  : "Backend may be offline."}
              </span>
            </div>
          ) : (unusualOIQuery.data?.unusual.length ?? 0) === 0 ? (
            <div className="flex items-center justify-center h-full px-4 text-center">
              <span className="text-xs text-text-muted">
                No unusual OI activity detected right now.
              </span>
            </div>
          ) : (
            <SortableTable data={unusualOIQuery.data?.unusual ?? []} columns={unusualCols} />
          )
        )}
        {activeTab === "sectors" && (
          <SortableTable data={sectorMovers.data} columns={sectorCols} />
        )}
      </div>
    </div>
  );
}

export default memo(ScannerWidget);
