import { buildHeaders, get, getBase, isDemoAuthSession, post, del } from "./ftApi.helpers";
import { assertNativeWriteTargetReadyOrThrow, pickNativeBrokerOrderTarget } from "@/services/brokerTargets";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

export interface SafetyConfigRaw {
  l1_order: { price_deviation_pct: number; check_market_hours: boolean; qty_limits: Record<string, number> };
  l2_position: { max_positions: number; max_margin_pct: number };
  l3_portfolio: { max_net_delta: number; max_net_vega: number };
  l4_pnl: { pause_pct: number; kill_pct: number; is_paused: boolean; is_killed: boolean };
  l5_kill: { is_active: boolean; reason: string };
}

export interface SafetyConfig {
  check_market_hours: boolean;
  max_qty_nse: number;
  max_qty_nfo: number;
  max_qty_mcx: number;
  max_positions: number;
  max_margin_pct: number;
  max_net_delta: number;
  max_net_vega: number;
  daily_loss_pause_pct: number;
  daily_loss_kill_pct: number;
  kill_switch_active: boolean;
}

export interface PendingOrder {
  id: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
  order_type: string;
  product: string;
  strategy: string;
  created_at: string;
  reason: string;
}

function flattenSafetyConfig(raw: SafetyConfigRaw): SafetyConfig {
  return {
    check_market_hours: raw.l1_order?.check_market_hours ?? true,
    max_qty_nse: raw.l1_order?.qty_limits?.NSE ?? 1800,
    max_qty_nfo: raw.l1_order?.qty_limits?.NFO ?? 1800,
    max_qty_mcx: raw.l1_order?.qty_limits?.MCX ?? 100,
    max_positions: raw.l2_position?.max_positions ?? 10,
    max_margin_pct: raw.l2_position?.max_margin_pct ?? 80,
    max_net_delta: raw.l3_portfolio?.max_net_delta ?? 1000,
    max_net_vega: raw.l3_portfolio?.max_net_vega ?? 500,
    daily_loss_pause_pct: raw.l4_pnl?.pause_pct ?? 2,
    daily_loss_kill_pct: raw.l4_pnl?.kill_pct ?? 5,
    kill_switch_active: raw.l5_kill?.is_active ?? false,
  };
}

export const getSafetyConfig = async (): Promise<SafetyConfig> => {
  if (isDemoAuthSession()) {
    return flattenSafetyConfig({} as SafetyConfigRaw);
  }
  const raw = await get<SafetyConfigRaw>("safety/config");
  return flattenSafetyConfig(raw);
};

export const updateSafetyConfig = (config: Partial<SafetyConfig>) => {
  const body: Record<string, unknown> = {};
  if (config.check_market_hours !== undefined) body.check_market_hours = config.check_market_hours;
  if (config.max_positions !== undefined) body.max_positions = config.max_positions;
  if (config.max_margin_pct !== undefined) body.max_margin_pct = config.max_margin_pct;
  if (config.max_net_delta !== undefined) body.max_net_delta = config.max_net_delta;
  if (config.max_net_vega !== undefined) body.max_net_vega = config.max_net_vega;
  if (config.daily_loss_pause_pct !== undefined) body.pnl_pause_pct = config.daily_loss_pause_pct;
  if (config.daily_loss_kill_pct !== undefined) body.pnl_kill_pct = config.daily_loss_kill_pct;
  return post<{ status: string }>("safety/config", body);
};

export const activateKillSwitch = (reason: string) =>
  post<{ status: string }>("safety/kill-switch", { reason });

export const resetKillSwitch = () => del<{ status: string }>("safety/kill-switch");

export const getPendingOrders = () =>
  get<{ orders: PendingOrder[] }>("action-center/pending").then(
    (r) => r.orders,
  );

export const approveOrder = (id: string) =>
  post<{ status: string }>(
    "action-center/approve/" + encodeURIComponent(id),
  );

export const rejectOrder = (id: string) =>
  post<{ status: string }>(
    "action-center/reject/" + encodeURIComponent(id),
  );

export const approveAllOrders = () =>
  post<{ status: string; approved_count: number }>("action-center/approve-all");

// NOTE: practice/sandbox mode is owned by the mode state machine
// (ModeIndicator → POST /ft-api/v1/auth/mode + /auth/pin), not a standalone
// `sandbox/config` toggle. The old getSandboxStatus/toggleSandbox helpers
// pointed at /api/v1/sandbox/config — a route that never existed (the engine
// leverage config lives at /v1/sandbox-config/config with a different shape) —
// and were removed in the usability-recovery campaign.

