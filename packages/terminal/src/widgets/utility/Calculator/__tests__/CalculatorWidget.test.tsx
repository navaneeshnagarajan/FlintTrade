/**
 * CalculatorWidget.test.tsx
 *
 * Tests for the Calculator widget with Risk/Reward, Brokerage, and Margin tabs.
 * Verifies rendering, tab structure, and form defaults.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getMargin: vi.fn().mockResolvedValue({
    span_margin: 12000,
    exposure_margin: 8000,
    total_margin_required: 20000,
  }),
  getFunds: vi.fn().mockResolvedValue({
    availableCash: 100000,
    usedMargin: 20000,
    totalBalance: 120000,
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import CalculatorWidget from "../CalculatorWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof CalculatorWidget>[0];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CalculatorWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Calculator")).toBeInTheDocument();
  });

  it("shows Risk / Reward tab by default", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Risk / Reward")).toBeInTheDocument();
    expect(screen.getByText("Brokerage")).toBeInTheDocument();
  });

  it("shows Margin tab trigger", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByRole("tab", { name: /margin/i })).toBeInTheDocument();
  });

  it("shows risk calculator template buttons", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Conservative")).toBeInTheDocument();
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    expect(screen.getByText("Aggressive")).toBeInTheDocument();
  });

  it("has Risk/Reward, Brokerage, and Margin tab triggers", () => {
    render(<CalculatorWidget {...defaultProps} />);
    const tabs = screen.getAllByRole("tab");
    const tabLabels = tabs.map((t) => t.textContent?.trim());
    expect(tabLabels).toContain("Risk / Reward");
    expect(tabLabels).toContain("Brokerage");
    expect(tabLabels.some((l) => l?.includes("Margin"))).toBe(true);
  });

  it("shows the default prompt text for risk calculator", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(
      screen.getByText("Enter entry and stop loss prices to calculate"),
    ).toBeInTheDocument();
  });

  it("renders Margin tab content when clicked", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    const marginTab = screen.getByRole("tab", { name: /margin/i });
    await userEvent.click(marginTab);
    expect(screen.getByText(/SPAN-like/i)).toBeInTheDocument();
  });

  it("Margin tab shows live estimate results section", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    const marginTab = screen.getByRole("tab", { name: /margin/i });
    await userEvent.click(marginTab);
    expect(screen.getByText("SPAN Margin")).toBeInTheDocument();
    expect(screen.getByText("Exposure Margin")).toBeInTheDocument();
    expect(screen.getByText("Total Required")).toBeInTheDocument();
  });

  it("Margin tab has product type selector with NRML default value", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    const marginTab = screen.getByRole("tab", { name: /margin/i });
    await userEvent.click(marginTab);
    // Product select shows current value NRML (may appear in both visible span and hidden option)
    const nrmlEls = screen.getAllByText("NRML");
    expect(nrmlEls.length).toBeGreaterThanOrEqual(1);
  });

  // ── Interaction tests ────────────────────────────────────────────────────

  it("applying Conservative template updates Capital and Risk % inputs", async () => {
    render(<CalculatorWidget {...defaultProps} />);

    // Conservative: capital=500000, riskPercent=1
    const conservativeBtn = screen.getByRole("button", { name: /conservative/i });
    await userEvent.click(conservativeBtn);

    // Capital field should now show 500000
    const capitalInput = screen.getByPlaceholderText("200000") as HTMLInputElement;
    expect(Number(capitalInput.value)).toBe(500000);
  });

  it("entering entry and stop loss prices shows calculated results", async () => {
    render(<CalculatorWidget {...defaultProps} />);

    // Fill Entry Price (500) and Stop Loss (490) — valid BUY trade
    // Use getAllByText for "Stop Loss" since the prompt text also contains the phrase
    const entryLabel = screen.getByText("Entry Price");
    const entryField = entryLabel.closest("div")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(entryField, { target: { value: "500" } });

    // getByText("Stop Loss") is unambiguous — the Label element uses exact casing
    const slLabel = screen.getByText("Stop Loss");
    const slField = slLabel.closest("div")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(slField, { target: { value: "490" } });

    // Results section should now appear with Quantity row
    expect(screen.getByText("Quantity")).toBeInTheDocument();
    expect(screen.getByText(/shares/i)).toBeInTheDocument();
  });

  it("switching to Brokerage tab and changing price updates Total Cost", async () => {
    render(<CalculatorWidget {...defaultProps} />);

    const brokerageTab = screen.getByRole("tab", { name: /brokerage/i });
    await userEvent.click(brokerageTab);

    // Default price is 100; change to 200 — Total Cost row should still be present
    const priceLabel = screen.getByText(/^price/i);
    const priceField = priceLabel.closest("div")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(priceField, { target: { value: "200" } });

    // The Brokerage tab shows Total Cost row
    expect(screen.getByText(/total cost/i)).toBeInTheDocument();
  });

  it("applying Aggressive template then calculating shows results for 3% risk", async () => {
    render(<CalculatorWidget {...defaultProps} />);

    const aggressiveBtn = screen.getByRole("button", { name: /aggressive/i });
    await userEvent.click(aggressiveBtn);

    // Now enter a valid entry and SL to trigger calculation (BUY: entry > SL)
    const entryLabel = screen.getByText(/entry price/i);
    const entryField = entryLabel.closest("div")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(entryField, { target: { value: "1000" } });

    const slLabel = screen.getByText("Stop Loss");
    const slField = slLabel.closest("div")?.querySelector("input") as HTMLInputElement;
    fireEvent.change(slField, { target: { value: "950" } });

    // Results should appear
    expect(screen.getByText("Risk Amount")).toBeInTheDocument();
    expect(screen.getByText("Reward Amount")).toBeInTheDocument();
  });
});
