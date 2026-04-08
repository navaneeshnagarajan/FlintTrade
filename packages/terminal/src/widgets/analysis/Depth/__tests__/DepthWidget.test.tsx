/**
 * DepthWidget.test.tsx
 *
 * Smoke tests for the market depth (Level 2) widget.
 * Mocks the API layer to prevent real network calls.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockDepthResponse = {
  bids: [
    { price: 22500.50, quantity: 1200, orders: 45 },
    { price: 22500.00, quantity: 800, orders: 30 },
  ],
  asks: [
    { price: 22501.00, quantity: 900, orders: 38 },
    { price: 22501.50, quantity: 1100, orders: 42 },
  ],
};

vi.mock("@/services/api", () => ({
  getDepth: vi.fn(() => Promise.resolve(mockDepthResponse)),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import DepthWidget from "../DepthWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DepthWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<DepthWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows bid and ask sections after data loads", async () => {
    render(<DepthWidget />);
    // Wait for the async fetch to resolve and the table to render.
    // "Bid" may appear in both the table header and the summary row.
    await waitFor(() => {
      expect(screen.getAllByText("Bid").length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getAllByText("Ask").length).toBeGreaterThanOrEqual(1);
  });
});
