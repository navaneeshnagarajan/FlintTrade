/**
 * CalculatorWidget.test.tsx
 *
 * The merged calculator: Sizing, Target / R:R, Brokerage and Margin.
 *
 * The numeric characterisation blocks are the only numeric coverage this
 * family has, and they carry over the pins written for all three pre-merge
 * widgets (Calculator, Position Sizing, Profit Target). Where a pin moved
 * tab — Position Sizing's suggested-lot arithmetic and Profit Target's
 * suggested quantity are both the Sizing tab now — the inputs and the
 * expected numbers are unchanged; only the surface they are read from moved.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const apiMocks = vi.hoisted(() => ({
  getMargin: vi.fn(),
  getFunds: vi.fn(),
}));

const accountReadState = vi.hoisted(() => {
  let current: AccountReadContext | undefined;
  const listeners = new Set<() => void>();
  return {
    get current() { return current; },
    set current(value: AccountReadContext | undefined) {
      current = value;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

vi.mock("@/services/api", () => ({
  getMargin: apiMocks.getMargin,
  getFunds: apiMocks.getFunds,
}));

vi.mock("@/hooks/useAccountReadsEnabled", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useAccountReadContext: () => useSyncExternalStore(
      accountReadState.subscribe,
      () => accountReadState.current,
    ),
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const ACCOUNT_B_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:native:upstox:B2",
    brokerType: "upstox",
    accountId: "B2",
  }),
  enabled: true,
  host: "",
  apiKey: "",
}) satisfies AccountReadContext;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const LIVE_MARGIN = {
    span_margin: 12000,
    exposure_margin: 8000,
    total_margin_required: 20000,
};

const ACCOUNT_A_FUNDS = {
    availableCash: 100000,
    usedMargin: 20000,
    totalBalance: 120000,
};

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import CalculatorWidget from "../CalculatorWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = makeWidgetPanelProps();

/** Render with a `tab` panel param, as a retired id or a saved layout would. */
function renderWithTab(tab: string) {
  return render(
    <CalculatorWidget {...makeWidgetPanelProps<{ tab: string }>({ params: { tab } })} />,
  );
}

/** Read the value cell of a labelled result or legend row. */
function resultValue(label: string): string {
  const row = screen.getByText(label).closest("div");
  return row?.querySelector("span:last-child")?.textContent?.trim() ?? "";
}

/** As {@link resultValue}, scoped — "Brokerage" is both a tab and a charge. */
function resultValueIn(scope: HTMLElement, label: string): string {
  const row = within(scope).getByText(label).closest("div");
  return row?.querySelector("span:last-child")?.textContent?.trim() ?? "";
}

/** Type into the field with the given accessible label. */
function setField(label: string, value: string): void {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

/** Open one of the four top-level sections. */
async function openTab(name: RegExp): Promise<void> {
  await userEvent.click(
    within(screen.getByRole("tablist", { name: "Calculator sections" })).getByRole("tab", {
      name,
    }),
  );
}

/** Select one of the three sizing methods. */
function selectMethod(name: string): void {
  fireEvent.click(
    within(screen.getByRole("tablist", { name: "Position sizing method" })).getByRole("tab", {
      name,
    }),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
  apiMocks.getMargin.mockReset().mockResolvedValue(LIVE_MARGIN);
  apiMocks.getFunds.mockReset().mockResolvedValue(ACCOUNT_A_FUNDS);
});

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------

describe("CalculatorWidget shell", () => {
  it("renders without crashing", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Calculator")).toBeInTheDocument();
  });

  it("has the four section tabs", () => {
    render(<CalculatorWidget {...defaultProps} />);
    const sections = within(screen.getByRole("tablist", { name: "Calculator sections" }));
    expect(sections.getByRole("tab", { name: /sizing/i })).toBeInTheDocument();
    expect(sections.getByRole("tab", { name: /target/i })).toBeInTheDocument();
    expect(sections.getByRole("tab", { name: /brokerage/i })).toBeInTheDocument();
    expect(sections.getByRole("tab", { name: /margin/i })).toBeInTheDocument();
  });

  it("opens on Sizing by default", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Position Size (lots)")).toBeInTheDocument();
  });

  it("opens on the tab named by params — the retired positionsizing id", () => {
    renderWithTab("sizing");
    expect(screen.getByRole("tablist", { name: "Position sizing method" })).toBeInTheDocument();
  });

  it("opens on the tab named by params — the retired profittarget id", () => {
    renderWithTab("target");
    expect(screen.getByText("Breakeven Win Rate")).toBeInTheDocument();
  });

  it("opens on the brokerage and margin tabs when asked", () => {
    const { unmount } = renderWithTab("brokerage");
    expect(screen.getByText("Charges Breakdown")).toBeInTheDocument();
    unmount();

    renderWithTab("margin");
    expect(screen.getByText("Margin Required")).toBeInTheDocument();
  });

  it("falls back to Sizing for an unknown tab param", () => {
    renderWithTab("payoff");
    expect(screen.getByText("Position Size (lots)")).toBeInTheDocument();
  });

  it("persists the chosen tab into the panel params", async () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps();
    render(<CalculatorWidget {...props} api={{ ...props.api, updateParameters }} />);

    await openTab(/brokerage/i);
    expect(updateParameters).toHaveBeenCalledWith({ tab: "brokerage" });
  });
});

