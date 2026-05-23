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

  it("renders the SVG cone chart", () => {
    render(<VolatilityConeWidget />);
    expect(screen.getByRole("img", { name: /volatility cone chart/i })).toBeTruthy();
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
