/**
 * Terminal mirror of the shared order rules evaluator.
 *
 * The rows live in ``flinttrade_core/data/order_rules.json``; this file only
 * evaluates them so the ticket can show a refusal or warning before submit.
 * The server evaluates the same rows again on every place and modify, and a
 * shared case file keeps both evaluators returning the same level, source and
 * message for the same order.
 */

import table from "@flinttrade/order-rules";
import { istToday } from "@/lib/ist";

export type RuleLevel = "block" | "warn" | "info";

/** The one result shape every surface shows. */
export interface RuleResult {
  level: RuleLevel;
  source: string;
  rule_id: string;
  message: string;
}

interface RuleScope {
  exchange: string;
  broker: string;
  instrument: string;
  order_types: string[];
  expiry_day?: boolean | null;
  underlying?: string | null;
  product?: string | null;
  unless_broker?: string[] | null;
}

interface RuleRow {
  id: string;
  authority: string;
  level: RuleLevel;
  source: string;
  check: string;
  scope: RuleScope;
  family?: string | null;
  effective_from: string;
  effective_to?: string | null;
  parameters?: Record<string, unknown> | null;
  message: string;
}

/** What the ticket knows about one order. Prices are rupees. */
export interface OrderRuleInput {
  symbol: string;
  exchange: string;
  orderType: string;
  action?: string;
  price?: number | null;
  triggerPrice?: number | null;
  lastPrice?: number | null;
  broker?: string;
  brokerName?: string;
  expiryDay?: boolean | null;
  hasStopLossOrTarget?: boolean;
  stopLossTargetPlacement?: "attached" | "separate";
  product?: string;
  tradedToday?: boolean | null;
  atMinutes?: number | null;
  circuitLow?: number | null;
  circuitHigh?: number | null;
}

const LEVELS: RuleLevel[] = ["block", "warn", "info"];
const AUTHORITIES = ["regulatory", "exchange", "broker", "product"];
const NOT_PER_ORDER = new Set(["order_rate", "order_budget", "modification_cap", "live_acknowledgement"]);
const NSE_VENUES = new Set(["NSE", "NFO", "NSE_FO", "NSE_FNO", "NSE_EQ", "NSE_CM", "CDS", "NSE_INDEX"]);
const BSE_VENUES = new Set(["BSE", "BFO", "BSE_FO", "BSE_FNO", "BSE_EQ", "BCD", "BSE_INDEX"]);
const DERIVATIVE_VENUES = new Set(["NFO", "NSE_FO", "NSE_FNO", "BFO", "BSE_FO", "BSE_FNO", "MCX", "CDS", "BCD", "NCO"]);
const ORDER_TYPE_ALIASES: Record<string, string> = {
  MARKET: "MARKET",
  MKT: "MARKET",
  LIMIT: "LIMIT",
  LMT: "LIMIT",
  SL: "SL",
  "SL-L": "SL",
  SL_LIMIT: "SL",
  STOP_LIMIT: "SL",
  STOP_LOSS: "SL",
  "SL-M": "SL-M",
  SLM: "SL-M",
  SL_M: "SL-M",
  STOP: "SL-M",
  STOP_LOSS_MARKET: "SL-M",
};
const MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const NAMED_INDICES = ["SENSEX50", "SENSEX", "BANKEX", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTY"];
const CONTRACT_TAIL = new RegExp(`^(\\d{1,2})?(${MONTHS.join("|")})(\\d{2})(\\d+(?:\\.\\d+)?)(CE|PE)$`);

const ROWS = (table as { rules: RuleRow[] }).rules;

/** Every row of the shared table, in file order. */
export function orderRules(): readonly RuleRow[] {
  return ROWS;
}

export function normaliseOrderType(value: string | null | undefined): string {
  const token = String(value ?? "").trim().toUpperCase().replace(/ /g, "_");
  return ORDER_TYPE_ALIASES[token] ?? token;
}

export function exchangeFamily(exchange: string): string {
  const venue = String(exchange ?? "").trim().toUpperCase();
  if (NSE_VENUES.has(venue)) return "NSE";
  if (BSE_VENUES.has(venue)) return "BSE";
  if (venue === "MCX" || venue === "MCX_INDEX") return "MCX";
  return venue;
}

interface OptionParts {
  underlying: string;
  day: string | null;
  month: string;
  year: string;
}

function parseOption(symbol: string): OptionParts | null {
  const name = String(symbol ?? "").trim().toUpperCase();
  if (!name.endsWith("CE") && !name.endsWith("PE")) return null;
  for (const index of NAMED_INDICES) {
    if (!name.startsWith(index)) continue;
    const match = CONTRACT_TAIL.exec(name.slice(index.length));
    if (match) return { underlying: index, day: match[1] ?? null, month: match[2], year: match[3] };
  }
  const generic = /^([A-Z&]+?)(\d{1,2})?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})(\d+(?:\.\d+)?)(CE|PE)$/.exec(name);
  if (!generic) return null;
  return { underlying: generic[1], day: generic[2] ?? null, month: generic[3], year: generic[4] };
}

