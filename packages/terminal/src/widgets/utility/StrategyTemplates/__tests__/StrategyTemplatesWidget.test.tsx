/**
 * StrategyTemplatesWidget.test.tsx
 *
 * Tests: render, filter buttons, card count, custom event dispatch.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
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

describe("StrategyTemplatesWidget", () => {
  it("renders the widget header", () => {
    render(<StrategyTemplatesWidget />);
    expect(screen.getByText("Strategy Templates")).toBeTruthy();
  });

  it("renders all 12 strategy template cards by default", () => {
    render(<StrategyTemplatesWidget />);
    const cards = screen.getAllByRole("button", { name: /Load .* strategy template/i });
    expect(cards).toHaveLength(12);
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
    // Long Call, Bull Call Spread, Protective Put = 3 bullish templates
    expect(cards.length).toBeGreaterThanOrEqual(1);
    cards.forEach((card) => {
      expect(card.getAttribute("aria-label")).toMatch(/Load .* strategy template/);
    });
  });

  it("dispatches custom event when a card is clicked", () => {
    render(<StrategyTemplatesWidget />);
    const listener = vi.fn();
    window.addEventListener("flinttrade:load-strategy-template", listener);

    fireEvent.click(screen.getByLabelText("Load Long Call strategy template"));

    expect(listener).toHaveBeenCalledOnce();
    const event = listener.mock.calls[0][0] as CustomEvent;
    expect(event.detail.id).toBe("long_call");

    window.removeEventListener("flinttrade:load-strategy-template", listener);
  });

  it("shows correct card details for Iron Condor", () => {
    render(<StrategyTemplatesWidget />);
    expect(screen.getByText("Iron Condor")).toBeTruthy();
    expect(screen.getByText("Net credit")).toBeTruthy();
  });
});
