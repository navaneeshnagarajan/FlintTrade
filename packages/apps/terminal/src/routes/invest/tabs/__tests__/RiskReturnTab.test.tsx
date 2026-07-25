/**
 * RiskReturnTab.test.tsx — render tests for the risk-return scatter tab.
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
    // Return error=false, data=undefined → isDemo path (uses DEMO_POINTS)
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

import { RiskReturnTab } from "../RiskReturnTab";
import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as unknown as ReturnType<typeof vi.fn>;

const NO_DATA = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };

const LIVE_POINT = {
  symbol: "NIFTYBEES",
  name: "Nifty 50 ETF",
  category: "Equity",
  annualised_return: 14.2,
  annualised_volatility: 15.8,
  sharpe_ratio: 0.89,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RiskReturnTab", () => {
  beforeEach(() => {
    mockUseQuery.mockReturnValue(NO_DATA);
  });

  it("keeps the demo banner when the response omits is_sample_data", () => {
    // Provenance fails closed — an absent flag is sample, never live.
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { points: [LIVE_POINT] } });
    render(<RiskReturnTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("drops the demo banner only on an explicit is_sample_data: false", () => {
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { is_sample_data: false, points: [LIVE_POINT] } });
    render(<RiskReturnTab />);
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });

  it("renders the section heading", () => {
    render(<RiskReturnTab />);
    expect(screen.getByText("Risk-Return Analysis")).toBeInTheDocument();
  });

  it("shows demo banner when API is unavailable", () => {
    render(<RiskReturnTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders stats cards for avg return, volatility, and Sharpe", () => {
    render(<RiskReturnTab />);
    expect(screen.getByText("Avg Return")).toBeInTheDocument();
    expect(screen.getByText("Avg Volatility")).toBeInTheDocument();
    expect(screen.getByText("Best Sharpe")).toBeInTheDocument();
  });

  it("renders the scatter plot through the shared Flint scatter primitive", () => {
    render(<RiskReturnTab />);
    const chart = screen.getByRole("img", { name: /risk-return scatter/i });
    expect(chart).toHaveAttribute("data-flint-chart", "scatter");
    expect(chart.querySelectorAll("[data-scatter-point]").length).toBeGreaterThan(0);
  });

  it("renders category legend items", () => {
    render(<RiskReturnTab />);
    expect(screen.getByText("Equity")).toBeInTheDocument();
    expect(screen.getByText("Gold")).toBeInTheDocument();
  });
});
