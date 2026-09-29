/**
 * BenchmarkTab.test.tsx — Render tests for the Benchmark Comparison tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock themeStore — GlassCard reads glass.enabled and activeThemeId
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

// Mock cinematicThemes
vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

// Mock GlossaryTooltip — render children without tooltip wrapper
vi.mock("@/components/ui/GlossaryTooltip", () => ({
  GlossaryTooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const investState = vi.hoisted(() => ({
  holdings: [] as {
    symbol: string;
    averagePrice: number;
    quantity: number;
    pnl: number;
  }[],
  isSampleData: false,
}));

vi.mock("../../InvestContext", () => ({
  useInvest: () => investState,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { BenchmarkTab, portfolioBookReturn } from "../BenchmarkTab";

function holding(pnl: number, averagePrice = 100, quantity = 2) {
  return { symbol: "SBIN", averagePrice, quantity, pnl };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BenchmarkTab", () => {
  beforeEach(() => {
    investState.holdings = [holding(50)];
    investState.isSampleData = false;
    vi.clearAllMocks();
  });

  it("renders the Benchmark Comparison heading", () => {
    render(<BenchmarkTab />);
    expect(screen.getByText("Benchmark Comparison")).toBeInTheDocument();
  });

  it("shows the book return without a chip and keeps the chip on sample index rows", () => {
    const rows = [holding(50)];
    investState.holdings = rows;
    render(<BenchmarkTab />);

    const portfolio = screen.getByTestId("benchmark-portfolio-row");
    const expected = portfolioBookReturn(rows);
    expect(expected).toBe((50 / (100 * 2)) * 100);
    expect(within(portfolio).getByTestId("benchmark-portfolio-return")).toHaveTextContent(
      "+25.00%",
    );
    expect(within(portfolio).getByText("Your Portfolio (since first buy)")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: "Your Portfolio (since first buy)" })).toBe(portfolio);
    expect(within(portfolio).queryByText("Example")).not.toBeInTheDocument();
    expect(screen.queryByText(/Showing sample data/)).not.toBeInTheDocument();

    expect(screen.getAllByTestId("benchmark-row-example")).toHaveLength(5);
    for (const name of ["NIFTY 50", "NIFTY Next 50", "NIFTY Midcap 150", "SENSEX", "NIFTY Bank"]) {
      const indexRow = screen.getByText(name).closest("tr");
      expect(indexRow).not.toBeNull();
      expect(within(indexRow as HTMLElement).getByTestId("benchmark-row-example")).toHaveTextContent(
        "Example",
      );
    }

    expect(screen.queryByText("Benchmarks Beaten (1Y)")).not.toBeInTheDocument();
    expect(screen.queryByText("Best 1Y Alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("Worst 1Y Alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("Alpha")).not.toBeInTheDocument();
    expect(screen.queryByText(/Portfolio - Benchmark/)).not.toBeInTheDocument();
    expect(screen.queryByText("indices outperformed")).not.toBeInTheDocument();
    expect(screen.queryByText("+18.45%")).not.toBeInTheDocument();
    expect(screen.queryByText("4/5")).not.toBeInTheDocument();
    expect(screen.getByTestId("benchmark-comparison-note")).toHaveTextContent(
      "Comparison needs real index data.",
    );
    expect(screen.queryByTestId("benchmark-empty-note")).not.toBeInTheDocument();
  });

  it("shows the portfolio row", () => {
    render(<BenchmarkTab />);
    expect(screen.getByRole("row", { name: "Your Portfolio (since first buy)" })).toBeInTheDocument();
  });

  it("renders all five benchmark indices", () => {
    render(<BenchmarkTab />);
    expect(screen.getAllByText("NIFTY 50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Next 50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Midcap 150").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("SENSEX").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Bank").length).toBeGreaterThanOrEqual(1);
  });

  it("shows all time period columns", () => {
    render(<BenchmarkTab />);
    for (const period of ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]) {
      expect(screen.getAllByText(period).length).toBeGreaterThanOrEqual(1);
    }
  });

  it("shows benchmark lines only when the account has no holdings", () => {
    investState.holdings = [];
    render(<BenchmarkTab />);

    const portfolio = screen.getByTestId("benchmark-portfolio-row");
    expect(screen.getByText("NIFTY 50")).toBeInTheDocument();
    expect(within(portfolio).getByText("Your Portfolio")).toBeInTheDocument();
    expect(within(portfolio).queryByText(/since first buy/)).not.toBeInTheDocument();
    expect(screen.getByRole("row", { name: "Your Portfolio" })).toBe(portfolio);
    expect(within(portfolio).queryByTestId("benchmark-portfolio-return")).not.toBeInTheDocument();
    expect(within(portfolio).getAllByText("—").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId("benchmark-empty-note")).toHaveTextContent(
      "Add holdings to compare against benchmarks.",
    );
    expect(screen.queryByTestId("benchmark-comparison-note")).not.toBeInTheDocument();
    expect(screen.queryByText("+18.45%")).not.toBeInTheDocument();
    expect(screen.queryByText("Benchmarks Beaten (1Y)")).not.toBeInTheDocument();
    expect(screen.queryByText("4/5")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("benchmark-row-example")).toHaveLength(5);
  });

  it("renders the disclaimer", () => {
    render(<BenchmarkTab />);
    expect(
      screen.getByText(/Benchmark data is illustrative/),
    ).toBeInTheDocument();
  });
});
