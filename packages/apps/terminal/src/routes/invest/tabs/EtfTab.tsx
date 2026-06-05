/**
 * EtfTab.tsx
 *
 * Real ETF universe view — replaces the old FeatureLockCard placeholder.
 *
 * Data flow:
 *   ETF_UNIVERSE (static config) → getMultiQuotes() → TanStack Query
 *   → summary cards (grid) + sortable TanStack Table
 *
 * Design adapted from:
 * - etftracker Dashboard4_IndiaSectors: grid of summary cards + table below
 * - SectorTab.tsx: sort-header pattern, GlassCard usage, table structure
 * - HoldingsTab.tsx: TanStack Table column definition and row rendering
 *
 * Accessibility:
 * - Table has aria-label and aria-sort on sortable columns
 * - Loading skeleton uses role="status" / aria-live
 * - Error state provides retry button with explicit label
 * - Colour badges are supplemented by text (not colour-only signals)
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getMultiQuotes, normaliseMultiQuotes } from "@/services/api";
import type { Quote } from "@/types/api";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import { ETF_UNIVERSE, type EtfInfo } from "@/lib/etfs";
import { formatINR, formatPercent } from "../formatters";

// ─── Demo prices (approximate last known) ────────────────────────────────────

const DEMO_ETF_PRICES: Record<string, { ltp: number; change: number; changePct: number; volume: number }> = {
  NIFTYBEES: { ltp: 265, change: 2.10, changePct: 0.80, volume: 1250000 },
  BANKBEES: { ltp: 530, change: -1.50, changePct: -0.28, volume: 890000 },
  JUNIORBEES: { ltp: 760, change: 4.20, changePct: 0.56, volume: 320000 },
  GOLDBEES: { ltp: 58, change: 0.35, changePct: 0.61, volume: 2100000 },
  LIQUIDBEES: { ltp: 1000, change: 0.01, changePct: 0.00, volume: 150000 },
  ITBEES: { ltp: 420, change: 3.80, changePct: 0.91, volume: 480000 },
  PHARMABEES: { ltp: 185, change: -0.90, changePct: -0.48, volume: 210000 },
  CPSEETF: { ltp: 82, change: 0.60, changePct: 0.74, volume: 560000 },
  SETFNIF50: { ltp: 265, change: 1.90, changePct: 0.72, volume: 710000 },
  MAFANG: { ltp: 72, change: -0.40, changePct: -0.55, volume: 95000 },
};

// ─── Types ────────────────────────────────────────────────────────────────────

/** ETF info merged with live quote data. */
interface EtfRow extends EtfInfo {
  ltp: number;
  change: number;
  changePct: number;
  volume: number;
}

// ─── Query ─────────────────────────────────────────────────────────────────────

const ETF_SYMBOLS = ETF_UNIVERSE.map((e) => ({ symbol: e.symbol, exchange: e.exchange }));

function useEtfQuotes() {
  return useQuery<Quote[]>({
    queryKey: ["etf-quotes"],
    queryFn: () => getMultiQuotes(ETF_SYMBOLS).then(normaliseMultiQuotes),
    refetchInterval: 30_000,
    retry: 1,
  });
}

// ─── Merge helper ─────────────────────────────────────────────────────────────

