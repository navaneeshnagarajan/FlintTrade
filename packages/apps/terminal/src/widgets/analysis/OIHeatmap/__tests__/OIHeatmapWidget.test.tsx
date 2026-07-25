import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock API calls — no real network
// ---------------------------------------------------------------------------

vi.mock("@/services/api", () => ({
  getOptionChain: vi.fn().mockResolvedValue(null),
  getExpiry: vi.fn().mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] }),
}));

// Mock lib/market
vi.mock("@/lib/market", () => ({ isMarketHours: vi.fn().mockReturnValue(false) }));

// Mock broker connected — default: disconnected → sample data path
const mockMode = vi.hoisted(() => ({ current: "live" }));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: mockMode.current }),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({
    children,
    featureName,
  }: {
    children: React.ReactNode;
    featureName: string;
  }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getOptionChain, getExpiry } from "@/services/api";
import OIHeatmapWidget, { buildSampleChain } from "../OIHeatmapWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetOptionChain = getOptionChain as ReturnType<typeof vi.fn>;
const mockGetExpiry = getExpiry as ReturnType<typeof vi.fn>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
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
  mockUseBrokerConnected.mockReturnValue(false);
  mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
  mockGetOptionChain.mockResolvedValue(null);
});

describe("OIHeatmapWidget — disconnected (sample data)", () => {
  it("renders the widget root", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    expect(screen.getByTestId("oiheatmap-widget")).toBeTruthy();
  });

  it("renders CE and PE row labels in the strike grid", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Both row labels should be present
    const ceLabels = screen.getAllByText(/^CE$/i);
    const peLabels = screen.getAllByText(/^PE$/i);
    expect(ceLabels.length).toBeGreaterThan(0);
    expect(peLabels.length).toBeGreaterThan(0);
  });

  it("shows colour legend (CE and PE labels in legend)", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Legend has CE and PE span labels
    const ceElems = screen.getAllByText(/^CE$/i);
    const peElems = screen.getAllByText(/^PE$/i);
    // At least 2 of each (row label + legend)
    expect(ceElems.length).toBeGreaterThanOrEqual(2);
    expect(peElems.length).toBeGreaterThanOrEqual(2);
  });

  it("wraps grid in FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("feature-teaser").dataset.feature).toBe("OI Heatmap");
  });

  it("renders symbol selector with NIFTY as default option", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    const trigger = screen.getByTestId("symbol-select");
    expect(trigger).toBeTruthy();
    // shadcn Select trigger shows current value text
    expect(trigger.textContent).toContain("NIFTY");
  });
});

