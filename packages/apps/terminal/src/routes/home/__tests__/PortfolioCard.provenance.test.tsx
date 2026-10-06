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
    ledgerBalance?: number;
    futuresMtmInLedger?: boolean;
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
    symbol?: string;
    exchange?: string;
    product?: string;
    ltp: number;
    quantity: number;
    averagePrice?: number;
    settlementPrice?: number;
    markSource?: "avg" | "fallback";
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

import {
  accountCharges,
  accountLedgerCash,
  accountNetWorth,
  accountNetWorthAccessibleName,
  approximateNetWorthTooltip,
  formatAccountNetWorth,
  NET_WORTH_POSITIONS_NOTE,
} from "@/lib/accountNetWorth";
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

const PRACTICE_FUNDS = {
  availableCash: 999_200,
  usedMargin: 800,
  totalBalance: 1_000_000,
  ledgerBalance: 1_000_000,
  futuresMtmInLedger: false,
};

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

    expect(screen.getByTestId("portfolio-net-worth")).toHaveAttribute("data-value", "1000000");
    expect(screen.queryByTestId("portfolio-net-worth-example")).not.toBeInTheDocument();
    expect(screen.queryByTestId("allocation-example-label")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Cash 100%");
    expect(screen.queryByText(/Equity 45%/)).not.toBeInTheDocument();
  });

  it("splits cash and the open position after a fill without dropping blocked margin", () => {
    const positions = [{
      symbol: "SBIN",
      exchange: "NSE",
      product: "MIS",
      ltp: 800,
      quantity: 1,
      averagePrice: 800,
      pnl: 0,
    }];
    const funds = { ...PRACTICE_FUNDS, ledgerBalance: 999_200 };
    setBook(fundsQuery, "success", funds);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "practice" });
    const charges = accountCharges(funds);
    const cash = accountLedgerCash(funds);
    const expected = accountNetWorth([], cash, positions, charges, funds.futuresMtmInLedger);
    render(<PortfolioCard />);

    expect(expected).toBe(1_000_000);
    expect(expected).not.toBe(funds.availableCash);
    expect(screen.getByTestId("portfolio-net-worth")).toHaveAttribute("data-value", String(expected));
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute(
      "title",
      NET_WORTH_POSITIONS_NOTE,
    );
    expect(screen.queryByTestId("allocation-example-label")).not.toBeInTheDocument();
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Cash 99.92%");
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("Positions 0.08%");
    expect(screen.getByTestId("portfolio-allocation")).not.toHaveTextContent("≈");
  });
});

const BROKER_FUNDS = {
  availableCash: 950_000,
  usedMargin: 50_000,
  totalBalance: 1_000_000,
  ledgerBalance: 1_000_000,
  futuresMtmInLedger: true,
};

function futurePosition(overrides: Record<string, unknown> = {}) {
  return {
    symbol: "NIFTY-JUN2026-FUT",
    exchange: "NFO",
    product: "NRML",
    ltp: 22_150,
    quantity: 50,
    averagePrice: 22_000,
    settlementPrice: 22_000,
    markSource: "fallback" as const,
    pnl: 0,
    ...overrides,
  };
}

