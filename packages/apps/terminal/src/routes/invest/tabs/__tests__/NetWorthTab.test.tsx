/**
 * NetWorthTab.test.tsx — Render tests for the net worth breakdown tab.
 */

import { describe, it, expect, vi } from "vitest";
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

vi.mock("@tremor/react", () => ({
  DonutChart: () => <div data-testid="donut-chart" />,
  BarList: () => <div data-testid="bar-list" />,
}));

vi.mock("@/hooks/useTremorTheme", () => ({
  useTremorTheme: () => ["blue", "emerald", "amber"],
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

// Mock InvestContext
vi.mock("../../InvestContext", () => ({
  useInvest: () => ({
    holdings: [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
    ],
    summary: {
      currentValue: 126000,
      totalInvested: 122500,
      totalPnl: 3500,
      totalPnlPercent: 2.86,
      availableCash: 50000,
      sectorCount: 1,
      holdingCount: 1,
    },
    isLoading: false,
    isError: false,
    refetchHoldings: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { NetWorthTab } from "../NetWorthTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NetWorthTab", () => {
  it("renders the net worth breakdown heading", () => {
    render(<NetWorthTab />);
    expect(screen.getByText("Net Worth Breakdown")).toBeInTheDocument();
    expect(screen.getByText("All Asset Classes")).toBeInTheDocument();
  });

  it("shows asset category cards including equity and cash", () => {
    render(<NetWorthTab />);
    // "Equity Holdings" appears in both the donut legend and the category cards
    expect(screen.getAllByText("Equity Holdings").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Available Cash").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Mutual Funds")).toBeInTheDocument();
    expect(screen.getByText("Gold")).toBeInTheDocument();
    expect(screen.getByText("Fixed Deposits")).toBeInTheDocument();
  });
});
