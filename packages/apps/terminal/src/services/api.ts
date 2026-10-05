

import type {
  Position,
  Order,
  Trade,
  Holding,
  Funds,
  Quote,
  MarketDepth,
  DepthLevel,
  OHLCVBar,
  OptionChainData,
  PlaceOrderParams,
  ModifyOrderParams,
  OrderStatusParams,
  BasketOrderParams,
  BasketOrderResult,
  SplitOrderParams,
  OptionsOrderParams,
  OptionsMultiOrderParams,
  OptionGreeksParams,
  Greeks,
  GexEntry,
  ProvenancedRows,
  IVSmileEntry,
  IVSmileSeriesData,
  MaxPainData,
  OIProfileEntry,
  SyntheticFutureData,
  MarginData,
  Holiday,
  MarketTiming,
  BrokerCapabilities,
  LeverageSettings,
} from "@/types/api";
import { layaOrderRefused } from "@/lib/layaStatus";
import { useConnectionStore } from "@/stores/connectionStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { readOperatorIncident } from "@/hooks/useOperatorIncident";
import { liveWritesMuted } from "@/lib/operatorIncident";
import { operatorModeName } from "@/lib/operatorModeLabel";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { exchangeTransactionLabel } from "@/lib/indianCharges";
import { buildCompactOptionSymbol } from "@/lib/optionSymbols";
import { sampleChainOptionLtp } from "@/lib/sampleOptionChain";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  requireCurrentBrokerCapabilityScope,
  requireCurrentMarketDataScope,
  resolveAccountAuthorityIdentity,
  resolveMarketDataScope,
  resolveBrokerCapabilityScope,
  resolveNativeDataAccount,
  type AccountAuthorityIdentity,
} from "@/hooks/useDataScope";
export { MarketDataAuthorityChangedError } from "@/hooks/useDataScope";
import {
  assertNativeWriteTargetReadyOrThrow,
  pickNativeBrokerOrderTarget,
  pickNativeWriteTarget,
} from "@/services/brokerTargets";
import {
  cancelForeverOrder,
  listForeverOrders,
  modifyForeverOrder,
  placeForeverOrder,
  type BrokerTarget,
  type ForeverOrderPlaceParams,
  type OrderChanges,
} from "@/lib/brokerOrdersApi";
import { orderLimiter, smartOrderLimiter, generalLimiter } from "@/services/rateLimiter";
import { mockDataEngine } from "@/services/mockDataEngine";
import {
  readNativeAccount,
  type NativeReadKind,
  type NativeReadParams,
} from "@/services/ftApi.native";
import {
  listLiveNativeReadAccounts,
  selectNativeReadAccount,
} from "@/services/brokerAccountsApi";
import { z } from "zod";
import {
  get as getFtApi,
  getBase as getFtBase,
  getV1 as getFtV1,
  post as postFtApi,
  postWithMode as postFtApiWithMode,
} from "./ftApi.helpers";

// Endpoints subject to the 10/s order rate limit (excludes placesmartorder which has its own)
const ORDER_ENDPOINTS = new Set([
  "placeorder",
  "modifyorder",
  "cancelorder",
  "cancelallorder",
  "closeposition",
  "openposition",
  "optionsorder",
  "optionsmultiorder",
  "basketorder",
  "splitorder",
]);

// Endpoints subject to the 2/s smart-order rate limit
const SMART_ORDER_ENDPOINTS = new Set(["placesmartorder"]);

const NATIVE_READ_ENDPOINTS: Partial<Record<string, NativeReadKind>> = {
  funds: "funds",
  limits: "limits",
  orderbook: "orders",
  orderstatus: "orderstatus",
  orderhistory: "orderhistory",
  ordertrades: "ordertrades",
  tradebook: "trades",
  positionbook: "positions",
  holdings: "holdings",
  ltp: "ltp",
  quotes: "quotes",
  quote_details: "quote_details",
  ticker: "quotes",
  multiquotes: "quotes",
  depth: "depth",
  margin: "margin",
  scrip_master: "scrip_master",
  holidays: "holidays",
  "market/holidays": "holidays",
  timings: "timings",
  "market/timings": "timings",
  optiongreeks: "optiongreeks",
  multioptiongreeks: "optiongreeks",
  history: "history",
  expiry: "expiry",
  optionchain: "optionchain",
  search: "search",
  symbol: "search",
  search_scrip: "search_scrip",
};

const NATIVE_ROUTED_ORDER_ENDPOINTS = new Set(["place", "modify", "cancel"]);

// Endpoints with no `/<broker>/` path variant whose backend handler resolves the
// broker principal from `broker` / `account_id` in the request body
// (`_request_principal` → `_resolve_target` in order_routes / bracket_routes).
// When a native write target is selected, the selectors MUST ride in the body —
// otherwise the backend silently falls back to `brokers.execution.default`, a
// different target than the operator chose. `split` shares the identical
// body-resolved contract (order_routes `place_split` → `_request_principal`);
// add `options-strategy` here too if a client for that route is ever wired.
const TARGET_IN_BODY_ORDER_ENDPOINTS = new Set(["cancel-all", "basket", "split"]);

// Account-scoped native reads expose the REAL broker account (balances,
// positions, order/trade book, margin). They must only surface in LIVE mode —
// in Practice/Explore orders execute in the SandboxEngine, so showing the live
// account here would falsely present real money as sandbox state. Market-data
// kinds (quotes/history/depth/optionchain/greeks/expiry/search/timings/holidays)
// are broker-agnostic reference data and stay available in every mode.
const NATIVE_ACCOUNT_SCOPED_KINDS = new Set<NativeReadKind>([
  "funds", "limits", "positions", "holdings", "orders", "orderstatus", "orderhistory", "ordertrades", "trades", "margin",
]);


/** Base URL for the FlintTrade Python backend.
 *  In dev mode the Vite proxy maps /ft-api → localhost:5100.
 *  In production the backend shares the same origin. */

function isExploreMode(): boolean {
  return useModeStore.getState().mode === "explore";
}

function captureMarketDataScope(expectedScope?: string): string {
  if (expectedScope) return expectedScope;
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return resolveMarketDataScope({ mode: useModeStore.getState().mode, accounts, activeAccountId });
}

async function awaitMarketDataAuthority<T>(
  operation: () => Promise<T>,
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<T> {
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  try {
    const value = await operation();
    signal?.throwIfAborted();
    requireCurrentMarketDataScope(expectedDataScope);
    return value;
  } catch (error) {
    // A transport failure from authority A must not be downgraded to an
    // ordinary fallback after the UI has already retired A for authority B.
    signal?.throwIfAborted();
    requireCurrentMarketDataScope(expectedDataScope);
    throw error;
  }
}

type NativeReadAccountCandidate = Awaited<ReturnType<typeof listLiveNativeReadAccounts>>[number];

function pickNativeReadAccount(accounts: Awaited<ReturnType<typeof listLiveNativeReadAccounts>>) {
  const { accounts: brokerAccounts, activeAccountId } = useBrokerStore.getState();
  return selectNativeReadAccount(accounts, brokerAccounts, activeAccountId);
}

async function primaryNativeReadAccountFor(
  kind: NativeReadKind,
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<NativeReadAccountCandidate | undefined> {
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (isExploreMode()) return undefined;
  // Account-scoped reads expose the REAL broker account and must be Live-only.
  // Market-data kinds stay readable in every mode.
  if (NATIVE_ACCOUNT_SCOPED_KINDS.has(kind) && useModeStore.getState().mode !== "live") {
    return undefined;
  }
  const accounts = await awaitMarketDataAuthority(
    () => listLiveNativeReadAccounts(signal),
    signal,
    expectedDataScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  // Mode can change while discovery is in flight. Revalidate before the
  // caller starts the account-specific broker request on this authority.
  if (isExploreMode()) return undefined;
  if (NATIVE_ACCOUNT_SCOPED_KINDS.has(kind) && useModeStore.getState().mode !== "live") {
    return undefined;
  }
  return pickNativeReadAccount(accounts);
}

function normaliseOrderBody(body: object): Record<string, unknown> {
  const normalised = { ...(body as Record<string, unknown>) };
  const copyField = (from: string, to: string) => {
    if (normalised[from] !== undefined && normalised[to] === undefined) {
      normalised[to] = normalised[from];
    }
  };

  copyField("orderId", "orderid");
  copyField("orderType", "order_type");
  copyField("triggerPrice", "trigger_price");
  copyField("marketProtection", "market_protection");
  copyField("positionSize", "position_size");
  copyField("disclosedQuantity", "disclosed_quantity");
  copyField("priceBasis", "price_basis");

  return normalised;
}

function toNumber(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function toStrictNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && value.trim() === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function toNonNegativeInteger(value: unknown): number | null {
  const parsed = toStrictNumber(value);
  return parsed !== null && Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}

function toPositiveFiniteNumber(value: unknown): number | null {
  const parsed = toStrictNumber(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

function normaliseFundsShape(value: unknown): Funds {
  const row = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const availableCash = toNumber(
    row.availableCash ?? row.availablecash ?? row.available_balance ?? row.available ?? row.cash,
  );
  const usedMargin = toNumber(
    row.usedMargin ?? row.utiliseddebits ?? row.usedmargin ?? row.used_margin
      ?? row.utilized_margin ?? row.utilised_margin,
  );
  const estimatedRaw = row.estimatedCharges ?? row.estimated_charges;
  const estimatedCharges = estimatedRaw === undefined || estimatedRaw === null
    ? undefined
    : toNumber(estimatedRaw);
  const ledgerBalance = optionalFinite(row.ledgerBalance ?? row.ledger_balance);
  const futuresFlag = row.futuresMtmInLedger ?? row.futures_mtm_in_ledger;
  return {
    availableCash,
    usedMargin,
    totalBalance: toNumber(
      row.totalBalance ?? row.totalbalance ?? row.total_balance ?? row.total ?? row.net
        ?? (availableCash + usedMargin),
    ),
    ...(ledgerBalance !== undefined ? { ledgerBalance } : {}),
    ...(typeof futuresFlag === "boolean" ? { futuresMtmInLedger: futuresFlag } : {}),
    ...(estimatedCharges !== undefined ? { estimatedCharges } : {}),
  };
}

function optionalFinite(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringParam(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}



/** Official OptionSymbolSchema offset (ATM / ITM1-50 / OTM1-50), or null for an explicit strike. */







function todayIstIsoDate(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function currentIstYear(): number {
  return Number(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
  }).format(new Date()));
}

function holidayYear(value: unknown): number {
  if (value !== undefined && typeof value !== "number" && typeof value !== "string") {
    throw new Error("holiday year must be between 2020 and 2050");
  }
  const numericYear = value === undefined || value === "" ? currentIstYear() : Number(value);
  if (!Number.isInteger(numericYear) || numericYear < 2020 || numericYear > 2050) {
    throw new Error("holiday year must be between 2020 and 2050");
  }
  return numericYear;
}

/** Daily Welcome looks three calendar days ahead of the current IST date. */
const HOLIDAY_LOOKAHEAD_DAYS = 3;

function istCalendarDatePlusDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split("-").map(Number);
  const next = new Date(Date.UTC(year, month - 1, day + days));
  const yyyy = String(next.getUTCFullYear());
  const mm = String(next.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(next.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function holidayYearsForLookahead(lookAheadDays = HOLIDAY_LOOKAHEAD_DAYS): number[] {
  const year = currentIstYear();
  const years = [year];
  const aheadYear = Number(istCalendarDatePlusDays(todayIstIsoDate(), lookAheadDays).slice(0, 4));
  if (aheadYear !== year && aheadYear >= 2020 && aheadYear <= 2050) {
    years.push(aheadYear);
  }
  return years;
}

function mergeHolidayCalendars(calendars: Holiday[][]): Holiday[] {
  const byDate = new Map<string, Holiday>();
  for (const calendar of calendars) {
    for (const holiday of calendar) {
      if (!byDate.has(holiday.date)) byDate.set(holiday.date, holiday);
    }
  }
  return [...byDate.values()];
}

function nativeSymbolKey(symbol: unknown, exchange: unknown): string {
  const raw = stringParam(symbol).trim();
  if (!raw) return "";
  if (raw.includes(":")) return raw;
  return `${stringParam(exchange, "NSE").trim() || "NSE"}:${raw}`;
}

function buildNativeReadParams(endpoint: string, extra: object): NativeReadParams | undefined {
  const params = extra as Record<string, unknown>;
  if (endpoint === "ltp" || endpoint === "quotes" || endpoint === "ticker") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE"),
    };
  }
  if (endpoint === "quote_details") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE"),
      quote_type: stringParam(params.quote_type ?? params.type, "all"),
    };
  }
  if (endpoint === "multiquotes") {
    const symbols = Array.isArray(params.symbols)
      ? params.symbols
          .map((item) => (
            isRecord(item) ? nativeSymbolKey(item.symbol, item.exchange) : nativeSymbolKey(item, "NSE")
          ))
          .filter(Boolean)
      : [];
    return { symbols: symbols.join(",") };
  }
  if (endpoint === "multioptiongreeks") {
    const symbols = Array.isArray(params.symbols)
      ? params.symbols
          .map((item) => (
            isRecord(item) ? nativeSymbolKey(item.symbol, item.exchange) : nativeSymbolKey(item, "NFO")
          ))
          .filter(Boolean)
      : [];
    return { symbols: symbols.join(",") };
  }
  if (endpoint === "optiongreeks") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NFO"),
    };
  }
  if (endpoint === "depth") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE"),
    };
  }
  if (endpoint === "margin") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE"),
      qty: toNumber(params.qty ?? params.quantity),
      product: stringParam(params.product, "MIS"),
      action: stringParam(params.action, "BUY"),
      price: params.price === undefined ? undefined : stringParam(params.price),
      pricetype: stringParam(params.pricetype ?? params.order_type, "MARKET"),
    };
  }
  if (endpoint === "orderstatus") {
    return {
      order_id: stringParam(params.order_id ?? params.orderId ?? params.orderid),
    };
  }
  if (endpoint === "orderhistory" || endpoint === "ordertrades") {
    return {
      order_id: stringParam(params.order_id ?? params.orderId ?? params.orderid),
    };
  }
  if (endpoint === "limits") {
    return {
      segment: stringParam(params.segment, "ALL"),
      exchange: stringParam(params.exchange, "ALL"),
      product: stringParam(params.product, "ALL"),
    };
  }
  if (endpoint === "scrip_master") {
    const exchange = stringParam(params.exchange);
    return exchange ? { exchange } : undefined;
  }
  if (endpoint === "history") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE"),
      interval: stringParam(params.interval),
      start_date: stringParam(params.start_date),
      end_date: stringParam(params.end_date),
    };
  }
  if (endpoint === "expiry") {
    return {
      symbol: stringParam(params.symbol),
      exchange: stringParam(params.exchange, "NSE_INDEX"),
    };
  }
  if (endpoint === "optionchain") {
    const underlying = stringParam(params.underlying) || stringParam(params.symbol);
    const expiry = stringParam(params.expiry) || stringParam(params.expiry_date);
    const instrumentKey = stringParam(params.instrument_key);
    return {
      underlying,
      exchange: stringParam(params.exchange, "NSE_INDEX"),
      ...(expiry ? { expiry } : {}),
      ...(instrumentKey ? { instrument_key: instrumentKey } : {}),
    };
  }
  if (endpoint === "search" || endpoint === "symbol") {
    const exchange = stringParam(params.exchange);
    return {
      query: stringParam(params.query) || stringParam(params.symbol),
      ...(exchange ? { exchange } : {}),
    };
  }
  if (endpoint === "holidays" || endpoint === "market/holidays") {
    const paramsOut: NativeReadParams = {};
    const date = stringParam(params.date);
    if (date) paramsOut.date = date;
    if (typeof params.year === "number" && Number.isFinite(params.year)) {
      paramsOut.year = params.year;
    } else {
      const yearText = stringParam(params.year);
      if (yearText) paramsOut.year = yearText;
    }
    return Object.keys(paramsOut).length > 0 ? paramsOut : undefined;
  }
  if (endpoint === "search_scrip") {
    const optional: NativeReadParams = {};
    const expiry = stringParam(params.expiry);
    const optionType = stringParam(params.option_type);
    const strikePrice = stringParam(params.strike_price);
    if (expiry) optional.expiry = expiry;
    if (optionType) optional.option_type = optionType;
    if (strikePrice) optional.strike_price = strikePrice;
    if (typeof params.ignore_50multiple === "boolean") optional.ignore_50multiple = params.ignore_50multiple;
    return {
      symbol: stringParam(params.symbol) || stringParam(params.query),
      exchange: stringParam(params.exchange, "NSE"),
      ...optional,
    };
  }
  return undefined;
}

