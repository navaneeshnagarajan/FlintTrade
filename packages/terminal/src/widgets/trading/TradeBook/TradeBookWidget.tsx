// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getTradebook() call with useTradebook() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table + shadcn Badge for BUY/SELL side badges.
import { useMemo, useState } from "react";
import { Clock, RefreshCw } from "lucide-react";
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
import { useTradebook } from "@/hooks/useTradebook";
import type { WidgetProps } from "@/types/widgets";

// OpenAlgo REST returns snake_case; tradebook field names vary by broker.
interface RawTrade {
  symbol?: string;
  tradingsymbol?: string;
  action?: string;
  transaction_type?: string;
  side?: string;
  quantity?: string | number;
  qty?: string | number;
  filled_quantity?: string | number;
  average_price?: string | number;
  price?: string | number;
  trade_price?: string | number;
  trade_time?: string;
  timestamp?: string;
  order_time?: string;
}

interface TradeRow {
  timeDisplay: string;
  timeSortMs: number;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  value: number;
}

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

const FILTER_ALL = "ALL";
const FILTER_BUY = "BUY";
const FILTER_SELL = "SELL";
type FilterValue = typeof FILTER_ALL | typeof FILTER_BUY | typeof FILTER_SELL;

function parseTradeTime(trade: RawTrade): { display: string; ms: number } {
  const raw = trade.trade_time ?? trade.timestamp ?? trade.order_time ?? "";
  if (!raw) return { display: "—", ms: 0 };
  const d = new Date(raw);
  if (!isNaN(d.getTime())) {
    return {
      display: d.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false }),
      ms: d.getTime(),
    };
  }
  return { display: String(raw).slice(0, 8), ms: 0 };
}

function resolveSide(t: RawTrade): string {
  return (t.action ?? t.transaction_type ?? t.side ?? "").toUpperCase();
}

interface FilterPillProps {
  value: FilterValue;
  label: string;
  count: number;
  activeFilter: FilterValue;
  onClick: (v: FilterValue) => void;
}

function FilterPill({ value, label, count, activeFilter, onClick }: FilterPillProps) {
  const active = activeFilter === value;
  return (
    <button
      onClick={() => onClick(value)}
      className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
        active
          ? value === FILTER_BUY
            ? "bg-profit/20 text-profit border border-profit/40"
            : value === FILTER_SELL
              ? "bg-loss/20 text-loss border border-loss/40"
              : "bg-surface-hover text-text-primary border border-border-default"
          : "text-text-muted border border-transparent hover:text-text-secondary hover:border-border-default"
      }`}
    >
      {label}
      {count > 0 ? ` (${count})` : ""}
    </button>
  );
}

export default function TradeBookWidget(_props: WidgetProps) {
  const { data: tradesData, dataUpdatedAt, refetch, isFetching } = useTradebook();
  const [sorting, setSorting] = useState<SortingState>([]);
  const [filter, setFilter] = useState<FilterValue>(FILTER_ALL);

  const allRows = useMemo<TradeRow[]>(() => {
    const raw = (tradesData ?? []) as RawTrade[];
    return raw
      .map((t) => {
        const side = resolveSide(t);
        const qty = parseInt(
          String(t.quantity ?? t.qty ?? t.filled_quantity ?? 0),
          10,
        );
        const price = parseFloat(String(t.average_price ?? t.price ?? t.trade_price ?? 0));
        const { display, ms } = parseTradeTime(t);
        return {
          timeDisplay: display,
          timeSortMs: ms,
          symbol: ((t.symbol ?? t.tradingsymbol) || "—").toUpperCase(),
          side,
          qty,
          price,
          value: qty * price,
        };
      })
      .sort((a, b) => b.timeSortMs - a.timeSortMs);
  }, [tradesData]);

  const counts = useMemo(
    () => ({
      all: allRows.length,
      buy: allRows.filter((r) => r.side === FILTER_BUY).length,
      sell: allRows.filter((r) => r.side === FILTER_SELL).length,
    }),
    [allRows],
  );

  const filteredRows = useMemo<TradeRow[]>(() => {
    if (filter === FILTER_ALL) return allRows;
    return allRows.filter((r) => r.side === filter);
  }, [allRows, filter]);

  const lastFetch = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  const columns = useMemo<ColumnDef<TradeRow>[]>(
    () => [
      {
        accessorKey: "timeDisplay",
        header: "Time",
        cell: ({ row }) => (
          <span className="font-mono text-text-muted whitespace-nowrap">{row.original.timeDisplay}</span>
        ),
      },
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium">{row.original.symbol}</span>
        ),
      },
      {
        accessorKey: "side",
        header: "Side",
        cell: ({ row }) => (
          <Badge
            variant={row.original.side === "BUY" ? "default" : "destructive"}
            className={`text-xs font-semibold ${
              row.original.side === "BUY"
                ? "bg-profit/15 text-profit border border-profit/30"
                : "bg-loss/15 text-loss border border-loss/30"
            }`}
          >
            {row.original.side || "—"}
          </Badge>
        ),
      },
      {
        accessorKey: "qty",
        header: "Qty",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.qty}</span>
        ),
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => (
          <span className="font-mono text-text-primary">{INR.format(row.original.price)}</span>
        ),
      },
      {
        accessorKey: "value",
        header: "Value",
        cell: ({ row }) => (
          <span className="font-mono text-text-secondary">{INR.format(row.original.value)}</span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: filteredRows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs">
      {/* Header */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-text-muted uppercase tracking-wider text-xs">TRADES</span>
          <span className="text-xs text-text-secondary font-mono">({counts.all})</span>
        </div>
        <div className="flex items-center gap-2">
          {lastFetch && (
            <span className="text-xs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="text-text-muted hover:text-text-primary disabled:opacity-40"
            aria-label="Refresh tradebook"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default shrink-0">
        <FilterPill value={FILTER_ALL} label="All" count={counts.all} activeFilter={filter} onClick={setFilter} />
        <FilterPill value={FILTER_BUY} label="Buy" count={counts.buy} activeFilter={filter} onClick={setFilter} />
        <FilterPill value={FILTER_SELL} label="Sell" count={counts.sell} activeFilter={filter} onClick={setFilter} />
      </div>

      {/* Body */}
      {filteredRows.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">No trades today</div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
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
