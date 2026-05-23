/**
 * ThreePanelWidget.test.tsx
 *
 * Smoke tests for the ThreePanelWidget.
 * lightweight-charts is a canvas library — fully mocked.
 * ResizeObserver is not in jsdom — stubbed globally.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Global stubs required by jsdom
// ---------------------------------------------------------------------------

beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

// ---------------------------------------------------------------------------
// Mocks — declared before the component import
// ---------------------------------------------------------------------------

const mockTimeScaleSubscribe = vi.fn();
const mockSetVisibleRange = vi.fn();
const mockFitContent = vi.fn();

vi.mock("lightweight-charts", () => ({
  createChart: () => ({
    // LWC v5 uses addSeries(SeriesType, options)
    addSeries: () => ({
      setData: vi.fn(),
      applyOptions: vi.fn(),
    }),
    timeScale: () => ({
      fitContent: mockFitContent,
      subscribeVisibleTimeRangeChange: mockTimeScaleSubscribe,
      setVisibleRange: mockSetVisibleRange,
    }),
    priceScale: () => ({
      applyOptions: vi.fn(),
    }),
    subscribeCrosshairMove: vi.fn(),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
  CandlestickSeries: "CandlestickSeries",
  HistogramSeries: "HistogramSeries",
  CrosshairMode: { Normal: 0 },
  LineStyle: { Solid: 0, Dashed: 1, Dotted: 2 },
  ColorType: { Solid: "solid" },
}));

vi.mock("@/services/api", () => ({
  getHistory: vi.fn(() => Promise.resolve([])),
  getExpiry: vi.fn(() => Promise.resolve({ expiry: ["27MAR25", "03APR25"] })),
  getOptionSymbol: vi.fn(() =>
    Promise.resolve({ symbol: "NIFTY25MAR2522000CE", exchange: "NFO" }),
  ),
  getOptionChain: vi.fn(() => Promise.resolve({ atm_strike: 22000 })),
}));

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    candle: {},
    layout: { background: { type: "solid", color: "#0a0a0f" }, textColor: "#94a3b8" },
    grid: {},
    crosshair: {},
    rightPriceScale: {},
    timeScale: {},
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ThreePanelWidget from "../ThreePanelWidget";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ThreePanelWidget", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockTimeScaleSubscribe.mockReset();
    mockSetVisibleRange.mockReset();
    mockFitContent.mockReset();
  });

  it("renders without crashing", () => {
    const { container } = render(<ThreePanelWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("renders the widget root with correct data attribute", () => {
    render(<ThreePanelWidget />);
    expect(document.querySelector('[data-tour-target="threepanel"]')).toBeInTheDocument();
  });

  it("shows CE, Index and PE panel labels", () => {
    render(<ThreePanelWidget />);
    expect(screen.getByText("CE")).toBeInTheDocument();
    // Index panel renders "NIFTY" twice (title + symbol subtitle) — use getAllByText
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("PE")).toBeInTheDocument();
  });

  it("renders the underlying input with default NIFTY value", () => {
    render(<ThreePanelWidget />);
    const input = screen.getByPlaceholderText("NIFTY") as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe("NIFTY");
  });

  it("renders interval pills for all expected timeframes", () => {
    render(<ThreePanelWidget />);
    for (const iv of ["1m", "5m", "15m", "1h", "1D"]) {
      expect(screen.getByRole("button", { name: iv })).toBeInTheDocument();
    }
  });

  it("highlights the default interval pill (5m)", () => {
    render(<ThreePanelWidget />);
    const fiveMin = screen.getByRole("button", { name: "5m" });
    expect(fiveMin.className).toContain("accent");
  });

  it("changes active interval when a pill is clicked", async () => {
    render(<ThreePanelWidget />);
    const oneHour = screen.getByRole("button", { name: "1h" });
    await userEvent.click(oneHour);
    expect(oneHour.className).toContain("accent");
  });

  it("renders a Strike input with ATM placeholder", () => {
    render(<ThreePanelWidget />);
    const strikeInput = screen.getByPlaceholderText("ATM") as HTMLInputElement;
    expect(strikeInput).toBeInTheDocument();
  });

  it("renders an Expiry dropdown trigger button", () => {
    render(<ThreePanelWidget />);
    // Expiry trigger shows either an em-dash or a date string like "27MAR25"
    const buttons = screen.getAllByRole("button");
    const expiryTrigger = buttons.find(
      (b) => b.textContent?.includes("—") || /\d{2}[A-Z]{3}\d{2}/.test(b.textContent ?? ""),
    );
    expect(expiryTrigger).toBeTruthy();
  });

  it("updates the underlying input value when typed", async () => {
    render(<ThreePanelWidget />);
    const input = screen.getByPlaceholderText("NIFTY") as HTMLInputElement;
    await userEvent.clear(input);
    await userEvent.type(input, "BANKNIFTY");
    expect(input.value).toBe("BANKNIFTY");
  });
});
