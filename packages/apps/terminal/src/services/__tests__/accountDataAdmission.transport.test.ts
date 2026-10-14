/** Public getters with the real decoder/transport; only fetch is synthetic. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getFunds, getOrderbook, getPositionbook, getTradebook } from "../api";
import { useAuthStore } from "@/stores/authStore";
import { resetAccountRuntime, setAccountRuntime } from "@/test-utils/accountQueryHarness";
import {
  CONNECTED_NATIVE_READ_CONTEXT as LIVE,
  PRACTICE_READ_CONTEXT as PRACTICE,
} from "@/test-utils/accountReadFixtures";

const LIVE_FUNDS = "/ft-api/api/v1/native/accounts/dhan/A1/funds";
const ZERO_FUNDS = { availableCash: 0, usedMargin: 0, totalBalance: 0 };
const handlers = new Map<string, () => Response>();
const entered: string[] = [];
const fixtureFailures: string[] = [];
const clockStart = Date.now();
let scenario = 0;

function respond(path: string, data: unknown) {
  handlers.set(`GET ${path}`, () => new Response(JSON.stringify({ status: "success", data }), {
    headers: { "Content-Type": "application/json" },
  }));
}

beforeEach(() => {
  // Preserve the production token bucket without exhausting it across cases.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(clockStart + ++scenario * 1000);
  handlers.clear(); entered.length = 0; fixtureFailures.length = 0;
  setAccountRuntime();
  useAuthStore.setState({ status: "logged-in", token: null, username: "Synthetic" });
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${String(input)}`;
    try {
      const handler = handlers.get(key);
      expect(handler, `Unregistered synthetic request: ${key}`).toBeDefined();
      expect(init.body).toBeUndefined();
      expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBeNull();
      entered.push(key);
      return handler!();
    } catch (error) {
      fixtureFailures.push(`${key}: ${String(error)}`);
      throw error;
    }
  });
});

afterEach(() => {
  resetAccountRuntime();
  useAuthStore.setState({ status: "logged-out", token: null, username: null });
  vi.unstubAllGlobals();
  vi.useRealTimers();
  expect(fixtureFailures).toEqual([]);
  // Every registered exact handler must run once, with no fallback requests.
  expect(entered).toEqual([...handlers.keys()]);
});

const PRACTICE_BOOKS = [
  {
    field: "orders", read: getOrderbook,
    row: { order_id: "SYNTHETIC-ORDER", symbol: "SYNTHETIC", exchange: "NSE", action: "SELL", quantity: "2", avg_fill_px: "100", order_type: "LIMIT", status: "filled", product: "CNC", strategy: "Synthetic", created_at: "2026-04-08T10:00:00+05:30", trigger_price: "0" },
    expected: { orderId: "SYNTHETIC-ORDER", symbol: "SYNTHETIC", exchange: "NSE", action: "SELL", quantity: 2, price: 100, orderType: "LIMIT", status: "filled", product: "CNC", strategy: "Synthetic", timestamp: "2026-04-08T10:00:00+05:30", triggerPrice: 0 },
  },
  {
    field: "trades", read: getTradebook,
    row: { trade_id: "SYNTHETIC-FILL", order_id: "SYNTHETIC-ORDER", symbol: "SYNTHETIC", exchange: "NSE", action: "SELL", quantity: "2", fill_price: "100", traded_at: "2026-04-08T10:00:00+05:30", strategy: "Restored" },
    expected: { tradeId: "SYNTHETIC-FILL", orderId: "SYNTHETIC-ORDER", symbol: "SYNTHETIC", exchange: "NSE", action: "SELL", quantity: 2, price: 100, timestamp: "2026-04-08T10:00:00+05:30", strategy: "Restored" },
  },
  {
    field: "positions", read: getPositionbook,
    row: { symbol: "SYNTHETIC", exchange: "NSE", product: "CNC", net_qty: "2", avg_price: "100", realised_pnl: "0", unrealised_pnl: "10", restored: true, price_source: "ltp", price_age_s: "0" },
    expected: { symbol: "SYNTHETIC", exchange: "NSE", product: "CNC", quantity: 2, averagePrice: 100, ltp: 105, pnl: 10, pnlPercent: 5, restored: true, priceSource: "ltp", priceAgeS: 0 },
  },
];

describe.each(PRACTICE_BOOKS)("Practice $field collection admission", ({ field, read, row, expected }) => {
  const path = `/ft-api/v1/sandbox/${field}`;
  it.each([
    { name: "null payload", data: null },
    { name: "missing payload", data: undefined },
    { name: "bare array instead of producer envelope", data: [] },
    { name: "missing collection", data: {} },
    { name: "null collection", data: { [field]: null } },
    { name: "object collection", data: { [field]: {} } },
    { name: "string collection", data: { [field]: "" } },
    { name: "numeric collection", data: { [field]: 0 } },
    { name: "boolean collection", data: { [field]: false } },
    { name: "null row", data: { [field]: [null] } },
    { name: "array row", data: { [field]: [[]] } },
    { name: "string row", data: { [field]: ["bad"] } },
    { name: "numeric row", data: { [field]: [0] } },
    { name: "boolean row", data: { [field]: [false] } },
    { name: "valid prefix with malformed suffix", data: { [field]: [row, null] } },
    { name: "malformed prefix with valid suffix", data: { [field]: [false, row] } },
  ])("rejects $name instead of certifying a complete empty or partial book", async ({ data }) => {
    respond(path, data);
    await expect(read(PRACTICE)).rejects.toThrow(/book.*malformed/i);
  });

  it("preserves a genuinely empty collection", async () => {
    respond(path, { [field]: [] });
    await expect(read(PRACTICE)).resolves.toEqual([]);
  });

  it("preserves valid producer mapping, numeric aliases and provenance", async () => {
    respond(path, { [field]: [row] });
    await expect(read(PRACTICE)).resolves.toEqual([expected]);
  });
});

describe.each(PRACTICE_BOOKS.filter(({ field }) => field !== "positions"))(
  "Practice $field mapping completeness",
  ({ field, read, row }) => {
    it.each([
      { name: "single unrepresentable record", rows: [{}] },
      { name: "valid prefix followed by missing order identity", rows: [row, { ...row, order_id: "" }] },
      { name: "missing identity followed by valid suffix", rows: [{}, row] },
    ])("rejects $name instead of filtering it out", async ({ rows }) => {
      respond(`/ft-api/v1/sandbox/${field}`, { [field]: rows });
      await expect(read(PRACTICE)).rejects.toThrow(/book.*malformed/i);
    });
  },
);

describe("Practice funds producer admission", () => {
  const path = "/ft-api/v1/sandbox/funds";
  const funds = { available_balance: 100.5, used_margin: 20.25, current_balance: 150.75 };

  it.each([
    { name: "null payload", data: null },
    { name: "missing payload", data: undefined },
    { name: "missing funds", data: {} },
    { name: "null funds", data: { funds: null } },
    { name: "array funds", data: { funds: [] } },
    { name: "scalar funds", data: { funds: 0 } },
    { name: "empty funds", data: { funds: {} } },
    { name: "missing current balance", data: { funds: { available_balance: 100.5, used_margin: 20.25 } } },
    { name: "null current balance", data: { funds: { ...funds, current_balance: null } } },
    { name: "blank cash", data: { funds: { ...funds, available_balance: " " } } },
    { name: "boolean margin", data: { funds: { ...funds, used_margin: false } } },
    { name: "invalid charges", data: { funds: { ...funds, estimated_charges: "unknown" } } },
    { name: "invalid ledger", data: { funds: { ...funds, ledger_balance: "Infinity" } } },
    { name: "invalid MTM flag", data: { funds: { ...funds, futures_mtm_in_ledger: "false" } } },
  ])("rejects $name before projection", async ({ data }) => {
    respond(path, data);
    await expect(getFunds(PRACTICE)).rejects.toThrow(/funds.*malformed/i);
  });

  it.each([
    { name: "genuine zero", funds: { available_balance: 0, used_margin: 0, current_balance: 0 }, expected: ZERO_FUNDS },
    { name: "numeric strings with optional observations", funds: { available_balance: "100.50", used_margin: "20.25", current_balance: "150.75", ledger_balance: "-12.50", estimated_charges: "0", futures_mtm_in_ledger: false }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75, ledgerBalance: -12.5, estimatedCharges: 0, futuresMtmInLedger: false } },
    { name: "omitted optional observations", funds, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
  ])("preserves $name from the sandbox without a Live read", async ({ funds: value, expected }) => {
    respond(path, { funds: value });
    await expect(getFunds(PRACTICE)).resolves.toEqual(expected);
  });
});

describe("funds admission through the public getter", () => {
  it.each([
    { name: "null", value: null },
    { name: "missing data", value: undefined },
    { name: "empty object", value: {} },
    { name: "empty array", value: [] },
    { name: "numeric scalar", value: 0 },
    { name: "string scalar", value: "0" },
    { name: "boolean", value: false },
    { name: "unrelated record", value: { balance: 0 } },
    { name: "missing cash", value: { usedMargin: 0, totalBalance: 0 } },
    { name: "missing margin", value: { availableCash: 0, totalBalance: 0 } },
  ])("rejects $name instead of verifying zero funds", async ({ value }) => {
    respond(LIVE_FUNDS, value);
    await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
  });

  describe.each(["availableCash", "usedMargin", "totalBalance"])("%s", (field) => {
    it.each([
      { name: "null", value: null },
      { name: "empty string", value: "" },
      { name: "blank string", value: "  " },
      { name: "boolean", value: false },
      { name: "array", value: [] },
      { name: "object", value: {} },
      { name: "non-numeric string", value: "unknown" },
      { name: "NaN string", value: "NaN" },
      { name: "infinity string", value: "Infinity" },
      { name: "overflow string", value: "1e999" },
    ])("rejects a supplied $name rather than coercing or deriving it", async ({ value }) => {
      respond(LIVE_FUNDS, { ...ZERO_FUNDS, [field]: value });
      await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
    });
  });

  it.each([
    { name: "canonical zero", value: ZERO_FUNDS, expected: ZERO_FUNDS },
    { name: "canonical strings", value: { availableCash: "100.50", usedMargin: "20.25", totalBalance: "150.75" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
    { name: "native snake case", value: { available_balance: "100.50", used_margin: "20.25", total_balance: "150.75" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
    { name: "lowercase aliases", value: { availablecash: "100.50", utiliseddebits: "20.25", totalbalance: "150.75" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
    { name: "available and total", value: { available: "100.50", usedmargin: "20.25", total: "150.75" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
    { name: "cash and net", value: { cash: "100.50", utilized_margin: "20.25", net: "150.75" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 150.75 } },
    { name: "omitted total", value: { available_balance: " 100.50 ", utilised_margin: "20.25" }, expected: { availableCash: 100.5, usedMargin: 20.25, totalBalance: 120.75 } },
    { name: "negative finite cash", value: { availableCash: -20, usedMargin: 10 }, expected: { availableCash: -20, usedMargin: 10, totalBalance: -10 } },
  ])("preserves $name without inventing optional observations", async ({ value, expected }) => {
    respond(LIVE_FUNDS, value);
    await expect(getFunds(LIVE)).resolves.toEqual(expected);
  });

  describe.each(["estimatedCharges", "estimated_charges", "ledgerBalance", "ledger_balance"])("optional %s", (field) => {
    it.each([
      { name: "null", value: null },
      { name: "blank", value: " " },
      { name: "boolean", value: true },
      { name: "array", value: [] },
      { name: "object", value: {} },
      { name: "non-finite", value: "Infinity" },
      { name: "non-numeric", value: "unknown" },
    ])("rejects a supplied $name rather than inventing or omitting the observation", async ({ value }) => {
      respond(LIVE_FUNDS, { ...ZERO_FUNDS, [field]: value });
      await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
    });
  });

  describe.each(["futuresMtmInLedger", "futures_mtm_in_ledger"])("optional %s", (field) => {
    it.each([
      { name: "null", value: null },
      { name: "string", value: "false" },
      { name: "number", value: 0 },
      { name: "array", value: [] },
      { name: "object", value: {} },
    ])("rejects the non-boolean $name observation", async ({ value }) => {
      respond(LIVE_FUNDS, { ...ZERO_FUNDS, [field]: value });
      await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
    });
  });

  it.each([
    { name: "canonical zero and false", observation: { ledgerBalance: 0, estimatedCharges: 0, futuresMtmInLedger: false }, expected: { ledgerBalance: 0, estimatedCharges: 0, futuresMtmInLedger: false } },
    { name: "snake-case numeric strings and true", observation: { ledger_balance: "-25.50", estimated_charges: "12.25", futures_mtm_in_ledger: true }, expected: { ledgerBalance: -25.5, estimatedCharges: 12.25, futuresMtmInLedger: true } },
  ])("preserves optional $name", async ({ observation, expected }) => {
    respond(LIVE_FUNDS, { ...ZERO_FUNDS, ...observation });
    await expect(getFunds(LIVE)).resolves.toEqual({ ...ZERO_FUNDS, ...expected });
  });

  it("retains observed primary zeros and false rather than falling through to aliases", async () => {
    respond(LIVE_FUNDS, {
      ...ZERO_FUNDS, available_balance: 25, used_margin: 10, net: 35,
      estimatedCharges: 0, estimated_charges: 9,
      ledgerBalance: 0, ledger_balance: 25,
      futuresMtmInLedger: false, futures_mtm_in_ledger: true,
    });
    await expect(getFunds(LIVE)).resolves.toEqual({
      ...ZERO_FUNDS, estimatedCharges: 0, ledgerBalance: 0, futuresMtmInLedger: false,
    });
  });

  it.each(["available_balance", "used_margin", "net", "estimated_charges", "ledger_balance", "futures_mtm_in_ledger"])(
    "does not ignore a malformed supplied %s alias behind a valid primary",
    async (alias) => {
      respond(LIVE_FUNDS, { ...ZERO_FUNDS, estimatedCharges: 0, ledgerBalance: 0, futuresMtmInLedger: false, [alias]: null });
      await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
    },
  );

  it("rejects a JSON numeric overflow, not only string non-finite values", async () => {
    handlers.set(`GET ${LIVE_FUNDS}`, () => new Response(
      '{"status":"success","data":{"availableCash":1e999,"usedMargin":0,"totalBalance":0}}',
      { headers: { "Content-Type": "application/json" } },
    ));
    await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
  });

  it("rejects an overflowing derived total instead of returning zero", async () => {
    respond(LIVE_FUNDS, { availableCash: 1e308, usedMargin: 1e308 });
    await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
  });

  it("does not use a valid alias to hide a malformed primary observation", async () => {
    respond(LIVE_FUNDS, { ...ZERO_FUNDS, availableCash: null, available_balance: 25 });
    await expect(getFunds(LIVE)).rejects.toThrow(/funds.*malformed/i);
  });
});
