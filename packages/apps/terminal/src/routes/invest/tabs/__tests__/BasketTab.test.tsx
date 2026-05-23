/**
 * BasketTab.test.tsx — Basic render tests for stock basket investing.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
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

// Mock TanStack Query
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({
    data: {},
    isLoading: false,
    refetch: vi.fn(),
  }),
}));

// Mock API service
vi.mock("@/services/api", () => ({
  getMultiQuotes: vi.fn().mockResolvedValue([]),
}));

// Mock DemoBanner
vi.mock("@/components/ui/DemoBanner", () => ({
  DemoBanner: () => (
    <div data-testid="demo-banner">Demo mode</div>
  ),
}));

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(globalThis, "localStorage", { value: localStorageMock });

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { BasketTab } from "../BasketTab";

describe("BasketTab", () => {
  beforeEach(() => {
    localStorageMock.clear();
  });

  it("renders sample baskets when no saved data", () => {
    render(<BasketTab />);
    expect(screen.getByText("NIFTY IT")).toBeInTheDocument();
    expect(screen.getByText("Banking")).toBeInTheDocument();
  });

  it("renders header with stock baskets title", () => {
    render(<BasketTab />);
    expect(screen.getByText("Stock Baskets")).toBeInTheDocument();
    expect(screen.getByText(/thematic stock baskets/)).toBeInTheDocument();
  });

  it("renders New Basket button", () => {
    render(<BasketTab />);
    expect(screen.getByText("New Basket")).toBeInTheDocument();
  });

  it("renders Refresh button", () => {
    render(<BasketTab />);
    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });

  it("shows stock count badge on basket cards", () => {
    render(<BasketTab />);
    // NIFTY IT has 5 stocks, Banking has 5 stocks
    const badges = screen.getAllByText("5 stocks");
    expect(badges.length).toBeGreaterThanOrEqual(2);
  });

  it("shows demo banner when no quotes loaded", () => {
    render(<BasketTab />);
    expect(screen.getByTestId("demo-banner")).toBeInTheDocument();
  });

  it("renders saved baskets from localStorage", () => {
    const baskets = [
      {
        id: "custom-1",
        name: "My Picks",
        description: "Custom basket",
        constituents: [
          { symbol: "RELIANCE", exchange: "NSE", weight: 50 },
          { symbol: "TCS", exchange: "NSE", weight: 50 },
        ],
        investedAmount: 200000,
        createdAt: "2026-01-01T00:00:00.000Z",
      },
    ];
    localStorageMock.setItem("flinttrade:stock-baskets", JSON.stringify(baskets));

    render(<BasketTab />);
    expect(screen.getByText("My Picks")).toBeInTheDocument();
    expect(screen.getByText("2 stocks")).toBeInTheDocument();
  });

  it("shows constituents table when basket is clicked", () => {
    render(<BasketTab />);

    // Click on the NIFTY IT basket card
    const niftyCard = screen.getByText("NIFTY IT");
    fireEvent.click(niftyCard);

    // Should show constituents heading and table
    expect(screen.getByText("NIFTY IT — Constituents")).toBeInTheDocument();
    expect(screen.getByText("TCS")).toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
    expect(screen.getByText("WIPRO")).toBeInTheDocument();
  });

  it("shows drift column in constituents table", () => {
    render(<BasketTab />);
    // Click NIFTY IT
    fireEvent.click(screen.getByText("NIFTY IT"));

    // Table headers should include Drift
    expect(screen.getByText("Drift")).toBeInTheDocument();
    expect(screen.getByText("Target Wt.")).toBeInTheDocument();
  });

  it("hides constituents when clicking basket again (toggle)", () => {
    render(<BasketTab />);
    const niftyCard = screen.getByText("NIFTY IT");

    fireEvent.click(niftyCard);
    expect(screen.getByText("NIFTY IT — Constituents")).toBeInTheDocument();

    fireEvent.click(niftyCard);
    expect(screen.queryByText("NIFTY IT — Constituents")).not.toBeInTheDocument();
  });

  it("opens create dialog when New Basket is clicked", () => {
    render(<BasketTab />);
    fireEvent.click(screen.getByText("New Basket"));

    expect(screen.getByText("Create Stock Basket")).toBeInTheDocument();
    expect(screen.getByText("Basket Name")).toBeInTheDocument();
  });
});
