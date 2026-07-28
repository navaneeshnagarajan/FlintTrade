/**
 * OI Analytics — Max Pain view (rehomed from the Market Intelligence Max Pain
 * tab, ruling D4).
 *
 * What these tests pin is the reason the view exists: `getMaxPain` has always
 * returned a per-strike pain distribution, and BOTH of its consumers (this
 * widget and the option chain) discarded everything but `max_pain_strike`. The
 * curve says whether the level is a sharp pin or a flat basin, so it is drawn
 * here — off the SAME 60 s response the butterfly rule already uses, gated on
 * the SAME explicit `is_sample_data: false`.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
  getHistory: vi.fn(),
}));

const mockMode = vi.hoisted(() => ({ current: "live" }));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getMaxPain: apiMocks.getMaxPain,
  getHistory: apiMocks.getHistory,
}));

vi.mock("@/services/ftApi", () => ({
  getOIChangeAnalysis: vi.fn().mockResolvedValue({ signals: [], summary: {} }),
  getUnusualOI: vi.fn().mockResolvedValue({ unusual: [], count: 0, threshold: 2 }),
}));

vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: mockMode.current }),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import OIChartWidget from "../OIChartWidget";
import { SAMPLE_PAIN_ROWS, SAMPLE_STRIKE_CELLS, SAMPLE_MAX_PAIN } from "../sampleData";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderPain(params: Record<string, unknown> = {}) {
  return render(
    <OIChartWidget {...makeWidgetPanelProps({ params: { view: "pain", ...params } })} />,
    { wrapper },
  );
}

const LIVE_CHAIN = {
  underlying_ltp: 24_200,
  chain: [
    { strike: 24_000, ce: { oi: 50_000, oi_change: 1_000 }, pe: { oi: 30_000, oi_change: -500 } },
    { strike: 24_200, ce: { oi: 80_000, oi_change: 2_000 }, pe: { oi: 70_000, oi_change: 1_000 } },
    { strike: 24_400, ce: { oi: 60_000, oi_change: -1_000 }, pe: { oi: 20_000, oi_change: -200 } },
  ],
};

const LIVE_PAIN = {
  is_sample_data: false,
  max_pain_strike: 24_200,
  strikes: [
    { strike: 24_000, call_oi: 50_000, put_oi: 30_000, call_pain: 0, put_pain: 9_000_000, total_pain: 9_000_000 },
    { strike: 24_200, call_oi: 80_000, put_oi: 70_000, call_pain: 10_000_000, put_pain: 4_000_000, total_pain: 14_000_000 },
    { strike: 24_400, call_oi: 60_000, put_oi: 20_000, call_pain: 26_000_000, put_pain: 0, total_pain: 26_000_000 },
  ],
};

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  mockMode.current = "live";
  mockUseBrokerConnected.mockReturnValue(false);
  apiMocks.getExpiry.mockResolvedValue(["2026-03-27"]);
  apiMocks.getOptionChain.mockResolvedValue(LIVE_CHAIN);
  apiMocks.getQuotes.mockResolvedValue({ ltp: 24_200 });
  apiMocks.getMaxPain.mockResolvedValue(LIVE_PAIN);
  apiMocks.getHistory.mockResolvedValue([]);
});

describe("OI Analytics Max Pain view", () => {
  it("is reachable as a panel view and labelled Max Pain", () => {
    renderPain();
    expect(screen.getByRole("button", { name: "Max Pain" })).toHaveAttribute("aria-pressed", "true");
  });

  it("renders the per-strike pain distribution the strike alone cannot convey", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderPain();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalled());

    // Every strike carries call pain, put pain and the total — the columns
    // every other consumer of getMaxPain throws away.
    expect(await screen.findByLabelText("Strike 24000 total pain 9000000")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Strike 24200 total pain 14000000 (max pain)"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Strike 24400 total pain 26000000")).toBeInTheDocument();
    expect(screen.getByText("Call pain")).toBeInTheDocument();
    expect(screen.getByText("Put pain")).toBeInTheDocument();
    expect(screen.getByText("Total pain")).toBeInTheDocument();
  });

  it("reuses the max-pain response — it adds no endpoint and no poll", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderPain();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(1));
    // The curve and the max-pain rule come off ONE response, so they cannot
    // disagree about which strike is the max.
    expect(await screen.findByText("Max Pain: 24,200")).toBeInTheDocument();
  });

  it("fails closed: a curve that is not explicitly attested live is not drawn", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getMaxPain.mockResolvedValue({ ...LIVE_PAIN, is_sample_data: true });

    renderPain();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalled());
    expect(
      await screen.findByText(/No attested max-pain distribution for NIFTY\./),
    ).toBeInTheDocument();
    expect(screen.queryByText("Total pain")).not.toBeInTheDocument();
  });

  it("fails closed when the response omits provenance entirely", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    const { is_sample_data: _dropped, ...unflagged } = LIVE_PAIN;
    apiMocks.getMaxPain.mockResolvedValue(unflagged);

    renderPain();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalled());
    expect(
      await screen.findByText(/No attested max-pain distribution for NIFTY\./),
    ).toBeInTheDocument();
  });

  it("survives a live response that carries only a strike and no curve", async () => {
    // The shape the other consumers get away with. It must render the empty
    // state, not throw.
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 24_200 });

    renderPain();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalled());
    expect(
      await screen.findByText(/No attested max-pain distribution for NIFTY\./),
    ).toBeInTheDocument();
  });

  it("renders the sample curve when disconnected, and never fetches", async () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderPain();

    expect(apiMocks.getMaxPain).not.toHaveBeenCalled();
    expect(screen.getByText("Total pain")).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
  });

  it("derives the sample curve from the sample chain, so the two cannot disagree", () => {
    // A second hand-typed pain table would let the sample max-pain rule and
    // the sample curve drift apart.
    expect(SAMPLE_PAIN_ROWS).toHaveLength(SAMPLE_STRIKE_CELLS.length);
    expect(SAMPLE_PAIN_ROWS.map((r) => r.strike)).toEqual(
      SAMPLE_STRIKE_CELLS.map((c) => c.strike),
    );
    for (const row of SAMPLE_PAIN_ROWS) {
      expect(row.total_pain).toBe(row.call_pain + row.put_pain);
      expect(row.total_pain).toBeGreaterThanOrEqual(0);
    }
    // The extreme strikes hurt more than the middle — a real pain curve, not a
    // flat fill.
    const first = SAMPLE_PAIN_ROWS[0].total_pain;
    const middle = SAMPLE_PAIN_ROWS[Math.floor(SAMPLE_PAIN_ROWS.length / 2)].total_pain;
    const last = SAMPLE_PAIN_ROWS[SAMPLE_PAIN_ROWS.length - 1].total_pain;
    expect(middle).toBeLessThan(first);
    expect(middle).toBeLessThan(last);
    // And the trough sits at the sample max-pain strike the other views draw.
    const trough = SAMPLE_PAIN_ROWS.reduce((min, row) =>
      row.total_pain < min.total_pain ? row : min,
    );
    expect(trough.strike).toBe(SAMPLE_MAX_PAIN);
  });

  it("hides the ΔOI filter, which cannot act on a server-side pain curve", () => {
    renderPain();
    expect(screen.queryByRole("button", { name: "OI Increase" })).not.toBeInTheDocument();
    // …and keeps it on the chain views.
    render(
      <OIChartWidget {...makeWidgetPanelProps({ params: { view: "bars" } })} />,
      { wrapper },
    );
    expect(screen.getByRole("button", { name: "OI Increase" })).toBeInTheDocument();
  });

  it("does not show the chain's CE/PE OI totals footer — pain is not open interest", () => {
    renderPain();
    // The footer's "Total" label is what marks the OI totals strip; the pain
    // view aggregates writer loss, so that strip would answer another question.
    expect(screen.queryByText("Total")).not.toBeInTheDocument();
  });

  it("explains what pain means so the trough is not misread", () => {
    renderPain();
    expect(screen.getByText(/option writers would pay out/i)).toBeInTheDocument();
  });
});
