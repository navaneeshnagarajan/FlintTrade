// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getOrderbook() call with useOrders() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table + shadcn Badge for status.
// Open orders carry per-order Cancel and Modify actions wired to the REAL
// broker order id through the existing gated cancel/modify routes.
import { useMemo, useState, useEffect, useCallback, memo } from "react";
import { RefreshCw, FileText, X, Pencil, Loader2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { useModeStore } from "@/stores/modeStore";
import { cancelOrder, modifyOrder } from "@/services/api";
import { queryKeys } from "@/services/queryKeys";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import type { ModifyOrderParams } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import type { RawOrder } from "@/types/rawApi";

/** Raw orderbook row with the id/field aliases brokers actually send. */
interface RawOrderRecord extends RawOrder {
  orderid?: string;
  exchange?: string;
  product?: string;
  pricetype?: string;
  price_type?: string;
  trigger_price?: string | number;
  strategy?: string;
}

interface OrderRow {
  /** Real broker order id — null when the broker sent none (actions disabled). */
  orderId: string | null;
  symbol: string;
  exchange: string;
  action: string;
  quantity: string;
  quantityNum: number;
  price: string;
  priceNum: number;
  triggerPriceNum: number;
  orderType: string;
  product: string;
  strategy: string;
  orderStatus: string;
  isOpen: boolean;
}

const VALID_ORDER_TYPES = new Set(["MARKET", "LIMIT", "SL", "SL-M"]);
const VALID_PRODUCTS = new Set(["MIS", "CNC", "NRML"]);
const VALID_ACTIONS = new Set(["BUY", "SELL"]);

function statusVariant(
  status: string,
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "complete") return "default";
  if (status === "rejected") return "destructive";
  return "secondary";
}

/** Whether a broker order status still allows cancel/modify. */
export function isOpenOrderStatus(status: string): boolean {
  const s = status.toLowerCase();
  return s.includes("open") || s.includes("pending");
}

function extractOrderId(o: RawOrderRecord): string | null {
  const candidate = o.orderid ?? o.orderId ?? o.order_id;
  if (typeof candidate === "string" && candidate.trim() !== "") return candidate;
  if (typeof candidate === "number") return String(candidate);
  return null;
}

function toNum(value: string | number | undefined): number {
  const n = typeof value === "number" ? value : parseFloat(String(value ?? ""));
  return Number.isFinite(n) ? n : 0;
}

/**
 * A row qualifies for Modify only when every field the gated modify route
 * requires is present and valid — otherwise the request would be rejected
 * (or worse, mis-normalised). Fail closed.
 */
function canModify(row: OrderRow): boolean {
  return (
    row.orderId != null &&
    row.isOpen &&
    row.symbol !== "" &&
    row.exchange !== "" &&
    VALID_ACTIONS.has(row.action) &&
    VALID_ORDER_TYPES.has(row.orderType) &&
    VALID_PRODUCTS.has(row.product)
  );
}

// ─── Cancel confirmation overlay ─────────────────────────────────────────────

