/**
 * EtfScreenerTab.test.tsx — render tests for the ETF screener tab.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

// Mock TanStack Query — data=undefined, isError=false → demo path
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
import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as unknown as ReturnType<typeof vi.fn>;

const NO_DATA = { data: undefined, isLoading: false, isError: false, refetch: vi.fn() };

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EtfScreenerTab", () => {
  beforeEach(() => {
    mockUseQuery.mockReturnValue(NO_DATA);
  });

  it("keeps the demo banner when the response omits is_sample_data", () => {
    // Provenance fails closed — an absent flag is sample, never live.
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { etfs: [] } });
    render(<EtfScreenerTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("drops the demo banner only on an explicit is_sample_data: false", () => {
    mockUseQuery.mockReturnValue({ ...NO_DATA, data: { is_sample_data: false, etfs: [] } });
    render(<EtfScreenerTab />);
    expect(screen.queryByTestId("demo-banner")).not.toBeInTheDocument();
  });

  it("renders the section heading", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByText("ETF Screener")).toBeInTheDocument();
  });

  it("shows demo banner when API is unavailable", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders the category select with default All", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("combobox", { name: /filter by etf category/i })).toBeInTheDocument();
  });

  it("renders the search input", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("textbox", { name: /search etfs/i })).toBeInTheDocument();
  });

  it("renders the ETF table with new column headers", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("table", { name: /etf screener/i })).toBeInTheDocument();
    expect(screen.getByText("1M%")).toBeInTheDocument();
    expect(screen.getByText("12M%")).toBeInTheDocument();
    expect(screen.getByText("Momentum")).toBeInTheDocument();
    expect(screen.getByText("AUM")).toBeInTheDocument();
  });

  it("renders demo ETF rows", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByText("NIFTYBEES")).toBeInTheDocument();
    expect(screen.getByText("GOLDBEES")).toBeInTheDocument();
  });

  it("renders trend sparklines through the shared Flint primitive", () => {
    render(<EtfScreenerTab />);

    const sparklines = screen.getAllByRole("img", { name: /etf 30-day trend sparkline/i });
    expect(sparklines.length).toBeGreaterThan(0);
    expect(sparklines[0]).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparklines[0].querySelector("polyline")).not.toBeInTheDocument();
    expect(sparklines[0].querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renders table view toggle buttons", () => {
    render(<EtfScreenerTab />);
    expect(screen.getByRole("button", { name: /table view/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /asset quilt view/i })).toBeInTheDocument();
  });

  it("switches to quilt view on button click", () => {
    render(<EtfScreenerTab />);
    const quiltBtn = screen.getByRole("button", { name: /asset quilt view/i });
    fireEvent.click(quiltBtn);
    // Quilt renders without the table
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    // The quilt note text is present
    expect(screen.getByText(/ranked within each calendar year/i)).toBeInTheDocument();
  });

  it("filters rows when searching", () => {
    render(<EtfScreenerTab />);
    const searchInput = screen.getByRole("textbox", { name: /search etfs/i });
    fireEvent.change(searchInput, { target: { value: "GOLD" } });
    expect(screen.getByText("GOLDBEES")).toBeInTheDocument();
    expect(screen.queryByText("NIFTYBEES")).not.toBeInTheDocument();
  });
});