// ---------------------------------------------------------------------------
// Smart-order routing (liquidity-aware slicing through the gated path)
// ---------------------------------------------------------------------------

export interface SmartRouteChild {
  quantity: number;
  price_type: string;
  status: "placed" | "skipped" | "failed";
  order_id: string;
  error: string;
  slippage_bps: number;
  placed_at: string;
}

export interface SmartRouteJob {
  job_id: string;
  created_at: string;
  status: "running" | "done" | "error" | "cancelled";
  cancel_requested: boolean;
  error: string;
  symbol: string;
  exchange: string;
  action: string;
  urgency: string;
  total_quantity: number;
  /** Broker-ACCEPTED quantity (order ids returned) — not confirmed fills. */
  filled_quantity: number;
  average_slippage_bps: number;
  completed: boolean;
  child_orders: SmartRouteChild[];
}

export interface SmartRouteParams {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  urgency: "low" | "medium" | "high";
  max_slippage_bps?: number;
  product?: string;
  account_id?: string;
  broker?: string;
}

function withSmartRouteBrokerTarget(params: SmartRouteParams): SmartRouteParams {
  if (params.broker || params.account_id) return params;

  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const nativeTarget = pickNativeBrokerOrderTarget(mode, apiKey);
  if (nativeTarget) return { ...params, ...nativeTarget };
  // Fail closed like postOrder: a native active account that isn't confirmed
  // connected must not fall through to the bare smart-route path (backend
  // brokers.execution.default) and silently retarget this live order.
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  return params;
}

/**
 * Start a smart-routed order job (202 → initial job snapshot).
 *
 * Uses a direct fetch instead of the shared `post` helper so the backend's
 * actionable 403 messages (feature disabled / wrong mode / safety block)
 * reach the operator verbatim rather than collapsing to "HTTP 403".
 */
export async function startSmartRoute(params: SmartRouteParams): Promise<SmartRouteJob> {
  const resp = await fetch(`${getBase()}/api/v1/orders/smart-route`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(withSmartRouteBrokerTarget(params)),
  });
  const json = (await resp.json().catch(() => null)) as
    | { data?: SmartRouteJob; message?: string }
    | null;
  if (!resp.ok || !json?.data) {
    throw new Error(json?.message ?? `Smart route failed (HTTP ${resp.status})`);
  }
  return json.data;
}

export const getSmartRouteJob = (jobId: string) =>
  get<SmartRouteJob>("orders/smart-route/" + encodeURIComponent(jobId));

export const listSmartRouteJobs = () => get<SmartRouteJob[]>("orders/smart-route");

/** Request cancellation of a running smart-route job (honoured before the next child). */
export const cancelSmartRoute = (jobId: string) =>
  post<SmartRouteJob>("orders/smart-route/" + encodeURIComponent(jobId) + "/cancel");

// ---------------------------------------------------------------------------
// Bracket orders (entry + ONE protective exit leg through the gated path)
// ---------------------------------------------------------------------------

export interface BracketEntryLeg {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  /** 0 places a MARKET entry; a positive price places a LIMIT entry. */
  price: number;
  product: string;
  strategy: string;
}

export interface PlaceBracketParams {
  entry: BracketEntryLeg;
  /** Absolute stop-loss price — mutually exclusive with `target` (no OCO yet). */
  stoploss?: number;
  /** Absolute target price — mutually exclusive with `stoploss` (no OCO yet). */
  target?: number;
  broker?: string;
  account_id?: string;
}

/** Bracket state as serialised by the backend (`BracketOrder.to_dict`). */
export interface BracketOrderData {
  bracket_id: string;
  entry_order_id: string;
  sl_order_id: string | null;
  target_order_id: string | null;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  entry_price: number;
  stoploss: number | null;
  target: number | null;
  trailing_sl: number | null;
  strategy: string;
  product: string;
  broker: string;
  /** "partial" means the entry leg is live but UNPROTECTED — act on it. */
  status: "active" | "partial" | "completed" | "cancelled";
  cancel_warnings: string[];
  created_at: string;
  updated_at: string;
}

export interface PlaceBracketResult {
  /** Backend outcome message — reports PLACEMENT only, never fills. */
  message: string;
  data: BracketOrderData | null;
}

