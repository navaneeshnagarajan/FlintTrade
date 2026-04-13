// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getPositionbook() call with usePositions() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table for sortable positions grid.
import { useMemo, useState, memo } from "react";
import { Clock, Layers } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePositions } from "@/hooks/usePositions";
import type { WidgetProps } from "@/types/widgets";

// OpenAlgo REST returns snake_case at runtime
interface RawPosition {
  symbol: string;
  pnl?: string | number;
  average_price?: string | number;
  ltp?: string | number;
  quantity?: string | number;
}

interface PositionRow {
  symbol: string;
  qty: number;
  ltp: number;
  pnl: number;
}

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function formatPnl(pnl: number): string {
  return `${pnl >= 0 ? "+" : ""}₹${INR.format(Math.abs(pnl))}`;
}

function PositionsWidget(_props: WidgetProps) {
  const { data: positionsData, dataUpdatedAt, isError, error, refetch, isFetching } = usePositions();
  const [sorting, setSorting] = useState<SortingState>([]);

  const rows = useMemo<PositionRow[]>(() => {
    const raw = (positionsData ?? []) as RawPosition[];
    return raw.map((p) => ({
      symbol: p.symbol,
      qty: parseInt(String(p.quantity ?? 0), 10),
      ltp: parseFloat(String(p.ltp ?? 0)),
      pnl: parseFloat(String(p.pnl ?? 0)),
    }));
  }, [positionsData]);

  const totalPnl = useMemo(() => rows.reduce((s, r) => s + r.pnl, 0), [rows]);

  const lastFetch = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  const columns = useMemo<ColumnDef<PositionRow>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium">{row.original.symbol}</span>
        ),
      },
      {
        accessorKey: "qty",
        header: "Qty",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums ${
              row.original.qty > 0
                ? "text-profit"
                : row.original.qty < 0
                  ? "text-loss"
                  : "text-text-secondary"
            }`}
          >
            {row.original.qty}
          </span>
        ),
      },
      {
        accessorKey: "ltp",
        header: "LTP",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{INR.format(row.original.ltp)}</span>
        ),
      },
      {
        accessorKey: "pnl",
        header: "P&L",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums font-medium ${
              row.original.pnl >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {formatPnl(row.original.pnl)}
          </span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base" data-tour-target="positions">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          Positions{rows.length > 0 ? ` (${rows.length})` : ""}
        </span>
        <div className="flex items-center gap-2">
          <span className={`font-mono tabular-nums font-medium ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            P&L: {formatPnl(totalPnl)}
          </span>
          {lastFetch && (
            <span className="text-xxs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
        </div>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load positions{error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {/* Body */}
      {rows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <Layers size={24} className="text-text-disabled" />
          <span className="text-sm">No open positions</span>
        </div>
      ) : (
        <div className="flex-1 overflow-auto min-h-0">
          <div className="overflow-x-auto min-w-0">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className={`text-xxs text-text-muted uppercase tracking-wider cursor-pointer select-none px-2 py-1 whitespace-nowrap ${
                        header.id !== "symbol" ? "text-right" : ""
                      }`}
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
                  className={`border-t border-border-subtle hover:bg-surface-hover/50 ${
                    idx % 2 === 1 ? "bg-surface-stripe" : ""
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={`px-2 py-1 whitespace-nowrap ${cell.column.id !== "symbol" ? "text-right" : ""}`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(PositionsWidget);
