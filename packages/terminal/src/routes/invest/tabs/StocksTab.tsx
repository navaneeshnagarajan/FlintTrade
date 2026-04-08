/**
 * StocksTab.tsx
 *
 * Stock screener tab for the Invest route — displays fundamental data
 * from the FlintTrade backend stock cache (30 Indian large-cap stocks).
 *
 * Data flow:
 *   useStockScan() → GET /ft-api/v1/stocks/scan → TanStack Query (5 min stale)
 *
 * Features:
 *   - Sector filter dropdown (shadcn/ui Select)
 *   - Sort controls by market cap, PE, ROE, ROCE, dividend yield
 *   - TanStack Table with sortable columns
 *   - Loading skeletons, error state with retry
 *   - Responsive layout with GlassCard container
 *
 * Accessibility:
 *   - Table: aria-label, aria-sort on sortable columns
 *   - Loading skeleton: role="status" + aria-live
 *   - Error state: retry button with aria-label
 *   - Filter controls: proper labels
 */

import { useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import {
  AlertCircle,
  ArrowUpDown,
  BarChart3,
  Download,
  Printer,
  RefreshCw,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useStockScan, type StockFundamentals } from "@/hooks/useStockScan";
import { CompanySnapshot, type SnapshotData } from "@/components/data/CompanySnapshot";
import { cn } from "@/lib/utils";
import { exportToCSV, printCurrentView } from "@/lib/exportUtils";

// ─── Sort options ────────────────────────────────────────────────────────────

const SORT_OPTIONS = [
  { value: "market_cap", label: "Market Cap" },
  { value: "pe_ratio", label: "PE Ratio" },
  { value: "roe", label: "ROE" },
  { value: "roce", label: "ROCE" },
  { value: "dividend_yield", label: "Dividend Yield" },
] as const;

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatMarketCap(crore: number): string {
  if (crore >= 100000) {
    return `${(crore / 100000).toFixed(1)}L Cr`;
  }
  return `${crore.toLocaleString("en-IN")} Cr`;
}

function formatRatio(value: number): string {
  return value.toFixed(1);
}

// ─── Loading skeleton ────────────────────────────────────────────────────────

function TableSkeleton() {
  return (
    <div role="status" aria-live="polite" aria-label="Loading stock data">
      <div className="space-y-2 p-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-16" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
      <span className="sr-only">Loading stock screener data</span>
    </div>
  );
}

// ─── Column definitions ──────────────────────────────────────────────────────

const columns: ColumnDef<StockFundamentals>[] = [
  {
    accessorKey: "symbol",
    header: "Symbol",
    cell: ({ row }) => (
      <div>
        <div className="font-mono text-xs font-bold text-text-primary">
          {row.original.symbol}
        </div>
        <div className="text-xs text-text-muted truncate max-w-45">
          {row.original.name}
        </div>
      </div>
    ),
  },
  {
    accessorKey: "sector",
    header: "Sector",
    cell: ({ getValue }) => (
      <Badge
        variant="outline"
        className="text-xs border-border-default text-text-muted font-normal"
      >
        {getValue() as string}
      </Badge>
    ),
  },
  {
    accessorKey: "market_cap",
    header: () => <span className="block text-right">Mkt Cap</span>,
    cell: ({ getValue }) => (
      <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
        {formatMarketCap(getValue() as number)}
      </div>
    ),
  },
  {
    accessorKey: "pe_ratio",
    header: () => <span className="block text-right">PE</span>,
    cell: ({ getValue }) => (
      <div className="text-right font-mono tabular-nums text-xs text-text-primary">
        {formatRatio(getValue() as number)}
      </div>
    ),
  },
  {
    accessorKey: "pb_ratio",
    header: () => <span className="block text-right">PB</span>,
    cell: ({ getValue }) => (
      <div className="text-right font-mono tabular-nums text-xs text-text-muted">
        {formatRatio(getValue() as number)}
      </div>
    ),
  },
  {
    accessorKey: "roe",
    header: () => <span className="block text-right">ROE %</span>,
    cell: ({ getValue }) => {
      const v = getValue() as number;
      return (
        <div
          className={cn(
            "text-right font-mono tabular-nums text-xs",
            v >= 20 ? "text-profit" : v >= 10 ? "text-text-primary" : "text-text-muted",
          )}
        >
          {formatRatio(v)}%
        </div>
      );
    },
  },
  {
    accessorKey: "roce",
    header: () => <span className="block text-right">ROCE %</span>,
    cell: ({ getValue }) => {
      const v = getValue() as number;
      return (
        <div
          className={cn(
            "text-right font-mono tabular-nums text-xs",
            v >= 20 ? "text-profit" : v >= 10 ? "text-text-primary" : "text-text-muted",
          )}
        >
          {v > 0 ? `${formatRatio(v)}%` : "—"}
        </div>
      );
    },
  },
  {
    accessorKey: "dividend_yield",
    header: () => <span className="block text-right">Div %</span>,
    cell: ({ getValue }) => {
      const v = getValue() as number;
      return (
        <div
          className={cn(
            "text-right font-mono tabular-nums text-xs",
            v >= 3 ? "text-profit" : "text-text-muted",
          )}
        >
          {formatRatio(v)}%
        </div>
      );
    },
  },
];

// ─── Main component ──────────────────────────────────────────────────────────

export function StocksTab() {
  const [selectedSector, setSelectedSector] = useState<string>("all");
  const [sortField, setSortField] = useState<string>("market_cap");
  const [sorting, setSorting] = useState<SortingState>([
    { id: "market_cap", desc: true },
  ]);
  const [selectedStock, setSelectedStock] = useState<StockFundamentals | null>(null);

  const sectorParam = selectedSector === "all" ? undefined : selectedSector;

  const { data, isLoading, isError, refetch } = useStockScan({
    sector: sectorParam,
    sort_by: sortField,
    limit: 50,
  });

  const stocks = data?.stocks ?? [];
  const sectors = data?.sectors ?? [];

  const table = useReactTable({
    data: stocks,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // ─── Render ────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Stock Screener
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Fundamental analysis of 30 Indian large-cap stocks. Filter by
            sector and sort by key metrics.
          </p>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (stocks.length === 0) return;
              const csvData = stocks.map((s) => ({
                Symbol: s.symbol,
                Name: s.name,
                Sector: s.sector,
                "Market Cap (Cr)": s.market_cap,
                PE: s.pe_ratio,
                PB: s.pb_ratio,
                "ROE %": s.roe,
                "ROCE %": s.roce,
                "Div Yield %": s.dividend_yield,
              }));
              exportToCSV(csvData, `stock-screener-${new Date().toISOString().slice(0, 10)}`);
            }}
            className="text-xs text-text-muted h-6 px-2 gap-1"
            aria-label="Export stock data as CSV"
          >
            <Download className="size-3" aria-hidden="true" />
            Export CSV
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={printCurrentView}
            className="text-xs text-text-muted h-6 px-2 gap-1"
            aria-label="Print current view"
          >
            <Printer className="size-3" aria-hidden="true" />
            Print
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            className="text-xs text-text-muted h-6 px-2 gap-1"
            aria-label="Refresh stock data"
          >
            <RefreshCw className="size-3" aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Sector filter */}
        <div className="flex items-center gap-2">
          <label
            htmlFor="sector-filter"
            className="text-xs text-text-muted whitespace-nowrap"
          >
            Sector
          </label>
          <Select value={selectedSector} onValueChange={setSelectedSector}>
            <SelectTrigger
              id="sector-filter"
              className="h-7 w-35 text-xs border-border-default bg-surface-card"
            >
              <SelectValue placeholder="All Sectors" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Sectors</SelectItem>
              {sectors.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Sort control */}
        <div className="flex items-center gap-2">
          <label
            htmlFor="sort-field"
            className="text-xs text-text-muted whitespace-nowrap"
          >
            <ArrowUpDown className="size-3 inline mr-1" aria-hidden="true" />
            Sort
          </label>
          <Select value={sortField} onValueChange={setSortField}>
            <SelectTrigger
              id="sort-field"
              className="h-7 w-35 text-xs border-border-default bg-surface-card"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SORT_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Result count */}
        {!isLoading && !isError && (
          <Badge
            variant="outline"
            className="text-xs border-border-default text-text-muted h-5 px-2"
          >
            {stocks.length} stocks
          </Badge>
        )}
      </div>

      {/* sr-only live region for loading state */}
      <div className="sr-only" role="status" aria-live="polite">
        {isLoading ? "Loading stock data" : "Stock data loaded"}
      </div>

      {/* Error state */}
      {isError && (
        <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
          <AlertCircle className="size-5 text-loss" aria-hidden="true" />
          <span className="text-sm">Failed to load stock data.</span>
          <span className="text-xs text-text-muted max-w-xs text-center">
            Check that the FlintTrade backend is running on port 5100.
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            className="text-xs"
            aria-label="Retry loading stock data"
          >
            <RefreshCw className="size-3 mr-1" aria-hidden="true" />
            Retry
          </Button>
        </div>
      )}

      {/* Loading state */}
      {isLoading && (
        <GlassCard className="p-0 overflow-hidden">
          <TableSkeleton />
        </GlassCard>
      )}

      {/* Data table */}
      {!isLoading && !isError && (
        <GlassCard className="p-0 overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 border-b border-border-default">
            <div className="flex items-center gap-2">
              <BarChart3 className="size-3 text-text-muted" aria-hidden="true" />
              <span className="text-xs font-medium text-text-secondary">
                Fundamentals
              </span>
              {selectedSector !== "all" && (
                <Badge
                  variant="outline"
                  className="text-xs border-border-default text-text-muted h-4 px-1.5"
                >
                  {selectedSector}
                </Badge>
              )}
            </div>
            <span className="text-xs text-text-muted">
              Sorted by {SORT_OPTIONS.find((o) => o.value === sortField)?.label ?? sortField}
            </span>
          </div>

          <Table aria-label="Stock fundamentals screener — sortable by any column">
            <TableHeader>
              {table.getHeaderGroups().map((hg) => (
                <TableRow
                  key={hg.id}
                  className="border-border-default hover:bg-transparent"
                >
                  {hg.headers.map((header) => {
                    const sorted = header.column.getIsSorted();
                    const canSort = header.column.getCanSort();
                    return (
                      <TableHead
                        key={header.id}
                        className={cn(
                          "h-8 text-xxs font-medium text-text-muted uppercase tracking-wider",
                          canSort && "cursor-pointer select-none",
                        )}
                        onClick={
                          canSort
                            ? header.column.getToggleSortingHandler()
                            : undefined
                        }
                        aria-sort={
                          canSort
                            ? sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : "none"
                            : undefined
                        }
                      >
                        <span className="flex items-center gap-1">
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                          {sorted === "asc" && <span aria-hidden="true"> ↑</span>}
                          {sorted === "desc" && <span aria-hidden="true"> ↓</span>}
                        </span>
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length > 0
                ? table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className={cn(
                        "border-border-default hover:bg-surface-card transition-colors cursor-pointer",
                        selectedStock?.symbol === row.original.symbol && "bg-surface-card",
                      )}
                      onClick={() =>
                        setSelectedStock(
                          selectedStock?.symbol === row.original.symbol ? null : row.original,
                        )
                      }
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="py-2 text-xs">
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                : (
                    <TableRow>
                      <TableCell
                        colSpan={columns.length}
                        className="py-8 text-center"
                      >
                        <div className="flex flex-col items-center gap-2 text-text-muted">
                          <BarChart3 className="size-5 text-text-disabled" aria-hidden="true" />
                          <span className="text-xs">
                            No stocks match the current filters.
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
            </TableBody>
          </Table>
        </GlassCard>
      )}

      {/* Company Snapshot panel */}
      {selectedStock && (
        <div className="relative">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedStock(null)}
            className="absolute -top-1 right-0 text-xs text-text-muted h-6 w-6 p-0"
            aria-label="Close company snapshot"
          >
            <X className="size-3.5" />
          </Button>
          <CompanySnapshot
            data={selectedStock as SnapshotData}
          />
        </div>
      )}

      <p className="text-xs text-text-muted">
        Fundamental data is cached for 24 hours. Market cap in INR crore.
        PE/PB ratios are TTM. ROE and ROCE as percentage.
        Click any row to view a detailed snapshot.
      </p>
    </div>
  );
}
