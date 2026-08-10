/**
 * BreadthTab.test — adapted from the retired MarketBreadth widget suite,
 * plus the ported per-index breadth split (permanently badged sample) and
 * the MarketSummary Top Movers section with its Live/Sample chip.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

const mockSectorMovers = vi.fn();
vi.mock("@/hooks/useSectorMovers", () => ({
  useSectorMovers: () => mockSectorMovers() as unknown,
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import BreadthTab from "../tabs/BreadthTab";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

const SAMPLE_MOVERS_STATE = {
  data: [],
  movers: { gainers: [], losers: [] },
  isLoading: false,
  isLive: false,
  wantsLive: false,
  error: null,
  refetch: vi.fn(),
};

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  mockSectorMovers.mockReset();
  mockSectorMovers.mockReturnValue(SAMPLE_MOVERS_STATE);
});

describe("BreadthTab", () => {
  it("renders the breadth toolbar title", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getByText("Market Breadth (NSE)")).toBeTruthy();
  });

  it("shows sample badge when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getByTitle(/Showing sample breadth data/)).toBeTruthy();
  });

  it("keeps the sample badge while connected until real live data arrives", () => {
    // Fetch pending → no confirmed live snapshot yet → badge must stay (honest).
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
    mockUseBrokerConnected.mockReturnValue(true);
    render(<BreadthTab />);
    expect(screen.getByTitle(/Showing sample breadth data/)).toBeTruthy();
  });

  it("hides the sample badge once the backend returns real (non-sample) data", async () => {
    // The EXACT live payload breadth_routes emits: the derived multi-day /
    // 52-week indicators are explicit NULLs (a single live snapshot cannot
    // compute them).
    const realResponse = {
      status: "success",
      is_sample_data: false,
      data: {
        date: "2026-06-05",
        advances: 30, declines: 18, unchanged: 2,
        ad_ratio: 1.6667,
        new_highs: null, new_lows: null,
        ad_line: null, mcclellan_oscillator: null, breadth_thrust: null,
      },
    };
    global.fetch = vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            String(url).includes("/history")
              ? { status: "success", is_sample_data: true, count: 0, data: [] }
              : realResponse,
          ),
      }),
    );
    mockUseBrokerConnected.mockReturnValue(true);
    render(<BreadthTab />);
    await vi.waitFor(() => expect(screen.queryByTitle(/Showing sample breadth data/)).toBeNull());
    // live advances rendered (parse really succeeded, not stale sample data)
    expect(screen.getByText("30")).toBeTruthy();
    // history is still sample → the series is captioned sample, with the
    // accumulation note (live current + sample history disclosed)
    expect(screen.getByText(/A\/D Line \(sample series\)/)).toBeTruthy();
    expect(screen.getByText(/live history accumulates while connected/)).toBeTruthy();
  });

  it("keeps the sample badge when the payload omits is_sample_data entirely", async () => {
    // Provenance fails closed. The flag is optional in the schema, so a payload
    // without it parses cleanly and the numbers land — but an absent flag is
    // never evidence of live data, so the badge must stay.
    global.fetch = vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            String(url).includes("/history")
              ? { status: "success", count: 0, data: [] }
              : {
                  status: "success",
                  data: {
                    date: "2026-06-05",
                    advances: 47, declines: 11, unchanged: 2,
                    ad_ratio: 4.2727,
                    new_highs: null, new_lows: null,
                    ad_line: null, mcclellan_oscillator: null, breadth_thrust: null,
                  },
                },
          ),
      }),
    );
    mockUseBrokerConnected.mockReturnValue(true);
    render(<BreadthTab />);
    // The payload really was adopted…
    expect(await screen.findByText("47")).toBeTruthy();
    // …and it is still badged Sample, because the backend never claimed otherwise.
    expect(screen.getByTitle(/Showing sample breadth data/)).toBeTruthy();
  });

  it("charts REAL accumulated history when /breadth/history reports live points", async () => {
    const livePoint = (d: string, adv: number) => ({
      date: d, advances: adv, declines: 50 - adv - 2, unchanged: 2,
      ad_ratio: 1.0, new_highs: null, new_lows: null,
      ad_line: null, mcclellan_oscillator: null, breadth_thrust: null,
    });
    global.fetch = vi.fn().mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve(
            String(url).includes("/history")
              ? {
                  status: "success", is_sample_data: false, count: 3,
                  data: [livePoint("2026-06-09", 28), livePoint("2026-06-10", 31), livePoint("2026-06-11", 26)],
                }
              : { status: "success", is_sample_data: false, data: livePoint("2026-06-12", 30) },
          ),
      }),
    );
    mockUseBrokerConnected.mockReturnValue(true);
    render(<BreadthTab />);
    await vi.waitFor(() =>
      expect(screen.getByText(/A\/D Line \(accumulated live days\)/)).toBeTruthy(),
    );
  });

  it("keeps the sample badge when the backend reports its own sample fallback", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        status: "success",
        is_sample_data: true,
        data: {
          date: "2026-06-05",
          advances: 1000, declines: 1000, unchanged: 0,
          new_highs: 10, new_lows: 10,
          mcclellan_oscillator: 0, breadth_thrust: 0.5,
        },
      }),
    });
    mockUseBrokerConnected.mockReturnValue(true);
    render(<BreadthTab />);
    // Badge persists because the data is the backend's sample, not live.
    expect(screen.getByTitle(/Showing sample breadth data/)).toBeTruthy();
  });

  it("renders A/D ratio section with Advances and Declines labels", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getAllByText("Advances").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Declines").length).toBeGreaterThan(0);
    expect(screen.getByText("A/D Ratio")).toBeTruthy();
  });

  it("renders breadth sparklines through shared Flint primitives", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);

    const sparklines = [
      screen.getByRole("img", { name: "Market breadth advances sparkline" }),
      screen.getByRole("img", { name: "Market breadth declines sparkline" }),
      screen.getByRole("img", { name: "Market breadth net sparkline" }),
    ];

    for (const sparkline of sparklines) {
      expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
      expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
      expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
    }
  });

  it("renders McClellan Oscillator and Breadth Thrust sections", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getByText(/McClellan Osc/i)).toBeTruthy();
    expect(screen.getByText(/Breadth Thrust/i)).toBeTruthy();
  });

  it("renders 52-week highs vs lows section", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getByText(/52-Week Highs vs Lows/i)).toBeTruthy();
    expect(screen.getByText("New Highs")).toBeTruthy();
    expect(screen.getByText("New Lows")).toBeTruthy();
  });

  it("refresh button is disabled when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    const btn = screen.getByRole("button", { name: /refresh market breadth/i });
    expect(btn).toBeDisabled();
  });

  // -------------------------------------------------------------------------
  // Per-index breadth split (ported from Market Intelligence)
  // -------------------------------------------------------------------------

  it("renders the per-index breadth split with an UNCONDITIONAL sample badge", () => {
    // No live per-index breadth source exists; the section must disclose that
    // even when the broker is connected and headline breadth is live.
    mockUseBrokerConnected.mockReturnValue(true);
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
    render(<BreadthTab />);
    expect(screen.getByText("Index-wise Breadth")).toBeTruthy();
    expect(screen.getAllByText("NSE 500").length).toBeGreaterThan(0);
    expect(screen.getAllByText("BSE 500").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Nifty 50").length).toBeGreaterThan(0);
    const badge = screen.getByTitle(/no live per-index breadth source/i);
    expect(badge.textContent).toBe("Sample");
  });

  // -------------------------------------------------------------------------
  // Top movers (from MarketSummary)
  // -------------------------------------------------------------------------

  it("renders sample movers with a Sample chip when the quote sweep is not live", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<BreadthTab />);
    expect(screen.getByText("Top Movers")).toBeTruthy();
    // Disclosed sample rows render…
    expect(screen.getByText("INFY")).toBeTruthy();
    expect(screen.getByText("BANKBARODA")).toBeTruthy();
    // …under a Sample chip.
    const heading = screen.getByText("Top Movers");
    expect(heading.querySelector("span")?.textContent).toBe("Sample");
  });

  it("renders live movers with a Live chip when the quote sweep is healthy", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockSectorMovers.mockReturnValue({
      ...SAMPLE_MOVERS_STATE,
      isLive: true,
      wantsLive: true,
      movers: {
        gainers: [{ symbol: "SBIN", ltp: 850, changePct: 2.4 }],
        losers: [{ symbol: "WIPRO", ltp: 480, changePct: -1.8 }],
      },
    });
    render(<BreadthTab />);
    expect(screen.getByText("SBIN")).toBeTruthy();
    expect(screen.getByText("WIPRO")).toBeTruthy();
    const heading = screen.getByText("Top Movers");
    expect(heading.querySelector("span")?.textContent).toBe("Live");
    // The disclosed sample rows must NOT render alongside live rows.
    expect(screen.queryByText("BANKBARODA")).toBeNull();
  });
});
