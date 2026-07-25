/**
 * IndicesTab.test — adapted from the retired GlobalIndices suite (the
 * codebase's strictest fail-closed provenance tests) plus the live NSE
 * index tick cards carried over from MarketSummary.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return { ...actual, getGlobalIndices: vi.fn() };
});

import { createStore, Provider } from "jotai";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getGlobalIndices } from "@/services/ftApi";
import type { GlobalIndexEntry } from "@/services/ftApi";
import IndicesTab, { currencyForIndex, vixBandFor } from "../tabs/IndicesTab";
import { SAMPLE_GLOBAL_INDICES } from "../sampleData";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockIndices = getGlobalIndices as ReturnType<typeof vi.fn>;

/** Jotai store seeded per test so index cards can be given a live tick. */
let store = createStore();

function seedTick(key: string, tick: { ltp: number; prevClose?: number }) {
  store.set(tickAtomFamily(key), tick as never);
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <Provider store={store}>
      <QueryClientProvider client={qc}>
        <IndicesTab />
      </QueryClientProvider>
    </Provider>,
  );
}

beforeEach(() => {
  store = createStore();
  mockConnected.mockReturnValue(false);
  mockIndices.mockReset();
  mockIndices.mockResolvedValue({
    indices: [],
    updated_at: new Date().toISOString(),
    is_sample_data: false,
  });
});

// ---------------------------------------------------------------------------
// Live NSE index cards (from MarketSummary)
// ---------------------------------------------------------------------------

describe("IndicesTab — NSE index cards", () => {
  it("shows an awaiting-tick state rather than a fabricated level", () => {
    // These cards once rendered a hardcoded sample with the chip pinned to
    // "Sample" forever. They read the live tick atoms now, so with no tick
    // they must say so instead of inventing a number.
    renderTab();
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/awaiting live price/i).length).toBeGreaterThan(0);
    const heading = screen.getByText("NSE Indices");
    expect(heading.querySelector("span")?.textContent).toBe("Sample");
  });

  it("renders a live index level once a tick arrives", () => {
    // 22150.4 against a 21965.15 previous close = +185.25 (+0.84%).
    seedTick("NSE_INDEX:NIFTY", { ltp: 22150.4, prevClose: 21965.15 });
    renderTab();

    expect(screen.getByText("22,150.4")).toBeInTheDocument();
    const heading = screen.getByText("NSE Indices");
    expect(heading.querySelector("span")?.textContent).toBe("Live");
  });
});

// ---------------------------------------------------------------------------
// Global indices table (from GlobalIndices)
// ---------------------------------------------------------------------------

