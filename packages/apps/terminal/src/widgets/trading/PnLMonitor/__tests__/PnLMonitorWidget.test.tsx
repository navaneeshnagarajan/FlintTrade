/**
 * PnLMonitorWidget.test.tsx
 *
 * Semantic suite for the merged P&L Monitor widget (dedup 2.10).
 *
 * Every semantic pin from the retired IntradayPnL suite survives here with the
 * SAME numeric expectations (the P&L maths were declared canonical); the
 * equity-curve pin is adapted to the Lightweight Charts surface that replaced
 * the baseline sparkline. The P&L Dashboard tool's Summary and Drawdown
 * assertions are ported onto the new tabs. Chart-behaviour pins from the
 * retired MTM Monitor live in PnLMonitorChart.test.tsx (different mock plane).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getPositionbook: vi.fn().mockResolvedValue([]),
  getTradebook: vi.fn().mockResolvedValue([]),
  getFunds: vi.fn().mockResolvedValue({ availableCash: 250_000, usedMargin: 48_500, totalBalance: 298_500 }),
}));

vi.mock("@/services/ftApi.native", () => ({
  listNativeAccounts: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => true,
}));

// Lightweight Charts runtime — canvas does not exist in jsdom. Each series
// gets its OWN mock instance so the suite can tell the net-P&L series from
// the drawdown/equity ones.
const chartMocks = vi.hoisted(() => {
  interface SeriesMock {
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
    createPriceLine: ReturnType<typeof vi.fn>;
    removePriceLine: ReturnType<typeof vi.fn>;
  }
  const seriesInstances: SeriesMock[] = [];
  const makeSeries = (): SeriesMock => {
    const series: SeriesMock = {
      setData: vi.fn(),
      applyOptions: vi.fn(),
      createPriceLine: vi.fn(() => ({})),
      removePriceLine: vi.fn(),
    };
    seriesInstances.push(series);
    return series;
  };
  const chart = {
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
    remove: vi.fn(),
    resize: vi.fn(),
  };
  // The design-system shell hangs role="img" + aria-label on the canvas the
  // real runtime creates — the mock must plant one for those queries to work.
  const createChart = vi.fn((container: HTMLElement) => {
    container.appendChild(document.createElement("canvas"));
    return chart;
  });
  const addAreaSeries = vi.fn(() => makeSeries());
  return {
    seriesInstances,
    chart,
    createChart,
    addAreaSeries,
    reset() {
      seriesInstances.length = 0;
      createChart.mockClear();
      addAreaSeries.mockClear();
      chart.remove.mockClear();
    },
  };
});

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: { createChart: chartMocks.createChart },
  lightweightAreaRuntime: {
    createChart: chartMocks.createChart,
    addAreaSeries: chartMocks.addAreaSeries,
  },
}));

// ---------------------------------------------------------------------------
// Import component and mock references
// ---------------------------------------------------------------------------

import { getPositionbook, getTradebook } from "@/services/api";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import PnLMonitorWidget from "../PnLMonitorWidget";

const mockGetPositionbook = getPositionbook as ReturnType<typeof vi.fn>;
const mockGetTradebook = getTradebook as ReturnType<typeof vi.fn>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePosition(symbol: string, pnl: number, qty = 1) {
  // (ltp − averagePrice) × qty reproduces `pnl` so the locally computed MTM
  // (preferred over the broker figure) equals the requested value; closed
  // positions (qty = 0) fall back to the broker-supplied pnl.
  return {
    symbol,
    exchange: "NSE",
    product: "MIS",
    quantity: qty,
    averagePrice: 100,
    ltp: qty === 0 ? 110 : 100 + pnl / qty,
    pnl,
    pnlPercent: 10,
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={qc}>
      <PnLMonitorWidget {...makeDockviewPanelProps()} />
    </QueryClientProvider>,
  );
  return { ...utils, qc };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PnLMonitorWidget", () => {
  beforeEach(() => {
    // No fake timers: the widget does not own a poll loop — data flows
    // through the shared TanStack caches, whose fetch cycle needs real
    // microtask/macrotask scheduling to settle in tests.
    // Full reset (not clearAllMocks): pending mockResolvedValueOnce queues
    // from a prior test must not feed a later test's first shared-cache fetch.
    mockGetPositionbook.mockReset();
    mockGetTradebook.mockReset();
    mockGetPositionbook.mockResolvedValue([]);
    mockGetTradebook.mockResolvedValue([]);
    chartMocks.reset();
  });

  afterEach(() => {
    useModeStore.setState({ mode: "explore" });
    useConnectionStore.setState({ status: "disconnected" });
  });

  it("renders without crashing", async () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the P&L Monitor heading", async () => {
    renderWidget();
    expect(screen.getByText(/p&l monitor/i)).toBeInTheDocument();
  });

  it("has Live, Summary and Drawdown view tabs", async () => {
    renderWidget();
    expect(screen.getByRole("tab", { name: "Live" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Summary" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Drawdown" })).toBeInTheDocument();
  });

  it("shows stat card labels", async () => {
    renderWidget();
    await waitFor(() => expect(screen.getByText("Realised")).toBeInTheDocument());
    expect(screen.getByText("Unrealised")).toBeInTheDocument();
    expect(screen.getByText("Peak P&L")).toBeInTheDocument();
    expect(screen.getByText("Min P&L")).toBeInTheDocument();
    expect(screen.getByText("Max DD")).toBeInTheDocument();
  });

  it("displays net P&L as zero when no positions", async () => {
    mockGetPositionbook.mockResolvedValue([]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("0.00"),
    );
  });

  it("displays positive net P&L in profit colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", 500)]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.className).toMatch(/profit/);
  });

  it("feeds the equity curve through the shared Flint area runtime with the running net P&L", async () => {
    // Adapted from the retired IntradayPnL sparkline pin: the curve now
    // renders through the Lightweight Charts area pair the MTM Monitor
    // contributed, but the plotted VALUES are the same corrected net P&L.
    mockGetPositionbook
      .mockResolvedValueOnce([makePosition("SBIN", 500)])
      .mockResolvedValueOnce([makePosition("SBIN", -250)]);

    const { qc } = renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );

    // The Live view creates the net-P&L series first, then the drawdown one.
    expect(chartMocks.addAreaSeries).toHaveBeenCalledTimes(2);
    const pnlSeries = chartMocks.seriesInstances[0];
    await waitFor(() => {
      const sawFirstSnapshot = pnlSeries.setData.mock.calls.some((call) =>
        (call[0] as { value: number }[]).some((p) => p.value === 500),
      );
      expect(sawFirstSnapshot).toBe(true);
    });

    // Second positions refresh — with the shared cache the cadence belongs to
    // usePositions, so the test drives it via the query client.
    await act(async () => {
      await qc.refetchQueries();
      await new Promise((r) => setTimeout(r, 0));
    });

    await waitFor(() => {
      const calls = pnlSeries.setData.mock.calls;
      const lastData = calls[calls.length - 1][0] as { value: number }[];
      expect(lastData[lastData.length - 1].value).toBe(-250);
    });
  });

  it("displays negative net P&L in loss colour", async () => {
    mockGetPositionbook.mockResolvedValue([makePosition("SBIN", -300)]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("300"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.className).toMatch(/loss/);
  });

  it("shows error indicator when API fails", async () => {
    // In Explore (no account reads) the failure surfaces as the quiet header
    // dot — the loud banner + retry appears only when account reads are live
    // (covered in PnLMonitorChart.test.tsx).
    mockGetPositionbook.mockRejectedValue(new Error("Network error"));
    renderWidget();
    // The error state lands after the query's retry cycle — wait for the
    // dot itself rather than racing it with a fixed flush.
    await waitFor(() => {
      expect(document.querySelector(".bg-loss.rounded-full")).toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it("sums P&L from multiple positions", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN", 200),
      makePosition("RELIANCE", 300),
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
  });

  it("splits realised (qty=0) vs unrealised (qty>0) correctly", async () => {
    mockGetPositionbook.mockResolvedValue([
      makePosition("SBIN", 200, 0), // realised
      makePosition("RELIANCE", 300, 1), // unrealised
    ]);
    renderWidget();
    // Net should still be 500
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("500"),
    );
  });

  it("books partial-close realised from the tradebook for a still-open position", async () => {
    // Bought 100 @ 100, sold 40 @ 110 (realised 400), 60 still open. positionbook
    // shows only the open 60 @ avg 100, ltp 105 (unrealised 300) — its booked
    // realised is invisible without the tradebook.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 60, averagePrice: 100, ltp: 105, pnl: 99999, pnlPercent: 0 },
    ]);
    mockGetTradebook.mockResolvedValue([
      { tradeId: "T1", orderId: "O1", symbol: "SBIN", exchange: "NSE", action: "BUY", quantity: 100, price: 100, timestamp: "2026-07-09T09:20:00Z" },
      { tradeId: "T2", orderId: "O2", symbol: "SBIN", exchange: "NSE", action: "SELL", quantity: 40, price: 110, timestamp: "2026-07-09T10:00:00Z" },
    ]);
    renderWidget();
    // Realised = (110 − 100) × 40 = 400 (from tradebook, not double-counted in
    // unrealised); Unrealised = (105 − 100) × 60 = 300 (open MTM); Net = 700.
    await waitFor(() =>
      expect(screen.getByText("Realised").parentElement).toHaveTextContent("+₹400.00"),
    );
    expect(screen.getByText("Unrealised").parentElement).toHaveTextContent("+₹300.00");
    expect(screen.getByTestId("net-pnl").textContent).toContain("700");
  });

  // ── Broker numeric coercion + local P&L (OpenAlgo quirk 4) ────────────────

  it("computes open-position P&L locally instead of trusting a wrong broker pnl", async () => {
    // Broker reports a wildly wrong pnl; local MTM = (110 − 100) × 10 = 100.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 100, ltp: 110, pnl: 999999, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("100.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("9,99,999");
  });

  it("coerces string-typed quantity/ltp/average_price from real adapters", async () => {
    // Wire-format row: snake_case average_price and every numeric as a string.
    // Local MTM = (150 − 134) × 75 = 1,200.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "NIFTY24APR24000CE", exchange: "NFO", product: "NRML", quantity: "75", average_price: "134", ltp: "150", pnl: "0" },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("1,200.00"),
    );
  });

  it("treats a string \"0\" quantity as a closed position (realised broker pnl)", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: "0", pnl: "150.25" },
    ]);
    renderWidget();
    // Falls into the Realised bucket (local computation impossible for closed);
    // the same figure legitimately repeats in Net and Peak P&L, so assert the
    // buckets via their stat cards rather than a bare text query.
    await waitFor(() =>
      expect(screen.getByText("Realised").parentElement).toHaveTextContent("+₹150.25"),
    );
    expect(screen.getByText("Unrealised").parentElement).toHaveTextContent("+₹0.00");
    expect(screen.getByTestId("net-pnl").textContent).toContain("150.25");
  });

  it("falls back to the broker pnl when LTP or average price is missing", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 5, pnl: "250.5" },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("250.50"),
    );
  });

  it("does not fabricate a loss when the broker reports ltp: 0 for an open position", async () => {
    // Illiquid/pre-market open long: broker LTP is a literal 0 but the pnl
    // field is correct. (0 − 134) × 75 = −10,050 would be a fabricated loss;
    // the widget must fall back to the broker pnl instead.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "NIFTY24APR24000CE", exchange: "NFO", product: "NRML", quantity: 75, averagePrice: 134, ltp: 0, pnl: 375, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("375.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("10,050");
  });

  it("does not fabricate P&L when the broker reports averagePrice: 0", async () => {
    // averagePrice 0 would make (ltp − 0) × qty the full notional shown as P&L.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 10, averagePrice: 0, ltp: 110, pnl: 42.5, pnlPercent: 0 },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("42.50"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("1,100");
  });

  it("guards against non-numeric garbage instead of rendering NaN", async () => {
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: "abc", pnl: "N/A", ltp: "", average_price: null },
    ]);
    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("0.00"),
    );
    const netEl = screen.getByTestId("net-pnl");
    expect(netEl.textContent).not.toContain("NaN");
  });
});

// ---------------------------------------------------------------------------
// Summary view (ported from the P&L Dashboard tool's Summary tab)
// ---------------------------------------------------------------------------

describe("PnLMonitorWidget — Summary view", () => {
  beforeEach(() => {
    mockGetPositionbook.mockReset();
    mockGetTradebook.mockReset();
    mockGetPositionbook.mockResolvedValue([]);
    mockGetTradebook.mockResolvedValue([]);
    chartMocks.reset();
  });

  it("renders the summary breakdown through shared core donut and ranked bar primitives", async () => {
    mockGetPositionbook.mockResolvedValue([
      { averagePrice: 2400, ltp: 2550, pnl: 1500, pnlPercent: 6.25, product: "MIS", quantity: 10, symbol: "RELIANCE", exchange: "NSE" },
      { averagePrice: 3800, ltp: 3720, pnl: -800, pnlPercent: -2.1, product: "CNC", quantity: 10, symbol: "TCS", exchange: "NSE" },
    ]);

    renderWidget();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Summary" }));

    expect(await screen.findByRole("img", { name: "P&L breakdown by symbol" })).toHaveAttribute(
      "data-flint-chart",
      "donut",
    );
    expect(screen.getByRole("list", { name: "Top winners P&L" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Top losers P&L" })).toBeInTheDocument();
  });

  it("shows the same corrected day P&L on the Summary card as the Live headline", async () => {
    // Same partial-close book as the Live pin: net = 400 realised + 300
    // unrealised = 700. A raw Σ position MTM would read 300 and the raw
    // broker field 99,999 — both wrong.
    mockGetPositionbook.mockResolvedValue([
      { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 60, averagePrice: 100, ltp: 105, pnl: 99999, pnlPercent: 0 },
    ]);
    mockGetTradebook.mockResolvedValue([
      { tradeId: "T1", orderId: "O1", symbol: "SBIN", exchange: "NSE", action: "BUY", quantity: 100, price: 100, timestamp: "2026-07-09T09:20:00Z" },
      { tradeId: "T2", orderId: "O2", symbol: "SBIN", exchange: "NSE", action: "SELL", quantity: 40, price: 110, timestamp: "2026-07-09T10:00:00Z" },
    ]);

    renderWidget();
    await waitFor(() =>
      expect(screen.getByTestId("net-pnl").textContent).toContain("700"),
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Summary" }));

    const card = screen.getByText("Day P&L").parentElement as HTMLElement;
    expect(card).toHaveTextContent("₹700.00");
    expect(card).not.toHaveTextContent("₹300.00");
    expect(card).toHaveTextContent("1 open positions");
  });

  it("renders margin and balance cards from the funds feed", async () => {
    renderWidget();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Summary" }));

    await waitFor(() =>
      expect(screen.getByText("Available Margin").parentElement).toHaveTextContent("₹2.50L"),
    );
    expect(screen.getByText("Available Margin").parentElement).toHaveTextContent("Used: ₹48.50K");
    // 298500/100000 = 2.985 → binary float 2.98499…, so toFixed(2) truncates.
    expect(screen.getByText("Total Balance").parentElement).toHaveTextContent("₹2.98L");
  });
});

// ---------------------------------------------------------------------------
// Drawdown view (ported from the P&L Dashboard tool's Drawdown tab)
// ---------------------------------------------------------------------------

describe("PnLMonitorWidget — Drawdown view", () => {
  beforeEach(() => {
    mockGetPositionbook.mockReset();
    mockGetTradebook.mockReset();
    mockGetPositionbook.mockResolvedValue([]);
    mockGetTradebook.mockResolvedValue([]);
    chartMocks.reset();
  });

  it("renders drawdown charts through the shared Flint area runtime", async () => {
    mockGetTradebook.mockResolvedValue([
      { action: "BUY", exchange: "NSE", orderId: "o-1", price: 100, quantity: 10, symbol: "NIFTY", timestamp: "2026-05-29T09:30:00.000Z", tradeId: "t-1" },
      { action: "SELL", exchange: "NSE", orderId: "o-2", price: 120, quantity: 10, symbol: "NIFTY", timestamp: "2026-05-29T15:00:00.000Z", tradeId: "t-2" },
      { action: "BUY", exchange: "NSE", orderId: "o-3", price: 120, quantity: 10, symbol: "BANKNIFTY", timestamp: "2026-05-30T09:30:00.000Z", tradeId: "t-3" },
      { action: "SELL", exchange: "NSE", orderId: "o-4", price: 110, quantity: 10, symbol: "BANKNIFTY", timestamp: "2026-05-30T15:00:00.000Z", tradeId: "t-4" },
    ]);

    renderWidget();
    await waitFor(() => expect(mockGetTradebook).toHaveBeenCalled());

    // The Live view's own chart mounts first — count only the NEW series.
    const baseline = chartMocks.seriesInstances.length;
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Drawdown" }));

    await waitFor(() => {
      expect(chartMocks.seriesInstances.length).toBe(baseline + 2);
    });

    expect(screen.getByRole("img", { name: "P&L monitor equity curve chart" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "P&L monitor drawdown chart" })).toBeInTheDocument();

    // Pinned series values from the tool's suite: daily realised 200 then
    // −100 → cumulative equity [200, 100]; percent-of-peak drawdown [0, −50].
    const [equitySeries, drawdownSeries] = chartMocks.seriesInstances.slice(-2);
    expect(equitySeries.setData).toHaveBeenCalledWith([
      { time: "2026-05-29", value: 200 },
      { time: "2026-05-30", value: 100 },
    ]);
    expect(drawdownSeries.setData).toHaveBeenCalledWith([
      { time: "2026-05-29", value: 0 },
      { time: "2026-05-30", value: -50 },
    ]);

    // Headline cards derived from the same series.
    expect(screen.getByText("Max Drawdown").parentElement).toHaveTextContent("-50.00%");
    expect(screen.getByText("Net Cumulative P&L").parentElement).toHaveTextContent("₹100.00");
  });

  it("shows an empty state when there is no historical trade data", async () => {
    renderWidget();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Drawdown" }));

    expect(await screen.findByText("No historical trade data")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Provenance — both directions of the sample-data disclosure
// ---------------------------------------------------------------------------

describe("PnLMonitorWidget — provenance badge", () => {
  beforeEach(() => {
    mockGetPositionbook.mockReset();
    mockGetTradebook.mockReset();
    mockGetPositionbook.mockResolvedValue([]);
    mockGetTradebook.mockResolvedValue([]);
    chartMocks.reset();
  });

  afterEach(() => {
    useModeStore.setState({ mode: "explore" });
    useConnectionStore.setState({ status: "disconnected" });
  });

  it("shows the Sample data badge while no broker is connected", async () => {
    renderWidget();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("labels Practice mode data as practice, not sample", async () => {
    useModeStore.setState({ mode: "practice" });
    renderWidget();
    expect(screen.getByText("Practice data")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("hides the provenance badge when a broker is connected in Live mode", async () => {
    useModeStore.setState({ mode: "live" });
    useConnectionStore.setState({ status: "connected" });
    renderWidget();
    await waitFor(() => {
      expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    });
    expect(screen.queryByText("Practice data")).not.toBeInTheDocument();
  });
});
