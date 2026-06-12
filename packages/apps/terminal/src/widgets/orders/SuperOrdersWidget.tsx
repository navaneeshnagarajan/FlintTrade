/**
 * SuperOrdersWidget — super-order (entry + target + stop-loss legs) management.
 *
 * Front-end for the gated super-order routes:
 *   GET    /api/v1/orders/super              (list with leg details)
 *   PUT    /api/v1/orders/super/<id>         (leg modify — kill-switch gated;
 *                                             changes.leg_name selects the leg)
 *   DELETE /api/v1/orders/super/<id>?leg=    (cancel whole order or one leg)
 *
 * Placement happens through the regular order pad / broker flows — this
 * widget manages what already rests at the broker. Live-broker construct:
 * nothing is fetched or simulated outside Live mode, and backend refusals
 * (mode guard, kill switch, 501 unsupported broker) surface verbatim.
 */

import { useState } from "react";
import { Layers, RefreshCw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useModeStore } from "@/stores/modeStore";
import {
  SUPER_ORDER_LEGS,
  useCancelSuperOrder,
  useModifySuperOrder,
  useSuperOrders,
  type BrokerOrderRow,
  type OrderChanges,
  type SuperOrderLeg,
} from "@/lib/brokerOrdersApi";
import {
  BrokerOrdersErrorNotice,
  BrokerTargetSelect,
  BrokerRowsTable,
  DEFAULT_BROKER_TARGET,
  LiveModeNotice,
  extractRowId,
  parsePriceValue,
  parseWholeNumber,
} from "./OrdersManagerShared";

const ORDER_ID_KEYS = ["order_id", "orderid", "orderId", "id"];

const LEG_LABELS: Record<SuperOrderLeg, string> = {
  ENTRY_LEG: "Entry leg (cancels all)",
  TARGET_LEG: "Target leg",
  STOP_LOSS_LEG: "Stop-loss leg",
};

