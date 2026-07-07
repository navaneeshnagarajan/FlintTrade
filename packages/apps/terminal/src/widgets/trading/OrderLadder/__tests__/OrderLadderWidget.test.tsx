import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — inline selectors to avoid Zustand cast issues
// ---------------------------------------------------------------------------

const mockMode = vi.hoisted(() => ({ value: "explore" }));
const mockWsTicks = vi.hoisted(() => ({ value: {} as Record<string, { ltp: number }> }));
const mockPlaceOrder = vi.hoisted(() => vi.fn());
const mockCancelOrder = vi.hoisted(() => vi.fn());

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode.value }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  default: () => ({ ticks: mockWsTicks.value, connected: true }),
}));

vi.mock("@/services/api", () => ({
  placeOrder: mockPlaceOrder,
  cancelOrder: mockCancelOrder,
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mockMode.value = "explore";
  mockWsTicks.value = {};
  mockPlaceOrder.mockResolvedValue({ orderId: "test_123" });
  mockCancelOrder.mockResolvedValue(undefined);
});

import OrderLadderWidget, { generateLadderLevels, extractBrokerOrderId } from "../OrderLadderWidget";

// ---------------------------------------------------------------------------
// generateLadderLevels unit tests
// ---------------------------------------------------------------------------

describe("generateLadderLevels", () => {
  it("generates 41 levels (20 above + centre + 20 below)", () => {
    const levels = generateLadderLevels(22000, 0.25);
    expect(levels).toHaveLength(41);
  });

  it("first level is 20 ticks above centre", () => {
    const levels = generateLadderLevels(22000, 1);
    expect(levels[0].price).toBeCloseTo(22020, 1);
  });

  it("last level is 20 ticks below centre", () => {
    const levels = generateLadderLevels(22000, 1);
    expect(levels[40].price).toBeCloseTo(21980, 1);
  });

  it("centre level (index 20) equals centre price", () => {
    const levels = generateLadderLevels(22150, 0.5);
    expect(levels[20].price).toBeCloseTo(22150, 2);
  });

  it("all prices are finite numbers", () => {
    const levels = generateLadderLevels(100, 0.05);
    for (const l of levels) {
      expect(isFinite(l.price)).toBe(true);
    }
  });
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("OrderLadderWidget", () => {
  it("renders widget title", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Order Ladder")).toBeTruthy();
  });

  it("renders default symbol NIFTY", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("NIFTY")).toBeTruthy();
  });

  it("renders default exchange NSE", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("NSE")).toBeTruthy();
  });

  it("renders Bid and Ask column headers", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Bid")).toBeTruthy();
    expect(screen.getByText("Ask")).toBeTruthy();
    expect(screen.getByText("Price")).toBeTruthy();
  });

  it("renders quantity input", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByLabelText("Order quantity")).toBeTruthy();
  });

  it("renders tick size selector group", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByRole("group", { name: "Tick size" })).toBeTruthy();
  });

  it("price ladder aria-label is present", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByLabelText("Price ladder")).toBeTruthy();
  });

  it("clicking bid in explore mode shows connect message", async () => {
    render(<OrderLadderWidget />);
    // Find first sell button on the ladder
    const sellBtns = screen.getAllByRole("button").filter((b) =>
      b.getAttribute("title")?.startsWith("SELL")
    );
    if (sellBtns.length > 0) {
      fireEvent.click(sellBtns[0]);
      const status = await screen.findByRole("status");
      expect(status.textContent).toContain("broker");
    }
  });

  it("custom symbol rendered in header", () => {
    render(<OrderLadderWidget symbol="BANKNIFTY" exchange="NSE_FO" />);
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("NSE_FO")).toBeTruthy();
  });

  it("Qty label is present in controls", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Qty")).toBeTruthy();
  });

  it("Tick label is present in controls", () => {
    render(<OrderLadderWidget />);
    expect(screen.getByText("Tick")).toBeTruthy();
  });

  it("changing qty input updates the value", () => {
    render(<OrderLadderWidget />);
    const input = screen.getByLabelText("Order quantity") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "50" } });
    expect(input.value).toBe("50");
  });
});

