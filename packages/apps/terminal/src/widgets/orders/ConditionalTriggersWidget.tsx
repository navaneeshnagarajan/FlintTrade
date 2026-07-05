/**
 * ConditionalTriggersWidget — price/indicator alerts that place orders.
 *
 * Front-end for the gated conditional-trigger routes:
 *   POST   /api/v1/orders/triggers           (place — kill-switch gated)
 *   GET    /api/v1/orders/triggers           (list)
 *   PUT    /api/v1/orders/triggers/<id>      (modify — FULL replacement)
 *   DELETE /api/v1/orders/triggers/<id>      (cancel)
 *
 * The condition builder follows the Dhan v2 conditional-trigger contract
 * (comparisonType / exchangeSegment / securityId / indicatorName / timeFrame /
 * operator / comparingValue / comparingIndicatorName / expDate / frequency).
 * Each attached order is a FlintTrade typed order — the backend coerces and
 * safety-checks every leg before the gated dispatch. Live-broker construct:
 * nothing fetched or simulated outside Live mode; refusals surface verbatim.
 */

import { useMemo, useState } from "react";
import { BellRing, Loader2, RefreshCw, Send, XCircle } from "lucide-react";
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
  useCancelConditionalTrigger,
  useConditionalTriggers,
  useModifyConditionalTrigger,
  usePlaceConditionalTrigger,
  type BrokerOrderRow,
  type TriggerCondition,
  type TypedOrderFields,
} from "@/lib/brokerOrdersApi";
import {
  BrokerOrdersErrorNotice,
  BrokerTargetSelect,
  BrokerRowsTable,
  LiveModeNotice,
  extractRowId,
  parsePriceValue,
  parseWholeNumber,
  useBrokerOrderTarget,
} from "./OrdersManagerShared";

// --- Dhan v2 condition vocabulary (see broker docs: conditional-trigger) ----

const COMPARISON_TYPES = [
  { value: "PRICE_WITH_VALUE", label: "Price vs value" },
  { value: "TECHNICAL_WITH_VALUE", label: "Indicator vs value" },
  { value: "TECHNICAL_WITH_INDICATOR", label: "Indicator vs indicator" },
  { value: "TECHNICAL_WITH_CLOSE", label: "Indicator vs close" },
] as const;

const EXCHANGE_SEGMENTS = ["NSE_EQ", "BSE_EQ", "IDX_I"] as const;

const INDICATORS = [
  "SMA_5", "SMA_10", "SMA_20", "SMA_50", "SMA_100", "SMA_200",
  "EMA_5", "EMA_10", "EMA_20", "EMA_50", "EMA_100", "EMA_200",
  "BB_UPPER", "BB_LOWER", "RSI_14", "ATR_14", "STOCHASTIC",
  "STOCHRSI_14", "MACD_26", "MACD_12", "MACD_HIST",
] as const;

const TIME_FRAMES = ["DAY", "ONE_MIN", "FIVE_MIN", "FIFTEEN_MIN"] as const;

const OPERATORS = [
  "CROSSING_UP", "CROSSING_DOWN", "CROSSING_ANY_SIDE",
  "GREATER_THAN", "LESS_THAN", "GREATER_THAN_EQUAL",
  "LESS_THAN_EQUAL", "EQUAL", "NOT_EQUAL",
] as const;

// --- Order-leg vocabulary (FlintTrade typed order fields) -------------------

const LEG_EXCHANGES = ["NSE", "BSE", "NFO", "BFO"] as const;
const LEG_PRICE_TYPES = ["LIMIT", "MARKET", "SL", "SL-M"] as const;
const LEG_PRODUCTS = ["CNC", "NRML", "MIS"] as const;

const ALERT_ID_KEYS = ["alert_id", "alertId", "id"];

function isTechnical(comparisonType: string): boolean {
  return comparisonType.startsWith("TECHNICAL");
}

function needsValue(comparisonType: string): boolean {
  return comparisonType.endsWith("WITH_VALUE");
}

