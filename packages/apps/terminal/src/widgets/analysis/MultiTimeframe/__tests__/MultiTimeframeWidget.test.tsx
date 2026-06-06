import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches live bars per timeframe (`getHistory`)
// and runs them through the analyser (`getMultiTimeframe`). We mock both so we
// can exercise the live ("Live" badge) and sample ("Sample data" badge) paths.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getHistory: vi.fn(),
}));

vi.mock("@/services/ftApi.analysis", () => ({
  getMultiTimeframe: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import { getMultiTimeframe } from "@/services/ftApi.analysis";
import MultiTimeframeWidget from "../MultiTimeframeWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetHistory = getHistory as ReturnType<typeof vi.fn>;
const mockGetMtf = getMultiTimeframe as ReturnType<typeof vi.fn>;

function liveAnalysis() {
  return {
    symbol: "NIFTY",
    confluence: 0.75,
    overall: "bullish" as const,
    signals: [
      { timeframe: "5m", trend: "bullish" as const, rsi: 61.5, macd_histogram: 4.2, ema_position: "above" as const, strength: 0.6 },
      { timeframe: "15m", trend: "bullish" as const, rsi: 58.0, macd_histogram: 2.1, ema_position: "above" as const, strength: 0.4 },
      { timeframe: "1h", trend: "bearish" as const, rsi: 41.0, macd_histogram: -1.5, ema_position: "below" as const, strength: 0.3 },
      { timeframe: "1D", trend: "neutral" as const, rsi: 50.0, macd_histogram: 0.0, ema_position: "above" as const, strength: 0.0 },
    ],
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MultiTimeframeWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockGetHistory.mockResolvedValue([]);
  // Default: analyser returns no usable timeframes → honest sample fallback.
  mockGetMtf.mockResolvedValue({ symbol: "NIFTY", signals: [], confluence: 0, overall: "neutral" });
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("MultiTimeframeWidget", () => {
  it("renders widget title", () => {
    renderWidget();
    expect(screen.getByText("Multi-Timeframe")).toBeTruthy();
  });

  it("shows the Sample data badge when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetHistory).not.toHaveBeenCalled();
    expect(mockGetMtf).not.toHaveBeenCalled();
  });

  it("flips to a Live badge once the analyser returns live signals", async () => {
    mockConnected.mockReturnValue(true);
    mockGetHistory.mockResolvedValue(
      Array.from({ length: 40 }, (_, i) => ({
        timestamp: 1705289100 + i * 300,
        open: 100, high: 101, low: 99, close: 100 + i, volume: 1000,
      })),
    );
    mockGetMtf.mockResolvedValue(liveAnalysis());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    // Live RSI value from the analyser is rendered.
    expect(screen.getByText("61.5")).toBeInTheDocument();
    expect(mockGetMtf).toHaveBeenCalled();
  });

  // When connected but the analyser returns nothing usable, the widget must NOT
  // pretend — it falls back to sample signals with the honest amber badge.
  it("falls back to Sample data when connected but the analyser returns no timeframes", async () => {
    mockConnected.mockReturnValue(true);
    mockGetMtf.mockResolvedValue({ symbol: "NIFTY", signals: [], confluence: 0, overall: "neutral" });
    renderWidget();

    await waitFor(() => expect(mockGetMtf).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("badge discloses that no live source is wired via its accessible name (sample mode)", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    const badge = screen.getByText("Sample data");
    expect(badge.getAttribute("aria-label")).toMatch(/no live multi-timeframe source/i);
  });

  it("renders all four timeframe rows", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("5m")).toBeTruthy();
    expect(screen.getByText("15m")).toBeTruthy();
    expect(screen.getByText("1h")).toBeTruthy();
    expect(screen.getByText("1D")).toBeTruthy();
  });

  it("renders column headers: TF, Trend, RSI, MACD, EMA", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("TF")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
    expect(screen.getByText("RSI")).toBeTruthy();
    expect(screen.getByText("MACD")).toBeTruthy();
    expect(screen.getByText("EMA")).toBeTruthy();
  });

  it("renders confluence section", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Confluence")).toBeTruthy();
  });

  it("renders symbol selector defaulting to NIFTY", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByRole("button", { name: /selected symbol: NIFTY/i })).toBeTruthy();
  });

  it("opens symbol dropdown and shows alternative symbols", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    expect(screen.getByText("BANKNIFTY")).toBeTruthy();
    expect(screen.getByText("RELIANCE")).toBeTruthy();
  });

  it("switches symbol when dropdown option is selected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /selected symbol/i }));
    fireEvent.click(screen.getByText("BANKNIFTY"));
    expect(screen.getByRole("button", { name: /selected symbol: BANKNIFTY/i })).toBeTruthy();
  });

  it("renders legend section", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Legend")).toBeTruthy();
    expect(screen.getByText(/Overbought/i)).toBeTruthy();
    expect(screen.getByText(/Oversold/i)).toBeTruthy();
  });
});
