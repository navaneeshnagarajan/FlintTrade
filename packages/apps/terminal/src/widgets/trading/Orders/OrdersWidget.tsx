// Migrated to TSX — Phase 4 Batch 1
// Replaces direct getOrderbook() call with useOrders() TanStack Query hook.
// Uses TanStack Table v8 + shadcn Table + shadcn Badge for status.
// Open orders carry per-order Cancel and Modify actions wired to the REAL
// broker order id through the existing gated cancel/modify routes.
import { useMemo, useState, useEffect, useCallback, useRef, memo } from "react";
import { RefreshCw, FileText, X, Pencil, Loader2 } from "lucide-react";
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
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";
import {
  accountAuthorityMatches,
  captureAccountAuthority,
  resolveAccountQueryUi,
  runGuardedAccountRefetch,
  runWithMatchingAccountAuthority,
} from "@/lib/accountQueryState";
import { cancelOrder, modifyOrder } from "@/services/api";
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
  triggerPrice?: string | number;
  triggerprice?: string | number;
  disclosed_quantity?: string | number;
  disclosedQuantity?: string | number;
  disclosedqty?: string | number;
  disclosed_qty?: string | number;
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
  disclosedQuantityNum: number;
  hasDisclosedQuantity: boolean;
  orderType: string;
  product: string;
  strategy: string;
  orderStatus: string;
  isOpen: boolean;
}

interface OrderActionIntent {
  row: OrderRow;
  identity: AccountAuthorityIdentity;
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

function firstPresentValue(
  ...values: Array<string | number | undefined>
): string | number | undefined {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    if (String(value).trim() === "") continue;
    return value;
  }
  return undefined;
}

/** Map a raw orderbook row, preserving trigger and disclosed-quantity aliases. */
export function toOrderRow(o: RawOrderRecord): OrderRow {
  const status = o.order_status ?? o.status ?? "—";
  const orderType = String(o.pricetype ?? o.price_type ?? "").toUpperCase();
  const disclosed = firstPresentValue(
    o.disclosed_quantity,
    o.disclosedQuantity,
    o.disclosedqty,
    o.disclosed_qty,
  );
  return {
    orderId: extractOrderId(o),
    symbol: o.symbol,
    exchange: o.exchange ?? "",
    action: (o.action ?? "—").toUpperCase(),
    quantity: String(o.quantity ?? ""),
    quantityNum: toNum(o.quantity),
    price: o.price ? String(o.price) : "MKT",
    priceNum: toNum(o.price),
    triggerPriceNum: toNum(firstPresentValue(o.trigger_price, o.triggerPrice, o.triggerprice)),
    disclosedQuantityNum: toNum(disclosed),
    hasDisclosedQuantity: disclosed !== undefined,
    orderType,
    product: String(o.product ?? "").toUpperCase(),
    strategy: typeof o.strategy === "string" && o.strategy !== "" ? o.strategy : "Flint",
    orderStatus: status,
    isOpen: isOpenOrderStatus(status),
  };
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
    VALID_PRODUCTS.has(row.product) &&
    (!(row.orderType === "SL" || row.orderType === "SL-M") || row.triggerPriceNum > 0)
  );
}

// ─── Cancel confirmation overlay ─────────────────────────────────────────────

