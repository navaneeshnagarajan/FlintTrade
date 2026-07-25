/**
 * StraddleWidget.test.tsx
 *
 * Tests for the Straddle analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 *
 * This suite is the union of the old Straddle suite and the retired
 * ImpliedMove suite (merge 2.15). The ImpliedMove suite pinned that its
 * "Sample data" badge stayed visible EVEN WHEN CONNECTED, because the widget
 * had no live source at all. Those pins are obsolete by construction now that
 * the σ bands are computed from this widget's live chain, so they are rewritten
 * to pin the opposite: a live ATM straddle renders figures with no sample
 * badge, and the absence of one renders an honest "No live data" disclosure
 * instead of fabricated numbers. The σ arithmetic pins (move = CE + PE,
 * bounds = spot ± move, 2σ = 2 × 1σ) carry over verbatim in intent, but run
 * against `computeImpliedMove` on live inputs rather than a constant table.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const chartMocks = vi.hoisted(() => {
  const lineSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];
  const createdLineSeries: Array<{
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
  }> = [];

  const createSeries = () => ({
    setData: vi.fn(),
    applyOptions: vi.fn(),
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
  };

  const shellRuntime = {
    createChart: vi.fn(() => chart),
  };

  const lineRuntime = {
    createChart: shellRuntime.createChart,
    addLineSeries: vi.fn((_chart: unknown, options: unknown) => {
      lineSeriesOptions.push(options);
      const series = createSeries();
      createdLineSeries.push(series);
      return series;
    }),
  };

  return {
    chart,
    shellRuntime,
    lineRuntime,
    lineSeriesOptions,
    localSeriesOptions,
    createdLineSeries,
    reset() {
      lineSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      createdLineSeries.length = 0;
    },
  };
});

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getPositionbook: vi.fn(),
}));

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getPositionbook: apiMocks.getPositionbook,
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock lightweight-charts to avoid canvas issues in JSDOM
vi.mock("lightweight-charts", () => ({
  createChart: chartMocks.shellRuntime.createChart,
  LineSeries: "LineSeries",
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: chartMocks.shellRuntime,
  lightweightLineRuntime: chartMocks.lineRuntime,
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Mock chart theme hook
vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    rightPriceScale: {},
    timeScale: {},
    // createFlintLineChart (real, from the design-system) reads
    // theme.crosshair.vertLine — the mock must carry the same shape.
    crosshair: { vertLine: {}, horzLine: {} },
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import StraddleWidget, { computeImpliedMove } from "../StraddleWidget";

/** Renders the widget with a Dockview panel-props stub and optional params. */
function renderWidget(params: Record<string, unknown> = {}) {
  return render(<StraddleWidget {...makeDockviewPanelProps({ params })} />);
}

/**
 * A live NIFTY chain whose ATM straddle produces round σ bands:
 *   move = 112.5 + 87.5 = 200 → ±1σ = 25,200 / 24,800, ±2σ = 25,400 / 24,600.
 */
