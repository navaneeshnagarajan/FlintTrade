import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import VolatilityConeWidget from "../VolatilityConeWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

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

  it("shows sample badge when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<VolatilityConeWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("hides sample badge when broker is connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    render(<VolatilityConeWidget />);
    expect(screen.queryByText("Sample")).toBeNull();
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
