/**
 * HoldingsTab.test.tsx — Render tests for the holdings table tab.
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

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo mode</div>,
}));

vi.mock("@/lib/exportUtils", () => ({
  exportToCSV: vi.fn(),
  printCurrentView: vi.fn(),
}));

// Mock InvestContext with holdings data
vi.mock("../../InvestContext", () => ({
  useInvest: () => ({
    holdings: [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2520, pnl: 3500, pnlPercent: 2.86 },
      { symbol: "TCS", exchange: "NSE", quantity: 25, averagePrice: 3800, ltp: 3920, pnl: 3000, pnlPercent: 3.16 },
    ],
    summary: {
      currentValue: 224000,
      totalInvested: 217500,
      totalPnl: 6500,
      totalPnlPercent: 2.99,
      availableCash: 50000,
      sectorCount: 2,
      holdingCount: 2,
    },
    isLoading: false,
    isError: false,
    refetchHoldings: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { HoldingsTab } from "../HoldingsTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("HoldingsTab", () => {
  it("renders the holdings table with symbols", () => {
    render(<HoldingsTab />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
  });

  it("shows the stock count and toolbar buttons", () => {
    render(<HoldingsTab />);
    expect(screen.getByText("2 stocks")).toBeInTheDocument();
    expect(screen.getByText("Export CSV")).toBeInTheDocument();
    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });
});
