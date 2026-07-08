/**
 * SmartOrderWidget.test — smart-route form, mode gating, live job display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockMode = "live";
let mockApiKey = "";
let mockBrokerState: {
  accounts: Array<{ account_id: string; broker: string; source?: "gateway" | "native"; status: string }>;
  activeAccountId: string | null;
} = { accounts: [], activeAccountId: null };
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
}));
vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    // openAlgoHydrated: true models a normally-loaded app; the hydration
    // fail-closed window is covered by brokerTargets/api tests.
    getState: () => ({ apiKey: mockApiKey, openAlgoHydrated: true }),
  },
}));
vi.mock("@/stores/brokerStore", () => ({
  findBrokerAccountMatch: (
    accounts: Array<{ account_id: string; broker: string; source?: "gateway" | "native" }>,
    selector: string | null,
  ) => accounts.find((account) => mockBrokerAccountMatch(account, selector)),
  isBrokerAccountMatch: (
    account: { account_id: string; broker: string; source?: "gateway" | "native" },
    selector: string | null,
  ) => mockBrokerAccountMatch(account, selector),
  useBrokerStore: {
    getState: () => mockBrokerState,
  },
}));
vi.mock("@/services/ftApi", () => ({
  startSmartRoute: vi.fn(),
  getSmartRouteJob: vi.fn(),
  cancelSmartRoute: vi.fn(),
  listSmartRouteJobs: vi.fn(),
}));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: vi.fn(),
}));

import SmartOrderWidget, { parseQuantity, parseSlippageBps } from "../SmartOrderWidget";
import {
  startSmartRoute,
  getSmartRouteJob,
  cancelSmartRoute,
  listSmartRouteJobs,
} from "@/services/ftApi";

function mockBrokerAccountMatch(
  account: { account_id: string; broker: string; source?: "gateway" | "native" },
  selector: string | null,
) {
  if (!selector) return false;
  const key = [account.source ?? "gateway", account.broker, account.account_id]
    .map(encodeURIComponent)
    .join(":");
  return selector === key || selector === account.account_id;
}

const DONE_JOB = {
  job_id: "j1",
  created_at: "2026-06-10T00:00:00Z",
  status: "done" as const,
  cancel_requested: false,
  error: "",
  symbol: "RELIANCE",
  exchange: "NSE",
  action: "BUY",
  urgency: "high",
  total_quantity: 10,
  filled_quantity: 10,
  average_slippage_bps: 1.2,
  completed: true,
  child_orders: [
    {
      quantity: 10,
      price_type: "MARKET",
      status: "placed" as const,
      order_id: "OID-1",
      error: "",
      slippage_bps: 1.2,
      placed_at: "2026-06-10T00:00:01Z",
    },
  ],
};

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SmartOrderWidget />
    </QueryClientProvider>,
  );
}

describe("SmartOrderWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMode = "live";
    mockApiKey = "";
    mockBrokerState = { accounts: [], activeAccountId: null };
    vi.mocked(listSmartRouteJobs).mockResolvedValue([]);
  });

  it("adopts a still-running route on mount (widget reopened mid-TWAP)", async () => {
    const running = { ...DONE_JOB, job_id: "j9", status: "running" as const, completed: false };
    vi.mocked(listSmartRouteJobs).mockResolvedValue([running]);
    vi.mocked(getSmartRouteJob).mockResolvedValue(running);
    renderWidget();

    await waitFor(() => expect(screen.getByText("Routing…")).toBeInTheDocument());
    expect(getSmartRouteJob).toHaveBeenCalledWith("j9");
  });

  it("renders the header", () => {
    renderWidget();
    expect(screen.getByText("Smart Order")).toBeInTheDocument();
  });

  it("gates submission outside live mode with an honest hint", () => {
    mockMode = "practice";
    renderWidget();

    expect(screen.getByText(/serves live mode only/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Smart order symbol"), {
      target: { value: "RELIANCE" },
    });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), {
      target: { value: "10" },
    });
    expect(screen.getByRole("button", { name: /route order/i })).toBeDisabled();
  });

  it("starts a smart route and renders the gated child orders", async () => {
    vi.mocked(startSmartRoute).mockResolvedValue({ ...DONE_JOB, status: "running" });
    vi.mocked(getSmartRouteJob).mockResolvedValue(DONE_JOB);
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), {
      target: { value: "reliance" },
    });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    // mutationFn receives (variables, context) in TanStack v5 — assert the
    // variables payload only.
    await waitFor(() => expect(startSmartRoute).toHaveBeenCalledOnce());
    expect(vi.mocked(startSmartRoute).mock.calls[0][0]).toEqual({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 10,
      urgency: "medium",
      max_slippage_bps: 20,
    });

    // The poll resolves to the completed job — children render as real rows.
    await waitFor(() => expect(screen.getByText("OID-1")).toBeInTheDocument());
    expect(screen.getByText("placed")).toBeInTheDocument();
    // "accepted", not "filled" — order ids returned ≠ confirmed fills.
    expect(screen.getByText(/accepted 10\/10/)).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
  });

  it("routes through the active native account when no OpenAlgo key is configured", async () => {
    mockBrokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    vi.mocked(startSmartRoute).mockResolvedValue({ ...DONE_JOB, status: "running" });
    vi.mocked(getSmartRouteJob).mockResolvedValue(DONE_JOB);
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), {
      target: { value: "reliance" },
    });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    await waitFor(() => expect(startSmartRoute).toHaveBeenCalledOnce());
    expect(vi.mocked(startSmartRoute).mock.calls[0][0]).toMatchObject({
      symbol: "RELIANCE",
      broker: "upstox",
      account_id: "U1",
    });
  });

  it("keeps OpenAlgo primary when an OpenAlgo key is configured", async () => {
    mockApiKey = "openalgo-key";
    mockBrokerState = {
      accounts: [
        { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
      ],
      activeAccountId: "native:upstox:U1",
    };
    vi.mocked(startSmartRoute).mockResolvedValue({ ...DONE_JOB, status: "running" });
    vi.mocked(getSmartRouteJob).mockResolvedValue(DONE_JOB);
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), {
      target: { value: "reliance" },
    });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    await waitFor(() => expect(startSmartRoute).toHaveBeenCalledOnce());
    expect(vi.mocked(startSmartRoute).mock.calls[0][0]).not.toHaveProperty("broker");
    expect(vi.mocked(startSmartRoute).mock.calls[0][0]).not.toHaveProperty("account_id");
  });

  it("surfaces the backend's refusal message verbatim", async () => {
    vi.mocked(startSmartRoute).mockRejectedValue(
      new Error(
        "Smart routing is disabled. Enable it via workspace.json brokers.smart_routing.enabled and restart the backend.",
      ),
    );
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), {
      target: { value: "RELIANCE" },
    });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    await waitFor(() =>
      expect(screen.getByText(/smart routing is disabled/i)).toBeInTheDocument(),
    );
  });

  it("toggles BUY/SELL side", () => {
    renderWidget();
    const sell = screen.getByRole("button", { name: "SELL" });
    fireEvent.click(sell);
    expect(sell).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "BUY" })).toHaveAttribute("aria-pressed", "false");
  });

  it("offers a Cancel control while running and calls the cancel endpoint", async () => {
    const running = { ...DONE_JOB, status: "running" as const, completed: false };
    vi.mocked(startSmartRoute).mockResolvedValue(running);
    vi.mocked(getSmartRouteJob).mockResolvedValue(running);
    vi.mocked(cancelSmartRoute).mockResolvedValue({ ...running, cancel_requested: true });
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), { target: { value: "RELIANCE" } });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    const cancel = await screen.findByRole("button", { name: /cancel/i });
    fireEvent.click(cancel);
    await waitFor(() => expect(cancelSmartRoute).toHaveBeenCalledOnce());
    expect(vi.mocked(cancelSmartRoute).mock.calls[0][0]).toBe("j1");
  });

  it("stops pretending to route when the job poll fails (lost job)", async () => {
    vi.mocked(startSmartRoute).mockResolvedValue({ ...DONE_JOB, status: "running", completed: false });
    vi.mocked(getSmartRouteJob).mockRejectedValue(new Error("Unknown smart-route job j1"));
    renderWidget();

    fireEvent.change(screen.getByLabelText("Smart order symbol"), { target: { value: "RELIANCE" } });
    fireEvent.change(screen.getByLabelText("Smart order quantity"), { target: { value: "10" } });
    fireEvent.click(screen.getByRole("button", { name: /route order/i }));

    await waitFor(() =>
      expect(screen.getByText(/no longer tracked/i)).toBeInTheDocument(),
    );
  });
});

describe("strict numeric parsers", () => {
  it("keeps an explicit 0-bps budget as 0 (not the 20 default)", () => {
    expect(parseSlippageBps("0")).toBe(0);
    expect(parseSlippageBps("20")).toBe(20);
    expect(parseSlippageBps("abc")).toBeNull();
    expect(parseSlippageBps("")).toBeNull();
  });

  it("handles thousands separators and rejects garbage quantities", () => {
    expect(parseQuantity("1,000")).toBe(1000);
    expect(parseQuantity("10")).toBe(10);
    expect(parseQuantity("0")).toBeNull();
    expect(parseQuantity("1.5")).toBeNull();
    expect(parseQuantity("ten")).toBeNull();
  });
});
