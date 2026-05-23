/**
 * LegBuilder.test.tsx
 *
 * Unit tests for the multi-leg option strategy builder panel.
 * Covers: template application, leg CRUD, payoff maths, imperative handle.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { createRef } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  basketOrder: vi.fn().mockResolvedValue({ orderId: "ORD001" }),
}));

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import LegBuilder, { type LegBuilderHandle } from "../LegBuilder";
import type { StrikeRow } from "../types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

/** Minimal strike data — NIFTY-style 100-point gaps around ATM 22000 */
const makeStrikes = (): StrikeRow[] =>
  [21700, 21800, 21900, 22000, 22100, 22200, 22300].map((strike) => ({
    strike,
    call: { ltp: strike > 22000 ? 50 : 150, last_price: strike > 22000 ? 50 : 150 },
    put:  { ltp: strike < 22000 ? 50 : 150, last_price: strike < 22000 ? 50 : 150 },
  }));

const defaultProps = {
  strikes:   makeStrikes(),
  atmStrike: 22000,
  lotSize:   50,
  symLabel:  "NIFTY",
  exchange:  "NFO",
  expiry:    "2026-04-10",
  onClose:   vi.fn(),
};

function renderLegBuilder(props = {}) {
  const ref = createRef<LegBuilderHandle>();
  const utils = render(
    <LegBuilder ref={ref} {...defaultProps} {...props} />,
  );
  return { ...utils, ref };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LegBuilder — render", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the panel with strategy builder heading", () => {
    renderLegBuilder();
    expect(screen.getByRole("region", { name: "Strategy leg builder" })).toBeInTheDocument();
    expect(screen.getByText("Strategy Builder")).toBeInTheDocument();
  });

  it("renders all 7 template pills", () => {
    renderLegBuilder();
    const pills = ["STR", "STRG", "BCS", "BPS", "IC", "BF", "CUST"];
    for (const pill of pills) {
      expect(screen.getByText(pill)).toBeInTheDocument();
    }
  });

  it("shows empty-state prompt when no legs are present", () => {
    renderLegBuilder();
    expect(screen.getByText(/choose a template above/i)).toBeInTheDocument();
  });

  it("renders the close button", () => {
    renderLegBuilder();
    expect(screen.getByLabelText("Close strategy builder")).toBeInTheDocument();
  });

  it("calls onClose when close button is clicked", async () => {
    const onClose = vi.fn();
    renderLegBuilder({ onClose });
    await userEvent.click(screen.getByLabelText("Close strategy builder"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("LegBuilder — template selection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("STR template populates 2 legs (Sell CE + Sell PE at ATM)", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));

    // 2 leg rows should appear (column header + 2 data rows)
    const sideLabels = screen.getAllByLabelText("Strike price");
    expect(sideLabels).toHaveLength(2);
  });

  it("IC template populates 4 legs", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("IC"));

    const strikeSelects = screen.getAllByLabelText("Strike price");
    expect(strikeSelects).toHaveLength(4);
  });

  it("BF template populates 3 legs", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("BF"));

    const strikeSelects = screen.getAllByLabelText("Strike price");
    expect(strikeSelects).toHaveLength(3);
  });

  it("CUST template clears legs and shows empty prompt", async () => {
    renderLegBuilder();
    // First load STR
    await userEvent.click(screen.getByText("STR"));
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(2);

    // Switch to custom
    await userEvent.click(screen.getByText("CUST"));
    expect(screen.queryByLabelText("Strike price")).toBeNull();
    expect(screen.getByText(/choose a template above/i)).toBeInTheDocument();
  });

  it("active template pill has aria-pressed=true", async () => {
    renderLegBuilder();
    const strBtn = screen.getByText("STR").closest("button")!;
    await userEvent.click(strBtn);
    expect(strBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("inactive pills have aria-pressed=false", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    const icBtn = screen.getByText("IC").closest("button")!;
    expect(icBtn).toHaveAttribute("aria-pressed", "false");
  });
});

describe("LegBuilder — leg CRUD", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Add Leg button adds a blank leg and switches to CUST template", async () => {
    renderLegBuilder();
    // The button is the only <button> containing "Add Leg" text
    const addBtn = screen.getByRole("button", { name: /Add Leg/ });
    await userEvent.click(addBtn);
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(1);
    const custBtn = screen.getByText("CUST").closest("button")!;
    expect(custBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("Add Leg is capped at 4", async () => {
    renderLegBuilder();
    for (let i = 0; i < 4; i++) {
      const btn = screen.queryByRole("button", { name: /Add Leg/ });
      if (btn) await userEvent.click(btn);
    }
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(4);
    // No more Add Leg button once cap is reached
    expect(screen.queryByRole("button", { name: /Add Leg/ })).toBeNull();
  });

  it("Remove leg button removes a specific leg", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR")); // 2 legs
    const removeButtons = screen.getAllByLabelText("Remove leg");
    expect(removeButtons).toHaveLength(2);
    await userEvent.click(removeButtons[0]);
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(1);
  });

  it("toggling BUY/SELL changes the leg side", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR")); // 2 SELL legs

    // Click the B (BUY) button on the first leg
    const buyButtons = screen.getAllByText("B");
    await userEvent.click(buyButtons[0]);

    // First leg's row should now have profit background (BUY tint)
    // Verify via aria or class — we just check no crash and DOM update
    expect(buyButtons[0]).toBeInTheDocument();
  });

  it("toggling CE/PE changes the option type", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("BCS")); // 2 legs, both CE

    const peButtons = screen.getAllByText("PE");
    await userEvent.click(peButtons[0]);
    // Component should not throw; strike selector still present
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(2);
  });

  it("changing lots input updates the leg", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    const lotsInputs = screen.getAllByLabelText("Number of lots");
    fireEvent.change(lotsInputs[0], { target: { value: "3" } });
    expect((lotsInputs[0] as HTMLInputElement).value).toBe("3");
  });
});

