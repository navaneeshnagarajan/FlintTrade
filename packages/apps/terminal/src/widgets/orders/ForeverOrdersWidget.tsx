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

import { useEffect, useState } from "react";
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
  LiveModeNotice,
  extractRowId,
  parsePriceValue,
  parseWholeNumber,
  pickField,
  useResolvedLotSize,
  useSupportedNativeBrokerOrderTarget,
} from "./OrdersManagerShared";
import { checkLotMultiple } from "@/lib/orderGuards";

const SUPPORTED_GTT_BROKERS = ["dhan", "upstox"] as const;
const EXCHANGES = ["NSE", "NFO", "BSE", "BFO", "MCX", "CDS"] as const;
// GTT triggers can rest for days — intraday (MIS) product is rejected upstream.
const PRODUCTS = ["CNC", "NRML"] as const;
const PRICE_TYPES = ["LIMIT", "MARKET"] as const;
const DHAN_MODIFY_PRICE_TYPES = [
  { value: "LIMIT", label: "LIMIT" },
  { value: "MARKET", label: "MARKET" },
  { value: "SL", label: "STOP_LOSS" },
  { value: "SLM", label: "STOP_LOSS_MARKET" },
] as const;
const VALIDITIES = ["DAY", "IOC"] as const;
const ENTRY_TRIGGER_TYPES = ["ABOVE", "BELOW", "IMMEDIATE"] as const;
const DHAN_FOREVER_FLAGS = ["SINGLE", "OCO"] as const;
const DHAN_FOREVER_LEGS = ["TARGET_LEG", "STOP_LOSS_LEG"] as const;

const ORDER_ID_KEYS = ["order_id", "orderid", "orderId", "id", "trigger_id", "gtt_order_id"];

type DhanForeverFlag = (typeof DHAN_FOREVER_FLAGS)[number];
type DhanForeverLeg = (typeof DHAN_FOREVER_LEGS)[number];

function rowText(row: BrokerOrderRow, keys: string[], fallback = ""): string {
  const value = pickField(row, keys);
  return value === "—" ? fallback : value;
}

function upstoxRule(row: BrokerOrderRow, strategy: string): BrokerOrderRow | null {
  const rules = row.rules;
  if (!Array.isArray(rules)) return null;
  const rule = rules.find(
    (candidate) =>
      candidate !== null &&
      typeof candidate === "object" &&
      !Array.isArray(candidate) &&
      String((candidate as BrokerOrderRow).strategy ?? "").toUpperCase() === strategy,
  );
  return rule === undefined ? null : (rule as BrokerOrderRow);
}

function ruleText(rule: BrokerOrderRow | null, key: string, fallback = ""): string {
  if (rule === null) return fallback;
  const value = rule[key];
  return value === null || value === undefined ? fallback : String(value);
}

function dhanModifyPriceType(value: string): string {
  const normalised = value.toUpperCase().replace("-", "_");
  if (normalised === "STOP_LOSS" || normalised === "SL") return "SL";
  if (normalised === "STOP_LOSS_MARKET" || normalised === "SL_M" || normalised === "SLM") {
    return "SLM";
  }
  if (normalised === "MARKET") return "MARKET";
  if (normalised === "LIMIT") return "LIMIT";
  // Fail closed: an unrecognised broker price type must not silently prefill
  // LIMIT — under the complete-replacement modify contract that would rewrite
  // the resting leg's order type at the broker. "" blocks Apply until the
  // operator picks the type deliberately.
  return "";
}

