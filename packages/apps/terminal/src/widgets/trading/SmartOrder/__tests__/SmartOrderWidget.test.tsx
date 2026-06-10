/**
 * SmartOrderWidget.test — smart-route form, mode gating, live job display.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

let mockMode = "live";
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector?: (s: { mode: string }) => unknown) =>
    typeof selector === "function" ? selector({ mode: mockMode }) : { mode: mockMode },
}));
vi.mock("@/services/ftApi", () => ({
  startSmartRoute: vi.fn(),
  getSmartRouteJob: vi.fn(),
}));
vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: vi.fn(),
}));

import SmartOrderWidget from "../SmartOrderWidget";
import { startSmartRoute, getSmartRouteJob } from "@/services/ftApi";

const DONE_JOB = {
  job_id: "j1",
  created_at: "2026-06-10T00:00:00Z",
  status: "done" as const,
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
    expect(screen.getByText(/filled 10\/10/)).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
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
});