export function instrumentKind(symbol: string, exchange: string): "option" | "future" | "equity" {
  const name = String(symbol ?? "").trim().toUpperCase();
  const venue = String(exchange ?? "").trim().toUpperCase();
  if (DERIVATIVE_VENUES.has(venue)) {
    // A strike before CE/PE marks an option; RELIANCE ends in CE but is not one.
    return parseOption(name) || /\d[-_ ]?(CE|PE|CALL|PUT)$/.test(name) ? "option" : "future";
  }
  return "equity";
}

export function isOptionContract(symbol: string, exchange: string): boolean {
  return instrumentKind(symbol, exchange) === "option";
}

/** ``YYYY-MM-DD`` expiry spelt in an option symbol, when it carries a day. */
export function contractExpiry(symbol: string): string | null {
  const parts = parseOption(symbol);
  if (!parts || !parts.day || parts.day.length !== 2) return null;
  const month = MONTHS.indexOf(parts.month) + 1;
  return `20${parts.year}-${String(month).padStart(2, "0")}-${parts.day}`;
}

export function underlyingOf(symbol: string): string {
  const name = String(symbol ?? "").trim().toUpperCase();
  const parts = parseOption(name);
  if (parts) return parts.underlying;
  for (const index of NAMED_INDICES) if (name.startsWith(index)) return index;
  return name;
}

// Money is handled in paise so ₹49.90 − ₹39.90 is exactly ₹10.
function paise(rupees: number): number {
  return Math.round(rupees * 100 + (rupees >= 0 ? 1e-7 : -1e-7));
}

function money(p: number): string {
  const rounded = Math.round(p);
  return rounded % 100 === 0 ? String(rounded / 100) : (rounded / 100).toFixed(2);
}

function fill(template: string, values: Record<string, unknown>): string {
  let text = template;
  for (const [key, value] of Object.entries(values)) text = text.split(`{${key}}`).join(String(value));
  return text;
}

