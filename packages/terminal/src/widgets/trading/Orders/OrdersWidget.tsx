// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getOrderbook() call with useOrders() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table + shadcn Badge for status.
import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { useOrders } from "@/hooks/useOrders";
import type { WidgetProps } from "@/types/widgets";

// OpenAlgo REST returns snake_case at runtime
interface RawOrder {
  symbol: string;
  action?: string;
  quantity?: string | number;
  price?: string | number;
  order_status?: string;
  status?: string;
  timestamp?: string;
}

interface OrderRow {
  symbol: string;
  action: string;
  quantity: string;
  price: string;
  orderStatus: string;
}

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "complete") return "default";
  if (status === "rejected") return "destructive";
  return "secondary";
}

export default function OrdersWidget(_props: WidgetProps) {
  const { data: ordersData, refetch, isFetching } = useOrders();
  const [sorting, setSorting] = useState<SortingState>([]);

  const rows = useMemo<OrderRow[]>(() => {
    const raw = (ordersData ?? []) as RawOrder[];
    return raw.map((o) => ({
      symbol: o.symbol,
      action: o.action ?? "—",
      quantity: String(o.quantity ?? ""),
      price: o.price ? String(o.price) : "MKT",
      orderStatus: o.order_status ?? o.status ?? "—",
    }));
  }, [ordersData]);

  const columns = useMemo<ColumnDef<OrderRow>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium">{row.original.symbol}</span>
        ),
      },
      {
        accessorKey: "action",
        header: "Side",
        cell: ({ row }) => (
          <span
            className={`font-medium ${
              row.original.action === "BUY" ? "text-profit" : "text-loss"
            }`}
          >
            {row.original.action}
          </span>
        ),
      },
      {
        accessorKey: "quantity",
        header: "Qty",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.quantity}</span>
        ),
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.price}</span>
        ),
      },
      {
        accessorKey: "orderStatus",
        header: "Status",
        cell: ({ row }) => (
          <Badge
            variant={statusVariant(row.original.orderStatus)}
            className="text-[10px] font-medium"
          >
            {row.original.orderStatus}
          </Badge>
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
        <span className="text-text-muted uppercase tracking-wider text-[10px]">
          Orders{rows.length > 0 ? ` — ${rows.length}` : ""}
        </span>
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="text-text-muted hover:text-text-primary disabled:opacity-40"
          aria-label="Refresh orders"
        >
          <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Body */}
      {rows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No orders</div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className="text-[10px] text-text-muted uppercase tracking-wider cursor-pointer select-none px-2 py-1"
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
