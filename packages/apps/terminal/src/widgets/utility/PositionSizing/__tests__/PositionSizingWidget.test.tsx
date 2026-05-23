import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import PositionSizingWidget from "../PositionSizingWidget";

describe("PositionSizingWidget", () => {
  it("renders widget header with title", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("Position Sizing")).toBeTruthy();
  });

  it("renders three method tabs", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByRole("tab", { name: "Fixed %" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Kelly" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "ATR" })).toBeTruthy();
  });

  it("Fixed % tab is active by default", () => {
    render(<PositionSizingWidget />);
    const tab = screen.getByRole("tab", { name: "Fixed %" });
    expect(tab.getAttribute("aria-selected")).toBe("true");
  });

  it("shows results with default Fixed % values", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("Position Size (lots)")).toBeTruthy();
    expect(screen.getByText("Rupee Risk")).toBeTruthy();
    expect(screen.getByText("Max Loss")).toBeTruthy();
  });

  it("renders pie chart with aria label", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByRole("img", { name: /capital allocation/i })).toBeTruthy();
  });

  it("switches to Kelly tab and shows Kelly inputs", () => {
    render(<PositionSizingWidget />);
    fireEvent.click(screen.getByRole("tab", { name: "Kelly" }));
    expect(screen.getByLabelText("Win Rate %")).toBeTruthy();
    expect(screen.getByLabelText("Reward : Risk")).toBeTruthy();
  });

  it("switches to ATR tab and shows ATR inputs", () => {
    render(<PositionSizingWidget />);
    fireEvent.click(screen.getByRole("tab", { name: "ATR" }));
    expect(screen.getByLabelText("ATR Value")).toBeTruthy();
    expect(screen.getByLabelText("ATR Multiplier")).toBeTruthy();
  });

  it("shows empty state when account capital is cleared", () => {
    render(<PositionSizingWidget />);
    const capitalInput = screen.getByLabelText("Account Capital");
    fireEvent.change(capitalInput, { target: { value: "" } });
    expect(screen.getByText(/fill in all fields/i)).toBeTruthy();
  });

  it("has correct aria label on widget container", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByLabelText("Position Sizing widget")).toBeTruthy();
  });

  it("renders At Risk and Available pie legend labels", () => {
    render(<PositionSizingWidget />);
    expect(screen.getByText("At Risk")).toBeTruthy();
    expect(screen.getByText("Available")).toBeTruthy();
  });
});