describe("IndicesTab — global indices (disconnected)", () => {
  it("renders the section heading and table column headers", () => {
    renderTab();
    expect(screen.getByText("Global Indices")).toBeTruthy();
    expect(screen.getByText("Index")).toBeTruthy();
    expect(screen.getByText("LTP")).toBeTruthy();
    expect(screen.getByText("Chg")).toBeTruthy();
    expect(screen.getByText("Trend")).toBeTruthy();
  });

  it("renders region group headers from sample data", () => {
    renderTab();
    expect(screen.getByText("India")).toBeTruthy();
    expect(screen.getByText("US")).toBeTruthy();
    expect(screen.getByText("Europe")).toBeTruthy();
    expect(screen.getByText("Asia")).toBeTruthy();
  });

  it("renders sample index names", () => {
    renderTab();
    expect(screen.getByText("NIFTY 50")).toBeTruthy();
    expect(screen.getByText("S&P 500")).toBeTruthy();
    expect(screen.getByText("FTSE 100")).toBeTruthy();
    expect(screen.getByText("Nikkei 225")).toBeTruthy();
  });

  it("shows sample data label when disconnected", () => {
    renderTab();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("does not export a module-load freshness timestamp", async () => {
    const sampleData = await import("../sampleData");
    expect("SAMPLE_UPDATED_AT" in sampleData).toBe(false);
  });

  it("renders sparklines for each index row", () => {
    renderTab();
    const sparklines = screen.getAllByRole("img", { name: /30-day index sparkline/i });
    expect(sparklines.length).toBeGreaterThanOrEqual(10);
    expect(sparklines[0]).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparklines[0].querySelector("polyline")).not.toBeInTheDocument();
    expect(sparklines[0].querySelectorAll("path").length).toBeGreaterThan(0);
  });
});

describe("IndicesTab — global indices (connected)", () => {
  const LIVE_INDICES: GlobalIndexEntry[] = [
    {
      id: "NIFTY50",
      name: "NIFTY 50",
      region: "India",
      ltp: 22_500.5,
      change: 50.2,
      change_pct: 0.22,
      history: [22_400, 22_450, 22_500],
    },
  ];

  it("queries the live endpoint only when connected", () => {
    mockConnected.mockReturnValue(false);
    renderTab();
    expect(mockIndices).not.toHaveBeenCalled();
  });

  it("shows the honest empty state — and no sample rows — when the live response is empty", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: [],
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderTab();

    // Honest empty state is shown.
    expect(await screen.findByText("No global indices available")).toBeTruthy();
    // Fabricated sample rows must NOT appear for a connected user.
    expect(screen.queryByText("NIFTY 50")).toBeNull();
    expect(screen.queryByText("S&P 500")).toBeNull();
    // An explicitly live empty response has no sample-data affordance.
    expect(screen.queryByText("(sample data)")).toBeNull();
    expect(screen.queryByText(/Could not load global indices/i)).toBeNull();
  });

  it("renders live indices and no sample affordance when connected with data", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: LIVE_INDICES,
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderTab();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    expect(screen.queryByText("(sample data)")).toBeNull();
    expect(screen.queryByText("Sample data")).toBeNull();
    expect(screen.getByLabelText("Refresh global indices")).toBeTruthy();
    // A sample-only index must NOT appear alongside the single live row.
    expect(screen.queryByText("S&P 500")).toBeNull();
  });

  it("badges a connected response flagged is_sample_data — stub prices must never render as live", async () => {
    // The backend endpoint is currently a hardcoded stub that declares
    // is_sample_data: true and omits updated_at. A connected user must
    // still see the sample affordance and no invented freshness timestamp.
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({ indices: LIVE_INDICES, is_sample_data: true });
    renderTab();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    // Header badge + footer note both visible despite the connection.
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    // No fabricated "Updated: …" freshness claim when the payload has no
    // honest timestamp.
    expect(screen.queryByText(/Updated:/)).toBeNull();
    expect(screen.queryByLabelText("Refresh global indices")).toBeNull();
  });

  it("treats missing connected provenance as sample or unknown", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: LIVE_INDICES,
      updated_at: "2026-07-14T09:30:00.000Z",
    });
    renderTab();

    expect(await screen.findByText("NIFTY 50")).toBeTruthy();
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.getByText("(sample data)")).toBeTruthy();
    expect(screen.queryByLabelText("Refresh global indices")).toBeNull();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("distinguishes request failure from an empty response and retries honestly", async () => {
    mockConnected.mockReturnValue(true);

    let resolveRetry: ((value: { indices: GlobalIndexEntry[]; is_sample_data: false }) => void) | undefined;
    mockIndices
      .mockRejectedValueOnce(new Error("Indices API unavailable"))
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          resolveRetry = resolve;
        }),
      );

    renderTab();

    expect(await screen.findByText("Indices API unavailable")).toBeTruthy();
    expect(screen.queryByText("No global indices available")).toBeNull();

    const retry = screen.getByRole("button", { name: "Retry global indices" });
    fireEvent.click(retry);
    expect(await screen.findByText("Retrying global indices...")).toBeTruthy();

    await act(async () => {
      resolveRetry?.({ indices: [], is_sample_data: false });
    });

    expect(await screen.findByText("No global indices available")).toBeTruthy();
    expect(screen.queryByText("Indices API unavailable")).toBeNull();
  });

  it("renders the quote currency for a live row, from static metadata", async () => {
    // Ported from the Market Intelligence global-indices table (D4). Currency
    // is metadata about the index, not a price, so it applies to live rows too.
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: [{ ...LIVE_INDICES[0], id: "NDX", name: "Nasdaq 100" }],
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderTab();

    expect(await screen.findByText("Nasdaq 100")).toBeTruthy();
    expect(screen.getByLabelText("quoted in USD")).toBeTruthy();
  });

  it("renders NO currency for an index the map does not know — never a guess", async () => {
    mockConnected.mockReturnValue(true);
    mockIndices.mockResolvedValue({
      indices: [{ ...LIVE_INDICES[0], id: "KOSPI", name: "KOSPI", region: "Asia" as const }],
      updated_at: new Date().toISOString(),
      is_sample_data: false,
    });
    renderTab();

    expect(await screen.findByText("KOSPI")).toBeTruthy();
    expect(screen.queryByLabelText(/^quoted in/)).toBeNull();
  });

  it("stops automatic polling after a response with missing provenance", async () => {
    vi.useFakeTimers();
    mockConnected.mockReturnValue(true);

    let resolveRequest: ((value: { indices: GlobalIndexEntry[] }) => void) | undefined;
    mockIndices.mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <Provider store={store}>
        <QueryClientProvider client={qc}>
          <IndicesTab />
        </QueryClientProvider>
      </Provider>,
    );

    try {
      expect(mockIndices).toHaveBeenCalledTimes(1);
      await act(async () => {
        resolveRequest?.({ indices: LIVE_INDICES });
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("NIFTY 50")).toBeTruthy();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockIndices).toHaveBeenCalledTimes(1);
    } finally {
      view.unmount();
      qc.clear();
      vi.useRealTimers();
    }
  });
});

// ---------------------------------------------------------------------------
// Currency + GIFT Nifty (ported from the Market Intelligence global-indices
// table, ruling D4)
// ---------------------------------------------------------------------------

