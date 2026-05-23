/**
 * GoalTab.test.tsx — Basic render tests for the Goal-based investment tracker.
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

// Mock crypto.randomUUID
Object.defineProperty(globalThis, "crypto", {
  value: { randomUUID: () => "test-uuid-001" },
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { GoalTab } from "../GoalTab";

describe("GoalTab", () => {
  beforeEach(() => {
    localStorageMock.clear();
  });

  it("renders empty state when no goals exist", () => {
    render(<GoalTab />);
    expect(
      screen.getByText("Set your first financial goal"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Add Your First Goal/)).toBeInTheDocument();
  });

  it("renders goal cards when goals exist in localStorage", () => {
    const goals = [
      {
        id: "goal-1",
        name: "Dream Home",
        category: "home",
        targetAmount: 5000000,
        currentSavings: 1000000,
        monthlySip: 25000,
        expectedReturnPct: 12,
        targetDate: "2030-01-01",
        createdAt: "2024-01-01T00:00:00.000Z",
      },
    ];
    localStorageMock.setItem("flinttrade:investment-goals", JSON.stringify(goals));

    render(<GoalTab />);
    expect(screen.getByText("Dream Home")).toBeInTheDocument();
    expect(screen.getByText(/Total Goals/)).toBeInTheDocument();
  });

  it("renders summary stats with correct goal count", () => {
    const goals = [
      {
        id: "goal-1",
        name: "Retirement",
        category: "retirement",
        targetAmount: 10000000,
        currentSavings: 2000000,
        monthlySip: 50000,
        expectedReturnPct: 12,
        targetDate: "2040-01-01",
        createdAt: "2024-01-01T00:00:00.000Z",
      },
      {
        id: "goal-2",
        name: "Education",
        category: "education",
        targetAmount: 3000000,
        currentSavings: 500000,
        monthlySip: 15000,
        expectedReturnPct: 10,
        targetDate: "2032-01-01",
        createdAt: "2024-01-01T00:00:00.000Z",
      },
    ];
    localStorageMock.setItem("flinttrade:investment-goals", JSON.stringify(goals));

    render(<GoalTab />);
    // Should show count of 2
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
