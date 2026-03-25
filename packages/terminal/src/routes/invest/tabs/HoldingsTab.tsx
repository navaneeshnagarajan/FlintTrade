/**
 * HoldingsTab.tsx
 *
 * Sortable TanStack Table of equity holdings with a sticky totals footer.
 * Full-height layout — the outer route wraps this in overflow-hidden so it
 * can own its own scroll area.
 *
 * Accessibility: table has an aria-label; sortable headers use aria-sort.
 */

import { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { AlertCircle, BarChart3, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Holding } from "@/types/api";
import { cn } from "@/lib/utils";
import { useInvest } from "../InvestContext";
import { formatINR, formatPercent } from "../formatters";

// ─── Sub-component ─────────────────────────────────────────────────────────────

function PnLCell({ value, percent }: { value: number; percent: number }) {
  const pos = value >= 0;
  return (
    <div className={cn("text-right", pos ? "text-profit" : "text-loss")}>
      <div className="font-mono tabular-nums text-xs font-semibold">{formatINR(value)}</div>
      <div className="font-mono tabular-nums text-xs opacity-75">{formatPercent(percent)}</div>
    </div>
  );
}

// ─── Column definitions ────────────────────────────────────────────────────────

function buildColumns(): ColumnDef<Holding>[] {
  return [
    {
      accessorKey: "symbol",
      header: "Symbol",
      cell: ({ row }) => (
        <div>
          <div className="text-xs font-semibold text-text-primary font-mono">
            {row.original.symbol}
          </div>
          <div className="text-xs text-text-muted">{row.original.exchange}</div>
        </div>
      ),
    },
    {
      accessorKey: "quantity",
      header: () => <span className="block text-right">Qty</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {(getValue() as number).toLocaleString("en-IN")}
        </div>
      ),
    },
    {
      accessorKey: "averagePrice",
      header: () => <span className="block text-right">Avg Price</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {formatINR(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "ltp",
      header: () => <span className="block text-right">LTP</span>,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-primary font-semibold">
          {formatINR(getValue() as number)}
        </div>
      ),
    },
    {
      id: "invested",
      header: () => <span className="block text-right">Invested</span>,
      accessorFn: (row) => row.averagePrice * row.quantity,
      cell: ({ getValue }) => (
        <div className="text-right font-mono tabular-nums text-xs text-text-secondary">
          {formatINR(getValue() as number)}
        </div>
      ),
    },
    {
      accessorKey: "pnl",
      header: () => <span className="block text-right">P&amp;L</span>,
      cell: ({ row }) => (
        <PnLCell value={row.original.pnl} percent={row.original.pnlPercent} />
      ),
    },
  ];
}

// ─── Component ────────────────────────────────────────────────────────────────

export function HoldingsTab() {
  const { holdings, isLoading, isError, refetchHoldings } = useInvest();
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo(() => buildColumns(), []);

  const table = useReactTable({
    data: holdings,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const totalInvested = useMemo(
    () => holdings.reduce((acc, h) => acc + h.averagePrice * h.quantity, 0),
    [holdings],
  );
  const totalCurrent = useMemo(
    () => holdings.reduce((acc, h) => acc + h.ltp * h.quantity, 0),
    [holdings],
  );
  const totalPnl = useMemo(
    () => holdings.reduce((acc, h) => acc + h.pnl, 0),
    [holdings],
  );
  const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Fetching holdings from OpenAlgo...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <AlertCircle className="size-5 text-loss" />
        <span className="text-sm">Failed to load holdings.</span>
        <Button variant="outline" size="sm" onClick={refetchHoldings} className="text-xs">
          Retry
        </Button>
      </div>
    );
  }

  if (holdings.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <BarChart3 className="size-8 text-text-disabled" />
        <span className="text-sm font-medium text-text-secondary">No holdings found</span>
        <span className="text-xs text-text-muted max-w-sm text-center">
          Buy equities via your broker (via OpenAlgo) and they will appear here after settlement.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-2 py-2 border-b border-border-default shrink-0">
        <span className="text-xs text-text-muted">
          {holdings.length} stock{holdings.length !== 1 ? "s" : ""}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={refetchHoldings}
          className="text-xs text-text-muted h-6 px-2 gap-1"
        >
          <RefreshCw className="size-3" />
          Refresh
        </Button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        <Table aria-label="Holdings">
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
      </div>

      {/* Sticky totals row */}
      <div className="border-t border-border-default bg-surface-card px-4 py-2 grid grid-cols-6 gap-2 text-xs font-mono tabular-nums shrink-0">
        <span className="text-text-secondary font-semibold col-span-1">Total</span>
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-muted" />
        <span className="text-right text-text-secondary">{formatINR(totalInvested)}</span>
        <div className={cn("text-right", totalPnl >= 0 ? "text-profit" : "text-loss")}>
          <div className="font-semibold">{formatINR(totalPnl)}</div>
          <div className="text-xs opacity-75">
            {formatPercent(totalPnlPct)} on {formatINR(totalCurrent)}
          </div>
        </div>
      </div>
    </div>
  );
}
