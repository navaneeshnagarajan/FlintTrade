/**
 * NewsWidget.test.tsx
 *
 * Tests for the News feed widget.
 * Verifies rendering, sentiment filter tabs, and search input.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

// Mock ftApi.getNews to avoid real network calls
vi.mock("@/services/ftApi", () => ({
  getNews: vi.fn().mockRejectedValue(new Error("No backend")),
}));

// Mock global fetch to avoid real RSS calls in the CORS proxy fallback
vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import NewsWidget from "../NewsWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("NewsWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Re-apply fetch mock after restoreAllMocks
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("No network"));
  });

  it("renders without crashing", () => {
    render(<NewsWidget />);
    expect(screen.getByText("News")).toBeInTheDocument();
  });

  it("shows sentiment filter tabs", () => {
    render(<NewsWidget />);
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("Bullish")).toBeInTheDocument();
    expect(screen.getByText("Bearish")).toBeInTheDocument();
    expect(screen.getByText("Neutral")).toBeInTheDocument();
  });

  it("shows search input with placeholder", () => {
    render(<NewsWidget />);
    expect(
      screen.getByPlaceholderText("Search headlines, sources..."),
    ).toBeInTheDocument();
  });
});
