/**
 * RiskPanelWidget.test.tsx
 *
 * Tests for the RiskPanel trading widget.
 * Verifies rendering, risk metrics display, and overall risk badge.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const mockUseFunds = vi.fn();
const mockUsePositions = vi.fn();

vi.mock("@/hooks/useFunds", () => ({
  useFunds: () => mockUseFunds(),
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => mockUsePositions(),
}));

vi.mock("@/stores/settingsStore", () => ({
  useSettingsStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      riskLimits: {
        maxPositionLots: 10,
        mtmStoploss: 5000,
        mtmTarget: 10000,
        maxOrdersPerMinute: 20,
      },
    }),
}));

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: () => ({
    totalPnl: 0,
    openOrderCount: 0,
  }),
}));

vi.mock("zustand/react/shallow", () => ({
  useShallow: (fn: unknown) => fn,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import RiskPanelWidget from "../RiskPanelWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof RiskPanelWidget>[0];

function setupDefaultMocks() {
  mockUseFunds.mockReturnValue({
    data: { usedMargin: 50000, availableCash: 150000, totalBalance: 200000 },
    isLoading: false,
  });
  mockUsePositions.mockReturnValue({
    data: [{ symbol: "NIFTY" }, { symbol: "BANKNIFTY" }],
    isLoading: false,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RiskPanelWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupDefaultMocks();
  });

  it("renders without crashing", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Risk Panel")).toBeInTheDocument();
  });

  it("shows margin usage progress row", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Margin Used")).toBeInTheDocument();
  });

  it("shows position lots progress row", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Position Lots")).toBeInTheDocument();
  });

  it("shows configured limits section", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Configured Limits")).toBeInTheDocument();
    expect(screen.getByText("Max Lots")).toBeInTheDocument();
  });

  it("displays overall risk badge as Safe when usage is low", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Safe")).toBeInTheDocument();
  });
});
