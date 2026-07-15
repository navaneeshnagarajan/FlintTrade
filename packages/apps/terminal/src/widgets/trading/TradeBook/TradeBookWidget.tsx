// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getTradebook() call with useTradebook() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table + shadcn Badge for BUY/SELL side badges.
import { useMemo, useState, memo } from "react";
import { Clock, RefreshCw, ArrowRightLeft } from "lucide-react";
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
import { Badge } from "@/components/ui/badge";
import { useTradebook } from "@/hooks/useTradebook";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import type { WidgetProps } from "@/types/widgets";
import type { RawTrade } from "@/types/rawApi";

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

function TradeBookWidget(_props: WidgetProps) {
  const accountReadsEnabled = useAccountReadsEnabled();
  const {
    data: tradesData,
    dataUpdatedAt,
    refetch,
    isFetching,
    isError,
    error,
  } = useTradebook({ enabled: accountReadsEnabled });
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
          <span className="font-mono tabular-nums text-text-muted whitespace-nowrap">{row.original.timeDisplay}</span>
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
          <span className="font-mono tabular-nums">{row.original.qty}</span>
        ),
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-primary">{INR.format(row.original.price)}</span>
        ),
      },
      {
        accessorKey: "value",
        header: "Value",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{INR.format(row.original.value)}</span>
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
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">Trades</span>
          <span className="text-xxs text-text-secondary font-mono tabular-nums">({counts.all})</span>
        </div>
        <div className="flex items-center gap-2">
          {!accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live trade book"
            >
              Broker required
            </span>
          )}
          {lastFetch && (
            <span className="text-xxs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          {accountReadsEnabled && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="h-auto w-auto p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
              aria-label="Refresh tradebook"
            >
              <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
            </Button>
          )}
        </div>
      </div>

      {/* Filter pills */}
      <div className="flex items-center gap-1.5 px-3 py-1 border-b border-border-default shrink-0">
        <FilterPill value={FILTER_ALL} label="All" count={counts.all} activeFilter={filter} onClick={setFilter} />
        <FilterPill value={FILTER_BUY} label="Buy" count={counts.buy} activeFilter={filter} onClick={setFilter} />
        <FilterPill value={FILTER_SELL} label="Sell" count={counts.sell} activeFilter={filter} onClick={setFilter} />
      </div>

      {/* Error banner — a failed fetch must never masquerade as "No trades today" */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load trades{error instanceof Error ? `: ${error.message}` : ""}
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
      {filteredRows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <ArrowRightLeft size={24} className="text-text-disabled" />
          <span className="text-sm">
            {!accountReadsEnabled
              ? "Connect a broker to load trades"
              : isError
                ? "Trade book unavailable — retry above"
                : "No trades today"}
          </span>
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 bg-surface-card z-10">
              {table.getHeaderGroups().map((hg) => (
                <TableRow key={hg.id}>
                  {hg.headers.map((header) => (
                    <TableHead
                      key={header.id}
                      className={`text-xxs text-text-muted uppercase tracking-wider cursor-pointer select-none px-2 py-1 ${
                        header.id === "qty" || header.id === "price" || header.id === "value" ? "text-right" : ""
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
                      className={`px-2 py-1 ${
                        cell.column.id === "qty" || cell.column.id === "price" || cell.column.id === "value" ? "text-right" : ""
                      }`}
                    >
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

export default memo(TradeBookWidget);
