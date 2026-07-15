// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getHoldings() / getMultiQuotes() calls with useHoldings() hook.
// PRESERVED: retry:false in useHoldings to suppress errors for brokers without holdings API.
// Uses TanStack Table v8 + shadcn Table; search + sort are client-side derived state.
import { useMemo, useState, useCallback, memo } from "react";
import { Clock, Search, RefreshCw, Briefcase, FileSpreadsheet } from "lucide-react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
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
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useHoldings } from "@/hooks/useHoldings";
import { usePositions } from "@/hooks/usePositions";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { downloadPortfolioReport } from "@/services/ftApi.data";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import type { WidgetProps } from "@/types/widgets";
import type { RawHolding, RawPosition } from "@/types/rawApi";

interface HoldingRow {
  symbol: string;
  qty: number;
  avgPrice: number;
  ltp: number;
  currentVal: number;
  pnl: number;
  pnlPct: number;
}

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function formatPnl(pnl: number): string {
  return `${pnl >= 0 ? "+" : ""}₹${INR.format(Math.abs(pnl))}`;
}

function resolveSymbol(h: RawHolding): string {
  return ((h.symbol ?? h.tradingsymbol) || "").toUpperCase();
}

function resolveLtp(h: RawHolding): number {
  if (h.ltp) return parseFloat(String(h.ltp));
  if (h.close_price) return parseFloat(String(h.close_price));
  return parseFloat(String(h.average_price ?? h.avg_price ?? 0));
}