function normaliseNativeTimestamp(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value > 1_000_000_000_000 ? Math.floor(value / 1000) : value;
  }
  if (typeof value === "string") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      return numeric > 1_000_000_000_000 ? Math.floor(numeric / 1000) : numeric;
    }
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  }
  return 0;
}

function normaliseNativeHistory(value: unknown): OHLCVBar[] {
  const rawBars = Array.isArray(value) ? value : (isRecord(value) && Array.isArray(value.bars) ? value.bars : []);
  return rawBars.filter(isRecord).map((bar) => ({
    timestamp: normaliseNativeTimestamp(bar.timestamp),
    open: toNumber(bar.open),
    high: toNumber(bar.high),
    low: toNumber(bar.low),
    close: toNumber(bar.close),
    volume: toNumber(bar.volume),
  }));
}

function normaliseNativeQuote(value: unknown): Quote {
  const raw = Array.isArray(value)
    ? value[0]
    : (isRecord(value) && Array.isArray(value.quotes) ? value.quotes[0] : value);
  if (!isRecord(raw)) {
    throw new Error("Native broker returned no quote.");
  }
  const ltp = toPositiveFiniteNumber(raw.ltp ?? raw.last_price ?? raw.lastPrice);
  if (ltp === null) {
    throw new Error("Native broker quote lacks a valid positive LTP.");
  }
  return {
    ...(raw as Partial<Quote>),
    symbol: String(raw.symbol ?? ""),
    exchange: String(raw.exchange ?? ""),
    ltp,
    open: toNumber(raw.open),
    high: toNumber(raw.high),
    low: toNumber(raw.low),
    close: toNumber(raw.close),
    volume: toNumber(raw.volume),
    prev_close: toNumber(raw.prev_close ?? raw.previous_close ?? raw.previousClose),
  };
}

function normaliseNativeMultiQuotes(value: unknown): { results: MultiQuoteResult[] } {
  const rawRows = Array.isArray(value)
    ? value
    : (isRecord(value) && Array.isArray(value.quotes) ? value.quotes : []);
  const results = rawRows.filter(isRecord).map((row) => {
    const quote = normaliseNativeQuote(row);
    return {
      symbol: quote.symbol,
      exchange: quote.exchange,
      data: quote,
    };
  });
  return { results };
}

function nativeDepthLevel(row: unknown): DepthLevel {
  const data = isRecord(row) ? row : {};
  return {
    price: toNumber(data.price),
    quantity: toNumber(data.quantity),
    orders: toNumber(data.orders),
  };
}

function firstNativeDepthBook(value: unknown): unknown {
  if (Array.isArray(value)) return value[0];
  if (isRecord(value)) {
    if (Array.isArray(value.bids) || Array.isArray(value.asks) || Array.isArray(value.buy) || Array.isArray(value.sell)) {
      return value;
    }
    const first = Object.values(value).find((entry) => (
      isRecord(entry) && (
        Array.isArray(entry.bids) || Array.isArray(entry.asks) ||
        Array.isArray(entry.buy) || Array.isArray(entry.sell)
      )
    ));
    if (first) return first;
  }
  return value;
}

function normaliseNativeDepth(value: unknown): MarketDepth {
  const book = firstNativeDepthBook(value);
  const row = isRecord(book) ? book : {};
  const bids = Array.isArray(row.bids) ? row.bids : (Array.isArray(row.buy) ? row.buy : []);
  const asks = Array.isArray(row.asks) ? row.asks : (Array.isArray(row.sell) ? row.sell : []);
  return {
    buy: bids.map(nativeDepthLevel),
    sell: asks.map(nativeDepthLevel),
  };
}

function normaliseNativeMargin(value: unknown): MarginData {
  const row = isRecord(value) ? value : {};
  const required = toNumber(
    row.required_margin
      ?? row.total_margin_required
      ?? row.total_margin
      ?? row.final_margin
      ?? row.margin_required,
  );
  return {
    ...row,
    required_margin: required,
    total_margin_required: required,
    span_margin: toNumber(row.span_margin),
    exposure_margin: toNumber(row.exposure_margin),
    available_margin: toNumber(row.available_margin ?? row.available_balance),
    brokerage: toNumber(row.brokerage),
    charges: isRecord(row.charges) ? row.charges : row.charges,
  } as MarginData;
}

function normaliseNativeOrderStatus(value: unknown): { status: string } {
  const row = isRecord(value) ? value : {};
  return {
    status: String(row.status ?? row.order_status ?? row.orderStatus ?? row.state ?? ""),
  };
}

const isoCalendarDateSchema = z.string().trim().regex(/^\d{4}-\d{2}-\d{2}$/).refine((value) => {
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}, "Invalid calendar date");

const nativeHolidayDateSchema = z.string().trim()
  .regex(
    /^(\d{4}-\d{2}-\d{2})(?:[T ](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)?)?$/,
    "Invalid calendar date or datetime",
  )
  .refine(
    (value) => isoCalendarDateSchema.safeParse(value.slice(0, 10)).success,
    "Invalid calendar date",
  )
  .transform((value) => value.slice(0, 10));

const nativeEpochSchema = z.union([
  z.number().finite().nonnegative(),
  z.string().trim().regex(/^\d+(?:\.\d+)?$/).transform(Number).pipe(z.number().finite().nonnegative()),
]);

const nativeOpenExchangeSchema = z.object({
  exchange: z.string().trim().min(1),
  start_time: nativeEpochSchema,
  end_time: nativeEpochSchema,
}).refine((session) => session.end_time > session.start_time, {
  message: "end_time must be after start_time",
  path: ["end_time"],
});

const nativeHolidaySchema = z.object({
  date: nativeHolidayDateSchema.optional(),
  _date: nativeHolidayDateSchema.optional(),
  description: z.string().trim().min(1),
  holiday_type: z.string().trim().min(1),
  closed_exchanges: z.array(z.string().trim().min(1)),
  open_exchanges: z.array(nativeOpenExchangeSchema),
}).refine((row) => row.date !== undefined || row._date !== undefined, {
  message: "date or _date is required",
  path: ["date"],
}).transform((row): Holiday => ({
  date: row.date ?? row._date!,
  description: row.description,
  holiday_type: row.holiday_type,
  closed_exchanges: row.closed_exchanges,
  open_exchanges: row.open_exchanges,
}));

function normaliseNativeHolidays(value: unknown): Holiday[] {
  const parsed = z.array(nativeHolidaySchema).safeParse(value);
  if (!parsed.success) {
    const issue = parsed.error.issues[0];
    const path = issue?.path.length ? ` at ${issue.path.join(".")}` : "";
    throw new Error(`Invalid native holiday response${path}: ${issue?.message ?? "schema mismatch"}`);
  }
  return parsed.data;
}

function normaliseNativeTimings(value: unknown): MarketTiming[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.filter(isRecord).map((row) => ({
    exchange: String(row.exchange ?? ""),
    start_time: toNumber(row.start_time),
    end_time: toNumber(row.end_time),
  }));
}

function greekNumber(row: Record<string, unknown>, field: string, ...aliases: string[]): number {
  const raw = [field, ...aliases].map((key) => row[key]).find((item) => item !== undefined);
  if (
    raw === null
    || raw === undefined
    || typeof raw === "boolean"
    || (typeof raw !== "number" && typeof raw !== "string")
    || (typeof raw === "string" && !raw.trim())
  ) {
    throw new Error(`Option-Greeks row lacks ${field}`);
  }
  const parsed = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(parsed)) throw new Error(`Option-Greeks row has invalid ${field}`);
  return parsed;
}

function nativeGreeksRow(value: unknown): Greeks {
  if (!isRecord(value)) throw new Error("Invalid native option-Greeks row");
  const row = value;
  const symbol = stringParam(row.symbol ?? row.trading_symbol ?? row.tradingsymbol).trim();
  const exchange = stringParam(row.exchange).trim().toUpperCase();
  const instrumentId = stringParam(row.instrument_id ?? row.instrument_token).trim();
  if (!symbol || !exchange || !instrumentId) {
    throw new Error("Native option-Greeks row lacks contract identity");
  }
  return {
    symbol,
    exchange,
    instrument_id: instrumentId,
    delta: greekNumber(row, "delta", "Delta"),
    gamma: greekNumber(row, "gamma", "Gamma"),
    theta: greekNumber(row, "theta", "Theta"),
    vega: greekNumber(row, "vega", "Vega"),
    iv: greekNumber(row, "iv", "implied_volatility", "IV", "vix"),
  };
}

function normaliseNativeGreeks(value: unknown): Greeks[] {
  if (!Array.isArray(value)) throw new Error("Invalid native option-Greeks response");
  const rows = value;
  return rows.map(nativeGreeksRow);
}

function normaliseNativeExpiry(value: unknown): { expiry: string[] } {
  const rows = Array.isArray(value)
    ? value
    : (isRecord(value) && Array.isArray(value.expiry) ? value.expiry : []);
  return {
    expiry: rows.flatMap((item) => {
      if (typeof item !== "string") return [];
      const expiry = item.trim();
      return expiry ? [expiry] : [];
    }),
  };
}

type OptionLegNumberKind = "finite" | "nonnegative" | "nonnegative-integer";

const OPTION_LEG_NUMERIC_FIELDS: ReadonlyArray<readonly [string, OptionLegNumberKind]> = [
  ["ltp", "nonnegative"],
  ["last_price", "nonnegative"],
  ["bid", "nonnegative"],
  ["ask", "nonnegative"],
  ["change", "finite"],
  ["change_percent", "finite"],
  ["change_pct", "finite"],
  ["oi_change", "finite"],
  ["oi", "nonnegative-integer"],
  ["open_interest", "nonnegative-integer"],
  ["volume", "nonnegative-integer"],
  ["delta", "finite"],
  ["gamma", "finite"],
  ["theta", "finite"],
  ["vega", "finite"],
  ["iv", "nonnegative"],
  ["implied_volatility", "nonnegative"],
];

function optionLegNumber(
  value: unknown,
  label: string,
  field: string,
  kind: OptionLegNumberKind = "finite",
): number | undefined {
  if (value === null || value === undefined) return undefined;
  const parsed = toStrictNumber(value);
  const valid = parsed !== null
    && (kind === "finite" || parsed >= 0)
    && (kind !== "nonnegative-integer" || Number.isInteger(parsed));
  if (!valid) throw new Error(`Invalid option-chain ${label} ${field}`);
  return parsed;
}

function normaliseOptionLegNumericFields(
  value: Record<string, unknown>,
  label: string,
): Record<string, unknown> {
  const normalised = { ...value };
  for (const [field, kind] of OPTION_LEG_NUMERIC_FIELDS) {
    if (!(field in value)) continue;
    const parsed = optionLegNumber(value[field], label, field, kind);
    if (parsed === undefined) delete normalised[field];
    else normalised[field] = parsed;
  }
  const mirrorAlias = (primary: string, alias: string) => {
    const parsed = normalised[primary] ?? normalised[alias];
    if (typeof parsed !== "number") return;
    normalised[primary] = parsed;
    normalised[alias] = parsed;
  };
  mirrorAlias("ltp", "last_price");
  mirrorAlias("change_percent", "change_pct");
  mirrorAlias("oi", "open_interest");
  mirrorAlias("iv", "implied_volatility");
  return normalised;
}

