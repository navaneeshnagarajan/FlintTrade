/**
 * StrategyBuilderTool.test.tsx
 *
 * Tests for the Strategy Builder canvas tool.
 * Verifies rendering, heading, tabs, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../usePineRunner", () => ({
  usePineRunner: () => ({
    code: "",
    output: "",
    isRunning: false,
    error: null,
    run: vi.fn(),
    reset: vi.fn(),
    setCode: vi.fn(),
    setOptions: vi.fn(),
    options: {},
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import StrategyBuilderTool from "../StrategyBuilderTool";
import {
  LOAD_TEMPLATE_EVENT,
  PENDING_TEMPLATE_KEY,
  type BuilderTemplate,
} from "../templateBridge";
import { act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StrategyBuilderTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("renders without crashing", () => {
    const { container } = render(<StrategyBuilderTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Strategy Builder heading", () => {
    render(<StrategyBuilderTool />);
    expect(screen.getByText("Strategy Builder")).toBeInTheDocument();
  });

  it("has Strategy Legs, Payoff, Margin, and Pine Script tabs", () => {
    render(<StrategyBuilderTool />);
    expect(screen.getByText("Strategy Legs")).toBeInTheDocument();
    expect(screen.getByText("Payoff")).toBeInTheDocument();
    expect(screen.getByText("Margin")).toBeInTheDocument();
    expect(screen.getByText("Pine Script")).toBeInTheDocument();
  });

  it("applies a stashed template on mount with real strikes", () => {
    // Iron condor handed off by the StrategyTemplates widget. Default
    // underlying is NIFTY (ATM 22500, gap 50) → -2/-1/+1/+2 offsets become
    // 22400 / 22450 / 22550 / 22600.
    const tmpl: BuilderTemplate = {
      id: "iron-condor",
      name: "Iron Condor",
      legs: [
        { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 },
        { action: "BUY", optionType: "CE", strikeOffset: 2, lots: 1 },
        { action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 },
        { action: "BUY", optionType: "PE", strikeOffset: -2, lots: 1 },
      ],
    };
    sessionStorage.setItem(PENDING_TEMPLATE_KEY, JSON.stringify(tmpl));

    render(<StrategyBuilderTool />);

    for (const strike of ["22550", "22600", "22450", "22400"]) {
      expect(screen.getByDisplayValue(strike)).toBeInTheDocument();
    }
    // The stash is one-shot — consumed on mount.
    expect(sessionStorage.getItem(PENDING_TEMPLATE_KEY)).toBeNull();
  });

  it("offers long and short volatility templates as separate pills", async () => {
    // The pill bar reads the shared catalogue (lib/strategyTemplates). Before
    // the merge this builder had a single "Straddle" pill meaning BUY-both,
    // while the OptionChain LegBuilder's identically-keyed pill sold both.
    render(<StrategyBuilderTool />);

    const longBtn = screen.getByRole("button", { name: "Long Straddle" });
    const shortBtn = screen.getByRole("button", { name: "Short Straddle" });
    expect(screen.queryByRole("button", { name: "Straddle" })).not.toBeInTheDocument();

    await userEvent.click(longBtn);
    expect(screen.getAllByText("BUY")).toHaveLength(2);

    await userEvent.click(shortBtn);
    expect(screen.getAllByText("SELL")).toHaveLength(2);
  });

  it("applies a live load-template event while mounted", () => {
    render(<StrategyBuilderTool />);

    const tmpl: BuilderTemplate = {
      id: "bull-call-spread",
      name: "Bull Call Spread",
      legs: [
        { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
        { action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 },
      ],
    };
    act(() => {
      window.dispatchEvent(new CustomEvent(LOAD_TEMPLATE_EVENT, { detail: tmpl }));
    });

    // 22500 matches both the ATM config input and the new ATM leg strike.
    expect(screen.getAllByDisplayValue("22500").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByDisplayValue("22550")).toBeInTheDocument();
  });
});
