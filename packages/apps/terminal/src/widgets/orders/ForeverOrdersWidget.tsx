/**
 * ForeverOrdersWidget — Forever (GTT, Good Till Triggered) order management.
 *
 * Front-end for the gated forever-order routes:
 *   POST   /api/v1/orders/forever            (place — SafetySystem L1–L5 gated)
 *   GET    /api/v1/orders/forever            (list resting triggers)
 *   PUT    /api/v1/orders/forever/<id>       (modify — kill-switch gated)
 *   DELETE /api/v1/orders/forever/<id>       (cancel)
 *
 * Honest gating: forever orders are live-broker constructs — the widget
 * fetches nothing outside Live mode and surfaces every backend refusal
 * (mode guard, PIN unlock, safety block, 501 unsupported broker) verbatim.
 * No demo rows, ever.
 */

import { useState } from "react";
import { Infinity as InfinityIcon, Loader2, RefreshCw, Send, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useModeStore } from "@/stores/modeStore";
import {
  useCancelForeverOrder,
  useForeverOrders,
  useModifyForeverOrder,
  usePlaceForeverOrder,
  type BrokerOrderRow,
  type ForeverOrderPlaceParams,
  type OrderChanges,
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

const EXCHANGES = ["NSE", "NFO", "BSE", "BFO", "MCX", "CDS"] as const;
// GTT triggers can rest for days — intraday (MIS) product is rejected upstream.
const PRODUCTS = ["CNC", "NRML"] as const;
const PRICE_TYPES = ["LIMIT", "MARKET", "SL", "SL-M"] as const;
const VALIDITIES = ["DAY", "IOC"] as const;

const ORDER_ID_KEYS = ["order_id", "orderid", "orderId", "id", "trigger_id", "gtt_order_id"];

export default function ForeverOrdersWidget() {
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [target, setTarget] = useState(DEFAULT_BROKER_TARGET);

  // --- place form -----------------------------------------------------------
  const [symbol, setSymbol] = useState("");
  const [exchange, setExchange] = useState<string>("NSE");
  const [action, setAction] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [triggerPrice, setTriggerPrice] = useState("");
  const [product, setProduct] = useState<string>("CNC");
  const [priceType, setPriceType] = useState<string>("LIMIT");
  const [validity, setValidity] = useState<string>("DAY");
  const [ocoEnabled, setOcoEnabled] = useState(false);
  const [ocoPrice, setOcoPrice] = useState("");
  const [ocoTriggerPrice, setOcoTriggerPrice] = useState("");
  const [ocoQuantity, setOcoQuantity] = useState("");

  // --- modify panel ---------------------------------------------------------
  const [modifyingId, setModifyingId] = useState<string | null>(null);
  const [modPrice, setModPrice] = useState("");
  const [modTriggerPrice, setModTriggerPrice] = useState("");
  const [modQuantity, setModQuantity] = useState("");

  const listQuery = useForeverOrders(target, { enabled: isLive });
  const placeMutation = usePlaceForeverOrder();
  const modifyMutation = useModifyForeverOrder();
  const cancelMutation = useCancelForeverOrder();

  const qty = parseWholeNumber(quantity);
  const trigger = parsePriceValue(triggerPrice);
  const limitPrice = parsePriceValue(price);
  const needsLimitPrice = priceType === "LIMIT" || priceType === "SL";
  const ocoValid =
    !ocoEnabled ||
    (parsePriceValue(ocoPrice) !== null &&
      parsePriceValue(ocoTriggerPrice) !== null &&
      parseWholeNumber(ocoQuantity) !== null);
  const canPlace =
    isLive &&
    !placeMutation.isPending &&
    symbol.trim().length > 0 &&
    qty !== null &&
    trigger !== null &&
    (!needsLimitPrice || limitPrice !== null) &&
    ocoValid;

  function handlePlace(e: React.FormEvent) {
    e.preventDefault();
    if (!canPlace || qty === null || trigger === null) return;
    const params: ForeverOrderPlaceParams = {
      ...target,
      variety: "gtt",
      symbol: symbol.trim().toUpperCase(),
      exchange,
      action,
      quantity: qty,
      price: limitPrice ?? 0,
      trigger_price: trigger,
      product,
      pricetype: priceType,
      validity,
    };
    if (ocoEnabled) {
      const p1 = parsePriceValue(ocoPrice);
      const t1 = parsePriceValue(ocoTriggerPrice);
      const q1 = parseWholeNumber(ocoQuantity);
      if (p1 === null || t1 === null || q1 === null) return;
      params.price1 = p1;
      params.trigger_price1 = t1;
      params.quantity1 = q1;
    }
    placeMutation.mutate(params);
  }

  function handleModify(e: React.FormEvent) {
    e.preventDefault();
    if (!modifyingId) return;
    const changes: OrderChanges = {};
    const newPrice = parsePriceValue(modPrice);
    const newTrigger = parsePriceValue(modTriggerPrice);
    const newQty = parseWholeNumber(modQuantity);
    if (newPrice !== null) changes.price = newPrice;
    if (newTrigger !== null) changes.trigger_price = newTrigger;
    if (newQty !== null) changes.quantity = newQty;
    if (Object.keys(changes).length === 0) return;
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
          onClick={() => orderId !== null && cancelMutation.mutate({ ...target, order_id: orderId })}
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
        <InfinityIcon size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Forever (GTT) Orders</span>
        <div className="flex-1" />
        <BrokerTargetSelect value={target} onChange={setTarget} />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void listQuery.refetch()}
          disabled={!isLive || listQuery.isFetching}
          className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
          aria-label="Refresh forever orders"
        >
          <RefreshCw size={12} className={listQuery.isFetching ? "animate-spin" : ""} />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {!isLive && <LiveModeNotice feature="Forever (GTT) orders" />}

        {/* Place form */}
        <form className="space-y-2" onSubmit={handlePlace}>
          <div className="flex items-center gap-2">
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="Symbol (e.g. RELIANCE)"
              aria-label="GTT symbol"
              className="h-7 flex-1 text-xs font-mono"
            />
            <Select value={exchange} onValueChange={setExchange}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Exchange">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXCHANGES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <div role="group" aria-label="Order side" className="flex rounded border border-border-default overflow-hidden">
              {(["BUY", "SELL"] as const).map((side) => (
                <Button
                  key={side}
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setAction(side)}
                  aria-pressed={action === side}
                  className={`h-7 px-3 rounded-none text-xs font-semibold ${
                    action === side
                      ? side === "BUY"
                        ? "bg-profit text-white hover:bg-profit hover:text-white"
                        : "bg-loss text-white hover:bg-loss hover:text-white"
                      : "text-text-muted"
                  }`}
                >
                  {side}
                </Button>
              ))}
            </div>
            <Input
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="Qty"
              inputMode="numeric"
              aria-label="GTT quantity"
              className="h-7 w-20 text-xs font-mono"
            />
            <Input
              value={triggerPrice}
              onChange={(e) => setTriggerPrice(e.target.value)}
              placeholder="Trigger price"
              inputMode="decimal"
              aria-label="GTT trigger price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder={needsLimitPrice ? "Limit price" : "Price (n/a)"}
              inputMode="decimal"
              disabled={!needsLimitPrice}
              aria-label="GTT limit price"
              className="h-7 w-24 text-xs font-mono"
            />
          </div>

          <div className="flex items-center gap-2">
            <Select value={priceType} onValueChange={setPriceType}>
              <SelectTrigger className="h-7 w-24 text-xs" aria-label="Price type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRICE_TYPES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={product} onValueChange={setProduct}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Product">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRODUCTS.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={validity} onValueChange={setValidity}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Validity">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {VALIDITIES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label className="flex items-center gap-1.5 text-xxs text-text-muted">
              <Switch
                checked={ocoEnabled}
                onCheckedChange={setOcoEnabled}
                aria-label="OCO second leg"
              />
              OCO
            </label>
            <div className="flex-1" />
            <Button type="submit" size="sm" disabled={!canPlace} className="gap-1.5 h-7">
              {placeMutation.isPending ? (
                <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              ) : (
                <Send size={13} aria-hidden="true" />
              )}
              Place GTT
            </Button>
          </div>

          {ocoEnabled && (
            <div className="flex items-center gap-2">
              <span className="text-xxs text-text-muted">OCO leg:</span>
              <Input
                value={ocoTriggerPrice}
                onChange={(e) => setOcoTriggerPrice(e.target.value)}
                placeholder="Trigger 2"
                inputMode="decimal"
                aria-label="OCO trigger price"
                className="h-7 w-24 text-xs font-mono"
              />
              <Input
                value={ocoPrice}
                onChange={(e) => setOcoPrice(e.target.value)}
                placeholder="Price 2"
                inputMode="decimal"
                aria-label="OCO price"
                className="h-7 w-24 text-xs font-mono"
              />
              <Input
                value={ocoQuantity}
                onChange={(e) => setOcoQuantity(e.target.value)}
                placeholder="Qty 2"
                inputMode="numeric"
                aria-label="OCO quantity"
                className="h-7 w-20 text-xs font-mono"
              />
            </div>
          )}
        </form>

        {placeMutation.isError && <BrokerOrdersErrorNotice error={placeMutation.error} />}
        {placeMutation.isSuccess && (
          <p className="text-xs text-profit">
            Forever order accepted — it rests at the broker until the trigger fires.
          </p>
        )}

        {/* Modify panel */}
        {modifyingId !== null && (
          <form
            className="flex items-center gap-2 border border-border-default rounded p-2"
            onSubmit={handleModify}
            aria-label="Modify forever order"
          >
            <span className="text-xxs text-text-muted font-mono">#{modifyingId}</span>
            <Input
              value={modTriggerPrice}
              onChange={(e) => setModTriggerPrice(e.target.value)}
              placeholder="New trigger"
              inputMode="decimal"
              aria-label="New trigger price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={modPrice}
              onChange={(e) => setModPrice(e.target.value)}
              placeholder="New price"
              inputMode="decimal"
              aria-label="New price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={modQuantity}
              onChange={(e) => setModQuantity(e.target.value)}
              placeholder="New qty"
              inputMode="numeric"
              aria-label="New quantity"
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
            ariaLabel="Forever orders"
            rowKeyKeys={ORDER_ID_KEYS}
            columns={[
              { header: "ID", keys: ORDER_ID_KEYS, mono: true },
              { header: "Symbol", keys: ["symbol", "tradingsymbol", "tradingSymbol", "trading_symbol"], mono: true },
              { header: "Side", keys: ["action", "transactionType", "transaction_type", "side"] },
              { header: "Qty", keys: ["quantity", "qty"], align: "right", mono: true },
              { header: "Trigger", keys: ["trigger_price", "triggerPrice"], align: "right", mono: true },
              { header: "Price", keys: ["price"], align: "right", mono: true },
              { header: "Status", keys: ["status", "order_status", "orderStatus", "gtt_status"] },
            ]}
            renderActions={rowActions}
            emptyMessage={
              listQuery.isFetching
                ? "Loading forever orders…"
                : "No resting forever orders for this broker account."
            }
          />
        )}
      </div>
    </div>
  );
}
