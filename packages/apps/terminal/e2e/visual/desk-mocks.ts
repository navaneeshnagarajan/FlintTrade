import type { SyntheticFixtureRegistry } from "../fixture-registry";
import { expect, registerExploreAdvisorStatusProbe, registerOperatorStatusProbes } from "../fixture-registry";
import systemDiagnostics from "./system-diagnostics.normal-factory.json" with { type: "json" };

/** SystemStatusBar's shared query: one completed initial body, with only the
 * existing StrictMode aborted-start allowance. No poll or failed-fetch budget.
 * Captured from create_flask_app's real diagnostics route with unavailable host
 * collectors; unknown capacity and partial coverage are not healthy zeros. */
export function registerSystemDiagnosticsRead(registry: SyntheticFixtureRegistry, token: string): void {
  registry.register({
    name: "global status normal-factory diagnostic snapshot",
    method: "GET", path: "/ft-api/api/v1/system/diagnostics",
    readPhase: "startup", expectedCalls: 1,
    handler: (request) => {
      expect(request.headers()["authorization"]).toBe(`Bearer ${token}`);
      expect(request.headers()["x-api-key"]).toBeUndefined();
      expect(request.postData()).toBeNull();
      return { json: systemDiagnostics };
    },
  });
}

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
