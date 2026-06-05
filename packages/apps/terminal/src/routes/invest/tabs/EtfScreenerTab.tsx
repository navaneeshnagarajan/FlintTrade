/**
 * EtfScreenerTab.tsx
 *
 * Filterable ETF screener for the Invest route (intermediate level).
 *
 * Data flow:
 *   GET /ft-api/api/v1/screener/etfs → TanStack Query (5 min stale)
 *   → category filter → shadcn Select → TanStack Table (sortable)
 *
 * Views:
 *   - Table view: Symbol, Name, Category, AUM, 1M, 3M, 6M, 12M, Momentum
 *     Score, 52W Hi/Lo, Sparkline
 *   - Asset Quilt: calendar-year return heatmap (rows=ETFs, cols=years),
 *     cells colour-coded by rank within the year (green=top, red=bottom)
 *
 * Design adapted from:
 *   - etftracker Dashboard4_IndiaSectors: category pills, colour-coded return cells
 *   - EtfTab.tsx: TanStack Table column pattern, GlassCard usage
 *   - StocksTab.tsx: search + filter bar, loading/error states
 *
 * Accessibility:
 *   - Table has aria-label and aria-sort on every sortable column
 *   - Category filter uses shadcn Select (keyboard-accessible)
 *   - Loading skeleton uses role="status" / aria-live
 *   - Return cells supplement colour with + / − prefix (not colour-only)
 *   - Asset Quilt cells carry aria-label with symbol + year + return value
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
  Grid2X2,
  LayoutList,
  RefreshCw,
  Search,
  TrendingDown,
  TrendingUp,
  X,
} from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import {
  getEtfScreener,
  type EtfScreenerRow,
} from "@/services/ftApi";
import { formatPercent } from "../formatters";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_ROWS: EtfScreenerRow[] = [
  {
    symbol: "NIFTYBEES", name: "Nippon India ETF Nifty 50 BeES", category: "Equity",
    exchange: "NSE", price: 265.4, change_1d: 0.80, change_1w: 1.20, change_1m: 2.40,
    change_3m: 4.10, change_6m: 8.20, change_1y: 14.20, volume: 1250000,
    week52_high: 280.5, week52_low: 220.3, expense_ratio: 0.04, aum_cr: 18400,
    momentum_score: 82.4,
    sparkline: [0.42, 0.45, 0.40, 0.48, 0.52, 0.50, 0.55, 0.58, 0.54, 0.60,
                0.62, 0.59, 0.63, 0.67, 0.65, 0.70, 0.68, 0.72, 0.75, 0.73,
                0.76, 0.79, 0.77, 0.81, 0.84, 0.82, 0.86, 0.89, 0.87, 0.92],
    annual_returns: { "2020": 14.9, "2021": 24.1, "2022": 4.3, "2023": 20.0, "2024": 8.8 },
  },
  {
    symbol: "BANKBEES", name: "Nippon India ETF Nifty Bank BeES", category: "Equity",
    exchange: "NSE", price: 528.6, change_1d: -0.28, change_1w: 0.45, change_1m: 1.80,
    change_3m: -2.10, change_6m: 2.30, change_1y: 8.40, volume: 890000,
    week52_high: 560.0, week52_low: 470.2, expense_ratio: 0.07, aum_cr: 6800,
    momentum_score: 54.1,
    sparkline: [0.60, 0.58, 0.62, 0.59, 0.55, 0.57, 0.53, 0.56, 0.54, 0.58,
                0.55, 0.52, 0.56, 0.53, 0.57, 0.54, 0.58, 0.55, 0.59, 0.56,
                0.60, 0.57, 0.61, 0.58, 0.55, 0.59, 0.56, 0.60, 0.57, 0.54],
    annual_returns: { "2020": -3.1, "2021": 16.2, "2022": 20.2, "2023": 12.4, "2024": 2.1 },
  },
  {
    symbol: "JUNIORBEES", name: "Nippon India ETF Junior BeES", category: "Equity",
    exchange: "NSE", price: 762.1, change_1d: 0.56, change_1w: 1.80, change_1m: 3.50,
    change_3m: 6.20, change_6m: 12.40, change_1y: 18.90, volume: 320000,
    week52_high: 790.0, week52_low: 610.0, expense_ratio: 0.19, aum_cr: 2100,
    momentum_score: 91.2,
    sparkline: [0.30, 0.33, 0.35, 0.38, 0.36, 0.40, 0.43, 0.46, 0.44, 0.48,
                0.51, 0.54, 0.52, 0.56, 0.59, 0.62, 0.60, 0.64, 0.67, 0.70,
                0.68, 0.72, 0.75, 0.73, 0.77, 0.80, 0.78, 0.82, 0.85, 0.88],
    annual_returns: { "2020": 22.3, "2021": 40.5, "2022": 0.8, "2023": 30.2, "2024": 12.1 },
  },
  {
    symbol: "ITBEES", name: "Nippon India ETF Nifty IT", category: "Sector",
    exchange: "NSE", price: 421.3, change_1d: 0.91, change_1w: 2.10, change_1m: 4.80,
    change_3m: 8.40, change_6m: 15.60, change_1y: 22.10, volume: 480000,
    week52_high: 445.0, week52_low: 320.0, expense_ratio: 0.15, aum_cr: 1200,
    momentum_score: 94.7,
    sparkline: [0.25, 0.28, 0.32, 0.30, 0.34, 0.37, 0.35, 0.40, 0.43, 0.41,
                0.46, 0.50, 0.48, 0.53, 0.57, 0.55, 0.60, 0.64, 0.62, 0.67,
                0.71, 0.69, 0.74, 0.78, 0.76, 0.81, 0.85, 0.83, 0.88, 0.92],
    annual_returns: { "2020": 56.1, "2021": 59.2, "2022": -22.1, "2023": 28.4, "2024": 18.9 },
  },
  {
    symbol: "PHARMABEES", name: "Nippon India ETF Nifty Pharma", category: "Sector",
    exchange: "NSE", price: 184.7, change_1d: -0.48, change_1w: -1.20, change_1m: 0.60,
    change_3m: 2.10, change_6m: 5.20, change_1y: 12.30, volume: 210000,
    week52_high: 200.0, week52_low: 155.0, expense_ratio: 0.15, aum_cr: 850,
    momentum_score: 48.3,
    sparkline: [0.55, 0.52, 0.49, 0.53, 0.56, 0.53, 0.50, 0.54, 0.57, 0.54,
                0.51, 0.55, 0.58, 0.55, 0.52, 0.56, 0.59, 0.56, 0.53, 0.57,
                0.60, 0.57, 0.54, 0.58, 0.61, 0.58, 0.55, 0.59, 0.62, 0.59],
    annual_returns: { "2020": 63.4, "2021": 26.9, "2022": -12.4, "2023": 38.6, "2024": 5.2 },
  },
  {
    symbol: "CPSEETF", name: "Nippon India ETF Nifty CPSE", category: "Equity",
    exchange: "NSE", price: 82.4, change_1d: 0.74, change_1w: 1.60, change_1m: 3.20,
    change_3m: 5.80, change_6m: 11.40, change_1y: 28.40, volume: 560000,
    week52_high: 92.0, week52_low: 60.0, expense_ratio: 0.01, aum_cr: 3200,
    momentum_score: 87.6,
    sparkline: [0.10, 0.14, 0.12, 0.16, 0.19, 0.22, 0.20, 0.24, 0.27, 0.25,
                0.30, 0.33, 0.31, 0.35, 0.38, 0.36, 0.41, 0.44, 0.42, 0.47,
                0.50, 0.53, 0.51, 0.56, 0.59, 0.62, 0.60, 0.65, 0.68, 0.72],
    annual_returns: { "2020": -22.0, "2021": 48.3, "2022": 28.5, "2023": 57.4, "2024": 15.6 },
  },
  {
    symbol: "GOLDBEES", name: "Nippon India ETF Gold BeES", category: "Gold",
    exchange: "NSE", price: 58.2, change_1d: 0.61, change_1w: 1.40, change_1m: 3.80,
    change_3m: 7.20, change_6m: 13.50, change_1y: 16.40, volume: 2100000,
    week52_high: 62.0, week52_low: 48.5, expense_ratio: 0.79, aum_cr: 8900,
    momentum_score: 75.8,
    sparkline: [0.40, 0.43, 0.46, 0.44, 0.47, 0.50, 0.48, 0.52, 0.55, 0.53,
                0.57, 0.60, 0.58, 0.62, 0.65, 0.63, 0.67, 0.70, 0.68, 0.72,
                0.75, 0.73, 0.77, 0.80, 0.78, 0.82, 0.85, 0.83, 0.87, 0.90],
    annual_returns: { "2020": 28.1, "2021": -4.6, "2022": 12.0, "2023": 14.3, "2024": 22.4 },
  },
  {
    symbol: "SILVERBEES", name: "Nippon India Silver ETF", category: "Gold",
    exchange: "NSE", price: 92.4, change_1d: 0.45, change_1w: 0.90, change_1m: 2.10,
    change_3m: 4.80, change_6m: 9.60, change_1y: 8.20, volume: 420000,
    week52_high: 98.0, week52_low: 78.0, expense_ratio: 0.40, aum_cr: 1800,
    momentum_score: 62.4,
    sparkline: [0.50, 0.48, 0.52, 0.55, 0.53, 0.57, 0.54, 0.58, 0.61, 0.59,
                0.63, 0.60, 0.64, 0.67, 0.65, 0.69, 0.66, 0.70, 0.73, 0.71,
                0.75, 0.72, 0.76, 0.79, 0.77, 0.81, 0.78, 0.82, 0.85, 0.83],
    annual_returns: { "2020": 45.2, "2021": -11.0, "2022": 8.4, "2023": 5.1, "2024": 16.8 },
  },
  {
    symbol: "LIQUIDBEES", name: "Nippon India ETF Liquid BeES", category: "Debt",
    exchange: "NSE", price: 1000.1, change_1d: 0.00, change_1w: 0.14, change_1m: 0.58,
    change_3m: 1.75, change_6m: 3.50, change_1y: 7.10, volume: 150000,
    week52_high: 1000.5, week52_low: 999.8, expense_ratio: 0.69, aum_cr: 4200,
    momentum_score: 30.5,
    sparkline: [0.50, 0.51, 0.51, 0.52, 0.52, 0.53, 0.53, 0.54, 0.54, 0.55,
                0.55, 0.56, 0.56, 0.57, 0.57, 0.58, 0.58, 0.59, 0.59, 0.60,
                0.60, 0.61, 0.61, 0.62, 0.62, 0.63, 0.63, 0.64, 0.64, 0.65],
    annual_returns: { "2020": 3.8, "2021": 3.5, "2022": 5.0, "2023": 7.0, "2024": 7.2 },
  },
  {
    symbol: "MAFANG", name: "Mirae Asset NYSE FANG+ ETF", category: "International",
    exchange: "NSE", price: 72.3, change_1d: -0.55, change_1w: -1.20, change_1m: 2.80,
    change_3m: 5.40, change_6m: 9.80, change_1y: 18.60, volume: 95000,
    week52_high: 80.0, week52_low: 55.0, expense_ratio: 0.70, aum_cr: 1100,
    momentum_score: 71.3,
    sparkline: [0.20, 0.24, 0.22, 0.27, 0.30, 0.28, 0.33, 0.37, 0.35, 0.40,
                0.38, 0.43, 0.46, 0.44, 0.49, 0.52, 0.50, 0.55, 0.58, 0.56,
                0.61, 0.64, 0.62, 0.67, 0.70, 0.68, 0.73, 0.76, 0.74, 0.79],
    annual_returns: { "2020": 65.3, "2021": 22.1, "2022": -42.5, "2023": 65.4, "2024": 38.2 },
  },
];

// ─── Category config ──────────────────────────────────────────────────────────

type Category = "All" | EtfScreenerRow["category"];

const CATEGORIES: Category[] = ["All", "Equity", "Gold", "Debt", "International", "Sector"];

// ─── Sparkline ────────────────────────────────────────────────────────────────

function Sparkline({ prices, positive }: { prices: number[]; positive: boolean }) {
  if (!prices || prices.length < 2) return null;

  return (
    <FlintMiniSparkline
      points={prices}
      positive={positive}
      ariaLabel="ETF 30-day trend sparkline"
      className="h-6 w-16 shrink-0"
    />
  );
}

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

// ─── Momentum score badge ─────────────────────────────────────────────────────

function MomentumBadge({ score }: { score: number }) {
  const colour =
    score >= 80 ? "text-profit" :
    score >= 50 ? "text-amber-400" :
    "text-loss";
  return (
    <div className={cn("text-right font-mono tabular-nums text-xs font-bold", colour)}>
      {score.toFixed(1)}
    </div>
  );
}

// ─── AUM formatter ───────────────────────────────────────────────────────────

function formatAum(cr: number): string {
  if (cr >= 10000) return `₹${(cr / 10000).toFixed(1)}T Cr`;
  if (cr >= 1000) return `₹${(cr / 1000).toFixed(1)}K Cr`;
  return `₹${cr.toFixed(0)} Cr`;
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
          <div className="text-xs text-text-muted max-w-48 truncate leading-tight">{row.original.name}</div>
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
      accessorKey: "aum_cr",
      header: () => <span className="block text-right">AUM</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {formatAum(getValue() as number)}
        </div>
      ),
    },
    returnCol("change_1m", "1M%"),
    returnCol("change_3m", "3M%"),
    returnCol("change_6m", "6M%"),
    returnCol("change_1y", "12M%"),
    {
      accessorKey: "momentum_score",
      header: () => <span className="block text-right">Momentum</span>,
      cell: ({ getValue }) => <MomentumBadge score={getValue() as number} />,
    },
    {
      accessorKey: "week52_high",
      header: () => <span className="block text-right">52W Hi</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          ₹{(getValue() as number).toFixed(1)}
        </div>
      ),
    },
    {
      accessorKey: "week52_low",
      header: () => <span className="block text-right">52W Lo</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-muted">
          ₹{(getValue() as number).toFixed(1)}
        </div>
      ),
    },
    {
      id: "sparkline",
      accessorKey: "sparkline",
      header: () => <span>Trend</span>,
      enableSorting: false,
      cell: ({ row }) => (
        <Sparkline prices={row.original.sparkline} positive={row.original.change_1m >= 0} />
      ),
    },
  ];
}

// ─── Asset Quilt view ─────────────────────────────────────────────────────────

/** Derive rank-based colour (1=best green, N=worst red) within a year. */
function quilColour(rank: number, total: number): string {
  if (total <= 1) return "hsl(160, 60%, 40%)";
  // rank is 0-indexed; 0 = best
  const t = rank / (total - 1); // 0=best → 1=worst
  // green at t=0, amber at t=0.5, red at t=1
  if (t < 0.5) {
    const h = Math.round(160 - (160 - 40) * (t / 0.5));  // 160→40
    const l = Math.round(35 + 10 * (1 - t));
    return `hsl(${h}, 70%, ${l}%)`;
  }
  const h = Math.round(40 - (40 - 0) * ((t - 0.5) / 0.5));  // 40→0
  const l = Math.round(30 + 5 * (t - 0.5));
  return `hsl(${h}, 70%, ${l}%)`;
}

