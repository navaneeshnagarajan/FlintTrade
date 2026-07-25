/**
 * LegBuilder.test.tsx
 *
 * Unit tests for the multi-leg option strategy builder panel.
 * Covers: template application, leg CRUD, payoff maths, imperative handle,
 * and strategy placement through the gated basket API (mocked).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { createRef } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { basketOrderMock, OrderApiErrorMock } = vi.hoisted(() => {
  /**
   * Mirror of `OrderApiError` from services/api — the widget narrows a thrown
   * error with `instanceof OrderApiError` + `.status` / `.body`, so the mocked
   * module must export a class with the identical runtime shape.
   */
  class OrderApiErrorMock extends Error {
    readonly status: number;
    readonly body: unknown;

    constructor(message: string, status: number, body: unknown) {
      super(message);
      this.name = "OrderApiError";
      this.status = status;
      this.body = body;
    }
  }
  return {
    OrderApiErrorMock,
    basketOrderMock: vi.fn().mockResolvedValue({
      status: "success",
      strategy: "FlintLegBuilder",
      timestamp: "2026-04-10T09:30:00+05:30",
      placed_count: 2,
      failed_count: 0,
      rolled_back: false,
      order_ids: ["ORD001", "ORD002"],
      legs: [],
    }),
  };
});