/** Flatten the nested condition object into display strings for the table. */
function withConditionSummary(row: BrokerOrderRow): BrokerOrderRow {
  const condition = row.condition;
  if (condition === null || typeof condition !== "object" || Array.isArray(condition)) {
    return row;
  }
  const c = condition as Record<string, unknown>;
  const subject = typeof c.indicatorName === "string" && c.indicatorName ? c.indicatorName : "PRICE";
  const operator = typeof c.operator === "string" ? c.operator : "?";
  const comparand =
    c.comparingValue !== undefined && c.comparingValue !== null
      ? String(c.comparingValue)
      : typeof c.comparingIndicatorName === "string" && c.comparingIndicatorName
        ? c.comparingIndicatorName
        : "CLOSE";
  return { ...row, _condition_summary: `${subject} ${operator} ${comparand}` };
}

export default function ConditionalTriggersWidget() {
  const appMode = useModeStore((s) => s.mode);
  const isLive = appMode === "live";

  const [target, setTarget] = useBrokerOrderTarget(appMode);

  // null → placing a new trigger; an id → FULL-replacement modify of that alert.
  const [editingAlertId, setEditingAlertId] = useState<string | null>(null);

  // --- condition fields -----------------------------------------------------
  const [comparisonType, setComparisonType] = useState<string>("PRICE_WITH_VALUE");
  const [exchangeSegment, setExchangeSegment] = useState<string>("NSE_EQ");
  const [securityId, setSecurityId] = useState("");
  const [indicatorName, setIndicatorName] = useState<string>("SMA_20");
  const [timeFrame, setTimeFrame] = useState<string>("DAY");
  const [operator, setOperator] = useState<string>("CROSSING_UP");
  const [comparingValue, setComparingValue] = useState("");
  const [comparingIndicatorName, setComparingIndicatorName] = useState<string>("SMA_50");
  const [expDate, setExpDate] = useState("");
  const [userNote, setUserNote] = useState("");

  // --- order leg fields -------------------------------------------------------
  const [symbol, setSymbol] = useState("");
  const [legExchange, setLegExchange] = useState<string>("NSE");
  const [action, setAction] = useState<"BUY" | "SELL">("BUY");
  const [quantity, setQuantity] = useState("");
  const [priceType, setPriceType] = useState<string>("LIMIT");
  const [price, setPrice] = useState("");
  const [legTriggerPrice, setLegTriggerPrice] = useState("");
  const [product, setProduct] = useState<string>("CNC");

  const listQuery = useConditionalTriggers(target, { enabled: isLive });
  const placeMutation = usePlaceConditionalTrigger();
  const modifyMutation = useModifyConditionalTrigger();
  const cancelMutation = useCancelConditionalTrigger();

  const displayRows = useMemo(
    () => (listQuery.data ?? []).map(withConditionSummary),
    [listQuery.data],
  );

  const qty = parseWholeNumber(quantity);
  const value = parsePriceValue(comparingValue);
  const limitPrice = parsePriceValue(price);
  const needsLimitPrice = priceType === "LIMIT" || priceType === "SL";
  const submitting = placeMutation.isPending || modifyMutation.isPending;
  const canSubmit =
    isLive &&
    !submitting &&
    securityId.trim().length > 0 &&
    (!needsValue(comparisonType) || value !== null) &&
    symbol.trim().length > 0 &&
    qty !== null &&
    (!needsLimitPrice || limitPrice !== null);

  function buildCondition(): TriggerCondition {
    const condition: TriggerCondition = {
      comparisonType,
      exchangeSegment,
      securityId: securityId.trim(),
      operator,
      frequency: "ONCE",
    };
    if (isTechnical(comparisonType)) {
      condition.indicatorName = indicatorName;
      condition.timeFrame = timeFrame;
    }
    if (needsValue(comparisonType) && value !== null) condition.comparingValue = value;
    if (comparisonType === "TECHNICAL_WITH_INDICATOR") {
      condition.comparingIndicatorName = comparingIndicatorName;
    }
    if (expDate) condition.expDate = expDate;
    if (userNote.trim()) condition.userNote = userNote.trim();
    return condition;
  }

  function buildOrders(): TypedOrderFields[] {
    return [
      {
        symbol: symbol.trim().toUpperCase(),
        exchange: legExchange,
        action,
        quantity: qty ?? 0,
        price: limitPrice ?? 0,
        trigger_price: parsePriceValue(legTriggerPrice) ?? 0,
        pricetype: priceType,
        product,
        validity: "DAY",
      },
    ];
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    const payload = { ...target, condition: buildCondition(), orders: buildOrders() };
    if (editingAlertId !== null) {
      modifyMutation.mutate(
        { ...payload, alert_id: editingAlertId },
        { onSuccess: () => setEditingAlertId(null) },
      );
    } else {
      placeMutation.mutate(payload);
    }
  }

  /** Best-effort hydration of the condition fields from an adapter row. */
  function startModify(row: BrokerOrderRow) {
    const alertId = extractRowId(row, ALERT_ID_KEYS);
    if (alertId === null) return;
    setEditingAlertId(alertId);
    const condition = row.condition;
    if (condition !== null && typeof condition === "object" && !Array.isArray(condition)) {
      const c = condition as Record<string, unknown>;
      if (typeof c.comparisonType === "string") setComparisonType(c.comparisonType);
      if (typeof c.exchangeSegment === "string") setExchangeSegment(c.exchangeSegment);
      if (typeof c.securityId === "string") setSecurityId(c.securityId);
      if (typeof c.indicatorName === "string") setIndicatorName(c.indicatorName);
      if (typeof c.timeFrame === "string") setTimeFrame(c.timeFrame);
      if (typeof c.operator === "string") setOperator(c.operator);
      if (typeof c.comparingValue === "number" || typeof c.comparingValue === "string") {
        setComparingValue(String(c.comparingValue));
      }
      if (typeof c.comparingIndicatorName === "string") {
        setComparingIndicatorName(c.comparingIndicatorName);
      }
      if (typeof c.expDate === "string") setExpDate(c.expDate);
      if (typeof c.userNote === "string") setUserNote(c.userNote);
    }
  }

  function rowActions(row: BrokerOrderRow) {
    const alertId = extractRowId(row, ALERT_ID_KEYS);
    return (
      <div className="flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          disabled={alertId === null}
          onClick={() => startModify(row)}
          className="h-5 px-1.5 text-xxs"
        >
          Modify
        </Button>
        <Button
          size="sm"
          variant="ghost"
          disabled={alertId === null || cancelMutation.isPending}
          onClick={() => alertId !== null && cancelMutation.mutate({ ...target, alert_id: alertId })}
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
        <BellRing size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Conditional Triggers</span>
        <div className="flex-1" />
        <BrokerTargetSelect value={target} onChange={setTarget} />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void listQuery.refetch()}
          disabled={!isLive || listQuery.isFetching}
          className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
          aria-label="Refresh conditional triggers"
        >
          <RefreshCw size={12} className={listQuery.isFetching ? "animate-spin" : ""} />
        </Button>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-3">
        {!isLive && <LiveModeNotice feature="Conditional triggers" />}

        <form className="space-y-2" onSubmit={handleSubmit}>
          {/* Condition builder */}
          <p className="text-xxs uppercase tracking-wider text-text-muted font-medium">
            Condition {editingAlertId !== null && (
              <span className="normal-case font-mono text-text-secondary">
                — modifying #{editingAlertId} (full replacement: re-confirm the order leg too)
              </span>
            )}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={comparisonType} onValueChange={setComparisonType}>
              <SelectTrigger className="h-7 w-44 text-xs" aria-label="Comparison type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPARISON_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value} className="text-xs">
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={exchangeSegment} onValueChange={setExchangeSegment}>
              <SelectTrigger className="h-7 w-24 text-xs" aria-label="Exchange segment">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {EXCHANGE_SEGMENTS.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={securityId}
              onChange={(e) => setSecurityId(e.target.value)}
              placeholder="Security ID"
              aria-label="Security ID"
              className="h-7 w-28 text-xs font-mono"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {isTechnical(comparisonType) && (
              <>
                <Select value={indicatorName} onValueChange={setIndicatorName}>
                  <SelectTrigger className="h-7 w-32 text-xs" aria-label="Indicator">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {INDICATORS.map((x) => (
                      <SelectItem key={x} value={x} className="text-xs">
                        {x}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Select value={timeFrame} onValueChange={setTimeFrame}>
                  <SelectTrigger className="h-7 w-28 text-xs" aria-label="Timeframe">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TIME_FRAMES.map((x) => (
                      <SelectItem key={x} value={x} className="text-xs">
                        {x}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            )}
            <Select value={operator} onValueChange={setOperator}>
              <SelectTrigger className="h-7 w-44 text-xs" aria-label="Operator">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OPERATORS.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {needsValue(comparisonType) && (
              <Input
                value={comparingValue}
                onChange={(e) => setComparingValue(e.target.value)}
                placeholder="Comparing value"
                inputMode="decimal"
                aria-label="Comparing value"
                className="h-7 w-28 text-xs font-mono"
              />
            )}
            {comparisonType === "TECHNICAL_WITH_INDICATOR" && (
              <Select value={comparingIndicatorName} onValueChange={setComparingIndicatorName}>
                <SelectTrigger className="h-7 w-32 text-xs" aria-label="Comparing indicator">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {INDICATORS.map((x) => (
                    <SelectItem key={x} value={x} className="text-xs">
                      {x}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Input
              type="date"
              value={expDate}
              onChange={(e) => setExpDate(e.target.value)}
              aria-label="Alert expiry date"
              title="Alert expiry date (defaults to one year at the broker)"
              className="h-7 w-36 text-xs"
            />
            <Input
              value={userNote}
              onChange={(e) => setUserNote(e.target.value)}
              placeholder="Note (optional)"
              aria-label="User note"
              className="h-7 flex-1 min-w-32 text-xs"
            />
          </div>

          {/* Order leg */}
          <p className="text-xxs uppercase tracking-wider text-text-muted font-medium">
            Order on trigger
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="Symbol"
              aria-label="Trigger order symbol"
              className="h-7 w-32 text-xs font-mono"
            />
            <Select value={legExchange} onValueChange={setLegExchange}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Order exchange">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEG_EXCHANGES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
              aria-label="Trigger order quantity"
              className="h-7 w-20 text-xs font-mono"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Select value={priceType} onValueChange={setPriceType}>
              <SelectTrigger className="h-7 w-24 text-xs" aria-label="Order price type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEG_PRICE_TYPES.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Input
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              placeholder={needsLimitPrice ? "Price" : "Price (n/a)"}
              inputMode="decimal"
              disabled={!needsLimitPrice}
              aria-label="Trigger order price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Input
              value={legTriggerPrice}
              onChange={(e) => setLegTriggerPrice(e.target.value)}
              placeholder="SL trigger"
              inputMode="decimal"
              disabled={priceType !== "SL" && priceType !== "SL-M"}
              aria-label="Trigger order stop price"
              className="h-7 w-24 text-xs font-mono"
            />
            <Select value={product} onValueChange={setProduct}>
              <SelectTrigger className="h-7 w-20 text-xs" aria-label="Order product">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LEG_PRODUCTS.map((x) => (
                  <SelectItem key={x} value={x} className="text-xs">
                    {x}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex-1" />
            {editingAlertId !== null && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => setEditingAlertId(null)}
                className="h-7"
              >
                Stop modifying
              </Button>
            )}
            <Button type="submit" size="sm" disabled={!canSubmit} className="gap-1.5 h-7">
              {submitting ? (
                <Loader2 size={13} className="animate-spin" aria-hidden="true" />
              ) : (
                <Send size={13} aria-hidden="true" />
              )}
              {editingAlertId !== null ? "Apply changes" : "Place trigger"}
            </Button>
          </div>
        </form>

        {placeMutation.isError && <BrokerOrdersErrorNotice error={placeMutation.error} />}
        {placeMutation.isSuccess && (
          <p className="text-xs text-profit">
            Conditional trigger placed — the broker watches the condition and
            places the order when it is met.
          </p>
        )}
        {modifyMutation.isError && <BrokerOrdersErrorNotice error={modifyMutation.error} />}
        {cancelMutation.isError && <BrokerOrdersErrorNotice error={cancelMutation.error} />}

        {/* Listing */}
        {listQuery.isError && <BrokerOrdersErrorNotice error={listQuery.error} />}
        {isLive && !listQuery.isError && (
          <BrokerRowsTable
            rows={displayRows}
            ariaLabel="Conditional triggers"
            rowKeyKeys={ALERT_ID_KEYS}
            columns={[
              { header: "Alert", keys: ALERT_ID_KEYS, mono: true },
              { header: "Condition", keys: ["_condition_summary"] },
              { header: "Status", keys: ["alertStatus", "alert_status", "status"] },
              { header: "Last price", keys: ["lastPrice", "last_price"], align: "right", mono: true },
              { header: "Created", keys: ["createdTime", "created_time", "created_at"] },
            ]}
            renderActions={rowActions}
            emptyMessage={
              listQuery.isFetching
                ? "Loading conditional triggers…"
                : "No conditional triggers for this broker account."
            }
          />
        )}
      </div>
    </div>
  );
}
