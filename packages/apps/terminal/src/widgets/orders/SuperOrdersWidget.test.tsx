/**
 * SuperOrdersWidget.test — live-mode gating, listing, leg-aware modify
 * (changes.leg_name) and leg-aware cancel (?leg=), plus the 501 mapping.
 *
 * The global fetch is stubbed so the REAL brokerOrdersApi client runs.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockMode = "live";
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
}));

import SuperOrdersWidget from "./SuperOrdersWidget";

const LIST_ROW = {
  order_id: "SO-1",
  symbol: "TCS",
  action: "BUY",
  quantity: 5,
  price: 3500,
  target_price: 3600,
  stop_loss_price: 3450,
  status: "PENDING",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let listRows: unknown[] = [LIST_ROW];
let listStatus = 200;
let listMessage = "";

const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
  const method = init?.method ?? "GET";
  if (method === "GET") {
    if (listStatus !== 200) {
      return Promise.resolve(jsonResponse({ status: "error", message: listMessage }, listStatus));
    }
    return Promise.resolve(jsonResponse({ status: "success", data: listRows }));
  }
  return Promise.resolve(jsonResponse({ status: "success", orderid: "SO-1", data: "SO-1" }));
});

function callsByMethod(method: string): [string, RequestInit][] {
  return fetchMock.mock.calls.filter(
    ([, init]) => ((init as RequestInit | undefined)?.method ?? "GET") === method,
  ) as [string, RequestInit][];
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SuperOrdersWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockMode = "live";
  listRows = [LIST_ROW];
  listStatus = 200;
  listMessage = "";
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SuperOrdersWidget", () => {
  it("renders the header", () => {
    renderWidget();
    expect(screen.getByText("Super Orders")).toBeInTheDocument();
  });

  it("outside Live mode: honest notice and no fetch", () => {
    mockMode = "explore";
    renderWidget();
    expect(screen.getByText(/live-broker constructs/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lists super orders with leg-level prices", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("TCS")).toBeInTheDocument());
    expect(screen.getByText("3600")).toBeInTheDocument(); // target leg
    expect(screen.getByText("3450")).toBeInTheDocument(); // stop-loss leg
    const [url] = callsByMethod("GET")[0];
    expect(url).toContain("/api/v1/orders/super");
  });

  it("cancels with the selected leg in the query string", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("TCS")).toBeInTheDocument());
    // Default cancel scope is ENTRY_LEG (cancels every leg).
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    await waitFor(() => expect(callsByMethod("DELETE").length).toBe(1));
    const [url] = callsByMethod("DELETE")[0];
    expect(url).toContain("/api/v1/orders/super/SO-1");
    expect(url).toContain("leg=ENTRY_LEG");
  });

  it("modifies one leg via changes.leg_name", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("TCS")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    // Default leg in the modify panel is TARGET_LEG.
    fireEvent.change(screen.getByLabelText("New leg price"), { target: { value: "3650" } });
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [url, init] = callsByMethod("PUT")[0];
    expect(url).toContain("/api/v1/orders/super/SO-1");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.changes).toStrictEqual({ leg_name: "TARGET_LEG", price: 3650 });
  });

  it("refuses to submit a leg modify with no actual changes", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("TCS")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));
    fireEvent.click(screen.getByRole("button", { name: /apply/i }));
    // leg_name alone modifies nothing — no PUT must fire.
    expect(callsByMethod("PUT").length).toBe(0);
  });

  it("maps the 501 unsupported-broker refusal honestly", async () => {
    listStatus = 501;
    listMessage = "broker adapter 'openalgo' does not support the 'super_orders' listing";
    renderWidget();
    await waitFor(() =>
      expect(screen.getByText("Not available for this broker.")).toBeInTheDocument(),
    );
  });
});
