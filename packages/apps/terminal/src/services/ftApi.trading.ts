import { buildHeaders, get, getBase, isDemoAuthSession, post, del } from "./ftApi.helpers";
import { assertNativeWriteTargetReadyOrThrow, pickNativeBrokerOrderTarget } from "@/services/brokerTargets";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";

export interface SafetyConfigRaw {
  l1_order: { price_deviation_pct: number; check_market_hours: boolean; qty_limits: Record<string, number> };
  l2_position: { max_positions: number; max_margin_pct: number };
  l3_portfolio: { max_net_delta: number; max_net_vega: number };
  l4_pnl: {
    pause_pct: number;
    kill_pct: number;
    selector?: string | null;
    opening_risk_capital?: number;
    is_paused: boolean;
    is_killed: boolean;
    accounts?: Array<{
      selector: string;
      session_key: string;
      opening_risk_capital: number;
      is_paused: boolean;
      is_killed: boolean;
    }>;
  };
  l5_kill: {
    is_active: boolean;
    reason: string;
    flatten_complete?: boolean;
    emergency_result?: EmergencyDispatchResult | null;
  };
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
  daily_loss_selector?: string | null;
  opening_risk_capital?: number;
  daily_loss_accounts?: SafetyConfigRaw["l4_pnl"]["accounts"];
  daily_loss_pause_active?: boolean;
  daily_loss_hard_stop_active?: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string;
  flatten_complete: boolean;
  emergency_result: EmergencyDispatchResult | null;
}

export interface SafetyAccountTarget {
  broker: string;
  account_id: string;
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

export interface EmergencyActionOutcome {
  verb: string;
  attempted: boolean;
  succeeded: boolean;
  failure_code: string | null;
}

export interface EmergencyTargetResult {
  selector: string;
  complete: boolean;
  outcomes: EmergencyActionOutcome[];
}

export interface EmergencyDispatchResult {
  policy: string;
  complete: boolean;
  target_count: number;
  completed_target_count: number;
  summary: string;
  targets: EmergencyTargetResult[];
  outcomes: EmergencyActionOutcome[];
}

export interface KillSwitchActivation {
  message: string;
  reason: string;
  is_active: boolean;
  emergency_actions: EmergencyDispatchResult;
}

function flattenSafetyConfig(raw: SafetyConfigRaw): SafetyConfig {
  const killSwitchActive = raw.l5_kill?.is_active ?? false;
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
    daily_loss_selector: raw.l4_pnl?.selector ?? null,
    opening_risk_capital: raw.l4_pnl?.opening_risk_capital ?? 0,
    daily_loss_accounts: raw.l4_pnl?.accounts ?? [],
    daily_loss_pause_active: raw.l4_pnl?.is_paused ?? false,
    daily_loss_hard_stop_active: raw.l4_pnl?.is_killed ?? false,
    kill_switch_active: killSwitchActive,
    kill_switch_reason: raw.l5_kill?.reason ?? "",
    flatten_complete: raw.l5_kill?.flatten_complete ?? !killSwitchActive,
    emergency_result: raw.l5_kill?.emergency_result ?? null,
  };
}

function safetyAccountTarget(): SafetyAccountTarget | undefined {
  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const nativeTarget = pickNativeBrokerOrderTarget(mode, apiKey);
  if (nativeTarget) return nativeTarget;
  if (mode === "live" && apiKey.trim()) return { broker: "openalgo", account_id: "default" };
  return undefined;
}

function safetyTargetQuery(target: SafetyAccountTarget | undefined): string {
  if (!target) return "";
  return `?broker=${encodeURIComponent(target.broker)}&account_id=${encodeURIComponent(target.account_id)}`;
}

async function fetchSafetyConfig(target: SafetyAccountTarget | undefined): Promise<SafetyConfig> {
  if (isDemoAuthSession()) {
    return flattenSafetyConfig({} as SafetyConfigRaw);
  }
  const raw = await get<SafetyConfigRaw>(`safety/config${safetyTargetQuery(target)}`);
  return flattenSafetyConfig(raw);
}

export const getSafetyConfig = (): Promise<SafetyConfig> => fetchSafetyConfig(safetyAccountTarget());

