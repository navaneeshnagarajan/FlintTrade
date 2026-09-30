/**
 * DashboardTab.test.tsx — Render tests for the Invest dashboard overview.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { getDemoFunds, getDemoHoldings } from "@/hooks/useModeData";
import { accountNetWorth, accountNetWorthAccessibleName, formatAccountNetWorth, NET_WORTH_LABEL, NET_WORTH_POSITIONS_NOTE } from "@/lib/accountNetWorth";
import { useModeStore } from "@/stores/modeStore";
import { formatCurrencyCompact } from "@/lib/formatters";
import type { Holding } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: Object.assign(
    (selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        glass: { enabled: false, blur: 12, transparency: 20 },
        activeThemeId: "graphite",
        mode: "dark",
        customThemes: [],
        getActiveTheme: () => ({
          id: "graphite",
          name: "Graphite",
          dark: {
            colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
            glass: { blur: 12, minOpacity: 0.8 },
          },
          light: {
            colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" },
            glass: { blur: 12, minOpacity: 0.8 },
          },
        }),
        getResolvedMode: () => "dark",
      }),
    { getState: () => ({ glass: { enabled: false } }) },
  ),
}));

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({ value, formatter }: { value: number; formatter: (v: number) => string }) => (
    <span>{formatter(value)}</span>
  ),
}));

vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const LIVE_ROWS: Holding[] = [
  { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
  { symbol: "INFY", exchange: "NSE", quantity: 30, averagePrice: 1500, ltp: 1475, pnl: -750, pnlPercent: -1.67 },
];

const investState = vi.hoisted(() => ({
  holdings: [] as Holding[],
  summary: {
    currentValue: 170100,
    totalInvested: 167250,
    totalPnl: 2750,
    totalPnlPercent: 1.64,
    availableCash: 50000,
    netWorth: 220100,
    positionValue: 0,
    approximateNetWorth: false,
    fallbackSymbols: [] as string[],
    sectorCount: 2,
    holdingCount: 2,
  },
  isLoading: false,
  isError: false,
  isSampleData: false,
  positionBookReady: true,
  refetchHoldings: vi.fn(),
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { DashboardTab } from "../DashboardTab";
import { NetWorthTab } from "../NetWorthTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardTab", () => {
  beforeEach(() => {
    useModeStore.setState({ mode: "live" });
    investState.holdings = LIVE_ROWS;
    investState.isLoading = false;
    investState.isError = false;
    investState.isSampleData = false;
    investState.positionBookReady = true;
    investState.summary = {
      currentValue: 170100,
      totalInvested: 167250,
      totalPnl: 2750,
      totalPnlPercent: 1.64,
      availableCash: 50000,
      netWorth: 220100,
      positionValue: 0,
      approximateNetWorth: false,
      fallbackSymbols: [],
      sectorCount: 2,
      holdingCount: LIVE_ROWS.length,
    };
  });

  it("renders the net worth hero section", () => {
    render(<DashboardTab />);
    expect(screen.getByText(/Net Worth/)).toBeInTheDocument();
  });

  it("shows portfolio summary cards (funds, invested, P&L)", () => {
    render(<DashboardTab />);
    expect(screen.getByText("Available Funds")).toBeInTheDocument();
    expect(screen.getByText("Invested Value")).toBeInTheDocument();
    expect(screen.getByText("Portfolio Allocation")).toBeInTheDocument();
  });

  it("renders allocation through Flint primitives", () => {
    render(<DashboardTab />);

    expect(screen.getByRole("img", { name: "Portfolio allocation donut" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Portfolio allocation values" })).toBeInTheDocument();
  });

  it("derives sample net worth from the shared getDemoHoldings book, not a mismatched constant", () => {
    const demo = getDemoHoldings();
    const availableCash = getDemoFunds().availableCash;
    const currentValue = demo.reduce((acc, h) => acc + h.ltp * h.quantity, 0);
    const totalInvested = demo.reduce((acc, h) => acc + h.averagePrice * h.quantity, 0);
    const totalPnl = demo.reduce((acc, h) => acc + h.pnl, 0);
    const expectedNetWorth = currentValue + availableCash;

    investState.holdings = demo;
    investState.isSampleData = true;
    investState.summary = {
      currentValue,
      totalInvested,
      totalPnl,
      totalPnlPercent: totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0,
      availableCash,
      netWorth: expectedNetWorth,
      positionValue: 0,
      approximateNetWorth: false,
      fallbackSymbols: [],
      sectorCount: 2,
      holdingCount: demo.length,
    };

    render(<DashboardTab />);

    expect(screen.getByText(formatAccountNetWorth(expectedNetWorth))).toBeInTheDocument();
    expect(screen.getByTestId("invest-net-worth")).toHaveAttribute("data-value", String(expectedNetWorth));
    expect(screen.queryByText("Portfolio XIRR")).not.toBeInTheDocument();
    expect(screen.queryByText(formatCurrencyCompact(845_000))).not.toBeInTheDocument();
    expect(expectedNetWorth).not.toBe(845_000);
  });

  it("shows one practice net worth and does not label that figure Example", () => {
    const practiceCash = 999_200;
    const demoNetWorth = accountNetWorth(getDemoHoldings(), getDemoFunds().availableCash);

    investState.holdings = [];
    investState.isSampleData = false;
    investState.summary = {
      currentValue: 0,
      totalInvested: 0,
      totalPnl: 0,
      totalPnlPercent: 0,
      availableCash: practiceCash,
      netWorth: practiceCash,
      positionValue: 0,
      approximateNetWorth: false,
      fallbackSymbols: [],
      sectorCount: 0,
      holdingCount: 0,
    };

    render(<DashboardTab />);

    expect(screen.getByTestId("invest-net-worth")).toHaveAttribute("data-value", String(practiceCash));
    expect(within(screen.getByTestId("invest-net-worth")).getByText(formatAccountNetWorth(practiceCash))).toBeInTheDocument();
    expect(screen.queryByTestId("invest-net-worth-example")).not.toBeInTheDocument();
    expect(screen.queryByText(formatCurrencyCompact(demoNetWorth))).not.toBeInTheDocument();
    expect(screen.queryByText(formatAccountNetWorth(demoNetWorth))).not.toBeInTheDocument();
    expect(demoNetWorth).not.toBe(practiceCash);
    expect(screen.getByText(NET_WORTH_LABEL)).toBeInTheDocument();
    expect(screen.getByText(NET_WORTH_LABEL).closest("p")).toHaveAttribute("title", NET_WORTH_POSITIONS_NOTE);
    expect(screen.getByTestId("invest-available-funds")).toHaveTextContent(formatAccountNetWorth(practiceCash));
    expect(screen.queryByText("Portfolio XIRR")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sample-xirr")).not.toBeInTheDocument();
    expect(screen.queryByText(/XIRR -0\.00%/)).not.toBeInTheDocument();
  });

  it("does not publish net worth until the position book is ready", () => {
    investState.positionBookReady = false;
    investState.summary = { ...investState.summary, netWorth: 999_200 };

    render(<DashboardTab />);

    expect(screen.getByTestId("invest-net-worth")).toHaveTextContent("—");
    expect(screen.getByTestId("invest-net-worth")).not.toHaveAttribute("data-value");
    expect(screen.queryByText(formatAccountNetWorth(999_200))).not.toBeInTheDocument();
    expect(screen.getByText(NET_WORTH_LABEL).closest("p")).toHaveAttribute("title", NET_WORTH_POSITIONS_NOTE);
  });

  it("does not add an Example chip or a Portfolio XIRR card when the book is not sample data", () => {
    render(<DashboardTab />);

    expect(screen.queryByText("Portfolio XIRR")).not.toBeInTheDocument();
    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
  });

  it("uses the connected-book allocation sentence when the figures are not sample data", () => {
    useModeStore.setState({ mode: "practice" });
    investState.holdings = [];
    investState.isSampleData = false;
    investState.summary = {
      ...investState.summary,
      currentValue: 0,
      totalInvested: 0,
      totalPnl: 0,
      totalPnlPercent: 0,
      availableCash: 999_200,
      netWorth: 999_200,
      holdingCount: 0,
    };

    render(<DashboardTab />);

    expect(screen.getByText(
      "Equity + Cash from your connected broker. Debt / MF requires NAV data source.",
    )).toBeInTheDocument();
    expect(screen.getByText("Connect a broker to see movers.")).toBeInTheDocument();
    expect(screen.queryByText(/Practice account/)).not.toBeInTheDocument();
  });

  it("marks the total row approximate and leaves allocation unmarked", () => {
    investState.summary = {
      ...investState.summary,
      netWorth: 452_300,
      positionValue: 2_500,
      approximateNetWorth: true,
      fallbackSymbols: ["NIFTY-JUN2026-FUT"],
    };

    render(<DashboardTab />);

    expect(screen.getByText(NET_WORTH_LABEL).closest("p")).toHaveAttribute(
      "title",
      "Approximate. Your broker didn't send an average price for NIFTY-JUN2026-FUT, so profit or loss from earlier days may be counted twice.",
    );
    expect(screen.getByTestId("invest-net-worth")).toHaveTextContent(formatAccountNetWorth(452_300, true));
    expect(screen.getByTestId("invest-net-worth")).toHaveAccessibleName(accountNetWorthAccessibleName(452_300));
    expect(screen.getByRole("list", { name: "Portfolio allocation values" })).not.toHaveTextContent("≈");
  });

  it("labels the sample XIRR with one Example chip and no sample banner in Explore", () => {
    useModeStore.setState({ mode: "explore" });
    investState.isSampleData = true;
    render(<DashboardTab />);

    expect(screen.queryByText(/Showing sample data/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Example data. Connect a broker to see your own.")).not.toBeInTheDocument();
    const xirr = screen.getByTestId("sample-xirr");
    expect(xirr).toHaveTextContent("XIRR +17.44%");
    expect(within(xirr).getAllByTestId("example-chip")).toHaveLength(1);
    expect(within(xirr).getByTestId("example-chip")).toHaveTextContent("Example");
    expect(screen.queryByText("Portfolio XIRR")).not.toBeInTheDocument();
  });

  it("does not mark Practice XIRR as Example", () => {
    useModeStore.setState({ mode: "practice" });
    investState.isSampleData = true;
    render(<DashboardTab />);

    expect(screen.queryByText(/Showing sample data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("example-chip")).not.toBeInTheDocument();
    expect(screen.getByTestId("sample-xirr")).toHaveTextContent("XIRR +17.44%");
  });

  it("shows no Live wording on sample Dashboard and Net Worth figures", () => {
    useModeStore.setState({ mode: "explore" });
    investState.isSampleData = true;
    investState.holdings = LIVE_ROWS;
    render(
      <>
        <DashboardTab />
        <NetWorthTab />
      </>,
    );

    for (const regionId of ["dashboard-figures", "net-worth-figures"]) {
      const region = screen.getByTestId(regionId);
      expect(region.textContent ?? "").not.toMatch(/\blive\b/i);
    }
    expect(screen.getByText("Example equity and cash. Connect a broker to see yours.")).toBeInTheDocument();
    expect(screen.queryByText("Allocation (live assets only)")).not.toBeInTheDocument();
    expect(screen.queryByText("Live from broker")).not.toBeInTheDocument();
    expect(screen.queryByText("Portfolio XIRR")).not.toBeInTheDocument();
  });

  it("keeps live broker wording when the figures are not sample data", () => {
    useModeStore.setState({ mode: "practice" });
    investState.isSampleData = false;
    investState.holdings = LIVE_ROWS;
    render(
      <>
        <DashboardTab />
        <NetWorthTab />
      </>,
    );

    expect(screen.getByText(
      "Live equity and cash from your connected broker. Other asset classes require additional data sources.",
    )).toBeInTheDocument();
    expect(screen.getByText("Allocation (live assets only)")).toBeInTheDocument();
    expect(screen.getAllByText("Live from broker").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(
      "Equity + Cash from your connected broker. Debt / MF requires NAV data source.",
    )).toBeInTheDocument();
    expect(screen.queryByText("Example equity and cash. Connect a broker to see yours.")).not.toBeInTheDocument();
  });
});

afterEach(() => {
  useModeStore.setState({ mode: "explore" });
});
