/**
 * brokerOrdersApi — typed client + TanStack Query hooks for the gated broker
 * order-management surfaces (forever/GTT, super orders, conditional triggers,
 * multi orders, cancel-all, smart-order cancel).
 *
 * Every endpoint here fronts the backend's single gated execution channel
 * (SafetySystem L1–L5 → gate / gate_broker_write → BrokerRouter), so this
 * module NEVER fabricates success: backend refusals (mode guard, live unlock,
 * kill switch, validation) are thrown verbatim with their HTTP status so the
 * widgets can surface them honestly. A 501 means the selected broker's
 * adapter does not support the operation — {@link isUnsupportedForBroker}
 * lets the UI render that as "Not available for this broker".
 *
 * Requests use a direct fetch (same idiom as `startSmartRoute` in
 * `ftApi.trading.ts`) rather than the shared `post`/`get` helpers because the
 * helpers discard the HTTP status — and the 501 "unsupported broker" mapping
 * needs it.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { buildHeaders, getBase } from "@/services/ftApi.helpers";
import { assertNativeWriteTargetReadyOrThrow, pickNativeBrokerOrderTarget } from "@/services/brokerTargets";
import { queryKeys } from "@/services/queryKeys";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

// ---------------------------------------------------------------------------
// Error type — keeps the HTTP status so the UI can map 501 honestly
// ---------------------------------------------------------------------------

export class BrokerOrdersApiError extends Error {
  /** HTTP status of the failed response (undefined for network failures). */
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "BrokerOrdersApiError";
    this.status = status;
  }
}

/** True when the error is the backend's 501 "adapter lacks this verb" refusal. */
export function isUnsupportedForBroker(error: unknown): boolean {
  return error instanceof BrokerOrdersApiError && error.status === 501;
}

// ---------------------------------------------------------------------------
// Shared types
// ---------------------------------------------------------------------------

/** Broker/account routing target. Defaults to the active native account in native-only Live mode, else OpenAlgo/default. */
export interface BrokerTarget {
  broker?: string;
  account_id?: string;
}

/**
 * One row from an adapter listing (forever orders, super orders, conditional
 * triggers). The shape is broker-specific — the backend forwards the
 * adapter's rows untouched — so consumers must pluck fields defensively.
 */
export type BrokerOrderRow = Record<string, unknown>;

/** Typed order fields the backend coerces into its `Order` model. */
export interface TypedOrderFields {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price?: number;
  trigger_price?: number;
  /** Upstox GTT TARGET rule price. */
  target_price?: number;
  /** Upstox GTT STOPLOSS rule price. */
  stop_loss_price?: number;
  entry_trigger_type?: "ABOVE" | "BELOW" | "IMMEDIATE";
  stop_loss_trigger_type?: "IMMEDIATE";
  target_trigger_type?: "IMMEDIATE";
  product?: string;
  pricetype?: string;
  validity?: string;
}

/** Forever (GTT) placement — typed order plus broker-specific protective legs. */
export interface ForeverOrderPlaceParams extends TypedOrderFields, BrokerTarget {
  variety?: "gtt";
  /** OCO second leg: limit price. */
  price1?: number;
  /** OCO second leg: trigger price. */
  trigger_price1?: number;
  /** OCO second leg: quantity. */
  quantity1?: number;
}

/** Non-empty field map for a gated modify (`changes` object on PUT routes). */
export type OrderChanges = Record<string, string | number>;

/** Super-order legs (Dhan bracket/cover anatomy). */
export const SUPER_ORDER_LEGS = ["ENTRY_LEG", "TARGET_LEG", "STOP_LOSS_LEG"] as const;
export type SuperOrderLeg = (typeof SUPER_ORDER_LEGS)[number];

/**
 * Conditional-trigger condition (Dhan v2 alerts/orders shape). Field names
 * and enums follow the Dhan docs; other adapters may accept extra keys, so
 * an open index signature is kept.
 */
export interface TriggerCondition {
  comparisonType?: string;
  exchangeSegment?: string;
  securityId?: string;
  indicatorName?: string;
  timeFrame?: string;
  operator?: string;
  comparingValue?: number;
  comparingIndicatorName?: string;
  /** Expiry date of the alert (YYYY-MM-DD). */
  expDate?: string;
  frequency?: string;
  userNote?: string;
  [key: string]: unknown;
}

export interface ConditionalTriggerParams extends BrokerTarget {
  condition: TriggerCondition;
  orders: TypedOrderFields[];
}

export interface CancelAllParams {
  broker: string;
  account_id?: string;
  tag?: string;
  segment?: string;
}

