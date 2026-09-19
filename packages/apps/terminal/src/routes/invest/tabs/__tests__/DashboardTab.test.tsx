/**
 * DashboardTab.test.tsx — Render tests for the Invest dashboard overview.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { getDemoFunds, getDemoHoldings } from "@/hooks/useModeData";
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

vi.mock("@/lib/xirr", () => ({
  xirr: () => 0.15,
}));

vi.mock("@/components/magicui/animated-counter", () => ({
  AnimatedCounter: ({ value, formatter }: { value: number; formatter: (v: number) => string }) => (
    <span>{formatter(value)}</span>
  ),
}));

vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo mode</div>,
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
    sectorCount: 2,
    holdingCount: 2,
  },
  isLoading: false,
  isError: false,
  isSampleData: false,
  refetchHoldings: vi.fn(),
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { DashboardTab } from "../DashboardTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardTab", () => {
  beforeEach(() => {
    investState.holdings = LIVE_ROWS;
    investState.isLoading = false;
    investState.isError = false;
    investState.isSampleData = false;
    investState.summary = {
      currentValue: 170100,
      totalInvested: 167250,
      totalPnl: 2750,
      totalPnlPercent: 1.64,
      availableCash: 50000,
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
      sectorCount: 2,
      holdingCount: demo.length,
    };

    render(<DashboardTab />);

    expect(screen.getByText(formatCurrencyCompact(expectedNetWorth))).toBeInTheDocument();
    expect(screen.queryByText(formatCurrencyCompact(845_000))).not.toBeInTheDocument();
    expect(expectedNetWorth).not.toBe(845_000);
  });
});