/**
 * Error from the bracket endpoint, carrying the backend's machine code
 * (e.g. `"mode_blocked"`, `"practice_unsupported"`, `"live_locked"`,
 * `"oco_unsupported"`, `"trailing_unsupported"`) so callers can react —
 * a Practice-mode JWT is honestly refused because the sandbox cannot
 * execute multi-leg brackets.
 */
export class BracketApiError extends Error {
  readonly code?: string;
  /** Partial bracket state (entry live but unprotected) when the exit leg failed. */
  readonly data?: BracketOrderData;

  constructor(message: string, code?: string, data?: BracketOrderData) {
    super(message);
    this.name = "BracketApiError";
    this.code = code;
    this.data = data;
  }
}

function withBracketBrokerTarget(params: PlaceBracketParams): PlaceBracketParams {
  if (params.broker || params.account_id) return params;

  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const nativeTarget = pickNativeBrokerOrderTarget(mode, apiKey);
  if (nativeTarget) return { ...params, ...nativeTarget };
  // Fail closed like postOrder/smart-route: a selected-but-unconfirmed native
  // account must not fall through to the bare route (which the backend
  // resolves to brokers.execution.default) and silently retarget these live
  // legs to a broker the operator did not choose.
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  return params;
}

/**
 * Place a bracket order (entry + exactly ONE protective exit leg) through the
 * gated backend route (`POST /api/v1/orders/bracket`) — every leg traverses
 * SafetySystem L1–L5 → `gate_order` → `BrokerRouter`.
 *
 * Uses a direct fetch instead of the shared `post` helper so the backend's
 * actionable refusals reach the operator verbatim — with their machine `code`
 * on the thrown {@link BracketApiError} — rather than collapsing to
 * "HTTP 403". A resolved promise means the legs were PLACED, not filled.
 */
export async function placeBracketOrder(params: PlaceBracketParams): Promise<PlaceBracketResult> {
  const resp = await fetch(`${getBase()}/api/v1/orders/bracket`, {
    method: "POST",
    headers: buildHeaders(true),
    body: JSON.stringify(withBracketBrokerTarget(params)),
  });
  const json = (await resp.json().catch(() => null)) as
    | { status?: string; message?: string; code?: string; error?: string; data?: BracketOrderData }
    | null;
  if (!resp.ok || json?.status !== "success") {
    const message = json?.message ?? `Bracket order failed (HTTP ${resp.status})`;
    throw new BracketApiError(
      json?.error ? `${message}: ${json.error}` : message,
      json?.code,
      json?.data,
    );
  }
  return { message: json.message ?? "Bracket placed", data: json.data ?? null };
}

/** Outcome of a bracket cancel — the backend's honest caveats travel here. */
export interface CancelBracketResult {
  message: string;
  /** Caveats such as a filled MARKET entry position this cancel does NOT close. */
  warnings: string[];
}

/**
 * Cancel a bracket order's resting legs through the gated DELETE route
 * (`DELETE /api/v1/orders/bracket/<id>`). The backend rebinds the cancel to the
 * selector the legs were PLACED on, so this is deliberately best-effort about
 * the broker target and NEVER fails closed on an unresolved native account —
 * cancelling an unprotected position must not be blocked by write-target
 * gating. `data.warnings` carry the honest caveats (e.g. a filled MARKET entry
 * position that removing the protective legs does not close). Direct fetch so
 * the backend message + `code` reach the caller verbatim.
 */
export async function cancelBracket(bracketId: string): Promise<CancelBracketResult> {
  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const target = pickNativeBrokerOrderTarget(mode, apiKey) ?? {};
  const resp = await fetch(`${getBase()}/api/v1/orders/bracket/${encodeURIComponent(bracketId)}`, {
    method: "DELETE",
    headers: buildHeaders(true),
    body: JSON.stringify(target),
  });
  const json = (await resp.json().catch(() => null)) as
    | { status?: string; message?: string; code?: string; error?: string; data?: { warnings?: string[] } }
    | null;
  if (!resp.ok || json?.status !== "success") {
    const message = json?.message ?? `Bracket cancel failed (HTTP ${resp.status})`;
    throw new BracketApiError(json?.error ? `${message}: ${json.error}` : message, json?.code);
  }
  return { message: json.message ?? "Bracket cancelled", warnings: json.data?.warnings ?? [] };
}