function nativeOptionLeg(
  row: Record<string, unknown>,
  prefix: "ce" | "pe",
): Record<string, number | null> {
  const field = (name: string) => row[`${prefix}_${name}`];
  const label = `native ${prefix.toUpperCase()} leg`;
  const greeksComplete = field("greeks_complete") === true;
  const requiredGreek = (name: string, value: number | undefined): number => {
    if (value === undefined) throw new Error(`Invalid option-chain ${label} ${name}: unavailable`);
    return value;
  };
  const ltp = optionLegNumber(field("ltp"), label, "ltp", "nonnegative");
  const bid = optionLegNumber(field("bid"), label, "bid", "nonnegative");
  const ask = optionLegNumber(field("ask"), label, "ask", "nonnegative");
  const oi = optionLegNumber(field("oi"), label, "oi", "nonnegative-integer");
  const volume = optionLegNumber(field("volume"), label, "volume", "nonnegative-integer");
  const change = optionLegNumber(field("change"), label, "change");
  const changePercentValue = optionLegNumber(field("change_percent"), label, "change_percent");
  const changePctValue = optionLegNumber(field("change_pct"), label, "change_pct");
  const changePercent = changePercentValue ?? changePctValue;
  const oiChange = optionLegNumber(field("oi_change"), label, "oi_change");
  const rawIV = optionLegNumber(field("iv"), label, "iv", "nonnegative");
  const rawDelta = optionLegNumber(field("delta"), label, "delta");
  const rawGamma = optionLegNumber(field("gamma"), label, "gamma");
  const rawTheta = optionLegNumber(field("theta"), label, "theta");
  const rawVega = optionLegNumber(field("vega"), label, "vega");
  const iv = greeksComplete ? requiredGreek("iv", rawIV) / 100 : null;
  const delta = greeksComplete ? requiredGreek("delta", rawDelta) : null;
  const gamma = greeksComplete ? requiredGreek("gamma", rawGamma) : null;
  const theta = greeksComplete ? requiredGreek("theta", rawTheta) : null;
  const vega = greeksComplete ? requiredGreek("vega", rawVega) : null;
  return {
    ...(ltp === undefined ? {} : { ltp, last_price: ltp }),
    ...(oi === undefined ? {} : { oi, open_interest: oi }),
    ...(volume === undefined ? {} : { volume }),
    ...(change === undefined ? {} : { change }),
    ...(changePercent === undefined ? {} : { change_percent: changePercent, change_pct: changePercent }),
    ...(oiChange === undefined ? {} : { oi_change: oiChange }),
    iv,
    implied_volatility: iv,
    delta,
    gamma,
    theta,
    vega,
    ...(bid === undefined ? {} : { bid }),
    ...(ask === undefined ? {} : { ask }),
  };
}

function normaliseNativePreShapedOptionLeg(value: unknown, label: string): Record<string, unknown> | null {
  if (!isRecord(value)) return null;
  return normaliseOptionLegNumericFields(value, label);
}



function nativeOptionChainPCR(
  chain: Array<{ ce: Record<string, unknown> | null; pe: Record<string, unknown> | null }>,
): number | null {
  const callOi = chain.map((entry) => toNonNegativeInteger(entry.ce?.oi));
  const putOi = chain.map((entry) => toNonNegativeInteger(entry.pe?.oi));
  const hasCompleteOi = chain.length > 0
    && callOi.every((oi) => oi !== null)
    && putOi.every((oi) => oi !== null);
  if (!hasCompleteOi) return null;
  const totalCallOi = callOi.reduce((total, oi) => total + oi!, 0);
  const totalPutOi = putOi.reduce((total, oi) => total + oi!, 0);
  return totalCallOi > 0 ? totalPutOi / totalCallOi : null;
}

function normaliseNativeOptionChain(value: unknown): unknown {
  const row = isRecord(value) ? value : {};
  const spot = toPositiveFiniteNumber(
    row.underlying_ltp ?? row.spot_price ?? row.spotPrice ?? row.spot,
  );
  if (spot === null) {
    throw new Error("Native option chain lacks a valid positive spot price.");
  }

  const chain = Array.isArray(row.chain)
    ? row.chain.filter(isRecord).flatMap((entry) => {
        const strike = toPositiveFiniteNumber(entry.strike ?? entry.strike_price);
        if (strike === null) return [];
        return [{
          strike,
          ce: normaliseNativePreShapedOptionLeg(entry.ce, "native CE leg"),
          pe: normaliseNativePreShapedOptionLeg(entry.pe, "native PE leg"),
        }];
      })
    : (Array.isArray(row.strikes) ? row.strikes : []).filter(isRecord).flatMap((strikeRow) => {
        const strike = toPositiveFiniteNumber(strikeRow.strike_price ?? strikeRow.strike);
        if (strike === null) return [];
        return [{
          strike,
          ce: nativeOptionLeg(strikeRow, "ce"),
          pe: nativeOptionLeg(strikeRow, "pe"),
        }];
      });
  chain.sort((a, b) => a.strike - b.strike);

  const requestedAtm = toPositiveFiniteNumber(row.atm_strike);
  const atmStrike = requestedAtm !== null && chain.some((entry) => entry.strike === requestedAtm)
    ? requestedAtm
    : chain.reduce<{ strike: number } | null>((nearest, entry) => (
        nearest === null || Math.abs(entry.strike - spot) < Math.abs(nearest.strike - spot)
          ? entry
          : nearest
      ), null)?.strike ?? null;
  return {
    ...row,
    chain,
    atm_strike: atmStrike,
    underlying_ltp: spot,
    expiry: String(row.expiry ?? row.expiry_date ?? ""),
    pcr: nativeOptionChainPCR(chain),
  };
}

type NativeSearchResult = {
  symbol: string;
  exchange: string;
  name?: unknown;
  instrumenttype?: unknown;
  instrument_type?: unknown;
  segment?: unknown;
  lotsize?: unknown;
  lot_size?: unknown;
  tick_size?: unknown;
} & Record<string, unknown>;

function normaliseNativeSearch(value: unknown): NativeSearchResult[] {
  const rawRows = Array.isArray(value)
    ? value
    : (isRecord(value) && Array.isArray(value.results) ? value.results : []);
  return rawRows.filter(isRecord).map((row) => {
    const symbol = String(row.symbol ?? row.trading_symbol ?? row.tradingsymbol ?? "").trim();
    const instrumentKey = String(row.instrument_key ?? row.instrument_token ?? "");
    const inferredExchange = instrumentKey.includes("|") ? instrumentKey.split("|")[0] : "";
    const exchange = String(row.exchange ?? row.exch_seg ?? inferredExchange).trim();
    return {
      ...row,
      symbol,
      exchange,
    };
  }).filter((row) => row.symbol);
}

function normaliseNativeSymbol(value: unknown): {
  symbol: string;
  name: string;
  exchange: string;
  instrumenttype: string;
  lotsize: number;
  tick_size: number;
} {
  const first = normaliseNativeSearch(value)[0];
  if (!first || !isRecord(first)) {
    throw new Error("Native broker returned no symbol metadata.");
  }
  return {
    symbol: String(first.symbol ?? ""),
    name: String(first.name ?? first.symbol ?? ""),
    exchange: String(first.exchange ?? ""),
    instrumenttype: String(first.instrumenttype ?? first.instrument_type ?? first.segment ?? ""),
    lotsize: toNumber(first.lotsize ?? first.lot_size),
    tick_size: toNumber(first.tick_size),
  };
}

interface BackendMaxPainData {
  is_sample_data?: unknown;
  max_pain_strike?: unknown;
  total_loss_at_max_pain?: unknown;
  strike_losses?: Array<{
    strike?: unknown;
    strike_price?: unknown;
    total_loss?: unknown;
    total_pain?: unknown;
  }>;
  strikes?: Array<{
    strike?: unknown;
    call_oi?: unknown;
    put_oi?: unknown;
    call_pain?: unknown;
    put_pain?: unknown;
    total_pain?: unknown;
  }>;
}

interface BackendGexEntry {
  strike?: number | string;
  call_gex?: number | string;
  put_gex?: number | string;
  net_gex?: number | string;
  call_oi?: number | string;
  put_oi?: number | string;
}

interface BackendGexData {
  is_sample_data?: unknown;
  strikes?: BackendGexEntry[];
}

interface BackendIVSmileData {
  is_sample_data?: unknown;
  curves?: Array<{
    points?: IVSmileEntry[];
  }>;
  points?: IVSmileEntry[];
}

interface BackendOIProfileData {
  is_sample_data?: unknown;
  strikes?: Array<{
    strike?: number | string;
    ce_oi?: number | string;
    pe_oi?: number | string;
    ce_oi_change?: number | string;
    pe_oi_change?: number | string;
  }>;
}

type BackendBrokerCapabilityRow = {
  broker_name?: string;
  broker_type?: BrokerCapabilities["broker_type"];
  historical_intervals?: string[];
  historical_intraday_intervals_minutes?: number[];
  historical_calendar_intervals?: string[];
  supported_exchanges?: string[];
  supports_bracket_orders?: boolean;
  supports_cover_orders?: boolean;
  supports_commodities?: boolean;
  supports_currency?: boolean;
  supports_equity?: boolean;
  supports_futures?: boolean;
  supports_market_orders?: boolean;
  supports_options?: boolean;
  market_protection?: boolean;
  leverage?: boolean;
} & Record<string, unknown>;

interface BackendBrokerCapabilitiesData {
  broker?: string;
  capabilities?: BackendBrokerCapabilityRow;
  brokers?: BackendBrokerCapabilityRow[];
}

type InstrumentRow = {
  symbol: string;
  name: string;
  exchange: string;
  instrumenttype: string;
  lotsize: number;
  tick_size: number;
  token: string;
};

function normaliseGexEntries(
  value: BackendGexData | Array<BackendGexEntry | GexEntry>,
): ProvenancedRows<GexEntry> {
  const rawRows = Array.isArray(value) ? value : value.strikes ?? [];
  const rows = rawRows.flatMap((row) => {
    const strike = toStrictNumber(row.strike);
    const callGex = toStrictNumber(row.call_gex);
    const putGex = toStrictNumber(row.put_gex);
    const netGex = toStrictNumber(row.net_gex);
    const callOi = toNonNegativeInteger(row.call_oi);
    const putOi = toNonNegativeInteger(row.put_oi);
    const expectedNetGex = callGex === null || putGex === null ? null : callGex + putGex;
    const exposureScale = expectedNetGex === null || netGex === null
      ? 1
      : Math.max(1, Math.abs(callGex!), Math.abs(putGex!), Math.abs(netGex), Math.abs(expectedNetGex));
    if (
      strike === null || strike <= 0
      || callGex === null || putGex === null || netGex === null
      || callOi === null || putOi === null
      || expectedNetGex === null
      || Math.abs(netGex - expectedNetGex) > exposureScale * 1e-6
    ) return [];
    return [{
      strike,
      call_gex: callGex,
      put_gex: putGex,
      net_gex: netGex,
      call_oi: callOi,
      put_oi: putOi,
    }];
  });
  return {
    rows,
    is_sample_data: Array.isArray(value) || value.is_sample_data !== false,
  };
}

function normaliseIVSmileEntries(value: BackendIVSmileData | IVSmileEntry[]): IVSmileSeriesData {
  const curve = Array.isArray(value) ? undefined : value.curves?.[0];
  const rawPoints = Array.isArray(value) ? value : (value.points ?? curve?.points ?? []);
  const points = rawPoints.flatMap((row) => {
    const strike = toStrictNumber(row.strike);
    const callIv = toStrictNumber(row.call_iv);
    const putIv = toStrictNumber(row.put_iv);
    const moneyness = toStrictNumber(row.moneyness);
    if (
      strike === null || strike <= 0
      || callIv === null || callIv <= 0
      || putIv === null || putIv <= 0
      || moneyness === null || moneyness <= 0
    ) return [];
    return [{ strike, call_iv: callIv, put_iv: putIv, moneyness }];
  });
  return {
    points,
    is_sample_data: Array.isArray(value) || value.is_sample_data !== false,
  };
}

function normaliseOIProfileEntries(
  value: BackendOIProfileData | OIProfileEntry[],
): ProvenancedRows<OIProfileEntry> {
  const rows = Array.isArray(value)
    ? value.flatMap((row) => {
        const strike = toStrictNumber(row.strike);
        const oi = toNonNegativeInteger(row.oi);
        if (strike === null || strike <= 0 || (row.type !== "CE" && row.type !== "PE") || oi === null) {
          return [];
        }
        const oiDelta = toStrictNumber(row.oi_delta_d);
        const ltp = toStrictNumber(row.ltp);
        const priceChange = toStrictNumber(row.price_change);
        return [{
          strike,
          type: row.type,
          oi,
          ...(oiDelta === null ? {} : { oi_delta_d: oiDelta }),
          ...(ltp === null || ltp < 0 ? {} : { ltp }),
          ...(priceChange === null ? {} : { price_change: priceChange }),
        }];
      })
    : (value.strikes ?? []).flatMap((row) => {
        const strike = toStrictNumber(row.strike);
        if (strike === null || strike <= 0) return [];
        const ceOi = toNonNegativeInteger(row.ce_oi);
        const peOi = toNonNegativeInteger(row.pe_oi);
        const ceOiChange = toStrictNumber(row.ce_oi_change);
        const peOiChange = toStrictNumber(row.pe_oi_change);
        return [
          ...(ceOi === null ? [] : [{
            strike,
            type: "CE" as const,
            oi: ceOi,
            ...(ceOiChange === null ? {} : { oi_delta_d: ceOiChange }),
          }]),
          ...(peOi === null ? [] : [{
            strike,
            type: "PE" as const,
            oi: peOi,
            ...(peOiChange === null ? {} : { oi_delta_d: peOiChange }),
          }]),
        ];
      });
  return {
    rows,
    is_sample_data: Array.isArray(value) || value.is_sample_data !== false,
  };
}

