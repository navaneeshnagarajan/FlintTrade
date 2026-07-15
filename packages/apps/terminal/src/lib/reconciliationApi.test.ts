/**
 * reconciliationApi.ts unit tests.
 *
 * Locks the route contract (exact dev-proxy URLs through the shared ftApi
 * helpers), the `{status, data}` envelope unwrapping, honest error
 * surfacing (the backend's actionable 503 message must reach the caller),
 * and the run-mutation's cache invalidation.
 *
 * `fetch` is stubbed so no real network calls are made; `import.meta.env.DEV`
 * is stubbed to `true` so `getBase()` returns the Vite-proxy prefix
 * (`/ft-api`) — mirroring `ftApi.helpers.test.ts`.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createElement, useEffect, type ReactNode } from "react";
import { act, render, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FtApiError } from "@/services/ftApi.helpers";

// Force DEV mode so getBase() returns "/ft-api". Stub before the helper
// import because Vite inlines `import.meta.env.DEV` at module-load time.
vi.stubEnv("DEV", true);

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));

const mockAuthState = vi.hoisted(() => ({
  status: "logged-in" as const,
  token: "jwt-alice",
  username: "alice",
  sessionGeneration: 1,
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(
    <T>(selector: (state: typeof mockAuthState) => T): T =>
      selector(mockAuthState),
    { getState: () => mockAuthState },
  ),
}));

import {
  getReconciliationOutcomes,
  getReconciliationReports,
  getReconciliationStatus,
  reconciliationKeys,
  resolveReconciliationOutcome,
  resolutionFromError,
  runReconciliation,
  useReconciliationOutcomes,
  useReconciliationStatus,
  useResolveReconciliationOutcome,
  useRunReconciliation,
  type ReconciliationOutcome,
  type ReconciliationOutcomesResult,
  type ReconciliationPendingResolution,
  type ResolveReconciliationOutcomeVariables,
  type ReconciliationStatus,
} from "./reconciliationApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockedFetch(): ReturnType<typeof vi.fn> {
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

function makeOutcome(
  overrides: Partial<ReconciliationOutcome> = {},
): ReconciliationOutcome {
  return {
    attempt_id: "attempt-123",
    adapter_id: "dhan",
    account_id: "ACC1",
    business_date: "2026-07-15",
    operation: "place_order",
    dispatch_state: "OUTCOME_UNKNOWN",
    intent_source: "manual",
    symbol: "RELIANCE",
    exchange: "NSE",
    product: "MIS",
    action: "BUY",
    quantity: 1,
    price: 1500,
    trigger_price: 0,
    price_type: "MARKET",
    variety: "regular",
    validity: "DAY",
    strategy: "",
    prepared_at: "2026-07-15T09:30:00+00:00",
    invoked_at: "2026-07-15T09:30:01+00:00",
    unknown_at: "2026-07-15T09:30:02+00:00",
    error_kind: "TimeoutError",
    recovery_supported_outcomes: ["confirmed_applied", "confirmed_not_applied"],
    recovery_blocked_reason: "",
    items: [],
    resolution: null,
    ...overrides,
  };
}

function makeOutcomeItem(
  itemIndex: number,
): ReconciliationOutcome["items"][number] {
  return {
    item_index: itemIndex,
    symbol: itemIndex === 0 ? "RELIANCE" : "TCS",
    exchange: "NSE",
    product: "MIS",
    action: "BUY",
    quantity: 1,
    price: 1500 + itemIndex,
    trigger_price: 0,
    price_type: "MARKET",
    variety: "regular",
    validity: "DAY",
    strategy: "",
  };
}

function makeMultiOutcome(
  overrides: Partial<ReconciliationOutcome> = {},
): ReconciliationOutcome {
  return makeOutcome({
    operation: "place_multi_order",
    symbol: "",
    exchange: "",
    product: "",
    action: "",
    quantity: 0,
    price: 0,
    price_type: "",
    variety: "",
    validity: "",
    recovery_supported_outcomes: [
      "confirmed_applied",
      "confirmed_not_applied",
      "confirmed_partial",
    ],
    items: [makeOutcomeItem(0), makeOutcomeItem(1)],
    ...overrides,
  });
}

function makeResolutionVariables(
  bodyOverrides: Partial<ResolveReconciliationOutcomeVariables["body"]> = {},
): ResolveReconciliationOutcomeVariables {
  return {
    attemptId: "attempt-123",
    body: {
      broker: "dhan",
      account_id: "ACC1",
      business_date: "2026-07-15",
      outcome: "confirmed_applied",
      broker_order_ids: ["ORDER-1"],
      broker_order_item_indexes: [],
      not_applied_item_indexes: [],
      confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-123",
      note: "",
      ...bodyOverrides,
    },
  };
}

function makePendingResolution(
  overrides: Partial<ReconciliationPendingResolution> = {},
): ReconciliationPendingResolution {
  return {
    resolution_id: "resolution-1",
    outcome: "confirmed_applied",
    status: "PENDING_AUDIT",
    broker_order_ids: ["ORDER-1"],
    broker_order_item_indexes: [],
    not_applied_item_indexes: [],
    note: "",
    evidence_digest: "digest-1",
    prepared_at: "2026-07-15T09:35:00+00:00",
    ...overrides,
  };
}

function makeStructuredResolutionError(
  resolution: ReconciliationPendingResolution,
): Response {
  return makeJsonResponse(
    {
      status: "error",
      message: `Outcome finalisation remains ${resolution.status}`,
      data: {
        attempt_id: "attempt-123",
        resolution_id: resolution.resolution_id,
        status: resolution.status,
        resolution,
      },
    },
    503,
  );
}

beforeEach(() => {
  mockAuthState.token = "jwt-alice";
  mockAuthState.username = "alice";
  mockAuthState.sessionGeneration = 1;
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("reconciliationKeys", () => {
  it("isolates every authenticated principal", () => {
    expect(reconciliationKeys.status("alice")).not.toStrictEqual(
      reconciliationKeys.status("bob"),
    );
    expect(reconciliationKeys.outcomes("alice")).not.toStrictEqual(
      reconciliationKeys.outcomes("bob"),
    );
    expect(
      reconciliationKeys.reports("alice", "dhan", "ACC1", 5),
    ).not.toStrictEqual(reconciliationKeys.reports("bob", "dhan", "ACC1", 5));
  });
});

// ---------------------------------------------------------------------------
// getReconciliationStatus
// ---------------------------------------------------------------------------

describe("getReconciliationStatus", () => {
  it("GETs the status route with the ft-api dev prefix and unwraps data", async () => {
    const payload: ReconciliationStatus = {
      targets: [
        {
          broker: "dhan",
          account_id: "ACC1",
          last_report_at: "2026-06-12T09:00:00+00:00",
          clean: true,
          severity: "",
          severity_counts: { info: 0, warning: 0, critical: 0 },
          error: "",
        },
      ],
      runner_active: true,
    };
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: payload }),
    );

    const result = await getReconciliationStatus();

    const [url] = mockedFetch().mock.calls[0] as [string];
    expect(url).toBe("/ft-api/api/v1/reconciliation/status");
    expect(result).toStrictEqual(payload);
  });

  it("stores status under the live authenticated principal's query key", async () => {
    const payload: ReconciliationStatus = { targets: [], runner_active: false };
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: payload }),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);

    const { result } = renderHook(() => useReconciliationStatus(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(
      queryClient.getQueryData(reconciliationKeys.status("alice")),
    ).toStrictEqual(payload);
  });

  it("rejects a contradictory clean status instead of rendering it as healthy", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: {
          targets: [
            {
              broker: "dhan",
              account_id: "ACC1",
              last_report_at: "2026-07-15T09:35:00+00:00",
              clean: true,
              severity: "critical",
              severity_counts: { info: 1, warning: 0, critical: 0 },
              error: "",
            },
          ],
          runner_active: true,
        },
      }),
    );

    await expect(getReconciliationStatus()).rejects.toThrow(
      "Reconciliation status evidence is malformed",
    );
  });

  it.each(["", null, "not-a-timestamp", "2026-99-99T25:61:00Z"])(
    "rejects status evidence with invalid last_report_at %s",
    async (lastReportAt) => {
      mockedFetch().mockResolvedValue(
        makeJsonResponse({
          status: "success",
          data: {
            targets: [
              {
                broker: "dhan",
                account_id: "ACC1",
                last_report_at: lastReportAt,
                clean: true,
                severity: "",
                severity_counts: { info: 0, warning: 0, critical: 0 },
                error: "",
              },
            ],
            runner_active: true,
          },
        }),
      );

      await expect(getReconciliationStatus()).rejects.toThrow(
        "Reconciliation status evidence is malformed",
      );
    },
  );
});

// ---------------------------------------------------------------------------
// getReconciliationReports
// ---------------------------------------------------------------------------

describe("getReconciliationReports", () => {
  it("encodes broker, account_id, and limit into the query string", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: { reports: [] } }),
    );

    await getReconciliationReports("dhan", "AC C/1", 3);

    const [url] = mockedFetch().mock.calls[0] as [string];
    expect(url).toBe(
      "/ft-api/api/v1/reconciliation/reports?broker=dhan&account_id=AC+C%2F1&limit=3",
    );
  });

  it("defaults limit to 5 and returns the reports array", async () => {
    const report = {
      adapter_id: "dhan",
      account_id: "ACC1",
      generated_at: "2026-06-12T09:00:00+00:00",
      orders_diff: [],
      positions_diff: [],
      holdings_diff: [],
      error: "",
      clean: true,
      severity: "",
      severity_counts: { info: 0, warning: 0, critical: 0 },
    };
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: { reports: [report] } }),
    );

    const reports = await getReconciliationReports("dhan", "ACC1");

    const [url] = mockedFetch().mock.calls[0] as [string];
    expect(url).toBe(
      "/ft-api/api/v1/reconciliation/reports?broker=dhan&account_id=ACC1&limit=5",
    );
    expect(reports).toStrictEqual([report]);
  });

  it("rejects a response that omits the reports collection", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: {} }),
    );
    await expect(getReconciliationReports("dhan", "ACC1")).rejects.toThrow(
      "Reconciliation reports response is malformed",
    );
  });

  it("rejects malformed report evidence instead of converting it to a clean report", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: {
          reports: [
            null,
            "not-a-report",
            {
              generated_at: 42,
              clean: "yes",
              severity_counts: { warning: 2, critical: "many" },
              orders_diff: [
                null,
                {
                  order_id: "ORDER-1",
                  symbol: { unexpected: true },
                  discrepancy: "missing_at_broker",
                },
              ],
              positions_diff: "not-an-array",
              holdings_diff: [
                { symbol: "INFY", exchange: "NSE", flinttrade_qty: "invalid" },
              ],
            },
          ],
        },
      }),
    );

    await expect(getReconciliationReports("dhan", "ACC1")).rejects.toThrow(
      "Reconciliation report evidence is malformed",
    );
  });

  it("rejects clean report evidence with a non-zero info count", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: {
          reports: [
            {
              adapter_id: "dhan",
              account_id: "ACC1",
              generated_at: "2026-07-15T09:35:00+00:00",
              orders_diff: [],
              positions_diff: [],
              holdings_diff: [],
              error: "",
              clean: true,
              severity: "info",
              severity_counts: { info: 1, warning: 0, critical: 0 },
            },
          ],
        },
      }),
    );

    await expect(getReconciliationReports("dhan", "ACC1")).rejects.toThrow(
      "Reconciliation report evidence is malformed",
    );
  });

  it.each(["", null, "not-a-timestamp", "2026-99-99T25:61:00Z"])(
    "rejects report evidence with invalid generated_at %s",
    async (generatedAt) => {
      mockedFetch().mockResolvedValue(
        makeJsonResponse({
          status: "success",
          data: {
            reports: [
              {
                adapter_id: "dhan",
                account_id: "ACC1",
                generated_at: generatedAt,
                orders_diff: [],
                positions_diff: [],
                holdings_diff: [],
                error: "",
                clean: true,
                severity: "",
                severity_counts: { info: 0, warning: 0, critical: 0 },
              },
            ],
          },
        }),
      );

      await expect(getReconciliationReports("dhan", "ACC1")).rejects.toThrow(
        "Reconciliation report evidence is malformed",
      );
    },
  );
});

describe("resolveReconciliationOutcome", () => {
  const body = {
    broker: "dhan",
    account_id: "ACC1",
    business_date: "2026-07-15",
    outcome: "confirmed_applied" as const,
    broker_order_ids: ["ORDER-1"],
    broker_order_item_indexes: [],
    not_applied_item_indexes: [],
    confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-123",
    note: "",
  };

  it("validates the committed response identity and primitive types", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: {
          resolution_id: "resolution-1",
          attempt_id: "attempt-123",
          outcome: "confirmed_applied",
          status: "COMMITTED",
          evidence_digest: "digest-1",
          router_fault_cleared: true,
          writes_unblocked: false,
          remaining_outcomes: 0,
        },
      }),
    );

    await expect(
      resolveReconciliationOutcome("attempt-123", body),
    ).resolves.toMatchObject({
      attempt_id: "attempt-123",
      outcome: "confirmed_applied",
      writes_unblocked: false,
    });
  });

  it("rejects a mismatched attempt and string boolean in a success envelope", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: {
          resolution_id: "resolution-1",
          attempt_id: "attempt-other",
          outcome: "confirmed_applied",
          status: "COMMITTED",
          evidence_digest: "digest-1",
          router_fault_cleared: true,
          writes_unblocked: "false",
          remaining_outcomes: 0,
        },
      }),
    );

    await expect(
      resolveReconciliationOutcome("attempt-123", body),
    ).rejects.toThrow("Outcome resolution response is malformed");
  });

  it("rejects structured errors whose outer identity disagrees with the requested attempt", () => {
    const error = new FtApiError("committed", 503, {
      attempt_id: "attempt-other",
      resolution_id: "resolution-1",
      status: "COMMITTED",
      resolution: {
        resolution_id: "resolution-1",
        outcome: "confirmed_applied",
        status: "COMMITTED",
        broker_order_ids: ["ORDER-1"],
        broker_order_item_indexes: [],
        not_applied_item_indexes: [],
        note: "",
        evidence_digest: "digest-1",
        prepared_at: "2026-07-15T09:35:00+00:00",
      },
    });

    expect(resolutionFromError(error, "attempt-123")).toBeNull();
  });
});

describe("getReconciliationOutcomes", () => {
  const migratedHistoryReason =
    "Broker identity history is incomplete after ledger migration; " +
    "negative and partial-negative recovery remain fail-closed.";

  it("accepts a complete operation-specific unresolved outcome", async () => {
    const outcome = makeMultiOutcome();
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: { count: 1, outcomes: [outcome] },
      }),
    );

    await expect(getReconciliationOutcomes()).resolves.toStrictEqual({
      count: 1,
      outcomes: [outcome],
    });
  });

  it("accepts migrated positive-only recovery without poisoning fresh outcomes", async () => {
    const migrated = makeOutcome({
      attempt_id: "attempt-migrated",
      recovery_supported_outcomes: ["confirmed_applied"],
      recovery_blocked_reason: migratedHistoryReason,
    });
    const fresh = makeOutcome({ attempt_id: "attempt-fresh" });
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: { count: 2, outcomes: [migrated, fresh] },
      }),
    );

    await expect(getReconciliationOutcomes()).resolves.toStrictEqual({
      count: 2,
      outcomes: [migrated, fresh],
    });
  });

  it("retains zero price and trigger price for valid placement evidence", async () => {
    const outcome = makeOutcome({ price: 0, trigger_price: 0 });
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: { count: 1, outcomes: [outcome] },
      }),
    );

    await expect(getReconciliationOutcomes()).resolves.toStrictEqual({
      count: 1,
      outcomes: [outcome],
    });
  });

  it.each([
    [
      "modify evidence",
      makeOutcome({
        operation: "modify_order",
        symbol: "",
        exchange: "",
        product: "",
        action: "",
        quantity: 0,
        price: 2510,
        price_type: "",
        variety: "",
        validity: "",
      }),
    ],
    [
      "modify evidence with explicit zero prices",
      makeOutcome({
        operation: "modify_order",
        symbol: "",
        exchange: "",
        product: "",
        action: "",
        quantity: 0,
        price: 0,
        trigger_price: 0,
        price_type: "MARKET",
        variety: "",
        validity: "",
      }),
    ],
    [
      "cancel evidence",
      makeOutcome({
        operation: "cancel_order",
        symbol: "",
        exchange: "",
        product: "",
        action: "",
        quantity: 0,
        price: 0,
        price_type: "",
        variety: "",
        validity: "",
      }),
    ],
    [
      "blocked unsupported operation",
      makeOutcome({
        operation: "place_conditional_trigger",
        symbol: "",
        exchange: "",
        product: "",
        action: "",
        quantity: 0,
        price: 0,
        price_type: "",
        variety: "",
        validity: "",
        recovery_supported_outcomes: [],
        recovery_blocked_reason:
          "Operation-specific recovery remains fail-closed.",
      }),
    ],
  ])("accepts valid %s", async (_label, outcome) => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: { count: 1, outcomes: [outcome] },
      }),
    );

    await expect(getReconciliationOutcomes()).resolves.toStrictEqual({
      count: 1,
      outcomes: [outcome],
    });
  });

  it("fails closed instead of hiding a malformed unresolved outcome", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({
        status: "success",
        data: { count: 1, outcomes: [null] },
      }),
    );

    await expect(getReconciliationOutcomes()).rejects.toThrow(
      "Reconciliation outcomes response is malformed",
    );
  });

  const malformedCases: Array<[string, () => unknown]> = [
    [
      "coerced top-level intent field",
      () => ({ count: 1, outcomes: [{ ...makeOutcome(), symbol: 42 }] }),
    ],
    [
      "coerced child intent field",
      () => ({
        count: 1,
        outcomes: [
          makeMultiOutcome({
            items: [
              {
                ...makeOutcomeItem(0),
                quantity: "1",
              } as unknown as ReconciliationOutcome["items"][number],
            ],
          }),
        ],
      }),
    ],
    [
      "placement without material intent evidence",
      () => ({ count: 1, outcomes: [makeOutcome({ symbol: "" })] }),
    ],
    [
      "placement with a negative price",
      () => ({ count: 1, outcomes: [makeOutcome({ price: -1 })] }),
    ],
    [
      "placement with a negative trigger price",
      () => ({ count: 1, outcomes: [makeOutcome({ trigger_price: -1 })] }),
    ],
    [
      "modify with a negative price",
      () => ({
        count: 1,
        outcomes: [makeOutcome({ operation: "modify_order", price: -1 })],
      }),
    ],
    [
      "modify with a negative trigger price",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({ operation: "modify_order", trigger_price: -1 }),
        ],
      }),
    ],
    [
      "cancel with a negative price",
      () => ({
        count: 1,
        outcomes: [makeOutcome({ operation: "cancel_order", price: -1 })],
      }),
    ],
    [
      "cancel with a negative trigger price",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({ operation: "cancel_order", trigger_price: -1 }),
        ],
      }),
    ],
    [
      "modify with a non-finite price",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            operation: "modify_order",
            price: Number.POSITIVE_INFINITY,
          }),
        ],
      }),
    ],
    [
      "cancel with a non-finite trigger price",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({ operation: "cancel_order", trigger_price: Number.NaN }),
        ],
      }),
    ],
    [
      "basket child with a negative price",
      () => ({
        count: 1,
        outcomes: [
          makeMultiOutcome({
            items: [{ ...makeOutcomeItem(0), price: -1 }, makeOutcomeItem(1)],
          }),
        ],
      }),
    ],
    [
      "basket child with a negative trigger price",
      () => ({
        count: 1,
        outcomes: [
          makeMultiOutcome({
            items: [
              { ...makeOutcomeItem(0), trigger_price: -1 },
              makeOutcomeItem(1),
            ],
          }),
        ],
      }),
    ],
    [
      "modify without a requested change",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            operation: "modify_order",
            symbol: "",
            exchange: "",
            product: "",
            action: "",
            quantity: 0,
            price: 0,
            trigger_price: 0,
            price_type: "",
            variety: "",
            validity: "",
            strategy: "",
          }),
        ],
      }),
    ],
    [
      "multi-order with omitted children",
      () => {
        const outcome = { ...makeMultiOutcome() } as Record<string, unknown>;
        delete outcome.items;
        return { count: 1, outcomes: [outcome] };
      },
    ],
    [
      "count that disagrees with the outcome collection",
      () => ({ count: 2, outcomes: [makeOutcome()] }),
    ],
    [
      "duplicate attempt identity",
      () => ({ count: 2, outcomes: [makeOutcome(), makeOutcome()] }),
    ],
    [
      "duplicate basket child index",
      () => ({
        count: 1,
        outcomes: [
          makeMultiOutcome({ items: [makeOutcomeItem(0), makeOutcomeItem(0)] }),
        ],
      }),
    ],
    [
      "operation-incompatible recovery evidence",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            recovery_supported_outcomes: [
              "confirmed_applied",
              "confirmed_not_applied",
              "confirmed_partial",
            ],
          }),
        ],
      }),
    ],
    [
      "empty recovery set when positive proof remains valid",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            recovery_supported_outcomes: [],
            recovery_blocked_reason: migratedHistoryReason,
          }),
        ],
      }),
    ],
    [
      "arbitrary negative-only recovery subset",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            recovery_supported_outcomes: ["confirmed_not_applied"],
            recovery_blocked_reason: migratedHistoryReason,
          }),
        ],
      }),
    ],
    [
      "duplicate positive-only recovery outcome",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            recovery_supported_outcomes: [
              "confirmed_applied",
              "confirmed_applied",
            ],
            recovery_blocked_reason: migratedHistoryReason,
          }),
        ],
      }),
    ],
    [
      "positive-only recovery without its blocking reason",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({
            recovery_supported_outcomes: ["confirmed_applied"],
            recovery_blocked_reason: "",
          }),
        ],
      }),
    ],
    [
      "complete recovery set with a contradictory blocking reason",
      () => ({
        count: 1,
        outcomes: [
          makeOutcome({ recovery_blocked_reason: migratedHistoryReason }),
        ],
      }),
    ],
    [
      "invalid dispatch evidence",
      () => ({
        count: 1,
        outcomes: [makeOutcome({ dispatch_state: "ACKNOWLEDGED" })],
      }),
    ],
    [
      "non-array recovery metadata",
      () => ({
        count: 1,
        outcomes: [
          {
            ...makeOutcome(),
            recovery_supported_outcomes: "confirmed_applied",
          },
        ],
      }),
    ],
  ];

  it.each(malformedCases)("rejects %s", async (_label, data) => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: data() }),
    );

    await expect(getReconciliationOutcomes()).rejects.toThrow(
      "Reconciliation outcomes response is malformed",
    );
  });
});

// ---------------------------------------------------------------------------
// runReconciliation
// ---------------------------------------------------------------------------

describe("runReconciliation", () => {
  it("POSTs the run route and unwraps the cycle result", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: { count: 0, reports: [] } }),
    );

    const result = await runReconciliation();

    const [url, init] = mockedFetch().mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/reconciliation/run");
    expect(init.method).toBe("POST");
    expect(result).toStrictEqual({ count: 0, reports: [] });
  });

  it("surfaces the backend's honest 503 message when the runner is dormant", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse(
        {
          status: "error",
          message:
            "Reconciliation runner not active — no native broker sessions to reconcile",
        },
        503,
      ),
    );

    await expect(runReconciliation()).rejects.toThrow(
      "Reconciliation runner not active",
    );
  });
});

// ---------------------------------------------------------------------------
// useRunReconciliation — cache invalidation
// ---------------------------------------------------------------------------

describe("useRunReconciliation", () => {
  it("invalidates every reconciliation query after a successful run", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse({ status: "success", data: { count: 0, reports: [] } }),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);

    const { result } = renderHook(() => useRunReconciliation(), { wrapper });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: reconciliationKeys.principal("alice"),
    });
  });
});

describe("useResolveReconciliationOutcome", () => {
  it.each(["PENDING_AUDIT", "PENDING_ROUTER_CLEAR"] as const)(
    "updates the cached attempt to %s and invalidates on a state-changing HTTP error",
    async (status) => {
      const pendingData = {
        resolution_id: "resolution-1",
        attempt_id: "attempt-123",
        status,
      };
      mockedFetch().mockResolvedValue(
        makeJsonResponse(
          {
            status: "error",
            message: `Outcome finalisation remains ${status}`,
            data: {
              attempt_id: pendingData.attempt_id,
              resolution_id: pendingData.resolution_id,
              status: pendingData.status,
              resolution: {
                resolution_id: pendingData.resolution_id,
                outcome: "confirmed_partial",
                status: pendingData.status,
                broker_order_ids: ["ORDER-2"],
                broker_order_item_indexes: [1],
                not_applied_item_indexes: [0],
                note: "Verified the basket at the broker",
                evidence_digest: "digest-1",
                prepared_at: "2026-07-15T09:35:00+00:00",
              },
            },
          },
          503,
        ),
      );
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      queryClient.setQueryData(reconciliationKeys.outcomes("alice"), {
        count: 1,
        outcomes: [makeMultiOutcome()],
      });
      const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
      const wrapper = ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client: queryClient }, children);
      const variables: ResolveReconciliationOutcomeVariables = {
        attemptId: "attempt-123",
        body: {
          broker: "dhan",
          account_id: "ACC1",
          business_date: "2026-07-15",
          outcome: "confirmed_partial",
          broker_order_ids: ["ORDER-2"],
          broker_order_item_indexes: [1],
          not_applied_item_indexes: [0],
          confirmation: "CONFIRM PARTIAL dhan:ACC1:attempt-123",
          note: "Verified the basket at the broker",
        },
      };

      const { result } = renderHook(() => useResolveReconciliationOutcome(), {
        wrapper,
      });
      act(() => result.current.mutate(variables));
      await waitFor(() => expect(result.current.isError).toBe(true));

      const cached = queryClient.getQueryData<{
        outcomes: ReconciliationOutcome[];
      }>(reconciliationKeys.outcomes("alice"));
      expect(cached?.outcomes[0]?.resolution).toMatchObject({
        resolution_id: pendingData.resolution_id,
        status: pendingData.status,
        outcome: "confirmed_partial",
        broker_order_ids: ["ORDER-2"],
        broker_order_item_indexes: [1],
        not_applied_item_indexes: [0],
        note: "Verified the basket at the broker",
      });
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: reconciliationKeys.principal("alice"),
      });
    },
  );

  const migratedHistoryReason =
    "Broker identity history is incomplete after ledger migration; " +
    "negative and partial-negative recovery remain fail-closed.";
  const rejectedStructuredErrors: Array<{
    label: string;
    attempt: ReconciliationOutcome;
    variables: ResolveReconciliationOutcomeVariables;
    resolution: ReconciliationPendingResolution;
  }> = [
    {
      label: "an outcome that differs from the submitted decision",
      attempt: makeOutcome({ operation: "cancel_order" }),
      variables: makeResolutionVariables({
        outcome: "confirmed_applied",
        broker_order_ids: [],
        note: "Verified in the broker order book",
      }),
      resolution: makePendingResolution({
        outcome: "confirmed_not_applied",
        broker_order_ids: [],
        note: "Verified in the broker order book",
      }),
    },
    {
      label: "broker evidence that differs from the submitted variables",
      attempt: makeOutcome(),
      variables: makeResolutionVariables({ broker_order_ids: ["ORDER-1"] }),
      resolution: makePendingResolution({ broker_order_ids: ["ORDER-2"] }),
    },
    {
      label: "a confirmation that does not match the exact selector phrase",
      attempt: makeOutcome(),
      variables: makeResolutionVariables({
        confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-other",
      }),
      resolution: makePendingResolution(),
    },
    {
      label:
        "a negative decision unsupported by migrated positive-only recovery",
      attempt: makeOutcome({
        recovery_supported_outcomes: ["confirmed_applied"],
        recovery_blocked_reason: migratedHistoryReason,
      }),
      variables: makeResolutionVariables({
        outcome: "confirmed_not_applied",
        broker_order_ids: [],
        confirmation: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123",
        note: "Verified absent at the broker",
      }),
      resolution: makePendingResolution({
        outcome: "confirmed_not_applied",
        broker_order_ids: [],
        note: "Verified absent at the broker",
      }),
    },
    {
      label:
        "a partial decision unsupported by migrated positive-only recovery",
      attempt: makeMultiOutcome({
        recovery_supported_outcomes: ["confirmed_applied"],
        recovery_blocked_reason: migratedHistoryReason,
      }),
      variables: makeResolutionVariables({
        outcome: "confirmed_partial",
        broker_order_ids: ["ORDER-2"],
        broker_order_item_indexes: [1],
        not_applied_item_indexes: [0],
        confirmation: "CONFIRM PARTIAL dhan:ACC1:attempt-123",
        note: "Verified the basket at the broker",
      }),
      resolution: makePendingResolution({
        outcome: "confirmed_partial",
        broker_order_ids: ["ORDER-2"],
        broker_order_item_indexes: [1],
        not_applied_item_indexes: [0],
        note: "Verified the basket at the broker",
      }),
    },
    {
      label: "operation-invalid placement evidence",
      attempt: makeOutcome(),
      variables: makeResolutionVariables({ broker_order_ids: [] }),
      resolution: makePendingResolution({ broker_order_ids: [] }),
    },
  ];

  it.each(rejectedStructuredErrors)(
    "keeps $label as an ordinary error without mutating cached retry state",
    async ({ attempt, variables, resolution }) => {
      mockedFetch().mockResolvedValue(
        makeStructuredResolutionError(resolution),
      );
      const queryClient = new QueryClient({
        defaultOptions: {
          queries: { retry: false },
          mutations: { retry: false },
        },
      });
      queryClient.setQueryData(reconciliationKeys.outcomes("alice"), {
        count: 1,
        outcomes: [attempt],
      });
      const setQueryDataSpy = vi.spyOn(queryClient, "setQueryData");
      const onError = vi.fn();
      const wrapper = ({ children }: { children: ReactNode }) =>
        createElement(QueryClientProvider, { client: queryClient }, children);
      const { result } = renderHook(
        () => useResolveReconciliationOutcome({ onError }),
        { wrapper },
      );

      act(() => result.current.mutate(variables));
      await waitFor(() => expect(result.current.isError).toBe(true));

      expect(onError).toHaveBeenCalledWith(
        expect.any(FtApiError),
        variables,
        null,
      );
      expect(setQueryDataSpy).not.toHaveBeenCalled();
      expect(
        queryClient.getQueryData<ReconciliationOutcomesResult>(
          reconciliationKeys.outcomes("alice"),
        ),
      ).toEqual({ count: 1, outcomes: [attempt] });
    },
  );

  it("removes a committed attempt from cache after a state-changing HTTP error", async () => {
    mockedFetch().mockResolvedValue(
      makeJsonResponse(
        {
          status: "error",
          message: "Decision committed; status refresh failed",
          data: {
            attempt_id: "attempt-123",
            resolution_id: "resolution-1",
            status: "COMMITTED",
            resolution: {
              resolution_id: "resolution-1",
              outcome: "confirmed_applied",
              status: "COMMITTED",
              broker_order_ids: ["ORDER-1"],
              broker_order_item_indexes: [],
              not_applied_item_indexes: [],
              note: "",
              evidence_digest: "digest-1",
              prepared_at: "2026-07-15T09:35:00+00:00",
            },
          },
        },
        503,
      ),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(reconciliationKeys.outcomes("alice"), {
      count: 1,
      outcomes: [makeOutcome()],
    });
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const variables: ResolveReconciliationOutcomeVariables = {
      attemptId: "attempt-123",
      body: {
        broker: "dhan",
        account_id: "ACC1",
        business_date: "2026-07-15",
        outcome: "confirmed_applied",
        broker_order_ids: ["ORDER-1"],
        broker_order_item_indexes: [],
        not_applied_item_indexes: [],
        confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-123",
        note: "",
      },
    };

    const { result } = renderHook(() => useResolveReconciliationOutcome(), {
      wrapper,
    });
    act(() => result.current.mutate(variables));
    await waitFor(() => expect(result.current.isError).toBe(true));

    expect(
      queryClient.getQueryData(reconciliationKeys.outcomes("alice")),
    ).toEqual({
      count: 0,
      outcomes: [],
    });
  });

  it("runs a hook-level side effect before cache remount and an awaited refetch settle", async () => {
    const pendingResolution = {
      resolution_id: "resolution-1",
      outcome: "confirmed_applied" as const,
      status: "PENDING_AUDIT" as const,
      broker_order_ids: ["ORDER-1"],
      broker_order_item_indexes: [],
      not_applied_item_indexes: [],
      note: "",
      evidence_digest: "digest-1",
      prepared_at: "2026-07-15T09:35:00+00:00",
    };
    let resolveRefetch: ((response: Response) => void) | undefined;
    const deferredRefetch = new Promise<Response>((resolve) => {
      resolveRefetch = resolve;
    });
    const sequence: string[] = [];
    mockedFetch()
      .mockResolvedValueOnce(
        makeJsonResponse(
          {
            status: "error",
            message: "Outcome finalisation remains PENDING_AUDIT",
            data: {
              attempt_id: "attempt-123",
              resolution_id: "resolution-1",
              status: "PENDING_AUDIT",
              resolution: pendingResolution,
            },
          },
          503,
        ),
      )
      .mockImplementationOnce(() => {
        sequence.push("refetch-started");
        return deferredRefetch;
      });
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(reconciliationKeys.outcomes("alice"), {
      count: 1,
      outcomes: [makeOutcome()],
    });
    const variables: ResolveReconciliationOutcomeVariables = {
      attemptId: "attempt-123",
      body: {
        broker: "dhan",
        account_id: "ACC1",
        business_date: "2026-07-15",
        outcome: "confirmed_applied",
        broker_order_ids: ["ORDER-1"],
        broker_order_item_indexes: [],
        not_applied_item_indexes: [],
        confirmation: "CONFIRM APPLIED dhan:ACC1:attempt-123",
        note: "",
      },
    };
    let mutate:
      ((variables: ResolveReconciliationOutcomeVariables) => void) | undefined;
    const observerUnmounted = vi.fn(() => {
      sequence.push("observer-unmounted");
    });
    const requiredSideEffect = vi.fn(() => {
      sequence.push("side-effect");
    });

    function MutationObserver() {
      const mutation = useResolveReconciliationOutcome({
        onError: (_error, _variables, errorResolution) => {
          expect(errorResolution?.resolution.status).toBe("PENDING_AUDIT");
          requiredSideEffect();
        },
      });
      useEffect(() => {
        mutate = mutation.mutate;
        return observerUnmounted;
      }, [mutation.mutate]);
      return null;
    }

    function Harness() {
      const query = useReconciliationOutcomes();
      const outcome = query.data?.outcomes[0];
      if (!outcome) return null;
      const observerKey = `${outcome.attempt_id}:${outcome.resolution?.status ?? "none"}`;
      return createElement(MutationObserver, { key: observerKey });
    }

    const view = render(
      createElement(
        QueryClientProvider,
        { client: queryClient },
        createElement(Harness),
      ),
    );
    await waitFor(() => expect(mutate).toBeTypeOf("function"));

    act(() => mutate?.(variables));

    await waitFor(() => expect(requiredSideEffect).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(observerUnmounted).toHaveBeenCalledTimes(1));
    expect(sequence[0]).toBe("side-effect");
    expect(sequence).toContain("refetch-started");

    resolveRefetch?.(
      makeJsonResponse({
        status: "success",
        data: {
          count: 1,
          outcomes: [
            makeOutcome({
              dispatch_state: "OUTCOME_UNKNOWN",
              resolution: pendingResolution,
            }),
          ],
        },
      }),
    );
    await waitFor(() => {
      const queryState = queryClient.getQueryState(
        reconciliationKeys.outcomes("alice"),
      );
      expect(queryState?.fetchStatus).toBe("idle");
    });
    view.unmount();
  });

  it("ignores a mutation settlement from an older auth generation", async () => {
    let resolveResponse: ((response: Response) => void) | undefined;
    mockedFetch().mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveResponse = resolve;
      }),
    );
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(reconciliationKeys.outcomes("alice"), {
      count: 1,
      outcomes: [makeOutcome()],
    });
    queryClient.setQueryData(reconciliationKeys.outcomes("bob"), {
      count: 0,
      outcomes: [],
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);
    const staleSideEffect = vi.fn();
    const { result } = renderHook(
      () => useResolveReconciliationOutcome({ onError: staleSideEffect }),
      { wrapper },
    );

    act(() => {
      result.current.mutate({
        attemptId: "attempt-123",
        body: {
          broker: "dhan",
          account_id: "ACC1",
          business_date: "2026-07-15",
          outcome: "confirmed_not_applied",
          broker_order_ids: [],
          broker_order_item_indexes: [],
          not_applied_item_indexes: [],
          confirmation: "CONFIRM NOT_APPLIED dhan:ACC1:attempt-123",
          note: "Checked broker",
        },
      });
    });
    mockAuthState.username = "bob";
    mockAuthState.sessionGeneration = 2;
    resolveResponse?.(
      makeJsonResponse(
        {
          status: "error",
          message: "Outcome finalisation remains PENDING_AUDIT",
          data: {
            attempt_id: "attempt-123",
            resolution_id: "resolution-1",
            status: "PENDING_AUDIT",
          },
        },
        503,
      ),
    );
    await waitFor(() => expect(result.current.isError).toBe(true));

    const alice = queryClient.getQueryData<{
      outcomes: ReconciliationOutcome[];
    }>(reconciliationKeys.outcomes("alice"));
    expect(alice?.outcomes[0]?.resolution).toBeNull();
    expect(
      queryClient.getQueryData(reconciliationKeys.outcomes("bob")),
    ).toEqual({
      count: 0,
      outcomes: [],
    });
    expect(staleSideEffect).not.toHaveBeenCalled();
    expect(invalidateSpy).not.toHaveBeenCalled();
  });
});