function num(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function positive(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

/** Largest allowed stop-loss limit gap from ``trigger``, in paise. */
export function maxStopLimitGapPaise(trigger: number, parameters: Record<string, unknown>): number {
  const flatUpTo = paise(num(parameters.flat_gap_up_to_trigger_inr, 50));
  const minGap = paise(num(parameters.min_gap_inr, 10));
  const pct = num(parameters.max_gap_pct, 20);
  const triggerPaise = paise(trigger);
  if (triggerPaise <= flatUpTo) return minGap;
  return Math.round((triggerPaise * pct) / 100 + 1e-7);
}

/** Band around ``reference`` in paise: the larger of the percentage and the rupee floor. */
export function priceBandPaise(reference: number, parameters: Record<string, unknown>): [number, number] {
  const ref = paise(reference);
  const width = Math.max((ref * num(parameters.band_pct, 40)) / 100, paise(num(parameters.min_band_inr, 20)));
  const low = Math.max(5, ref - width);
  return [Math.round(low + 1e-7), Math.round(ref + width + 1e-7)];
}

function marketBandLabel(reference: number, parameters: Record<string, unknown>, option: boolean): string {
  const tiers = (parameters[option ? "option_tiers" : "other_tiers"] ?? []) as [number | null, string, string?][];
  for (const [upper, value, unit] of tiers) {
    if (upper === null || reference < upper) return unit === "inr" ? `₹${value}` : `${value}%`;
  }
  return "";
}

function minutesOf(hhmm: string): number {
  const [hours, minutes] = hhmm.split(":");
  return Number(hours) * 60 + Number(minutes ?? 0);
}

function inForce(row: RuleRow, on: string): boolean {
  return row.effective_from <= on && (!row.effective_to || on <= row.effective_to);
}

interface Facts extends OrderRuleInput {
  broker: string;
  kind: string;
  venue: string;
  orderType: string;
}

function scopeMatches(row: RuleRow, facts: Facts): boolean {
  const scope = row.scope;
  if (scope.exchange !== "all" && scope.exchange !== facts.venue) return false;
  if (scope.broker !== "all" && scope.broker !== facts.broker) return false;
  if ((scope.unless_broker ?? []).includes(facts.broker)) return false;
  if (scope.instrument === "derivative") {
    if (facts.kind !== "option" && facts.kind !== "future") return false;
  } else if (scope.instrument !== "all" && scope.instrument !== facts.kind) return false;
  if (scope.product && String(facts.product ?? "").toUpperCase() !== scope.product.toUpperCase()) return false;
  if (scope.underlying && underlyingOf(facts.symbol) !== scope.underlying.toUpperCase()) return false;
  if (!scope.order_types.includes("all") && !scope.order_types.includes(facts.orderType)) return false;
  if (scope.expiry_day !== undefined && scope.expiry_day !== null && Boolean(facts.expiryDay) !== scope.expiry_day) {
    return false;
  }
  return true;
}

function evaluateRow(row: RuleRow, facts: Facts): RuleResult | null {
  const source = fill(row.source, { broker_name: facts.brokerName || "Broker" });
  const params = row.parameters ?? {};
  const result = (message: string): RuleResult => ({ level: row.level, source, rule_id: row.id, message });
  switch (row.check) {
    case "order_type_not_allowed":
      return result(row.message);
    case "stop_limit_gap": {
      const trigger = positive(facts.triggerPrice);
      const limit = positive(facts.price);
      if (trigger === null || limit === null) return null;
      const gap = maxStopLimitGapPaise(trigger, params);
      if (Math.abs(paise(limit) - paise(trigger)) <= gap) return null;
      return result(fill(row.message, { max_gap: money(gap) }));
    }
    case "price_band": {
      const reference = positive(facts.lastPrice);
      const limit = positive(facts.price);
      if (reference === null || limit === null) return null;
      const [low, high] = priceBandPaise(reference, params);
      const limitPaise = paise(limit);
      if (low <= limitPaise && limitPaise <= high) return null;
      return result(fill(row.message, { low: money(low), high: money(high) }));
    }
    case "stop_limit_at_trigger": {
      const trigger = positive(facts.triggerPrice);
      const limit = positive(facts.price);
      if (trigger === null || limit === null || paise(limit) !== paise(trigger)) return null;
      return result(row.message);
    }
    case "note":
    case "market_price_cap":
      return result(fill(row.message, params));
    case "separate_stop_loss_target":
      return facts.hasStopLossOrTarget && facts.stopLossTargetPlacement === "separate" ? result(row.message) : null;
    case "circuit_band": {
      const low = positive(facts.circuitLow);
      const high = positive(facts.circuitHigh);
      const limit = positive(facts.price);
      if (low === null || high === null || limit === null || high < low) return null;
      if (paise(low) <= paise(limit) && paise(limit) <= paise(high)) return null;
      return result(fill(row.message, { low: money(paise(low)), high: money(paise(high)) }));
    }
    case "market_band": {
      const reference = positive(facts.lastPrice);
      if (reference === null) return null;
      return result(fill(row.message, { band: marketBandLabel(reference, params, facts.kind === "option") }));
    }
    case "needs_trade_today":
      return facts.tradedToday === false ? result(row.message) : null;
    case "square_off": {
      if (facts.atMinutes === null || facts.atMinutes === undefined) return null;
      const cutoff = minutesOf(String(params.square_off_from ?? "15:25"));
      const lead = num(params.warn_minutes_before, 5);
      if (facts.atMinutes < cutoff - lead) return null;
      return result(fill(row.message, params));
    }
    default:
      return null;
  }
}

/** Every rule result for one order, most serious first. ``on`` is ``YYYY-MM-DD`` (IST). */
export function evaluateOrderRules(input: OrderRuleInput, on: string = istToday()): RuleResult[] {
  const kind = instrumentKind(input.symbol, input.exchange);
  let expiryDay = input.expiryDay ?? null;
  if (expiryDay === null && kind === "option") {
    const expiry = contractExpiry(input.symbol);
    expiryDay = expiry !== null && expiry === on;
  }
  const facts: Facts = {
    ...input,
    broker: input.broker || "all",
    kind,
    venue: exchangeFamily(input.exchange),
    orderType: normaliseOrderType(input.orderType),
    expiryDay,
    stopLossTargetPlacement: input.stopLossTargetPlacement ?? "attached",
  };
  const scored: { key: [number, number, number]; result: RuleResult }[] = [];
  const settled = new Set<string>();
  ROWS.forEach((row, index) => {
    if (NOT_PER_ORDER.has(row.check)) return;
    if (row.family && settled.has(row.family)) return;
    if (!inForce(row, on) || !scopeMatches(row, facts)) return;
    if (row.family) settled.add(row.family);
    const result = evaluateRow(row, facts);
    if (result) scored.push({ key: [LEVELS.indexOf(row.level), AUTHORITIES.indexOf(row.authority), index], result });
  });
  scored.sort((a, b) => a.key[0] - b.key[0] || a.key[1] - b.key[1] || a.key[2] - b.key[2]);
  return scored.map((entry) => entry.result);
}

export interface StopLossLimitInput {
  symbol: string;
  exchange: string;
  exitAction: string;
  trigger: number;
  broker?: string | null;
  product?: string | null;
  tickPaise?: number;
}

/**
 * Limit price for a protective stop-loss leg (mirrors ``stop_loss_limit_price``).
 *
 * The limit sits past the trigger in the exit direction by the widest buffer
 * every matching stop-loss gap and price band row allows, the band measured
 * from the trigger. Without such a row the ``stop_limit_at_trigger`` default
 * buffer applies. Rounded to the tick toward the trigger.
 */
export function stopLossLimitPrice(input: StopLossLimitInput, on: string = istToday()): number | null {
  const trigger = positive(input.trigger);
  if (trigger === null) return null;
  const tick = input.tickPaise ?? 5;
  const sell = String(input.exitAction).toUpperCase() === "SELL";
  const kind = instrumentKind(input.symbol, input.exchange);
  const expiry = kind === "option" ? contractExpiry(input.symbol) : null;
  const facts: Facts = {
    symbol: input.symbol,
    exchange: input.exchange,
    orderType: "SL",
    product: input.product ?? undefined,
    broker: input.broker || "all",
    kind,
    venue: exchangeFamily(input.exchange),
    expiryDay: expiry !== null && expiry === on,
  };
  const triggerPaise = paise(trigger);
  const limits: number[] = [];
  let defaultPct = 0;
  const settled = new Set<string>();
  for (const row of ROWS) {
    if (row.check !== "stop_limit_gap" && row.check !== "price_band" && row.check !== "stop_limit_at_trigger") continue;
    if (row.family && settled.has(row.family)) continue;
    if (!inForce(row, on) || !scopeMatches(row, facts)) continue;
    if (row.family) settled.add(row.family);
    const params = row.parameters ?? {};
    if (row.check === "stop_limit_gap") limits.push(maxStopLimitGapPaise(trigger, params));
    else if (row.check === "price_band") {
      const [low, high] = priceBandPaise(trigger, params);
      limits.push(sell ? triggerPaise - low : high - triggerPaise);
    } else defaultPct = num(params.default_buffer_pct, 0);
  }
  const buffer = limits.length ? Math.min(...limits) : (triggerPaise * defaultPct) / 100;
  const ticks = sell
    ? Math.max(1, Math.ceil((triggerPaise - buffer) / tick - 1e-7))
    : Math.floor((triggerPaise + buffer) / tick + 1e-7);
  return (ticks * tick) / 100;
}

/** The ticket line: the most serious result prefixed by its source. */
export function ruleHeadline(results: readonly RuleResult[]): string {
  const top = results[0];
  return top ? `${top.source} · ${top.message}` : "";
}

export function hasBlockingRule(results: readonly RuleResult[]): boolean {
  return results.some((result) => result.level === "block");
}

/** Read ``rule_results`` from an API error or success payload. */
export function ruleResultsFrom(payload: unknown): RuleResult[] {
  if (!payload || typeof payload !== "object") return [];
  const raw = (payload as { rule_results?: unknown }).rule_results;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is RuleResult =>
      !!item &&
      typeof item === "object" &&
      LEVELS.includes((item as RuleResult).level) &&
      typeof (item as RuleResult).message === "string" &&
      typeof (item as RuleResult).source === "string",
  );
}

/** Text of the Live switch acknowledgement when its dated row is in force, else "". */
export function liveAcknowledgementText(on: string = istToday()): string {
  const row = ROWS.find((item) => item.check === "live_acknowledgement");
  return row && inForce(row, on) ? row.message : "";
}

const BROKER_NAMES: Record<string, string> = {
  practice: "Practice",
  sandbox: "Practice",
  mock: "Practice",
  dhan: "Dhan",
  kotakneo: "Kotak Neo",
  kotak: "Kotak Neo",
  upstox: "Upstox",
  groww: "Groww",
  indmoney: "INDmoney",
  deltaexchange: "Delta Exchange",
};

/** Name shown as the source of a broker rule. */
export function brokerDisplayName(broker: string | null | undefined): string {
  const id = String(broker ?? "").trim().toLowerCase();
  return BROKER_NAMES[id] ?? "Broker";
}

/** Brokers that hold a stop-loss and target with the entry order (mirrors the broker profile). */
const ATTACHED_STOP_LOSS_TARGET = new Set(["dhan", "practice", "sandbox", "mock"]);

export function stopLossTargetPlacement(broker: string | null | undefined): "attached" | "separate" {
  return ATTACHED_STOP_LOSS_TARGET.has(String(broker ?? "").trim().toLowerCase()) ? "attached" : "separate";
}

/** A desk premium as a limit price on the 5-paise tick, or null without one. */
export function optionLimitPrice(premium: number | null | undefined): number | null {
  if (typeof premium !== "number" || !Number.isFinite(premium) || premium <= 0) return null;
  const ticks = Math.max(1, Math.round(premium * 20 + 1e-7));
  return ticks / 20;
}
