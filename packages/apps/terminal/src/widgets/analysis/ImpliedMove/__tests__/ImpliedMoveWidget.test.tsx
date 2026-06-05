import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import ImpliedMoveWidget, {
  SAMPLE_IMPLIED_MOVE,
  SAMPLE_SYMBOLS,
} from "../ImpliedMoveWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("ImpliedMoveWidget", () => {
  it("renders widget title", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByText("Implied Move")).toBeTruthy();
  });

  it("shows the Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("keeps the Sample data badge visible even when connected (no live endpoint yet)", () => {
    // The widget renders sample figures only — there is no live implied-move
    // backend endpoint. The badge MUST stay visible when a broker is connected
    // so live users are never misled into thinking the figures are real.
    mockConnected.mockReturnValue(true);
    render(<ImpliedMoveWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("the Sample data badge discloses that no live data source is wired", () => {
    mockConnected.mockReturnValue(true);
    render(<ImpliedMoveWidget />);
    const badge = screen.getByLabelText(
      "Showing sample data; no live implied-move endpoint yet",
    );
    expect(badge.textContent).toBe("Sample data");
  });

  it("renders range bar with aria label", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByLabelText("Implied move range bar")).toBeTruthy();
  });

  it("renders probability zones table", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByLabelText("Probability zones table")).toBeTruthy();
    expect(screen.getByText("68%")).toBeTruthy();
    expect(screen.getByText("95%")).toBeTruthy();
  });

  it("renders ATM straddle premiums section", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByText("ATM CE Premium")).toBeTruthy();
    expect(screen.getByText("ATM PE Premium")).toBeTruthy();
    expect(screen.getByText("Total (Implied Move)")).toBeTruthy();
  });

  it("renders symbol select with NIFTY as default", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    const trigger = screen.getByLabelText("Select symbol");
    expect(trigger.textContent).toContain("NIFTY");
  });

  it("renders refresh button", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByLabelText("Refresh implied move")).toBeTruthy();
  });

  it("renders expected range section heading", () => {
    mockConnected.mockReturnValue(false);
    render(<ImpliedMoveWidget />);
    expect(screen.getByText("Expected Range")).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// Sample data tests
// ---------------------------------------------------------------------------

describe("SAMPLE_IMPLIED_MOVE", () => {
  it("implied move equals CE + PE premium", () => {
    const { cePremium, pePremium, impliedMove } = SAMPLE_IMPLIED_MOVE;
    expect(impliedMove).toBeCloseTo(cePremium + pePremium, 1);
  });

  it("upper bound equals spot + implied move", () => {
    const { spot, impliedMove, upperBound } = SAMPLE_IMPLIED_MOVE;
    expect(upperBound).toBeCloseTo(spot + impliedMove, 1);
  });

  it("lower bound equals spot - implied move", () => {
    const { spot, impliedMove, lowerBound } = SAMPLE_IMPLIED_MOVE;
    expect(lowerBound).toBeCloseTo(spot - impliedMove, 1);
  });

  it("2 sigma bounds are twice as wide as 1 sigma bounds", () => {
    const { spot, impliedMove, upper2Sigma, lower2Sigma } = SAMPLE_IMPLIED_MOVE;
    expect(upper2Sigma).toBeCloseTo(spot + impliedMove * 2, 1);
    expect(lower2Sigma).toBeCloseTo(spot - impliedMove * 2, 1);
  });

  it("implied move pct is non-zero and reasonable", () => {
    expect(SAMPLE_IMPLIED_MOVE.impliedMovePct).toBeGreaterThan(0);
    expect(SAMPLE_IMPLIED_MOVE.impliedMovePct).toBeLessThan(10);
  });

  it("all sample symbols have valid data", () => {
    for (const d of SAMPLE_SYMBOLS) {
      expect(d.spot).toBeGreaterThan(0);
      expect(d.impliedMove).toBeGreaterThan(0);
      expect(d.symbol.length).toBeGreaterThan(0);
    }
  });
});