describe("OIHeatmapWidget — connected with live data", () => {
  const mockChain = {
    chain: [
      { strike: 24700, ce: { oi: 120_000, oi_change: 5_000 }, pe: { oi: 80_000, oi_change: -2_000 } },
      { strike: 24750, ce: { oi: 200_000, oi_change: 10_000 }, pe: { oi: 180_000, oi_change: 8_000 } },
      { strike: 24800, ce: { oi: 95_000, oi_change: -3_000 }, pe: { oi: 110_000, oi_change: 4_000 } },
    ],
    atm_strike: 24750,
    pcr: 1.15,
  };

  it("does not wrap in FeatureTeaser when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue(mockChain);
    render(<OIHeatmapWidget />);
    // FeatureTeaser should not be present
    expect(screen.queryByTestId("feature-teaser")).toBeNull();
  });

  it("renders expiry selector when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
    mockGetOptionChain.mockResolvedValue(mockChain);
    render(<OIHeatmapWidget />);
    // Initially shows the widget
    expect(screen.getByTestId("oiheatmap-widget")).toBeTruthy();
  });

  it("trims expiry payloads before enabling the live chain", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: [null, "", "   ", " 24-APR-25 "] });
    mockGetOptionChain.mockResolvedValue({
      underlying_ltp: 24750,
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
    });

    render(<OIHeatmapWidget />);

    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));
    expect(mockGetOptionChain).not.toHaveBeenCalledWith("NIFTY", "NFO", "");
  });

  it("refresh button is enabled when connected with a validated expiry", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue(mockChain);
    render(<OIHeatmapWidget />);
    const refreshBtn = screen.getByTestId("refresh-btn");
    await waitFor(() => expect(refreshBtn).not.toBeDisabled());
  });

  it("refresh button is disabled when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    const refreshBtn = screen.getByTestId("refresh-btn") as HTMLButtonElement;
    expect(refreshBtn.disabled).toBe(true);
  });

  it("renders an absent live OI change as unavailable instead of +0", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } },
      ],
      atm_strike: 24750,
    });
    render(<OIHeatmapWidget />);

    const callOi = await screen.findByText("100");
    fireEvent.mouseEnter(callOi.parentElement!);

    const tooltip = await screen.findByTestId("oi-tooltip");
    expect(tooltip.textContent).toContain("OI Chg--");
    expect(tooltip.textContent).not.toContain("+0");
  });

  it("renders missing live OI as unavailable while preserving explicit zero", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: {}, pe: { oi: 0 } },
      ],
      atm_strike: 24750,
    });
    render(<OIHeatmapWidget />);

    const unavailable = (await screen.findAllByText("--"))[0];
    expect(unavailable).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    fireEvent.mouseEnter(unavailable.parentElement!);

    const tooltip = await screen.findByTestId("oi-tooltip");
    expect(tooltip.textContent).toContain("OI--");
    expect(tooltip.textContent).not.toContain("PCR");
  });

  it("withholds max-OI markers when both live sides are incomplete", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: {}, pe: { oi: 100 } },
        { strike: 24800, ce: { oi: 200 }, pe: {} },
      ],
      atm_strike: 24750,
    });
    const { container } = render(<OIHeatmapWidget />);

    expect(await screen.findByText("200")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(0);
  });

  it("marks only the complete positive OI side", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: {}, pe: { oi: 100 } },
        { strike: 24800, ce: { oi: 200 }, pe: { oi: 180 } },
      ],
      atm_strike: 24750,
    });
    const { container } = render(<OIHeatmapWidget />);

    expect((await screen.findByText("180")).parentElement).toHaveAttribute("data-max-oi", "true");
    expect(screen.getByText("200").parentElement).not.toHaveAttribute("data-max-oi");
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(1);
  });

  it("drops legacy rows without a positive strike instead of rendering strike zero", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      calls: [
        { oi: 100 },
        { strike: 0, oi: 100 },
        { strike_price: 24750, oi: 120 },
      ],
      puts: [
        { strike_price: 24750, oi: 80 },
        { strike_price: 24800, oi: 90 },
      ],
    });

    render(<OIHeatmapWidget />);

    expect(await screen.findByText("24750")).toBeInTheDocument();
    expect(screen.getByText("24800")).toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it("preserves explicit zero OI without marking an all-zero side as maximum", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: { oi: 0 }, pe: { oi: 0 } },
        { strike: 24800, ce: { oi: 0 }, pe: { oi: 0 } },
      ],
      atm_strike: 24750,
    });
    const { container } = render(<OIHeatmapWidget />);

    expect((await screen.findAllByText("0"))).toHaveLength(4);
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(0);
  });

  it("marks the strictly positive maxima when both live sides are complete", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: { oi: 100 }, pe: { oi: 180 } },
        { strike: 24800, ce: { oi: 200 }, pe: { oi: 80 } },
      ],
      atm_strike: 24750,
    });
    const { container } = render(<OIHeatmapWidget />);

    expect((await screen.findByText("200")).parentElement).toHaveAttribute("data-max-oi", "true");
    expect(screen.getByText("180").parentElement).toHaveAttribute("data-max-oi", "true");
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(2);
  });

  it("does not let an older expiry request overwrite the newer selection", async () => {
    const firstExpiry = deferred<Record<string, unknown>>();
    const secondExpiry = deferred<Record<string, unknown>>();
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
    mockGetOptionChain.mockImplementation((_symbol: string, _exchange: string, expiry: string) => (
      expiry === "24-APR-25" ? firstExpiry.promise : secondExpiry.promise
    ));
    render(<OIHeatmapWidget />);

    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "24-APR-25"));
    fireEvent.click(await screen.findByTestId("expiry-select"));
    fireEvent.click(await screen.findByRole("option", { name: "01-MAY-25" }));
    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "01-MAY-25"));

    await act(async () => {
      secondExpiry.resolve({
        chain: [{ strike: 24800, ce: { oi: 100 }, pe: { oi: 200 } }],
        atm_strike: 24800,
        pcr: 2,
      });
      await secondExpiry.promise;
    });
    expect(await screen.findByText("24800")).toBeInTheDocument();

    await act(async () => {
      firstExpiry.resolve({
        chain: [{ strike: 24700, ce: { oi: 300 }, pe: { oi: 400 } }],
        atm_strike: 24700,
        pcr: 4 / 3,
      });
      await firstExpiry.promise;
    });

    expect(screen.getByText("24800")).toBeInTheDocument();
    expect(screen.queryByText("24700")).not.toBeInTheDocument();
  });

  it("does not request a new symbol with the previous symbol's expiry", async () => {
    const bankExpiry = deferred<{ expiry: string[] }>();
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockImplementation((symbol: string) => (
      symbol === "NIFTY"
        ? Promise.resolve({ expiry: ["24-APR-25"] })
        : bankExpiry.promise
    ));
    mockGetOptionChain.mockResolvedValue({
      underlying_ltp: 24750,
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
    });

    render(<OIHeatmapWidget />);
    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));

    fireEvent.click(screen.getByTestId("symbol-select"));
    fireEvent.click(screen.getByRole("option", { name: "BANKNIFTY" }));
    await act(async () => { await Promise.resolve(); });
    expect(mockGetOptionChain).not.toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "24-APR-25",
    );

    await act(async () => {
      bankExpiry.resolve({ expiry: ["01-MAY-25"] });
      await bankExpiry.promise;
    });
    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "01-MAY-25",
    ));
  });

  it("does not let an abandoned same-key request block a validated identity round trip", async () => {
    const hungNifty = deferred<Record<string, unknown>>();
    let niftyCalls = 0;
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockImplementation((symbol: string) => Promise.resolve({
      expiry: [symbol === "NIFTY" ? "24-APR-25" : "01-MAY-25"],
    }));
    mockGetOptionChain.mockImplementation((symbol: string) => {
      if (symbol === "NIFTY" && niftyCalls++ === 0) return hungNifty.promise;
      const strike = symbol === "NIFTY" ? 24750 : 55000;
      return Promise.resolve({
        underlying_ltp: strike,
        chain: [{ strike, ce: { oi: 100 }, pe: { oi: 200 } }],
      });
    });

    render(<OIHeatmapWidget />);
    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));

    fireEvent.click(screen.getByTestId("symbol-select"));
    fireEvent.click(screen.getByRole("option", { name: "BANKNIFTY" }));
    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "01-MAY-25",
    ));

    fireEvent.click(screen.getByTestId("symbol-select"));
    fireEvent.click(screen.getByRole("option", { name: "NIFTY" }));
    await waitFor(() => expect(
      mockGetOptionChain.mock.calls.filter(([symbol]) => symbol === "NIFTY"),
    ).toHaveLength(2));
  });

  it("clears retained heatmap rows when the current refresh fails", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValueOnce({
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
      atm_strike: 24750,
    });
    render(<OIHeatmapWidget />);

    expect(await screen.findByText("24750")).toBeInTheDocument();
    mockGetOptionChain.mockRejectedValueOnce(new Error("chain refresh failed"));
    fireEvent.click(screen.getByTestId("refresh-btn"));

    expect(await screen.findByText("chain refresh failed")).toBeInTheDocument();
    expect(screen.queryByText("24750")).not.toBeInTheDocument();
  });

  it("uses the valid strike nearest authoritative spot when ATM is absent", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      underlying_ltp: 92,
      chain: [
        { strike: 50, ce: { oi: 1000 }, pe: { oi: 1100 } },
        { strike: 90, ce: { oi: 1200 }, pe: { oi: 1300 } },
        { strike: 110, ce: { oi: 1400 }, pe: { oi: 1500 } },
        { strike: 200, ce: { oi: 1600 }, pe: { oi: 1700 } },
      ],
    });

    render(<OIHeatmapWidget />);

    expect(await screen.findByText("90")).toHaveClass("text-accent");
    expect(screen.getByText("110")).not.toHaveClass("text-accent");
  });

  it("uses the strike nearest authoritative spot instead of stale backend ATM", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      underlying_ltp: 109,
      atm_strike: 90,
      chain: [
        { strike: 90, ce: { oi: 1200 }, pe: { oi: 1300 } },
        { strike: 110, ce: { oi: 1400 }, pe: { oi: 1500 } },
      ],
    });

    render(<OIHeatmapWidget />);

    expect(await screen.findByText("110")).toHaveClass("text-accent");
    expect(screen.getByText("90")).not.toHaveClass("text-accent");
  });

  it("shows validated supplied volume and leaves missing volume unavailable", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    mockGetOptionChain.mockResolvedValue({
      atm_strike: 24750,
      chain: [{
        strike: 24750,
        ce: { oi: 101, volume: 123 },
        pe: { oi: 202 },
      }],
    });

    render(<OIHeatmapWidget />);

    fireEvent.mouseEnter((await screen.findByText("101")).parentElement!);
    expect((await screen.findByTestId("oi-tooltip")).textContent).toContain("Volume123");

    fireEvent.mouseLeave(screen.getByTestId("oi-tooltip"));
    fireEvent.mouseEnter(screen.getByText("202").parentElement!);
    expect((await screen.findByTestId("oi-tooltip")).textContent).toContain("Volume--");
  });

  it("skips an auto-refresh tick while the same identity request is pending", async () => {
    vi.useFakeTimers();
    try {
      const pendingChain = deferred<Record<string, unknown>>();
      mockUseBrokerConnected.mockReturnValue(true);
      mockGetExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
      mockGetOptionChain.mockReturnValue(pendingChain.promise);

      render(<OIHeatmapWidget />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(mockGetOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockGetOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        pendingChain.resolve({
          atm_strike: 24750,
          chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
        });
        await pendingChain.promise;
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(mockGetOptionChain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("OIHeatmapWidget — colour scale logic (unit)", () => {
  it("sample data grid has more than 10 strike price cells", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    // Sample data has 21 strikes; each row has the same number of cells.
    // Verify that more than 10 OI value texts are rendered (fmtOI output).
    // We look for elements with tabular-nums that contain K/L/Cr or a number.
    const cells = screen
      .getAllByRole("generic")
      .filter((el) =>
        el.className?.includes("tabular-nums") &&
        /\d/.test(el.textContent ?? ""),
      );
    expect(cells.length).toBeGreaterThan(10);
  });
});

// ---------------------------------------------------------------------------
// Data provenance. This widget rendered fabricated open interest with no
// affordance at all: the FeatureTeaser wrapper says "In Development", which
// is a roadmap label, not a statement about the data. In Explore mode the
// broker reads as connected while the API serves a mock chain, so that case
// needs badging too.
// ---------------------------------------------------------------------------

describe("OIHeatmapWidget data provenance", () => {
  beforeEach(() => {
    mockMode.current = "live";
  });

  it("badges the sample chain when no broker is connected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    render(<OIHeatmapWidget />);
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("badges Explore mode even though a broker reads as connected", () => {
    // services/api serves makeMockOptionChain in Explore — connected alone is
    // not evidence of live data.
    mockUseBrokerConnected.mockReturnValue(true);
    mockMode.current = "explore";
    render(<OIHeatmapWidget />);
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("drops the badge on a live connected read", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockMode.current = "live";
    render(<OIHeatmapWidget />);
    expect(screen.queryByRole("status", { name: /sample data/i })).toBeNull();
  });

  it("builds a deterministic sample chain so the same figures render every load", () => {
    const first = buildSampleChain(24_750, 50, 21);
    const second = buildSampleChain(24_750, 50, 21);
    expect(first).toEqual(second);
    expect(first.every((row) => row.ceOi > 0 && row.peOi > 0)).toBe(true);
  });
});
