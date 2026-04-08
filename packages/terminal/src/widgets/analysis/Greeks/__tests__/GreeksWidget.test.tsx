/**
 * GreeksWidget.test.tsx
 *
 * Tests for the Portfolio Greeks analysis widget.
 * Verifies rendering, empty state, and summary cards.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getPositionbook: vi.fn().mockResolvedValue([]),
  getMultiOptionGreeks: vi.fn().mockResolvedValue([]),
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import GreeksWidget from "../GreeksWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GreeksWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<GreeksWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the Portfolio Greeks heading", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Portfolio Greeks")).toBeInTheDocument();
  });

  it("shows all four Greek summary cards", () => {
    render(<GreeksWidget />);
    expect(screen.getByText("Net Delta")).toBeInTheDocument();
    expect(screen.getByText("Net Gamma")).toBeInTheDocument();
    expect(screen.getByText("Net Theta")).toBeInTheDocument();
    expect(screen.getByText("Net Vega")).toBeInTheDocument();
  });

  it("shows empty state when no F&O positions", async () => {
    render(<GreeksWidget />);
    // The empty state text (with &amp; entity rendered)
    expect(await screen.findByText(/No F&O positions/)).toBeInTheDocument();
  });

  it("shows footer with refresh interval info", () => {
    render(<GreeksWidget />);
    expect(screen.getByText(/Greeks = per-leg/)).toBeInTheDocument();
  });
});