// ---------------------------------------------------------------------------
// Sizing tab
// ---------------------------------------------------------------------------

describe("Sizing tab", () => {
  it("shows the risk templates", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByRole("button", { name: "Conservative" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Balanced" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aggressive" })).toBeInTheDocument();
  });

  it("applying the Balanced template rewrites capital, risk % and the target R:R", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await userEvent.click(screen.getByRole("button", { name: "Balanced" }));

    expect(screen.getByLabelText("Account Capital")).toHaveValue(200_000);
    expect(screen.getByLabelText("Risk per Trade %")).toHaveValue(2);

    // The template's R:R reaches the Target tab, which is only true because the
    // two surfaces now share one trade description.
    await openTab(/target/i);
    expect(screen.getByRole("combobox", { name: "Target R:R" })).toHaveTextContent("2.00 : 1");
  });

  it("renders three sizing methods with Fixed % active by default", () => {
    render(<CalculatorWidget {...defaultProps} />);
    const methods = within(screen.getByRole("tablist", { name: "Position sizing method" }));
    expect(methods.getByRole("tab", { name: "Fixed %" })).toHaveAttribute("aria-selected", "true");
    expect(methods.getByRole("tab", { name: "Kelly" })).toBeInTheDocument();
    expect(methods.getByRole("tab", { name: "ATR" })).toBeInTheDocument();
  });

  it("switches to Kelly and shows its inputs", () => {
    render(<CalculatorWidget {...defaultProps} />);
    selectMethod("Kelly");
    expect(screen.getByLabelText("Win Rate %")).toBeInTheDocument();
    expect(screen.getByLabelText("Reward : Risk")).toBeInTheDocument();
    // Kelly derives the stake, so the operator's risk % is not asked for.
    expect(screen.queryByLabelText("Risk per Trade %")).not.toBeInTheDocument();
  });

  it("switches to ATR and shows its inputs", () => {
    render(<CalculatorWidget {...defaultProps} />);
    selectMethod("ATR");
    expect(screen.getByLabelText("ATR Value")).toBeInTheDocument();
    expect(screen.getByLabelText("ATR Multiplier")).toBeInTheDocument();
  });

  it("renders capital allocation through the shared Flint donut primitive", () => {
    render(<CalculatorWidget {...defaultProps} />);
    const chart = screen.getByRole("img", { name: /capital allocation/i });
    expect(chart).toHaveClass("rounded-full");
    expect(chart.getAttribute("style")).toContain("conic-gradient");
    expect(chart.querySelector("svg")).not.toBeInTheDocument();
  });

  it("renders the At Risk and Available donut legend", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("At Risk")).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
  });

  it("shows the empty state when account capital is cleared", () => {
    render(<CalculatorWidget {...defaultProps} />);
    setField("Account Capital", "");
    expect(screen.getByText(/fill in all fields/i)).toBeInTheDocument();
  });

  it("refuses a direction the prices contradict", () => {
    render(<CalculatorWidget {...defaultProps} />);
    // Stop sitting exactly on entry is not a trade, so there is nothing to size.
    setField("Stop Loss", "22000");
    expect(screen.getByText(/fill in all fields/i)).toBeInTheDocument();
  });

  // ── Numeric characterisation (pins the sizing kernel) ─────────────────────

  describe("sizing arithmetic", () => {
    it("pins the default Fixed % result — 1 lot, clamped above the risk budget", () => {
      render(<CalculatorWidget {...defaultProps} />);

      // Capital ₹5,00,000 · risk 1% → budget ₹5,000. Stop 22,000 → 21,800 is
      // 200 points, so one 50-unit lot risks ₹10,000: floor() lands on 0 and
      // the max(1, …) clamp recommends a lot risking 2× the stated budget.
      expect(resultValue("Position Size (lots)")).toBe("1");
      expect(resultValue("Units (shares)")).toBe("50");
      expect(resultValue("SL Points")).toBe("200.00");
      expect(resultValue("Risk Budget")).toBe("₹5,000");
      expect(resultValue("Actual Risk")).toBe("₹10,000");
      expect(resultValue("At Risk")).toBe("2.00%");
      expect(resultValue("Available")).toBe("98.00%");

      // …and the clamp is stated out loud instead of passing silently.
      expect(screen.getByRole("status")).toHaveTextContent(
        /single lot risks ₹10,000 — more than the ₹5,000 you allowed/i,
      );
    });

    it("pins Fixed % sizing when the budget covers several lots", () => {
      render(<CalculatorWidget {...defaultProps} />);
      // A 50-point stop — the pre-merge widget typed this as a distance.
      setField("Stop Loss", "21950");

      // Budget ₹5,000 / (50 × 50 = ₹2,500 per lot) → 2 lots exactly.
      expect(resultValue("Position Size (lots)")).toBe("2");
      expect(resultValue("Units (shares)")).toBe("100");
      expect(resultValue("Actual Risk")).toBe("₹5,000");
      expect(resultValue("At Risk")).toBe("1.00%");
      // Within budget → no warning.
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the lot count a 4% budget buys at the default stop", () => {
      render(<CalculatorWidget {...defaultProps} />);
      setField("Risk per Trade %", "4");

      // Budget ₹20,000 / (200 × 50 = ₹10,000 per lot) → 2 lots exactly.
      // (Profit Target's "Suggested Qty (lots)" pin — same inputs, same answer,
      // read from the tab that now owns every quantity recommendation.)
      expect(resultValue("Position Size (lots)")).toBe("2");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the default half-Kelly result", () => {
      render(<CalculatorWidget {...defaultProps} />);
      selectMethod("Kelly");

      // 55% win rate at 2R → full Kelly (0.55 × 2 − 0.45) / 2 = 32.5%,
      // half-Kelly 16.25% → budget ₹81,250 / ₹10,000 per lot → 8 lots.
      expect(resultValue("Kelly Stake")).toBe("16.25%");
      expect(resultValue("Position Size (lots)")).toBe("8");
      expect(resultValue("Units (shares)")).toBe("400");
      expect(resultValue("Actual Risk")).toBe("₹80,000");
      expect(resultValue("At Risk")).toBe("16.00%");
      // Half-Kelly sized the budget itself, so nothing is over-risked.
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("pins the default ATR result — also clamped above the risk budget", () => {
      render(<CalculatorWidget {...defaultProps} />);
      selectMethod("ATR");

      // Stop distance = ATR 180 × 1.5 = 270 → ₹13,500 per lot vs a ₹5,000
      // budget, so the clamp again recommends 1 over-risked lot.
      expect(resultValue("Position Size (lots)")).toBe("1");
      expect(resultValue("Units (shares)")).toBe("50");
      expect(resultValue("Actual Risk")).toBe("₹13,500");
      expect(resultValue("At Risk")).toBe("2.70%");
      // The derived stop is shown, because the operator never typed it.
      expect(resultValue("Stop Loss (from ATR)")).toBe("₹21,730");
      expect(screen.getByRole("status")).toHaveTextContent(
        /single lot risks ₹13,500 — more than the ₹5,000 you allowed/i,
      );
    });

    it("pins quantity and position value for a known BUY trade in shares", () => {
      render(<CalculatorWidget {...defaultProps} />);
      setField("Account Capital", "200000");
      setField("Risk per Trade %", "2");
      setField("Lot Size", "1");
      setField("Entry Price", "500");
      setField("Stop Loss", "490");

      // Budget ₹4,000, SL points 10 → floor(4000 / 10) = 400 shares.
      expect(resultValue("Position Size (lots)")).toBe("400");
      expect(resultValue("Units (shares)")).toBe("400");
      expect(resultValue("Position Value")).toBe("₹2,00,000");
      expect(resultValue("SL Points")).toBe("10.00");
      expect(resultValue("Risk Budget")).toBe("₹4,000");
      expect(resultValue("Actual Risk")).toBe("₹4,000");
    });

    it("pins a SELL trade, auto-detecting the side from a stop above entry", () => {
      render(<CalculatorWidget {...defaultProps} />);
      setField("Account Capital", "200000");
      setField("Risk per Trade %", "2");
      setField("Lot Size", "1");
      setField("Entry Price", "490");
      setField("Stop Loss", "500");

      // The Side select still reads BUY; the prices win.
      expect(resultValue("Position Size (lots)")).toBe("400");
      expect(resultValue("SL Points")).toBe("10.00");
    });

    it("shows budget and actual apart when flooring to whole units bites", () => {
      render(<CalculatorWidget {...defaultProps} />);
      setField("Account Capital", "200000");
      setField("Risk per Trade %", "2");
      setField("Lot Size", "1");
      setField("Entry Price", "500");
      setField("Stop Loss", "487");

      // A 13-point stop against a ₹4,000 budget buys floor(4000 / 13) = 307
      // shares risking ₹3,991 — ₹9 under. The pre-merge widgets printed the
      // budget alone under "Risk Amount", so this ₹9 was invisible.
      expect(resultValue("Position Size (lots)")).toBe("307");
      expect(resultValue("Risk Budget")).toBe("₹4,000");
      expect(resultValue("Actual Risk")).toBe("₹3,991");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    });

    it("warns rather than hiding results when one share breaches the risk budget", () => {
      render(<CalculatorWidget {...defaultProps} />);
      setField("Account Capital", "200000");
      setField("Risk per Trade %", "2");
      setField("Lot Size", "1");
      // Budget ₹4,000 but a single share risks ₹10,000 → floor() lands on 0.
      // Pre-merge this rendered the empty-form placeholder, which was
      // indistinguishable from "you have not typed anything yet".
      setField("Entry Price", "100000");
      setField("Stop Loss", "90000");

      expect(resultValue("Position Size (lots)")).toBe("1");
      expect(resultValue("Units (shares)")).toBe("1");
      expect(resultValue("Risk Budget")).toBe("₹4,000");
      expect(resultValue("Actual Risk")).toBe("₹10,000");
      expect(screen.getByRole("status")).toHaveTextContent(
        /single share risks ₹10,000 — more than the ₹4,000 you allowed/i,
      );
      expect(screen.queryByText(/fill in all fields/i)).not.toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Target / R:R tab
// ---------------------------------------------------------------------------

describe("Target / R:R tab", () => {
  async function openTarget() {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/target/i);
  }

  it("renders every trade input", async () => {
    await openTarget();
    expect(screen.getByLabelText("Entry Price")).toBeInTheDocument();
    expect(screen.getByLabelText("Stop Loss")).toBeInTheDocument();
    expect(screen.getByLabelText("Target Price")).toBeInTheDocument();
    expect(screen.getByLabelText("Quantity (lots)")).toBeInTheDocument();
    expect(screen.getByLabelText("Lot Size")).toBeInTheDocument();
  });

  it("renders the R:R bar with its aria label", async () => {
    await openTarget();
    expect(screen.getByLabelText(/risk reward ratio/i)).toBeInTheDocument();
  });

  it("shows the breakeven insight in prose", async () => {
    await openTarget();
    expect(screen.getByText(/of your trades to break even at this R:R/i)).toBeInTheDocument();
  });

  it("shows the empty state when entry is cleared", async () => {
    await openTarget();
    setField("Entry Price", "");
    expect(screen.getByText(/enter entry, stop loss and target/i)).toBeInTheDocument();
  });

  it("reads the entry price typed on the Sizing tab", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    setField("Entry Price", "23000");
    await openTab(/target/i);
    expect(screen.getByLabelText("Entry Price")).toHaveValue(23_000);
  });

  // ── Numeric characterisation (pins the risk/reward kernel) ────────────────

  describe("risk/reward arithmetic", () => {
    it("pins every result row for the default trade", async () => {
      await openTarget();

      // entry 22,000 · SL 21,800 · target 22,500 · 1 lot × 50 → risk 200 points,
      // reward 500 points.
      expect(resultValue("Target")).toBe("₹22,500");
      expect(resultValue("Reward Points")).toBe("500.00");
      expect(resultValue("Risk per Trade")).toBe("₹10,000");
      expect(resultValue("Potential Profit")).toBe("₹25,000");
      expect(resultValue("R:R Ratio")).toBe("2.50 : 1");
      // Breakeven win rate = 1 / (1 + 2.5) = 28.571…%
      expect(resultValue("Breakeven Win Rate")).toBe("28.6%");
    });

    it("pins the breakeven win rate at 1:1", async () => {
      await openTarget();
      setField("Target Price", "22200");

      expect(resultValue("R:R Ratio")).toBe("1.00 : 1");
      expect(resultValue("Breakeven Win Rate")).toBe("50.0%");
    });

    it("pins the auto-derived target when no target price is given", async () => {
      await openTarget();
      setField("Entry Price", "500");
      setField("Stop Loss", "490");
      setField("Target Price", "");
      setField("Quantity (lots)", "400");
      setField("Lot Size", "1");

      // SL points 10 at the default 2R → target = 500 + 10 × 2 = 520.
      expect(resultValue("Target")).toBe("₹520");
      expect(resultValue("Reward Points")).toBe("20.00");
      expect(resultValue("Potential Profit")).toBe("₹8,000");
      expect(resultValue("R:R Ratio")).toBe("2.00 : 1");
    });

    it("pins the R:R implied by an explicit target price", async () => {
      await openTarget();
      setField("Entry Price", "500");
      setField("Stop Loss", "490");
      setField("Target Price", "530");
      setField("Quantity (lots)", "400");
      setField("Lot Size", "1");

      // Reward 30 / risk 10 → 3R.
      expect(resultValue("Reward Points")).toBe("30.00");
      expect(resultValue("Potential Profit")).toBe("₹12,000");
      expect(resultValue("R:R Ratio")).toBe("3.00 : 1");
    });

    it("pins a SELL target derived below entry, auto-detecting the side", async () => {
      await openTarget();
      setField("Entry Price", "490");
      setField("Stop Loss", "500");
      setField("Target Price", "");

      // Stop above entry → SELL, so the 2R target sits below: 490 − 10 × 2 = 470.
      expect(resultValue("Target")).toBe("₹470");
      expect(resultValue("R:R Ratio")).toBe("2.00 : 1");
    });

    it("refuses a target on the wrong side of entry", async () => {
      await openTarget();
      setField("Target Price", "21000");
      expect(screen.getByText(/enter entry, stop loss and target/i)).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Brokerage tab
// ---------------------------------------------------------------------------

describe("Brokerage tab", () => {
  it("pins the default round-trip charges breakdown", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/brokerage/i);

    // 1 lot × 25 at ₹100 = ₹2,500 turnover, options, round trip, ₹20 flat.
    // STT 0.15% on the sell leg only = ₹3.75; brokerage ₹40 both legs.
    const charges = screen.getByText("Charges Breakdown").closest("div") as HTMLElement;
    expect(resultValueIn(charges, "STT")).toBe("₹3.75");
    expect(resultValueIn(charges, "Brokerage")).toBe("₹40");
    expect(resultValueIn(charges, "Total Cost")).toBe("₹51.22");
    expect(resultValueIn(charges, "Breakeven/Unit")).toBe("₹2.049");
  });

  it("recomputes when the price changes", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/brokerage/i);

    setField("Price (₹)", "200");
    // Turnover doubles, so STT doubles.
    const charges = screen.getByText("Charges Breakdown").closest("div") as HTMLElement;
    expect(resultValueIn(charges, "STT")).toBe("₹7.5");
  });
});

// ---------------------------------------------------------------------------
// Margin tab
// ---------------------------------------------------------------------------

describe("Margin tab", () => {
  it("shows the SEBI estimate note and its rows", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/margin/i);

    expect(screen.getByText(/SPAN-like/i)).toBeInTheDocument();
    expect(screen.getByText("SPAN Margin")).toBeInTheDocument();
    expect(screen.getByText("Exposure Margin")).toBeInTheDocument();
    expect(screen.getByText("Total Required")).toBeInTheDocument();
    expect(screen.getAllByText("NRML").length).toBeGreaterThanOrEqual(1);
  });

  it("pins the SPAN-like estimate and labels it ESTIMATE", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/margin/i);

    // Notional 25 × ₹100 × 1 leg = ₹2,500; NRML 15% → ₹375, split 60/40.
    expect(screen.getByText("ESTIMATE")).toBeInTheDocument();
    expect(resultValue("SPAN Margin")).toBe("₹225");
    expect(resultValue("Exposure Margin")).toBe("₹150");
    expect(resultValue("Total Required")).toBe("₹375");
  });

  it("replaces the estimate with the broker's figures and compares funds", async () => {
    render(<CalculatorWidget {...defaultProps} />);
    await openTab(/margin/i);

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));

    await waitFor(() => expect(screen.getByText("LIVE")).toBeInTheDocument());
    expect(resultValue("Total Required")).toBe("₹20,000");
    expect(resultValue("Available Funds")).toBe("₹1,00,000");
    expect(resultValue("After Margin")).toBe("₹80,000");
  });

  it("makes zero account requests when Live account reads are unconfigured", async () => {
    accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;
    renderWithTab("margin");

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));

    expect(apiMocks.getFunds).not.toHaveBeenCalled();
    expect(apiMocks.getMargin).not.toHaveBeenCalled();
  });

  it.each([
    ["native Live", CONNECTED_NATIVE_READ_CONTEXT],
    ["Practice", PRACTICE_READ_CONTEXT],
  ])("pins %s funds and margin to the same exact account context and AbortSignal", async (_label, context) => {
    accountReadState.current = context;
    renderWithTab("margin");

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));

    await waitFor(() => expect(apiMocks.getMargin).toHaveBeenCalledOnce());
    const signal = apiMocks.getFunds.mock.calls[0]?.[1] as AbortSignal | undefined;
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(apiMocks.getFunds).toHaveBeenCalledWith(context, signal);
    expect(apiMocks.getMargin).toHaveBeenCalledWith(
      context,
      "NIFTY",
      "NFO",
      25,
      "NRML",
      "BUY",
      signal,
    );
  });

  it("clears account-A funds immediately when account B becomes active", async () => {
    const props = makeWidgetPanelProps<{ tab: string }>({ params: { tab: "margin" } });
    const { rerender } = render(<CalculatorWidget {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(resultValue("Available Funds")).toBe("₹1,00,000"));

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<CalculatorWidget {...props} />);

    await waitFor(() => expect(screen.queryByText("Available Funds")).not.toBeInTheDocument());
  });

  it("aborts and ignores a late account-A funds response after switching to B", async () => {
    const pendingA = deferred<typeof ACCOUNT_A_FUNDS>();
    apiMocks.getFunds
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValueOnce({
        availableCash: 200000,
        usedMargin: 10000,
        totalBalance: 210000,
      });
    const props = makeWidgetPanelProps<{ tab: string }>({ params: { tab: "margin" } });
    const { rerender } = render(<CalculatorWidget {...props} />);

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(apiMocks.getFunds).toHaveBeenCalledTimes(1));
    const accountASignal = apiMocks.getFunds.mock.calls[0]?.[1] as AbortSignal | undefined;

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<CalculatorWidget {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(resultValue("Available Funds")).toBe("₹2,00,000"));

    pendingA.resolve(ACCOUNT_A_FUNDS);
    await pendingA.promise;
    await waitFor(() => expect(resultValue("Available Funds")).toBe("₹2,00,000"));
    expect(accountASignal?.aborted).toBe(true);
  });

  it("does not retarget or commit a late non-abortable account-A margin after switching to B", async () => {
    const pendingA = deferred<typeof LIVE_MARGIN>();
    const accountBMargin = {
      span_margin: 18000,
      exposure_margin: 12000,
      total_margin_required: 30000,
    };
    apiMocks.getMargin
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValueOnce(accountBMargin);
    apiMocks.getFunds
      .mockResolvedValueOnce(ACCOUNT_A_FUNDS)
      .mockResolvedValueOnce({
        availableCash: 200000,
        usedMargin: 10000,
        totalBalance: 210000,
      });
    const props = makeWidgetPanelProps<{ tab: string }>({ params: { tab: "margin" } });
    const { rerender } = render(<CalculatorWidget {...props} />);

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(apiMocks.getMargin).toHaveBeenCalledTimes(1));
    const accountASignal = apiMocks.getMargin.mock.calls[0]?.[6] as AbortSignal | undefined;
    expect(apiMocks.getMargin.mock.calls[0]?.[0]).toBe(CONNECTED_NATIVE_READ_CONTEXT);

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<CalculatorWidget {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(resultValue("Total Required")).toBe("₹30,000"));
    expect(apiMocks.getMargin.mock.calls[1]?.[0]).toBe(ACCOUNT_B_READ_CONTEXT);

    pendingA.resolve(LIVE_MARGIN);
    await pendingA.promise;
    await waitFor(() => expect(resultValue("Total Required")).toBe("₹30,000"));
    expect(accountASignal?.aborted).toBe(true);
  });

  it("keeps only the latest result from overlapping requests on the same authority", async () => {
    const first = deferred<typeof LIVE_MARGIN>();
    const second = deferred<typeof LIVE_MARGIN>();
    apiMocks.getMargin
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    renderWithTab("margin");
    const form = screen.getByRole("button", { name: /get live margin/i }).closest("form");
    expect(form).not.toBeNull();

    fireEvent.submit(form!);
    await waitFor(() => expect(apiMocks.getMargin).toHaveBeenCalledTimes(1));
    const firstSignal = apiMocks.getMargin.mock.calls[0]?.[6] as AbortSignal | undefined;
    fireEvent.submit(form!);
    await waitFor(() => expect(apiMocks.getMargin).toHaveBeenCalledTimes(2));
    const secondSignal = apiMocks.getMargin.mock.calls[1]?.[6] as AbortSignal | undefined;

    expect(firstSignal?.aborted).toBe(true);
    expect(secondSignal?.aborted).toBe(false);
    second.resolve({
      span_margin: 18000,
      exposure_margin: 12000,
      total_margin_required: 30000,
    });
    await waitFor(() => expect(resultValue("Total Required")).toBe("₹30,000"));

    first.resolve(LIVE_MARGIN);
    await first.promise;
    await waitFor(() => expect(resultValue("Total Required")).toBe("₹30,000"));
  });

  it("aborts the shared funds and margin signal on unmount", async () => {
    apiMocks.getMargin.mockReturnValue(new Promise(() => {}));
    const { unmount } = renderWithTab("margin");

    await userEvent.click(screen.getByRole("button", { name: /get live margin/i }));
    await waitFor(() => expect(apiMocks.getMargin).toHaveBeenCalledOnce());
    const fundsSignal = apiMocks.getFunds.mock.calls[0]?.[1] as AbortSignal | undefined;
    const marginSignal = apiMocks.getMargin.mock.calls[0]?.[6] as AbortSignal | undefined;

    expect(marginSignal).toBe(fundsSignal);
    unmount();
    expect(fundsSignal?.aborted).toBe(true);
    expect(marginSignal?.aborted).toBe(true);
  });
});