function normaliseMaxPainData(value: BackendMaxPainData): MaxPainData {
  const parsedStrikeLosses = (value.strike_losses ?? []).flatMap((row) => {
    const strike = toStrictNumber(row.strike ?? row.strike_price);
    const totalLoss = toStrictNumber(row.total_loss ?? row.total_pain);
    return strike !== null && strike > 0 && totalLoss !== null && totalLoss >= 0
      ? [{ strike, total_loss: totalLoss }]
      : [];
  });
  const maxPainStrike = toStrictNumber(value.max_pain_strike);
  const totalLossAtMaxPain = toStrictNumber(value.total_loss_at_max_pain);
  const parsedStrikes = value.strikes
    ? value.strikes.flatMap((row) => {
        const strike = toStrictNumber(row.strike);
        const totalPain = toStrictNumber(row.total_pain);
        if (strike === null || strike <= 0 || totalPain === null || totalPain < 0) return [];

        const callOi = toNonNegativeInteger(row.call_oi);
        const putOi = toNonNegativeInteger(row.put_oi);
        const callPain = toStrictNumber(row.call_pain);
        const putPain = toStrictNumber(row.put_pain);
        return [{
          strike,
          ...(callOi === null ? {} : { call_oi: callOi }),
          ...(putOi === null ? {} : { put_oi: putOi }),
          ...(callPain === null || callPain < 0 ? {} : { call_pain: callPain }),
          ...(putPain === null || putPain < 0 ? {} : { put_pain: putPain }),
          total_pain: totalPain,
        }];
      })
    : parsedStrikeLosses.map((row) => ({
        strike: row.strike,
        total_pain: row.total_loss,
      }));
  const meaningfulMaxPainStrike = maxPainStrike !== null && maxPainStrike > 0
    ? maxPainStrike
    : null;
  const strikeLosses = meaningfulMaxPainStrike === null
    ? parsedStrikeLosses.filter((row) => row.total_loss > 0)
    : parsedStrikeLosses;
  const strikes = meaningfulMaxPainStrike === null
    ? parsedStrikes.filter((row) => row.total_pain > 0)
    : parsedStrikes;

  return {
    is_sample_data: value.is_sample_data !== false,
    max_pain_strike: meaningfulMaxPainStrike,
    ...(meaningfulMaxPainStrike === null || totalLossAtMaxPain === null || totalLossAtMaxPain < 0
      ? {}
      : { total_loss_at_max_pain: totalLossAtMaxPain }),
    strike_losses: strikeLosses,
    strikes,
  };
}

type SyntheticFutureChainRow = {
  strike: number;
  ceLtp: number;
  peLtp: number;
};

function optionLegLtp(value: unknown): number {
  const row = isRecord(value) ? value : {};
  return toNumber(row.ltp ?? row.last_price ?? row.lastPrice);
}

function syntheticRowsFromChain(value: unknown): SyntheticFutureChainRow[] {
  if (!isRecord(value)) return [];
  if (Array.isArray(value.chain)) {
    return value.chain.filter(isRecord).map((row) => ({
      strike: toNumber(row.strike ?? row.strike_price),
      ceLtp: optionLegLtp(row.ce),
      peLtp: optionLegLtp(row.pe),
    })).filter((row) => row.strike > 0 && row.ceLtp > 0 && row.peLtp > 0);
  }
  if (Array.isArray(value.strikes)) {
    return value.strikes.filter(isRecord).map((row) => ({
      strike: toNumber(row.strikePrice ?? row.strike_price ?? row.strike),
      ceLtp: toNumber(row.ceLtp ?? row.ce_ltp ?? row.call_ltp),
      peLtp: toNumber(row.peLtp ?? row.pe_ltp ?? row.put_ltp),
    })).filter((row) => row.strike > 0 && row.ceLtp > 0 && row.peLtp > 0);
  }
  return [];
}

