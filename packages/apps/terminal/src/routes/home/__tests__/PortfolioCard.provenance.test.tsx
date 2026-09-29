/**
 * PortfolioCard — the 45/30/10/15 mix is an example until an account snapshot
 * exists. Practice then shows cash, holdings, and open positions.
 */
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

type BookStatus = "loading" | "error" | "success";

interface BookQuery<T> {
  data: T | undefined;
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
}

const fundsQuery = vi.hoisted(() => ({
  data: undefined as {
    availableCash: number;
    usedMargin: number;
    totalBalance: number;
  } | undefined,
  isLoading: false,
  isError: false,
  isSuccess: false,
}));

const holdingsQuery = vi.hoisted(() => ({
  data: undefined as { ltp: number; quantity: number }[] | undefined,
  isLoading: false,
  isError: false,
  isSuccess: false,
}));

const positionsQuery = vi.hoisted(() => ({
  data: undefined as {
    ltp: number;
    quantity: number;
    averagePrice?: number;
    pnl?: number;
  }[] | undefined,
  isLoading: false,
  isError: false,
  isSuccess: false,
}));

vi.mock("@/hooks/useFunds", () => ({ useFunds: () => fundsQuery }));
vi.mock("@/hooks/useHoldings", () => ({ useHoldings: () => holdingsQuery }));
vi.mock("@/hooks/usePositions", () => ({ usePositions: () => positionsQuery }));
vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
}));

import { accountCharges, accountNetWorth, markedValue, positionsUnrealisedPnl } from "@/lib/accountNetWorth";
import { useModeStore } from "@/stores/modeStore";
import { PortfolioCard } from "../PortfolioCard";

function setBook<T>(query: BookQuery<T>, status: BookStatus, data: T | undefined) {
  query.isLoading = status === "loading";
  query.isError = status === "error";
  query.isSuccess = status === "success";
  query.data = status === "success" ? data : undefined;
}

function resetBooks() {
  setBook(fundsQuery, "loading", undefined);
  setBook(holdingsQuery, "loading", undefined);
  setBook(positionsQuery, "loading", undefined);
  fundsQuery.isLoading = false;
  holdingsQuery.isLoading = false;
  positionsQuery.isLoading = false;
}

const PRACTICE_FUNDS = { availableCash: 999_200, usedMargin: 800, totalBalance: 1_000_000 };

afterEach(() => {
  resetBooks();
  useModeStore.setState({ mode: "live" });
});

describe("PortfolioCard allocation provenance (Slice 3)", () => {
  it("Allocation heading has inline visible Sample badge with data-provenance=Sample", () => {
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByText("Allocation")).toBeInTheDocument();
    expect(screen.getByTestId("allocation-example-label")).toHaveTextContent("Example");
    expect(screen.queryByText("Sample")).not.toBeInTheDocument();
    expect(screen.queryByTestId("portfolio-net-worth-example")).not.toBeInTheDocument();
  });

  it("uses the practice cash balance as the only net worth figure", () => {
    setBook(fundsQuery, "success", PRACTICE_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", []);
    useModeStore.setState({ mode: "practice" });
    render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).toHaveAttribute("data-value", "999200");
    expect(screen.queryByTestId("portfolio-net-worth-example")).not.toBeInTheDocument();
    expect(screen.queryByTestId("allocation-example-label")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Cash 100%");
    expect(screen.queryByText(/Equity 45%/)).not.toBeInTheDocument();
  });

  it("splits cash and the open position after a fill without adding flat notional to net worth", () => {
    const positions = [{ ltp: 800, quantity: 1, averagePrice: 800, pnl: 0 }];
    setBook(fundsQuery, "success", PRACTICE_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "practice" });
    const charges = accountCharges(PRACTICE_FUNDS);
    const expected = accountNetWorth([], PRACTICE_FUNDS.availableCash, positions, charges);
    render(<PortfolioCard />);

    expect(positionsUnrealisedPnl(positions)).toBe(0);
    expect(expected).toBe(PRACTICE_FUNDS.availableCash - charges);
    expect(expected).not.toBe(markedValue(positions) + PRACTICE_FUNDS.availableCash - charges);
    expect(screen.getByTestId("portfolio-net-worth")).toHaveAttribute("data-value", String(expected));
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute(
      "title",
      "Positions count at unrealised P&L.",
    );
    expect(screen.queryByTestId("allocation-example-label")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Cash 99.92%");
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Positions 0.08%");
  });
});

const BOOK_STATUSES = ["loading", "error", "success"] as const;

function allocationCases(): { funds: BookStatus; holdings: BookStatus; positions: BookStatus }[] {
  const cases: { funds: BookStatus; holdings: BookStatus; positions: BookStatus }[] = [];
  for (const funds of BOOK_STATUSES) {
    for (const holdings of BOOK_STATUSES) {
      for (const positions of BOOK_STATUSES) {
        if (funds === "success" && holdings === "success" && positions === "success") continue;
        cases.push({ funds, holdings, positions });
      }
    }
  }
  return cases;
}

describe("PortfolioCard allocation stays provisional", () => {
  it.each(allocationCases())(
    "while funds is $funds, holdings is $holdings, and positions is $positions",
    ({ funds, holdings, positions }) => {
      setBook(fundsQuery, funds, PRACTICE_FUNDS);
      setBook(holdingsQuery, holdings, []);
      setBook(positionsQuery, positions, [{ ltp: 800, quantity: 1, averagePrice: 800 }]);
      useModeStore.setState({ mode: "live" });
      render(<PortfolioCard />);

      expect(screen.getByTestId("allocation-example-label")).toBeInTheDocument();
      expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Equity 45%");
      expect(screen.queryByText("Cash 100%")).not.toBeInTheDocument();
    },
  );

  it("shows the account split only after funds, holdings, and positions succeed", () => {
    setBook(fundsQuery, "success", PRACTICE_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", []);
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.queryByTestId("allocation-example-label")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Cash 100%");
    expect(screen.queryByText(/Equity 45%/)).not.toBeInTheDocument();
  });
});