function HoldingsWidget(_props: WidgetProps) {
  // retry:false preserved — some brokers don't have a holdings endpoint
  const accountReadsEnabled = useAccountReadsEnabled();
  const { data: holdingsData, dataUpdatedAt, refetch, isFetching, isError, error } = useHoldings({
    enabled: accountReadsEnabled,
  });
  const [sorting, setSorting] = useState<SortingState>([{ id: "symbol", desc: false }]);
  const [globalFilter, setGlobalFilter] = useState("");

  const rows = useMemo<HoldingRow[]>(() => {
    const raw = (holdingsData ?? []) as RawHolding[];
    return raw.map((h) => {
      const qty = parseInt(String(h.quantity ?? h.qty ?? 0), 10);
      const avgPrice = parseFloat(String(h.average_price ?? h.avg_price ?? 0));
      const ltp = resolveLtp(h);
      const invested = qty * avgPrice;
      const currentVal = qty * ltp;
      const pnl = currentVal - invested;
      const pnlPct = invested > 0 ? (pnl / invested) * 100 : 0;
      return { symbol: resolveSymbol(h), qty, avgPrice, ltp, currentVal, pnl, pnlPct };
    });
  }, [holdingsData]);

  const totals = useMemo(
    () => ({
      invested: rows.reduce((s, r) => s + r.qty * r.avgPrice, 0),
      currentVal: rows.reduce((s, r) => s + r.currentVal, 0),
      pnl: rows.reduce((s, r) => s + r.pnl, 0),
    }),
    [rows],
  );

  const lastFetch = dataUpdatedAt ? new Date(dataUpdatedAt) : null;

  // Positions are fetched so the portfolio report can span both books.
  const { data: positionsData } = usePositions({ enabled: accountReadsEnabled });
  const [isExporting, setIsExporting] = useState(false);

  const handlePortfolioReport = useCallback(async () => {
    const posRows = ((positionsData ?? []) as RawPosition[]).map((p) => ({
      symbol: p.symbol,
      qty: parseInt(String(p.quantity ?? 0), 10),
      ltp: parseFloat(String(p.ltp ?? 0)),
      pnl: parseFloat(String(p.pnl ?? 0)),
    }));
    if (posRows.length === 0 && rows.length === 0) {
      emitNotification({
        category: "alert",
        title: "Nothing to export",
        body: "No positions or holdings to include in the report.",
      });
      return;
    }
    setIsExporting(true);
    try {
      const total = await downloadPortfolioReport(
        posRows as unknown as Record<string, unknown>[],
        rows as unknown as Record<string, unknown>[],
        "portfolio.xlsx",
      );
      emitNotification({
        category: "system",
        title: "Portfolio report exported",
        body: `Downloaded ${total} row${total === 1 ? "" : "s"} (positions + holdings) to portfolio.xlsx.`,
      });
    } catch (err) {
      emitNotification({
        category: "alert",
        title: "Report export failed",
        body: err instanceof Error ? err.message : "Could not export the portfolio report.",
      });
    } finally {
      setIsExporting(false);
    }
  }, [positionsData, rows]);

  const columns = useMemo<ColumnDef<HoldingRow>[]>(
    () => [
      {
        accessorKey: "symbol",
        header: "Symbol",
        cell: ({ row }) => (
          <span className="font-mono font-medium text-left">{row.original.symbol}</span>
        ),
      },
      {
        accessorKey: "qty",
        header: "Qty",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{row.original.qty}</span>
        ),
      },
      {
        accessorKey: "avgPrice",
        header: "Avg",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{INR.format(row.original.avgPrice)}</span>
        ),
      },
      {
        accessorKey: "ltp",
        header: "LTP",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-primary">{INR.format(row.original.ltp)}</span>
        ),
      },
      {
        accessorKey: "currentVal",
        header: "Value",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums text-text-secondary">{INR.format(row.original.currentVal)}</span>
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
      {
        accessorKey: "pnlPct",
        header: "P&L%",
        cell: ({ row }) => (
          <span
            className={`font-mono tabular-nums font-medium ${
              row.original.pnlPct >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            {row.original.pnlPct >= 0 ? "+" : ""}
            {row.original.pnlPct.toFixed(2)}%
          </span>
        ),
      },
    ],
    [],
  );

  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">Holdings</span>
          <span className="text-xxs text-text-secondary font-mono tabular-nums">({rows.length})</span>
          {!accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live holdings"
            >
              Broker required
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono tabular-nums text-xs text-text-secondary">
            Inv: ₹{INR.format(totals.invested)}
          </span>
          <span className="font-mono tabular-nums text-xs text-text-secondary">
            Val: ₹{INR.format(totals.currentVal)}
          </span>
          <span
            className={`font-mono tabular-nums text-xs font-medium ${
              totals.pnl >= 0 ? "text-profit" : "text-loss"
            }`}
          >
            P&L: {formatPnl(totals.pnl)}
          </span>
          {lastFetch && (
            <span className="text-xxs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          {accountReadsEnabled && (
            <>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => void handlePortfolioReport()}
                disabled={isExporting}
                className="h-auto w-auto p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
                aria-label="Export portfolio report to Excel"
                title="Export a Positions + Holdings + Summary Excel report"
              >
                <FileSpreadsheet size={11} className={isExporting ? "animate-pulse" : ""} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => void refetch()}
                disabled={isFetching}
                className="h-auto w-auto p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
                aria-label="Refresh holdings"
              >
                <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="px-3 py-1 border-b border-border-default shrink-0">
        <div className="flex items-center gap-1 bg-surface-card rounded px-1.5 py-0.5">
          <Search size={10} className="text-text-muted shrink-0" />
          <Input
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value.toUpperCase())}
            placeholder="Filter symbol…"
            className="bg-transparent border-none shadow-none h-auto p-0 text-xs font-mono text-text-primary placeholder:text-text-muted focus-visible:ring-0"
          />
        </div>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load holdings{error instanceof Error ? `: ${error.message}` : ""}
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
      {table.getRowModel().rows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <Briefcase size={24} className="text-text-disabled" />
          <span className="text-sm">
            {!accountReadsEnabled
              ? "Connect a broker to load holdings"
              : rows.length === 0
                ? "No holdings"
                : "No matches"}
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
                      className={`text-xxs text-text-muted uppercase tracking-wider cursor-pointer select-none whitespace-nowrap px-2 py-1 ${
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
                      className={`px-2 py-1 ${cell.column.id !== "symbol" ? "text-right" : ""}`}
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

export default memo(HoldingsWidget);
