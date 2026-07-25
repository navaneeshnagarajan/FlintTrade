/**
 * OI Analytics — signals view (the retired OI Signals widget's presentation).
 *
 * The tri-state Live / Mixed data / Sample data provenance rules survive
 * unchanged. What CHANGES here is the request: the retired widget hard-coded
 * exchange NFO and sent an EMPTY expiry, which the backend cannot resolve to a
 * live chain — so its "Live" state was unreachable in production. It now shares
 * this widget's symbol, exchange and expiry selection, and its refresh cadence.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
  getHistory: vi.fn(),
}));

const ftApiMocks = vi.hoisted(() => ({
  getOIChangeAnalysis: vi.fn(),
  getUnusualOI: vi.fn(),
}));

const state = vi.hoisted(() => ({ connected: false }));
const mockMode = vi.hoisted(() => ({ current: "live" }));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getMaxPain: apiMocks.getMaxPain,
  getHistory: apiMocks.getHistory,
}));

vi.mock("@/services/ftApi", () => ({
  getOIChangeAnalysis: (...a: unknown[]) => ftApiMocks.getOIChangeAnalysis(...a),
  getUnusualOI: (...a: unknown[]) => ftApiMocks.getUnusualOI(...a),
}));

vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => state.connected,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: mockMode.current }),
}));

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import OIChartWidget from "../OIChartWidget";

function analysisResponse(isSampleData?: boolean) {
  return {
    ...(isSampleData === undefined ? {} : { is_sample_data: isSampleData }),
    signals: [
      { strike: 25000, option_type: "CE", oi: 1_000_000, oi_change: 200_000, price_change: "up", signal: "Long Build-up", signal_short: "LB" },
    ],
    long_buildups: [25000],
    short_coverings: [],
    short_buildups: [],
    long_unwindings: [],
    summary: { "Long Build-up": 1 },
  };
}

function unusualResponse(isSampleData?: boolean) {
  return {
    ...(isSampleData === undefined ? {} : { is_sample_data: isSampleData }),
    unusual: [
      { strike: 25000, option_type: "CE", oi: 1_000_000, oi_change: 200_000, change_pct: 25, z_score: 3.1, direction: "addition" },
    ],
    count: 1,
    threshold: 2.0,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** The signals view is what the retired `oisignals` panel id resolves to. */
function renderSignals() {
  return render(
    <OIChartWidget {...makeDockviewPanelProps({ params: { view: "signals" } })} />,
    { wrapper },
  );
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  state.connected = false;
  mockMode.current = "live";
  apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
  apiMocks.getOptionChain.mockResolvedValue({
    underlying_ltp: 25_000,
    chain: [{ strike: 25_000, ce: { oi: 10 }, pe: { oi: 20 } }],
  });
  apiMocks.getQuotes.mockResolvedValue({ ltp: 25_000 });
  apiMocks.getMaxPain.mockResolvedValue({});
  apiMocks.getHistory.mockResolvedValue([]);
});

describe("OI Analytics signals view", () => {
  it("renders the signal table header", () => {
    renderSignals();
    expect(screen.getByText("Strike")).toBeInTheDocument();
    expect(screen.getByText("Signal")).toBeInTheDocument();
  });

  it("shows the Sample data badge and sample signals when disconnected", () => {
    renderSignals();
    expect(screen.getByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(screen.getAllByText("24500").length).toBeGreaterThan(0);
    // The queries are gated off while disconnected.
    expect(ftApiMocks.getOIChangeAnalysis).not.toHaveBeenCalled();
    expect(ftApiMocks.getUnusualOI).not.toHaveBeenCalled();
  });

  it("shows Live signals from the backend when connected", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(await screen.findByText("25000")).toBeInTheDocument();
  });

  it("sends the shared expiry and exchange instead of a hard-coded NFO and an empty expiry", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();

    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", "flat",
    ));
    expect(ftApiMocks.getUnusualOI).toHaveBeenCalledWith("NIFTY", "NFO", "2026-07-30");
    // An empty expiry is what made the retired widget's Live state unreachable.
    expect(ftApiMocks.getOIChangeAnalysis).not.toHaveBeenCalledWith("NIFTY", "NFO", "", "flat");
  });

  it("follows the symbol selector onto its own exchange", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();
    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalled());

    fireEvent.click(screen.getByTestId("symbol-select"));
    fireEvent.click(await screen.findByRole("option", { name: "SENSEX" }));

    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalledWith(
      "SENSEX", "BFO", "2026-07-30", "flat",
    ));
  });

  it("re-asks the backend when the price direction changes", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();
    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalled());

    fireEvent.click(screen.getByLabelText("Underlying price direction"));
    fireEvent.click(await screen.findByRole("option", { name: "Price ↑" }));

    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", "up",
    ));
  });

  it("shows mixed provenance instead of Live while unusual OI falls back locally", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockRejectedValue(new Error("unusual OI unavailable"));

    renderSignals();

    expect(await screen.findByText("Mixed data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.getByText("25000")).toBeInTheDocument();
    expect(screen.getByText("24500PE")).toBeInTheDocument();
  });

  it.each([
    ["analysis", true, false],
    ["unusual OI", false, true],
  ])("does not show Live when the %s backend response is sample data", async (_source, analysisSample, unusualSample) => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(analysisSample));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(unusualSample));

    renderSignals();

    expect(await screen.findByText("Mixed data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("requires explicit non-sample flags from both responses before showing Live", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse());
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse());

    renderSignals();

    expect(await screen.findByText("25000")).toBeInTheDocument();
    await waitFor(() => expect(ftApiMocks.getUnusualOI).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("never claims Live analytics while the chain plane is an Explore mock", async () => {
    state.connected = true;
    mockMode.current = "explore";
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();

    await waitFor(() => expect(ftApiMocks.getOIChangeAnalysis).toHaveBeenCalled());
    expect(screen.getByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("keeps the z-score unusual-OI chips", async () => {
    state.connected = true;
    ftApiMocks.getOIChangeAnalysis.mockResolvedValue(analysisResponse(false));
    ftApiMocks.getUnusualOI.mockResolvedValue(unusualResponse(false));

    renderSignals();

    expect(await screen.findByText("25000CE")).toBeInTheDocument();
    expect(screen.getByText("z3.1")).toBeInTheDocument();
    expect(screen.getByText(/\|z\| ≥ 2\.0/)).toBeInTheDocument();
  });

  it("keeps the LB/SC/SB/LU summary chips", () => {
    renderSignals();
    for (const short of ["LB", "SC", "SB", "LU"]) {
      expect(screen.getAllByText(short).length).toBeGreaterThan(0);
    }
  });
});
