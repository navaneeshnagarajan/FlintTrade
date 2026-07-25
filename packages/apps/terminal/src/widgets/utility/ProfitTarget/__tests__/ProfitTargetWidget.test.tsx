import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import ProfitTargetWidget from "../ProfitTargetWidget";

/** Read the value cell of a `ResultRow` by its label. */
function resultValue(label: string): string {
  const row = screen.getByText(label).closest("div");
  return row?.querySelector("span:last-child")?.textContent?.trim() ?? "";
}

describe("ProfitTargetWidget", () => {
  it("renders widget header with title", () => {
    render(<ProfitTargetWidget />);
    expect(screen.getByText("Profit Target Calculator")).toBeTruthy();
  });

  it("renders all input fields", () => {
    render(<ProfitTargetWidget />);
    expect(screen.getByLabelText("Entry Price")).toBeTruthy();
    expect(screen.getByLabelText("Stop Loss")).toBeTruthy();
    expect(screen.getByLabelText("Target Price")).toBeTruthy();
    expect(screen.getByLabelText("Quantity (lots)")).toBeTruthy();
    expect(screen.getByLabelText("Lot Size")).toBeTruthy();
  });

  it("shows results with default values", () => {
    render(<ProfitTargetWidget />);
    expect(screen.getByText("R:R Ratio")).toBeTruthy();
    expect(screen.getByText("Risk per Trade")).toBeTruthy();
    expect(screen.getByText("Potential Profit")).toBeTruthy();
    expect(screen.getByText("Breakeven Win Rate")).toBeTruthy();
  });

  it("shows suggested qty in results", () => {
    render(<ProfitTargetWidget />);
    expect(screen.getByText("Suggested Qty (lots)")).toBeTruthy();
  });

  it("renders R:R bar with aria label", () => {
    render(<ProfitTargetWidget />);
    const bar = screen.getByLabelText(/risk reward ratio/i);
    expect(bar).toBeTruthy();
  });

  it("shows empty state when entry is cleared", () => {
    render(<ProfitTargetWidget />);
    const entryInput = screen.getByLabelText("Entry Price");
    fireEvent.change(entryInput, { target: { value: "" } });
    expect(screen.getByText(/enter entry, stop loss and target/i)).toBeTruthy();
  });

  it("renders position sizing section inputs", () => {
    render(<ProfitTargetWidget />);
    expect(screen.getByLabelText("Account Capital")).toBeTruthy();
    expect(screen.getByLabelText("Max Risk %")).toBeTruthy();
  });

  it("updates R:R ratio when inputs change", () => {
    render(<ProfitTargetWidget />);
    // Default: entry=22000, sl=21800, target=22500 → risk=200, reward=500 → 2.5:1
    const rrRow = screen.getByText("R:R Ratio");
    expect(rrRow).toBeTruthy();
    const rrValue = screen.getByText(/2.50 : 1/);
    expect(rrValue).toBeTruthy();
  });

  // ── Numeric characterisation (pins the sizing kernel) ──────────────────────
  //
  // These pin the exact arithmetic so that extracting the shared sizing kernel
  // into `lib/sizing.ts` cannot silently change a number.

  describe("risk/reward arithmetic", () => {
    it("pins every result row for the default trade", () => {
      render(<ProfitTargetWidget />);

      // entry 22000 · SL 21800 · target 22500 · 1 lot × 50 → risk 200, reward 500.
      expect(resultValue("Risk per Trade")).toBe("₹10,000");
      expect(resultValue("Potential Profit")).toBe("₹25,000");
      expect(resultValue("R:R Ratio")).toBe("2.50 : 1");
      // Breakeven win rate = 1 / (1 + 2.5) = 28.571…%
      expect(resultValue("Breakeven Win Rate")).toBe("28.6%");
      // Capital ₹5,00,000 · max risk 1% → budget ₹5,000, but one lot risks
      // ₹10,000; the max(1, …) clamp still recommends 1 lot.
      expect(resultValue("Suggested Qty (lots)")).toBe("1");
      // …and the clamp is now stated out loud instead of passing silently.
      expect(screen.getByRole("status")).toHaveTextContent(
        /single lot risks ₹10,000 — more than the ₹5,000 you allowed/i,
      );
    });

    it("pins suggested qty when the budget covers several lots", () => {
      render(<ProfitTargetWidget />);
      fireEvent.change(screen.getByLabelText("Max Risk %"), { target: { value: "4" } });

      // Budget ₹20,000 / (200 × 50 = ₹10,000 per lot) → 2 lots exactly.
      expect(resultValue("Suggested Qty (lots)")).toBe("2");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the breakeven win rate at 1:1", () => {
      render(<ProfitTargetWidget />);
      fireEvent.change(screen.getByLabelText("Target Price"), { target: { value: "22200" } });

      expect(resultValue("R:R Ratio")).toBe("1.00 : 1");
      expect(resultValue("Breakeven Win Rate")).toBe("50.0%");
    });
  });
});
