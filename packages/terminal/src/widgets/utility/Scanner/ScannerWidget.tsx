/**
 * ScannerWidget — Pre-Market Scanner for FlintTrade terminal.
 *
 * Features:
 *   - 4 tabs: Gap Scan | OI Change | Volume | Sectors
 *   - Sortable TanStack Tables per tab
 *   - Color-coded bullish (green) / bearish (red) signals
 *   - Auto-refresh indicator (simulated, ready for real data)
 *   - "Add to Watchlist" action per row
 *   - Sample data seeded with realistic NIFTY 50 patterns
 *
 * Ready to wire to OpenAlgo pre-market data when available.
 */

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
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
import {
  SAMPLE_GAP_SCANS,
  SAMPLE_OI_CHANGES,
  SAMPLE_VOLUME_SPIKES,
  SAMPLE_SECTOR_MOVERS,
  type GapScanEntry,
  type OIChangeEntry,
  type VolumeSpikeEntry,
  type SectorMoverEntry,
} from "./sampleData";

// ─── Constants ──────────────────────────────────────────────────────────────────

type ScannerTab = "gap" | "oi" | "volume" | "sectors";

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

  const handleAdd = useCallback(() => {
    try {
      const LS_KEY = "flinttrade:watchlist";
      const raw = localStorage.getItem(LS_KEY);
      const list: Array<{ symbol: string; exchange: string }> = raw ? JSON.parse(raw) : [];
      const exists = list.some((w) => w.symbol === symbol && w.exchange === exchange);
      if (!exists) {
        list.push({ symbol, exchange });
        localStorage.setItem(LS_KEY, JSON.stringify(list));
      }
      setAdded(true);
    } catch {
      // localStorage unavailable
    }
  }, [symbol, exchange]);

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

function gapColumns(): ColumnDef<GapScanEntry, unknown>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          {row.original.gapType === "up" ? (
            <TrendingUp className="size-3 text-profit shrink-0" />
          ) : (
            <TrendingDown className="size-3 text-loss shrink-0" />
          )}
          <div>
            <div className="text-xs font-semibold text-text-primary font-mono">
              {row.original.symbol}
            </div>
            <div className="text-xxs text-text-muted">{row.original.sector}</div>
          </div>
        </div>
      ),
    },
    {
      accessorKey: "prevClose",
      header: () => <span className="block text-right">Prev Close</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {fmtPrice(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "openPrice",
      header: () => <span className="block text-right">Open</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
          {fmtPrice(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "gapPercent",
      header: () => <span className="block text-right">Gap %</span>,
      cell: ({ row }) => {
        const v = row.original.gapPercent;
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
      accessorKey: "volume",
      header: () => <span className="block text-right">Volume</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {fmtVolume(getValue() as number)}
        </div>
      ),
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

function oiColumns(): ColumnDef<OIChangeEntry, unknown>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div>
          <div className="text-xs font-semibold text-text-primary font-mono">
            {row.original.symbol}
          </div>
          <div className="text-xxs text-text-muted">{row.original.exchange}</div>
        </div>
      ),
    },
    {
      accessorKey: "oiChangePct",
      header: () => <span className="block text-right">OI Change %</span>,
      cell: ({ row }) => {
        const v = row.original.oiChangePct;
        return (
          <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
            {fmtPct(v)}
          </div>
        );
      },
    },
    {
      accessorKey: "oiChange",
      header: () => <span className="block text-right">OI Change</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {fmtVolume(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "price",
      header: () => <span className="block text-right">Price</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-primary">
          {fmtPrice(getValue() as number)}
        </div>
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
              s === "bullish" && "text-profit border-profit/30 bg-profit/5",
              s === "bearish" && "text-loss border-loss/30 bg-loss/5",
              s === "neutral" && "text-text-muted border-border-default",
            )}
          >
            {s}
          </Badge>
        );
      },
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

function volumeColumns(): ColumnDef<VolumeSpikeEntry, unknown>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div>
          <div className="text-xs font-semibold text-text-primary font-mono">
            {row.original.symbol}
          </div>
          <div className="text-xxs text-text-muted">{row.original.sector}</div>
        </div>
      ),
    },
    {
      accessorKey: "volumeRatio",
      header: () => <span className="block text-right">Vol Ratio</span>,
      cell: ({ row }) => {
        const v = row.original.volumeRatio;
        return (
          <div
            className={cn(
              "text-right font-mono tabular-nums text-xs font-semibold",
              v >= 2 ? "text-profit" : v >= 1.5 ? "text-warning" : "text-text-secondary",
            )}
          >
            {v.toFixed(2)}x
          </div>
        );
      },
    },
    {
      accessorKey: "preMarketVolume",
      header: () => <span className="block text-right">Pre-Mkt Vol</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {fmtVolume(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "avgVolume",
      header: () => <span className="block text-right">Avg Vol</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          {fmtVolume(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "changePercent",
      header: () => <span className="block text-right">Change %</span>,
      cell: ({ row }) => {
        const v = row.original.changePercent;
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

export default function ScannerWidget() {
  const [activeTab, setActiveTab] = useState<ScannerTab>("gap");
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [isRefreshing, setIsRefreshing] = useState(false);
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Memoize columns
  const gapCols = useMemo(() => gapColumns(), []);
  const oiCols = useMemo(() => oiColumns(), []);
  const volumeCols = useMemo(() => volumeColumns(), []);
  const sectorCols = useMemo(() => sectorColumns(), []);

  // Simulated auto-refresh (60s interval — ready for real data)
  useEffect(() => {
    refreshTimerRef.current = setInterval(() => {
      setLastRefresh(new Date());
    }, 60_000);

    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current);
    };
  }, []);

  const handleManualRefresh = useCallback(() => {
    setIsRefreshing(true);
    // Simulate refresh delay
    setTimeout(() => {
      setLastRefresh(new Date());
      setIsRefreshing(false);
    }, 500);
  }, []);

  const refreshTime = useMemo(() => {
    return lastRefresh.toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZone: "Asia/Kolkata",
    });
  }, [lastRefresh]);

  return (
    <div className="h-full flex flex-col bg-surface-base text-text-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <ScanLine className="size-3.5 text-accent shrink-0" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Scanner
        </span>

        <div className="flex-1" />

        {/* Auto-refresh indicator */}
        <span className="text-xxs font-mono text-text-muted" title="Last refreshed">
          {refreshTime}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleManualRefresh}
          disabled={isRefreshing}
          className="h-5 w-5 p-0 text-text-muted hover:text-text-primary"
          aria-label="Refresh scanner"
        >
          <RefreshCw className={cn("size-3", isRefreshing && "animate-spin")} />
        </Button>
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

      {/* Sample data notice */}
      <div className="px-2 py-1 bg-warning/5 border-b border-warning/20 shrink-0">
        <span className="text-xxs text-warning">
          Sample data — connect broker for live pre-market data
        </span>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto">
        {activeTab === "gap" && (
          <SortableTable data={SAMPLE_GAP_SCANS} columns={gapCols} />
        )}
        {activeTab === "oi" && (
          <SortableTable data={SAMPLE_OI_CHANGES} columns={oiCols} />
        )}
        {activeTab === "volume" && (
          <SortableTable data={SAMPLE_VOLUME_SPIKES} columns={volumeCols} />
        )}
        {activeTab === "sectors" && (
          <SortableTable data={SAMPLE_SECTOR_MOVERS} columns={sectorCols} />
        )}
      </div>
    </div>
  );
}
