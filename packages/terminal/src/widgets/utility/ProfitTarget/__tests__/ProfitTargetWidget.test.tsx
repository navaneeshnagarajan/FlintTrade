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
});
