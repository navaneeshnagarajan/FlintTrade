/**
 * OpenAlgo REST API client (TypeScript).
 * Host & API key sourced from connectionStore (Zustand).
 * All responses are unwrapped: { data: X, status: "success" } → X
 */

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
  OpenPositionParams,
  BasketOrderParams,
  SplitOrderParams,
  OptionsOrderParams,
  OptionsMultiOrderParams,
  OptionGreeksParams,
  Greeks,
  GexEntry,
  IVSmileEntry,
  MaxPainData,
  OIProfileEntry,
  SyntheticFutureData,
  MarginData,
  Holiday,
  MarketTiming,
  BrokerCapabilities,
  LeverageSettings,
} from "@/types/api";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import { findBrokerAccountMatch, useBrokerStore } from "@/stores/brokerStore";
import { buildCompactOptionSymbol } from "@/lib/optionSymbols";
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
import { get as getFtApi, post as postFtApi } from "./ftApi.helpers";

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
  timings: "timings",
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

// Account-scoped native reads expose the REAL broker account (balances,
// positions, order/trade book, margin). They must only surface in LIVE mode —
// in Practice/Explore orders execute in the SandboxEngine, so showing the live
// account here would falsely present real money as sandbox state. Market-data
// kinds (quotes/history/depth/optionchain/greeks/expiry/search/timings/holidays)
// are broker-agnostic reference data and stay available in every mode.
const NATIVE_ACCOUNT_SCOPED_KINDS = new Set<NativeReadKind>([
  "funds", "limits", "positions", "holdings", "orders", "orderstatus", "orderhistory", "ordertrades", "trades", "margin",
]);

function getBase(): string {
  // In dev mode, Vite proxy handles routing to OpenAlgo — use relative paths
  // In production, use the full host from connectionStore
  if (import.meta.env.DEV) return "";
  return useConnectionStore.getState().host;
}

/** Base URL for the FlintTrade Python backend.
 *  In dev mode the Vite proxy maps /ft-api → localhost:5100.
 *  In production the backend shares the same origin. */
