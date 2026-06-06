/**
 * demoDashboard.test.tsx
 *
 * Regression guard for the demo-mode (explore) dashboard: the REST-backed cards
 * (Positions / Orders / Portfolio / Welcome) must show SIMULATED data when the
 * app is in explore mode, even though the broker query hooks return nothing.
 * Before this, those cards called the raw query hooks directly and rendered an
 * empty dashboard ("No open positions" / Net Worth "—") in a real demo session.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// Broker query hooks return NOTHING (a real demo session has no broker) — the
// cards must fall back to simulated data purely from the mode, not the query.
vi.mock("@/hooks/usePositions", () => ({ usePositions: () => ({ data: undefined, isLoading: false }) }));
vi.mock("@/hooks/useOrders", () => ({ useOrders: () => ({ data: undefined, isLoading: false }) }));
vi.mock("@/hooks/useFunds", () => ({ useFunds: () => ({ data: undefined }) }));
vi.mock("@/hooks/useHoldings", () => ({ useHoldings: () => ({ data: undefined }) }));
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: (sel: (s: { totalPnl: number }) => unknown) => sel({ totalPnl: 0 }),
}));
vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (sel: (s: { name: string }) => unknown) => sel({ name: "Tester" }),
}));

import { useModeStore } from "@/stores/modeStore";
import { PositionsCard } from "../PositionsCard";
import { OrdersCard } from "../OrdersCard";
import { PortfolioCard } from "../PortfolioCard";
import { WelcomeCard } from "../WelcomeCard";

function setMode(mode: "explore" | "live") {
  useModeStore.setState({ mode });
}

afterEach(() => setMode("live"));

describe("demo-mode dashboard cards", () => {
  it("PositionsCard shows simulated positions in explore mode", () => {
    setMode("explore");
    render(<PositionsCard />);
    expect(screen.queryByText("No open positions")).not.toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("OrdersCard shows simulated orders in explore mode", () => {
    setMode("explore");
    render(<OrdersCard />);
    expect(screen.queryByText("No recent orders")).not.toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });

  it("PortfolioCard shows a simulated net worth (not the empty dash) in explore mode", () => {
    setMode("explore");
    render(<PortfolioCard />);
    // Net worth renders "—" only when zero; demo holdings make it positive.
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("WelcomeCard shows the simulated open-position count in explore mode", () => {
    setMode("explore");
    render(<WelcomeCard />);
    // getMockPositions yields 5 positions, all non-zero quantity.
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("falls back to the empty state in live mode when the broker returns nothing", () => {
    setMode("live");
    render(<PositionsCard />);
    expect(screen.getByText("No open positions")).toBeInTheDocument();
    expect(screen.queryByText("RELIANCE")).not.toBeInTheDocument();
  });
});
