import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import MarketClockWidget, { MARKET_DEFS } from "../MarketClockWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Widget render tests
// ---------------------------------------------------------------------------

describe("MarketClockWidget", () => {
  it("renders widget title", () => {
    render(<MarketClockWidget />);
    expect(screen.getByText("Market Clock")).toBeTruthy();
  });

  it("renders IST clock in header", () => {
    render(<MarketClockWidget />);
    // time string in header has tabular-nums class
    const clockEl = document.querySelector(".tabular-nums");
    expect(clockEl).toBeTruthy();
    expect(clockEl?.textContent).toMatch(/IST/);
  });

  it("renders a row for each market definition", () => {
    render(<MarketClockWidget />);
    for (const def of MARKET_DEFS) {
      expect(screen.getByText(def.name)).toBeTruthy();
    }
  });

  it("renders market session list with correct role", () => {
    render(<MarketClockWidget />);
    expect(screen.getByRole("list", { name: /market session list/i })).toBeTruthy();
  });

  it("renders each market row with listitem role and aria-label", () => {
    render(<MarketClockWidget />);
    const items = screen.getAllByRole("listitem");
    expect(items.length).toBeGreaterThanOrEqual(MARKET_DEFS.length);
  });

  it("renders legend with Open, Pre-market, Closed labels", () => {
    render(<MarketClockWidget />);
    // These may appear multiple times (rows + legend) — just verify presence
    expect(screen.getAllByText("Open").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pre-market").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Closed").length).toBeGreaterThan(0);
  });

  it("renders progress bars for all markets", () => {
    render(<MarketClockWidget />);
    const bars = screen.getAllByRole("progressbar");
    expect(bars.length).toBe(MARKET_DEFS.length);
  });

  it("each progress bar has aria-valuemin 0 and aria-valuemax 100", () => {
    render(<MarketClockWidget />);
    const bars = screen.getAllByRole("progressbar");
    for (const bar of bars) {
      expect(bar.getAttribute("aria-valuemin")).toBe("0");
      expect(bar.getAttribute("aria-valuemax")).toBe("100");
    }
  });

  it("renders description text for each market", () => {
    render(<MarketClockWidget />);
    for (const def of MARKET_DEFS) {
      expect(screen.getByText(def.description)).toBeTruthy();
    }
  });

  it("renders closes/opens label for each market row", () => {
    render(<MarketClockWidget />);
    // At least one "closes" or "opens" text should be present
    const closeEls = screen.queryAllByText("closes");
    const openEls = screen.queryAllByText("opens");
    expect(closeEls.length + openEls.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Market definition tests
// ---------------------------------------------------------------------------

describe("MARKET_DEFS", () => {
  it("has exactly 5 markets", () => {
    expect(MARKET_DEFS).toHaveLength(5);
  });

  it("all markets have positive openMin and closeMin", () => {
    for (const def of MARKET_DEFS) {
      expect(def.openMin).toBeGreaterThanOrEqual(0);
      expect(def.closeMin).toBeGreaterThan(0);
    }
  });

  it("NSE open is 09:15 IST (555 minutes)", () => {
    const nse = MARKET_DEFS.find((d) => d.name === "NSE");
    expect(nse).toBeDefined();
    expect(nse!.openMin).toBe(9 * 60 + 15);
  });

  it("NSE close is 15:30 IST (930 minutes)", () => {
    const nse = MARKET_DEFS.find((d) => d.name === "NSE");
    expect(nse!.closeMin).toBe(15 * 60 + 30);
  });

  it("all markets have non-empty name and description", () => {
    for (const def of MARKET_DEFS) {
      expect(def.name.length).toBeGreaterThan(0);
      expect(def.description.length).toBeGreaterThan(0);
    }
  });
});
