/**
 * OverlapTab.test.tsx — Tests for portfolio overlap detection calculations and rendering.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import type { Holding } from "@/types/api";
import {
  computeOverlaps,
  computeSectorConcentration,
  computeConcentrationStats,
  resolveOverlapPresentation,
} from "../OverlapTab";
import { useModeStore } from "@/stores/modeStore";

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

const investState = vi.hoisted(() => ({
  holdings: [] as Holding[],
  isSampleData: false,
  hasAccountSnapshot: false,
}));

const publicDemo = vi.hoisted(() => ({ current: false }));

vi.mock("@/lib/demoSession", () => ({
  isPublicDemoBuild: () => publicDemo.current,
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
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

function row(symbol: string): Holding {
  return {
    symbol,
    exchange: "NSE",
    quantity: 1,
    averagePrice: 10,
    ltp: 10,
    pnl: 0,
    pnlPercent: 0,
  };
}

const EMPTY_COPY =
  "No holdings to compare yet. Overlap appears once you hold two or more funds or baskets.";

describe("resolveOverlapPresentation", () => {
  it("keeps Practice on the empty state with zero holdings even when the sample feed is on", () => {
    const presentation = resolveOverlapPresentation({
      mode: "practice",
      isPublicDemo: false,
      isSampleData: true,
      hasAccountSnapshot: false,
      holdings: [],
    });
    expect(presentation.kind).toBe("empty");
  });

  it("keeps Practice empty with one holding and opens the book at two", () => {
    expect(resolveOverlapPresentation({
      mode: "practice",
      isPublicDemo: false,
      isSampleData: false,
      hasAccountSnapshot: true,
      holdings: [row("SBIN")],
    }).kind).toBe("empty");

    const opened = resolveOverlapPresentation({
      mode: "practice",
      isPublicDemo: false,
      isSampleData: false,
      hasAccountSnapshot: true,
      holdings: [row("SBIN"), row("TCS")],
    });
    expect(opened.kind).toBe("book");
    if (opened.kind === "book") expect(opened.holdings).toHaveLength(2);
  });

  it("shows the sample book in the web demo and before an account snapshot", () => {
    const demo = resolveOverlapPresentation({
      mode: "live",
      isPublicDemo: true,
      isSampleData: false,
      hasAccountSnapshot: false,
      holdings: [],
    });
    expect(demo).toMatchObject({ kind: "sample", label: "demo" });

    const pending = resolveOverlapPresentation({
      mode: "live",
      isPublicDemo: false,
      isSampleData: true,
      hasAccountSnapshot: false,
      holdings: [],
    });
    expect(pending).toMatchObject({ kind: "sample", label: "example" });
  });

  it("does not key the sample book on Explore", () => {
    expect(resolveOverlapPresentation({
      mode: "explore",
      isPublicDemo: true,
      isSampleData: true,
      hasAccountSnapshot: false,
      holdings: [],
    })).toMatchObject({ kind: "sample", label: "demo" });

    expect(resolveOverlapPresentation({
      mode: "explore",
      isPublicDemo: false,
      isSampleData: true,
      hasAccountSnapshot: false,
      holdings: [],
    })).toMatchObject({ kind: "sample", label: "example" });

    expect(resolveOverlapPresentation({
      mode: "practice",
      isPublicDemo: true,
      isSampleData: true,
      hasAccountSnapshot: false,
      holdings: [],
    }).kind).toBe("empty");
  });
});

describe("OverlapTab rendering", () => {
  beforeEach(() => {
    investState.holdings = [];
    investState.isSampleData = false;
    investState.hasAccountSnapshot = false;
    publicDemo.current = false;
    useModeStore.setState({ mode: "live" });
  });

  it("renders with sample data when no live holdings", () => {
    render(<OverlapTab />);
    expect(screen.queryByText(/sample portfolio/i)).not.toBeInTheDocument();
    expect(screen.getByText("Stock Overlaps")).toBeInTheDocument();
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

  it("labels the sample overlap book Example", () => {
    render(<OverlapTab />);
    expect(screen.getByTestId("overlap-example")).toHaveTextContent("Example");
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument();
  });

  it("shows the empty state instead of the sample book when the account has no holdings", () => {
    investState.hasAccountSnapshot = true;
    investState.holdings = [];
    render(<OverlapTab />);

    expect(screen.getByTestId("overlap-empty")).toHaveTextContent(EMPTY_COPY);
    expect(screen.queryByText("HDFCBANK")).not.toBeInTheDocument();
    expect(screen.queryByText("Unique Stocks")).not.toBeInTheDocument();
    expect(screen.queryByText(/₹18,62,044/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("overlap-example")).not.toBeInTheDocument();
  });

  it("stays empty with one holding and opens at two", () => {
    investState.hasAccountSnapshot = true;
    investState.holdings = [row("SBIN")];
    const { unmount } = render(<OverlapTab />);
    expect(screen.getByTestId("overlap-empty")).toHaveTextContent(EMPTY_COPY);
    unmount();

    investState.holdings = [row("SBIN"), row("TCS")];
    render(<OverlapTab />);
    expect(screen.queryByTestId("overlap-empty")).not.toBeInTheDocument();
    expect(screen.getByText("2 total holdings")).toBeInTheDocument();
    expect(screen.queryByText("HDFCBANK")).not.toBeInTheDocument();
  });

  it("labels the web demo sample book and keeps Practice empty", () => {
    publicDemo.current = true;
    render(<OverlapTab />);
    expect(screen.getByTestId("overlap-demo-label")).toHaveTextContent("Demo (example data)");
    expect(screen.getByText("HDFCBANK")).toBeInTheDocument();
    expect(screen.queryByTestId("overlap-example")).not.toBeInTheDocument();
  });

  it("does not show the sample book in Practice when holdings are absent", () => {
    useModeStore.setState({ mode: "practice" });
    investState.isSampleData = true;
    investState.holdings = [row("ZZZ"), row("YYY"), row("XXX")];
    render(<OverlapTab />);

    expect(screen.getByTestId("overlap-empty")).toHaveTextContent(EMPTY_COPY);
    expect(screen.queryByText("ZZZ")).not.toBeInTheDocument();
    expect(screen.queryByText("HDFCBANK")).not.toBeInTheDocument();
    expect(screen.queryByTestId("overlap-demo-label")).not.toBeInTheDocument();
  });
});
