/**
 * TickerWidget.test.tsx
 *
 * Tests for the Ticker scrolling price tape widget.
 * Verifies rendering and default instrument labels.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock Jotai tickAtomFamily — returns null tick atom (no WS data in test)
vi.mock("@/atoms/marketAtoms", () => ({
  tickAtomFamily: () => ({ init: null }),
}));

vi.mock("jotai", () => ({
  useAtomValue: () => null,
  atom: (v: unknown) => ({ init: v }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import TickerWidget from "../TickerWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TickerWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    render(<TickerWidget />);
    expect(screen.getByText("Live Prices")).toBeInTheDocument();
  });

  it("shows default instrument labels", () => {
    render(<TickerWidget />);
    // Instruments appear twice (doubled for seamless scroll loop)
    const niftyLabels = screen.getAllByText("NIFTY 50");
    expect(niftyLabels.length).toBe(2);

    const bankNiftyLabels = screen.getAllByText("BANK NIFTY");
    expect(bankNiftyLabels.length).toBe(2);
  });
});
