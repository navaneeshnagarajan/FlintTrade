/**
 * BenchmarkTab.test.tsx — Render tests for the Benchmark Comparison tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

// Mock DemoBanner
vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo Mode</div>,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { BenchmarkTab } from "../BenchmarkTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("BenchmarkTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the Benchmark Comparison heading", () => {
    render(<BenchmarkTab />);
    expect(screen.getByText("Benchmark Comparison")).toBeInTheDocument();
  });

  it("renders the demo banner", () => {
    render(<BenchmarkTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("shows the portfolio row", () => {
    render(<BenchmarkTab />);
    expect(screen.getByText("Your Portfolio")).toBeInTheDocument();
  });

  it("renders all five benchmark indices", () => {
    render(<BenchmarkTab />);
    expect(screen.getAllByText("NIFTY 50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Next 50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Midcap 150").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("SENSEX").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("NIFTY Bank").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the alpha section", () => {
    render(<BenchmarkTab />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("(Portfolio - Benchmark)")).toBeInTheDocument();
  });

  it("shows all time period columns", () => {
    render(<BenchmarkTab />);
    // Each period appears in both the returns table and the alpha table headers
    for (const period of ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]) {
      expect(screen.getAllByText(period).length).toBeGreaterThanOrEqual(2);
    }
  });

  it("renders summary cards", () => {
    render(<BenchmarkTab />);
    expect(screen.getByText("Best 1Y Alpha")).toBeInTheDocument();
    expect(screen.getByText("Worst 1Y Alpha")).toBeInTheDocument();
    expect(screen.getByText("Benchmarks Beaten (1Y)")).toBeInTheDocument();
  });

  it("shows benchmarks beaten count and outperformance label", () => {
    render(<BenchmarkTab />);
    // Portfolio 1Y = 18.45%, beats all 5 benchmarks
    expect(screen.getByText("Benchmarks Beaten (1Y)")).toBeInTheDocument();
    expect(screen.getByText("indices outperformed")).toBeInTheDocument();
  });

  it("renders the disclaimer", () => {
    render(<BenchmarkTab />);
    expect(
      screen.getByText(/Benchmark data is illustrative/),
    ).toBeInTheDocument();
  });
});
