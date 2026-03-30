/**
 * OverlapTab.test.tsx — Tests for portfolio overlap detection calculations and rendering.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { Holding } from "@/types/api";
import {
  computeOverlaps,
  computeSectorConcentration,
  computeConcentrationStats,
} from "../OverlapTab";

// ─── Pure calculation tests ─────────────────────────────────────────────────────

describe("computeOverlaps", () => {
  it("detects stocks appearing multiple times", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2900, pnl: 22500, pnlPercent: 18.4 },
      { symbol: "RELIANCE", exchange: "NSE", quantity: 30, averagePrice: 2600, ltp: 2900, pnl: 9000, pnlPercent: 11.5 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1500, ltp: 1680, pnl: 18000, pnlPercent: 12.0 },
    ];

    const overlaps = computeOverlaps(holdings);
    expect(overlaps).toHaveLength(1);
    expect(overlaps[0].symbol).toBe("RELIANCE");
    expect(overlaps[0].occurrences).toBe(2);
    expect(overlaps[0].totalQuantity).toBe(80);
  });

  it("returns empty array when no overlaps exist", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 2900, pnl: 22500, pnlPercent: 18.4 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1500, ltp: 1680, pnl: 18000, pnlPercent: 12.0 },
    ];

    const overlaps = computeOverlaps(holdings);
    expect(overlaps).toHaveLength(0);
  });

  it("calculates portfolio percentage correctly", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 100, averagePrice: 2450, ltp: 1000, pnl: -145000, pnlPercent: -59.2 },
      { symbol: "RELIANCE", exchange: "NSE", quantity: 100, averagePrice: 2600, ltp: 1000, pnl: -160000, pnlPercent: -61.5 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1500, ltp: 1000, pnl: -50000, pnlPercent: -33.3 },
    ];

    const overlaps = computeOverlaps(holdings);
    // RELIANCE: 200 * 1000 = 200000, total = 300000, so ~66.67%
    expect(overlaps[0].portfolioPercent).toBeCloseTo(66.67, 1);
  });
});

describe("computeSectorConcentration", () => {
  it("groups holdings by sector", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 100, averagePrice: 2450, ltp: 3000, pnl: 55000, pnlPercent: 22.4 },
      { symbol: "ONGC", exchange: "NSE", quantity: 200, averagePrice: 250, ltp: 260, pnl: 2000, pnlPercent: 4.0 },
      { symbol: "INFY", exchange: "NSE", quantity: 50, averagePrice: 1600, ltp: 1800, pnl: 10000, pnlPercent: 12.5 },
    ];

    const sectors = computeSectorConcentration(holdings);
    expect(sectors.length).toBeGreaterThanOrEqual(2);

    const energySector = sectors.find((s) => s.sector === "Energy");
    expect(energySector).toBeDefined();
    expect(energySector!.stockCount).toBe(2);
  });

  it("flags sectors above 30% as risky", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 1000, averagePrice: 2450, ltp: 3000, pnl: 550000, pnlPercent: 22.4 },
      { symbol: "INFY", exchange: "NSE", quantity: 10, averagePrice: 1600, ltp: 1800, pnl: 2000, pnlPercent: 12.5 },
    ];

    const sectors = computeSectorConcentration(holdings);
    const energySector = sectors.find((s) => s.sector === "Energy");
    expect(energySector).toBeDefined();
    expect(energySector!.isRisky).toBe(true);
  });
});

describe("computeConcentrationStats", () => {
  it("calculates top 10 concentration", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 100, averagePrice: 2450, ltp: 1000, pnl: -145000, pnlPercent: -59.2 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1500, ltp: 500, pnl: -100000, pnlPercent: -66.7 },
    ];

    const stats = computeConcentrationStats(holdings);
    expect(stats.uniqueStocks).toBe(2);
    expect(stats.totalHoldings).toBe(2);
    // All stocks are in top 10 since only 2 stocks
    expect(stats.top10Percent).toBeCloseTo(100, 0);
  });

  it("aggregates duplicate symbols before ranking", () => {
    const holdings: Holding[] = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2450, ltp: 1000, pnl: -72500, pnlPercent: -59.2 },
      { symbol: "RELIANCE", exchange: "NSE", quantity: 50, averagePrice: 2600, ltp: 1000, pnl: -80000, pnlPercent: -61.5 },
      { symbol: "HDFCBANK", exchange: "NSE", quantity: 100, averagePrice: 1500, ltp: 500, pnl: -100000, pnlPercent: -66.7 },
    ];

    const stats = computeConcentrationStats(holdings);
    // 2 unique stocks, 3 total holdings
    expect(stats.uniqueStocks).toBe(2);
    expect(stats.totalHoldings).toBe(3);
  });
});

// ─── Render tests ───────────────────────────────────────────────────────────────

// Mock InvestContext
vi.mock("../../InvestContext", () => ({
  useInvest: vi.fn().mockReturnValue({
    holdings: [],
    summary: {
      currentValue: 0,
      totalInvested: 0,
      totalPnl: 0,
      totalPnlPercent: 0,
      availableCash: 0,
      sectorCount: 0,
      holdingCount: 0,
    },
    isLoading: false,
    isError: false,
    refetchHoldings: vi.fn(),
  }),
}));

// Mock themeStore for GlassCard
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

import { OverlapTab } from "../OverlapTab";

describe("OverlapTab rendering", () => {
  it("renders with sample data when no live holdings", () => {
    render(<OverlapTab />);
    // Should show sample data notice
    expect(screen.getByText(/sample portfolio/i)).toBeInTheDocument();
  });

  it("shows overlap section with sample data", () => {
    render(<OverlapTab />);
    expect(screen.getByText("Stock Overlaps")).toBeInTheDocument();
    // RELIANCE should show as overlapping (3x in sample data)
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("shows sector concentration section", () => {
    render(<OverlapTab />);
    expect(screen.getByText("Sector Concentration")).toBeInTheDocument();
  });

  it("shows summary stat cards", () => {
    render(<OverlapTab />);
    expect(screen.getByText("Unique Stocks")).toBeInTheDocument();
    expect(screen.getByText("Top 10 Concentration")).toBeInTheDocument();
    expect(screen.getByText("Overlapping Stocks")).toBeInTheDocument();
    expect(screen.getByText("Sector Risk")).toBeInTheDocument();
  });
});