function AssetQuilt({ rows }: { rows: EtfScreenerRow[] }) {
  // Collect all years across all ETFs
  const years = useMemo(() => {
    const ys = new Set<string>();
    for (const r of rows) {
      for (const y of Object.keys(r.annual_returns)) ys.add(y);
    }
    return [...ys].sort();
  }, [rows]);

  // Rank within each year (sorted desc by return)
  const ranks = useMemo(() => {
    const map: Record<string, Record<string, number>> = {};
    for (const y of years) {
      const sorted = [...rows]
        .filter((r) => r.annual_returns[y] !== undefined)
        .sort((a, b) => b.annual_returns[y] - a.annual_returns[y]);
      sorted.forEach((r, i) => {
        if (!map[r.symbol]) map[r.symbol] = {};
        map[r.symbol][y] = i;
      });
    }
    return map;
  }, [rows, years]);

  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-text-muted text-sm">
        No ETFs to display.
      </div>
    );
  }

  return (
    <GlassCard className="p-4 overflow-x-auto">
      <div className="space-y-1">
        {/* Header row */}
        <div
          className="grid gap-1 items-center text-xxs text-text-muted font-medium"
          style={{ gridTemplateColumns: `10rem repeat(${years.length}, minmax(3.5rem, 1fr))` }}
        >
          <span>ETF</span>
          {years.map((y) => (
            <span key={y} className="text-center">{y}</span>
          ))}
        </div>

        {/* ETF rows */}
        {rows.map((row) => (
          <div
            key={row.symbol}
            className="grid gap-1 items-center"
            style={{ gridTemplateColumns: `10rem repeat(${years.length}, minmax(3.5rem, 1fr))` }}
          >
            <div className="font-mono text-xs text-text-primary truncate pr-2" title={row.name}>
              {row.symbol}
            </div>
            {years.map((y) => {
              const ret = row.annual_returns[y];
              if (ret === undefined) {
                return (
                  <div
                    key={y}
                    className="h-8 rounded text-center flex items-center justify-center text-xxs text-text-disabled bg-surface-card border border-border-default"
                  >
                    —
                  </div>
                );
              }
              const rank = ranks[row.symbol]?.[y] ?? 0;
              const total = rows.filter((r) => r.annual_returns[y] !== undefined).length;
              const bg = quilColour(rank, total);
              const isPos = ret >= 0;
              return (
                <div
                  key={y}
                  className="h-8 rounded flex items-center justify-center text-xxs font-mono font-semibold text-white"
                  style={{ backgroundColor: bg }}
                  aria-label={`${row.symbol} ${y}: ${isPos ? "+" : ""}${ret.toFixed(1)}%`}
                  title={`${row.symbol} ${y}: ${isPos ? "+" : ""}${ret.toFixed(1)}%`}
                >
                  {isPos ? "+" : ""}{ret.toFixed(1)}%
                </div>
              );
            })}
          </div>
        ))}
      </div>

      <p className="text-xs text-text-muted mt-3">
        Cells ranked within each calendar year — green = best performer, red = worst.
      </p>
    </GlassCard>
  );
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
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-8 w-28 animate-pulse rounded bg-surface-card border border-border-default" />
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

  const [category, setCategory] = useState<Category>("All");
  const [searchText, setSearchText] = useState("");
  const [sorting, setSorting] = useState<SortingState>([{ id: "momentum_score", desc: true }]);
  const [view, setView] = useState<"table" | "quilt">("table");

  const columns = useMemo(() => buildColumns(), []);

  const isDemo = isError || (!isLoading && (!data || data.is_sample_data));
  const rawRows = data?.etfs ?? DEMO_ROWS;

  const filteredRows = useMemo(() => {
    let rows = rawRows;
    if (category !== "All") {
      rows = rows.filter((r) => r.category === category);
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
  }, [rawRows, category, searchText]);

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

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
        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div
            className="flex rounded-md border border-border-default overflow-hidden"
            role="group"
            aria-label="View mode"
          >
            <button
              onClick={() => setView("table")}
              aria-pressed={view === "table"}
              className={cn(
                "px-2.5 py-1.5 text-xs flex items-center gap-1 transition-colors",
                view === "table"
                  ? "bg-accent text-black"
                  : "text-text-muted hover:text-text-primary",
              )}
              aria-label="Table view"
            >
              <LayoutList className="size-3" aria-hidden="true" />
              Table
            </button>
            <button
              onClick={() => setView("quilt")}
              aria-pressed={view === "quilt"}
              className={cn(
                "px-2.5 py-1.5 text-xs flex items-center gap-1 border-l border-border-default transition-colors",
                view === "quilt"
                  ? "bg-accent text-black"
                  : "text-text-muted hover:text-text-primary",
              )}
              aria-label="Asset Quilt view"
            >
              <Grid2X2 className="size-3" aria-hidden="true" />
              Quilt
            </button>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void refetch()}
            className="text-xs text-text-muted h-7 px-2 gap-1"
            aria-label="Refresh ETF screener"
          >
            <RefreshCw className="size-3" aria-hidden="true" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Controls: category selector + search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <Select
          value={category}
          onValueChange={(v) => setCategory(v as Category)}
        >
          <SelectTrigger
            className="h-8 w-44 text-xs bg-surface-card border-border-default"
            aria-label="Filter by ETF category"
          >
            <SelectValue placeholder="All categories" />
          </SelectTrigger>
          <SelectContent className="bg-surface-elevated border-border-default">
            {CATEGORIES.map((cat) => (
              <SelectItem key={cat} value={cat} className="text-xs">
                {cat}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

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
            className="pl-7 pr-7 h-8 text-xs bg-surface-card border-border-default placeholder:text-text-muted"
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

      {/* Result count */}
      <div className="flex items-center gap-2">
        <TrendingUp className="size-3 text-profit" aria-hidden="true" />
        <span className="text-xs text-text-muted font-mono">{filteredRows.length} results</span>
        {category !== "All" && (
          <Badge variant="outline" className="text-xs border-border-default text-text-muted h-5">
            {category}
          </Badge>
        )}
      </div>

      {/* Content */}
      {filteredRows.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-2 py-12 text-text-muted">
          <TrendingDown className="size-5" aria-hidden="true" />
          <p className="text-sm">No ETFs match your filters.</p>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setCategory("All"); setSearchText(""); }}
            className="text-xs"
          >
            Clear filters
          </Button>
        </div>
      ) : view === "quilt" ? (
        <AssetQuilt rows={filteredRows} />
      ) : (
        <GlassCard className="p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <Table aria-label="ETF screener — click column headers to sort">
              <TableHeader>
                {table.getHeaderGroups().map((hg) => (
                  <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                    {hg.headers.map((header) => {
                      const sorted = header.column.getIsSorted();
                      const canSort = header.column.getCanSort();
                      return (
                        <TableHead
                          key={header.id}
                          className={cn(
                            "h-8 text-xxs font-medium text-text-muted uppercase tracking-wider select-none whitespace-nowrap",
                            canSort && "cursor-pointer",
                          )}
                          onClick={canSort ? header.column.getToggleSortingHandler() : undefined}
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
        Momentum score: 40% × 12M + 30% × 6M + 20% × 3M + 10% × 1M return.
        AUM and returns are indicative.
        {isDemo ? " Sample data — connect broker for live prices." : ""}
      </p>
    </div>
  );
}

export default EtfScreenerTab;
