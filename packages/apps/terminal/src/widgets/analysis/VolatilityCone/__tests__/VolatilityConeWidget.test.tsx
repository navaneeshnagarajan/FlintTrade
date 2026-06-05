import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import VolatilityConeWidget from "../VolatilityConeWidget";

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("VolatilityConeWidget", () => {
  it("renders widget header", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getByText("Volatility Cone")).toBeTruthy();
  });

  it("always shows the permanent 'Sample data' badge (no live endpoint wired)", () => {
    // coneData is hardcoded SAMPLE_CONE with no `/ft-api/v1/volcone` backend; the
    // badge must stay visible even when a broker is connected.
    render(<VolatilityConeWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("aria-label")).toContain("sample data");
  });

  it("renders the cone chart", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getByRole("img", { name: /volatility cone chart/i })).toBeTruthy();
  });

  it("renders the cone through the shared Flint banded-line primitive", () => {
    render(<VolatilityConeWidget />);
    const chart = screen.getByRole("img", { name: /volatility cone chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-band]").length).toBe(3);
    expect(chart.querySelectorAll("[data-banded-line-marker]").length).toBeGreaterThan(0);
  });

  it("renders period labels in summary row", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getAllByText(/5d/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/90d/).length).toBeGreaterThan(0);
  });

  it("renders IV Regime label", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getByText("IV Regime:")).toBeTruthy();
  });

  it("renders symbol selector defaulting to NIFTY", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getByText("NIFTY")).toBeTruthy();
  });

  it("opens symbol dropdown when clicked", () => {
    render(<VolatilityConeWidget />);
    const dropdown = screen.getByRole("button", { name: /NIFTY/i });
    fireEvent.click(dropdown);
    expect(screen.getByRole("option", { name: "BANKNIFTY" })).toBeTruthy();
  });
});
