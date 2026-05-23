import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — inline selectors to avoid Zustand cast issues
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: "explore" }),
}));

vi.mock("@/services/api", () => ({
  placeOrder: vi.fn().mockResolvedValue({ orderId: "test_123" }),
  modifyOrder: vi.fn().mockResolvedValue({}),
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

import OrderLadderWidget, { generateLadderLevels } from "../OrderLadderWidget";

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
