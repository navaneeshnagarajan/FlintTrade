import type { SyntheticFixtureRegistry } from "../fixture-registry";
import { expect, registerExploreAdvisorStatusProbe, registerOperatorStatusProbes } from "../fixture-registry";

const LOOSE = { minimum: 0, maximum: 32 } as const;

const AUTH_READY = {
  is_setup: true,
  is_locked: false,
  has_pin: false,
  totp_enabled: false,
  vault_open: false,
  setup_finished: true,
  migration_blocked: null,
} as const;

export function registerAuthStatus(
  registry: SyntheticFixtureRegistry,
  data: Record<string, unknown>,
  name = "auth status",
): void {
  registry.register({
    name,
    method: "GET",
    path: "/ft-api/v1/auth/status",
    expectedCalls: { minimum: 1, maximum: 16 },
    handler: (request) => {
      expect(request.postData()).toBeNull();
      return { json: { status: "success", data } };
    },
  });
}

function registerRead(
  registry: SyntheticFixtureRegistry,
  name: string,
  path: string,
  json: unknown,
): void {
  registry.register({
    name,
    method: "GET",
    path,
    expectedCalls: LOOSE,
    handler: (request) => {
      expect(request.postData()).toBeNull();
      return { json };
    },
  });
}

/**
 * Read-only desk mocks shared by Example-session screens.
 *
 * Ranges allow Strict Mode remounts. An unregistered `/ft-api` path still
 * fails the fixture. Nothing here places an order.
 */
export function registerExampleDeskReads(
  registry: SyntheticFixtureRegistry,
  options: { laya?: "ready" | "degraded" | "down" } = {},
): void {
  registerOperatorStatusProbes(registry, {
    expectedCalls: { minimum: 1, maximum: 16 },
    laya: options.laya,
  });
  registerExploreAdvisorStatusProbe(registry, { expectedCalls: { minimum: 1, maximum: 16 } });
  registerAuthStatus(registry, { ...AUTH_READY }, "Mode menu Live-arm status");

  registerRead(registry, "native accounts", "/ft-api/api/v1/native/accounts", { accounts: [] });

  registerRead(registry, "example breadth", "/ft-api/v1/breadth/current", {
    status: "success",
    is_sample_data: true,
    data: { advances: 1240, declines: 860, unchanged: 40 },
  });
  registerRead(registry, "safety configuration", "/ft-api/api/v1/safety/config", {
    status: "success",
    data: { l1_order: {}, l2_position: {}, l3_portfolio: {}, l4_pnl: {}, l5_kill: {} },
  });
  registerRead(registry, "broker capabilities", "/ft-api/api/v1/broker/capabilities", {
    status: "success",
    data: {
      broker_name: "Example",
      broker_type: "multi",
      supported_exchanges: ["NSE", "BSE", "NFO"],
      features: {},
    },
  });
}

export function registerPracticeOrderPadReads(registry: SyntheticFixtureRegistry): void {
  registerRead(registry, "practice sandbox funds", "/ft-api/v1/sandbox/funds", {
    status: "success",
    data: {
      funds: {
        starting_capital: 100_000,
        available_balance: 100_000,
        used_margin: 0,
        realized_pnl: 0,
        current_balance: 100_000,
        ledger_balance: 100_000,
        futures_mtm_in_ledger: false,
      },
    },
  });
  registerRead(registry, "practice sandbox positions", "/ft-api/v1/sandbox/positions", {
    status: "success",
    data: { positions: [] },
  });
  registerRead(registry, "practice sandbox orders", "/ft-api/v1/sandbox/orders", {
    status: "success",
    data: { orders: [] },
  });
}