export default function SuperOrdersWidget() {
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [target, setTarget] = useState(DEFAULT_BROKER_TARGET);

  // Leg selection for the next cancel (per the widget, not per row — keeps
  // the table compact; the chosen leg applies to whichever row is cancelled).
  const [cancelLeg, setCancelLeg] = useState<SuperOrderLeg>("ENTRY_LEG");

  // Modify panel state.
  const [modifyingId, setModifyingId] = useState<string | null>(null);
  const [modLeg, setModLeg] = useState<SuperOrderLeg>("TARGET_LEG");
  const [modPrice, setModPrice] = useState("");
  const [modTriggerPrice, setModTriggerPrice] = useState("");
  const [modQuantity, setModQuantity] = useState("");

  const listQuery = useSuperOrders(target, { enabled: isLive });
  const modifyMutation = useModifySuperOrder();
  const cancelMutation = useCancelSuperOrder();

  function handleModify(e: React.FormEvent) {
    e.preventDefault();
    if (!modifyingId) return;
    const changes: OrderChanges = { leg_name: modLeg };
    const newPrice = parsePriceValue(modPrice);
    const newTrigger = parsePriceValue(modTriggerPrice);
    const newQty = parseWholeNumber(modQuantity);
    if (newPrice !== null) changes.price = newPrice;
    if (newTrigger !== null) changes.trigger_price = newTrigger;
    if (newQty !== null) changes.quantity = newQty;
    if (Object.keys(changes).length === 1) return; // leg_name alone modifies nothing
    modifyMutation.mutate(
      { ...target, order_id: modifyingId, changes },
      { onSuccess: () => setModifyingId(null) },
    );
  }

  function rowActions(row: BrokerOrderRow) {
    const orderId = extractRowId(row, ORDER_ID_KEYS);
    return (
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          disabled={orderId === null}
          onClick={() => {
            setModifyingId(orderId);
            setModPrice("");
            setModTriggerPrice("");
            setModQuantity("");
          }}
          className="h-5 px-1.5 text-xxs"
        >
          Modify
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={orderId === null || cancelMutation.isPending}
          onClick={() =>
            orderId !== null &&
            cancelMutation.mutate({ ...target, order_id: orderId, leg: cancelLeg })
          }
          className="h-5 px-1.5 gap-1 text-xxs text-loss hover:text-loss"
        >
          <XCircle size={11} aria-hidden="true" />
          Cancel
        </Button>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden text-xs">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <Layers size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Super Orders</span>
        <div className="flex-1" />
        <BrokerTargetSelect value={target} onChange={setTarget} />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void listQuery.refetch()}
          disabled={!isLive || listQuery.isFetching}
          className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
          aria-label="Refresh super orders"
        >
          <RefreshCw size={12} className={listQuery.isFetching ? "animate-spin" : ""} />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {!isLive && <LiveModeNotice feature="Super orders" />}

        {/* Cancel-leg selector */}
        {isLive && (
          <div className="flex items-center gap-2">
            <span className="text-xxs text-text-muted">Cancel scope:</span>
            <Select value={cancelLeg} onValueChange={(v) => setCancelLeg(v as SuperOrderLeg)}>
              <SelectTrigger className="h-7 w-48 text-xs" aria-label="Cancel leg">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUPER_ORDER_LEGS.map((leg) => (
                  <SelectItem key={leg} value={leg} className="text-xs">
                    {LEG_LABELS[leg]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Modify panel */}
        {modifyingId !== null && (
          <form
            className="flex flex-wrap items-center gap-2 border border-border-default rounded p-2"
            onSubmit={handleModify}
            aria-label="Modify super order leg"
          >
            <span className="text-xxs text-text-muted font-mono">#{modifyingId}</span>
            <Select value={modLeg} onValueChange={(v) => setModLeg(v as SuperOrderLeg)}>
              <SelectTrigger className="h-7 w-36 text-xs" aria-label="Leg to modify">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SUPER_ORDER_LEGS.map((leg) => (
                  <SelectItem key={leg} value={leg} className="text-xs">
                    {leg}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={modPrice}
              onChange={(e) => setModPrice(e.target.value)}
              placeholder="New price"
              inputMode="decimal"
              aria-label="New leg price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={modTriggerPrice}
              onChange={(e) => setModTriggerPrice(e.target.value)}
              placeholder="New trigger"
              inputMode="decimal"
              aria-label="New leg trigger price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={modQuantity}
              onChange={(e) => setModQuantity(e.target.value)}
              placeholder="New qty"
              inputMode="numeric"
              aria-label="New leg quantity"
              className="h-7 w-20 text-xs font-mono"
            />
            <Button type="submit" size="sm" disabled={modifyMutation.isPending} className="h-7">
              Apply
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setModifyingId(null)}
              className="h-7"
            >
              Close
            </Button>
          </form>
        )}
        {modifyMutation.isError && <BrokerOrdersErrorNotice error={modifyMutation.error} />}
        {cancelMutation.isError && <BrokerOrdersErrorNotice error={cancelMutation.error} />}

        {/* Listing */}
        {listQuery.isError && <BrokerOrdersErrorNotice error={listQuery.error} />}
        {isLive && !listQuery.isError && (
          <BrokerRowsTable
            rows={listQuery.data ?? []}
            ariaLabel="Super orders"
            rowKeyKeys={ORDER_ID_KEYS}
            columns={[
              { header: "ID", keys: ORDER_ID_KEYS, mono: true },
              { header: "Symbol", keys: ["symbol", "tradingsymbol", "tradingSymbol", "trading_symbol"], mono: true },
              { header: "Side", keys: ["action", "transactionType", "transaction_type", "side"] },
              { header: "Qty", keys: ["quantity", "qty"], align: "right", mono: true },
              { header: "Price", keys: ["price"], align: "right", mono: true },
              { header: "Target", keys: ["target_price", "targetPrice", "profit_value"], align: "right", mono: true },
              { header: "Stop loss", keys: ["stop_loss_price", "stopLossPrice", "stoploss_value"], align: "right", mono: true },
              { header: "Status", keys: ["status", "order_status", "orderStatus"] },
            ]}
            renderActions={rowActions}
            emptyMessage={
              listQuery.isFetching
                ? "Loading super orders…"
                : "No pending super orders for this broker account."
            }
          />
        )}
      </div>
    </div>
  );
}