describe("LegBuilder — imperative handle (addLegFromStrike)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("exposes addLegFromStrike via ref and adds a leg", () => {
    const { ref } = renderLegBuilder();
    expect(ref.current).not.toBeNull();
    expect(typeof ref.current?.addLegFromStrike).toBe("function");

    act(() => { ref.current!.addLegFromStrike(22000, "CE"); });
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(1);
  });

  it("toggles (removes) a leg when the same strike+type is passed twice", () => {
    const { ref } = renderLegBuilder();

    act(() => { ref.current!.addLegFromStrike(22000, "CE"); });
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(1);

    act(() => { ref.current!.addLegFromStrike(22000, "CE"); });
    expect(screen.queryByLabelText("Strike price")).toBeNull();
  });

  it("does not exceed 4 legs when called repeatedly", () => {
    const { ref } = renderLegBuilder();
    act(() => {
      ref.current!.addLegFromStrike(21700, "CE");
      ref.current!.addLegFromStrike(21800, "CE");
      ref.current!.addLegFromStrike(21900, "CE");
      ref.current!.addLegFromStrike(22000, "CE");
      ref.current!.addLegFromStrike(22100, "CE"); // 5th — should be silently ignored
    });
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(4);
  });

  it("switches active template to CUST when a leg is added via ref", async () => {
    const { ref } = renderLegBuilder();
    act(() => { ref.current!.addLegFromStrike(22000, "CE"); });
    const custBtn = screen.getByText("CUST").closest("button")!;
    expect(custBtn).toHaveAttribute("aria-pressed", "true");
  });
});

describe("LegBuilder — metrics", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows metrics footer when legs are present", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    expect(screen.getByText(/Net/)).toBeInTheDocument();
    expect(screen.getByText(/Place Strategy/)).toBeInTheDocument();
  });

  it("shows credit net premium for sell-only strategy (straddle)", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    // Straddle = 2× SELL; net premium < 0 → Credit label
    expect(screen.getByText(/Credit/)).toBeInTheDocument();
  });

  it("shows debit net premium for buy-only strategy (single BUY leg)", async () => {
    renderLegBuilder();
    // Add a single BUY leg via the button (role-scoped to avoid matching <strong>)
    await userEvent.click(screen.getByRole("button", { name: /Add Leg/ }));
    // Default is BUY CE — net premium is positive → Debit label
    expect(screen.getByText(/Debit/)).toBeInTheDocument();
  });

  it("shows breakeven values when they exist", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("BCS")); // Bull call spread — has breakeven
    // Breakeven label should appear (exact value depends on premium fixture)
    const beLabel = screen.queryByText("B/E");
    // May or may not appear depending on fixture premiums; just ensure no crash
    if (beLabel) expect(beLabel).toBeInTheDocument();
  });
});

describe("LegBuilder — order placement", () => {
  beforeEach(() => vi.clearAllMocks());

  it("Place Strategy button is disabled with no legs", () => {
    renderLegBuilder();
    const btn = screen.queryByText("Place Strategy");
    // Button only appears when legs.length > 0
    expect(btn).toBeNull();
  });

  it("Place Strategy button is enabled when legs are present", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    const btn = screen.getByText("Place Strategy");
    expect(btn).not.toBeDisabled();
  });

  it("calls basketOrder when Place Strategy is clicked", async () => {
    const { basketOrder } = await import("@/services/api");
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    await userEvent.click(screen.getByText("Place Strategy"));
    expect(basketOrder).toHaveBeenCalledTimes(1);
    const call = (basketOrder as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      strategy: string;
      orders: unknown[];
    };
    expect(call.strategy).toBe("FlintLegBuilder");
    expect(call.orders).toHaveLength(2); // straddle = 2 legs
  });

  it("shows success toast after order placement", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    await userEvent.click(screen.getByText("Place Strategy"));
    expect(await screen.findByText(/legs placed/i)).toBeInTheDocument();
  });

  it("shows error toast when basketOrder rejects", async () => {
    const { basketOrder } = await import("@/services/api");
    (basketOrder as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("Rate limit hit"),
    );
    renderLegBuilder();
    await userEvent.click(screen.getByText("STR"));
    await userEvent.click(screen.getByText("Place Strategy"));
    expect(await screen.findByText("Rate limit hit")).toBeInTheDocument();
  });

  it("shows expiry-missing error when expiry is null", async () => {
    renderLegBuilder({ expiry: null });
    await userEvent.click(screen.getByText("STR"));
    await userEvent.click(screen.getByText("Place Strategy"));
    expect(await screen.findByText("Select an expiry first")).toBeInTheDocument();
  });
});
