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

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import MarketBreadthWidget from "../MarketBreadthWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

beforeEach(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("MarketBreadthWidget", () => {
  it("renders widget header with title", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText("Market Breadth")).toBeTruthy();
  });

  it("shows sample badge when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("keeps the sample badge while connected until real live data arrives", () => {
    // Fetch pending → no confirmed live snapshot yet → badge must stay (honest).
    global.fetch = vi.fn().mockImplementation(() => new Promise(() => {}));
    mockUseBrokerConnected.mockReturnValue(true);
    render(<MarketBreadthWidget />);
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("hides the sample badge once the backend returns real (non-sample) data", async () => {
    // The EXACT live payload breadth_routes emits: the derived multi-day /
    // 52-week indicators are explicit NULLs (a single live snapshot cannot
    // compute them). The schema previously rejected these nulls, so the real
    // live payload failed parsing and the badge stuck on Sample — this test
    // used to feed a null-free payload that masked the bug.
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
    render(<MarketBreadthWidget />);
    await vi.waitFor(() => expect(screen.queryByText("Sample")).toBeNull());
    // live advances rendered (parse really succeeded, not stale sample data)
    expect(screen.getByText("30")).toBeTruthy();
    // history is still sample → the series is captioned sample, with the
    // accumulation note (live current + sample history disclosed)
    expect(screen.getByText(/A\/D Line \(sample series\)/)).toBeTruthy();
    expect(screen.getByText(/live history accumulates while connected/)).toBeTruthy();
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
    render(<MarketBreadthWidget />);
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
    render(<MarketBreadthWidget />);
    // Badge persists because the data is the backend's sample, not live.
    expect(screen.getByText("Sample")).toBeTruthy();
  });

  it("renders A/D ratio section with Advances and Declines labels", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getAllByText("Advances").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Declines").length).toBeGreaterThan(0);
    expect(screen.getByText("A/D Ratio")).toBeTruthy();
  });

  it("renders breadth sparklines through shared Flint primitives", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);

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
    render(<MarketBreadthWidget />);
    expect(screen.getByText(/McClellan Osc/i)).toBeTruthy();
    expect(screen.getByText(/Breadth Thrust/i)).toBeTruthy();
  });

  it("renders 52-week highs vs lows section", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    expect(screen.getByText(/52-Week Highs vs Lows/i)).toBeTruthy();
    expect(screen.getByText("New Highs")).toBeTruthy();
    expect(screen.getByText("New Lows")).toBeTruthy();
  });

  it("refresh button is disabled when broker is disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<MarketBreadthWidget />);
    const btn = screen.getByRole("button", { name: /refresh market breadth/i });
    expect(btn).toBeDisabled();
  });
});