function liveChainMocks() {
  apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
  apiMocks.getQuotes.mockResolvedValue({ ltp: 25000, prev_close: 24990 });
  apiMocks.getOptionChain.mockResolvedValue({
    atm_strike: 25000,
    chain: [{ strike: 25000, ce: { ltp: 112.5 }, pe: { ltp: 87.5 } }],
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StraddleWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    apiMocks.getExpiry.mockResolvedValue([]);
    apiMocks.getOptionChain.mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
    apiMocks.getPositionbook.mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    renderWidget();
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows headline price labels (Straddle, CE, PE)", () => {
    renderWidget();
    // "Straddle" appears in the headline, the overlay toggle and the view
    // toggle — use getAllByText
    const straddleElements = screen.getAllByText("Straddle");
    expect(straddleElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("CE")).toBeInTheDocument();
    expect(screen.getByText("PE")).toBeInTheDocument();
  });

  it("shows overlay toggle buttons", () => {
    renderWidget();
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.getByText("Spot")).toBeInTheDocument();
    expect(screen.getByText("SynFut")).toBeInTheDocument();
  });

  it("routes overlay line series through the shared Flint line runtime", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-06-25"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 22510, prev_close: 22480 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 22500,
      calls: [{ strike_price: 22500, ltp: 112.5 }],
      puts: [{ strike_price: 22500, ltp: 98.25 }],
    });

    renderWidget();

    await waitFor(() => {
      expect(chartMocks.lineRuntime.addLineSeries).toHaveBeenCalledTimes(3);
    });
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.lineSeriesOptions).toEqual([
      expect.objectContaining({
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      }),
      expect.objectContaining({
        color: "#eab308",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
      expect.objectContaining({
        color: "#a78bfa",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
    ]);
  });

  it("uses native chain[] option legs for headline prices", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000, prev_close: 24990 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        {
          strike: 25000,
          ce: { ltp: 112.5 },
          pe: { ltp: 98.25 },
        },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(screen.getByText("210.75")).toBeInTheDocument();
    });
    expect(screen.getByText("112.5")).toBeInTheDocument();
    expect(screen.getByText("98.25")).toBeInTheDocument();
    await waitFor(() => {
      expect(chartMocks.createdLineSeries[0]?.setData).toHaveBeenCalledWith(
        expect.arrayContaining([expect.objectContaining({ value: 210.75 })]),
      );
    });
  });
});

// ---------------------------------------------------------------------------
// Implied-move view (absorbed from the retired ImpliedMove widget, merge 2.15)
// ---------------------------------------------------------------------------

describe("StraddleWidget — implied-move view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    apiMocks.getExpiry.mockResolvedValue([]);
    apiMocks.getOptionChain.mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
    apiMocks.getPositionbook.mockResolvedValue([]);
  });

  it("opens on the σ-band view when params.view is impliedmove", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Implied move range bar")).toBeInTheDocument();
    });
    expect(screen.getByText("Expected Range")).toBeInTheDocument();
    // The chart plane's overlay toggles belong to the other view only.
    expect(screen.queryByText("Overlay")).not.toBeInTheDocument();
  });

  it("defaults to the straddle chart view when no params.view is given", () => {
    renderWidget();
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.queryByLabelText("Implied move range bar")).not.toBeInTheDocument();
  });

  it("persists the chosen view into the panel params", async () => {
    const updateParameters = vi.fn();
    const props = makeDockviewPanelProps({ params: {} });
    render(<StraddleWidget {...props} api={{ ...props.api, updateParameters }} />);

    screen.getByRole("button", { name: "Implied Move" }).click();

    await waitFor(() => {
      expect(updateParameters).toHaveBeenCalledWith({ view: "impliedmove" });
    });
  });

  // REWRITTEN PIN (was: "keeps the Sample data badge visible even when
  // connected"). The retired widget had no live source, so its badge was
  // unconditional. The σ bands now come from the live chain, so a live chain
  // must produce figures and no sample badge at all.
  it("shows no sample badge once the live chain yields an ATM straddle", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Implied move range bar")).toBeInTheDocument();
    });
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("No live option chain — implied move is unavailable"),
    ).not.toBeInTheDocument();
  });

  // REWRITTEN PIN (was: "shows the Sample data badge when disconnected"). With
  // no live chain the view must disclose the absence rather than substitute a
  // sample — the same honesty the chart view's empty states carry.
  it("discloses the absence of live data instead of showing sample figures", () => {
    renderWidget({ view: "impliedmove" });

    const badge = screen.getByLabelText(
      "No live option chain — implied move is unavailable",
    );
    expect(badge.textContent).toBe("No live data");
    expect(screen.getByText("Implied move needs a live ATM straddle quote")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Implied move range bar")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Probability zones table")).not.toBeInTheDocument();
  });

  it("renders the probability zones table from live bands", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Probability zones table")).toBeInTheDocument();
    });
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
    // move = 112.5 + 87.5 = 200 on a 25,000 spot
    expect(screen.getAllByText("25,200").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("24,800").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("25,400").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("24,600").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the ATM straddle premium breakdown from live legs", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByText("ATM CE Premium")).toBeInTheDocument();
    });
    expect(screen.getByText("ATM PE Premium")).toBeInTheDocument();
    expect(screen.getByText("Total (Implied Move)")).toBeInTheDocument();
    expect(screen.getByText("₹112.5")).toBeInTheDocument();
    expect(screen.getByText("₹87.5")).toBeInTheDocument();
    expect(screen.getByText("₹200")).toBeInTheDocument();
  });

  it("shows the implied move as a percentage of live spot", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    // 200 / 25,000 = 0.80%
    await waitFor(() => {
      expect(screen.getByText("±0.80% of spot")).toBeInTheDocument();
    });
    expect(screen.getByText("±₹200")).toBeInTheDocument();
  });

  // The retired widget's dropdown had 5 entries indexed into a 2-entry sample
  // array, so FINNIFTY rendered NIFTY's figures under a FINNIFTY label. Every
  // figure is now derived from the selected symbol's own live chain, so the
  // mislabel is unrepresentable — pinned here by the absence of any constant
  // table to index into.
  it("derives every figure from the fetched chain, never a symbol-indexed table", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(apiMocks.getOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "2026-07-30");
    });
    expect(apiMocks.getQuotes).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
  });
});

