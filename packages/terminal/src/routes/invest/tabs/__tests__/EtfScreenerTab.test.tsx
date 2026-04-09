/**
 * EtfScreenerTab.test.tsx — render tests for the ETF screener tab.
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

// Mock TanStack Query — data=undefined, isError=false → isDemo path (uses DEMO_ROWS)
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

import { EtfScreenerTab } from "../EtfScreenerTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EtfScreenerTab", () => {
  it("renders the section heading", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByText("ETF Screener")).toBeInTheDocument();
  });

  it("shows demo banner when API is unavailable", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders category filter pills including All and Equity", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("radio", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Equity" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Gold" })).toBeInTheDocument();
  });

  it("renders the search input", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("textbox", { name: /search etfs/i })).toBeInTheDocument();
  });

  it("renders the ETF table with expected column headers", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("table", { name: /etf screener/i })).toBeInTheDocument();
    expect(screen.getByText("1D%")).toBeInTheDocument();
    expect(screen.getByText("1Y%")).toBeInTheDocument();
  });

  it("renders demo ETF rows", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByText("NIFTYBEES")).toBeInTheDocument();
    expect(screen.getByText("GOLDBEES")).toBeInTheDocument();
  });
});
