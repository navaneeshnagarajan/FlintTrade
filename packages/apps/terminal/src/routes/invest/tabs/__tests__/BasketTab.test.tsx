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

import { useModeStore } from "@/stores/modeStore";
import { BasketTab } from "../BasketTab";

const SAMPLE_BASKET_EDIT_UNAVAILABLE = "Sample basket — editing unavailable in Explore";

const USER_BASKET = {
  id: "custom-1",
  name: "My Picks",
  description: "Custom basket",
  constituents: [
    { symbol: "RELIANCE", exchange: "NSE", weight: 50 },
    { symbol: "TCS", exchange: "NSE", weight: 50 },
  ],
  investedAmount: 200000,
  createdAt: "2026-01-01T00:00:00.000Z",
};

function seedUserBasket(): void {
  localStorageMock.setItem("flinttrade:stock-baskets", JSON.stringify([USER_BASKET]));
}

function expectNoCardSampleChip(): void {
  expect(screen.queryByTestId("provenance-badge")).not.toBeInTheDocument();
  expect(screen.queryByTestId("provenance-badge-inline")).not.toBeInTheDocument();
  expect(screen.queryByText("Sample")).not.toBeInTheDocument();
}

describe("BasketTab", () => {
  beforeEach(() => {
    localStorageMock.clear();
    useModeStore.setState({ mode: "explore" });
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
    seedUserBasket();

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

  it("disables Edit and Delete on seeded Explore baskets with the sample helper", () => {
    render(<BasketTab />);

    for (const name of ["NIFTY IT", "Banking"]) {
      const edit = screen.getByRole("button", { name: `Edit ${name}` });
      const remove = screen.getByRole("button", { name: `Delete ${name}` });
      expect(edit).toBeDisabled();
      expect(remove).toBeDisabled();
      expect(edit).toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
      expect(remove).toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
    }

    expectNoCardSampleChip();
    fireEvent.click(screen.getByRole("button", { name: "Edit NIFTY IT" }));
    expect(screen.queryByText("Edit Basket")).not.toBeInTheDocument();
  });

  it("keeps Edit and Delete armed on user-created Explore baskets", () => {
    seedUserBasket();
    render(<BasketTab />);

    const edit = screen.getByRole("button", { name: "Edit My Picks" });
    const remove = screen.getByRole("button", { name: "Delete My Picks" });
    expect(edit).toBeEnabled();
    expect(remove).toBeEnabled();
    expectNoCardSampleChip();

    fireEvent.click(edit);
    expect(screen.getByText("Edit Basket")).toBeInTheDocument();
  });

  it("keeps Edit and Delete armed on Practice user-created baskets", () => {
    useModeStore.setState({ mode: "practice" });
    seedUserBasket();
    render(<BasketTab />);

    const edit = screen.getByRole("button", { name: "Edit My Picks" });
    const remove = screen.getByRole("button", { name: "Delete My Picks" });
    expect(edit).toBeEnabled();
    expect(remove).toBeEnabled();
    expect(edit).not.toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
    expect(remove).not.toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
    expectNoCardSampleChip();

    fireEvent.click(edit);
    expect(screen.getByText("Edit Basket")).toBeInTheDocument();
  });

  it("keeps Edit and Delete armed on Live user-created baskets", () => {
    useModeStore.setState({ mode: "live" });
    seedUserBasket();
    render(<BasketTab />);

    const edit = screen.getByRole("button", { name: "Edit My Picks" });
    const remove = screen.getByRole("button", { name: "Delete My Picks" });
    expect(edit).toBeEnabled();
    expect(remove).toBeEnabled();
    expect(edit).not.toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
    expect(remove).not.toHaveAttribute("title", SAMPLE_BASKET_EDIT_UNAVAILABLE);
    expectNoCardSampleChip();

    fireEvent.click(edit);
    expect(screen.getByText("Edit Basket")).toBeInTheDocument();
  });
});
