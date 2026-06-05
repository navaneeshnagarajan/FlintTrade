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
import PCRTrendWidget from "../PCRTrendWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("PCRTrendWidget", () => {
  it("renders widget header with correct title", () => {
    render(<PCRTrendWidget />);
    expect(screen.getByText("PCR Trend")).toBeTruthy();
  });

  it("shows the Sample data badge when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<PCRTrendWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("still shows the Sample data badge when broker is connected (data is never live yet)", () => {
    // CASE A: the widget only ever renders `SAMPLE_PCR`; no live PCR endpoint
    // is wired. The badge must stay visible on a live connection so we never
    // imply the headline PCR / arrow / regime is real.
    mockUseBrokerConnected.mockReturnValue(true);
    render(<PCRTrendWidget />);
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("labels the Sample data badge as a status disclosing no live source", () => {
    render(<PCRTrendWidget />);
    const badge = screen.getByText("Sample data");
    expect(badge).toHaveAttribute("role", "status");
    expect(badge.getAttribute("aria-label")).toMatch(/no live PCR data source is wired yet/i);
  });

  it("renders the PCR chart through the shared Flint threshold line primitive", () => {
    render(<PCRTrendWidget />);
    const chart = screen.getByRole("img", { name: /pcr trend chart/i });
    expect(chart).toHaveAttribute("data-flint-chart", "threshold-line");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-threshold-band]").length).toBeGreaterThan(0);
  });

  it("displays a current PCR value", () => {
    render(<PCRTrendWidget />);
    // PCR value is a number between 0 and 3, rendered in the summary row
    const pcrEl = screen.getByLabelText(/Current PCR/i);
    expect(pcrEl).toBeTruthy();
    const val = parseFloat(pcrEl.textContent ?? "0");
    expect(val).toBeGreaterThan(0);
    expect(val).toBeLessThan(3);
  });

  it("renders regime label in summary row", () => {
    render(<PCRTrendWidget />);
    // One of the known regimes must be visible
    const regimeLabels = [
      "Bullish Extreme",
      "Bullish",
      "Neutral",
      "Bearish",
      "Bearish Extreme",
    ];
    const found = regimeLabels.some((label) => {
      try {
        return screen.getByText(label) !== null;
      } catch {
        return false;
      }
    });
    expect(found).toBe(true);
  });

  it("renders 20-session average in summary", () => {
    render(<PCRTrendWidget />);
    expect(screen.getByText(/20-session avg:/i)).toBeTruthy();
  });

  it("symbol selector defaults to NIFTY", () => {
    render(<PCRTrendWidget />);
    // The button with aria-label containing the symbol name
    expect(screen.getByLabelText(/Select symbol, currently NIFTY/i)).toBeTruthy();
  });

  it("opens symbol dropdown and shows alternatives", () => {
    render(<PCRTrendWidget />);
    const btn = screen.getByLabelText(/Select symbol, currently NIFTY/i);
    fireEvent.click(btn);
    expect(screen.getByRole("option", { name: "BANKNIFTY" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "FINNIFTY" })).toBeTruthy();
  });

  it("renders band legend items", () => {
    render(<PCRTrendWidget />);
    expect(screen.getByText(/Bullish Ext\./i)).toBeTruthy();
    expect(screen.getByText(/Bearish Ext\./i)).toBeTruthy();
  });
});
