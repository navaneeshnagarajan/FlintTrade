import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useModeStore } from "@/stores/modeStore";
import MarketClockWidget, {
  MARKET_DEFS,
  computeMarketState,
  computeNseMarketState,
} from "../MarketClockWidget";
import { NSE_CASH_TIMELINE_NOTE } from "@/lib/nseSession";
import { istMinutes } from "@/lib/ist";

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
  beforeEach(() => {
    useModeStore.setState({ mode: "explore" });
  });

  it("renders widget title", () => {
    render(<MarketClockWidget />);
    expect(screen.getByText("Market Clock")).toBeTruthy();
  });

  it("shows a Sample feed-source chip in Explore (FT-CORE-002)", () => {
    render(<MarketClockWidget />);
    const chip = screen.getByTestId("feed-freshness-chip");
    expect(chip.textContent).toBe("Sample");
    expect(chip.getAttribute("data-state")).toBe("sample");
    expect(chip.textContent).not.toMatch(/Live/);
  });

  it("renders IST clock in header", () => {
    render(<MarketClockWidget />);
    expect(screen.getByTestId("market-clock-ist").textContent).toMatch(/IST/);
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

  it("NSE session ends at post-close 16:00 IST, not a flat 15:30 close", () => {
    const nse = MARKET_DEFS.find((d) => d.name === "NSE");
    expect(nse).toBeDefined();
    expect(nse!.closeMin).toBe(16 * 60);
    expect(nse!.description).toMatch(/CAS-aware/);
  });

  it("all markets have non-empty name and description", () => {
    for (const def of MARKET_DEFS) {
      expect(def.name.length).toBeGreaterThan(0);
      expect(def.description.length).toBeGreaterThan(0);
    }
  });

  it("names the Nifty proxy GIFT Nifty, not the retired SGX Nifty", () => {
    // SGX Nifty ceased to exist in July 2023 — the contract migrated to NSE
    // International Exchange in GIFT City. Only the label changed here; the
    // session window is carried over unverified (see the widget comment).
    expect(MARKET_DEFS.some((d) => d.name === "SGX Nifty")).toBe(false);
    const gift = MARKET_DEFS.find((d) => d.name === "GIFT Nifty");
    expect(gift).toBeDefined();
    expect(gift!.description).toBe("NSE IX — GIFT City");
    expect(gift!.openMin).toBe(6 * 60 + 30);
    expect(gift!.closeMin).toBe(23 * 60 + 30);
  });
});

// ---------------------------------------------------------------------------
// Sessions that run past IST midnight
//
// US Markets is defined 19:00–25:30 IST (i.e. closing at 01:30 the following
// morning). The widget used to compare the raw minutes-since-midnight against
// that window, so once the IST clock wrapped to 00:00 the reading fell below
// the 19:00 open and the row flipped to Closed — for the last 90 minutes of a
// live NYSE session.
//
// Fixed instants only: nothing below reads the machine's clock or zone.
// ---------------------------------------------------------------------------

const US_MARKETS = MARKET_DEFS.find((d) => d.name === "US Markets")!;

describe("computeMarketState — sessions crossing IST midnight", () => {
  it("REGRESSION: reports US Markets Open at 01:00 IST, inside the session", () => {
    const state = computeMarketState(US_MARKETS, 60, 0);
    expect(state.status).toBe("open");
  });

  it("counts the remaining 30 minutes to the 01:30 IST close", () => {
    const state = computeMarketState(US_MARKETS, 60, 0);
    expect(state.remainingMs).toBe(30 * 60_000);
  });

  it("reports progress near the end of the session, not zero", () => {
    // 01:00 IST is 6h into a 6h30m session.
    expect(computeMarketState(US_MARKETS, 60, 0).progress).toBeCloseTo(360 / 390, 6);
  });

  it("closes at 01:30 IST and counts down to the next 19:00 open", () => {
    const state = computeMarketState(US_MARKETS, 95, 0); // 01:35 IST
    expect(state.status).toBe("closed");
    expect(state.remainingMs).toBe((19 * 60 - 95) * 60_000);
  });

  it("still reports Open during the evening leg of the same session", () => {
    expect(computeMarketState(US_MARKETS, 20 * 60, 0).status).toBe("open");
  });

  it("still reports Pre-market in the half hour before the 19:00 open", () => {
    expect(computeMarketState(US_MARKETS, 18 * 60 + 45, 0).status).toBe("pre");
  });

  it("leaves same-day sessions untouched by the wrap", () => {
    const nse = MARKET_DEFS.find((d) => d.name === "NSE")!;
    expect(computeMarketState(nse, 60, 0).status).toBe("closed");       // 01:00 IST
    expect(computeMarketState(nse, 10 * 60, 0).status).toBe("open");    // 10:00 IST
    expect(computeMarketState(nse, 16 * 60, 0).status).toBe("closed");  // 16:00 IST
  });
});

describe("computeNseMarketState — CAS honesty (FT-CORE-001)", () => {
  const nse = MARKET_DEFS.find((d) => d.name === "NSE")!;

  function istWeekday(hour: number, minute: number): Date {
    const utcMs = Date.UTC(2026, 7, 18, hour, minute, 0, 0) - (5 * 60 + 30) * 60 * 1000;
    return new Date(utcMs);
  }

  it("is Continuous (green open) at 10:00 IST", () => {
    const state = computeNseMarketState(nse, istWeekday(10, 0));
    expect(state.status).toBe("open");
    expect(state.phaseLabel).toBe("Continuous");
    expect(state.timelineNote).toBe(NSE_CASH_TIMELINE_NOTE);
  });

  it("is CAS at 15:20 — not Closed and not green Open", () => {
    const state = computeNseMarketState(nse, istWeekday(15, 20));
    expect(state.status).toBe("cas");
    expect(state.phaseLabel).toBe("CAS");
    expect(state.status).not.toBe("open");
    expect(state.status).not.toBe("closed");
  });

  it("is Matching at 15:40 and Post-close at 15:55", () => {
    expect(computeNseMarketState(nse, istWeekday(15, 40)).phaseLabel).toBe("Matching");
    expect(computeNseMarketState(nse, istWeekday(15, 55)).phaseLabel).toBe("Post-close");
  });

  it("is Closed at 16:00, not still Open until 15:30-only", () => {
    const state = computeNseMarketState(nse, istWeekday(16, 0));
    expect(state.status).toBe("closed");
    expect(state.phaseLabel).toBe("Closed");
  });
});

describe("MarketClockWidget — after IST midnight", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the NSE CAS timeline and never VWAP-last-30-min copy", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-18T04:30:00Z")); // 10:00 IST Tuesday
    render(<MarketClockWidget />);
    expect(screen.getByTestId("nse-cas-timeline")).toHaveTextContent(NSE_CASH_TIMELINE_NOTE);
    expect(screen.getByLabelText("NSE market status: Continuous")).toBeTruthy();
    expect(screen.queryByText(/VWAP last 30 min/i)).toBeNull();
    expect(screen.queryByText(/Market open until 15:30/i)).toBeNull();
  });

  it("REGRESSION: renders US Markets as Open at 01:00 IST", () => {
    // 19:30 UTC on 25 July 2026 is 01:00 IST on the 26th — the widget used to
    // render this as Closed.
    const instant = new Date("2026-07-25T19:30:00Z");
    vi.setSystemTime(instant);
    expect(istMinutes(instant)).toBe(60);

    render(<MarketClockWidget />);

    expect(screen.getByLabelText("US Markets market status: Open")).toBeTruthy();
  });
});
