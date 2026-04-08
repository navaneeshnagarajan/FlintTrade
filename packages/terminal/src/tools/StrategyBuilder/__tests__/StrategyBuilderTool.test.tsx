/**
 * StrategyBuilderTool.test.tsx
 *
 * Tests for the Strategy Builder canvas tool.
 * Verifies rendering, heading, tabs, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("../usePineRunner", () => ({
  usePineRunner: () => ({
    code: "",
    output: "",
    isRunning: false,
    error: null,
    run: vi.fn(),
    reset: vi.fn(),
    setCode: vi.fn(),
    setOptions: vi.fn(),
    options: {},
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import StrategyBuilderTool from "../StrategyBuilderTool";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StrategyBuilderTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders without crashing", () => {
    const { container } = render(<StrategyBuilderTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Strategy Builder heading", () => {
    render(<StrategyBuilderTool />);
    expect(screen.getByText("Strategy Builder")).toBeInTheDocument();
  });

  it("has Strategy Legs, Payoff, Margin, and Pine Script tabs", () => {
    render(<StrategyBuilderTool />);
    expect(screen.getByText("Strategy Legs")).toBeInTheDocument();
    expect(screen.getByText("Payoff")).toBeInTheDocument();
    expect(screen.getByText("Margin")).toBeInTheDocument();
    expect(screen.getByText("Pine Script")).toBeInTheDocument();
  });
});
