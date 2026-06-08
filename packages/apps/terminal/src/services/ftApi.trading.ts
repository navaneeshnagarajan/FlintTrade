import { get, isDemoAuthSession, post, del } from "./ftApi.helpers";

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

export type PositionSizeMethod =
  | "from_capital"
  | "from_risk_percent"
  | "from_kelly"
  | "max_lots";

export interface PositionSizeRequest {
  method: PositionSizeMethod;
  capital: number;
  ltp?: number;
  lot_size?: number;
  risk_pct?: number;
  entry?: number;
  sl?: number;
  win_rate?: number;
  avg_win?: number;
  avg_loss?: number;
  margin_per_lot?: number;
}

export interface PositionSizeResult {
  quantity: number;
  method: PositionSizeMethod;
  inputs: PositionSizeRequest;
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

export const calculatePositionSize = (req: PositionSizeRequest) =>
  post<PositionSizeResult>("position/size", req);

// NOTE: practice/sandbox mode is owned by the mode state machine
// (ModeIndicator → POST /ft-api/v1/auth/mode + /auth/pin), not a standalone
// `sandbox/config` toggle. The old getSandboxStatus/toggleSandbox helpers
// pointed at /api/v1/sandbox/config — a route that never existed (the engine
// leverage config lives at /v1/sandbox-config/config with a different shape) —
// and were removed in the usability-recovery campaign.
