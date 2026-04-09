import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => false,
}));

import CorrelationMatrixWidget from "../CorrelationMatrixWidget";

describe("CorrelationMatrixWidget", () => {
  it("renders widget header with title", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByText("Correlation Matrix")).toBeTruthy();
  });

  it("shows Sample badge when not connected", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("renders default 8 instruments as column headers", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThan(0);
    expect(screen.getAllByText("GOLD").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TCS").length).toBeGreaterThan(0);
  });

  it("renders matrix table with aria label", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByRole("table", { name: /correlation matrix table/i })).toBeTruthy();
  });

  it("renders symbol add input", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByLabelText("Add instrument to correlation matrix")).toBeTruthy();
  });

  it("adds a new symbol via Enter key", () => {
    render(<CorrelationMatrixWidget />);
    const input = screen.getByLabelText("Add instrument to correlation matrix");
    fireEvent.change(input, { target: { value: "SBIN" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getAllByText("SBIN").length).toBeGreaterThan(0);
  });

  it("adds a symbol via Add button", () => {
    render(<CorrelationMatrixWidget />);
    const input = screen.getByLabelText("Add instrument to correlation matrix");
    fireEvent.change(input, { target: { value: "WIPRO" } });
    fireEvent.click(screen.getByLabelText("Add instrument"));
    expect(screen.getAllByText("WIPRO").length).toBeGreaterThan(0);
  });

  it("removes a symbol via X button", () => {
    render(<CorrelationMatrixWidget />);
    const removeBtn = screen.getByLabelText("Remove GOLD from matrix");
    fireEvent.click(removeBtn);
    // GOLD should be gone from headers (chips gone; it was in multiple places)
    const goldElements = screen.queryAllByText("GOLD");
    expect(goldElements.length).toBe(0);
  });

  it("renders scale legend", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByText("Scale:")).toBeTruthy();
    expect(screen.getByText("20-day rolling returns")).toBeTruthy();
  });

  it("has correct aria label on widget container", () => {
    render(<CorrelationMatrixWidget />);
    expect(screen.getByLabelText("Correlation Matrix widget")).toBeTruthy();
  });

  it("diagonal cells show 1.00", () => {
    render(<CorrelationMatrixWidget />);
    const ones = screen.getAllByText("1.00");
    // One per diagonal symbol (8 default symbols)
    expect(ones.length).toBeGreaterThanOrEqual(8);
  });
});
