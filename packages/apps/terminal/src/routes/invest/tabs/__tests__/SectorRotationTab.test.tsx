/**
 * SectorRotationTab.test.tsx — render tests for the sector rotation tab.
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

// Mock TanStack Query — data=undefined, isError=false → isDemo path (uses DEMO_SECTORS)
vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return {
    ...actual,
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

import { SectorRotationTab } from "../SectorRotationTab";
import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as unknown as ReturnType<typeof vi.fn>;

const NO_DATA = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };

const LIVE_SECTOR = {
  symbol: "NIFTYIT",
  name: "Nifty IT",
  change_1d: 1.24,
  change_1w: 3.10,
  change_1m: 6.80,
  change_3m: 12.40,
  change_6m: 18.20,
  change_1y: 32.10,
  market_cap_cr: 980000,
  momentum_score: 82,
  quadrant: "leading",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("SectorRotationTab", () => {
  beforeEach(() => {
    mockUseQuery.mockReturnValue(NO_DATA);
  });

  it("keeps the demo banner when the response omits is_sample_data", () => {
    // Provenance fails closed — an absent flag is sample, never live.
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { sectors: [LIVE_SECTOR] } });
    render(<SectorRotationTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("drops the demo banner only on an explicit is_sample_data: false", () => {
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { is_sample_data: false, sectors: [LIVE_SECTOR] } });
    render(<SectorRotationTab />);
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });

  it("renders the section heading", () => {
    render(<SectorRotationTab />);
    expect(screen.getByText("Sector Rotation")).toBeInTheDocument();
  });

  it("shows demo banner when API is unavailable", () => {
    render(<SectorRotationTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders heatmap and momentum sub-tabs", () => {
    render(<SectorRotationTab />);
    expect(screen.getByRole("tab", { name: /heatmap/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /momentum/i })).toBeInTheDocument();
  });

  it("renders sector heatmap tiles with demo data", () => {
    render(<SectorRotationTab />);
    // Sector symbols stripped of NIFTY prefix are shown in tiles
    expect(screen.getByLabelText(/Nifty IT/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Nifty Bank/i)).toBeInTheDocument();
  });

  it("renders the returns table with multi-period columns", () => {
    render(<SectorRotationTab />);
    expect(screen.getByRole("table", { name: /sector returns/i })).toBeInTheDocument();
    expect(screen.getByText("1D%")).toBeInTheDocument();
    expect(screen.getByText("1Y%")).toBeInTheDocument();
  });
});