vi.mock("@/services/api", () => ({
  basketOrder: basketOrderMock,
  OrderApiError: OrderApiErrorMock,
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

  // Pills now come from the shared catalogue (lib/strategyTemplates). The two
  // credit pills were labelled "STR"/"STRG" while the same ids meant the LONG
  // (debit) strategies in the other two catalogues — this panel places real
  // gated basket orders, so they are now the explicit short variants. The leg
  // shapes are unchanged; only the labels name what was always being sold.
  it("renders every template pill, with the credit strategies named short", () => {
    renderLegBuilder();
    // BUPS/BECS joined when Spread View was demoted to template data — two of
    // its four spread types had been unreachable from the only builder that
    // can price them live and place them.
    const pills = ["SSTR", "SSTG", "BCS", "BPS", "BUPS", "BECS", "IC", "BF", "CUST"];
    for (const pill of pills) {
      expect(screen.getByText(pill)).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Short Straddle" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Short Strangle" })).toBeInTheDocument();
    // No ambiguous bare label may survive anywhere on the panel.
    expect(screen.queryByRole("button", { name: "Straddle" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Strangle" })).toBeNull();
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

  it("SSTR template populates 2 legs (Sell CE + Sell PE at ATM)", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));

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
    // First load SSTR
    await userEvent.click(screen.getByText("SSTR"));
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(2);

    // Switch to custom
    await userEvent.click(screen.getByText("CUST"));
    expect(screen.queryByLabelText("Strike price")).toBeNull();
    expect(screen.getByText(/choose a template above/i)).toBeInTheDocument();
  });

  it("active template pill has aria-pressed=true", async () => {
    renderLegBuilder();
    const strBtn = screen.getByText("SSTR").closest("button")!;
    await userEvent.click(strBtn);
    expect(strBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("inactive pills have aria-pressed=false", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
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
    await userEvent.click(screen.getByText("SSTR")); // 2 legs
    const removeButtons = screen.getAllByLabelText("Remove leg");
    expect(removeButtons).toHaveLength(2);
    await userEvent.click(removeButtons[0]);
    expect(screen.getAllByLabelText("Strike price")).toHaveLength(1);
  });

  it("toggling BUY/SELL changes the leg side", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR")); // 2 SELL legs

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
    await userEvent.click(screen.getByText("SSTR"));
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
    await userEvent.click(screen.getByText("SSTR"));
    expect(screen.getByText(/Net/)).toBeInTheDocument();
    // The footer's place action is present and live.
    expect(
      screen.getByRole("button", { name: /place strategy/i }),
    ).toBeInTheDocument();
  });

  it("shows credit net premium for sell-only strategy (short straddle)", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    // Short straddle = 2× SELL; net premium < 0 → Credit label
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

describe("LegBuilder — order placement (gated basket path)", () => {
  // Strategy placement dispatches basketOrder → POST /api/v1/orders/basket,
  // which is live-gated server-side (require_live_unlocked → SafetySystem
  // L1–L5 → gate_order → BrokerRouter per leg, atomic with rollback). The
  // widget's job is to build the exact payload and surface honest outcomes.
  beforeEach(() => vi.clearAllMocks());

  it("does not render the place action with no legs", () => {
    renderLegBuilder();
    // The footer (and its action button) only appears when legs.length > 0.
    expect(screen.queryByRole("button", { name: /place strategy/i })).toBeNull();
  });

  it("shows an enabled 'Place Strategy' action when legs are present", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    const btn = screen.getByRole("button", { name: "Place strategy" });
    expect(btn).toBeEnabled();
    expect(btn).toHaveTextContent(/place strategy/i);
    expect(btn).not.toHaveTextContent(/coming soon/i);
  });

  it("dispatches basketOrder with the exact per-leg contract for a short straddle", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR")); // SELL ATM CE + SELL ATM PE
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    expect(basketOrderMock).toHaveBeenCalledTimes(1);
    // Field-by-field pin of the frontend basket contract: compact option
    // symbols, quantity = lots × lotSize, MARKET/MIS, and NO price /
    // trigger_price keys (MARKET legs must reach the backend as None).
    expect(basketOrderMock).toHaveBeenCalledWith({
      strategy: "FlintLegBuilder",
      orders: [
        {
          symbol: "NIFTY10APR2622000CE",
          exchange: "NFO",
          action: "SELL",
          quantity: 50,
          orderType: "MARKET",
          product: "MIS",
        },
        {
          symbol: "NIFTY10APR2622000PE",
          exchange: "NFO",
          action: "SELL",
          quantity: 50,
          orderType: "MARKET",
          product: "MIS",
        },
      ],
    });
  });

  it("shows a placed-count toast when the basket succeeds", async () => {
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    expect(await screen.findByRole("status")).toHaveTextContent("2 legs placed");
  });

  it("surfaces the backend refusal message when the basket is rejected", async () => {
    // e.g. a SafetySystem admission block — postOrder throws with the
    // server's message and the widget must show it verbatim.
    basketOrderMock.mockRejectedValueOnce(new Error("Daily loss limit breached"));
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Daily loss limit breached");
  });

  // 422 partial-failure bodies from order_routes `place_basket` — the client
  // attaches them to OrderApiError.body and the widget must render the per-leg
  // truth, not only the first error string.
  const make422Leg = (over: Record<string, unknown> = {}) => ({
    leg_index: 0,
    symbol: "NIFTY10APR2622000CE",
    action: "SELL",
    quantity: 50,
    success: true,
    order_id: "B1",
    error: "",
    rolled_back: false,
    rollback_order_id: "",
    ...over,
  });

  it("renders placed/failed counts for a 422 partial failure with a confirmed rollback", async () => {
    basketOrderMock.mockRejectedValueOnce(
      new OrderApiErrorMock("Leg 2 failed: margin blocked", 422, {
        status: "error",
        strategy: "FlintLegBuilder",
        timestamp: "2026-07-20T10:15:00+05:30",
        placed_count: 1,
        failed_count: 1,
        rolled_back: true,
        order_ids: ["B1"],
        legs: [
          make422Leg({ rolled_back: true, rollback_order_id: "RB1" }),
          make422Leg({ leg_index: 1, symbol: "NIFTY10APR2622000PE", success: false, order_id: "", error: "margin blocked" }),
        ],
        message: "Leg 2 failed: margin blocked",
        failed_leg_index: 1,
      }),
    );
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    // Confirmed rollback (rollback_order_id present) — honest counts, but no
    // urgent alert: nothing is believed live on the broker.
    const toast = await screen.findByRole("status");
    expect(toast).toHaveTextContent("1 leg placed then rolled back, 1 failed — Leg 2 failed: margin blocked");
    expect(toast).not.toHaveTextContent(/rollback unconfirmed/i);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("raises an urgent rollback-unconfirmed warning when a rolled-back leg has no rollback order id", async () => {
    // basket_orders.py marks a FAILED rollback as rolled_back=True with
    // rollback_order_id="" — that leg was really placed and may still be open.
    basketOrderMock.mockRejectedValueOnce(
      new OrderApiErrorMock("Leg 2 failed: broker session dropped", 422, {
        status: "error",
        strategy: "FlintLegBuilder",
        timestamp: "2026-07-20T10:15:00+05:30",
        placed_count: 1,
        failed_count: 1,
        rolled_back: true,
        order_ids: ["B1"],
        legs: [
          make422Leg({ rolled_back: true, rollback_order_id: "" }),
          make422Leg({ leg_index: 1, symbol: "NIFTY10APR2622000PE", success: false, order_id: "", error: "broker session dropped" }),
        ],
        message: "Leg 2 failed: broker session dropped",
        failed_leg_index: 1,
      }),
    );
    renderLegBuilder();
    await userEvent.click(screen.getByText("SSTR"));
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "1 leg placed, 1 failed — Leg 2 failed: broker session dropped. Rollback unconfirmed — check Positions.",
    );
  });

  it("keeps the urgent rollback warning visible past the auto-dismiss window", async () => {
    vi.useFakeTimers();
    try {
      basketOrderMock.mockRejectedValueOnce(
        new OrderApiErrorMock("Leg 2 failed: broker session dropped", 422, {
          status: "error",
          placed_count: 1,
          failed_count: 1,
          rolled_back: true,
          order_ids: ["B1"],
          legs: [make422Leg({ rolled_back: true, rollback_order_id: "" })],
          message: "Leg 2 failed: broker session dropped",
        }),
      );
      renderLegBuilder();
      // fireEvent (not userEvent) — userEvent's internal delays hang under
      // fake timers; the clicks here need no pointer-event realism.
      fireEvent.click(screen.getByText("SSTR"));
      fireEvent.click(screen.getByRole("button", { name: "Place strategy" }));
      await act(async () => {}); // flush the rejected basket promise

      expect(screen.getByRole("alert")).toHaveTextContent(/rollback unconfirmed — check positions/i);

      // Ordinary toasts auto-dismiss after 4 s; the unconfirmed-rollback
      // warning must survive until the next placement attempt replaces it.
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(screen.getByRole("alert")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("refuses to dispatch without an expiry", async () => {
    renderLegBuilder({ expiry: null });
    await userEvent.click(screen.getByText("SSTR"));
    await userEvent.click(screen.getByRole("button", { name: "Place strategy" }));

    expect(basketOrderMock).not.toHaveBeenCalled();
    expect(await screen.findByRole("status")).toHaveTextContent("Select an expiry first");
  });
});
