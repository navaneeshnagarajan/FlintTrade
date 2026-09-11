/**
 * MutualFundTab.test.tsx — Explore sample-copy honesty (FT-INVEST-001).
 *
 * Explore must not claim daily AMFI updates while showing a static fixture.
 * Practice / Live keep the live-feed freshness sentence.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let currentMode: "explore" | "practice" | "live" = "explore";

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: currentMode }),
}));

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

vi.mock("@/lib/cinematicThemes", () => ({
  getResolvedVariant: () => ({
    colors: { card: "#16161f", border: "#2a2a3a", cardHover: "#1e1e2e" },
    glass: { blur: 12, minOpacity: 0.8 },
  }),
}));

const searchMock = vi.fn(() =>
  Promise.resolve({
    funds: [
      {
        scheme_code: 999999,
        scheme_name: "API Fund - Growth",
        amc: "API AMC",
        category: "Equity Scheme - Large Cap Fund",
        nav: 100.0,
        nav_date: "11-Sep-2026",
        scheme_type: "Open Ended",
      },
    ],
  }),
);

const categoriesMock = vi.fn(() =>
  Promise.resolve({ categories: ["Equity Scheme - Large Cap Fund"] }),
);

vi.mock("@/services/ftApi", () => ({
  searchMutualFunds: () => searchMock(),
  getMFCategories: () => categoriesMock(),
  getMutualFundNAV: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { MutualFundTab } from "../MutualFundTab";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MutualFundTab />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  currentMode = "explore";
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MutualFundTab Explore sample copy (FT-INVEST-001)", () => {
  it("shows Sample NAVs · as of the fixture date and drops the daily-update claim", () => {
    renderTab();

    const asOfLines = screen.getAllByText(/Sample NAVs · as of /);
    expect(asOfLines.length).toBeGreaterThan(0);
    expect(screen.queryByText(/Updated daily after market close/i)).not.toBeInTheDocument();
    expect(screen.getByText("Sample Data")).toBeInTheDocument();

    const match = asOfLines[0].textContent?.match(/as of (\d{2}-[A-Za-z]{3}-\d{4})/);
    expect(match?.[1]).toBeTruthy();
    // Fixture date must appear on the NAV rows as well as the as-of line.
    expect(screen.getAllByText(match![1]).length).toBeGreaterThan(1);
  });

  it("does not advertise live AMFI updates while Explore sample data is showing", () => {
    renderTab();

    expect(screen.queryByText(/live NAV data from AMFI/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Sample NAVs · as of/).length).toBeGreaterThan(0);
  });

  it.each(["practice", "live"] as const)(
    "keeps daily AMFI update copy in %s when a live feed is used",
    (mode) => {
      currentMode = mode;
      renderTab();

      expect(screen.getAllByText(/Updated daily after market close/i).length).toBeGreaterThan(0);
      expect(screen.queryByText(/Sample NAVs · as of /)).not.toBeInTheDocument();
      expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
    },
  );
});
