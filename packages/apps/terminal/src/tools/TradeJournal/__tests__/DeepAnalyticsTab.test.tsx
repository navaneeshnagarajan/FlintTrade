/**
 * DeepAnalyticsTab.test.tsx
 *
 * Focused tests for Trade Journal deep analytics visuals.
 */

import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { DeepAnalyticsTab } from "../DeepAnalyticsTab";
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

describe("DeepAnalyticsTab", () => {
  it("renders data-present visuals through shared chart primitives", () => {
    render(
      <DeepAnalyticsTab
        trades={[
          makeTrade({ symbol: "NIFTY", pnl: 2400, timestamp: "2026-04-13T09:30:00" }),
          makeTrade({ symbol: "NIFTY", pnl: -1200, timestamp: "2026-04-13T10:10:00" }),
          makeTrade({ symbol: "BANKNIFTY", pnl: 1800, timestamp: "2026-04-20T09:30:00" }),
          makeTrade({ symbol: "FINNIFTY", pnl: -900, timestamp: "2026-04-21T09:30:00" }),
          makeTrade({ symbol: "MIDCPNIFTY", pnl: 3200, timestamp: "2026-05-04T09:30:00" }),
        ]}
      />,
    );

    expect(screen.getByRole("list", { name: "Deep analytics win rate over time" })).toHaveAttribute(
      "data-flint-chart",
      "ranked-bar-list",
    );
    expect(screen.getByRole("list", { name: "Deep analytics instrument performance" })).toHaveAttribute(
      "data-flint-chart",
      "ranked-bar-list",
    );
    expect(screen.getByRole("img", { name: "Deep analytics risk-reward distribution" })).toHaveAttribute(
      "data-flint-chart",
      "categorical-bar",
    );
  });
});
