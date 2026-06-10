import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const state = vi.hoisted(() => ({ connected: false }));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => state.connected,
}));

const mockGetHistory = vi.fn();
const mockGetVolCone = vi.fn();
vi.mock("@/services/api", () => ({
  getHistory: (...args: unknown[]) => mockGetHistory(...args),
}));
vi.mock("@/services/ftApi", () => ({
  getVolatilityCone: (...args: unknown[]) => mockGetVolCone(...args),
}));

import VolatilityConeWidget from "../VolatilityConeWidget";

// 130 ascending closes — enough for the 90-day window; getVolatilityCone is
// mocked so the exact values only need to be finite.
const SAMPLE_BARS = Array.from({ length: 130 }, (_, i) => ({
  close: 100 + i, high: 0, low: 0, open: 0, volume: 0, timestamp: "",
}));
const CONE_ROWS = [5, 10, 20, 30, 60, 90].map((lb) => ({
  lookback: lb, current_hv: 0.14, current_iv: null,
  p10: 0.09, p25: 0.11, p50: 0.14, p75: 0.18, p90: 0.22,
  min: 0.07, max: 0.31, iv_percentile: null,
}));

beforeEach(() => {
  state.connected = false;
  mockGetHistory.mockReset();
  mockGetVolCone.mockReset();
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

  it("shows the 'Sample data' badge when disconnected", () => {
    render(<VolatilityConeWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toBeTruthy();
    expect(badge.getAttribute("aria-label")).toContain("sample data");
    expect(mockGetHistory).not.toHaveBeenCalled();
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

  it("labels the regime 'IV' in sample mode", () => {
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

  it("builds a LIVE HV cone from real history when connected", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue(SAMPLE_BARS);
    mockGetVolCone.mockResolvedValue(CONE_ROWS);

    render(<VolatilityConeWidget />);

    // The badge flips to Live and the regime relabels to HV (the honest overlay
    // is realised HV, not a fabricated IV feed).
    expect(await screen.findByText("Live")).toBeTruthy();
    expect(screen.getByText("HV Regime:")).toBeTruthy();

    // history fetched, return series computed, cone requested
    await waitFor(() => expect(mockGetVolCone).toHaveBeenCalledTimes(1));
    const returnsArg = mockGetVolCone.mock.calls[0][0] as number[];
    expect(returnsArg.length).toBe(SAMPLE_BARS.length - 1); // closes-1 returns
  });

  it("falls back to sample (badged) when the live history is too short", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue(SAMPLE_BARS.slice(0, 10)); // < 90d window
    mockGetVolCone.mockResolvedValue(CONE_ROWS);

    render(<VolatilityConeWidget />);

    expect(await screen.findByText("Sample data")).toBeTruthy();
    expect(mockGetVolCone).not.toHaveBeenCalled();
  });
});