interface CancelConfirmProps {
  row: OrderRow;
  pending: boolean;
  canSubmit: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

function CancelConfirmOverlay({ row, pending, canSubmit, onConfirm, onClose }: CancelConfirmProps) {
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
        {!canSubmit && (
          <p role="alert" className="text-xs text-warning mb-3">
            Order data is unavailable or frozen. Close this confirmation and reconnect before retrying.
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={onConfirm}
            disabled={pending || !canSubmit}
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
  canSubmit: boolean;
  onSubmit: (qty: number, price: number, triggerPrice: number, disclosedQuantity?: number) => void;
  onClose: () => void;
}

function ModifyOverlay({ row, pending, canSubmit, onSubmit, onClose }: ModifyOverlayProps) {
  const [qty, setQty] = useState(String(row.quantityNum > 0 ? row.quantityNum : 1));
  const [price, setPrice] = useState(row.priceNum > 0 ? String(row.priceNum) : "");
  const [trigger, setTrigger] = useState(row.triggerPriceNum > 0 ? String(row.triggerPriceNum) : "");
  const [disclosed, setDisclosed] = useState(
    row.hasDisclosedQuantity ? String(row.disclosedQuantityNum) : "",
  );
  const [error, setError] = useState<string | null>(null);

  const priceRequired = row.orderType === "LIMIT" || row.orderType === "SL";
  const triggerRequired = row.orderType === "SL" || row.orderType === "SL-M";

  function handleSubmit(): void {
    if (!canSubmit) return;
    const qtyNum = parseInt(qty, 10);
    const priceNum = parseFloat(price) || 0;
    const triggerNum = parseFloat(trigger) || 0;
    const disclosedTrimmed = disclosed.trim();
    let disclosedQuantity: number | undefined;
    if (disclosedTrimmed !== "") {
      const disclosedNum = parseFloat(disclosedTrimmed);
      if (!Number.isFinite(disclosedNum) || disclosedNum < 0) {
        setError("Disclosed quantity cannot be negative");
        return;
      }
      disclosedQuantity = disclosedNum;
    } else if (row.hasDisclosedQuantity) {
      disclosedQuantity = row.disclosedQuantityNum;
    }
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
    onSubmit(qtyNum, priceNum, triggerNum, disclosedQuantity);
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
          <div className="flex flex-col gap-0.5">
            <label htmlFor="orders-modify-disclosed" className="text-xxs text-text-muted uppercase tracking-wider">
              Disclosed Quantity
            </label>
            <Input
              id="orders-modify-disclosed"
              type="number"
              min={0}
              value={disclosed}
              onChange={(e) => setDisclosed(e.target.value)}
              placeholder="0"
              className="h-8 text-xs font-mono"
            />
          </div>
        </div>
        {error && (
          <p role="alert" className="text-xs text-loss mb-2">
            {error}
          </p>
        )}
        {!canSubmit && (
          <p role="alert" className="text-xs text-warning mb-2">
            Order data is unavailable or frozen. Close this confirmation and reconnect before retrying.
          </p>
        )}
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            onClick={handleSubmit}
            disabled={pending || !canSubmit}
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
  const accountReadContext = useAccountReadContext();
  const { identity: currentIdentity, enabled: accountReadsEnabled } = accountReadContext;
  const isExplore = currentIdentity.mode === "explore";
  const {
    data: ordersData,
    refetch,
    isFetching,
    isError,
    error,
    isLoading,
    fetchStatus,
  } = useOrders({ enabled: accountReadsEnabled, context: accountReadContext });
  const [sorting, setSorting] = useState<SortingState>([]);
  const track = useTrackBehavior();

  const [cancelIntent, setCancelIntent] = useState<OrderActionIntent | null>(null);
  const [modifyIntent, setModifyIntent] = useState<OrderActionIntent | null>(null);
  const [actionPending, setActionPending] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const rows = useMemo<OrderRow[]>(() => {
    const raw = (ordersData ?? []) as RawOrderRecord[];
    return raw.map(toOrderRow);
  }, [ordersData]);

  const queryUi = resolveAccountQueryUi({
    accountReadsEnabled,
    fetchStatus,
    hasData: rows.length > 0,
    isError,
    isExplore,
    isLoading,
  });
  const canManageOrders = queryUi.canRefetch && !isError;
  const actionGateRef = useRef(canManageOrders);
  const currentIdentityRef = useRef(currentIdentity);
  const refetchBoundaryRef = useRef({
    canRefetch: queryUi.canRefetch,
    identity: currentIdentity,
    refetch,
  });
  actionGateRef.current = canManageOrders;
  currentIdentityRef.current = currentIdentity;
  refetchBoundaryRef.current = {
    canRefetch: queryUi.canRefetch,
    identity: currentIdentity,
    refetch,
  };

  const cancelCanSubmit = canManageOrders
    && cancelIntent !== null
    && accountAuthorityMatches(cancelIntent.identity, currentIdentity);
  const modifyCanSubmit = canManageOrders
    && modifyIntent !== null
    && accountAuthorityMatches(modifyIntent.identity, currentIdentity);

  useEffect(() => {
    if (cancelIntent && !accountAuthorityMatches(cancelIntent.identity, currentIdentity)) {
      setCancelIntent(null);
    }
    if (modifyIntent && !accountAuthorityMatches(modifyIntent.identity, currentIdentity)) {
      setModifyIntent(null);
    }
  }, [cancelIntent, currentIdentity, modifyIntent]);

  useEffect(() => {
    if (rows.length > 0) track("trade", "ordersPlaced");
  }, [rows.length, track]);

  const refreshOrders = useCallback((expectedIdentity: AccountAuthorityIdentity) => {
    runWithMatchingAccountAuthority(
      expectedIdentity,
      () => refetchBoundaryRef.current.identity,
      () => runGuardedAccountRefetch(
        refetchBoundaryRef.current.canRefetch,
        refetchBoundaryRef.current.refetch,
      ),
    );
  }, []);

  const handleCancelConfirm = useCallback(async () => {
    const intent = cancelIntent;
    // Fail closed — compare the immutable open-time identity at the final click.
    if (!actionGateRef.current || !intent || intent.row.orderId == null) return;
    const mutationIdentity = runWithMatchingAccountAuthority(
      intent.identity,
      () => currentIdentityRef.current,
      () => captureAccountAuthority(currentIdentityRef.current),
    );
    if (!mutationIdentity) return;

    const row = intent.row;
    setActionPending(true);
    setActionError(null);
    try {
      await cancelOrder(row.orderId!, row.strategy, mutationIdentity);
      if (accountAuthorityMatches(mutationIdentity, currentIdentityRef.current)) {
        emitNotification({
          category: "order",
          title: `Order cancelled: ${row.action} ${row.symbol}`,
          body: `Order ID ${row.orderId}`,
          accountScopeKey: mutationIdentity.scopeKey,
          skipAccountRefresh: true,
        });
        setCancelIntent(null);
        refreshOrders(mutationIdentity);
      }
    } catch (err) {
      if (accountAuthorityMatches(mutationIdentity, currentIdentityRef.current)) {
        setActionError(err instanceof Error ? err.message : "Cancel failed");
        setCancelIntent(null);
      }
    } finally {
      setActionPending(false);
    }
  }, [cancelIntent, refreshOrders]);

  const handleModifySubmit = useCallback(
    async (qty: number, price: number, triggerPrice: number, disclosedQuantity?: number) => {
      const intent = modifyIntent;
      if (
        !actionGateRef.current
        || !intent
        || intent.row.orderId == null
        || !canModify(intent.row)
      ) return;
      const mutationIdentity = runWithMatchingAccountAuthority(
        intent.identity,
        () => currentIdentityRef.current,
        () => captureAccountAuthority(currentIdentityRef.current),
      );
      if (!mutationIdentity) return;

      const row = intent.row;
      setActionPending(true);
      setActionError(null);
      const params: ModifyOrderParams = {
        orderId: row.orderId!,
        symbol: row.symbol,
        exchange: row.exchange,
        action: row.action as "BUY" | "SELL",
        quantity: qty,
        orderType: row.orderType as "MARKET" | "LIMIT" | "SL" | "SL-M",
        product: row.product as "MIS" | "CNC" | "NRML",
        price,
        triggerPrice,
        strategy: row.strategy,
      };
      if (disclosedQuantity !== undefined) {
        params.disclosedQuantity = disclosedQuantity;
      }
      try {
        await modifyOrder(params, mutationIdentity);
        if (accountAuthorityMatches(mutationIdentity, currentIdentityRef.current)) {
          emitNotification({
            category: "order",
            title: `Order modified: ${params.action} ${qty} ${params.symbol}`,
            body: `Order ID ${params.orderId}`,
            accountScopeKey: mutationIdentity.scopeKey,
            skipAccountRefresh: true,
          });
          setModifyIntent(null);
          refreshOrders(mutationIdentity);
        }
      } catch (err) {
        if (accountAuthorityMatches(mutationIdentity, currentIdentityRef.current)) {
          setActionError(err instanceof Error ? err.message : "Modify failed");
          setModifyIntent(null);
        }
      } finally {
        setActionPending(false);
      }
    },
    [modifyIntent, refreshOrders],
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
          const disabledReason = !canManageOrders
            ? isExplore
              ? "Connect a broker to manage orders"
              : "Order data is unavailable or frozen"
            : idMissing
              ? "Broker did not return an order id"
              : undefined;
          return (
            <span className="flex items-center gap-1.5 justify-end">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => {
                  if (!canManageOrders) return;
                  setActionError(null);
                  setModifyIntent({
                    row: r,
                    identity: captureAccountAuthority(currentIdentity),
                  });
                }}
                disabled={!canManageOrders || actionPending || !canModify(r)}
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
                onClick={() => {
                  if (!canManageOrders) return;
                  setActionError(null);
                  setCancelIntent({
                    row: r,
                    identity: captureAccountAuthority(currentIdentity),
                  });
                }}
                disabled={!canManageOrders || actionPending || idMissing}
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
    [canManageOrders, isExplore, actionPending, currentIdentity],
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
      {cancelIntent && (
        <CancelConfirmOverlay
          row={cancelIntent.row}
          pending={actionPending}
          canSubmit={cancelCanSubmit}
          onConfirm={() => void handleCancelConfirm()}
          onClose={() => setCancelIntent(null)}
        />
      )}

      {/* Modify dialog */}
      {modifyIntent && (
        <ModifyOverlay
          row={modifyIntent.row}
          pending={actionPending}
          canSubmit={modifyCanSubmit}
          onSubmit={(qty, price, trigger, disclosed) => {
            void handleModifySubmit(qty, price, trigger, disclosed);
          }}
          onClose={() => setModifyIntent(null)}
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
          {queryUi.canRefetch && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => runGuardedAccountRefetch(queryUi.canRefetch, refetch)}
              disabled={isFetching}
              className="h-auto w-auto p-0 text-text-muted hover:text-text-primary disabled:opacity-40"
              aria-label="Refresh orders"
            >
              <RefreshCw size={12} className={isFetching ? "animate-spin" : ""} />
            </Button>
          )}
        </div>
      </div>

      {/* Error banner — retained rows stay visible; empty+error shows banner only */}
      {isError && (
        <div
          role="alert"
          className="flex items-center gap-2 px-3 py-2 mx-3 mt-2 bg-loss/10 border border-loss/20 rounded-md text-sm text-loss"
        >
          <span className="flex-1">
            Failed to load orders
            {queryUi.isFrozen ? " — displayed orders are frozen" : ""}
            {error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <Button
            variant="link"
            size="sm"
            onClick={() => runGuardedAccountRefetch(queryUi.canRefetch, refetch)}
            disabled={!queryUi.canRefetch || isFetching}
            className="shrink-0 h-auto p-0 text-xs font-medium text-loss hover:text-loss/80 disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Retry"}
          </Button>
        </div>
      )}

      {queryUi.isFrozen && !isError && (
        <div
          role="status"
          className="px-3 py-1.5 mx-3 mt-2 bg-warning/10 border border-warning/20 rounded-md text-xs text-warning"
        >
          {queryUi.isPaused
            ? "Offline — displayed orders are frozen"
            : "Broker disconnected — displayed orders are frozen"}
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

      {/* Body — mutually exclusive: loading | empty | table | error-only */}
      {queryUi.showInitialLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={16} className="animate-spin text-text-muted" aria-label="Loading orders" />
        </div>
      ) : rows.length === 0 && !isError ? (
        <div className="flex-1 flex flex-col items-center justify-center gap-2 text-text-muted">
          <FileText size={24} className="text-text-disabled" />
          <span className="text-sm">
            {queryUi.isPaused
              ? "Orders unavailable while offline"
              : accountReadsEnabled
                ? "No orders today"
                : "Connect a broker to load orders"}
          </span>
        </div>
      ) : rows.length > 0 ? (
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
      ) : null}
    </div>
  );
}

export default memo(OrdersWidget);