function mergeWithQuotes(quotes: Quote[]): EtfRow[] {
  const quoteMap = new Map<string, Quote>(quotes.map((q) => [q.symbol.toUpperCase(), q]));
  return ETF_UNIVERSE.map((etf): EtfRow => {
    const q = quoteMap.get(etf.symbol.toUpperCase());
    const ltp = q?.ltp ?? 0;
    const prevClose = q?.prev_close ?? q?.close ?? 0;
    const change = prevClose > 0 ? ltp - prevClose : (q?.change ?? 0);
    const changePct =
      prevClose > 0 ? (change / prevClose) * 100 : (q?.pct ?? 0);
    return {
      ...etf,
      ltp,
      change,
      changePct,
      volume: q?.volume ?? 0,
    };
  });
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ChangeCell({ change, pct }: { change: number; pct: number }) {
  const pos = change >= 0;
  return (
    <div className={cn("text-right tabular-nums", pos ? "text-profit" : "text-loss")}>
      <div className="font-mono text-xs font-semibold">{formatPercent(pct)}</div>
      <div className="font-mono text-xs opacity-75">{formatINR(change)}</div>
    </div>
  );
}

function TrendIcon({ pct }: { pct: number }) {
  if (pct > 0) return <TrendingUp className="size-3 text-profit" aria-hidden="true" />;
  if (pct < 0) return <TrendingDown className="size-3 text-loss" aria-hidden="true" />;
  return null;
}

// ─── Summary card skeleton ────────────────────────────────────────────────────

function EtfCardSkeleton() {
  return (
    <div className="animate-pulse rounded-lg bg-surface-card border border-border-default h-28" />
  );
}

// ─── Summary ETF card ─────────────────────────────────────────────────────────

function EtfCard({ row }: { row: EtfRow }) {
  const pos = row.changePct >= 0;
  return (
    <GlassCard className="p-4 gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-xs font-bold text-text-primary truncate">
            {row.symbol}
          </div>
          <div className="text-xs text-text-muted truncate leading-tight mt-0.5">
            {row.underlying}
          </div>
        </div>
        <TrendIcon pct={row.changePct} />
      </div>

      <div className="flex items-end justify-between">
        <div>
          <div className="font-mono text-sm font-bold text-text-primary tabular-nums">
            {row.ltp > 0 ? formatINR(row.ltp) : "—"}
          </div>
          <div
            className={cn(
              "font-mono text-xs tabular-nums",
              pos ? "text-profit" : "text-loss",
            )}
          >
            {row.ltp > 0 ? formatPercent(row.changePct) : "—"}
          </div>
        </div>
        <Badge
          variant="outline"
          className="text-xs border-border-default text-text-muted shrink-0"
        >
          {row.expenseRatio}% TER
        </Badge>
      </div>
    </GlassCard>
  );
}

// ─── Column definitions ───────────────────────────────────────────────────────

function buildColumns(): ColumnDef<EtfRow>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div>
          <div className="font-mono text-xs font-bold text-text-primary">{row.original.symbol}</div>
          <div className="text-xs text-text-muted">{row.original.exchange}</div>
        </div>
      ),
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ getValue }) => (
        <div className="text-xs text-text-secondary max-w-52 truncate">
          {getValue() as string}
        </div>
      ),
    },
    {
      accessorKey: "underlying",
      header: "Underlying",
      cell: ({ getValue }) => (
        <div className="text-xs text-text-muted">{getValue() as string}</div>
      ),
    },
    {
      accessorKey: "ltp",
      header: () => <span className="block text-right">LTP</span>,
      cell: ({ getValue }) => {
        const v = getValue() as number;
        return (
          <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
            {v > 0 ? formatINR(v) : "—"}
          </div>
        );
      },
    },
    {
      accessorKey: "changePct",
      header: () => <span className="block text-right">Change</span>,
      cell: ({ row }) => (
        <ChangeCell change={row.original.change} pct={row.original.changePct} />
      ),
    },
    {
      accessorKey: "expenseRatio",
      header: () => <span className="block text-right">TER%</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toFixed(2)}%
        </div>
      ),
    },
    {
      accessorKey: "volume",
      header: () => <span className="block text-right">Volume</span>,
      cell: ({ getValue }) => {
        const v = getValue() as number;
        return (
          <div className="text-right font-mono tabular-nums text-xs text-text-muted">
            {v > 0 ? v.toLocaleString("en-IN") : "—"}
          </div>
        );
      },
    },
  ];
}

// ─── Main component ───────────────────────────────────────────────────────────

export function EtfTab() {
  const { data: quotes, isLoading, isError, refetch } = useEtfQuotes();

  const [sorting, setSorting] = useState<SortingState>([
    { id: "changePct", desc: true },
  ]);

  const columns = useMemo(() => buildColumns(), []);

  // Fall back to demo prices when API fails or returns empty
  const isDemo = isError || (!isLoading && (!quotes || quotes.length === 0));

  const rows = useMemo<EtfRow[]>(() => {
    if (quotes && quotes.length > 0) return mergeWithQuotes(quotes);
    // Use demo prices when no live data
    return ETF_UNIVERSE.map((e): EtfRow => {
      const demo = DEMO_ETF_PRICES[e.symbol];
      return {
        ...e,
        ltp: demo?.ltp ?? 0,
        change: demo?.change ?? 0,
        changePct: demo?.changePct ?? 0,
        volume: demo?.volume ?? 0,
      };
    });
  }, [quotes]);

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // ─── Loading state ──────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="space-y-6">
        {/* Header */}
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">ETF Universe</h3>
          <p className="text-xs text-text-muted mt-0.5">
            {ETF_UNIVERSE.length} Indian ETFs — fetching live quotes...
          </p>
        </div>

        {/* Card skeletons */}
        <div
          className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3"
          role="status"
          aria-label="Loading ETF quotes"
          aria-live="polite"
        >
          {ETF_UNIVERSE.map((e) => (
            <EtfCardSkeleton key={e.symbol} />
          ))}
        </div>

        {/* Table skeleton */}
        <div className="animate-pulse rounded-lg bg-surface-card border border-border-default h-64" />
      </div>
    );
  }

  // ─── Render ──────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Demo banner */}
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">ETF Universe</h3>
          <p className="text-xs text-text-muted mt-0.5">
            {ETF_UNIVERSE.length} ETFs — {isDemo ? "sample prices" : "live quotes via OpenAlgo. Refreshes every 30s"}.
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1"
          aria-label="Refresh ETF quotes"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Summary card grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
        {rows.map((row) => (
          <EtfCard key={row.symbol} row={row} />
        ))}
      </div>

      {/* Sortable full table */}
      <GlassCard className="p-0 overflow-hidden">
        <Table aria-label="ETF universe — sortable by any column">
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id} className="border-border-default hover:bg-transparent">
                {hg.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider cursor-pointer select-none"
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
                  <TableCell key={cell.id} className="py-2 text-xs">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </GlassCard>

      <p className="text-xs text-text-muted">
        Expense ratios (TER%) are approximate annual values. Price data sourced from
        OpenAlgo via NSE EQ segment. LTP and change% reflect the current session.
      </p>
    </div>
  );
}