describe("IndicesTab — quote currency", () => {
  it("covers both id vocabularies — the backend stub's and this widget's sample", () => {
    // The two sets genuinely differ (NIFTY vs NIFTY50, NDX vs NASDAQ, FTSE vs
    // FTSE100, NIKKEI vs N225); a map that covered only one would blank the
    // column on live rows or on sample rows.
    expect(currencyForIndex("NIFTY")).toBe("INR");
    expect(currencyForIndex("NIFTY50")).toBe("INR");
    expect(currencyForIndex("NDX")).toBe("USD");
    expect(currencyForIndex("NASDAQ")).toBe("USD");
    expect(currencyForIndex("FTSE")).toBe("GBP");
    expect(currencyForIndex("FTSE100")).toBe("GBP");
    expect(currencyForIndex("NIKKEI")).toBe("JPY");
    expect(currencyForIndex("N225")).toBe("JPY");
  });

  it("separates the Asian currencies the region alone cannot", () => {
    expect(currencyForIndex("N225")).toBe("JPY");
    expect(currencyForIndex("HSI")).toBe("HKD");
    expect(currencyForIndex("SHCOMP")).toBe("CNY");
  });

  it("returns null for an unknown id rather than guessing", () => {
    expect(currencyForIndex("KOSPI")).toBeNull();
    expect(currencyForIndex("")).toBeNull();
  });

  it("labels every sample row's currency", () => {
    renderTab();
    // Every sample row is in the map, so each renders a currency suffix.
    expect(screen.getAllByLabelText(/^quoted in/)).toHaveLength(SAMPLE_GLOBAL_INDICES.length);
  });
});

describe("IndicesTab — GIFT Nifty", () => {
  it("carries GIFT Nifty in the India group, quoted in USD", () => {
    renderTab();
    expect(screen.getByText("GIFT Nifty")).toBeInTheDocument();

    const entry = SAMPLE_GLOBAL_INDICES.find((row) => row.id === "GIFTNIFTY");
    expect(entry?.region).toBe("India");
    expect(currencyForIndex("GIFTNIFTY")).toBe("USD");
  });
});

// ---------------------------------------------------------------------------
// India VIX regime (rehomed from the Market Intelligence India VIX tab, D4)
// ---------------------------------------------------------------------------

describe("IndicesTab — India VIX regime", () => {
  it("classifies each band at its boundaries", () => {
    expect(vixBandFor(9.8).label).toBe("Extreme complacency");
    expect(vixBandFor(11.99).label).toBe("Extreme complacency");
    expect(vixBandFor(12).label).toBe("Low volatility");
    expect(vixBandFor(15.99).label).toBe("Low volatility");
    expect(vixBandFor(16).label).toBe("Moderate volatility");
    expect(vixBandFor(20).label).toBe("Elevated fear");
    expect(vixBandFor(25).label).toBe("High fear");
    expect(vixBandFor(30).label).toBe("Panic zone");
    expect(vixBandFor(64.2).label).toBe("Panic zone");
  });

  it("classifies nothing until a tick arrives — the tool hardcoded 14.28", () => {
    renderTab();
    const heading = screen.getByText("Volatility Regime");
    expect(heading.querySelector("span")?.textContent).toBe("Sample");
    expect(screen.getByText(/Awaiting India VIX tick/)).toBeInTheDocument();
    expect(screen.queryByText("14.28")).toBeNull();
  });

  it("classifies the live tick and shows the change against previous close", () => {
    seedTick("NSE_INDEX:INDIAVIX", { ltp: 22.4, prevClose: 20.0 });
    renderTab();

    const heading = screen.getByText("Volatility Regime");
    expect(heading.querySelector("span")?.textContent).toBe("Live");
    // Scoped: the NSE index strip above carries its own INDIAVIX card off the
    // SAME tick, which is the point — one source, so the two cannot disagree.
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const regime = within(section as HTMLElement);
    expect(regime.getByText("22.40")).toBeInTheDocument();
    expect(regime.getByText("Elevated fear")).toBeInTheDocument();
    expect(regime.getByText(/\+2\.40 \(\+12\.00%\)/)).toBeInTheDocument();
  });

  it("renders the full band ladder as the operator's reference", () => {
    renderTab();
    for (const range of ["Below 12", "12 – 16", "16 – 20", "20 – 25", "25 – 30", "Above 30"]) {
      expect(screen.getByText(range)).toBeInTheDocument();
    }
  });

  it("does NOT port the tool's hardcoded 52-week range — no such series exists", () => {
    seedTick("NSE_INDEX:INDIAVIX", { ltp: 14.28, prevClose: 14.7 });
    renderTab();
    expect(screen.queryByText(/52-Week Range/i)).toBeNull();
    expect(screen.queryByText(/10\.84/)).toBeNull();
    expect(screen.queryByText(/28\.42/)).toBeNull();
  });
});
