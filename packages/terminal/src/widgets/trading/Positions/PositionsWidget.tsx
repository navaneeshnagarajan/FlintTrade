// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getPositionbook() call with usePositions() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table for sortable positions grid.
import { useMemo, useState } from "react";
import { Clock } from "lucide-react";
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

export default function PositionsWidget(_props: WidgetProps) {
  const { data: positionsData, dataUpdatedAt } = usePositions();
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
            className={`font-mono ${
              row.original.qty > 0
                ? "text-profit"
                : row.original.qty < 0
                  ? "text-loss"
                  : ""
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
          <span className="font-mono text-text-secondary">{INR.format(row.original.ltp)}</span>
        ),
      },
      {
        accessorKey: "pnl",
        header: "P&L",
        cell: ({ row }) => (
          <span
            className={`font-mono font-medium ${
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
    <div className="h-full flex flex-col overflow-hidden text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0">
        <span className="text-text-muted uppercase tracking-wider text-xs">
          {rows.length} position{rows.length !== 1 ? "s" : ""}
        </span>
        <div className="flex items-center gap-2">
          <span className={`font-mono font-medium ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            P&L: {formatPnl(totalPnl)}
          </span>
          {lastFetch && (
            <span className="text-xs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      {rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No positions</div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className="text-xs text-text-muted uppercase tracking-wider cursor-pointer select-none px-2 py-1"
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
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="border-t border-border-subtle hover:bg-surface-hover/50"
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className="px-2 py-1">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
