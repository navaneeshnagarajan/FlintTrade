/**
 * EtfScreenerTab.tsx
 *
 * Filterable ETF screener for the Invest route (intermediate level).
 *
 * Data flow:
 *   GET /ft-api/api/v1/etf/screener → TanStack Query (5 min stale)
 *   → category filter pills → search input → TanStack Table (sortable)
 *
 * Design absorbed from:
 *   - etftracker Dashboard4_IndiaSectors: category pills, colour-coded return cells
 *   - EtfTab.tsx: TanStack Table column pattern, GlassCard usage
 *   - StocksTab.tsx: search + filter bar, loading/error states
 *
 * Accessibility:
 *   - Table has aria-label and aria-sort on every sortable column
 *   - Category pills use role="radio" group semantics
 *   - Loading skeleton uses role="status" / aria-live
 *   - Return cells supplement colour with + / − prefix (not colour-only)
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import {
  AlertCircle,
  RefreshCw,
  Search,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import {
  getEtfScreener,
  type EtfScreenerRow,
} from "@/services/ftApi";
import { formatPercent } from "../formatters";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_ROWS: EtfScreenerRow[] = [
  { symbol: "NIFTYBEES", name: "Nippon India ETF Nifty 50 BeES", category: "Equity", exchange: "NSE", price: 265.4, change_1d: 0.80, change_1w: 1.20, change_1m: 2.40, change_3m: 4.10, change_1y: 14.20, volume: 1250000, week52_high: 280.5, week52_low: 220.3, expense_ratio: 0.04, aum_cr: 18400 },
  { symbol: "BANKBEES", name: "Nippon India ETF Nifty Bank BeES", category: "Equity", exchange: "NSE", price: 528.6, change_1d: -0.28, change_1w: 0.45, change_1m: 1.80, change_3m: -2.10, change_1y: 8.40, volume: 890000, week52_high: 560.0, week52_low: 470.2, expense_ratio: 0.07, aum_cr: 6800 },
  { symbol: "JUNIORBEES", name: "Nippon India ETF Junior BeES", category: "Equity", exchange: "NSE", price: 762.1, change_1d: 0.56, change_1w: 1.80, change_1m: 3.50, change_3m: 6.20, change_1y: 18.90, volume: 320000, week52_high: 790.0, week52_low: 610.0, expense_ratio: 0.19, aum_cr: 2100 },
  { symbol: "SETFNIF50", name: "SBI ETF Nifty 50", category: "Equity", exchange: "NSE", price: 263.8, change_1d: 0.72, change_1w: 1.15, change_1m: 2.30, change_3m: 3.90, change_1y: 13.80, volume: 710000, week52_high: 278.0, week52_low: 218.0, expense_ratio: 0.07, aum_cr: 21000 },
  { symbol: "ITBEES", name: "Nippon India ETF Nifty IT", category: "Equity", exchange: "NSE", price: 421.3, change_1d: 0.91, change_1w: 2.10, change_1m: 4.80, change_3m: 8.40, change_1y: 22.10, volume: 480000, week52_high: 445.0, week52_low: 320.0, expense_ratio: 0.15, aum_cr: 1200 },
  { symbol: "PHARMABEES", name: "Nippon India ETF Nifty Pharma", category: "Equity", exchange: "NSE", price: 184.7, change_1d: -0.48, change_1w: -1.20, change_1m: 0.60, change_3m: 2.10, change_1y: 12.30, volume: 210000, week52_high: 200.0, week52_low: 155.0, expense_ratio: 0.15, aum_cr: 850 },
  { symbol: "CPSEETF", name: "Nippon India ETF Nifty CPSE", category: "Equity", exchange: "NSE", price: 82.4, change_1d: 0.74, change_1w: 1.60, change_1m: 3.20, change_3m: 5.80, change_1y: 28.40, volume: 560000, week52_high: 92.0, week52_low: 60.0, expense_ratio: 0.01, aum_cr: 3200 },
  { symbol: "GOLDBEES", name: "Nippon India ETF Gold BeES", category: "Gold", exchange: "NSE", price: 58.2, change_1d: 0.61, change_1w: 1.40, change_1m: 3.80, change_3m: 7.20, change_1y: 16.40, volume: 2100000, week52_high: 62.0, week52_low: 48.5, expense_ratio: 0.79, aum_cr: 8900 },
  { symbol: "GOLDIETF", name: "HDFC Gold Exchange Traded Fund", category: "Gold", exchange: "NSE", price: 62.1, change_1d: 0.58, change_1w: 1.35, change_1m: 3.70, change_3m: 7.10, change_1y: 16.10, volume: 380000, week52_high: 66.0, week52_low: 52.0, expense_ratio: 0.59, aum_cr: 2400 },
  { symbol: "SILVERBEES", name: "Nippon India Silver ETF", category: "Silver", exchange: "NSE", price: 92.4, change_1d: 0.45, change_1w: 0.90, change_1m: 2.10, change_3m: 4.80, change_1y: 8.20, volume: 420000, week52_high: 98.0, week52_low: 78.0, expense_ratio: 0.40, aum_cr: 1800 },
  { symbol: "LIQUIDBEES", name: "Nippon India ETF Liquid BeES", category: "Debt", exchange: "NSE", price: 1000.1, change_1d: 0.00, change_1w: 0.14, change_1m: 0.58, change_3m: 1.75, change_1y: 7.10, volume: 150000, week52_high: 1000.5, week52_low: 999.8, expense_ratio: 0.69, aum_cr: 4200 },
  { symbol: "MAFANG", name: "Mirae Asset NYSE FANG+ ETF", category: "International", exchange: "NSE", price: 72.3, change_1d: -0.55, change_1w: -1.20, change_1m: 2.80, change_3m: 5.40, change_1y: 18.60, volume: 95000, week52_high: 80.0, week52_low: 55.0, expense_ratio: 0.70, aum_cr: 1100 },
];

// ─── Category config ──────────────────────────────────────────────────────────

type Category = "All" | EtfScreenerRow["category"];

const CATEGORIES: Category[] = ["All", "Equity", "Gold", "Silver", "Debt", "International"];

// ─── Return cell ──────────────────────────────────────────────────────────────

function ReturnCell({ value }: { value: number }) {
  const pos = value >= 0;
  return (
    <div
      className={cn(
        "text-right font-mono tabular-nums text-xs font-semibold",
        pos ? "text-profit" : "text-loss",
      )}
    >
      {formatPercent(value)}
    </div>
  );
}

// ─── Column definitions ───────────────────────────────────────────────────────

function buildColumns(): ColumnDef<EtfScreenerRow>[] {
  const returnCol = (
    key: keyof EtfScreenerRow,
    label: string,
  ): ColumnDef<EtfScreenerRow> => ({
    accessorKey: key as string,
    header: () => <span className="block text-right">{label}</span>,
    cell: ({ getValue }) => <ReturnCell value={getValue() as number} />,
  });

  return [
    {
      accessorKey: "symbol",
      header: "Symbol / Name",
      cell: ({ row }) => (
        <div>
          <div className="font-mono text-xs font-bold text-text-primary">{row.original.symbol}</div>
          <div className="text-xs text-text-muted max-w-52 truncate leading-tight">{row.original.name}</div>
        </div>
      ),
    },
    {
      accessorKey: "category",
      header: "Category",
      cell: ({ getValue }) => (
        <Badge variant="outline" className="text-xs border-border-default text-text-muted">
          {getValue() as string}
        </Badge>
      ),
    },
    {
      accessorKey: "price",
      header: () => <span className="block text-right">Price</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
          ₹{(getValue() as number).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </div>
      ),
    },
    returnCol("change_1d", "1D%"),
    returnCol("change_1w", "1W%"),
    returnCol("change_1m", "1M%"),
    returnCol("change_3m", "3M%"),
    returnCol("change_1y", "1Y%"),
    {
      accessorKey: "volume",
      header: () => <span className="block text-right">Volume</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          {(getValue() as number).toLocaleString("en-IN")}
        </div>
      ),
    },
    {
      accessorKey: "week52_high",
      header: () => <span className="block text-right">52W H</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          ₹{(getValue() as number).toFixed(1)}
        </div>
      ),
    },
    {
      accessorKey: "week52_low",
      header: () => <span className="block text-right">52W L</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          ₹{(getValue() as number).toFixed(1)}
        </div>
      ),
    },
  ];
}

// ─── Loading skeleton ─────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div
      className="space-y-4"
      role="status"
      aria-label="Loading ETF screener"
      aria-live="polite"
    >
      <div className="h-8 w-64 animate-pulse rounded bg-surface-card border border-border-default" />
      <div className="flex gap-2">
        {CATEGORIES.map((c) => (
          <div key={c} className="h-7 w-20 animate-pulse rounded-full bg-surface-card border border-border-default" />
        ))}
      </div>
      <div className="animate-pulse rounded-lg bg-surface-card border border-border-default h-80" />
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function EtfScreenerTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["etf-screener"],
    queryFn: getEtfScreener,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const [activeCategory, setActiveCategory] = useState<Category>("All");
  const [searchText, setSearchText] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "change_1d", desc: true }]);

  const columns = useMemo(() => buildColumns(), []);

  const isDemo = isError || (!isLoading && (!data || data.is_sample_data));
  const rawRows = data?.etfs ?? DEMO_ROWS;

  // Filter by category and search text
  const filteredRows = useMemo(() => {
    let rows = rawRows;
    if (activeCategory !== "All") {
      rows = rows.filter((r) => r.category === activeCategory);
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      rows = rows.filter(
        (r) =>
          r.symbol.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q),
      );
    }
    return rows;
  }, [rawRows, activeCategory, searchText]);

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  // Summary stats
  const gainers = useMemo(() => rawRows.filter((r) => r.change_1d > 0).length, [rawRows]);
  const losers = useMemo(() => rawRows.filter((r) => r.change_1d < 0).length, [rawRows]);

  if (isLoading) return <LoadingSkeleton />;

  if (isError && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-text-muted">
        <AlertCircle className="size-6" aria-hidden="true" />
        <p className="text-sm">Could not load ETF screener data.</p>
        <Button variant="ghost" size="sm" onClick={() => void refetch()} aria-label="Retry loading ETF screener">
          <RefreshCw className="size-3 mr-1.5" aria-hidden="true" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">ETF Screener</h3>
          <p className="text-xs text-text-muted mt-0.5">
            {rawRows.length} Indian ETFs &mdash;{" "}
            <span className="text-profit">{gainers} up</span>,{" "}
            <span className="text-loss">{losers} down</span> today
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1 shrink-0"
          aria-label="Refresh ETF screener"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Controls: category pills + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Category pills */}
        <div
          role="radiogroup"
          aria-label="Filter by ETF category"
          className="flex flex-wrap gap-1.5"
        >
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              role="radio"
              aria-checked={activeCategory === cat}
              onClick={() => setActiveCategory(cat)}
              className={cn(
                "px-3 py-1 text-xs rounded-full border font-medium transition-colors",
                activeCategory === cat
                  ? "bg-accent text-black border-accent"
                  : "border-border-default text-text-secondary hover:text-text-primary hover:border-border-default/80",
              )}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="relative ml-auto w-full sm:w-52">
          <Search
            className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3 text-text-muted"
            aria-hidden="true"
          />
          <Input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search ETFs..."
            aria-label="Search ETFs by name or symbol"
            className="pl-7 pr-7 h-7 text-xs bg-surface-card border-border-default placeholder:text-text-muted"
          />
          {searchText && (
            <button
              onClick={() => setSearchText("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-secondary"
              aria-label="Clear search"
            >
              <X className="size-3" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      {/* Summary stat pills */}
      <div className="flex items-center gap-2">
        <TrendingUp className="size-3 text-profit" aria-hidden="true" />
        <span className="text-xs text-text-muted font-mono">
          {filteredRows.length} results
        </span>
        {activeCategory !== "All" && (
          <Badge variant="outline" className="text-xs border-border-default text-text-muted h-5">
            {activeCategory}
          </Badge>
        )}
      </div>

      {/* Sortable table */}
      {filteredRows.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted">
          <TrendingDown className="size-5" aria-hidden="true" />
          <p className="text-sm">No ETFs match your filters.</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setActiveCategory("All"); setSearchText(""); }}
            className="text-xs"
          >
            Clear filters
          </Button>
        </div>
      ) : (
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <Table aria-label="ETF screener — click column headers to sort">
              <TableHeader>
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                    {hg.headers.map((header) => {
                      const sorted = header.column.getIsSorted();
                      return (
                        <TableHead
                          key={header.id}
                          className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none whitespace-nowrap"
                          onClick={header.column.getToggleSortingHandler()}
                          aria-sort={
                            sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : "none"
                          }
                        >
                          <span className="flex items-center gap-1">
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" && " ↑"}
                            {sorted === "desc" && " ↓"}
                          </span>
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
                      <TableCell key={cell.id} className="py-2 text-xs whitespace-nowrap">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </GlassCard>
      )}

      <p className="text-xs text-text-muted">
        Returns are approximate. Price data via OpenAlgo NSE. 52W range and AUM are indicative.
        {isDemo ? " Sample data shown — connect broker for live prices." : ""}
      </p>
    </div>
  );
}

export default EtfScreenerTab;
