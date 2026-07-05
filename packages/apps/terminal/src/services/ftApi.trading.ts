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