function nearestSyntheticRow(rows: SyntheticFutureChainRow[], target: number): SyntheticFutureChainRow | undefined {
  if (rows.length === 0) return undefined;
  if (!Number.isFinite(target) || target <= 0) return rows[Math.floor(rows.length / 2)];
  return rows.reduce((best, row) => (
    Math.abs(row.strike - target) < Math.abs(best.strike - target) ? row : best
  ), rows[0]);
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function syntheticFutureFromOptionChain(
  value: unknown,
  underlying: string,
  expiry: string | undefined,
): SyntheticFutureData {
  const rows = syntheticRowsFromChain(value);
  const source = isRecord(value) ? value : {};
  const target = toNumber(source.atm_strike ?? source.atmStrike ?? source.spotPrice ?? source.underlying_ltp);
  const row = nearestSyntheticRow(rows, target);
  if (!row) {
    throw new Error("Native option chain did not include call and put LTPs for synthetic future pricing.");
  }
  const syntheticPrice = round2(row.strike + row.ceLtp - row.peLtp);
  return {
    underlying,
    underlying_ltp: toNumber(
      source.underlying_ltp ?? source.spot_price ?? source.spotPrice ?? source.spot ?? syntheticPrice,
    ),
    expiry: String(expiry ?? source.expiry ?? ""),
    atm_strike: row.strike,
    synthetic_future_price: syntheticPrice,
  };
}

async function getNativeSyntheticFuture(
  symbol: string,
  exchange: string,
  expiry_date?: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<SyntheticFutureData | undefined> {
  expectedDataScope = captureMarketDataScope(expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (isExploreMode()) return undefined;
  const chain = await getOptionChain(symbol, exchange, expiry_date, signal, expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  return syntheticFutureFromOptionChain(chain, symbol, expiry_date);
}

function compactOptionSymbolResult(
  underlying: string,
  exchange: string,
  expiry_date: string,
  option_type: string,
  offset: string,
): { symbol: string; exchange: string } {
  const optionType = option_type.toUpperCase() === "PE" ? "PE" : "CE";
  const symbol = buildCompactOptionSymbol(underlying, expiry_date, offset, optionType);
  if (!symbol) {
    throw new Error("Option symbol requires underlying, expiry, strike, and option type.");
  }
  return { symbol, exchange };
}

function normaliseInstrumentList(value: InstrumentRow[] | { data?: InstrumentRow[]; instruments?: InstrumentRow[] }): InstrumentRow[] {
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.instruments)) return value.instruments;
  if (Array.isArray(value.data)) return value.data;
  return [];
}

function exchangesFromCapability(row: BackendBrokerCapabilityRow): string[] {
  if (Array.isArray(row.supported_exchanges)) return row.supported_exchanges.map(String);
  const exchanges = new Set<string>();
  if (row.supports_equity) {
    exchanges.add("NSE");
    exchanges.add("BSE");
  }
  if (row.supports_options || row.supports_futures) {
    exchanges.add("NFO");
    exchanges.add("BFO");
  }
  if (row.supports_currency) {
    exchanges.add("CDS");
    exchanges.add("BCD");
  }
  if (row.supports_commodities) exchanges.add("MCX");
  return Array.from(exchanges);
}

function normaliseBrokerCapabilities(value: BackendBrokerCapabilitiesData): BrokerCapabilities {
  const rows = value.capabilities ? [value.capabilities] : (value.brokers ?? []);
  const first = rows[0] ?? {};
  const supportedExchanges = Array.from(new Set(rows.flatMap(exchangesFromCapability))).sort();
  const features = rows.reduce<BrokerCapabilities["features"]>(
    (acc, row) => ({
      market_protection: acc.market_protection || row.market_protection === true,
      leverage: acc.leverage || row.leverage === true,
      bracket_orders: acc.bracket_orders || row.supports_bracket_orders === true,
      cover_orders: acc.cover_orders || row.supports_cover_orders === true,
    }),
    { market_protection: false, leverage: false, bracket_orders: false, cover_orders: false },
  );
  const brokerType = first.broker_type
    ?? (rows.some((row) => row.supports_commodities) && rows.some((row) => row.supports_equity || row.supports_options)
      ? "multi"
      : rows.some((row) => row.supports_commodities)
        ? "commodity"
        : "equity");

  return {
    broker_name: String(first.broker_name ?? value.broker ?? "FlintTrade"),
    broker_type: brokerType,
    supported_exchanges: supportedExchanges,
    features,
  };
}

function minuteIntervalLabel(minutes: number): string {
  if (minutes > 0 && minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

function intervalsFromCapability(value: BackendBrokerCapabilitiesData): string[] {
  const rows = value.capabilities ? [value.capabilities] : (value.brokers ?? []);
  const intervals = rows.flatMap((row) => {
    if (Array.isArray(row.historical_intervals) && row.historical_intervals.length > 0) {
      return row.historical_intervals.map(String);
    }
    const calendar = Array.isArray(row.historical_calendar_intervals)
      ? row.historical_calendar_intervals.map(String)
      : [];
    if (Array.isArray(row.historical_intraday_intervals_minutes)) {
      const intraday = row.historical_intraday_intervals_minutes
        .map((minutes) => Number(minutes))
        .filter((minutes) => Number.isFinite(minutes) && minutes > 0)
        .map(minuteIntervalLabel);
      return [...intraday, ...calendar];
    }
    return calendar;
  });
  return Array.from(new Set(intervals));
}

function nativeCapabilityBrokerFromStore(): string | undefined {
  const { accounts, activeAccountId } = useBrokerStore.getState();
  return resolveNativeDataAccount(accounts, activeAccountId)?.broker;
}

async function nativeCapabilityBroker(
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<string | undefined> {
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  const broker = nativeCapabilityBrokerFromStore();
  if (broker) return broker;
  const accounts = await awaitMarketDataAuthority(
    () => listLiveNativeReadAccounts(signal),
    signal,
    expectedDataScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  const account = pickNativeReadAccount(accounts);
  return account?.adapter_id;
}

async function getNativeIntervals(
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<string[] | undefined> {
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (isExploreMode()) return undefined;
  const broker = await nativeCapabilityBroker(signal, expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (!broker || isExploreMode()) return undefined;
  const endpoint = `broker/capabilities?broker=${encodeURIComponent(broker)}`;
  const intervals = intervalsFromCapability(await awaitMarketDataAuthority(
    () => getFtApi<BackendBrokerCapabilitiesData>(endpoint, signal),
    signal,
    expectedDataScope,
  ));
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  return intervals.length > 0 ? intervals : undefined;
}

function normaliseNativeRead(endpoint: string, value: unknown): unknown {
  if (endpoint === "funds") return normaliseFundsShape(value);
  if (endpoint === "history") return normaliseNativeHistory(value);
  if (endpoint === "quotes" || endpoint === "ticker") return normaliseNativeQuote(value);
  if (endpoint === "multiquotes") return normaliseNativeMultiQuotes(value);
  if (endpoint === "depth") return normaliseNativeDepth(value);
  if (endpoint === "margin") return normaliseNativeMargin(value);
  if (endpoint === "orderstatus") return normaliseNativeOrderStatus(value);
  if (endpoint === "holidays" || endpoint === "market/holidays") return normaliseNativeHolidays(value);
  if (endpoint === "timings" || endpoint === "market/timings") return normaliseNativeTimings(value);
  if (endpoint === "multioptiongreeks") return normaliseNativeGreeks(value);
  if (endpoint === "optiongreeks") return normaliseNativeGreeks(value)[0] ?? nativeGreeksRow({});
  if (endpoint === "expiry") return normaliseNativeExpiry(value);
  if (endpoint === "optionchain") return normaliseNativeOptionChain(value);
  if (endpoint === "search") return normaliseNativeSearch(value);
  if (endpoint === "symbol") return normaliseNativeSymbol(value);
  return value;
}

async function readPrimaryNative<T>(
  endpoint: string,
  extra: object = {},
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<T | undefined> {
  expectedDataScope = captureMarketDataScope(expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  const kind = NATIVE_READ_ENDPOINTS[endpoint];
  if (!kind) return undefined;
  const account = await awaitMarketDataAuthority(
    () => primaryNativeReadAccountFor(kind, signal, expectedDataScope),
    signal,
    expectedDataScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (!account || isExploreMode()) return undefined;
  if (NATIVE_ACCOUNT_SCOPED_KINDS.has(kind) && useModeStore.getState().mode !== "live") {
    return undefined;
  }
  const value = await awaitMarketDataAuthority(
    () => readNativeAccount<unknown>(
      account.adapter_id,
      account.account_id,
      kind,
      buildNativeReadParams(endpoint, extra),
      signal,
    ),
    signal,
    expectedDataScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  return normaliseNativeRead(endpoint, value) as T;
}

async function readRequiredPrimaryNative<T>(endpoint: string, extra: object = {}): Promise<T> {
  const value = await readPrimaryNative<T>(endpoint, extra);
  if (value !== undefined) return value;
  throw new Error(`A live native broker account is required for ${endpoint}.`);
}


function findMockQuote(symbol = "NIFTY", exchange = "NSE_INDEX"): Quote {
  const snapshot = mockDataEngine.getSnapshot();
  const match = snapshot.find((tick) => (
    tick.symbol === symbol || `${tick.exchange}:${tick.symbol}` === symbol
  )) ?? snapshot.find((tick) => tick.exchange === exchange) ?? snapshot[0];

  return {
    symbol: match?.symbol ?? symbol,
    exchange: match?.exchange ?? exchange,
    ltp: match?.ltp ?? 0,
    open: match?.open ?? 0,
    high: match?.high ?? 0,
    low: match?.low ?? 0,
    close: match?.close ?? 0,
    prev_close: match?.close ?? 0,
    volume: match?.volume ?? 0,
    change: match?.change ?? 0,
    pct: match?.changePct ?? 0,
  };
}

function makeMockSearch(
  query: string,
  exchange?: string,
): Array<{ symbol: string; exchange: string }> {
  const needle = query.trim().toUpperCase();
  if (!needle) return [];
  const exchangeFilter = exchange?.trim().toUpperCase();
  return mockDataEngine.getSnapshot()
    .filter((tick) => {
      if (!tick.symbol.toUpperCase().includes(needle)) return false;
      if (exchangeFilter && tick.exchange.toUpperCase() !== exchangeFilter) return false;
      return true;
    })
    .map((tick) => ({ symbol: tick.symbol, exchange: tick.exchange }));
}

const MOCK_HISTORY_BAR_COUNT = 96;

/** Seconds per Explore sample bar. Unknown intervals keep the historic 5-minute step. */
const MOCK_HISTORY_INTERVAL_SECONDS: Record<string, number> = {
  "1m": 60,
  "3m": 180,
  "5m": 300,
  "15m": 900,
  "30m": 1_800,
  "1h": 3_600,
  "4h": 14_400,
  "1D": 86_400,
  "1d": 86_400,
  D: 86_400,
  "1W": 604_800,
  "1w": 604_800,
  W: 604_800,
};

function mockHistoryIntervalSeconds(interval?: string): number {
  if (!interval) return 300;
  return MOCK_HISTORY_INTERVAL_SECONDS[interval] ?? 300;
}

function makeMockHistory(symbol?: string, exchange?: string, interval?: string): OHLCVBar[] {
  const quote = findMockQuote(symbol, exchange);
  const step = mockHistoryIntervalSeconds(interval);
  const now = Math.floor(Date.now() / 1000);
  // Calendar intervals align to midnight UTC so the time scale shows dates,
  // not an 8-hour intraday clock leftover from the 5-minute sample.
  const end = step >= 86_400 ? now - (now % 86_400) : now;
  return Array.from({ length: MOCK_HISTORY_BAR_COUNT }, (_, index) => {
    const drift = Math.sin(index / 6) * quote.ltp * 0.002;
    const open = quote.ltp + drift;
    const close = open + Math.cos(index / 5) * quote.ltp * 0.0015;
    return {
      timestamp: end - (MOCK_HISTORY_BAR_COUNT - 1 - index) * step,
      open,
      high: Math.max(open, close) + quote.ltp * 0.001,
      low: Math.min(open, close) - quote.ltp * 0.001,
      close,
      volume: Math.max(1, Math.round(quote.volume / 100 + index * 37)),
    };
  });
}


function makeMockExpiries(count = 4): string[] {
  const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  const expiries: string[] = [];
  const cursor = new Date();
  cursor.setDate(cursor.getDate() + ((4 - cursor.getDay() + 7) % 7 || 7)); // next Thursday
  for (let i = 0; i < count; i++) {
    const dd = String(cursor.getDate()).padStart(2, "0");
    expiries.push(`${dd}-${months[cursor.getMonth()]}-${String(cursor.getFullYear()).slice(-2)}`);
    cursor.setDate(cursor.getDate() + 7);
  }
  return expiries;
}


function makeMockOptionChain(symbol = "NIFTY", exchange = "NSE_INDEX"): Record<string, unknown> {
  const spot = findMockQuote(symbol, exchange).ltp || 24_150;
  const step = spot > 40_000 ? 100 : spot > 8_000 ? 50 : Math.max(2.5, Math.round(spot * 0.01));
  const atm = Math.round(spot / step) * step;
  const chain = Array.from({ length: 21 }, (_, index) => {
    const offset = index - 10;
    const strike = atm + offset * step;
    const distance = Math.abs(offset);
    const makeLeg = (optionType: "CE" | "PE", oiBias: number) => ({
      ltp: sampleChainOptionLtp(spot, strike, step, optionType),
      oi: Math.round((120_000 - distance * 8_000 + oiBias) * (1 + (distance % 3) * 0.1)),
      volume: Math.max(500, 40_000 - distance * 3_200),
      iv: Math.round((12 + distance * distance * 0.18 + (oiBias > 0 ? 0.6 : 0)) * 100) / 100,
      delta: null,
      gamma: null,
      theta: null,
      vega: null,
    });
    return {
      strike,
      ce: makeLeg("CE", offset > 0 ? 15_000 : 0),
      pe: makeLeg("PE", offset < 0 ? 15_000 : 0),
    };
  });
  const totalCallOi = chain.reduce((sum, row) => sum + row.ce.oi, 0);
  const totalPutOi = chain.reduce((sum, row) => sum + row.pe.oi, 0);
  return {
    chain,
    atm_strike: atm,
    underlying_ltp: spot,
    underlying_prev_close: spot,
    pcr: totalCallOi > 0 ? Math.round((totalPutOi / totalCallOi) * 100) / 100 : null,
    is_sample_data: true,
  };
}

function mockOrders(): Order[] {
  return mockDataEngine.getMockOrders().map((order) => ({
    orderId: order.orderId,
    symbol: order.symbol,
    exchange: order.exchange,
    action: order.side,
    quantity: order.quantity,
    price: order.price,
    orderType: order.orderType,
    status: order.status,
    product: order.product,
    strategy: "Example",
    timestamp: order.timestamp,
  }));
}

function mockPositions(): Position[] {
  return mockDataEngine.getMockPositions().map((position) => ({
    symbol: position.symbol,
    exchange: position.exchange,
    product: position.product,
    quantity: position.quantity,
    averagePrice: position.avgPrice,
    ltp: position.ltp,
    pnl: position.pnl,
    pnlPercent: position.avgPrice > 0 ? (position.pnl / (position.avgPrice * position.quantity)) * 100 : 0,
  }));
}

function mockHoldings(): Holding[] {
  return mockDataEngine.getMockHoldings().map((holding) => ({
    symbol: holding.symbol,
    exchange: holding.exchange,
    quantity: holding.quantity,
    averagePrice: holding.avgPrice,
    ltp: holding.ltp,
    pnl: holding.pnl,
    pnlPercent: holding.pnlPct,
  }));
}

function mockTrades(): Trade[] {
  return mockOrders()
    .filter((order) => ["complete", "completed", "filled"].includes(order.status.toLowerCase()))
    .map((order) => ({
      tradeId: order.orderId,
      orderId: order.orderId,
      symbol: order.symbol,
      exchange: order.exchange,
      action: order.action,
      quantity: order.quantity,
      price: order.price,
      timestamp: order.timestamp,
    }));
}

function normalisePracticePosition(value: unknown): Position | undefined {
  if (!isRecord(value)) return undefined;
  const quantity = toNumber(value.quantity ?? value.net_qty);
  const averagePrice = toNumber(value.averagePrice ?? value.average_price ?? value.avg_price);
  const realisedPnl = toNumber(value.realised_pnl ?? value.realized_pnl);
  const unrealisedPnl = toNumber(value.unrealised_pnl ?? value.unrealized_pnl);
  const pnl = toNumber(value.pnl ?? (realisedPnl + unrealisedPnl));
  const ltp = quantity !== 0 && unrealisedPnl !== 0
    ? averagePrice + (unrealisedPnl / quantity)
    : toNumber(value.ltp ?? averagePrice);
  const cost = Math.abs(quantity * averagePrice);
  const priceSourceRaw = String(value.priceSource ?? value.price_source ?? "");
  const priceSource = priceSourceRaw === "ltp" || priceSourceRaw === "last_close"
    ? priceSourceRaw
    : undefined;
  const ageRaw = value.priceAgeS ?? value.price_age_s;
  const priceAgeS = ageRaw === null || ageRaw === undefined || ageRaw === ""
    ? undefined
    : toNumber(ageRaw);
  const hasLiveMark = quantity !== 0 && unrealisedPnl !== 0;
  const ltpBasis = priceSource === "last_close" && !hasLiveMark ? "last_close" as const : undefined;
  return {
    symbol: String(value.symbol ?? ""),
    exchange: String(value.exchange ?? ""),
    product: String(value.product ?? "MIS"),
    quantity,
    averagePrice,
    ltp,
    pnl,
    pnlPercent: cost > 0 ? (pnl / cost) * 100 : 0,
    restored: value.restored === true,
    ...(priceSource ? { priceSource } : {}),
    ...(priceAgeS !== undefined ? { priceAgeS } : {}),
    ...(ltpBasis ? { ltpBasis } : {}),
  };
}

function normalisePracticeOrder(value: unknown): Order | undefined {
  if (!isRecord(value)) return undefined;
  const orderId = String(value.orderId ?? value.order_id ?? "");
  if (!orderId) return undefined;
  const action = String(value.action ?? "BUY").toUpperCase() === "SELL" ? "SELL" : "BUY";
  const triggerPrice = toStrictNumber(value.trigger_price ?? value.triggerPrice);
  return {
    orderId,
    symbol: String(value.symbol ?? ""),
    exchange: String(value.exchange ?? ""),
    action,
    quantity: toNumber(value.quantity),
    price: toNumber(value.price ?? value.avg_fill_px),
    orderType: String(value.orderType ?? value.order_type ?? "MARKET"),
    status: String(value.status ?? ""),
    product: String(value.product ?? "MIS"),
    strategy: String(value.strategy ?? "Practice"),
    timestamp: String(value.timestamp ?? value.created_at ?? ""),
    ...(triggerPrice !== null ? { triggerPrice } : {}),
  };
}

function normalisePracticeTrade(value: unknown): Trade | undefined {
  if (!isRecord(value)) return undefined;
  const orderId = String(value.orderId ?? value.order_id ?? "");
  const tradeId = String(value.tradeId ?? value.trade_id ?? orderId);
  if (!tradeId || !orderId) return undefined;
  const action = String(value.action ?? "BUY").toUpperCase() === "SELL" ? "SELL" : "BUY";
  const exchange = String(value.exchange ?? "");
  const breakdown = isRecord(value.charges_breakdown) ? value.charges_breakdown : undefined;
  const storedLabel = breakdown ? String(breakdown.exchange_label ?? "") : "";
  const estimatedCharges = breakdown
    ? {
        total: toNumber(breakdown.total ?? value.charges),
        stt: toNumber(breakdown.stt),
        exchangeCharges: toNumber(breakdown.exchange_charges),
        exchangeLabel: exchange.trim().length > 0
          ? exchangeTransactionLabel(exchange)
          : (storedLabel || "NSE transaction"),
        sebiFee: toNumber(breakdown.sebi_fee),
        stampDuty: toNumber(breakdown.stamp_duty),
        gst: toNumber(breakdown.gst),
      }
    : undefined;
  return {
    tradeId,
    orderId,
    symbol: String(value.symbol ?? ""),
    exchange,
    action,
    quantity: toNumber(value.quantity),
    price: toNumber(value.price ?? value.fill_price ?? value.avg_fill_px),
    timestamp: String(value.timestamp ?? value.traded_at ?? value.fill_time ?? ""),
    ...(typeof value.strategy === "string" && value.strategy
      ? { strategy: value.strategy }
      : {}),
    ...(estimatedCharges ? { estimatedCharges } : {}),
  };
}

async function getPracticeOrders(signal?: AbortSignal): Promise<Order[]> {
  const payload = await getFtV1<{ orders?: unknown[] }>("sandbox/orders", signal);
  return (payload.orders ?? []).map(normalisePracticeOrder).filter((order): order is Order => order !== undefined);
}

async function getPracticeTrades(signal?: AbortSignal): Promise<Trade[]> {
  const payload = await getFtV1<{ trades?: unknown[] }>("sandbox/trades", signal);
  return (payload.trades ?? [])
    .map(normalisePracticeTrade)
    .filter((trade): trade is Trade => trade !== undefined);
}

/** Read account data from the same sandbox that executes Practice orders. */
async function readPracticeAccountData<T>(
  endpoint: string,
  extra: object = {},
  mode = useModeStore.getState().mode,
  signal?: AbortSignal,
): Promise<T | undefined> {
  if (mode !== "practice") return undefined;
  const kind = NATIVE_READ_ENDPOINTS[endpoint];
  if (!kind || !NATIVE_ACCOUNT_SCOPED_KINDS.has(kind)) return undefined;

  if (endpoint === "funds") {
    const payload = await getFtV1<{ funds?: unknown }>("sandbox/funds", signal);
    const row = isRecord(payload.funds) ? payload.funds : {};
    // Practice get_funds: available_balance is after margin, current_balance
    // is the untouched ledger, and ledger_balance has option premium and
    // equity notional applied. futures_mtm_in_ledger is false.
    return normaliseFundsShape({
      available_balance: row.available_balance,
      used_margin: row.used_margin,
      total_balance: row.current_balance,
      ledger_balance: row.ledger_balance,
      futures_mtm_in_ledger: row.futures_mtm_in_ledger,
      estimated_charges: row.estimated_charges,
    }) as T;
  }
  if (endpoint === "limits") {
    const payload = await getFtV1<{ capital?: unknown }>("sandbox/capital", signal);
    const capital = isRecord(payload.capital) ? payload.capital : {};
    return capital as T;
  }
  if (endpoint === "positionbook") {
    const payload = await getFtV1<{ positions?: unknown[] }>("sandbox/positions", signal);
    const positions = (payload.positions ?? [])
      .map(normalisePracticePosition)
      .filter((position): position is Position => position !== undefined);
    return { positions } as T;
  }
  if (endpoint === "orderbook") {
    return { orders: await getPracticeOrders(signal) } as T;
  }
  if (endpoint === "tradebook") {
    return { trades: await getPracticeTrades(signal) } as T;
  }
  if (endpoint === "holdings") {
    return { holdings: [] } as T;
  }
  if (endpoint === "orderstatus") {
    const params = extra as Record<string, unknown>;
    const orderId = stringParam(params.order_id ?? params.orderId ?? params.orderid);
    const order = (await getPracticeOrders(signal)).find((candidate) => candidate.orderId === orderId);
    return { status: order?.status ?? "not found" } as T;
  }

  throw new Error(`${endpoint} is not available from the Practice sandbox.`);
}

function expectedNativeScope(brokerType: string, accountId: string): string {
  return ["live", "native", brokerType, accountId].map(encodeURIComponent).join(":");
}


/**
 * Read an account endpoint from the immutable source encoded by its query key.
 * This path never re-selects an account from mutable stores after an await.
 */
async function readAccountSnapshot<T>(
  endpoint: string,
  extra: object,
  context: AccountReadContext,
  signal?: AbortSignal,
): Promise<T> {
  if (!context) throw new Error(`Account read context is required for ${endpoint}.`);
  if (!context.enabled) throw new Error(`Account reads are unavailable for ${endpoint}.`);
  if (!generalLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for ${endpoint} (general: 50/s)`);
  }

  const { identity } = context;
  if (identity.mode === "practice") {
    if (
      identity.scopeKey !== "practice:sandbox:default"
      || identity.brokerType !== "sandbox"
      || identity.accountId !== "default"
    ) {
      throw new Error(`Account identity mismatch for ${endpoint}.`);
    }
    const value = await readPracticeAccountData<T>(endpoint, extra, "practice", signal);
    if (value !== undefined) return value;
    throw new Error(`${endpoint} is not available from the Practice sandbox.`);
  }

  if (identity.mode !== "live") {
    throw new Error(`${endpoint} is not available in ${identity.mode} mode.`);
  }
  if (
    identity.brokerType === "unconfigured"
    || identity.scopeKey !== expectedNativeScope(identity.brokerType, identity.accountId)
  ) {
    throw new Error(`Account identity mismatch for ${endpoint}.`);
  }

  const kind = NATIVE_READ_ENDPOINTS[endpoint];
  if (!kind || !NATIVE_ACCOUNT_SCOPED_KINDS.has(kind)) {
    throw new Error(`${endpoint} is not an account-scoped read.`);
  }
  const value = await readNativeAccount<unknown>(
    identity.brokerType,
    identity.accountId,
    kind,
    buildNativeReadParams(endpoint, extra),
    signal,
  );
  return normaliseNativeRead(endpoint, value) as T;
}

function getExplorePostFallback<T>(endpoint: string, extra: object): T | undefined {
  const params = extra as Record<string, unknown>;
  const symbol = typeof params.symbol === "string" ? params.symbol : undefined;
  const exchange = typeof params.exchange === "string" ? params.exchange : undefined;

  switch (endpoint) {
    case "quotes":
    case "ticker":
      return findMockQuote(symbol, exchange) as T;
    case "multiquotes": {
      const symbols = Array.isArray(params.symbols)
        ? params.symbols as Array<{ symbol?: string; exchange?: string }>
        : [];
      const results = symbols.map((item) => ({
        symbol: item.symbol ?? "NIFTY",
        exchange: item.exchange ?? "NSE_INDEX",
        data: findMockQuote(item.symbol, item.exchange),
      }));
      return { results } as T;
    }
    case "history": {
      const interval = typeof params.interval === "string" ? params.interval : undefined;
      return makeMockHistory(symbol, exchange, interval) as T;
    }
    case "expiry":
      return { expiry: makeMockExpiries() } as T;
    case "optionchain": {
      const underlying = typeof params.underlying === "string" ? params.underlying : symbol;
      return makeMockOptionChain(underlying, exchange) as T;
    }
    case "search": {
      const query = typeof params.query === "string" ? params.query : "";
      return makeMockSearch(query, exchange) as T;
    }
    case "symbol":
      return {
        symbol: symbol ?? "NIFTY",
        name: symbol ?? "NIFTY",
        exchange: exchange ?? "NSE_INDEX",
        instrumenttype: "INDEX",
        lotsize: 1,
        tick_size: 0.05,
      } as T;
    case "funds":
      return {
        availableCash: 250_000,
        usedMargin: 48_500,
        totalBalance: 298_500,
      } as T;
    case "margin":
      return {
        total_margin_required: 0,
        span_margin: 0,
        exposure_margin: 0,
      } as T;
    case "orderbook":
      return { orders: mockOrders() } as T;
    case "tradebook":
      return { trades: mockTrades() } as T;
    case "positionbook":
      return { positions: mockPositions() } as T;
    case "holdings":
      return { holdings: mockHoldings() } as T;
    case "holidays":
    case "market/holidays":
      return [] as T;
    case "intervals":
      return ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as T;
    case "timings":
    case "market/timings":
      return [
        { exchange: "NSE", start_time: 915, end_time: 1530 },
        { exchange: "BSE", start_time: 915, end_time: 1530 },
        { exchange: "MCX", start_time: 900, end_time: 2330 },
      ] as T;
    default:
      return undefined;
  }
}

function getExploreGetFallback<T>(endpoint: string): T | undefined {
  switch (endpoint) {
    case "intervals":
      return ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as T;
    case "../broker/capabilities":
      return getExploreBrokerCapabilities() as T;
    default:
      return undefined;
  }
}

function getExploreBrokerCapabilities(): BrokerCapabilities {
  return {
    broker_name: "Example",
    broker_type: "multi",
    supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
    features: {
      market_protection: false,
      leverage: false,
      bracket_orders: false,
      cover_orders: false,
    },
  };
}

/**
 * Error thrown by `postOrder` when the backend answers non-2xx.
 *
 * Carries the HTTP status and the parsed JSON error body so callers can render
 * structured failure states instead of only the first error message — most
 * critically the 422 partial-failure `BasketOrderResult` from the basket route
 * (order_routes `place_basket`), where the per-leg detail says which legs are
 * live and whether their rollback was confirmed. Extends `Error` with the same
 * message as before, so existing `catch (e) { (e as Error).message }` sites
 * keep working unchanged.
 */
export class OrderApiError extends Error {
  /** HTTP status code of the failed response. */
  readonly status: number;
  /** Parsed JSON body of the failed response, or `null` when it was not JSON. */
  readonly body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "OrderApiError";
    this.status = status;
    this.body = body;
  }
}


type ModeOrderAuthorityPin = {
  /**
   * Immutable mode captured at the irreversible UI boundary (e.g. Practice
   * review confirm). Must still match the live mode store when the request
   * begins; the pin is also what headers/routing use so a later store flip
   * cannot retarget a Practice payload onto Live/native.
   */
  mode: "practice" | "live";
};

/** Exact immutable account/query provenance required by order mutations. */
export type OrderAuthorityPin = AccountAuthorityIdentity;

type PostOrderAuthorityPin = ModeOrderAuthorityPin | OrderAuthorityPin;

/** Client-only. Never sent on the body. The server decides reduce-only. */
export type PlaceOrderOptions = {
  exit?: boolean;
};

function isExactOrderAuthorityPin(
  authority: unknown,
): authority is OrderAuthorityPin {
  return authority !== null
    && typeof authority === "object"
    && "scopeKey" in authority
    && "brokerType" in authority
    && "accountId" in authority;
}

function isRuntimeOrderMutationAuthorityPin(authority: unknown): authority is OrderAuthorityPin {
  if (!isExactOrderAuthorityPin(authority)) return false;
  const { mode, scopeKey, brokerType, accountId } = authority;
  if (
    typeof scopeKey !== "string"
    || typeof brokerType !== "string"
    || typeof accountId !== "string"
    || !scopeKey
    || !brokerType
    || !accountId
  ) return false;
  if (mode === "practice") {
    return scopeKey === "practice:sandbox:default"
      && brokerType === "sandbox"
      && accountId === "default";
  }
  if (mode !== "live") return false;
  return scopeKey === `live:native:${encodeURIComponent(brokerType)}:${encodeURIComponent(accountId)}`;
}

function exactOrderAuthorityMatchesCurrent(
  authority: OrderAuthorityPin,
  currentMode: "explore" | "practice" | "live",
): boolean {
  const { apiKey } = useConnectionStore.getState();
  const { accounts, activeAccountId } = useBrokerStore.getState();

  const current = resolveAccountAuthorityIdentity({
    mode: currentMode,
    accounts,
    activeAccountId,
  });
  if (
    authority.mode !== current.mode
    || authority.scopeKey !== current.scopeKey
    || authority.brokerType !== current.brokerType
    || authority.accountId !== current.accountId
  ) return false;

  if (authority.mode !== "live") return true;
  const nativeTarget = pickNativeWriteTarget(currentMode, apiKey);
  return nativeTarget?.broker === authority.brokerType
    && nativeTarget.accountId === authority.accountId;
}

/**
 * Explore paper fill. Never contacts the order proxy, SafetySystem, or a
 * broker — Explore has no live session.
 */
function placeExploreSampleOrder(params: PlaceOrderParams): { orderId: string } {
  const stamp = Date.now().toString(36).toUpperCase();
  const symbol = params.symbol.replace(/[^A-Z0-9]/gi, "").slice(0, 12) || "ORDER";
  return { orderId: `SAMPLE-${symbol}-${stamp}` };
}

const LIVE_PLACE_ENDPOINTS = new Set([
  "place",
  "basket",
  "split",
  "options",
  "options-multi",
]);

async function postOrder<T>(
  ftEndpoint: string,
  body: object = {},
  authority?: PostOrderAuthorityPin,
  options?: PlaceOrderOptions,
): Promise<T> {
  // Explore paper fill for place only. Checked before the generic mode-pin
  // mismatch so Order Pad can confirm with a Practice pin while the store is
  // still Explore. Live pins are still refused. The `placeOrder` export must
  // stay a brace-depth-0 `postOrder("place", …)` call so the orders-contract
  // lexer keeps seeing the Live frontend caller.
  const currentModeForExplore = useModeStore.getState().mode;
  if (currentModeForExplore === "explore" && ftEndpoint === "place") {
    if (authority?.mode === "live") {
      throw new Error(
        `Order blocked: mode changed from ${operatorModeName(authority.mode, false)} to ${operatorModeName(currentModeForExplore, false)} before submission.`,
      );
    }
    return placeExploreSampleOrder(body as PlaceOrderParams) as T;
  }

  if (!orderLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for ${ftEndpoint} (order: 10/s)`);
  }

  // Read the current operating mode and auth state to assemble headers.
  const currentMode = useModeStore.getState().mode;
  if (authority?.mode && authority.mode !== currentMode) {
    throw new Error(
      `Order blocked: mode changed from ${operatorModeName(authority.mode, false)} to ${operatorModeName(currentMode, false)} before submission.`,
    );
  }
  if (isExactOrderAuthorityPin(authority) && !exactOrderAuthorityMatchesCurrent(authority, currentMode)) {
    throw new Error(
      "Order blocked: the displayed account authority no longer matches the current source, scope, account, or connection.",
    );
  }
  // Prefer the pinned authority mode so in-flight Practice confirms keep the
  // sandbox header/routing even if the store flips after the equality check.
  const mode = authority?.mode ?? currentMode;
  if (mode === "live" && LIVE_PLACE_ENDPOINTS.has(ftEndpoint)) {
    const incident = readOperatorIncident();
    const layaExit = options?.exit === true && incident?.failureClass === "laya";
    if (liveWritesMuted(incident) && !layaExit) {
      const message = incident?.failureClass === "laya"
        ? incident.headline
        : (incident?.rectify ?? "Live orders are closed.");
      throw new Error(message);
    }
  }
  const apiKey = useConnectionStore.getState().apiKey;
  const jwt = useAuthStore.getState().token;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-FlintTrade-Mode": mode,
  };
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (jwt) headers["Authorization"] = `Bearer ${jwt}`;

  const normalisedBody = normaliseOrderBody(body);
  // Fail closed before resolving a target: if the operator's selected active
  // account is native but not confirmed connected yet (e.g. the post-reload
  // window before the first account poll), reject rather than let the order fall
  // through to the bare path and be silently retargeted to brokers.execution.default.
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  const pinnedTarget = isExactOrderAuthorityPin(authority) && authority.mode === "live"
    ? { broker: authority.brokerType, accountId: authority.accountId }
    : undefined;
  const nativeTarget = pinnedTarget ?? pickNativeWriteTarget(mode, apiKey);
  const isNativeRoutedEndpoint = nativeTarget !== undefined && NATIVE_ROUTED_ORDER_ENDPOINTS.has(ftEndpoint);
  const orderPath = isNativeRoutedEndpoint
    ? `${encodeURIComponent(nativeTarget.broker)}/${ftEndpoint}`
    : ftEndpoint;
  const requestBody = nativeTarget !== undefined && (
    isNativeRoutedEndpoint || TARGET_IN_BODY_ORDER_ENDPOINTS.has(ftEndpoint)
  )
    ? { ...normalisedBody, broker: nativeTarget.broker, account_id: nativeTarget.accountId }
    : normalisedBody;

  let resp: Response;
  try {
    resp = await fetch(`${getFtBase()}/api/v1/orders/${orderPath}`, {
      method: "POST",
      headers,
      body: JSON.stringify(requestBody),
    });
  } catch {
    throw new Error("Connection failed. Check FlintTrade backend is running.");
  }

  if (!resp.ok) {
    const errorBody = await resp.json().catch(() => null) as {
      message?: string;
      error?: string;
      code?: string;
      reason?: string;
    } | null;
    if (layaOrderRefused(errorBody)) {
      useOperatorSignalStore.getState().noteLayaDown();
    }
    const serverMsg = errorBody?.message ?? errorBody?.error ?? null;
    let message: string;
    if (resp.status === 401) {
      message = "API key invalid. Check Settings → Connection.";
    } else if (resp.status === 400) {
      message = serverMsg ?? "Invalid order parameters. Check symbol and exchange.";
    } else if (resp.status === 403) {
      // Backend returns 403 when mode blocks the action (e.g. real order in practice mode)
      message = serverMsg ?? `Order blocked in ${mode} mode.`;
    } else if (resp.status === 500) {
      message = serverMsg ?? "FlintTrade backend error. Try again in a few seconds.";
    } else {
      message = serverMsg ?? `Server error (${resp.status})`;
    }
    // Attach the status + parsed body so callers can render structured failure
    // states — e.g. the 422 BasketOrderResult with per-leg rollback truth.
    throw new OrderApiError(message, resp.status, errorBody);
  }

  const json = await resp.json();
  const responseStatus = String(json.status ?? "").toUpperCase();
  if (responseStatus === "ERROR" || responseStatus === "REJECTED") {
    throw new Error(json.message || `Order API ${ftEndpoint} error`);
  }
  if (LIVE_PLACE_ENDPOINTS.has(ftEndpoint)) noteAdmittedPlace(mode);
  return (json.data ?? json) as T;
}

function noteAdmittedPlace(mode: string): void {
  const state = useOperatorSignalStore.getState();
  const confirmed = mode === "live"
    ? state.decisionStatus === "ready" || state.decisionStatus === "degraded"
    : state.layaPracticeStatus === "ready" || state.layaPracticeStatus === "degraded";
  if (!confirmed) state.noteLayaUnconfirmed();
}

async function postOrderMutation<T>(
  ftEndpoint: "cancel" | "modify",
  body: object,
  authority: OrderAuthorityPin,
): Promise<T> {
  if (!isRuntimeOrderMutationAuthorityPin(authority)) {
    throw new Error("Order blocked: cancel and modify require exact supported account authority.");
  }
  return postOrder<T>(ftEndpoint, body, authority);
}

async function post<T>(
  endpoint: string,
  extra: object = {},
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<T> {
  const capturedScope = captureMarketDataScope(expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(capturedScope);
  // Enforce rate limits before making the request
  if (SMART_ORDER_ENDPOINTS.has(endpoint)) {
    if (!smartOrderLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (smart order: 2/s)`);
    }
  } else if (ORDER_ENDPOINTS.has(endpoint)) {
    if (!orderLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (order: 10/s)`);
    }
  } else {
    if (!generalLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (general: 50/s)`);
    }
  }

  if (isExploreMode()) {
    const fallback = getExplorePostFallback<T>(endpoint, extra);
    if (fallback !== undefined) return fallback;
    const kind = NATIVE_READ_ENDPOINTS[endpoint];
    if (kind && NATIVE_ACCOUNT_SCOPED_KINDS.has(kind)) {
      throw new Error(`${endpoint} is not available in this session.`);
    }
  }

  const practiceRead = await awaitMarketDataAuthority(
    () => readPracticeAccountData<T>(endpoint, extra),
    signal,
    capturedScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(capturedScope);
  if (practiceRead !== undefined) return practiceRead;

  const nativeRead = await awaitMarketDataAuthority(
    () => readPrimaryNative<T>(endpoint, extra, signal, capturedScope),
    signal,
    capturedScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(capturedScope);
  if (nativeRead !== undefined) return nativeRead;

  if (isExploreMode()) {
    const fallback = getExplorePostFallback<T>(endpoint, extra);
    if (fallback !== undefined) return fallback;
  }
  throw new Error(`A connected native broker account is required for ${endpoint}.`);
}

// --- Orders (routed through FlintTrade safety proxy) ---
//
// The leaf names below MUST match the backend route registrations:
//
//   core   orders_bp at /api/v1/orders : place, modify, cancel, cancel-all,
//                                        options, options-multi
//   engine order_bp  at /api/v1/orders : basket, split, options-strategy
//
// Practice opens and closes are `place` (an opposite MARKET order for a
// close). Pre-2026-05-19 this file mixed FT-proxy names (place,
// openposition, basketorder, splitorder, optionsorder, optionsmultiorder),
// so half the order endpoints 404'd in production. Codex stop-gate review
// caught the mismatch on 2026-05-19 (task-mpcpfmws-5rokaa). A follow-up
// review then flagged that `optionsOrder` / `optionsMultiOrder` had been
// FT mode/safety gate. Both endpoints are now backed by /options and
// `optionsorder` and `optionsmultiorder` through `_dispatch_order`, so
// every options trade is mode-gated identically to a regular order.
//
// `orderStatus` is a read-only query. Native-only workspaces route it through
// path for bridge parity.
export const placeOrder = (
  params: PlaceOrderParams,
  authority?: PostOrderAuthorityPin,
  options?: PlaceOrderOptions,
) => postOrder<{ orderId: string }>("place", params, authority, options);
export const cancelAllOrders = () =>
  postOrder<void>("cancel-all");
export const cancelOrder = (
  orderId: string,
  strategy: string,
  authority: OrderAuthorityPin,
) => postOrderMutation<void>("cancel", { orderId, strategy }, authority);

const PRACTICE_SQUARE_OFF_PRODUCTS = new Set(["MIS", "CNC", "NRML"]);

function practiceSquareOffFailure(symbol: string, err: unknown): string {
  if (err instanceof OrderApiError && err.body && typeof err.body === "object") {
    const body = err.body as Record<string, unknown>;
    if (body.code === "laya_denied") {
      const reason = typeof body.reason === "string" && body.reason
        ? body.reason
        : err.message;
      const limits = body.limits;
      const max = limits && typeof limits === "object"
        ? (limits as { max_quantity?: unknown }).max_quantity
        : null;
      const limitsLine = typeof max === "number" && Number.isInteger(max) && max >= 1
        ? ` Max quantity ${max}.`
        : "";
      return `${symbol}: Laya denied. ${reason}${limitsLine}`;
    }
    if (body.code === "laya_clamp" && typeof body.message === "string" && body.message) {
      return `${symbol}: ${body.message}`;
    }
  }
  const message = err instanceof Error ? err.message : "Square-off failed.";
  return `${symbol}: ${message}`;
}

/** Place one opposite MARKET order per open Practice position. */
async function squareOffPracticePositions(): Promise<void> {
  const pinnedMode = "practice" as const;
  const payload = await getFtV1<{ positions?: unknown[] }>("sandbox/positions");
  const modeAfterFetch = useModeStore.getState().mode;
  if (modeAfterFetch !== pinnedMode) {
    throw new Error(
      `Order blocked: mode changed from ${pinnedMode} to ${modeAfterFetch} before submission.`,
    );
  }
  const positions = (payload.positions ?? [])
    .map(normalisePracticePosition)
    .filter((position): position is Position => position !== undefined)
    .filter((position) => position.quantity !== 0);
  const failures: string[] = [];
  for (const position of positions) {
    const product = position.product.toUpperCase();
    if (!PRACTICE_SQUARE_OFF_PRODUCTS.has(product)) {
      failures.push(
        `${position.symbol}: unrecognised product${position.product ? ` ${position.product}` : ""}`,
      );
      continue;
    }
    const price = position.ltp > 0
      ? position.ltp
      : position.averagePrice > 0
        ? position.averagePrice
        : 0;
    try {
      await postOrder("place", {
        symbol: position.symbol,
        exchange: position.exchange,
        action: position.quantity > 0 ? "SELL" : "BUY",
        product: product as "MIS" | "CNC" | "NRML",
        orderType: "MARKET",
        quantity: Math.abs(position.quantity),
        price,
        triggerPrice: 0,
        strategy: "FlintPositions",
      }, { mode: pinnedMode }, { exit: true });
    } catch (err) {
      failures.push(practiceSquareOffFailure(position.symbol, err));
    }
  }
  if (failures.length > 0) {
    throw new Error(failures.join("\n"));
  }
}

export const exitAllPositions = () => {
  const mode = useModeStore.getState().mode;
  if (mode === "practice") {
    return squareOffPracticePositions();
  }
  const apiKey = useConnectionStore.getState().apiKey;
  if (mode !== "live") {
    throw new Error("Exit all positions is available only in Live mode. Use the Positions widget for practice trades.");
  }
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  const nativeTarget = pickNativeWriteTarget(mode, apiKey);
  if (!nativeTarget) throw new Error("A connected trading-capable native broker is required.");
  const target = { broker: nativeTarget.broker, account_id: nativeTarget.accountId };
  return postFtApiWithMode<void>("positions/exit-all", { confirm: true, ...target }, mode);
};
export const modifyOrder = (params: ModifyOrderParams, authority: OrderAuthorityPin) =>
  postOrderMutation<{ orderId: string }>("modify", params, authority);
export const orderStatus = (params: OrderStatusParams) =>
  post<{ status: string }>("orderstatus", params);
// The backend basket route (order_routes `place_basket`) reads a `legs` array
// with snake_case per-leg fields; `normaliseOrderBody` only aliases top-level
// keys, so the nested legs are mapped onto the wire contract here. `price` /
// `trigger_price` are omitted when unset — the backend treats an absent key as
// None (MARKET legs must not arrive as price 0 LIMIT-alikes).
export const basketOrder = (params: BasketOrderParams) =>
  postOrder<BasketOrderResult>("basket", {
    strategy: params.strategy ?? "basket",
    legs: params.orders.map((leg) => ({
      symbol: leg.symbol,
      exchange: leg.exchange,
      action: leg.action,
      quantity: leg.quantity,
      order_type: leg.orderType,
      product: leg.product,
      ...(leg.price !== undefined ? { price: leg.price } : {}),
      ...(leg.triggerPrice !== undefined ? { trigger_price: leg.triggerPrice } : {}),
    })),
  });
export const optionsOrder = (params: OptionsOrderParams) =>
  postOrder<{ orderId: string }>("options", params);
export const optionsMultiOrder = (params: OptionsMultiOrderParams) =>
  postOrder<{ orderId: string }>("options-multi", params);
// The backend split route (order_routes `place_split`) requires snake_case
// total_qty / chunk_size (delay_seconds optional) and 400s without them;
// `normaliseOrderBody` only aliases its fixed top-level set, so the wire
// fields are mapped here the same way basketOrder maps its legs.
export const splitOrder = (params: SplitOrderParams) =>
  postOrder<{ orderId: string }>("split", {
    symbol: params.symbol,
    exchange: params.exchange,
    action: params.action,
    total_qty: params.totalQuantity,
    chunk_size: params.chunkSize,
    order_type: params.orderType,
    product: params.product,
    ...(params.price !== undefined ? { price: params.price } : {}),
    ...(params.triggerPrice !== undefined ? { trigger_price: params.triggerPrice } : {}),
    ...(params.delaySeconds !== undefined ? { delay_seconds: params.delaySeconds } : {}),
    ...(params.strategy !== undefined ? { strategy: params.strategy } : {}),
  });

// --- GTT (Good Till Triggered) ---
//
// route them through the current gated forever-order client so every trigger
// still passes SafetySystem/BrokerRouter and native broker targeting.

export interface PlaceGttParams extends BrokerTarget {
  /** Trigger type — SINGLE for one-leg, OCO for stoploss + target. */
  trigger_type: "SINGLE" | "OCO";
  /** Broker-specific entry condition for Upstox GTT rules. */
  entry_trigger_type?: "ABOVE" | "BELOW" | "IMMEDIATE";
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  /** GTT product is restricted to CNC or NRML — MIS is rejected by upstream. */
  product: "CNC" | "NRML";
  quantity: number;
  pricetype?: "LIMIT" | "MARKET";
  price: number;
  /** Stoploss-leg trigger price (SINGLE-SL or OCO). */
  triggerprice_sl?: number;
  /** Target-leg trigger price (SINGLE-TG or OCO). */
  triggerprice_tg?: number;
  /** Stoploss limit price — OCO only. */
  stoploss?: number;
  /** Target limit price — OCO only. */
  target?: number;
  /** Optional ISO timestamp at which the trigger auto-expires. */
  expires_at?: string;
  strategy?: string;
}

export interface ModifyGttParams extends PlaceGttParams {
  trigger_id: string;
}

export interface CancelGttParams extends BrokerTarget {
  trigger_id: string;
  strategy?: string;
}

export interface GttTrigger {
  trigger_id: string;
  status: string;
  trigger_type: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: string;
  product: string;
  price: string;
  triggerprice_sl: string;
  triggerprice_tg: string;
  stoploss: string;
  target: string;
  created_at: string;
  expires_at: string;
}

function legacyGttTarget(params: BrokerTarget = {}): BrokerTarget {
  if (params.broker || params.account_id) {
    return { broker: params.broker, account_id: params.account_id };
  }
  return (
    pickNativeBrokerOrderTarget(
      useModeStore.getState().mode,
      useConnectionStore.getState().apiKey,
    ) ?? {}
  );
}

function firstFiniteNumber(...values: Array<number | undefined>): number | undefined {
  return values.find((value): value is number => typeof value === "number" && Number.isFinite(value));
}

function legacyGttResponse(response: unknown): { orderId: string; trigger_id?: string } {
  if (response !== null && typeof response === "object" && !Array.isArray(response)) {
    const record = response as Record<string, unknown>;
    const rawId =
      record.orderId ?? record.order_id ?? record.orderid ?? record.trigger_id ?? record.data ?? "";
    return { ...record, orderId: String(rawId) } as { orderId: string; trigger_id?: string };
  }
  return { orderId: String(response ?? "") };
}

function legacyGttPlaceParams(params: PlaceGttParams): ForeverOrderPlaceParams {
  const triggerPrice = firstFiniteNumber(params.triggerprice_sl, params.triggerprice_tg);
  if (triggerPrice === undefined) {
    throw new Error("GTT order requires triggerprice_sl or triggerprice_tg.");
  }
  const limitPrice = firstFiniteNumber(params.stoploss, params.target, params.price) ?? 0;
  const payload: ForeverOrderPlaceParams = {
    ...legacyGttTarget(params),
    variety: "gtt",
    symbol: params.symbol,
    exchange: params.exchange,
    action: params.action,
    quantity: params.quantity,
    product: params.product,
    pricetype: params.pricetype ?? "LIMIT",
    price: limitPrice,
    trigger_price: triggerPrice,
    validity: "DAY",
  };
  if (params.entry_trigger_type !== undefined) {
    payload.entry_trigger_type = params.entry_trigger_type;
  }

  if (
    params.triggerprice_sl !== undefined &&
    params.triggerprice_tg !== undefined &&
    params.target !== undefined
  ) {
    payload.trigger_price1 = params.triggerprice_tg;
    payload.price1 = params.target;
    payload.quantity1 = params.quantity;
  }

  return payload;
}

function legacyGttChanges(params: ModifyGttParams): OrderChanges {
  const changes: OrderChanges = {
    quantity: params.quantity,
    pricetype: params.pricetype ?? "LIMIT",
    validity: "DAY",
  };
  const triggerPrice = firstFiniteNumber(params.triggerprice_sl, params.triggerprice_tg);
  const limitPrice = firstFiniteNumber(params.stoploss, params.target, params.price);
  if (triggerPrice !== undefined) changes.trigger_price = triggerPrice;
  if (limitPrice !== undefined) changes.price = limitPrice;
  if (params.entry_trigger_type !== undefined) changes.entry_trigger_type = params.entry_trigger_type;
  return changes;
}

export const placeGtt = async (params: PlaceGttParams) =>
  legacyGttResponse(await placeForeverOrder(legacyGttPlaceParams(params)));

export const modifyGtt = async (params: ModifyGttParams) =>
  legacyGttResponse(
    await modifyForeverOrder({
      ...legacyGttTarget(params),
      order_id: params.trigger_id,
      changes: legacyGttChanges(params),
    }),
  );

export const cancelGtt = async (params: CancelGttParams) =>
  legacyGttResponse(
    await cancelForeverOrder({
      ...legacyGttTarget(params),
      order_id: params.trigger_id,
    }),
  );

export const getGttOrderbook = async (target: BrokerTarget = {}): Promise<GttTrigger[]> =>
  (await listForeverOrders(legacyGttTarget(target))) as unknown as GttTrigger[];

// --- Data ---


export interface MultiQuoteResult {
  symbol: string;
  exchange: string;
  data: Quote;
}

export const getQuotes = (
  symbol: string,
  exchange = "NSE",
  signal?: AbortSignal,
  expectedDataScope?: string,
) => post<Quote>("quotes", { symbol, exchange }, signal, expectedDataScope);

/**
 * Canonical row shape the core reads facade guarantees for ltp/quote_details —
 * every broker's payload is normalised server-side (one-core rule: broker
 * differences are absorbed in the core facade, never in the terminal), so
 * these clients are thin envelope readers with NO per-broker logic.
 */
export interface CanonicalLtpRow {
  symbol: string;
  exchange: string;
  ltp: number;
  [key: string]: unknown;
}

export const getQuoteDetails = (
  symbol: string,
  exchange = "NSE",
  quoteType = "all",
) =>
  // The core facade serves quote_details uniformly for every broker (adapters
  // without the verb fall back to their ltp read server-side).
  readRequiredPrimaryNative<CanonicalLtpRow[]>("quote_details", {
    symbol,
    exchange,
    quote_type: quoteType,
  });

export const getBrokerLimits = (
  segment = "ALL",
  exchange = "ALL",
  product = "ALL",
) => readRequiredPrimaryNative<Record<string, unknown>>("limits", { segment, exchange, product });

export const getScripMaster = (exchange?: string) =>
  readRequiredPrimaryNative<Record<string, unknown>>("scrip_master", exchange ? { exchange } : {});

export interface NativeScripSearchOptions {
  exchange?: string;
  expiry?: string;
  option_type?: string;
  strike_price?: string;
  ignore_50multiple?: boolean;
}

export const searchScrip = (
  symbol: string,
  options: NativeScripSearchOptions = {},
) => readRequiredPrimaryNative<Array<Record<string, unknown>>>("search_scrip", { symbol, ...options });


export const getMultiQuotes = (
  symbols: Array<{ symbol: string; exchange: string }>,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => post<{ results: MultiQuoteResult[] } | MultiQuoteResult[]>("multiquotes", { symbols }, signal, expectedDataScope);


export function normaliseMultiQuotes(
  raw: { results: MultiQuoteResult[] } | MultiQuoteResult[],
): Quote[] {
  const items: MultiQuoteResult[] = Array.isArray(raw) ? raw : raw.results ?? [];
  return items.map((item) => {
    // Standard shape: item.data is the Quote payload
    if (item.data && typeof item.data === "object") {
      return { ...item.data, symbol: item.symbol, exchange: item.exchange };
    }
    // Flat shape: the item itself is the Quote (broker adapter omits the `data` wrapper)
    return item as unknown as Quote;
  });
}
export const getDepth = (symbol: string, exchange = "NSE", signal?: AbortSignal, expectedDataScope?: string) =>
  post<MarketDepth>("depth", { symbol, exchange }, signal, expectedDataScope);
export const getHistory = (
  symbol: string,
  exchange: string,
  interval: string,
  start_date: string,
  end_date: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => post<OHLCVBar[]>(
  "history",
  { symbol, exchange, interval, start_date, end_date },
  signal,
  expectedDataScope,
);
export const getOptionChain = (
  symbol: string,
  exchange = "NFO",
  expiry?: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => {
  const expiryDate = String(expiry ?? "").trim();
  return post<OptionChainData>("optionchain", {
    underlying: symbol,
    exchange,
    ...(expiryDate ? { expiry_date: expiryDate } : {}),
  }, signal, expectedDataScope);
};
export async function getExpiry(
  symbol: string,
  exchange = "NFO",
  instrumenttype: "options" | "futures" = "options",
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<{ expiry: string[] }> {
  return normaliseNativeExpiry(
    await post<unknown>(
      "expiry",
      { symbol, exchange, instrumenttype },
      signal,
      expectedDataScope,
    ),
  );
}
export function searchSymbol(
  query: string,
  exchange?: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
): Promise<Array<{ symbol: string; exchange: string }>> {
  // Sanitize: strip characters that are not word chars, spaces, hyphens, or dots
  const sanitized = query.replace(/[^\w\s\-.]/g, "").slice(0, 50).trim();
  if (!sanitized) {
    throw new Error("Search query is empty after sanitization");
  }
  const body: Record<string, string> = { query: sanitized };
  if (exchange) body.exchange = exchange;
  return post<Array<{ symbol: string; exchange: string }>>(
    "search",
    body,
    signal,
    expectedDataScope,
  );
}
export const getIntervals = async (signal?: AbortSignal, expectedDataScope?: string) => {
  const scope = captureMarketDataScope(expectedDataScope);
  return (await getNativeIntervals(signal, scope))
    ?? (isExploreMode() ? getExploreGetFallback<string[]>("intervals") ?? [] : []);
};
export async function getMultiOptionGreeks(
  symbols: Array<{ symbol: string; exchange: string }>,
): Promise<Greeks[]> {
  const value = await post<unknown>("multioptiongreeks", { symbols });
  if (!Array.isArray(value) || value.length !== symbols.length) {
    throw new Error("Option-Greeks response does not match the requested contracts");
  }
  const requestedKeys = symbols.map(({ symbol, exchange }) => (
    `${exchange.trim().toUpperCase()}:${symbol.trim().toUpperCase()}`
  ));
  if (new Set(requestedKeys).size !== requestedKeys.length) {
    throw new Error("Option-Greeks request repeats a contract identity");
  }
  const requested = new Set(requestedKeys);
  const byContract = new Map<string, Greeks>();
  value.forEach((candidate) => {
    if (!isRecord(candidate)) throw new Error("Invalid option-Greeks row");
    const symbol = stringParam(candidate.symbol ?? candidate.trading_symbol ?? candidate.tradingsymbol).trim();
    const exchange = stringParam(candidate.exchange).trim().toUpperCase();
    if (!symbol || !exchange) throw new Error("Option-Greeks row lacks contract identity");
    const key = `${exchange}:${symbol.toUpperCase()}`;
    if (!requested.has(key) || byContract.has(key)) {
      throw new Error("Option-Greeks response does not match the requested contracts");
    }
    const instrumentId = stringParam(candidate.instrument_id ?? candidate.instrument_token).trim();
    byContract.set(key, {
      symbol,
      exchange,
      ...(instrumentId ? { instrument_id: instrumentId } : {}),
      delta: greekNumber(candidate, "delta", "Delta"),
      gamma: greekNumber(candidate, "gamma", "Gamma"),
      theta: greekNumber(candidate, "theta", "Theta"),
      vega: greekNumber(candidate, "vega", "Vega"),
      iv: greekNumber(candidate, "iv", "implied_volatility", "IV", "vix"),
    });
  });
  if (byContract.size !== requestedKeys.length) {
    throw new Error("Option-Greeks response does not match the requested contracts");
  }
  return requestedKeys.map((key) => byContract.get(key)!);
}
export const getOptionSymbol = (
  underlying: string,
  exchange: string,
  expiry_date: string,
  option_type: string,
  offset: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => {
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  return Promise.resolve(compactOptionSymbolResult(underlying, exchange, expiry_date, option_type, offset));
};
export const getSymbol = (
  symbol: string,
  exchange: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) =>
  post<{ symbol: string; name: string; exchange: string; instrumenttype: string; lotsize: number; tick_size: number }>(
    "symbol",
    { symbol, exchange },
    signal,
    expectedDataScope,
  );
export const getSyntheticFuture = async (
  symbol: string,
  exchange: string,
  expiry_date?: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => {
  expectedDataScope = captureMarketDataScope(expectedDataScope);
  const native = await getNativeSyntheticFuture(symbol, exchange, expiry_date, signal, expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (native !== undefined) return native;
  const expiry = String(expiry_date ?? "").trim();
  return post<SyntheticFutureData>(
    "syntheticfuture",
    { underlying: symbol, exchange, ...(expiry ? { expiry_date: expiry } : {}) },
    signal,
    expectedDataScope,
  );
};
export const getTicker = (symbol: string, exchange: string) =>
  getQuotes(symbol, exchange);
/** Native instrument metadata from the configured broker. */
export const getInstruments = async (
  signal?: AbortSignal,
  expectedDataScope?: string,
  exchange?: string,
): Promise<InstrumentRow[]> => {
  if (isExploreMode()) return [];
  const rows = await readPrimaryNative<unknown>("scrip_master", exchange ? { exchange } : {}, signal, expectedDataScope);
  if (rows === undefined) throw new Error("A connected native broker account is required for instruments.");
  return normaliseInstrumentList(rows as InstrumentRow[] | { data?: InstrumentRow[]; instruments?: InstrumentRow[] });
};
function readDerivedMarket<T>(endpoint: string, body: object, signal?: AbortSignal): Promise<T> {
  const scope = captureMarketDataScope();
  return awaitMarketDataAuthority(() => postFtApi<T>(endpoint, body, signal), signal, scope);
}
export const getGex = (symbol: string, exchange: string, expiry_date?: string, signal?: AbortSignal) =>
  readDerivedMarket<BackendGexData | Array<BackendGexEntry | GexEntry>>("gex", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) }, signal)
    .then(normaliseGexEntries);
export const getIVSmile = (symbol: string, exchange: string, expiry_date?: string, signal?: AbortSignal) =>
  readDerivedMarket<BackendIVSmileData | IVSmileEntry[]>("ivsmile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) }, signal)
    .then(normaliseIVSmileEntries);
export const getMaxPain = async (
  symbol: string,
  exchange: string,
  expiry_date?: string,
  signal?: AbortSignal,
  expectedDataScope?: string,
) => {
  expectedDataScope = captureMarketDataScope(expectedDataScope);
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  if (isExploreMode()) throw new Error("Max Pain is not available in this session.");
  const value = await awaitMarketDataAuthority(
    () => postFtApi<BackendMaxPainData>(
      "maxpain",
      { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) },
      signal,
    ),
    signal,
    expectedDataScope,
  );
  signal?.throwIfAborted();
  requireCurrentMarketDataScope(expectedDataScope);
  return normaliseMaxPainData(value);
};
export const getOIProfile = (symbol: string, exchange: string, expiry_date?: string, signal?: AbortSignal) =>
  readDerivedMarket<BackendOIProfileData | OIProfileEntry[]>("oiprofile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) }, signal)
    .then(normaliseOIProfileEntries);

// --- Account ---
export const getFunds = async (context: AccountReadContext, signal?: AbortSignal) => normaliseFundsShape(
  await readAccountSnapshot<unknown>("funds", {}, context, signal),
);
export const getMargin = (
  context: AccountReadContext,
  symbol: string,
  exchange: string,
  qty: number,
  product: string,
  action: string,
  signal?: AbortSignal,
) => readAccountSnapshot<MarginData>(
  "margin",
  { symbol, exchange, qty, product, action },
  context,
  signal,
);
export const getOrderHistory = (orderId: string) =>
  readRequiredPrimaryNative<Array<Record<string, unknown>>>("orderhistory", { order_id: orderId });
export const getOrderTrades = (orderId: string) =>
  readRequiredPrimaryNative<Array<Record<string, unknown>>>("ordertrades", { order_id: orderId });

// post() unwraps json.data, so we receive { orders: [...], statistics: {...} }.
// We extract the nested array and fall back to the raw value for brokers that
// return a plain array (future-proofing / broker inconsistency).
export const getOrderbook = async (
  context: AccountReadContext,
  signal?: AbortSignal,
): Promise<Order[]> => {
  const raw = await readAccountSnapshot<Order[] | { orders?: Order[] }>("orderbook", {}, context, signal);
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.orders) ? raw.orders : [];
};

export const getTradebook = async (
  context: AccountReadContext,
  signal?: AbortSignal,
): Promise<Trade[]> => {
  const raw = await readAccountSnapshot<Trade[] | { trades?: Trade[] }>(
    "tradebook",
    {},
    context,
    signal,
  );
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.trades) ? raw.trades : [];
};

export const getPositionbook = async (
  context: AccountReadContext,
  signal?: AbortSignal,
): Promise<Position[]> => {
  const raw = await readAccountSnapshot<Position[] | { positions?: Position[] }>(
    "positionbook",
    {},
    context,
    signal,
  );
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.positions) ? raw.positions : [];
};

export const getHoldings = async (
  context: AccountReadContext,
  signal?: AbortSignal,
): Promise<Holding[]> => {
  const raw = await readAccountSnapshot<Holding[] | { holdings?: Holding[] }>(
    "holdings",
    {},
    context,
    signal,
  );
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.holdings) ? raw.holdings : [];
};

// --- Utility ---
export async function getHolidays(year?: number | string): Promise<Holiday[]> {
  if (year !== undefined && year !== "") {
    return post<Holiday[]>("market/holidays", { year: holidayYear(year) });
  }
  const years = holidayYearsForLookahead();
  const calendars = await Promise.all(
    years.map((calendarYear) => post<Holiday[]>("market/holidays", { year: calendarYear })),
  );
  return mergeHolidayCalendars(calendars);
}
export function getTimings(date?: string): Promise<MarketTiming[]> {
  const timingDate = String(date ?? todayIstIsoDate()).trim();
  if (!timingDate) throw new Error("date is required");
  return post<MarketTiming[]>("market/timings", { date: timingDate });
}
export interface TelegramSendOptions {
  botToken?: string;
  chatId?: string;
}

export const sendTelegram = (message: string, options: TelegramSendOptions = {}) => {
  const body: Record<string, string> = { message };
  const botToken = options.botToken?.trim();
  const chatId = options.chatId?.trim();
  if (botToken) body.bot_token = botToken;
  if (chatId) body.chat_id = chatId;
  return postFtApi<{ message: string }>("telegram", body);
};

// --- Broker Management ---
// workspaces use FlintTrade's own unified capability registry, normalised back
// into the compact terminal contract consumed by Order Pad and Settings.
export const getBrokerCapabilities = async (
  signal?: AbortSignal,
  expectedCapabilityScope?: string,
) => {
  expectedCapabilityScope ??= resolveBrokerCapabilityScope(captureMarketDataScope());
  try {
  signal?.throwIfAborted();
  requireCurrentBrokerCapabilityScope(expectedCapabilityScope);
  if (isExploreMode()) {
    // Explore capabilities are local demo metadata. Never let a stale bridge
    // key or native-account snapshot turn this read into a protected request.
    return getExploreBrokerCapabilities();
  }
  const broker = await nativeCapabilityBroker(signal);
  signal?.throwIfAborted();
  requireCurrentBrokerCapabilityScope(expectedCapabilityScope);
  // The authority can retire while native account discovery is in flight.
  // Never issue the follow-up protected capability request after Explore wins.
  if (isExploreMode()) return getExploreBrokerCapabilities();
  const endpoint = broker
    ? `broker/capabilities?broker=${encodeURIComponent(broker)}`
    : "broker/capabilities";
  const value = await getFtApi<BackendBrokerCapabilitiesData>(endpoint, signal);
  signal?.throwIfAborted();
  requireCurrentBrokerCapabilityScope(expectedCapabilityScope);
  return normaliseBrokerCapabilities(value);
  } catch (error) {
    signal?.throwIfAborted();
    requireCurrentBrokerCapabilityScope(expectedCapabilityScope);
    throw error;
  }
};
export const getLeverageSettings = async (): Promise<LeverageSettings> => {
  const { status: _status, ...settings } = await getFtApi<LeverageSettings & { status?: string }>("leverage/margin/current");
  return settings;
};

// --- Chart Preferences ---
export const getChartPreferences = () => getFtApi<object>("chart");
export const updateChartPreferences = (prefs: object) => postFtApi<object>("chart", prefs);

// --- Analytics ---
export const getOptionGreeks = (params: OptionGreeksParams) => post<Greeks>("optiongreeks", params);
