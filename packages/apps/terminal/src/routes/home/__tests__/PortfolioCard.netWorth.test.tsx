/**
 * Home net worth is cash + holdings + positions − estimated charges.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { accountNetWorth, markedValue } from "@/lib/accountNetWorth";
import type { Funds, Holding, Position } from "@/types/api";

const fundsQuery = vi.hoisted(() => ({
  data: undefined as Funds | undefined,
}));
const holdingsQuery = vi.hoisted(() => ({
  data: undefined as Holding[] | undefined,
}));
const positionsQuery = vi.hoisted(() => ({
  data: undefined as Position[] | undefined,
}));

vi.mock("@/hooks/useFunds", () => ({ useFunds: () => fundsQuery }));
vi.mock("@/hooks/useHoldings", () => ({ useHoldings: () => holdingsQuery }));
vi.mock("@/hooks/usePositions", () => ({ usePositions: () => positionsQuery }));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
}));

import { useModeStore } from "@/stores/modeStore";
import { PortfolioCard } from "../PortfolioCard";

afterEach(() => {
  fundsQuery.data = undefined;
  holdingsQuery.data = undefined;
  positionsQuery.data = undefined;
  useModeStore.setState({ mode: "live" });
});

describe("PortfolioCard net worth", () => {
  it("subtracts Practice charges from cash, holdings and positions", () => {
    const holdings: Holding[] = [
      {
        symbol: "SBIN",
        exchange: "NSE",
        quantity: 2,
        averagePrice: 100,
        ltp: 100,
        pnl: 0,
        pnlPercent: 0,
      },
    ];
    const positions: Position[] = [
      {
        symbol: "NIFTY-FUT",
        exchange: "NFO",
        product: "MIS",
        quantity: -3,
        averagePrice: 40,
        ltp: 40,
        pnl: 0,
        pnlPercent: 0,
      },
    ];
    const cash = 500;
    const charges = 17;
    fundsQuery.data = {
      availableCash: cash,
      usedMargin: 0,
      totalBalance: cash,
      estimatedCharges: charges,
    };
    holdingsQuery.data = holdings;
    positionsQuery.data = positions;
    useModeStore.setState({ mode: "practice" });

    render(<PortfolioCard />);

    const worth = Number(screen.getByTestId("portfolio-net-worth").getAttribute("data-value"));
    expect(worth).toBe(accountNetWorth(holdings, cash, positions, charges));
    expect(worth).toBe(markedValue(holdings) + markedValue(positions) + cash - charges);
    expect(screen.getByText("Net Worth (Cash + Holdings + Positions)")).toBeInTheDocument();
    expect(screen.getByText("Practice account, after estimated charges")).toBeInTheDocument();
  });
});