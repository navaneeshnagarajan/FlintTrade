/**
 * CorrelationTab.test.tsx — render tests for the correlation matrix tab.
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

vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => <div data-testid="demo-banner">Demo mode</div>,
}));

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
    // Return error=false, data=undefined → isDemo path (uses DEMO_MATRIX + regime)
    useQuery: vi.fn(() => ({
      data: undefined,
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    })),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { CorrelationTab } from "../CorrelationTab";
import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as unknown as ReturnType<typeof vi.fn>;

const NO_DATA = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };

const LIVE_MATRIX = {
  symbols: ["NIFTY50", "GOLD"],
  matrix: [[1.0, -0.18], [-0.18, 1.0]],
  regime: "Risk-On",
  regime_rationale: "Rolling 30-day index correlations",
  vix: 13.4,
  dxy: 101.2,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CorrelationTab", () => {
  beforeEach(() => {
    mockUseQuery.mockReturnValue(NO_DATA);
  });

  it("keeps the demo banner when the response omits is_sample_data", () => {
    // Provenance fails closed — an absent flag is sample, never live.
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: LIVE_MATRIX });
    render(<CorrelationTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("drops the demo banner only on an explicit is_sample_data: false", () => {
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { ...LIVE_MATRIX, is_sample_data: false } });
    render(<CorrelationTab />);
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });

  it("renders the section heading", () => {
    render(<CorrelationTab />);
    expect(screen.getByText("Correlation Matrix")).toBeInTheDocument();
  });

  it("shows demo banner when API is unavailable", () => {
    render(<CorrelationTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders the regime banner with Risk-On status and VIX/DXY badges", () => {
    render(<CorrelationTab />);
    // Regime status banner
    expect(screen.getByRole("status", { name: /market regime/i })).toBeInTheDocument();
    // VIX badge
    expect(screen.getByText(/VIX/)).toBeInTheDocument();
    // DXY badge
    expect(screen.getByText(/DXY/)).toBeInTheDocument();
  });

  it("renders the correlation matrix table", () => {
    render(<CorrelationTab />);
    expect(
      screen.getByRole("table", { name: /pairwise correlation/i }),
    ).toBeInTheDocument();
  });

  it("renders demo symbols as row and column headers", () => {
    render(<CorrelationTab />);
    expect(screen.getAllByText("NIFTY50").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("GOLD").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the interpretation guide", () => {
    render(<CorrelationTab />);
    expect(screen.getByText(/How to read this/i)).toBeInTheDocument();
  });
});
