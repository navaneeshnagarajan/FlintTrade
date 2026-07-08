/**
 * ConditionalTriggersWidget.test — live-mode gating, condition-builder wire
 * shape (Dhan v2 field names), listing with condition summaries, modify
 * (full replacement) and cancel, plus the 501 mapping.
 *
 * The global fetch is stubbed so the REAL brokerOrdersApi client runs.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useConnectionStore } from "@/stores/connectionStore";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockMode = "live";
vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(
    (selector?: (s: { mode: string }) => unknown) =>
      typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
    { getState: () => ({ mode: mockMode }) },
  ),
}));

import ConditionalTriggersWidget from "./ConditionalTriggersWidget";

const LIST_ROW = {
  alertId: "AL-1",
  alertStatus: "ACTIVE",
  lastPrice: "245.50",
  createdTime: "2026-06-10T09:15:00Z",
  condition: {
    comparisonType: "PRICE_WITH_VALUE",
    exchangeSegment: "NSE_EQ",
    securityId: "12345",
    operator: "GREATER_THAN",
    comparingValue: 250,
    frequency: "ONCE",
  },
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
  return Promise.resolve(
    jsonResponse({ status: "success", data: { alertId: "AL-1", alertStatus: "ACTIVE" } }),
  );
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
      <ConditionalTriggersWidget />
    </QueryClientProvider>,
  );
}

function fillMinimalForm() {
  fireEvent.change(screen.getByLabelText("Security ID"), { target: { value: "12345" } });
  fireEvent.change(screen.getByLabelText("Comparing value"), { target: { value: "250" } });
  fireEvent.change(screen.getByLabelText("Trigger order symbol"), {
    target: { value: "reliance" },
  });
  fireEvent.change(screen.getByLabelText("Trigger order quantity"), { target: { value: "10" } });
  fireEvent.change(screen.getByLabelText("Trigger order price"), { target: { value: "250.50" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockMode = "live";
  useConnectionStore.setState({ openAlgoHydrated: true });
  listRows = [LIST_ROW];
  listStatus = 200;
  listMessage = "";
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConditionalTriggersWidget", () => {
  it("renders the header", () => {
    renderWidget();
    expect(screen.getByText("Conditional Triggers")).toBeInTheDocument();
  });

  it("outside Live mode: honest notice, no fetch, submit disabled", () => {
    mockMode = "practice";
    renderWidget();
    expect(screen.getByText(/live-broker constructs/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /place trigger/i })).toBeDisabled();
  });

  it("lists triggers with a readable condition summary", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("AL-1")).toBeInTheDocument());
    expect(screen.getByText("PRICE GREATER_THAN 250")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
    const [url] = callsByMethod("GET")[0];
    expect(url).toContain("/api/v1/orders/triggers");
  });

  it("places a price-vs-value trigger with Dhan condition fields + typed order leg", async () => {
    renderWidget();
    fillMinimalForm();
    fireEvent.click(screen.getByRole("button", { name: /place trigger/i }));

    await waitFor(() => expect(callsByMethod("POST").length).toBe(1));
    const [url, init] = callsByMethod("POST")[0];
    expect(url).toContain("/api/v1/orders/triggers");
    const body = JSON.parse(init.body as string) as {
      condition: Record<string, unknown>;
      orders: Record<string, unknown>[];
    };
    expect(body.condition.comparisonType).toBe("PRICE_WITH_VALUE");
    expect(body.condition.exchangeSegment).toBe("NSE_EQ");
    expect(body.condition.securityId).toBe("12345");
    expect(body.condition.operator).toBe("CROSSING_UP");
    expect(body.condition.comparingValue).toBe(250);
    expect(body.condition.frequency).toBe("ONCE");
    // Price-vs-value conditions carry no indicator fields.
    expect(body.condition.indicatorName).toBeUndefined();
    expect(body.orders).toHaveLength(1);
    expect(body.orders[0].symbol).toBe("RELIANCE");
    expect(body.orders[0].action).toBe("BUY");
    expect(body.orders[0].quantity).toBe(10);
    expect(body.orders[0].price).toBe(250.5);
    expect(body.orders[0].pricetype).toBe("LIMIT");
    await waitFor(() =>
      expect(screen.getByText(/conditional trigger placed/i)).toBeInTheDocument(),
    );
  });

  it("modify hydrates the condition from the row and PUTs a full replacement", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("AL-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /modify/i }));

    // Hydrated from the adapter row.
    expect(screen.getByLabelText("Security ID")).toHaveValue("12345");
    expect(screen.getByLabelText("Comparing value")).toHaveValue("250");
    expect(screen.getByText(/modifying #AL-1/i)).toBeInTheDocument();

    // The order leg is a full replacement — the operator must re-enter it.
    fireEvent.change(screen.getByLabelText("Trigger order symbol"), { target: { value: "TCS" } });
    fireEvent.change(screen.getByLabelText("Trigger order quantity"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Trigger order price"), { target: { value: "260" } });
    fireEvent.click(screen.getByRole("button", { name: /apply changes/i }));

    await waitFor(() => expect(callsByMethod("PUT").length).toBe(1));
    const [url, init] = callsByMethod("PUT")[0];
    expect(url).toContain("/api/v1/orders/triggers/AL-1");
    const body = JSON.parse(init.body as string) as {
      condition: Record<string, unknown>;
      orders: Record<string, unknown>[];
    };
    expect(body.condition.securityId).toBe("12345");
    expect(body.orders[0].symbol).toBe("TCS");
  });

  it("cancels a trigger via the gated DELETE", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("AL-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /^cancel$/i }));

    await waitFor(() => expect(callsByMethod("DELETE").length).toBe(1));
    const [url] = callsByMethod("DELETE")[0];
    expect(url).toContain("/api/v1/orders/triggers/AL-1");
  });

  it("maps the 501 unsupported-broker refusal honestly", async () => {
    listStatus = 501;
    listMessage = "broker adapter 'openalgo' does not support the 'conditional_triggers' listing";
    renderWidget();
    await waitFor(() =>
      expect(screen.getByText("Not available for this broker.")).toBeInTheDocument(),
    );
  });
});