export default function ForeverOrdersWidget() {
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [target, setTarget] = useSupportedNativeBrokerOrderTarget(SUPPORTED_GTT_BROKERS);
  const selectedBroker = target?.broker.toLowerCase() ?? null;
  const isDhan = selectedBroker === "dhan";
  const isUpstox = selectedBroker === "upstox";

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
  const [entryTriggerType, setEntryTriggerType] = useState<(typeof ENTRY_TRIGGER_TYPES)[number]>("ABOVE");
  const [ocoEnabled, setOcoEnabled] = useState(false);
  const [ocoPrice, setOcoPrice] = useState("");
  const [ocoTriggerPrice, setOcoTriggerPrice] = useState("");
  const [ocoQuantity, setOcoQuantity] = useState("");
  const [stopLossEnabled, setStopLossEnabled] = useState(false);
  const [stopLossPrice, setStopLossPrice] = useState("");
  const [targetEnabled, setTargetEnabled] = useState(false);
  const [targetPrice, setTargetPrice] = useState("");

  // --- modify panel ---------------------------------------------------------
  const [modifyingId, setModifyingId] = useState<string | null>(null);
  const [modifyingRow, setModifyingRow] = useState<BrokerOrderRow | null>(null);
  const [modPrice, setModPrice] = useState("");
  const [modTriggerPrice, setModTriggerPrice] = useState("");
  const [modEntryTriggerType, setModEntryTriggerType] =
    useState<(typeof ENTRY_TRIGGER_TYPES)[number]>("ABOVE");
  const [modQuantity, setModQuantity] = useState("");
  const [modDhanFlag, setModDhanFlag] = useState<DhanForeverFlag>("SINGLE");
  const [modDhanLeg, setModDhanLeg] = useState<DhanForeverLeg>("TARGET_LEG");
  const [modPriceType, setModPriceType] = useState("LIMIT");
  const [modValidity, setModValidity] = useState("DAY");
  const [modDisclosedQuantity, setModDisclosedQuantity] = useState("0");
  const [modStopLossEnabled, setModStopLossEnabled] = useState(false);
  const [modStopLossPrice, setModStopLossPrice] = useState("");
  const [modStopLossTrailingGap, setModStopLossTrailingGap] = useState("0");
  const [modTargetEnabled, setModTargetEnabled] = useState(false);
  const [modTargetPrice, setModTargetPrice] = useState("");
  const [modUpstoxEntryStatus, setModUpstoxEntryStatus] = useState("");

  const listQuery = useForeverOrders(target ?? {}, { enabled: isLive && target !== null });
  const placeMutation = usePlaceForeverOrder();
  const modifyMutation = useModifyForeverOrder();
  const cancelMutation = useCancelForeverOrder();

  useEffect(() => {
    setModifyingId(null);
    setModifyingRow(null);
  }, [target?.account_id, target?.broker]);

  const qty = parseWholeNumber(quantity);
  const trigger = parsePriceValue(triggerPrice);
  const limitPrice = parsePriceValue(price);
  const needsLimitPrice = priceType === "LIMIT";
  const ocoValid =
    !ocoEnabled ||
    ((parsePriceValue(ocoPrice) ?? 0) > 0 &&
      (parsePriceValue(ocoTriggerPrice) ?? 0) > 0 &&
      parseWholeNumber(ocoQuantity) !== null);
  const stopLossValid = !stopLossEnabled || (parsePriceValue(stopLossPrice) ?? 0) > 0;
  const targetValid = !targetEnabled || (parsePriceValue(targetPrice) ?? 0) > 0;
  // A GTT can rest for days before it fires, so a quantity that is not a whole
  // number of lots is not rejected until it triggers — long after the operator
  // has stopped looking at this panel.
  const lotState = useResolvedLotSize(symbol, exchange);
  const lotError = qty === null
    ? null
    : checkLotMultiple(exchange, qty, lotState, symbol.trim().toUpperCase());
  const canPlace =
    isLive &&
    target !== null &&
    !placeMutation.isPending &&
    symbol.trim().length > 0 &&
    qty !== null &&
    lotError === null &&
    trigger !== null && trigger > 0 &&
    ((isDhan && (!needsLimitPrice || limitPrice !== null) && ocoValid) ||
      (isUpstox && stopLossValid && targetValid));
  const modTrigger = parsePriceValue(modTriggerPrice);
  const modQty = parseWholeNumber(modQuantity);
  const modDhanPrice = parsePriceValue(modPrice);
  const modStopLoss = parsePriceValue(modStopLossPrice);
  const modTrailingGap = parsePriceValue(modStopLossTrailingGap);
  const modTarget = parsePriceValue(modTargetPrice);
  const isUpstoxEntryOpen = isUpstox && modUpstoxEntryStatus === "OPEN";
  const canModify =
    target !== null &&
    modifyingId !== null &&
    modTrigger !== null &&
    modTrigger > 0 &&
    modQty !== null &&
    ((isDhan && modDhanPrice !== null && modPriceType !== "") ||
      (isUpstox &&
        (!modStopLossEnabled || (modStopLoss ?? 0) > 0) &&
        (!modStopLossEnabled || modTrailingGap !== null) &&
        (!modTargetEnabled || (modTarget ?? 0) > 0)));

  function handlePlace(e: React.FormEvent) {
    e.preventDefault();
    if (!canPlace || target === null || qty === null || trigger === null) return;
    const params: ForeverOrderPlaceParams = {
      ...target,
      variety: "gtt",
      symbol: symbol.trim().toUpperCase(),
      exchange,
      action,
      quantity: qty,
      trigger_price: trigger,
      product,
    };
    if (isDhan) {
      params.price = limitPrice ?? 0;
      params.pricetype = priceType;
      params.validity = validity;
    }
    if (isDhan && ocoEnabled) {
      const p1 = parsePriceValue(ocoPrice);
      const t1 = parsePriceValue(ocoTriggerPrice);
      const q1 = parseWholeNumber(ocoQuantity);
      if (p1 === null || t1 === null || q1 === null) return;
      params.price1 = p1;
      params.trigger_price1 = t1;
      params.quantity1 = q1;
    }
    if (isUpstox) {
      params.entry_trigger_type = entryTriggerType;
      if (stopLossEnabled) {
        params.stop_loss_price = parsePriceValue(stopLossPrice) ?? undefined;
        params.stop_loss_trigger_type = "IMMEDIATE";
      }
      if (targetEnabled) {
        params.target_price = parsePriceValue(targetPrice) ?? undefined;
        params.target_trigger_type = "IMMEDIATE";
      }
    }
    placeMutation.mutate(params);
  }

  function loadDhanLeg(row: BrokerOrderRow, leg: DhanForeverLeg) {
    const second = leg === "STOP_LOSS_LEG";
    setModDhanLeg(leg);
    setModTriggerPrice(
      rowText(row, second ? ["trigger_price1", "triggerPrice1"] : ["trigger_price", "triggerPrice"]),
    );
    setModPrice(rowText(row, second ? ["price1"] : ["price"]));
    setModQuantity(rowText(row, second ? ["quantity1"] : ["quantity", "qty"]));
  }

  function startModify(row: BrokerOrderRow) {
    const orderId = extractRowId(row, ORDER_ID_KEYS);
    if (orderId === null) return;
    setModifyingId(orderId);
    setModifyingRow(row);
    if (isDhan) {
      const flag = rowText(row, ["order_flag", "orderFlag"], "SINGLE").toUpperCase();
      setModDhanFlag(flag === "OCO" ? "OCO" : "SINGLE");
      setModPriceType(
        // Absent price type also fails closed ("") — never assume LIMIT.
        dhanModifyPriceType(rowText(row, ["pricetype", "order_type", "orderType"], "")),
      );
      setModValidity(rowText(row, ["validity"], "DAY"));
      setModDisclosedQuantity(rowText(row, ["disclosed_quantity", "disclosedQuantity"], "0"));
      loadDhanLeg(row, "TARGET_LEG");
      return;
    }
    const entry = upstoxRule(row, "ENTRY");
    const stop = upstoxRule(row, "STOPLOSS");
    const targetRule = upstoxRule(row, "TARGET");
    const entryStatus = ruleText(entry, "status", rowText(row, ["entry_status", "status"])).toUpperCase();
    setModUpstoxEntryStatus(entryStatus);
    setModQuantity(rowText(row, ["quantity", "qty"]));
    setModTriggerPrice(ruleText(entry, "trigger_price", rowText(row, ["trigger_price"])));
    const entryType = ruleText(entry, "trigger_type", "ABOVE").toUpperCase();
    setModEntryTriggerType(
      entryStatus === "OPEN"
        ? "IMMEDIATE"
        : ENTRY_TRIGGER_TYPES.includes(entryType as (typeof ENTRY_TRIGGER_TYPES)[number])
        ? (entryType as (typeof ENTRY_TRIGGER_TYPES)[number])
        : "ABOVE",
    );
    setModStopLossEnabled(stop !== null);
    setModStopLossPrice(ruleText(stop, "trigger_price"));
    setModStopLossTrailingGap(
      ruleText(stop, "trailing_gap", rowText(row, ["stop_loss_trailing_gap"], "0")),
    );
    setModTargetEnabled(targetRule !== null);
    setModTargetPrice(ruleText(targetRule, "trigger_price"));
  }

  function handleModify(e: React.FormEvent) {
    e.preventDefault();
    if (!modifyingId || target === null) return;
    const newPrice = parsePriceValue(modPrice);
    const newTrigger = parsePriceValue(modTriggerPrice);
    const newQty = parseWholeNumber(modQuantity);
    if (newTrigger === null || newTrigger <= 0 || newQty === null) return;
    let changes: OrderChanges;
    if (isDhan) {
      if (newPrice === null) return;
      changes = {
        order_flag: modDhanFlag,
        leg_name: modDhanLeg,
        pricetype: modPriceType,
        validity: modValidity,
        quantity: newQty,
        price: newPrice,
        trigger_price: newTrigger,
        disclosed_quantity: Number.parseInt(modDisclosedQuantity || "0", 10) || 0,
      };
    } else if (isUpstox) {
      const nextStop = modStopLossEnabled ? parsePriceValue(modStopLossPrice) : 0;
      const nextTrailingGap = modStopLossEnabled ? parsePriceValue(modStopLossTrailingGap) : 0;
      const nextTarget = modTargetEnabled ? parsePriceValue(modTargetPrice) : 0;
      if (
        (modStopLossEnabled && ((nextStop ?? 0) <= 0 || nextTrailingGap === null)) ||
        (modTargetEnabled && (nextTarget ?? 0) <= 0)
      ) return;
      changes = {
        type: modStopLossEnabled || modTargetEnabled ? "MULTIPLE" : "SINGLE",
        quantity: newQty,
        trigger_price: newTrigger,
        entry_trigger_type: isUpstoxEntryOpen ? "IMMEDIATE" : modEntryTriggerType,
        stop_loss_price: nextStop ?? 0,
        stop_loss_trailing_gap: nextTrailingGap ?? 0,
        target_price: nextTarget ?? 0,
        stop_loss_trigger_type: "IMMEDIATE",
        target_trigger_type: "IMMEDIATE",
      };
    } else {
      return;
    }
    modifyMutation.mutate(
      { ...target, order_id: modifyingId, changes },
      {
        onSuccess: () => {
          setModifyingId(null);
          setModifyingRow(null);
        },
      },
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
          onClick={() => startModify(row)}
          className="h-5 px-1.5 text-xxs"
        >
          Modify
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={target === null || orderId === null || cancelMutation.isPending}
          onClick={() =>
            target !== null &&
            orderId !== null &&
            cancelMutation.mutate({ ...target, order_id: orderId })
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
        <InfinityIcon size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Forever (GTT) Orders</span>
        <div className="flex-1" />
        <BrokerTargetSelect
          value={target}
          onChange={(next) => {
            setTarget(next);
            setModifyingId(null);
            setModifyingRow(null);
          }}
          includeOpenAlgo={false}
          nativeOnly
          supportedBrokers={SUPPORTED_GTT_BROKERS}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void listQuery.refetch()}
          disabled={!isLive || target === null || listQuery.isFetching}
          className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
          aria-label="Refresh forever orders"
        >
          <RefreshCw size={12} className={listQuery.isFetching ? "animate-spin" : ""} />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {!isLive && <LiveModeNotice feature="Forever (GTT) orders" />}
        {isLive && target === null && (
          <p className="text-xs text-warning bg-warning/10 border border-warning/30 rounded px-2.5 py-1.5">
            Connect a writable Dhan or Upstox account to manage broker-native GTT orders.
          </p>
        )}

        {/* Place form */}
        <form className="space-y-2" onSubmit={handlePlace}>
          <div className="flex flex-wrap items-center gap-2">
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

          <div className="flex flex-wrap items-center gap-2">
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
            {isDhan && (
              <Input
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder={needsLimitPrice ? "Limit price" : "Price (n/a)"}
                inputMode="decimal"
                disabled={!needsLimitPrice}
                aria-label="GTT limit price"
                className="h-7 w-24 text-xs font-mono"
              />
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
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
            {isDhan && (
              <>
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
              </>
            )}
            {isUpstox && (
              <>
                <Select
                  value={entryTriggerType}
                  onValueChange={(value) =>
                    setEntryTriggerType(value as (typeof ENTRY_TRIGGER_TYPES)[number])
                  }
                >
                  <SelectTrigger className="h-7 w-28 text-xs" aria-label="Entry trigger type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ENTRY_TRIGGER_TYPES.map((x) => (
                      <SelectItem key={x} value={x} className="text-xs">
                        {x}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="flex items-center gap-1.5 text-xxs text-text-muted">
                  <Switch
                    checked={stopLossEnabled}
                    onCheckedChange={setStopLossEnabled}
                    aria-label="Stop-loss rule"
                  />
                  Stop-loss
                </label>
                <label className="flex items-center gap-1.5 text-xxs text-text-muted">
                  <Switch
                    checked={targetEnabled}
                    onCheckedChange={setTargetEnabled}
                    aria-label="Target rule"
                  />
                  Target
                </label>
              </>
            )}
            {lotError && (
              <span role="status" className="text-xxs text-warning">
                {lotError}
              </span>
            )}
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

          {isDhan && ocoEnabled && (
            <div className="flex flex-wrap items-center gap-2">
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
          {isUpstox && (stopLossEnabled || targetEnabled) && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xxs text-text-muted">Protective rules:</span>
              {stopLossEnabled && (
                <Input
                  value={stopLossPrice}
                  onChange={(e) => setStopLossPrice(e.target.value)}
                  placeholder="Stop-loss trigger"
                  inputMode="decimal"
                  aria-label="Stop-loss trigger price"
                  className="h-7 w-32 text-xs font-mono"
                />
              )}
              {targetEnabled && (
                <Input
                  value={targetPrice}
                  onChange={(e) => setTargetPrice(e.target.value)}
                  placeholder="Target trigger"
                  inputMode="decimal"
                  aria-label="Target trigger price"
                  className="h-7 w-32 text-xs font-mono"
                />
              )}
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
            className="flex flex-wrap items-center gap-2 border border-border-default rounded p-2"
            onSubmit={handleModify}
            aria-label="Modify forever order"
          >
            <span className="text-xxs text-text-muted font-mono">#{modifyingId}</span>
            {isDhan && (
              <>
                <Select
                  value={modDhanFlag}
                  disabled
                >
                  <SelectTrigger className="h-7 w-24 text-xs" aria-label="Forever order flag">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DHAN_FOREVER_FLAGS.map((flag) => (
                      <SelectItem key={flag} value={flag} className="text-xs">
                        {flag}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select
                  value={modDhanLeg}
                  onValueChange={(value) =>
                    modifyingRow !== null && loadDhanLeg(modifyingRow, value as DhanForeverLeg)
                  }
                >
                  <SelectTrigger className="h-7 w-32 text-xs" aria-label="Forever order leg">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DHAN_FOREVER_LEGS.map((leg) => (
                      <SelectItem
                        key={leg}
                        value={leg}
                        className="text-xs"
                        disabled={leg === "STOP_LOSS_LEG" && modDhanFlag !== "OCO"}
                      >
                        {leg === "TARGET_LEG" ? "Target / single" : "Stop-loss leg"}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
            <Input
              value={modTriggerPrice}
              onChange={(e) => setModTriggerPrice(e.target.value)}
              placeholder="Trigger"
              inputMode="decimal"
              aria-label="New trigger price"
              className="h-7 w-24 text-xs font-mono"
            />
            {isDhan && (
              <Input
                value={modPrice}
                onChange={(e) => setModPrice(e.target.value)}
                placeholder="Price"
                inputMode="decimal"
                aria-label="New price"
                className="h-7 w-24 text-xs font-mono"
              />
            )}
            <Input
              value={modQuantity}
              onChange={(e) => setModQuantity(e.target.value)}
              placeholder="New qty"
              inputMode="numeric"
              disabled={isUpstoxEntryOpen}
              aria-label="New quantity"
              className="h-7 w-20 text-xs font-mono"
            />
            {isDhan && (
              <>
                <Select value={modPriceType} onValueChange={setModPriceType}>
                  <SelectTrigger className="h-7 w-24 text-xs" aria-label="New price type">
                    <SelectValue placeholder="Type?" />
                  </SelectTrigger>
                  <SelectContent>
                    {DHAN_MODIFY_PRICE_TYPES.map((option) => (
                      <SelectItem key={option.value} value={option.value} className="text-xs">
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={modValidity} onValueChange={setModValidity}>
                  <SelectTrigger className="h-7 w-20 text-xs" aria-label="New validity">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VALIDITIES.map((value) => (
                      <SelectItem key={value} value={value} className="text-xs">
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
            {isUpstox && (
              <>
                <Select
                  value={modEntryTriggerType}
                  disabled={isUpstoxEntryOpen}
                  onValueChange={(value) =>
                    setModEntryTriggerType(value as (typeof ENTRY_TRIGGER_TYPES)[number])
                  }
                >
                  <SelectTrigger className="h-7 w-28 text-xs" aria-label="New entry trigger type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ENTRY_TRIGGER_TYPES.map((value) => (
                      <SelectItem key={value} value={value} className="text-xs">
                        {value}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="flex items-center gap-1.5 text-xxs text-text-muted">
                  <Switch
                    checked={modStopLossEnabled}
                    onCheckedChange={setModStopLossEnabled}
                    aria-label="Modify stop-loss rule"
                  />
                  Stop-loss
                </label>
                {modStopLossEnabled && (
                  <>
                    <Input
                      value={modStopLossPrice}
                      onChange={(e) => setModStopLossPrice(e.target.value)}
                      placeholder="Stop-loss"
                      inputMode="decimal"
                      aria-label="New stop-loss trigger price"
                      className="h-7 w-24 text-xs font-mono"
                    />
                    <Input
                      value={modStopLossTrailingGap}
                      onChange={(e) => setModStopLossTrailingGap(e.target.value)}
                      placeholder="Trail gap"
                      inputMode="decimal"
                      aria-label="Stop-loss trailing gap"
                      className="h-7 w-24 text-xs font-mono"
                    />
                  </>
                )}
                <label className="flex items-center gap-1.5 text-xxs text-text-muted">
                  <Switch
                    checked={modTargetEnabled}
                    onCheckedChange={setModTargetEnabled}
                    aria-label="Modify target rule"
                  />
                  Target
                </label>
                {modTargetEnabled && (
                  <Input
                    value={modTargetPrice}
                    onChange={(e) => setModTargetPrice(e.target.value)}
                    placeholder="Target"
                    inputMode="decimal"
                    aria-label="New target trigger price"
                    className="h-7 w-24 text-xs font-mono"
                  />
                )}
              </>
            )}
            <Button
              type="submit"
              size="sm"
              disabled={!canModify || modifyMutation.isPending}
              className="h-7"
            >
              Apply
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => {
                setModifyingId(null);
                setModifyingRow(null);
              }}
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
        {isLive && target !== null && !listQuery.isError && (
          <BrokerRowsTable
            rows={listQuery.data ?? []}
            ariaLabel="Forever orders"
            rowKeyKeys={ORDER_ID_KEYS}
            columns={isUpstox
              ? [
                  { header: "ID", keys: ORDER_ID_KEYS, mono: true },
                  { header: "Symbol", keys: ["symbol", "tradingsymbol", "tradingSymbol", "trading_symbol"], mono: true },
                  { header: "Side", keys: ["action", "transactionType", "transaction_type", "side"] },
                  { header: "Qty", keys: ["quantity", "qty"], align: "right", mono: true },
                  { header: "Entry", keys: ["trigger_price", "triggerPrice"], align: "right", mono: true },
                  { header: "Stop", keys: ["stop_loss_price"], align: "right", mono: true },
                  { header: "Target", keys: ["target_price"], align: "right", mono: true },
                  { header: "Status", keys: ["status", "order_status", "orderStatus", "gtt_status"] },
                ]
              : [
                  { header: "ID", keys: ORDER_ID_KEYS, mono: true },
                  { header: "Symbol", keys: ["symbol", "tradingsymbol", "tradingSymbol", "trading_symbol"], mono: true },
                  { header: "Side", keys: ["action", "transactionType", "transaction_type", "side"] },
                  { header: "Qty", keys: ["quantity", "qty"], align: "right", mono: true },
                  { header: "Trigger", keys: ["trigger_price", "triggerPrice"], align: "right", mono: true },
                  { header: "Price", keys: ["price"], align: "right", mono: true },
                  { header: "Trigger 2", keys: ["trigger_price1", "triggerPrice1"], align: "right", mono: true },
                  { header: "Price 2", keys: ["price1"], align: "right", mono: true },
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