export const getSafetyConfigForTarget = (target: SafetyAccountTarget): Promise<SafetyConfig> => (
  fetchSafetyConfig(target)
);

export const updateSafetyConfig = (
  config: Partial<SafetyConfig>,
  target = safetyAccountTarget(),
) => {
  const body: Record<string, unknown> = {};
  if (config.check_market_hours !== undefined) body.check_market_hours = config.check_market_hours;
  if (config.max_positions !== undefined) body.max_positions = config.max_positions;
  if (config.max_margin_pct !== undefined) body.max_margin_pct = config.max_margin_pct;
  if (config.max_net_delta !== undefined) body.max_net_delta = config.max_net_delta;
  if (config.max_net_vega !== undefined) body.max_net_vega = config.max_net_vega;
  if (config.daily_loss_pause_pct !== undefined) body.pnl_pause_pct = config.daily_loss_pause_pct;
  if (config.daily_loss_kill_pct !== undefined) body.pnl_kill_pct = config.daily_loss_kill_pct;
  if (config.opening_risk_capital !== undefined) {
    if (Object.keys(body).length > 0) {
      throw new Error("Opening risk capital must be configured separately from global safety limits");
    }
    if (!target) throw new Error("Select a connected execution account before setting opening risk capital");
    body.opening_risk_capital = config.opening_risk_capital;
    body.broker = target.broker;
    body.account_id = target.account_id;
  }
  return post<{ status: string }>("safety/config", body);
};

export const resetDailyPnLState = (target = safetyAccountTarget()) => {
  if (!target) throw new Error("Select a connected execution account before resetting daily-loss state");
  return del<{
    selector: string;
    session_key: string;
    opening_risk_capital: number;
    is_paused: boolean;
    is_killed: boolean;
  }>(`safety/l4${safetyTargetQuery(target)}`);
};

export const activateKillSwitch = (reason: string) =>
  post<KillSwitchActivation>("safety/kill-switch", { reason });

export const resetKillSwitch = () => del<{ message: string }>("safety/kill-switch");

export const getPendingOrders = () =>
  get<{ orders: PendingOrder[] }>("action-center/pending").then(
    (r) => r.orders,
  );

/**
 * Approve a queued order — this releases it to the broker, so it is a live
 * order dispatch and fails closed on an unready native write target exactly
 * as `postOrder` does. Approving while the target is still hydrating could
 * send the order to `brokers.execution.default` instead of the account the
 * operator is looking at.
 */
export const approveOrder = async (id: string) => {
  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  assertNativeWriteTargetReadyOrThrow(mode, apiKey);
  return post<{ status: string }>(
    "action-center/approve/" + encodeURIComponent(id),
  );
};

/**
 * Reject a queued order. Not gated: refusing to send an order is
 * risk-reducing and must always be available.
 */
export const rejectOrder = (id: string) =>
  post<{ status: string }>(
    "action-center/reject/" + encodeURIComponent(id),
  );

// NOTE: practice/sandbox mode is owned by the mode state machine
// (ModeIndicator → POST /ft-api/v1/auth/mode + /auth/pin), not a standalone
// Practice policy is edited through the canonical /v1/sandbox/config surface
// in SandboxControls; there is no second runtime toggle or config store.

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
  if (params.broker !== undefined || params.account_id !== undefined) {
    const broker = params.broker?.trim();
    const accountId = params.account_id?.trim();
    if (!broker || !accountId) {
      throw new Error("Broker and account ID must be supplied together for a smart-routed order");
    }
    return { ...params, broker, account_id: accountId };
  }

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

/**
 * Request cancellation of a running smart-route job (honoured before the next
 * child order).
 *
 * Deliberately NOT write-target gated, for the same reason as `cancelBracket`:
 * stopping a job that is still slicing real orders into the market is
 * risk-reducing, and must never be blocked by native write-target hydration.
 * The job already carries the selector its children are placed on, so there is
 * no target to resolve here.
 */
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
  if (params.broker !== undefined || params.account_id !== undefined) {
    const broker = params.broker?.trim();
    const accountId = params.account_id?.trim();
    if (!broker || !accountId) {
      throw new Error("Broker and account ID must be supplied together for a bracket order");
    }
    return { ...params, broker, account_id: accountId };
  }

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
