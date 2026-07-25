/**
 * StrategyTemplatesWidget.test.tsx
 *
 * Tests: render, filter buttons, loadable vs reference split, builder
 * hand-off (event + sessionStorage stash + navigation).
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import StrategyTemplatesWidget from "../StrategyTemplatesWidget";
import {
  LOAD_TEMPLATE_EVENT,
  PENDING_TEMPLATE_KEY,
  type BuilderTemplate,
} from "@/tools/StrategyBuilder/templateBridge";

describe("StrategyTemplatesWidget", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("renders the widget header", () => {
    render(<StrategyTemplatesWidget />);
    expect(screen.getByText("Strategy Templates")).toBeTruthy();
  });

  // Was 8 loadable / 12 total. The unified catalogue (lib/strategyTemplates)
  // adds the two explicitly-short volatility entries — the widget's old
  // `straddle`/`strangle` ids meant LONG here but SHORT in the OptionChain
  // LegBuilder, so both directions now exist under their own names.
  it("renders 10 loadable cards and 4 reference-only cards (14 total)", () => {
    render(<StrategyTemplatesWidget />);
    const loadable = screen.getAllByRole("button", { name: /Load .* strategy template/i });
    expect(loadable).toHaveLength(10);
    // Stock-leg and multi-expiry templates must NOT offer a load affordance —
    // the options builder cannot represent them faithfully.
    for (const name of ["Covered Call", "Protective Put", "Collar", "Calendar Spread"]) {
      expect(
        screen.getByLabelText(`${name} strategy template (reference only)`),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: `Load ${name} strategy template` }),
      ).not.toBeInTheDocument();
    }
  });

  it("renders outlook filter buttons", () => {
    render(<StrategyTemplatesWidget />);
    expect(screen.getByRole("button", { name: "All" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bullish" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Bearish" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Neutral" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Volatile" })).toBeTruthy();
  });

  it("filters to bullish templates only", () => {
    render(<StrategyTemplatesWidget />);
    fireEvent.click(screen.getByRole("button", { name: "Bullish" }));
    const cards = screen.getAllByRole("button", { name: /Load .* strategy template/i });
    expect(cards.length).toBeGreaterThanOrEqual(1);
    cards.forEach((card) => {
      expect(card.getAttribute("aria-label")).toMatch(/Load .* strategy template/);
    });
  });

  it("hands a loadable template to the builder: event + stash + navigate", () => {
    render(<StrategyTemplatesWidget />);
    const loadListener = vi.fn();
    const navListener = vi.fn();
    window.addEventListener(LOAD_TEMPLATE_EVENT, loadListener);
    window.addEventListener("flinttrade:navigate", navListener);

    fireEvent.click(screen.getByLabelText("Load Long Call strategy template"));

    expect(loadListener).toHaveBeenCalledOnce();
    const event = loadListener.mock.calls[0][0] as CustomEvent;
    // Ids are kebab-case now (the shared catalogue's convention, already used
    // by both builders); the widget's old snake_case ids are gone.
    expect(event.detail.id).toBe("long-call");
    expect(event.detail.legs).toEqual([
      { action: "BUY", optionType: "CE", strikeOffset: 0, lots: 1 },
    ]);

    // Stash for the builder to read after the route change.
    const stashed = JSON.parse(
      sessionStorage.getItem(PENDING_TEMPLATE_KEY) ?? "null",
    ) as BuilderTemplate;
    expect(stashed.id).toBe("long-call");

    // Navigates to the Lab where the Options Builder lives.
    expect(navListener).toHaveBeenCalledOnce();
    const nav = navListener.mock.calls[0][0] as CustomEvent;
    expect(nav.detail.path).toBe("/lab");

    window.removeEventListener(LOAD_TEMPLATE_EVENT, loadListener);
    window.removeEventListener("flinttrade:navigate", navListener);
  });

  it("hands off the iron condor with four distinct strike offsets", () => {
    render(<StrategyTemplatesWidget />);
    fireEvent.click(screen.getByLabelText("Load Iron Condor strategy template"));

    const stashed = JSON.parse(
      sessionStorage.getItem(PENDING_TEMPLATE_KEY) ?? "null",
    ) as BuilderTemplate;
    expect(stashed.id).toBe("iron-condor");
    // The old coarse ATM/OTM labels could not distinguish the short strikes
    // from the protective wings — explicit offsets can.
    expect(stashed.legs.map((l) => l.strikeOffset).sort((a, b) => a - b)).toEqual([-2, -1, 1, 2]);
    expect(stashed.legs).toContainEqual({ action: "SELL", optionType: "CE", strikeOffset: 1, lots: 1 });
    expect(stashed.legs).toContainEqual({ action: "BUY", optionType: "CE", strikeOffset: 2, lots: 1 });
    expect(stashed.legs).toContainEqual({ action: "SELL", optionType: "PE", strikeOffset: -1, lots: 1 });
    expect(stashed.legs).toContainEqual({ action: "BUY", optionType: "PE", strikeOffset: -2, lots: 1 });
  });

  it("hands off long and short straddles as separate, opposite-direction cards", () => {
    // Regression guard for the catalogue merge: a single "Straddle" card used
    // to mean BUY-both here and SELL-both in the OptionChain LegBuilder.
    render(<StrategyTemplatesWidget />);

    fireEvent.click(screen.getByLabelText("Load Long Straddle strategy template"));
    const long = JSON.parse(
      sessionStorage.getItem(PENDING_TEMPLATE_KEY) ?? "null",
    ) as BuilderTemplate;
    expect(long.id).toBe("long-straddle");
    expect(long.legs.every((l) => l.action === "BUY")).toBe(true);

    fireEvent.click(screen.getByLabelText("Load Short Straddle strategy template"));
    const short = JSON.parse(
      sessionStorage.getItem(PENDING_TEMPLATE_KEY) ?? "null",
    ) as BuilderTemplate;
    expect(short.id).toBe("short-straddle");
    expect(short.legs.every((l) => l.action === "SELL")).toBe(true);

    expect(screen.queryByLabelText("Load Straddle strategy template")).not.toBeInTheDocument();
  });

  it("shows correct card details for Iron Condor", () => {
    render(<StrategyTemplatesWidget />);
    expect(screen.getByText("Iron Condor")).toBeTruthy();
    expect(screen.getByText("Net credit")).toBeTruthy();
  });
});
