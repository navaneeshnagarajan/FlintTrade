/**
 * RiskPanelWidget.test.tsx
 *
 * Tests for the RiskPanel trading widget.
 * Verifies rendering, risk metrics display, and overall risk badge.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const mockUseFunds = vi.fn();
const mockUsePositions = vi.fn();
const mockUseBrokerConnected = vi.fn();

vi.mock("@/hooks/useFunds", () => ({
  useFunds: (...args: unknown[]) => mockUseFunds(...args),
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockUseBrokerConnected(),
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

const defaultProps = makeDockviewPanelProps();

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
    mockUseBrokerConnected.mockReturnValue(true);
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

  it("does not substitute position rows for lot usage", () => {
    render(<RiskPanelWidget {...defaultProps} />);

    expect(screen.getByText("Position lot usage")).toBeInTheDocument();
    expect(screen.getByText(/instrument lot metadata is not loaded/i)).toBeInTheDocument();
    expect(screen.queryByText("Position Lots")).not.toBeInTheDocument();
  });

  it("does not substitute open-order count for orders per minute", () => {
    render(<RiskPanelWidget {...defaultProps} />);

    expect(screen.getByText("Order rate")).toBeInTheDocument();
    expect(screen.getByText(/rolling placement events are not tracked/i)).toBeInTheDocument();
    expect(screen.queryByText("Open Orders")).not.toBeInTheDocument();
  });

  it("shows local values as references rather than enforced limits", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Local Reference Values")).toBeInTheDocument();
    expect(screen.getByText("Lot reference")).toBeInTheDocument();
    expect(screen.getByText("Order-rate reference")).toBeInTheDocument();
    expect(screen.queryByText("Configured Limits")).not.toBeInTheDocument();
  });

  it("describes only the observed indicators when usage is low", () => {
    render(<RiskPanelWidget {...defaultProps} />);
    expect(screen.getByText("Indicators normal")).toBeInTheDocument();
  });

  it("gates live risk account data when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<RiskPanelWidget {...defaultProps} />);

    expect(mockUseFunds).toHaveBeenCalledWith({ enabled: false });
    expect(mockUsePositions).toHaveBeenCalledWith({ enabled: false });
    expect(screen.getByText("Broker required")).toBeInTheDocument();
  });
});