function getFtBase(): string {
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

function getApiKey(): string {
  return useConnectionStore.getState().apiKey;
}

function isExploreModeWithoutKey(): boolean {
  return useModeStore.getState().mode === "explore" && getApiKey().trim().length === 0;
}

type NativeReadAccountCandidate = Awaited<ReturnType<typeof listLiveNativeReadAccounts>>[number];

function pickNativeReadAccount(accounts: Awaited<ReturnType<typeof listLiveNativeReadAccounts>>) {
  const { accounts: brokerAccounts, activeAccountId } = useBrokerStore.getState();
  return selectNativeReadAccount(accounts, brokerAccounts, activeAccountId);
}

async function primaryNativeReadAccountFor(kind: NativeReadKind): Promise<NativeReadAccountCandidate | undefined> {
  if (getApiKey().trim().length > 0 || isExploreModeWithoutKey()) return undefined;
  // Account-scoped reads expose the REAL broker account and must be Live-only.
  // Market-data kinds stay readable in every mode.
  if (NATIVE_ACCOUNT_SCOPED_KINDS.has(kind) && useModeStore.getState().mode !== "live") {
    return undefined;
  }
  return pickNativeReadAccount(await listLiveNativeReadAccounts());
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

  return normalised;
}

function toNumber(value: unknown): number {
  const n = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

function normaliseFundsShape(value: unknown): Funds {
  const row = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    availableCash: toNumber(row.availableCash ?? row.available_balance ?? row.available ?? row.cash),
    usedMargin: toNumber(row.usedMargin ?? row.used_margin ?? row.utilized_margin ?? row.utilised_margin),
    totalBalance: toNumber(row.totalBalance ?? row.total_balance ?? row.total ?? row.net),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stringParam(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
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
  return {
    ...(raw as Partial<Quote>),
    symbol: String(raw.symbol ?? ""),
    exchange: String(raw.exchange ?? ""),
    ltp: toNumber(raw.ltp ?? raw.last_price ?? raw.lastPrice),
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
  date: isoCalendarDateSchema.optional(),
  _date: isoCalendarDateSchema.optional(),
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

function nativeGreeksRow(value: unknown): Greeks {
  const row = isRecord(value) ? value : {};
  return {
    delta: toNumber(row.delta ?? row.Delta),
    gamma: toNumber(row.gamma ?? row.Gamma),
    theta: toNumber(row.theta ?? row.Theta),
    vega: toNumber(row.vega ?? row.Vega),
    iv: toNumber(row.iv ?? row.implied_volatility ?? row.IV ?? row.vix),
  };
}

function normaliseNativeGreeks(value: unknown): Greeks[] {
  const rows = Array.isArray(value) ? value : [];
  return rows.map(nativeGreeksRow);
}

function normaliseNativeExpiry(value: unknown): { expiry: string[] } {
  const rows = Array.isArray(value)
    ? value
    : (isRecord(value) && Array.isArray(value.expiry) ? value.expiry : []);
  return { expiry: rows.map((item) => String(item)).filter(Boolean) };
}

function nativeOptionLeg(row: Record<string, unknown>, prefix: "ce" | "pe"): Record<string, number> {
  const field = (name: string) => row[`${prefix}_${name}`];
  return {
    ltp: toNumber(field("ltp")),
    last_price: toNumber(field("ltp")),
    oi: toNumber(field("oi")),
    open_interest: toNumber(field("oi")),
    volume: toNumber(field("volume")),
    iv: toNumber(field("iv")),
    implied_volatility: toNumber(field("iv")),
    delta: toNumber(field("delta")),
    gamma: toNumber(field("gamma")),
    theta: toNumber(field("theta")),
    vega: toNumber(field("vega")),
    bid: toNumber(field("bid")),
    ask: toNumber(field("ask")),
  };
}

function normaliseNativeOptionChain(value: unknown): unknown {
  if (isRecord(value) && Array.isArray(value.chain)) return value;
  const row = isRecord(value) ? value : {};
  const rawStrikes = isRecord(value) && Array.isArray(value.strikes) ? value.strikes : [];
  const chain = rawStrikes.filter(isRecord).map((row) => {
    const strike = toNumber(row.strike_price ?? row.strike);
    return {
      strike,
      ce: nativeOptionLeg(row, "ce"),
      pe: nativeOptionLeg(row, "pe"),
    };
  }).filter((entry) => entry.strike > 0).sort((a, b) => a.strike - b.strike);
  const totalCallOi = chain.reduce((acc, row) => acc + toNumber(row.ce.oi), 0);
  const totalPutOi = chain.reduce((acc, row) => acc + toNumber(row.pe.oi), 0);
  return {
    chain,
    atm_strike: chain[Math.floor(chain.length / 2)]?.strike ?? null,
    underlying_ltp: toNumber(row.underlying_ltp ?? row.spotPrice ?? row.spot),
    expiry: String(row.expiry ?? row.expiry_date ?? ""),
    pcr: totalCallOi > 0 ? totalPutOi / totalCallOi : null,
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
  max_pain_strike?: number | string;
  total_loss_at_max_pain?: number | string;
  strike_losses?: Array<{
    strike?: number | string;
    strike_price?: number | string;
    total_loss?: number | string;
    total_pain?: number | string;
  }>;
  strikes?: MaxPainData["strikes"];
}

interface BackendGexData {
  strikes?: Array<{
    strike?: number | string;
    call_gamma?: number | string;
    put_gamma?: number | string;
    net_gamma?: number | string;
    call_gex?: number | string;
    put_gex?: number | string;
    net_gex?: number | string;
    call_oi?: number | string;
    put_oi?: number | string;
  }>;
}

interface BackendIVSmileData {
  curves?: Array<{
    points?: IVSmileEntry[];
  }>;
  points?: IVSmileEntry[];
}

interface BackendOIProfileData {
  strikes?: Array<{
    strike?: number | string;
    ce_oi?: number | string;
    pe_oi?: number | string;
    ce_oi_change?: number | string;
    pe_oi_change?: number | string;
    ce_ltp?: number | string;
    pe_ltp?: number | string;
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

function normaliseGexEntries(value: BackendGexData | GexEntry[]): GexEntry[] {
  if (Array.isArray(value)) return value;
  return (value.strikes ?? []).map((row) => ({
    strike: toNumber(row.strike),
    call_gamma: toNumber(row.call_gamma ?? row.call_gex),
    put_gamma: toNumber(row.put_gamma ?? row.put_gex),
    net_gamma: toNumber(row.net_gamma ?? row.net_gex),
    call_oi: toNumber(row.call_oi),
    put_oi: toNumber(row.put_oi),
  })).filter((row) => row.strike > 0);
}

function normaliseIVSmileEntries(value: BackendIVSmileData | IVSmileEntry[]): IVSmileEntry[] {
  if (Array.isArray(value)) return value;
  const curve = value.curves?.[0];
  return (value.points ?? curve?.points ?? []).map((row) => ({
    strike: toNumber(row.strike),
    call_iv: toNumber(row.call_iv),
    put_iv: toNumber(row.put_iv),
    moneyness: toNumber(row.moneyness),
  })).filter((row) => row.strike > 0);
}

function normaliseOIProfileEntries(value: BackendOIProfileData | OIProfileEntry[]): OIProfileEntry[] {
  if (Array.isArray(value)) return value;
  return (value.strikes ?? []).flatMap((row) => {
    const strike = toNumber(row.strike);
    if (strike <= 0) return [];
    return [
      {
        strike,
        type: "CE" as const,
        oi: toNumber(row.ce_oi),
        oi_delta_d: toNumber(row.ce_oi_change),
        ltp: toNumber(row.ce_ltp),
      },
      {
        strike,
        type: "PE" as const,
        oi: toNumber(row.pe_oi),
        oi_delta_d: toNumber(row.pe_oi_change),
        ltp: toNumber(row.pe_ltp),
      },
    ];
  });
}

function normaliseMaxPainData(value: BackendMaxPainData): MaxPainData {
  const strikeLosses = (value.strike_losses ?? []).map((row) => ({
    strike: toNumber(row.strike ?? row.strike_price),
    total_loss: toNumber(row.total_loss ?? row.total_pain),
  })).filter((row) => row.strike > 0);

  const strikes = value.strikes ?? strikeLosses.map((row) => ({
    strike: row.strike,
    call_oi: 0,
    put_oi: 0,
    call_pain: 0,
    put_pain: 0,
    total_pain: row.total_loss,
  }));

  return {
    ...value,
    max_pain_strike: toNumber(value.max_pain_strike),
    total_loss_at_max_pain: toNumber(value.total_loss_at_max_pain),
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
    underlying_ltp: toNumber(source.underlying_ltp ?? source.spotPrice ?? source.spot ?? syntheticPrice),
    expiry: String(expiry ?? source.expiry ?? ""),
    atm_strike: row.strike,
    synthetic_future_price: syntheticPrice,
  };
}

async function getNativeSyntheticFuture(
  symbol: string,
  exchange: string,
  expiry_date?: string,
): Promise<SyntheticFutureData | undefined> {
  if (getApiKey().trim().length > 0 || isExploreModeWithoutKey()) return undefined;
  const chain = await getOptionChain(symbol, exchange, expiry_date);
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
  const active = findBrokerAccountMatch(accounts, activeAccountId);
  const selected = active ?? accounts.find((account) => account.is_primary) ?? accounts[0];
  return selected?.source === "native" ? selected.broker : undefined;
}

async function nativeCapabilityBroker(): Promise<string | undefined> {
  const broker = nativeCapabilityBrokerFromStore();
  if (broker) return broker;
  const account = pickNativeReadAccount(await listLiveNativeReadAccounts());
  return account?.adapter_id;
}

async function getNativeIntervals(): Promise<string[] | undefined> {
  if (getApiKey().trim().length > 0 || isExploreModeWithoutKey()) return undefined;
  const broker = await nativeCapabilityBroker();
  if (!broker) return undefined;
  const endpoint = `broker/capabilities?broker=${encodeURIComponent(broker)}`;
  const intervals = intervalsFromCapability(await getFtApi<BackendBrokerCapabilitiesData>(endpoint));
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
  if (endpoint === "holidays") return normaliseNativeHolidays(value);
  if (endpoint === "timings") return normaliseNativeTimings(value);
  if (endpoint === "multioptiongreeks") return normaliseNativeGreeks(value);
  if (endpoint === "optiongreeks") return normaliseNativeGreeks(value)[0] ?? nativeGreeksRow({});
  if (endpoint === "expiry") return normaliseNativeExpiry(value);
  if (endpoint === "optionchain") return normaliseNativeOptionChain(value);
  if (endpoint === "search") return normaliseNativeSearch(value);
  if (endpoint === "symbol") return normaliseNativeSymbol(value);
  return value;
}

async function readPrimaryNative<T>(endpoint: string, extra: object = {}): Promise<T | undefined> {
  const kind = NATIVE_READ_ENDPOINTS[endpoint];
  if (!kind) return undefined;
  const account = await primaryNativeReadAccountFor(kind);
  if (!account) return undefined;
  const value = await readNativeAccount<unknown>(
    account.adapter_id,
    account.account_id,
    kind,
    buildNativeReadParams(endpoint, extra),
  );
  return normaliseNativeRead(endpoint, value) as T;
}

async function readRequiredPrimaryNative<T>(endpoint: string, extra: object = {}): Promise<T> {
  const value = await readPrimaryNative<T>(endpoint, extra);
  if (value !== undefined) return value;
  throw new Error(`A live native broker account is required for ${endpoint}.`);
}

function requireApiKey(endpoint: string): void {
  if (getApiKey().trim().length > 0) return;
  throw new Error(`OpenAlgo API key is not configured for ${endpoint}. Check Settings -> Connection.`);
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

function makeMockHistory(symbol?: string, exchange?: string): OHLCVBar[] {
  const quote = findMockQuote(symbol, exchange);
  const now = Math.floor(Date.now() / 1000);
  return Array.from({ length: 96 }, (_, index) => {
    const drift = Math.sin(index / 6) * quote.ltp * 0.002;
    const open = quote.ltp + drift;
    const close = open + Math.cos(index / 5) * quote.ltp * 0.0015;
    return {
      timestamp: now - (95 - index) * 300,
      open,
      high: Math.max(open, close) + quote.ltp * 0.001,
      low: Math.min(open, close) - quote.ltp * 0.001,
      close,
      volume: Math.max(1, Math.round(quote.volume / 100 + index * 37)),
    };
  });
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
    strategy: "Explore",
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

function getExplorePostFallback<T>(endpoint: string, extra: object): T | undefined {
  const params = extra as Record<string, unknown>;
  const symbol = typeof params.symbol === "string" ? params.symbol : undefined;
  const exchange = typeof params.exchange === "string" ? params.exchange : undefined;

  switch (endpoint) {
    case "ping":
      return { status: "explore" } as T;
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
    case "history":
      return makeMockHistory(symbol, exchange) as T;
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
    case "positionbook":
      return { positions: mockPositions() } as T;
    case "holdings":
      return { holdings: mockHoldings() } as T;
    case "holidays":
      return [] as T;
    case "timings":
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
      return {
        broker_name: "Explore",
        broker_type: "multi",
        supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
        features: {
          market_protection: false,
          leverage: false,
          bracket_orders: false,
          cover_orders: false,
        },
      } as T;
    default:
      return undefined;
  }
}

/** POST an order through the FlintTrade safety proxy.
 *
 *  The backend at order_routes.py:
 *    - Validates `X-API-Key` against FLINTTRADE_API_KEY, with
 *      OPENALGO_API_KEY retained only as a compatibility fallback.
 *    - Reads `X-FlintTrade-Mode` to enforce explore / practice / live gates.
 *    - For live-mode orders, additionally requires
 *      `Authorization: Bearer <jwt>` with the `live_mode_unlocked` claim.
 *
 *  Headers we attach:
 *    - `Content-Type: application/json`
 *    - `X-FlintTrade-Mode: <explore|practice|live>`
 *    - `X-API-Key: <connectionStore.apiKey>`  (gates the auth middleware when
 *      a backend key is configured)
 *    - `Authorization: Bearer <authStore.token>` when a session token is
 *      available; the backend ignores it in explore/practice mode and
 *      checks the `live_mode_unlocked` claim before letting a real order
 *      reach OpenAlgo.
 *
 *  Pre-2026-05-19 this function only sent `Content-Type` and
 *  `X-FlintTrade-Mode`. Codex stop-gate review (task-mpcpfmws-5rokaa)
 *  flagged that every real terminal order placement would 401 against
 *  the require_auth middleware, even though the backend tests passed
 *  because they fabricated `X-API-Key` and `Authorization` in the test
 *  client.
 */
async function postOrder<T>(ftEndpoint: string, body: object = {}): Promise<T> {
  // Apply the order rate limit (10/s) — identical to OpenAlgo direct calls
  if (!orderLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for ${ftEndpoint} (order: 10/s)`);
  }

  // Read the current operating mode and auth state to assemble headers.
  const mode = useModeStore.getState().mode;
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
  const nativeTarget = pickNativeWriteTarget(mode, apiKey);
  const isNativeRoutedEndpoint = nativeTarget !== undefined && NATIVE_ROUTED_ORDER_ENDPOINTS.has(ftEndpoint);
  const orderPath = isNativeRoutedEndpoint
    ? `${encodeURIComponent(nativeTarget.broker)}/${ftEndpoint}`
    : ftEndpoint;
  const requestBody = nativeTarget !== undefined && (
    isNativeRoutedEndpoint || ftEndpoint === "cancel-all"
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
    const body2 = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body2?.message ?? body2?.error ?? null;
    if (resp.status === 401) {
      throw new Error("API key invalid. Check Settings → Connection.");
    }
    if (resp.status === 400) {
      throw new Error(serverMsg ?? "Invalid order parameters. Check symbol and exchange.");
    }
    if (resp.status === 403) {
      // Backend returns 403 when mode blocks the action (e.g. real order in practice mode)
      throw new Error(serverMsg ?? `Order blocked in ${mode} mode.`);
    }
    if (resp.status === 500) {
      throw new Error(serverMsg ?? "FlintTrade backend error. Try again in a few seconds.");
    }
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }

  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `Order API ${ftEndpoint} error`);
  return (json.data ?? json) as T;
}

async function post<T>(endpoint: string, extra: object = {}): Promise<T> {
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

  const nativeRead = await readPrimaryNative<T>(endpoint, extra);
  if (nativeRead !== undefined) return nativeRead;

  if (isExploreModeWithoutKey()) {
    const fallback = getExplorePostFallback<T>(endpoint, extra);
    if (fallback !== undefined) return fallback;
    requireApiKey(endpoint);
  } else {
    requireApiKey(endpoint);
  }

  let resp: Response;
  try {
    resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apikey: getApiKey(), ...extra }),
    });
  } catch {
    throw new Error("Connection failed. Check OpenAlgo is running.");
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body?.message ?? body?.error ?? null;
    if (resp.status === 401) {
      throw new Error("API key invalid. Check Settings → Connection.");
    }
    if (resp.status === 400) {
      throw new Error(serverMsg ?? "Invalid order parameters. Check symbol and exchange.");
    }
    if (resp.status === 500) {
      throw new Error(serverMsg ?? "OpenAlgo server error. Try again in a few seconds.");
    }
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }

  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

async function get<T>(endpoint: string): Promise<T> {
  if (!generalLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for GET ${endpoint}`);
  }

  if (isExploreModeWithoutKey()) {
    const fallback = getExploreGetFallback<T>(endpoint);
    if (fallback !== undefined) return fallback;
    requireApiKey(endpoint);
  } else {
    requireApiKey(endpoint);
  }

  let resp: Response;
  try {
    resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  } catch {
    throw new Error("Connection failed. Check OpenAlgo is running.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body?.message ?? body?.error ?? null;
    if (resp.status === 401) throw new Error("API key invalid. Check Settings → Connection.");
    if (resp.status === 500) throw new Error(serverMsg ?? "OpenAlgo server error. Try again in a few seconds.");
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

// --- Orders (routed through FlintTrade safety proxy) ---
//
// The leaf names below MUST match the backend route registrations:
//
//   core   orders_bp at /api/v1/orders : place, place-smart, modify, cancel,
//                                        cancel-all, close-position,
//                                        open-position, options, options-multi
//   engine order_bp  at /api/v1/orders : basket, split, options-strategy
//
// Pre-2026-05-19 this file mixed FT-proxy names (place, place-smart,
// cancel-all, close-position) with OpenAlgo-style names (cancelorder,
// openposition, basketorder, splitorder, optionsorder, optionsmultiorder),
// so half the order endpoints 404'd in production. Codex stop-gate review
// caught the mismatch on 2026-05-19 (task-mpcpfmws-5rokaa). A follow-up
// review then flagged that `optionsOrder` / `optionsMultiOrder` had been
// routed through `post()` (OpenAlgo direct) as a stopgap, bypassing the
// FT mode/safety gate. Both endpoints are now backed by /options and
// /options-multi handlers in core orders_bp that delegate to OpenAlgo's
// `optionsorder` and `optionsmultiorder` through `_dispatch_order`, so
// every options trade is mode-gated identically to a regular order.
//
// `orderStatus` is a read-only query. Native-only workspaces route it through
// the live native account; OpenAlgo-key workspaces keep the OpenAlgo direct
// path for bridge parity.
export const placeOrder = (params: PlaceOrderParams) =>
  postOrder<{ orderId: string }>("place", params);
export const placeSmartOrder = (params: PlaceOrderParams & { position_size: number }) =>
  postOrder<{ orderId: string }>("place-smart", params);
export const cancelAllOrders = (strategy = "Flint") =>
  postOrder<void>("cancel-all", { strategy });
export const cancelOrder = (orderId: string, strategy = "Flint") =>
  postOrder<void>("cancel", { orderId, strategy });
export const closePosition = (strategy = "Flint") =>
  postOrder<void>("close-position", { strategy });
export const modifyOrder = (params: ModifyOrderParams) =>
  postOrder<{ orderId: string }>("modify", params);
export const orderStatus = (params: OrderStatusParams) =>
  post<{ status: string }>("orderstatus", params);
export const openPosition = (params: OpenPositionParams) =>
  postOrder<{ orderId: string }>("open-position", params);
export const basketOrder = (params: BasketOrderParams) =>
  postOrder<{ orderId: string }>("basket", params);
export const optionsOrder = (params: OptionsOrderParams) =>
  postOrder<{ orderId: string }>("options", params);
export const optionsMultiOrder = (params: OptionsMultiOrderParams) =>
  postOrder<{ orderId: string }>("options-multi", params);
export const splitOrder = (params: SplitOrderParams) =>
  postOrder<{ orderId: string }>("split", params);

// --- GTT (Good Till Triggered) ---
//
// Legacy OpenAlgo-style GTT surface. Keep these exports for older callers, but
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

/**
 * Shape returned by the OpenAlgo /multiquotes endpoint.
 * Each element is a per-symbol wrapper containing the quote payload under `data`.
 */
export interface MultiQuoteResult {
  symbol: string;
  exchange: string;
  data: Quote;
}

export const getQuotes = (symbol: string, exchange = "NSE") =>
  post<Quote>("quotes", { symbol, exchange });

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

/**
 * Fetch quotes for multiple symbols in one request.
 *
 * OpenAlgo returns `{ results: MultiQuoteResult[], status }` which the `post<T>`
 * helper unwraps to `{ results: MultiQuoteResult[] }`.  Some broker adapters may
 * return a flat `Quote[]` directly — the union type covers both shapes.
 * Callers should check `Array.isArray(result)` vs `"results" in result`,
 * or use `normaliseMultiQuotes()` to get a flat `Quote[]` in one step.
 */
export const getMultiQuotes = (symbols: Array<{ symbol: string; exchange: string }>) =>
  post<{ results: MultiQuoteResult[] } | MultiQuoteResult[]>("multiquotes", { symbols });

/**
 * Normalise the `getMultiQuotes` response into a flat `Quote[]`.
 *
 * Handles both shapes returned by different OpenAlgo broker adapters:
 *  - `{ results: [{ symbol, exchange, data: Quote }, ...] }` — standard v2 shape
 *  - `MultiQuoteResult[]` — flat array of wrapper objects
 *  - `Quote[]` — some adapters return flat quotes directly (no `data` wrapper)
 *
 * The returned quotes always have `symbol` and `exchange` fields set.
 */
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
export const getDepth = (symbol: string, exchange = "NSE") =>
  post<MarketDepth>("depth", { symbol, exchange });
export const getHistory = (
  symbol: string,
  exchange: string,
  interval: string,
  start_date: string,
  end_date: string,
) => post<OHLCVBar[]>("history", { symbol, exchange, interval, start_date, end_date });
export const getOptionChain = (symbol: string, exchange = "NFO", expiry?: string) =>
  post<OptionChainData>("optionchain", {
    underlying: symbol, // OpenAlgo v2 uses 'underlying' not 'symbol'
    exchange,
    ...(expiry ? { expiry } : {}),
    // OpenAlgo expiry format: "24MAR26" (no dashes). Expiry API returns "24-MAR-26".
    ...(expiry ? { expiry_date: expiry.replace(/-/g, "") } : {}),
  });
export const getExpiry = (
  symbol: string,
  exchange = "NFO",
  instrumenttype: "options" | "futures" = "options",
) => post<{ expiry: string[] }>("expiry", { symbol, exchange, instrumenttype });
export function searchSymbol(
  query: string,
  exchange?: string,
): Promise<Array<{ symbol: string; exchange: string }>> {
  // Sanitize: strip characters that are not word chars, spaces, hyphens, or dots
  const sanitized = query.replace(/[^\w\s\-.]/g, "").slice(0, 50).trim();
  if (!sanitized) {
    throw new Error("Search query is empty after sanitization");
  }
  const body: Record<string, string> = { query: sanitized };
  if (exchange) body.exchange = exchange;
  return post<Array<{ symbol: string; exchange: string }>>("search", body);
}
export const getIntervals = async () => (await getNativeIntervals()) ?? get<string[]>("intervals");
export const getMultiOptionGreeks = (symbols: Array<{ symbol: string; exchange: string }>) =>
  post<Greeks[]>("multioptiongreeks", { symbols });
export const getOptionSymbol = (
  underlying: string,
  exchange: string,
  expiry_date: string,
  option_type: string,
  offset: string,
) => {
  if (getApiKey().trim().length === 0) {
    return Promise.resolve(compactOptionSymbolResult(underlying, exchange, expiry_date, option_type, offset));
  }
  return post<{ symbol: string; exchange: string }>("optionsymbol", { underlying, exchange, expiry_date, option_type, offset });
};
export const getSymbol = (symbol: string, exchange: string) =>
  post<{ symbol: string; name: string; exchange: string; instrumenttype: string; lotsize: number; tick_size: number }>("symbol", { symbol, exchange });
export const getSyntheticFuture = async (symbol: string, exchange: string, expiry_date?: string) =>
  (await getNativeSyntheticFuture(symbol, exchange, expiry_date))
    ?? post<SyntheticFutureData>("syntheticfuture", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });
export const getTicker = (symbol: string, exchange: string) =>
  post<Quote>("ticker", { symbol, exchange });
export const getInstruments = async (): Promise<InstrumentRow[]> => {
  if (getApiKey().trim().length === 0) return [];
  return normaliseInstrumentList(await get<InstrumentRow[] | { data?: InstrumentRow[]; instruments?: InstrumentRow[] }>("instruments"));
};
export const getGex = (symbol: string, exchange: string, expiry_date?: string) =>
  postFtApi<BackendGexData | GexEntry[]>("gex", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) })
    .then(normaliseGexEntries);
export const getIVSmile = (symbol: string, exchange: string, expiry_date?: string) =>
  postFtApi<BackendIVSmileData | IVSmileEntry[]>("ivsmile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) })
    .then(normaliseIVSmileEntries);
export const getMaxPain = (symbol: string, exchange: string, expiry_date?: string) =>
  postFtApi<BackendMaxPainData>("maxpain", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) })
    .then(normaliseMaxPainData);
export const getOIProfile = (symbol: string, exchange: string, expiry_date?: string) =>
  postFtApi<BackendOIProfileData | OIProfileEntry[]>("oiprofile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) })
    .then(normaliseOIProfileEntries);

// --- Account ---
export const getFunds = () => post<Funds>("funds");
export const getMargin = (symbol: string, exchange: string, qty: number, product: string, action: string) =>
  post<MarginData>("margin", { symbol, exchange, qty, product, action });
export const getOrderHistory = (orderId: string) =>
  readRequiredPrimaryNative<Array<Record<string, unknown>>>("orderhistory", { order_id: orderId });
export const getOrderTrades = (orderId: string) =>
  readRequiredPrimaryNative<Array<Record<string, unknown>>>("ordertrades", { order_id: orderId });

// OpenAlgo wraps list responses: { data: { orders: [...], statistics: {...} } }
// post() unwraps json.data, so we receive { orders: [...], statistics: {...} }.
// We extract the nested array and fall back to the raw value for brokers that
// return a plain array (future-proofing / broker inconsistency).
export const getOrderbook = async (): Promise<Order[]> => {
  const raw = await post<Order[] | { orders?: Order[] }>("orderbook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.orders) ? raw.orders : [];
};

export const getTradebook = async (): Promise<Trade[]> => {
  const raw = await post<Trade[] | { trades?: Trade[] }>("tradebook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.trades) ? raw.trades : [];
};

export const getPositionbook = async (): Promise<Position[]> => {
  const raw = await post<Position[] | { positions?: Position[] }>("positionbook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.positions) ? raw.positions : [];
};

export const getHoldings = async (): Promise<Holding[]> => {
  const raw = await post<Holding[] | { holdings?: Holding[] }>("holdings");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.holdings) ? raw.holdings : [];
};

// --- Utility ---
export const ping = () => post<{ status: string }>("ping"); // OpenAlgo docs: POST /api/v1/ping
export const getHolidays = () => post<Holiday[]>("holidays"); // POST with apikey, not GET
export const getTimings = () => post<MarketTiming[]>("timings"); // POST with apikey, not GET
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
// OpenAlgo-key workspaces keep using OpenAlgo's broker metadata. Native-only
// workspaces use FlintTrade's own unified capability registry, normalised back
// into the compact terminal contract consumed by Order Pad and Settings.
export const getBrokerCapabilities = async () => {
  if (getApiKey().trim().length > 0) {
    return get<BrokerCapabilities>("../broker/capabilities"); // actual path: /api/broker/capabilities
  }
  const broker = await nativeCapabilityBroker();
  const endpoint = broker
    ? `broker/capabilities?broker=${encodeURIComponent(broker)}`
    : "broker/capabilities";
  return normaliseBrokerCapabilities(await getFtApi<BackendBrokerCapabilitiesData>(endpoint));
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
export const getAnalyzerStatus = () => post<{ enabled: boolean }>("analyzer/status", {});
export const toggleAnalyzer = (enable: boolean) => post<{ enabled: boolean }>("analyzer/toggle", { enable });