// ---------------------------------------------------------------------------
// σ arithmetic — ported from the retired ImpliedMove suite, now over the live
// derivation rather than a constant sample table.
// ---------------------------------------------------------------------------

describe("computeImpliedMove", () => {
  const live = { spot: 22350, atmStrike: 22350, cePremium: 142.5, pePremium: 138.2 };

  it("implied move equals CE + PE premium", () => {
    const data = computeImpliedMove(live);
    expect(data?.impliedMove).toBeCloseTo(live.cePremium + live.pePremium, 1);
  });

  it("upper bound equals spot + implied move", () => {
    const data = computeImpliedMove(live);
    expect(data?.upperBound).toBeCloseTo(live.spot + (data?.impliedMove ?? 0), 1);
  });

  it("lower bound equals spot - implied move", () => {
    const data = computeImpliedMove(live);
    expect(data?.lowerBound).toBeCloseTo(live.spot - (data?.impliedMove ?? 0), 1);
  });

  it("2 sigma bounds are twice as wide as 1 sigma bounds", () => {
    const data = computeImpliedMove(live);
    expect(data?.upper2Sigma).toBeCloseTo(live.spot + (data?.impliedMove ?? 0) * 2, 1);
    expect(data?.lower2Sigma).toBeCloseTo(live.spot - (data?.impliedMove ?? 0) * 2, 1);
  });

  it("implied move pct is the move as a percentage of spot", () => {
    const data = computeImpliedMove(live);
    expect(data?.impliedMovePct).toBeCloseTo(((142.5 + 138.2) / 22350) * 100, 4);
    expect(data?.impliedMovePct).toBeGreaterThan(0);
    expect(data?.impliedMovePct).toBeLessThan(10);
  });

  it("fails closed on missing or non-positive live inputs", () => {
    expect(computeImpliedMove({ ...live, spot: null })).toBeNull();
    expect(computeImpliedMove({ ...live, spot: 0 })).toBeNull();
    expect(computeImpliedMove({ ...live, atmStrike: undefined })).toBeNull();
    expect(computeImpliedMove({ ...live, cePremium: 0 })).toBeNull();
    expect(computeImpliedMove({ ...live, pePremium: null })).toBeNull();
    expect(computeImpliedMove({ ...live, spot: Number.NaN })).toBeNull();
  });
});
