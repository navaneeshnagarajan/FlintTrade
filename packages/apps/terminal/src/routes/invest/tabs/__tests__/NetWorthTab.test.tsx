/**
 * NetWorthTab.test.tsx — Render tests for the net worth breakdown tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

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
          dark: { colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" }, glass: { blur: 12, minOpacity: 0.8 } },
          light: { colors: { card: "#ffffff", border: "#e5e7eb", cardHover: "#f9fafb" }, glass: { blur: 12, minOpacity: 0.8 } },
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

vi.mock("@/components/motion/StaggeredList", () => ({
  StaggeredList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

// DisabledActionButton
vi.mock("../../DisabledActionButton", () => ({
  DisabledActionButton: ({ label }: { label: string }) => (
    <button disabled>{label}</button>
  ),
}));

const investState = vi.hoisted(() => ({
  holdings: [
    { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
  ],
  summary: {
    currentValue: 126000,
    totalInvested: 122500,
    totalPnl: 3500,
    totalPnlPercent: 2.86,
    availableCash: 50000,
    positionValue: 0,
    netWorth: 176000,
    approximateNetWorth: false,
    fallbackSymbols: [] as string[],
    sectorCount: 1,
    holdingCount: 1,
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

import { formatAccountNetWorth } from "@/lib/accountNetWorth";
import { NetWorthTab } from "../NetWorthTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NetWorthTab", () => {
  beforeEach(() => {
    investState.summary.positionValue = 0;
    investState.summary.approximateNetWorth = false;
    investState.summary.fallbackSymbols = [];
    investState.summary.netWorth = 176000;
    investState.isLoading = false;
    investState.positionBookReady = true;
  });

  it("renders the net worth breakdown heading", () => {
    render(<NetWorthTab />);
    expect(screen.getByText("Net Worth Breakdown")).toBeInTheDocument();
    expect(screen.getByText("All Asset Classes")).toBeInTheDocument();
  });

  it("shows asset category cards including equity and cash", () => {
    render(<NetWorthTab />);
    // "Equity Holdings" appears in both the donut legend and the category cards
    expect(screen.getAllByText("Equity Holdings").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Cash").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Mutual Funds")).toBeInTheDocument();
    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(screen.getByText("Fixed Deposits")).toBeInTheDocument();
  });

  it("renders live asset visuals through Flint primitives", () => {
    render(<NetWorthTab />);

    expect(screen.getByRole("img", { name: "Live asset allocation donut" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Invested versus current values" })).toBeInTheDocument();
  });

  it("marks the positions line and the total approximate", () => {
    investState.summary.positionValue = 2_500;
    investState.summary.netWorth = 452_300;
    investState.summary.approximateNetWorth = true;
    investState.summary.fallbackSymbols = ["NIFTY25JUNFUT"];

    render(<NetWorthTab />);

    const tooltip = "Approximate. Your broker didn't send an average price for NIFTY25JUNFUT, so profit or loss from earlier days may be counted twice.";
    expect(screen.getByText("Known Total (Cash + Holdings + Positions)").closest("div")).toHaveAttribute("title", tooltip);
    expect(screen.getByTestId("net-worth-known-total")).toHaveTextContent(formatAccountNetWorth(452_300, true));
    expect(screen.getByTestId("net-worth-open-positions")).toHaveTextContent(formatAccountNetWorth(2_500, true));
    expect(screen.getByTestId("net-worth-open-positions")).toHaveAttribute("title", tooltip);
    expect(screen.getByTestId("net-worth-known-total")).toHaveAccessibleName(
      `Net Worth, approximately ${formatAccountNetWorth(452_300)}`,
    );
  });
});
