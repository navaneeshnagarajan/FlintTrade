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
import { useNarrowLayout } from "@/hooks/useNarrowLayout";
import { NarrowBookCards } from "@/components/books/NarrowBookCards";
import {
  useTable,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { sortedTableFeatures, type SortedTableFeatures } from "@/lib/tableFeatures";
import { AlertCircle, Download, Printer, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DemoBanner } from "@/components/ui/DemoBanner";
import type { Holding } from "@/types/api";
import { cn } from "@/lib/utils";
import { useInvest } from "../InvestContext";
import { formatINR, formatPercent } from "../formatters";
import { exportToCSV, printCurrentView } from "@/lib/exportUtils";

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

function buildColumns(): ColumnDef<SortedTableFeatures, Holding>[] {
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
  const { holdings, isLoading, isError, isSampleData, refetchHoldings } = useInvest();
  const { isNarrow, containerRef } = useNarrowLayout<HTMLDivElement>();
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo(() => buildColumns(), []);
  const isDemo = Boolean(isSampleData);

  const table = useTable({
    features: sortedTableFeatures,
    data: holdings,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
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
  const narrowCards = useMemo(
    () => holdings.map((h) => ({
      id: `${h.symbol}-${h.exchange}`,
      symbol: h.symbol,
      detail: `${h.exchange} · Qty ${h.quantity.toLocaleString("en-IN")} · LTP ${formatINR(h.ltp)}`,
      pnl: formatINR(h.pnl),
      pnlPercent: formatPercent(h.pnlPercent),
      pnlPositive: h.pnl >= 0,
    })),
    [holdings],
  );

  return (
    <div ref={containerRef} className="flex flex-col h-full overflow-hidden">
      {isLoading ? (
        <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
          <RefreshCw className="size-5 animate-spin" />
          <span className="text-sm">Fetching holdings from your active broker...</span>
        </div>
      ) : isError && holdings.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
          <AlertCircle className="size-6" aria-hidden="true" />
          <span className="text-sm">Failed to load holdings</span>
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
      ) : holdings.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 gap-2 text-text-muted">
          <span className="text-sm">No holdings</span>
        </div>
      ) : (
        <>
      {/* Demo banner */}
      {isDemo && (
        <div className="px-2 pt-2 shrink-0">
          <DemoBanner />
        </div>
      )}

      {/* Toolbar */}
      <div className="flex items-center justify-between px-2 py-2 border-b border-border-default shrink-0">
        <span className="text-xs text-text-muted">
          {holdings.length} stock{holdings.length !== 1 ? "s" : ""}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const csvData = holdings.map((h) => ({
                Symbol: h.symbol,
                Exchange: h.exchange,
                Quantity: h.quantity,
                "Avg Price": h.averagePrice,
                LTP: h.ltp,
                "P&L": h.pnl,
                "P&L %": h.pnlPercent,
              }));
              exportToCSV(csvData, `holdings-${new Date().toISOString().slice(0, 10)}`);
            }}
            className="text-xs text-text-muted h-6 px-2 gap-1"
          >
            <Download className="size-3" />
            Export CSV
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={printCurrentView}
            className="text-xs text-text-muted h-6 px-2 gap-1"
          >
            <Printer className="size-3" />
            Print
          </Button>
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
      </div>

      {/* Table or stacked cards on phone-width surfaces */}
      {isNarrow ? (
        <NarrowBookCards rows={narrowCards} ariaLabel="Holdings" />
      ) : (
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
      )}

      {/* Sticky totals row */}
      <div
        aria-label="Holdings totals"
        className={cn(
          "border-t border-border-default bg-surface-card px-4 py-2 text-xs font-mono tabular-nums shrink-0",
          isNarrow
            ? "flex items-start justify-between gap-3"
            : "grid grid-cols-6 gap-2",
        )}
      >
        <div className={isNarrow ? "min-w-0" : "col-span-1"}>
          <span className="text-text-secondary font-semibold">Total</span>
          {isNarrow && (
            <div className="text-xxs text-text-muted">
              Invested {formatINR(totalInvested)}
            </div>
          )}
        </div>
        {!isNarrow && (
          <>
            <span className="text-right text-text-muted" />
            <span className="text-right text-text-muted" />
            <span className="text-right text-text-muted" />
            <span className="text-right text-text-secondary">{formatINR(totalInvested)}</span>
          </>
        )}
        <div className={cn("text-right", totalPnl >= 0 ? "text-profit" : "text-loss")}>
          <div className="font-semibold">{formatINR(totalPnl)}</div>
          <div className="text-xs opacity-75">
            {formatPercent(totalPnlPct)} on {formatINR(totalCurrent)}
          </div>
        </div>
      </div>
        </>
      )}
    </div>
  );
}
