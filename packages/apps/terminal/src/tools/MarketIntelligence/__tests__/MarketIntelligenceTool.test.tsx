/**
 * MarketIntelligenceTool.test.tsx
 *
 * Tests for the Market Intelligence canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock market intel hooks
vi.mock("@/hooks/useMarketIntel", () => ({
  useGex: () => ({ data: undefined, isLoading: false, isError: false }),
  useIVSmile: () => ({ data: undefined, isLoading: false, isError: false }),
  useMaxPain: () => ({ data: undefined, isLoading: false, isError: false }),
  useOIProfile: () => ({ data: undefined, isLoading: false, isError: false }),
}));

// Mock API calls
vi.mock("@/services/api", () => ({
  getExpiry: vi.fn().mockResolvedValue([]),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import MarketIntelligenceTool from "../MarketIntelligenceTool";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MarketIntelligenceTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<MarketIntelligenceTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Market Intelligence heading", () => {
    render(<MarketIntelligenceTool />);
    expect(screen.getByText("Market Intelligence")).toBeInTheDocument();
  });

  it("shows the Sample Data badge for sample-data tabs", () => {
    render(<MarketIntelligenceTool />);
    // The default tab (breadth) uses sample data
    expect(screen.getByText("Sample Data")).toBeInTheDocument();
  });
});
