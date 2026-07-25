/**
 * MarketSummaryWidget tests — per-section provenance over live-backed sources
 * (breadth route, FII/DII route, the NIFTY 50 quote sweep) with disclosed
 * SAMPLE_* fallbacks. The header badge reads "Sample data" only when EVERY
 * section is on its fallback; any live section flips it to "Mixed".
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

const mockBreadth = vi.fn();
const mockFiiDii = vi.fn();
vi.mock("@/services/ftApi.screener", () => ({
  getBreadthCurrent: () => mockBreadth() as Promise<unknown>,
  getFiiDiiData: () => mockFiiDii() as Promise<unknown>,
}));

const mockSectorMovers = vi.fn();
vi.mock("@/hooks/useSectorMovers", () => ({
  useSectorMovers: () => mockSectorMovers() as unknown,
}));

import { createStore, Provider } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import MarketSummaryWidget from "../MarketSummaryWidget";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

/** Jotai store seeded per test so index cards can be given a live tick. */
let store = createStore();

function seedTick(key: string, tick: { ltp: number; prevClose?: number }) {
  store.set(tickAtomFamily(key), tick as never);
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <Provider store={store}>
      <QueryClientProvider client={qc}>
        <MarketSummaryWidget />
      </QueryClientProvider>
    </Provider>,
  );
}

const SAMPLE_MOVERS_STATE = {
  data: [],
  movers: { gainers: [], losers: [] },
  isLoading: false,
  isLive: false,
  wantsLive: false,
  error: null,
  refetch: vi.fn(),
};

describe("MarketSummaryWidget", () => {
  beforeEach(() => {
    store = createStore();
    mockBreadth.mockReset();
    mockFiiDii.mockReset();
    mockSectorMovers.mockReset();
    // Default: every source on its sample fallback.
    mockBreadth.mockResolvedValue({
      is_sample_data: true,
      date: "2026-07-18",
      advances: 1, declines: 1, unchanged: 0,
      new_highs: 0, new_lows: 0, ad_ratio: 1, ad_line: 0,
      mcclellan_oscillator: 0, breadth_thrust: 0,
    });
    mockFiiDii.mockResolvedValue({ is_sample_data: true, latest: null, trend: null });
    mockSectorMovers.mockReturnValue(SAMPLE_MOVERS_STATE);
  });

  it("renders widget title and all sections", () => {
    renderWidget();
    expect(screen.getByText("Market Summary")).toBeInTheDocument();
    expect(screen.getByText("Indices")).toBeInTheDocument();
    expect(screen.getByText(/Market Breadth/)).toBeInTheDocument();
    expect(screen.getByText("Top Movers")).toBeInTheDocument();
    expect(screen.getByText("Sector Performance")).toBeInTheDocument();
    expect(screen.getByText("FII Net")).toBeInTheDocument();
    expect(screen.getByText("DII Net")).toBeInTheDocument();
    expect(screen.getByText(/A\/D ratio/i)).toBeInTheDocument();
  });

  it("shows the all-sample header badge when every source is a fallback", async () => {
    renderWidget();
    expect(await screen.findByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText(/Mixed/)).not.toBeInTheDocument();
    // Every section chip reads Sample; nothing claims Live.
    expect(screen.getAllByText("Sample").length).toBeGreaterThanOrEqual(4);
    expect(screen.queryAllByText("Live")).toHaveLength(0);
  });

  it("flips to Mixed and badges only the live section when breadth is real", async () => {
    mockBreadth.mockResolvedValue({
      is_sample_data: false,
      date: "2026-07-19",
      advances: 32, declines: 15, unchanged: 3,
      new_highs: 4, new_lows: 1, ad_ratio: 2.13, ad_line: 100,
      mcclellan_oscillator: 12, breadth_thrust: 0.6,
    });
    renderWidget();
    expect(await screen.findByText(/Mixed — see section chips/)).toBeInTheDocument();
    // The live breadth numbers render.
    expect(screen.getByText(/↑ 32/)).toBeInTheDocument();
    expect(screen.getByText(/↓ 15/)).toBeInTheDocument();
    expect(screen.getAllByText("Live")).toHaveLength(1);
  });

  it("renders live FII/DII figures from the route", async () => {
    mockFiiDii.mockResolvedValue({
      is_sample_data: false,
      latest: {
        trade_date: "2026-07-18",
        fii_buy: 0, fii_sell: 0, fii_net: -1234.56,
        dii_buy: 0, dii_sell: 0, dii_net: 987.65,
      },
      trend: null,
    });
    renderWidget();
    expect(await screen.findByText(/1234\.56/)).toBeInTheDocument();
    expect(screen.getByText(/987\.65/)).toBeInTheDocument();
    expect(screen.getByText(/FII \/ DII — 2026-07-18/)).toBeInTheDocument();
  });

  it("renders live movers and sectors from the quote sweep", () => {
    mockSectorMovers.mockReturnValue({
      ...SAMPLE_MOVERS_STATE,
      isLive: true,
      wantsLive: true,
      data: [
        { sector: "Banking", advancers: 4, decliners: 1, unchanged: 0,
          avgChange: 1.2, topGainer: "SBIN", topLoser: "HDFCBANK", signal: "strong" },
      ],
      movers: {
        gainers: [{ symbol: "SBIN", ltp: 850, changePct: 2.4 }],
        losers: [{ symbol: "WIPRO", ltp: 480, changePct: -1.8 }],
      },
    });
    renderWidget();
    expect(screen.getByText("SBIN")).toBeInTheDocument();
    expect(screen.getByText("WIPRO")).toBeInTheDocument();
    expect(screen.getByText("Banking")).toBeInTheDocument();
  });

  it("shows an awaiting-tick state for the index cards rather than a fabricated level", () => {
    // These cards used to render a hardcoded SAMPLE_INDICES array with the
    // chip pinned to "Sample" forever — fabricated index levels a connected
    // operator could never replace. They now read the live tick atoms, so
    // with no tick they must say so instead of inventing a number.
    renderWidget();
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/awaiting live price/i).length).toBeGreaterThan(0);
    const indicesHeading = screen.getByText("Indices");
    expect(indicesHeading.querySelector("span")?.textContent).toBe("Sample");
  });

  it("renders a live index level once a tick arrives", () => {
    // 22150.4 against a 21965.15 previous close = +185.25 (+0.84%).
    seedTick("NSE_INDEX:NIFTY", { ltp: 22150.4, prevClose: 21965.15 });
    renderWidget();

    expect(screen.getByText("22,150.4")).toBeInTheDocument();
    const indicesHeading = screen.getByText("Indices");
    expect(indicesHeading.querySelector("span")?.textContent).toBe("Live");
  });

  it("renders no refresh control or timestamp implying live data", () => {
    renderWidget();
    expect(screen.queryByRole("button", { name: /refresh/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/last updated/i)).not.toBeInTheDocument();
  });

  it("breadth and sector containers keep their aria labels", () => {
    renderWidget();
    expect(screen.getAllByLabelText(/Market breadth/i).length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Sector performance")).toBeInTheDocument();
  });
});
