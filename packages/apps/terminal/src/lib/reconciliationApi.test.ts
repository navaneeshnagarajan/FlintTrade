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
import { createElement, type ReactNode } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Force DEV mode so getBase() returns "/ft-api". Stub before the helper
// import because Vite inlines `import.meta.env.DEV` at module-load time.
vi.stubEnv("DEV", true);

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "" }) },
}));

import {
  getReconciliationReports,
  getReconciliationStatus,
  reconciliationKeys,
  runReconciliation,
  useRunReconciliation,
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

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
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
    mockedFetch().mockResolvedValue(makeJsonResponse({ status: "success", data: payload }));

    const result = await getReconciliationStatus();

    const [url] = mockedFetch().mock.calls[0] as [string];
    expect(url).toBe("/ft-api/api/v1/reconciliation/status");
    expect(result).toStrictEqual(payload);
  });
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

  it("returns an empty array when the backend omits reports", async () => {
    mockedFetch().mockResolvedValue(makeJsonResponse({ status: "success", data: {} }));
    await expect(getReconciliationReports("dhan", "ACC1")).resolves.toStrictEqual([]);
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
          message: "Reconciliation runner not active — no native broker sessions to reconcile",
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
      makeJsonResponse({ status: "success", data: { count: 1, reports: [] } }),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children);

    const { result } = renderHook(() => useRunReconciliation(), { wrapper });
    result.current.mutate();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: reconciliationKeys.all });
  });
});
