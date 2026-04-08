/**
 * PnLDashboardTool.test.tsx
 *
 * Tests for the P&L Dashboard canvas tool.
 * Verifies rendering, heading, tabs, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const mockUsePositions = vi.fn();
const mockUseFunds = vi.fn();
const mockUseTradebook = vi.fn();

vi.mock("@/hooks/usePositions", () => ({
  usePositions: (...args: unknown[]) => mockUsePositions(...args),
}));

vi.mock("@/hooks/useFunds", () => ({
  useFunds: (...args: unknown[]) => mockUseFunds(...args),
}));

vi.mock("@/hooks/useTradebook", () => ({
  useTradebook: (...args: unknown[]) => mockUseTradebook(...args),
}));

// Mock Tremor charts to avoid canvas/SVG rendering issues in JSDOM
vi.mock("@tremor/react", () => ({
  AreaChart: () => null,
  DonutChart: () => null,
  BarList: () => null,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import PnLDashboardTool from "../PnLDashboardTool";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function queryResult(overrides = {}) {
  return {
    data: undefined,
    isLoading: false,
    isPending: false,
    isError: false,
    error: null,
    isFetching: false,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
    ...overrides,
  };
}

function setupMocks(config: {
  positions?: unknown[];
  posLoading?: boolean;
  posError?: boolean;
  funds?: Record<string, unknown>;
  fundsLoading?: boolean;
  trades?: unknown[];
  tradesLoading?: boolean;
} = {}) {
  mockUsePositions.mockReturnValue(
    queryResult({
      data: config.positions ?? [],
      isLoading: config.posLoading ?? false,
      isError: config.posError ?? false,
    }),
  );
  mockUseFunds.mockReturnValue(
    queryResult({
      data: config.funds,
      isLoading: config.fundsLoading ?? false,
    }),
  );
  mockUseTradebook.mockReturnValue(
    queryResult({
      data: config.trades ?? [],
      isLoading: config.tradesLoading ?? false,
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PnLDashboardTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setupMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<PnLDashboardTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the P&L Dashboard heading", () => {
    render(<PnLDashboardTool />);
    expect(screen.getByText("P&L Dashboard")).toBeInTheDocument();
  });

  it("has Summary, Calendar, and Drawdown tabs", () => {
    render(<PnLDashboardTool />);
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("Calendar")).toBeInTheDocument();
    expect(screen.getByText("Drawdown")).toBeInTheDocument();
  });
});
