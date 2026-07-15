import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import SpreadViewWidget, {
  analyseSpread,
  type PayoffPoint,
  type SpreadAnalysis,
  type SpreadInputs,
  type SpreadMetrics,
  type SpreadType,
} from "../SpreadViewWidget";

function expectValid(
  result: SpreadAnalysis,
): asserts result is Extract<SpreadAnalysis, { valid: true }> {
  expect(result.valid).toBe(true);
  if (!result.valid) {
    throw new Error(result.error);
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("SpreadViewWidget", () => {
  it("renders widget title", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Spread View")).toBeTruthy();
  });

  it("labels the manually entered and default values as illustrative", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Illustrative inputs")).toBeTruthy();
  });

  it("renders spread type selector defaulting to Bull Call", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Bull Call")).toBeTruthy();
  });

  it("renders all metric tiles", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("Max Profit")).toBeTruthy();
    expect(screen.getByText("Max Loss")).toBeTruthy();
    expect(screen.getByText("Breakeven")).toBeTruthy();
    // "Net Premium" appears in both the input label and the metric tile span
    expect(screen.getAllByText("Net Premium").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Illustrative margin proxy")).toBeTruthy();
    expect(screen.getByText("Heuristic only; not broker margin.")).toBeTruthy();
    expect(screen.queryByText("Margin Req.")).toBeNull();
  });

  it("does not show an expiry selector before option-chain data is wired", () => {
    render(<SpreadViewWidget />);
    expect(screen.queryByLabelText("Select expiry")).toBeNull();
    expect(screen.queryByText("Expiry")).toBeNull();
  });

  it("renders payoff diagram SVG", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByRole("img", { name: /spread payoff diagram/i })).toBeTruthy();
  });

  it("renders payoff through the shared Flint payoff chart primitive", () => {
    render(<SpreadViewWidget />);
    const chart = screen.getByRole("img", { name: /spread payoff diagram/i });
    expect(chart).toHaveAttribute("data-flint-chart", "payoff");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='profit']")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='loss']")).toBeInTheDocument();
  });

  it("renders execute button disabled when disconnected", () => {
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText(/Execute.*spread/i);
    expect(btn).toBeDefined();
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("states that the builder is not wired to gated basket execution", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByText("This builder is not wired to gated basket execution")).toBeTruthy();
  });

  it("keeps execution disabled until this builder is wired", () => {
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText(/Execute.*spread unavailable/i);
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders number inputs for strikes and premium", () => {
    render(<SpreadViewWidget />);
    expect(screen.getByLabelText("Long Strike")).toBeTruthy();
    expect(screen.getByLabelText("Short Strike")).toBeTruthy();
    expect(screen.getByLabelText("Net Premium")).toBeTruthy();
  });

  it.each([
    { label: "Bull Put", longStrike: 23600, shortStrike: 23800 },
    { label: "Bear Call", longStrike: 24200, shortStrike: 24000 },
  ])("uses semantically correct $label leg defaults", ({ label, longStrike, shortStrike }) => {
    render(<SpreadViewWidget />);
    fireEvent.click(screen.getByLabelText("Select spread type"));
    fireEvent.click(screen.getByRole("option", { name: label }));

    expect(screen.getByLabelText("Long Strike")).toHaveValue(longStrike);
    expect(screen.getByLabelText("Short Strike")).toHaveValue(shortStrike);
  });

  it("suppresses metrics and payoff when inputs are invalid", () => {
    render(<SpreadViewWidget />);
    fireEvent.change(screen.getByLabelText("Long Strike"), { target: { value: "24300" } });

    expect(screen.getByRole("alert")).toHaveTextContent(/invalid inputs/i);
    expect(screen.queryByText("Max Profit")).toBeNull();
    expect(screen.queryByRole("img", { name: /spread payoff diagram/i })).toBeNull();
  });

  it("opens spread type dropdown and shows all 4 types", () => {
    render(<SpreadViewWidget />);
    const btn = screen.getByLabelText("Select spread type");
    fireEvent.click(btn);
    expect(screen.getByRole("option", { name: "Bear Put" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Bull Put" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Bear Call" })).toBeTruthy();
  });
});

