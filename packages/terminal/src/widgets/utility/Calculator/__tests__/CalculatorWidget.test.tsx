/**
 * CalculatorWidget.test.tsx
 *
 * Tests for the Calculator widget with Risk/Reward and Brokerage tabs.
 * Verifies rendering, tab structure, and form defaults.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Import component under test
// ---------------------------------------------------------------------------

import CalculatorWidget from "../CalculatorWidget";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultProps = {} as Parameters<typeof CalculatorWidget>[0];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CalculatorWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Calculator")).toBeInTheDocument();
  });

  it("shows Risk / Reward tab by default", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Risk / Reward")).toBeInTheDocument();
    expect(screen.getByText("Brokerage")).toBeInTheDocument();
  });

  it("shows risk calculator template buttons", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(screen.getByText("Conservative")).toBeInTheDocument();
    expect(screen.getByText("Balanced")).toBeInTheDocument();
    expect(screen.getByText("Aggressive")).toBeInTheDocument();
  });

  it("has both Risk/Reward and Brokerage tab triggers", () => {
    render(<CalculatorWidget {...defaultProps} />);
    const tabs = screen.getAllByRole("tab");
    const tabLabels = tabs.map((t) => t.textContent?.trim());
    expect(tabLabels).toContain("Risk / Reward");
    expect(tabLabels).toContain("Brokerage");
  });

  it("shows the default prompt text for risk calculator", () => {
    render(<CalculatorWidget {...defaultProps} />);
    expect(
      screen.getByText("Enter entry and stop loss prices to calculate"),
    ).toBeInTheDocument();
  });
});