describe("PortfolioCard approximate net worth", () => {
  it("shows ≈ for a Dhan future missing its average and names the symbol", () => {
    const positions = [futurePosition()];
    setBook(fundsQuery, "success", BROKER_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    const worth = accountNetWorth([], BROKER_FUNDS.ledgerBalance, positions, 0, true);
    render(<PortfolioCard />);

    const figure = screen.getByTestId("portfolio-net-worth");
    expect(figure).toHaveTextContent(formatAccountNetWorth(worth, true));
    expect(figure).toHaveAccessibleName(accountNetWorthAccessibleName(worth));
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute(
      "title",
      approximateNetWorthTooltip(["NIFTY-JUN2026-FUT"]) ?? "",
    );
    expect(screen.getByTestId("portfolio-allocation")).not.toHaveTextContent("≈");
    expect(screen.getByTestId("portfolio-allocation")).toHaveTextContent("%");
  });

  it("uses the count when two futures fall back", () => {
    const positions = [
      futurePosition(),
      futurePosition({ symbol: "BANKNIFTY-JUN2026-FUT" }),
    ];
    setBook(fundsQuery, "success", BROKER_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute(
      "title",
      "Approximate. Your broker didn't send an average price for 2 futures positions, so profit or loss from earlier days may be counted twice.",
    );
    expect(screen.getByTestId("portfolio-net-worth")).toHaveTextContent("≈");
    expect(screen.getByTestId("portfolio-allocation")).not.toHaveTextContent("≈");
  });

  it("shows ≈ for a Neo open-leg average", () => {
    const positions = [futurePosition({
      symbol: "NIFTY25JUNFUT",
      settlementPrice: undefined,
      averagePrice: 22_000,
      ltp: 22_100,
    })];
    setBook(fundsQuery, "success", BROKER_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).toHaveTextContent("≈");
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute(
      "title",
      approximateNetWorthTooltip([], ["NIFTY25JUNFUT"]) ?? "",
    );
  });

  it("shows no ≈ when the future has an average", () => {
    const positions = [futurePosition({ markSource: "avg", settlementPrice: 22_100 })];
    setBook(fundsQuery, "success", BROKER_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).not.toHaveTextContent("≈");
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute("title", NET_WORTH_POSITIONS_NOTE);
    expect(screen.getByTestId("portfolio-net-worth")).not.toHaveAttribute("aria-label");
  });

  it("clears ≈ when the fallback position goes flat or its average arrives", () => {
    const positions = [futurePosition()];
    setBook(fundsQuery, "success", BROKER_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    const { rerender } = render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).toHaveTextContent("≈");

    positionsQuery.data = [futurePosition({ quantity: 0, pnl: 1_950 })];
    rerender(<PortfolioCard />);
    expect(screen.getByTestId("portfolio-net-worth")).not.toHaveTextContent("≈");

    positionsQuery.data = [futurePosition({ markSource: "avg", settlementPrice: 22_100 })];
    rerender(<PortfolioCard />);
    expect(screen.getByTestId("portfolio-net-worth")).not.toHaveTextContent("≈");
    expect(screen.getByText("Net Worth").closest("p")).toHaveAttribute("title", NET_WORTH_POSITIONS_NOTE);
  });

  it("never shows ≈ for Practice", () => {
    const positions = [futurePosition({
      symbol: "NIFTY24APRFUT",
      markSource: undefined,
      settlementPrice: undefined,
      ltp: 1_100,
      quantity: 1,
      averagePrice: 1_000,
    })];
    setBook(fundsQuery, "success", PRACTICE_FUNDS);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "practice" });
    render(<PortfolioCard />);

    expect(screen.getByTestId("portfolio-net-worth")).not.toHaveTextContent("≈");
    expect(screen.getByTestId("portfolio-allocation")).not.toHaveTextContent("≈");
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

describe("PortfolioCard net worth waits for the position book", () => {
  const cashFunds = {
    ...BROKER_FUNDS,
    availableCash: 1_000_000,
    usedMargin: 0,
    ledgerBalance: 1_000_000,
  };

  it("shows a dash while positions are pending, then the approximate figure", () => {
    setBook(fundsQuery, "success", cashFunds);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "loading", undefined);
    useModeStore.setState({ mode: "live" });
    const view = render(<PortfolioCard />);

    const pending = screen.getByTestId("portfolio-net-worth");
    expect(pending).toHaveTextContent("—");
    expect(pending.textContent).not.toContain("10,00,000");
    expect(pending).not.toHaveAttribute("data-value");

    const positions = [futurePosition()];
    setBook(positionsQuery, "success", positions);
    const expected = accountNetWorth(
      [],
      accountLedgerCash(cashFunds),
      positions,
      accountCharges(cashFunds),
      cashFunds.futuresMtmInLedger,
    );
    view.rerender(<PortfolioCard />);

    const loaded = screen.getByTestId("portfolio-net-worth");
    expect(loaded).toHaveTextContent(formatAccountNetWorth(expected, true));
    expect(loaded.textContent).toContain("≈");
    expect(loaded.textContent).not.toContain("10,00,000");
  });

  it("shows a dash when the position book has failed", () => {
    setBook(fundsQuery, "success", cashFunds);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "error", undefined);
    positionsQuery.data = [futurePosition()];
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    const figure = screen.getByTestId("portfolio-net-worth");
    expect(figure).toHaveTextContent("—");
    expect(figure.textContent).not.toContain("10,00,000");
    expect(figure.textContent).not.toContain("≈");
    expect(figure).not.toHaveAttribute("data-value");
  });

  it("draws a negative net worth the same way Invest does", () => {
    const funds = {
      ...PRACTICE_FUNDS,
      availableCash: -50_000,
      usedMargin: 0,
      totalBalance: -50_000,
      ledgerBalance: -50_000,
    };
    setBook(fundsQuery, "success", funds);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", []);
    useModeStore.setState({ mode: "practice" });
    render(<PortfolioCard />);

    const figure = screen.getByTestId("portfolio-net-worth");
    expect(figure).toHaveTextContent("-₹50,000");
    expect(figure).not.toHaveAttribute("aria-label");
    expect(figure).toHaveAttribute("title", NET_WORTH_POSITIONS_NOTE);
  });

  it("keeps the approximate accessible name when net worth is negative", () => {
    const funds = { ...BROKER_FUNDS, ledgerBalance: -50_000, availableCash: -50_000 };
    const positions = [futurePosition({ ltp: 22_000, settlementPrice: 22_000 })];
    setBook(fundsQuery, "success", funds);
    setBook(holdingsQuery, "success", []);
    setBook(positionsQuery, "success", positions);
    useModeStore.setState({ mode: "live" });
    render(<PortfolioCard />);

    const figure = screen.getByTestId("portfolio-net-worth");
    expect(figure).toHaveTextContent(`≈ ${formatAccountNetWorth(-50_000)}`);
    expect(figure).toHaveTextContent("-₹50,000");
    expect(figure).toHaveAccessibleName(accountNetWorthAccessibleName(-50_000));
  });
});

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
