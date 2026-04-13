/**
 * ShareholdingTab.test.tsx — render tests for the shareholding tab.
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

// TanStack Query — disabled (no symbol yet) → data=undefined, isLoading=false
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

import { ShareholdingTab } from "../ShareholdingTab";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ShareholdingTab", () => {
  it("renders the section heading", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Shareholding Pattern")).toBeInTheDocument();
  });

  it("renders the symbol search input", () => {
    render(<ShareholdingTab />);
    expect(
      screen.getByRole("textbox", { name: /enter nse\/bse symbol/i }),
    ).toBeInTheDocument();
  });

  it("renders the Fetch button", () => {
    render(<ShareholdingTab />);
    expect(screen.getByRole("button", { name: /fetch/i })).toBeInTheDocument();
  });

  it("shows demo banner when showing sample data", () => {
    render(<ShareholdingTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("shows demo symbol RELIANCE in the default state", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
  });

  it("renders financial highlights section", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Financial Highlights")).toBeInTheDocument();
    expect(screen.getByText("Revenue (Cr)")).toBeInTheDocument();
    expect(screen.getByText("Net Profit (Cr)")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
    expect(screen.getByText("ROCE")).toBeInTheDocument();
    expect(screen.getByText("D/E Ratio")).toBeInTheDocument();
    expect(screen.getByText("P/E Ratio")).toBeInTheDocument();
  });

  it("renders corporate announcements section", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Corporate Announcements")).toBeInTheDocument();
    // The demo has 3 announcements
    expect(screen.getByRole("list", { name: /corporate announcements/i })).toBeInTheDocument();
  });

  it("renders quarterly trend section with stacked bar", () => {
    render(<ShareholdingTab />);
    expect(screen.getByText("Quarterly Trend")).toBeInTheDocument();
    // Promoter label in legend
    expect(screen.getByText("Promoter")).toBeInTheDocument();
    expect(screen.getByText("FII")).toBeInTheDocument();
    expect(screen.getByText("DII")).toBeInTheDocument();
  });
});
