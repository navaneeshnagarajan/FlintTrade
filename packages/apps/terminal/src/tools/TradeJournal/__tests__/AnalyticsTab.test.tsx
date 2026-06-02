/**
 * AnalyticsTab.test.tsx
 *
 * Focused tests for Trade Journal analytics visuals.
 */

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { AnalyticsTab } from "../AnalyticsTab";
import type { JournalTrade } from "@/services/ftApi";

function makeTrade(overrides: Partial<JournalTrade>): JournalTrade {
  return {
    action: "BUY",
    entry_price: 100,
    exchange: "NFO",
    exit_price: 110,
    fees: 12,
    pnl: 1000,
    price: 100,
    quantity: 10,
    strategy: "Test",
    symbol: "NIFTY",
    timestamp: "2026-04-13T09:30:00",
    ...overrides,
  };
}

describe("AnalyticsTab", () => {
  it("renders symbol P&L through the shared ranked-bar primitive", () => {
    render(
      <AnalyticsTab
        trades={[
          makeTrade({ symbol: "NIFTY", pnl: 2400 }),
          makeTrade({ symbol: "BANKNIFTY", pnl: -1200, timestamp: "2026-04-14T09:30:00" }),
          makeTrade({ symbol: "NIFTY", pnl: 800, timestamp: "2026-04-15T09:30:00" }),
        ]}
      />,
    );

    expect(screen.getByRole("list", { name: "Trade journal P&L by symbol" })).toHaveAttribute(
      "data-flint-chart",
      "ranked-bar-list",
    );
  });

  it("renders day-of-week P&L through the shared signed categorical bar primitive", () => {
    render(
      <AnalyticsTab
        trades={[
          makeTrade({ symbol: "NIFTY", pnl: 2400 }),
          makeTrade({ symbol: "BANKNIFTY", pnl: -1200, timestamp: "2026-04-14T09:30:00" }),
          makeTrade({ symbol: "FINNIFTY", pnl: 800, timestamp: "2026-04-15T09:30:00" }),
        ]}
      />,
    );

    expect(screen.getByRole("img", { name: "Trade journal P&L by day of week" })).toHaveAttribute(
      "data-flint-chart",
      "signed-categorical-bar",
    );
  });
});