describe("analyseSpread", () => {
  const validCases: Array<{
    type: SpreadType;
    inputs: SpreadInputs;
    metrics: Pick<SpreadMetrics, "maxProfit" | "maxLoss" | "breakeven">;
    first: PayoffPoint;
    last: PayoffPoint;
  }> = [
    {
      type: "bull-call",
      inputs: { longStrike: 24000, shortStrike: 24200, premium: 45, lotSize: 25 },
      metrics: { maxProfit: 3875, maxLoss: 1125, breakeven: 24045 },
      first: { price: 23900, pnl: -1125 },
      last: { price: 24300, pnl: 3875 },
    },
    {
      type: "bear-put",
      inputs: { longStrike: 24000, shortStrike: 23800, premium: 50, lotSize: 25 },
      metrics: { maxProfit: 3750, maxLoss: 1250, breakeven: 23950 },
      first: { price: 23700, pnl: 3750 },
      last: { price: 24100, pnl: -1250 },
    },
    {
      type: "bull-put",
      inputs: { longStrike: 23800, shortStrike: 24000, premium: -30, lotSize: 25 },
      metrics: { maxProfit: 750, maxLoss: 4250, breakeven: 23970 },
      first: { price: 23700, pnl: -4250 },
      last: { price: 24100, pnl: 750 },
    },
    {
      type: "bear-call",
      inputs: { longStrike: 24200, shortStrike: 24000, premium: -35, lotSize: 25 },
      metrics: { maxProfit: 875, maxLoss: 4125, breakeven: 24035 },
      first: { price: 23900, pnl: 875 },
      last: { price: 24300, pnl: -4125 },
    },
  ];

  it.each(validCases)(
    "computes max profit, max loss, and breakeven for $type",
    ({ type, inputs, metrics }) => {
      const result = analyseSpread(type, inputs);
      expectValid(result);
      expect(result.metrics).toMatchObject(metrics);
    },
  );

  it.each(validCases)(
    "builds $type payoff endpoints from the explicit long and short legs",
    ({ type, inputs, first, last }) => {
      const result = analyseSpread(type, inputs);
      expectValid(result);
      expect(result.payoff[0]).toEqual(first);
      expect(result.payoff.at(-1)).toEqual(last);
    },
  );

  it.each([
    { name: "zero long strike", inputs: { longStrike: 0, shortStrike: 24200, premium: 45, lotSize: 25 } },
    { name: "negative short strike", inputs: { longStrike: 24000, shortStrike: -1, premium: 45, lotSize: 25 } },
    { name: "non-finite long strike", inputs: { longStrike: Number.POSITIVE_INFINITY, shortStrike: 24200, premium: 45, lotSize: 25 } },
    { name: "non-finite short strike", inputs: { longStrike: 24000, shortStrike: Number.NaN, premium: 45, lotSize: 25 } },
  ])("rejects $name", ({ inputs }) => {
    expect(analyseSpread("bull-call", inputs).valid).toBe(false);
  });

  it.each([
    { name: "zero", lotSize: 0 },
    { name: "negative", lotSize: -1 },
    { name: "fractional", lotSize: 1.5 },
    { name: "non-finite", lotSize: Number.POSITIVE_INFINITY },
  ])("rejects a $name lot size", ({ lotSize }) => {
    const result = analyseSpread("bull-call", {
      longStrike: 24000,
      shortStrike: 24200,
      premium: 45,
      lotSize,
    });
    expect(result.valid).toBe(false);
  });

  it.each([
    { type: "bull-call" as const, longStrike: 24200, shortStrike: 24000 },
    { type: "bear-put" as const, longStrike: 23800, shortStrike: 24000 },
    { type: "bull-put" as const, longStrike: 24000, shortStrike: 23800 },
    { type: "bear-call" as const, longStrike: 24000, shortStrike: 24200 },
  ])("rejects incorrectly ordered $type legs", ({ type, longStrike, shortStrike }) => {
    const premium = type === "bull-call" || type === "bear-put" ? 40 : -40;
    expect(analyseSpread(type, { longStrike, shortStrike, premium, lotSize: 25 }).valid).toBe(false);
  });

  it.each([
    { name: "zero debit", type: "bull-call" as const, premium: 0 },
    { name: "negative debit", type: "bear-put" as const, premium: -1 },
    { name: "debit above spread width", type: "bull-call" as const, premium: 201 },
    { name: "zero credit", type: "bull-put" as const, premium: 0 },
    { name: "positive credit", type: "bear-call" as const, premium: 1 },
    { name: "credit above spread width", type: "bull-put" as const, premium: -201 },
    { name: "non-finite premium", type: "bear-call" as const, premium: Number.NaN },
  ])("rejects $name", ({ type, premium }) => {
    const isLongLower = type === "bull-call" || type === "bull-put";
    const inputs = isLongLower
      ? { longStrike: 24000, shortStrike: 24200, premium, lotSize: 25 }
      : { longStrike: 24200, shortStrike: 24000, premium, lotSize: 25 };
    expect(analyseSpread(type, inputs).valid).toBe(false);
  });
});