interface CancelConfirmProps {
  row: OrderRow;
  pending: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

function CancelConfirmOverlay({ row, pending, onConfirm, onClose }: CancelConfirmProps) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirm order cancellation"
      className="absolute inset-0 z-20 flex items-center justify-center bg-surface-base/80 backdrop-blur-sm"
    >
      <div className="bg-surface-card border border-border-default rounded-lg p-4 min-w-64 max-w-80 shadow-2xl">
        <div className="text-sm font-heading font-bold text-text-primary mb-2">Cancel order?</div>
        <p className="text-xs text-text-secondary mb-3">
          {row.action} {row.quantity} {row.symbol} ({row.orderType}) · ID{" "}
          <span className="font-mono">{row.orderId}</span>
        </p>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={onConfirm}
            disabled={pending}
            className="flex-1 h-8 text-sm font-semibold bg-loss hover:bg-loss/85 text-white"
          >
            {pending ? <Loader2 size={12} className="animate-spin" /> : null}
            {pending ? "Cancelling…" : "Cancel Order"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={pending}
            className="flex-1 h-8 text-sm font-medium bg-surface-hover text-text-secondary border-border-default"
          >
            Keep Order
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Modify overlay ──────────────────────────────────────────────────────────

interface ModifyOverlayProps {
  row: OrderRow;
  pending: boolean;
  onSubmit: (qty: number, price: number, triggerPrice: number) => void;
  onClose: () => void;
}

function ModifyOverlay({ row, pending, onSubmit, onClose }: ModifyOverlayProps) {
  const [qty, setQty] = useState(String(row.quantityNum > 0 ? row.quantityNum : 1));
  const [price, setPrice] = useState(row.priceNum > 0 ? String(row.priceNum) : "");
  const [trigger, setTrigger] = useState(row.triggerPriceNum > 0 ? String(row.triggerPriceNum) : "");
  const [error, setError] = useState<string | null>(null);

  const priceRequired = row.orderType === "LIMIT" || row.orderType === "SL";
  const triggerRequired = row.orderType === "SL" || row.orderType === "SL-M";

  function handleSubmit(): void {
    const qtyNum = parseInt(qty, 10);
    const priceNum = parseFloat(price) || 0;
    const triggerNum = parseFloat(trigger) || 0;
    if (!Number.isFinite(qtyNum) || qtyNum < 1) {
      setError("Quantity must be at least 1");
      return;
    }
    if (priceRequired && priceNum <= 0) {
      setError("A price above 0 is required for this order type");
      return;
    }
    if (triggerRequired && triggerNum <= 0) {
      setError("A trigger price above 0 is required for this order type");
      return;
    }
    setError(null);
    onSubmit(qtyNum, priceNum, triggerNum);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Modify order"
      className="absolute inset-0 z-20 flex items-center justify-center bg-surface-base/80 backdrop-blur-sm"
    >
      <div className="bg-surface-card border border-border-default rounded-lg p-4 min-w-64 max-w-80 shadow-2xl">
        <div className="text-sm font-heading font-bold text-text-primary mb-1">Modify order</div>
        <p className="text-xs text-text-muted mb-3">
          {row.action} {row.symbol} ({row.orderType} · {row.product}) · ID{" "}
          <span className="font-mono">{row.orderId}</span>
        </p>
        <div className="space-y-2 mb-3">
          <div className="flex flex-col gap-0.5">
            <label htmlFor="orders-modify-qty" className="text-xxs text-text-muted uppercase tracking-wider">
              Quantity
            </label>
            <Input
              id="orders-modify-qty"
              type="number"
              min={1}
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              className="h-8 text-xs font-mono"
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <label htmlFor="orders-modify-price" className="text-xxs text-text-muted uppercase tracking-wider">
              Price
            </label>
            <Input
              id="orders-modify-price"
              type="number"
              min={0}
              step="0.05"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              disabled={!priceRequired}
              placeholder={priceRequired ? "0.00" : "N/A"}
              className="h-8 text-xs font-mono"
            />
          </div>
          <div className="flex flex-col gap-0.5">
            <label htmlFor="orders-modify-trigger" className="text-xxs text-text-muted uppercase tracking-wider">
              Trigger Price
            </label>
            <Input
              id="orders-modify-trigger"
              type="number"
              min={0}
              step="0.05"
              value={trigger}
              onChange={(e) => setTrigger(e.target.value)}
              disabled={!triggerRequired}
              placeholder={triggerRequired ? "0.00" : "N/A"}
              className="h-8 text-xs font-mono"
            />
          </div>
        </div>
        {error && (
          <p role="alert" className="text-xs text-loss mb-2">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={handleSubmit}
            disabled={pending}
            className="flex-1 h-8 text-sm font-semibold bg-accent hover:bg-accent/85 text-white"
          >
            {pending ? <Loader2 size={12} className="animate-spin" /> : null}
            {pending ? "Modifying…" : "Modify Order"}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={pending}
            className="flex-1 h-8 text-sm font-medium bg-surface-hover text-text-secondary border-border-default"
          >
            Close
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Main widget ─────────────────────────────────────────────────────────────

function OrdersWidget(_props: WidgetProps) {
  const accountReadsEnabled = useAccountReadsEnabled();
  const isExplore = useModeStore((s) => s.mode === "explore");
  const { data: ordersData, refetch, isFetching, isError, error } = useOrders({ enabled: accountReadsEnabled });
  const queryClient = useQueryClient();
  const [sorting, setSorting] = useState<SortingState>([]);
  const track = useTrackBehavior();

  const [cancelTarget, setCancelTarget] = useState<OrderRow | null>(null);
  const [modifyTarget, setModifyTarget] = useState<OrderRow | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const rows = useMemo<OrderRow[]>(() => {
    const raw = (ordersData ?? []) as RawOrderRecord[];
    return raw.map((o) => {
      const status = o.order_status ?? o.status ?? "—";
      const orderType = String(o.pricetype ?? o.price_type ?? "").toUpperCase();
      return {
        orderId: extractOrderId(o),
        symbol: o.symbol,
        exchange: o.exchange ?? "",
        action: (o.action ?? "—").toUpperCase(),
        quantity: String(o.quantity ?? ""),
        quantityNum: toNum(o.quantity),
        price: o.price ? String(o.price) : "MKT",
        priceNum: toNum(o.price),
        triggerPriceNum: toNum(o.trigger_price),
        orderType,
        product: String(o.product ?? "").toUpperCase(),
        strategy: typeof o.strategy === "string" && o.strategy !== "" ? o.strategy : "Flint",
        orderStatus: status,
        isOpen: isOpenOrderStatus(status),
      };
    });
  }, [ordersData]);

  useEffect(() => {
    if (rows.length > 0) track("trade", "ordersPlaced");
  }, [rows.length, track]);

  const refreshOrders = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.orders.all });
  }, [queryClient]);

  const handleCancelConfirm = useCallback(async () => {
    // Fail closed — never send a cancel without the real broker order id.
    if (!cancelTarget || cancelTarget.orderId == null) return;
    setActionPending(true);
    setActionError(null);
    try {
      await cancelOrder(cancelTarget.orderId, cancelTarget.strategy);
      emitNotification({
        category: "order",
        title: `Order cancelled: ${cancelTarget.action} ${cancelTarget.symbol}`,
        body: `Order ID ${cancelTarget.orderId}`,
      });
      setCancelTarget(null);
      refreshOrders();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Cancel failed");
      setCancelTarget(null);
    } finally {
      setActionPending(false);
    }
  }, [cancelTarget, refreshOrders]);

  const handleModifySubmit = useCallback(
    async (qty: number, price: number, triggerPrice: number) => {
      if (!modifyTarget || modifyTarget.orderId == null || !canModify(modifyTarget)) return;
      setActionPending(true);
      setActionError(null);
      const params: ModifyOrderParams = {
        orderId: modifyTarget.orderId,
        symbol: modifyTarget.symbol,
        exchange: modifyTarget.exchange,
        action: modifyTarget.action as "BUY" | "SELL",
        quantity: qty,
        orderType: modifyTarget.orderType as "MARKET" | "LIMIT" | "SL" | "SL-M",
        product: modifyTarget.product as "MIS" | "CNC" | "NRML",
        price,
        triggerPrice,
        strategy: modifyTarget.strategy,
      };
      try {
        await modifyOrder(params);
        emitNotification({
          category: "order",
          title: `Order modified: ${params.action} ${qty} ${params.symbol}`,
          body: `Order ID ${params.orderId}`,
        });
        setModifyTarget(null);
        refreshOrders();
      } catch (err) {
        setActionError(err instanceof Error ? err.message : "Modify failed");
        setModifyTarget(null);
      } finally {
        setActionPending(false);
      }
    },
    [modifyTarget, refreshOrders],
  );

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
          <span className="font-mono tabular-nums">{row.original.quantity}</span>
        ),
      },
      {
        accessorKey: "price",
        header: "Price",
        cell: ({ row }) => (
          <span className="font-mono tabular-nums">{row.original.price}</span>
        ),
      },
      {
        accessorKey: "orderStatus",
        header: "Status",
        cell: ({ row }) => (
          <Badge
            variant={statusVariant(row.original.orderStatus)}
            className="text-xs font-medium"
          >
            {row.original.orderStatus}
          </Badge>
        ),
      },
      {
        id: "actions",
        header: "Actions",
        enableSorting: false,
        cell: ({ row }) => {
          const r = row.original;
          if (!r.isOpen) return null;
          const idMissing = r.orderId == null;
          const disabledReason = isExplore
            ? "Connect a broker to manage orders"
            : idMissing
              ? "Broker did not return an order id"
              : undefined;
          return (
            <span className="flex items-center gap-1.5 justify-end">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => { setActionError(null); setModifyTarget(r); }}
                disabled={isExplore || actionPending || !canModify(r)}
                title={
                  disabledReason ??
                  (!canModify(r) ? "Order details incomplete — modify from your broker app" : `Modify order ${r.orderId}`)
                }
                aria-label={`Modify order ${r.orderId ?? r.symbol}`}
                className="h-auto w-auto p-0.5 text-text-muted hover:text-accent disabled:opacity-40"
              >
                <Pencil size={12} />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => { setActionError(null); setCancelTarget(r); }}
                disabled={isExplore || actionPending || idMissing}
                title={disabledReason ?? `Cancel order ${r.orderId}`}
                aria-label={`Cancel order ${r.orderId ?? r.symbol}`}
                className="h-auto w-auto p-0.5 text-text-muted hover:text-loss disabled:opacity-40"
              >
                <X size={12} />
              </Button>
            </span>
          );
        },
      },
    ],
    [isExplore, actionPending],
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
    <div className="relative h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Cancel confirmation */}
      {cancelTarget && (
        <CancelConfirmOverlay
          row={cancelTarget}
          pending={actionPending}
          onConfirm={() => void handleCancelConfirm()}
          onClose={() => setCancelTarget(null)}
        />
      )}

      {/* Modify dialog */}
      {modifyTarget && (
        <ModifyOverlay
          row={modifyTarget}
          pending={actionPending}
          onSubmit={(qty, price, trigger) => void handleModifySubmit(qty, price, trigger)}
          onClose={() => setModifyTarget(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">
          Orders{rows.length > 0 ? ` (${rows.length})` : ""}
        </span>
        <div className="flex items-center gap-2">
          {!accountReadsEnabled && (
            <span
              className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
              role="status"
              aria-label="Broker connection required for live orders"
            >
              Broker required
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
              aria-label="Refresh orders"
            >
              <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
            </Button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss">
          <span className="flex-1">
            Failed to load orders{error instanceof Error ? `: ${error.message}` : ""}
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

      {/* Cancel/modify failure banner */}
      {actionError && (
        <div
          role="alert"
          className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss"
        >
          <span className="flex-1">{actionError}</span>
          <Button
            variant="link"
            size="sm"
            onClick={() => setActionError(null)}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80"
          >
            Dismiss
          </Button>
        </div>
      )}

      {/* Body */}
      {rows.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <FileText size={24} className="text-text-disabled" />
          <span className="text-sm">
            {accountReadsEnabled ? "No orders today" : "Connect a broker to load orders"}
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
                        header.id === "quantity" || header.id === "price" || header.id === "actions" ? "text-right" : ""
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
                      className={`px-2 py-1 whitespace-nowrap ${
                        cell.column.id === "quantity" || cell.column.id === "price" || cell.column.id === "actions" ? "text-right" : ""
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
        </div>
      )}
    </div>
  );
}

export default memo(OrdersWidget);
