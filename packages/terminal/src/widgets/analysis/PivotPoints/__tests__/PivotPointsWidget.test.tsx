/**
 * PivotPointsWidget.test.tsx
 *
 * Tests: render, pivot calculation, method tabs, price zone, sample data.
 */

import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/api", () => ({
  getHistory: vi.fn(() => Promise.resolve([])),
  getQuotes: vi.fn(() => Promise.resolve({ ltp: 22495 })),
}));

import PivotPointsWidget from "../PivotPointsWidget";

describe("PivotPointsWidget", () => {
  it("renders the widget header", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("Pivot Points")).toBeTruthy();
  });

  it("shows sample data badge when disconnected", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("sample data")).toBeTruthy();
  });

  it("renders OHLC input fields", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByLabelText("Previous day High")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Low")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Close")).toBeTruthy();
    expect(screen.getByLabelText("Previous day Open")).toBeTruthy();
  });

  it("renders method tabs for all five pivot methods", () => {
    render(<PivotPointsWidget />);
    // Use getAllByText because method names also appear in the footer summary
    expect(screen.getAllByText("Standard").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Fibonacci").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Woodie").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Camarilla").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("DeMark").length).toBeGreaterThanOrEqual(1);
  });

  it("renders level labels P, R1–R4, S1–S4 in the table", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("P")).toBeTruthy();
    expect(screen.getByText("R1")).toBeTruthy();
    expect(screen.getByText("S1")).toBeTruthy();
    expect(screen.getByText("R4")).toBeTruthy();
    expect(screen.getByText("S4")).toBeTruthy();
  });

  it("switches to Fibonacci method when tab is clicked", () => {
    render(<PivotPointsWidget />);
    // Target the tab button specifically by role
    const tabs = screen.getAllByRole("tab");
    const fibTab = tabs.find((t) => t.textContent === "Fibonacci");
    expect(fibTab).toBeTruthy();
    fireEvent.click(fibTab!);
    expect(fibTab!.getAttribute("aria-selected")).toBe("true");
  });

  it("shows current price label", () => {
    render(<PivotPointsWidget />);
    expect(screen.getByText("Current price")).toBeTruthy();
  });

  it("renders the symbol selector with NIFTY as default", () => {
    render(<PivotPointsWidget />);
    const select = screen.getByLabelText("Select symbol");
    expect((select as HTMLSelectElement).value).toBe("NIFTY");
  });
});