// ---------------------------------------------------------------------------
// Fetch core
// ---------------------------------------------------------------------------

type HttpMethod = "GET" | "POST" | "PUT" | "DELETE";

function withNativeBrokerTarget<T extends BrokerTarget>(target: T): T {
  if (target.broker || target.account_id) return target;
  const nativeTarget = pickNativeBrokerOrderTarget(
    useModeStore.getState().mode,
    useConnectionStore.getState().apiKey,
  );
  return nativeTarget ? ({ ...target, ...nativeTarget } as T) : target;
}

function targetQuery(target: BrokerTarget): Record<string, string | undefined> {
  const resolvedTarget = withNativeBrokerTarget(target);
  return { broker: resolvedTarget.broker, account_id: resolvedTarget.account_id };
}

function resolvedBrokerOrderTarget(target: BrokerTarget): Required<BrokerTarget> {
  const resolvedTarget = withNativeBrokerTarget(target);
  return {
    broker: resolvedTarget.broker ?? "openalgo",
    account_id: resolvedTarget.account_id ?? "default",
  };
}

function extractMessage(json: unknown): string | null {
  if (json !== null && typeof json === "object" && "message" in json) {
    const message = (json as { message: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return null;
}

async function request<T>(
  method: HttpMethod,
  path: string,
  options: { body?: object; query?: Record<string, string | undefined> } = {},
): Promise<T> {
  const mode = useModeStore.getState().mode;
  // Every non-GET here is a live broker-management WRITE (forever/GTT, super,
  // conditional-trigger, multi, cancel-all, cancel-smart). Fail closed on the
  // same conditions as the primary order path: refuse while the OpenAlgo config
  // is still hydrating after a reload (so a write can't fall through to the
  // openalgo/default target on a transiently-empty apiKey), and when the
  // selected native account is not confirmed connected.
  if (method !== "GET") {
    assertNativeWriteTargetReadyOrThrow(
      mode,
      useConnectionStore.getState().apiKey,
    );
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, value);
  }
  const queryString = params.toString();
  const url = `${getBase()}/api/v1/${path}${queryString ? `?${queryString}` : ""}`;
  const hasBody = options.body !== undefined;

  let resp: Response;
  try {
    resp = await fetch(url, {
      method,
      headers: buildHeaders(hasBody, mode),
      body: hasBody ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new BrokerOrdersApiError(
      "Cannot reach the FlintTrade backend — check that it is running.",
    );
  }

  const json: unknown = await resp.json().catch(() => null);
  const message = extractMessage(json);
  const isErrorBody =
    json !== null &&
    typeof json === "object" &&
    "status" in json &&
    (json as { status: unknown }).status === "error";

  if (!resp.ok || isErrorBody) {
    throw new BrokerOrdersApiError(
      message ?? `Broker orders API ${path}: HTTP ${resp.status}`,
      resp.status,
    );
  }

  const data =
    json !== null && typeof json === "object" && "data" in json
      ? (json as { data: unknown }).data
      : json;
  return data as T;
}

function asRows(value: unknown): BrokerOrderRow[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (row): row is BrokerOrderRow =>
      row !== null && typeof row === "object" && !Array.isArray(row),
  );
}

// ---------------------------------------------------------------------------
// Forever (GTT) orders
// ---------------------------------------------------------------------------

export async function listForeverOrders(target: BrokerTarget = {}): Promise<BrokerOrderRow[]> {
  return asRows(await request<unknown>("GET", "orders/forever", { query: targetQuery(target) }));
}

export function placeForeverOrder(params: ForeverOrderPlaceParams): Promise<unknown> {
  return request<unknown>("POST", "orders/forever", {
    body: { variety: "gtt", ...withNativeBrokerTarget(params) },
  });
}

export function modifyForeverOrder(
  params: { order_id: string; changes: OrderChanges } & BrokerTarget,
): Promise<unknown> {
  const { order_id, changes, ...target } = params;
  return request<unknown>("PUT", `orders/forever/${encodeURIComponent(order_id)}`, {
    body: { changes, ...withNativeBrokerTarget(target) },
  });
}

export function cancelForeverOrder(
  params: { order_id: string } & BrokerTarget,
): Promise<unknown> {
  return request<unknown>("DELETE", `orders/forever/${encodeURIComponent(params.order_id)}`, {
    query: targetQuery(params),
  });
}

// ---------------------------------------------------------------------------
// Super orders (entry + target + stop-loss legs)
// ---------------------------------------------------------------------------

export async function listSuperOrders(target: BrokerTarget = {}): Promise<BrokerOrderRow[]> {
  return asRows(await request<unknown>("GET", "orders/super", { query: targetQuery(target) }));
}

/** Modify one leg — `changes.leg_name` selects ENTRY_LEG / TARGET_LEG / STOP_LOSS_LEG. */
export function modifySuperOrder(
  params: { order_id: string; changes: OrderChanges } & BrokerTarget,
): Promise<unknown> {
  const { order_id, changes, ...target } = params;
  return request<unknown>("PUT", `orders/super/${encodeURIComponent(order_id)}`, {
    body: { changes, ...withNativeBrokerTarget(target) },
  });
}

/** Cancel a super order, or one leg via `leg` (ENTRY_LEG cancels every leg). */
export function cancelSuperOrder(
  params: { order_id: string; leg?: SuperOrderLeg } & BrokerTarget,
): Promise<unknown> {
  return request<unknown>("DELETE", `orders/super/${encodeURIComponent(params.order_id)}`, {
    query: { ...targetQuery(params), leg: params.leg },
  });
}

// ---------------------------------------------------------------------------
// Conditional triggers (price / technical-indicator alerts that place orders)
// ---------------------------------------------------------------------------

export async function listConditionalTriggers(
  target: BrokerTarget = {},
): Promise<BrokerOrderRow[]> {
  return asRows(await request<unknown>("GET", "orders/triggers", { query: targetQuery(target) }));
}

export function placeConditionalTrigger(params: ConditionalTriggerParams): Promise<unknown> {
  return request<unknown>("POST", "orders/triggers", {
    body: withNativeBrokerTarget(params),
  });
}

/** Full replacement modify — condition + orders are resent in entirety. */
export function modifyConditionalTrigger(
  params: { alert_id: string } & ConditionalTriggerParams,
): Promise<unknown> {
  const { alert_id, ...body } = params;
  return request<unknown>("PUT", `orders/triggers/${encodeURIComponent(alert_id)}`, {
    body: withNativeBrokerTarget(body),
  });
}

export function cancelConditionalTrigger(
  params: { alert_id: string } & BrokerTarget,
): Promise<unknown> {
  return request<unknown>("DELETE", `orders/triggers/${encodeURIComponent(params.alert_id)}`, {
    query: targetQuery(params),
  });
}

// ---------------------------------------------------------------------------
// Batch + sweep verbs
// ---------------------------------------------------------------------------

/** Place a batch of typed orders — every leg passes SafetySystem L1–L5. */
export function placeMultiOrder(
  params: { orders: TypedOrderFields[] } & BrokerTarget,
): Promise<unknown> {
  return request<unknown>("POST", "orders/multi", {
    body: withNativeBrokerTarget(params),
  });
}

/** Cancel all open orders for a broker (optionally narrowed by tag/segment). */
export function cancelAllOrders(params: CancelAllParams): Promise<unknown> {
  return request<unknown>("POST", "orders/cancel-all", {
    body: withNativeBrokerTarget(params),
  });
}

/** Cancel a smart order (IndMoney-native), optionally narrowed by segment. */
export function cancelSmartOrder(
  params: { order_id: string; segment?: string } & BrokerTarget,
): Promise<unknown> {
  return request<unknown>("DELETE", `orders/smart/${encodeURIComponent(params.order_id)}`, {
    query: { ...targetQuery(params), segment: params.segment },
  });
}

// ---------------------------------------------------------------------------
// TanStack Query keys — same `.all` / `.list()` convention as queryKeys.ts
// ---------------------------------------------------------------------------

export const brokerOrderKeys = {
  all: ["brokerOrders"] as const,
  forever: {
    all: ["brokerOrders", "forever"] as const,
    list: (target: BrokerTarget = {}) => {
      const resolvedTarget = resolvedBrokerOrderTarget(target);
      return [
        ...brokerOrderKeys.forever.all,
        resolvedTarget.broker,
        resolvedTarget.account_id,
      ] as const;
    },
  },
  superOrders: {
    all: ["brokerOrders", "super"] as const,
    list: (target: BrokerTarget = {}) => {
      const resolvedTarget = resolvedBrokerOrderTarget(target);
      return [
        ...brokerOrderKeys.superOrders.all,
        resolvedTarget.broker,
        resolvedTarget.account_id,
      ] as const;
    },
  },
  triggers: {
    all: ["brokerOrders", "triggers"] as const,
    list: (target: BrokerTarget = {}) => {
      const resolvedTarget = resolvedBrokerOrderTarget(target);
      return [
        ...brokerOrderKeys.triggers.all,
        resolvedTarget.broker,
        resolvedTarget.account_id,
      ] as const;
    },
  },
} as const;

// ---------------------------------------------------------------------------
// Query hooks (lists). retry: false — every failure here is actionable
// (mode guard, broker not connected, 501 unsupported), not transient.
// ---------------------------------------------------------------------------

export interface BrokerOrdersQueryOptions {
  enabled?: boolean;
}

export function useForeverOrders(
  target: BrokerTarget = {},
  options: BrokerOrdersQueryOptions = {},
): UseQueryResult<BrokerOrderRow[], Error> {
  return useQuery({
    queryKey: brokerOrderKeys.forever.list(target),
    queryFn: () => listForeverOrders(target),
    enabled: options.enabled ?? true,
    retry: false,
  });
}

export function useSuperOrders(
  target: BrokerTarget = {},
  options: BrokerOrdersQueryOptions = {},
): UseQueryResult<BrokerOrderRow[], Error> {
  return useQuery({
    queryKey: brokerOrderKeys.superOrders.list(target),
    queryFn: () => listSuperOrders(target),
    enabled: options.enabled ?? true,
    retry: false,
  });
}

export function useConditionalTriggers(
  target: BrokerTarget = {},
  options: BrokerOrdersQueryOptions = {},
): UseQueryResult<BrokerOrderRow[], Error> {
  return useQuery({
    queryKey: brokerOrderKeys.triggers.list(target),
    queryFn: () => listConditionalTriggers(target),
    enabled: options.enabled ?? true,
    retry: false,
  });
}

// ---------------------------------------------------------------------------
// Mutation hooks — each invalidates its listing namespace on success so the
// widgets re-read REAL broker state rather than optimistically faking rows.
// ---------------------------------------------------------------------------

type Mutation<TVariables> = UseMutationResult<unknown, Error, TVariables>;

function useInvalidating<TVariables>(
  mutationFn: (variables: TVariables) => Promise<unknown>,
  invalidateKeys: readonly (readonly string[])[],
): Mutation<TVariables> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => {
      for (const queryKey of invalidateKeys) {
        void queryClient.invalidateQueries({ queryKey });
      }
    },
  });
}

