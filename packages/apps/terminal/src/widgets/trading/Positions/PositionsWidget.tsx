// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getPositionbook() call with usePositions() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table for sortable positions grid.
import { useMemo, useState, useCallback, memo } from "react";
import { Clock, Layers, FileDown, LogOut, Repeat, SquareX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { downloadExcel } from "@/services/ftApi.data";
import { post } from "@/services/ftApi.helpers";
import { placeOrder } from "@/services/api";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import { BrokerTargetSelect, useBrokerOrderTarget } from "@/widgets/orders/OrdersManagerShared";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import type { BrokerTarget } from "@/lib/brokerOrdersApi";
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
import type { RawPosition } from "@/types/rawApi";

interface PositionRow {
  symbol: string;
  exchange: string;
  product: string;
  qty: number;
  ltp: number;
  pnl: number;
}

/** Raw positionbook rows also carry exchange/product (used by Convert). */
type RawPositionRow = RawPosition & {
  exchange?: string | number;
  product?: string | number;
};

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** Position products supported by the convert verb (Indian F&O/equity). */
const PRODUCTS = ["MIS", "CNC", "NRML"] as const;

function formatPnl(pnl: number): string {
  return `${pnl >= 0 ? "+" : ""}₹${INR.format(Math.abs(pnl))}`;
}

// ---------------------------------------------------------------------------
// Convert-position dialog (gated convert_position verb)
// ---------------------------------------------------------------------------

interface ConvertPositionDialogProps {
  position: PositionRow;
  target: Required<BrokerTarget>;
  onClose: () => void;
  onConverted: () => void;
}

function ConvertPositionDialog({ position, target, onClose, onConverted }: ConvertPositionDialogProps) {
  const [toProduct, setToProduct] = useState<string>(position.product === "MIS" ? "CNC" : "MIS");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleConvert = useCallback(async () => {
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      // The backend signs the req object through the gated convert_position
      // verb; the field superset covers each adapter's expected names
      // (from/to_product, old/new_product, position_type, transaction_type).
      await post("positions/convert", {
        broker: target.broker,
        account_id: target.account_id,
        req: {
          symbol: position.symbol,
          exchange: position.exchange,
          quantity: Math.abs(position.qty),
          position_type: position.qty >= 0 ? "LONG" : "SHORT",
          transaction_type: position.qty >= 0 ? "BUY" : "SELL",
          product: position.product,
          from_product: position.product,
          old_product: position.product,
          to_product: toProduct,
          new_product: toProduct,
        },
      });
      emitNotification({
        category: "system",
        title: "Position conversion submitted",
        body: `${position.symbol}: ${position.product || "current product"} → ${toProduct}.`,
      });
      onConverted();
      onClose();
    } catch (err) {
      // Surface mode-guard 403s and broker rejections honestly — the backend
      // message tells the operator exactly what blocked the conversion.
      setErrorMsg(err instanceof Error ? err.message : "Position conversion failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [position, target, toProduct, onClose, onConverted]);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Convert position</DialogTitle>
          <DialogDescription>
            Change the product of {position.symbol} ({position.qty >= 0 ? "long" : "short"}{" "}
            {Math.abs(position.qty)}
            {position.product ? `, currently ${position.product}` : ""}). Converting a position
            changes its margin treatment with your broker.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="convert-to-product">Target product</Label>
          <Select value={toProduct} onValueChange={setToProduct}>
            <SelectTrigger id="convert-to-product" className="w-full">
              <SelectValue placeholder="Select product" />
            </SelectTrigger>
            <SelectContent>
              {PRODUCTS.filter((p) => p !== position.product).map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleConvert()}
            disabled={isSubmitting || !toProduct}
            aria-label={`Convert ${position.symbol} to ${toProduct}`}
          >
            {isSubmitting ? "Converting…" : "Convert"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Square-off dialog (per-position exit through the existing gated place path)
// ---------------------------------------------------------------------------

interface SquareOffDialogProps {
  position: PositionRow;
  onClose: () => void;
  onSquaredOff: () => void;
}

function SquareOffDialog({ position, onClose, onSquaredOff }: SquareOffDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const exitAction: "BUY" | "SELL" = position.qty > 0 ? "SELL" : "BUY";
  const exitQty = Math.abs(position.qty);
  // The counter-order must carry the position's own product, or the broker
  // opens a fresh position in a different product instead of squaring off.
  const product = (PRODUCTS as readonly string[]).includes(position.product)
    ? (position.product as (typeof PRODUCTS)[number])
    : null;

  const handleSquareOff = useCallback(async () => {
    if (!product) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      // Existing gated order path: SafetySystem → gate_order → BrokerRouter.
      // Identical route to the Order Pad — no new order path is introduced.
      await placeOrder({
        symbol: position.symbol,
        exchange: position.exchange,
        action: exitAction,
        product,
        orderType: "MARKET",
        quantity: exitQty,
        price: 0,
        triggerPrice: 0,
        strategy: "FlintPositions",
      });
      emitNotification({
        category: "order",
        title: "Square-off submitted",
        body: `${exitAction} ${exitQty} ${position.symbol} at market.`,
      });
      onSquaredOff();
      onClose();
    } catch (err) {
      // Surface mode-guard 403s and broker rejections honestly — the backend
      // message tells the operator exactly what blocked the square-off.
      setErrorMsg(err instanceof Error ? err.message : "Square-off failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [position, product, exitAction, exitQty, onClose, onSquaredOff]);

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Square off position?</DialogTitle>
          <DialogDescription>
            This places a {exitAction} market order for {exitQty} {position.symbol} (
            {position.exchange}
            {position.product ? `, ${position.product}` : ""}) to close your{" "}
            {position.qty > 0 ? "long" : "short"} position. Fills in a fast market can land far
            from the last traded price, and the action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {!product && (
          <p className="text-xs text-loss" role="alert">
            Cannot square off: unrecognised product
            {position.product ? ` “${position.product}”` : ""} on this position. Close it from your
            broker terminal instead.
          </p>
        )}
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSquareOff()}
            disabled={isSubmitting || !product}
            aria-label={`Confirm square off ${position.symbol}`}
            className="bg-loss hover:bg-loss/90 text-white"
          >
            {isSubmitting ? "Squaring off…" : `${exitAction} ${exitQty} at market`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Exit-all dialog (gated exit_all_positions verb — typed confirmation)
// ---------------------------------------------------------------------------

interface ExitAllDialogProps {
  open: boolean;
  positionCount: number;
  target: Required<BrokerTarget>;
  onOpenChange: (open: boolean) => void;
  onExited: () => void;
}

function ExitAllDialog({ open, positionCount, target, onOpenChange, onExited }: ExitAllDialogProps) {
  const [confirmText, setConfirmText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const confirmed = confirmText.trim() === "EXIT";

  const close = useCallback(
    (next: boolean) => {
      if (!next) {
        setConfirmText("");
        setErrorMsg(null);
      }
      onOpenChange(next);
    },
    [onOpenChange],
  );

  const handleExitAll = useCallback(async () => {
    if (!confirmed) return;
    setIsSubmitting(true);
    setErrorMsg(null);
    try {
      await post("positions/exit-all", {
        confirm: true,
        broker: target.broker,
        account_id: target.account_id,
      });
      emitNotification({
        category: "system",
        title: "Exit-all submitted",
        body: "Every open position is being squared off at market.",
      });
      onExited();
      close(false);
    } catch (err) {
      // Mode-guard 403s ("live mode only", PIN unlock) and broker errors are
      // shown verbatim — never a generic failure.
      setErrorMsg(err instanceof Error ? err.message : "Exit-all positions failed.");
    } finally {
      setIsSubmitting(false);
    }
  }, [confirmed, target, onExited, close]);

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Exit all positions?</DialogTitle>
          <DialogDescription>
            This squares off EVERY open position ({positionCount}) in your live broker account at
            market price. Fills in a fast market can land far from the last traded price, and the
            action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5">
          <Label htmlFor="exit-all-confirm">Type EXIT (in capitals) to confirm</Label>
          <Input
            id="exit-all-confirm"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="EXIT"
            autoComplete="off"
          />
        </div>
        {errorMsg && (
          <p className="text-xs text-loss" role="alert">
            {errorMsg}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleExitAll()}
            disabled={!confirmed || isSubmitting}
            aria-label="Confirm exit all positions"
            className="bg-loss hover:bg-loss/90 text-white"
          >
            {isSubmitting ? "Exiting…" : "Exit all positions"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PositionsWidget(_props: WidgetProps) {
  const appMode = useModeStore((s) => s.mode);
  const isBrokerConnected = useBrokerConnected();
  const accountReadsEnabled = resolveAccountReadsEnabled(appMode, isBrokerConnected);
  const canWritePositions = isBrokerConnected && appMode === "live";
  const { data: positionsData, dataUpdatedAt, isError, error, refetch, isFetching } = usePositions({
    enabled: accountReadsEnabled,
  });
  const [sorting, setSorting] = useState<SortingState>([]);
  const [convertTarget, setConvertTarget] = useState<PositionRow | null>(null);
  const [squareOffTarget, setSquareOffTarget] = useState<PositionRow | null>(null);
  const [exitAllOpen, setExitAllOpen] = useState(false);
  // Broker/account target for the gated convert + exit-all verbs. The OpenAlgo
  // bridge implements NEITHER verb (it would 501), so the operator picks a
  // native account (Dhan/Upstox/…) here, mirroring the orders widgets.
  const [brokerTarget, setBrokerTarget] = useBrokerOrderTarget(appMode);

  const rows = useMemo<PositionRow[]>(() => {
    const raw = (positionsData ?? []) as RawPositionRow[];
    return raw.map((p) => ({
      symbol: p.symbol,
      exchange: String(p.exchange ?? ""),
      product: String(p.product ?? ""),
      qty: parseInt(String(p.quantity ?? 0), 10),
      ltp: parseFloat(String(p.ltp ?? 0)),
      pnl: parseFloat(String(p.pnl ?? 0)),
    }));
  }, [positionsData]);

  const totalPnl = useMemo(() => rows.reduce((s, r) => s + r.pnl, 0), [rows]);

  const [isExporting, setIsExporting] = useState(false);

  const handleExport = useCallback(async () => {
    if (rows.length === 0) return;
    setIsExporting(true);
    try {
      const count = await downloadExcel(
        rows as unknown as Record<string, unknown>[],
        "Positions",
        "positions.xlsx",
      );
      emitNotification({
        category: "system",
        title: "Positions exported",
        body: `Downloaded ${count} position${count === 1 ? "" : "s"} to positions.xlsx.`,
      });
    } catch (err) {
      emitNotification({
        category: "alert",
        title: "Export failed",
        body: err instanceof Error ? err.message : "Could not export positions to Excel.",
      });
    } finally {
      setIsExporting(false);
    }
  }, [rows]);

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
      {
        id: "actions",
        header: "",
        enableSorting: false,
        cell: ({ row }) => canWritePositions ? (
          <span className="inline-flex items-center gap-0.5">
            {row.original.qty !== 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setSquareOffTarget(row.original)}
                aria-label={`Square off ${row.original.symbol}`}
                title={`Square off ${row.original.symbol} at market`}
                className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
              >
                <SquareX size={10} aria-hidden="true" /> Square off
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setConvertTarget(row.original)}
              aria-label={`Convert ${row.original.symbol}`}
              title={`Convert ${row.original.symbol} to another product`}
              className="h-5 px-1.5 text-xxs gap-1 text-text-muted hover:text-text-primary"
            >
              <Repeat size={10} aria-hidden="true" /> Convert
            </Button>
          </span>
        ) : (
          <span className="text-xxs text-text-muted">Live only</span>
        ),
      },
    ],
    [canWritePositions],
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
          {!accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live positions"
            >
              Broker required
            </span>
          )}
          {accountReadsEnabled && appMode !== "live" && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-surface-hover text-text-muted border border-border-subtle rounded"
              role="status"
              aria-label="Position management actions require Live mode"
            >
              Read-only
            </span>
          )}
          {/* Convert + Exit-all are gated native-broker verbs; pick the target
              account here (the OpenAlgo bridge implements neither). */}
          {canWritePositions && rows.length > 0 && (
            <BrokerTargetSelect value={brokerTarget} onChange={setBrokerTarget} />
          )}
          <span className={`font-mono tabular-nums font-medium ${totalPnl >= 0 ? "text-profit" : "text-loss"}`}>
            P&L: {formatPnl(totalPnl)}
          </span>
          {lastFetch && (
            <span className="text-xxs text-text-muted flex items-center gap-0.5">
              <Clock size={8} />
              {lastFetch.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
            </span>
          )}
          {accountReadsEnabled && rows.length > 0 && (
            <button
              type="button"
              onClick={() => void handleExport()}
              disabled={isExporting}
              aria-label="Export positions to Excel"
              title="Export positions to Excel"
              className="text-text-muted hover:text-text-primary transition-colors disabled:opacity-40"
            >
              <FileDown size={12} className={isExporting ? "animate-pulse" : ""} />
            </button>
          )}
          {canWritePositions && rows.length > 0 && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setExitAllOpen(true)}
              aria-label="Exit all positions"
              title="Square off every open position at market"
              className="h-5 px-1.5 text-xxs gap-1 text-loss hover:bg-loss/10 hover:text-loss"
            >
              <LogOut size={10} aria-hidden="true" /> Exit all…
            </Button>
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
          <span className="text-sm">
            {accountReadsEnabled ? "No open positions" : "Connect a broker to load positions"}
          </span>
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

      {/* Convert-position dialog — keyed so state resets per position */}
      {convertTarget && (
        <ConvertPositionDialog
          key={`${convertTarget.symbol}-${convertTarget.exchange}-${convertTarget.product}`}
          position={convertTarget}
          target={brokerTarget}
          onClose={() => setConvertTarget(null)}
          onConverted={() => void refetch()}
        />
      )}

      {/* Per-position square-off confirmation — keyed so state resets per position */}
      {squareOffTarget && (
        <SquareOffDialog
          key={`${squareOffTarget.symbol}-${squareOffTarget.exchange}-${squareOffTarget.product}-${squareOffTarget.qty}`}
          position={squareOffTarget}
          onClose={() => setSquareOffTarget(null)}
          onSquaredOff={() => void refetch()}
        />
      )}

      {/* Exit-all typed-confirmation dialog */}
      <ExitAllDialog
        open={exitAllOpen}
        positionCount={rows.length}
        target={brokerTarget}
        onOpenChange={setExitAllOpen}
        onExited={() => void refetch()}
      />
    </div>
  );
}

export default memo(PositionsWidget);