// ---------------------------------------------------------------------------
// extractBrokerOrderId unit tests
// ---------------------------------------------------------------------------

describe("extractBrokerOrderId", () => {
  it("reads orderId / orderid / order_id aliases", () => {
    expect(extractBrokerOrderId({ orderId: "A1" })).toBe("A1");
    expect(extractBrokerOrderId({ orderid: "B2" })).toBe("B2");
    expect(extractBrokerOrderId({ order_id: "C3" })).toBe("C3");
  });

  it("accepts a bare string or numeric id", () => {
    expect(extractBrokerOrderId("XYZ")).toBe("XYZ");
    expect(extractBrokerOrderId({ orderId: 12345 })).toBe("12345");
  });

  it("returns null for anything else — the caller must fail closed", () => {
    expect(extractBrokerOrderId(undefined)).toBeNull();
    expect(extractBrokerOrderId(null)).toBeNull();
    expect(extractBrokerOrderId({})).toBeNull();
    expect(extractBrokerOrderId({ orderId: "" })).toBeNull();
    expect(extractBrokerOrderId("")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Live-mode order placement + cancel with the REAL broker order id
// ---------------------------------------------------------------------------

describe("OrderLadderWidget live cancel", () => {
  function renderLiveLadder(): void {
    mockMode.value = "live";
    mockWsTicks.value = { "NSE:NIFTY": { ltp: 100 } };
    render(<OrderLadderWidget />);
  }

  async function placeBuyAtTopLevel(): Promise<void> {
    // Top ask level = 100 + 20 × 0.25 = 105.00
    const askBtn = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("title")?.startsWith("BUY"));
    expect(askBtn).toBeTruthy();
    fireEvent.click(askBtn as HTMLElement);
    await waitFor(() => expect(mockPlaceOrder).toHaveBeenCalledTimes(1));
  }

  it("cancels a ladder order with the REAL broker order id from placeOrder", async () => {
    mockPlaceOrder.mockResolvedValue({ orderId: "BRK-98765" });
    renderLiveLadder();

    await placeBuyAtTopLevel();

    // The cancel affordance unlocks only once the broker id is stored
    await waitFor(() => {
      expect(
        (screen.getByLabelText(/^Cancel buy order at/) as HTMLButtonElement).disabled,
      ).toBe(false);
    });
    fireEvent.click(screen.getByLabelText(/^Cancel buy order at/));

    await waitFor(() => {
      expect(mockCancelOrder).toHaveBeenCalledTimes(1);
      expect(mockCancelOrder).toHaveBeenCalledWith("BRK-98765", "orderladder");
    });
    // Never the fabricated local id
    expect(mockCancelOrder).not.toHaveBeenCalledWith(
      expect.stringMatching(/^lo_/),
      expect.anything(),
    );
  });

  it("disables cancel (fail closed) when the broker id is not in the response", async () => {
    mockPlaceOrder.mockResolvedValue({ status: "success" });
    renderLiveLadder();

    await placeBuyAtTopLevel();

    // Placement resolved (status message shown) but no broker id was returned
    await screen.findByText(/order id unconfirmed/);
    const cancelBtn = screen.getByLabelText(/^Cancel buy order at/) as HTMLButtonElement;
    expect(cancelBtn.disabled).toBe(true);
    fireEvent.click(cancelBtn);
    expect(mockCancelOrder).not.toHaveBeenCalled();
  });

  it("removes the pending row when placeOrder rejects", async () => {
    mockPlaceOrder.mockRejectedValue(new Error("Order blocked in live mode."));
    renderLiveLadder();

    await placeBuyAtTopLevel();

    await waitFor(() => {
      expect(screen.queryByLabelText(/^Cancel buy order at/)).toBeNull();
    });
  });
});