export function usePlaceForeverOrder(): Mutation<ForeverOrderPlaceParams> {
  return useInvalidating(placeForeverOrder, [brokerOrderKeys.forever.all]);
}

export function useModifyForeverOrder(): Mutation<
  { order_id: string; changes: OrderChanges } & BrokerTarget
> {
  return useInvalidating(modifyForeverOrder, [brokerOrderKeys.forever.all]);
}

export function useCancelForeverOrder(): Mutation<{ order_id: string } & BrokerTarget> {
  return useInvalidating(cancelForeverOrder, [brokerOrderKeys.forever.all]);
}

export function useModifySuperOrder(): Mutation<
  { order_id: string; changes: OrderChanges } & BrokerTarget
> {
  return useInvalidating(modifySuperOrder, [brokerOrderKeys.superOrders.all]);
}

export function useCancelSuperOrder(): Mutation<
  { order_id: string; leg?: SuperOrderLeg } & BrokerTarget
> {
  return useInvalidating(cancelSuperOrder, [brokerOrderKeys.superOrders.all]);
}

export function usePlaceConditionalTrigger(): Mutation<ConditionalTriggerParams> {
  return useInvalidating(placeConditionalTrigger, [brokerOrderKeys.triggers.all]);
}

export function useModifyConditionalTrigger(): Mutation<
  { alert_id: string } & ConditionalTriggerParams
> {
  return useInvalidating(modifyConditionalTrigger, [brokerOrderKeys.triggers.all]);
}

export function useCancelConditionalTrigger(): Mutation<{ alert_id: string } & BrokerTarget> {
  return useInvalidating(cancelConditionalTrigger, [brokerOrderKeys.triggers.all]);
}

export function usePlaceMultiOrder(): Mutation<
  { orders: TypedOrderFields[] } & BrokerTarget
> {
  // A multi-order placement lands in the regular order book — invalidate it.
  return useInvalidating(placeMultiOrder, [queryKeys.orders.all]);
}

export function useCancelAllOrders(): Mutation<CancelAllParams> {
  return useInvalidating(cancelAllOrders, [queryKeys.orders.all]);
}

export function useCancelSmartOrder(): Mutation<
  { order_id: string; segment?: string } & BrokerTarget
> {
  return useInvalidating(cancelSmartOrder, [queryKeys.orders.all]);
}
