/**
 * OI Analytics — heat view (the retired OI Heatmap widget's presentation).
 *
 * Everything the heat grid pinned before the merge lives here: the CE/PE strike
 * rows, the hover readout, the max-OI marker completeness rules, its expiry and
 * symbol races, and the deterministic sample chain.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

vi.mock("@/lib/market", () => ({ isMarketHours: vi.fn().mockReturnValue(false) }));

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
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import OIChartWidget from "../OIChartWidget";
import { buildSampleChain } from "../sampleData";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** The heat view is what the retired `oiheatmap` panel id resolves to. */
function renderHeat() {
  return render(
    <OIChartWidget {...makeDockviewPanelProps({ params: { view: "heat" } })} />,
    { wrapper },
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function selectSymbol(label: string) {
  fireEvent.click(screen.getByTestId("symbol-select"));
  fireEvent.click(await screen.findByRole("option", { name: label }));
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
  mockMode.current = "live";
  mockUseBrokerConnected.mockReturnValue(false);
  apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
  apiMocks.getOptionChain.mockResolvedValue(null);
  apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
  apiMocks.getMaxPain.mockResolvedValue({});
  apiMocks.getHistory.mockResolvedValue([]);
});

describe("OI Analytics heat view — disconnected (sample data)", () => {
  it("renders the widget root", () => {
    renderHeat();
    expect(screen.getByTestId("oianalytics-widget")).toBeTruthy();
  });

  it("renders CE and PE row labels in the strike grid", () => {
    renderHeat();
    expect(screen.getAllByText(/^CE$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/^PE$/i).length).toBeGreaterThan(0);
  });

  it("shows the colour legend (CE and PE labels in legend)", () => {
    renderHeat();
    // At least two of each: the row label and the legend swatch label.
    expect(screen.getAllByText(/^CE$/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/^PE$/i).length).toBeGreaterThanOrEqual(2);
  });

  it("badges the sample chain rather than presenting it as live", () => {
    renderHeat();
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("renders symbol selector with NIFTY as default option", () => {
    renderHeat();
    expect(screen.getByTestId("symbol-select").textContent).toContain("NIFTY");
  });

  it("renders more than 10 strike cells from the sample chain", () => {
    renderHeat();
    const cells = screen
      .getAllByRole("generic")
      .filter((el) => el.className?.includes("tabular-nums") && /\d/.test(el.textContent ?? ""));
    expect(cells.length).toBeGreaterThan(10);
  });

  it("builds a deterministic sample chain so the same figures render every load", () => {
    const first = buildSampleChain(24_750, 50, 21);
    const second = buildSampleChain(24_750, 50, 21);
    expect(first).toEqual(second);
    expect(first.every((row) => row.ceOi > 0 && row.peOi > 0)).toBe(true);
  });
});

describe("OI Analytics heat view — connected with live data", () => {
  const mockChain = {
    chain: [
      { strike: 24700, ce: { oi: 120_000, oi_change: 5_000 }, pe: { oi: 80_000, oi_change: -2_000 } },
      { strike: 24750, ce: { oi: 200_000, oi_change: 10_000 }, pe: { oi: 180_000, oi_change: 8_000 } },
      { strike: 24800, ce: { oi: 95_000, oi_change: -3_000 }, pe: { oi: 110_000, oi_change: 4_000 } },
    ],
    atm_strike: 24750,
    underlying_ltp: 24750,
    pcr: 1.15,
  };

  it("drops the sample badge on a live connected read", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue(mockChain);
    renderHeat();
    await waitFor(() => expect(screen.getByText("24750")).toBeInTheDocument());
    expect(screen.queryByRole("status", { name: /sample data/i })).toBeNull();
  });

  it("badges Explore mode even though a broker reads as connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockMode.current = "explore";
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue(mockChain);
    renderHeat();
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("trims expiry payloads before enabling the live chain", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: [null, "", "   ", " 24-APR-25 "] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 24750,
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
    });

    renderHeat();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith("NIFTY", "NFO", "");
  });

  it("refresh button is enabled when connected with a validated expiry", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue(mockChain);
    renderHeat();
    await waitFor(() => expect(screen.getByTestId("refresh-btn")).not.toBeDisabled());
  });

  it("refresh button is disabled when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderHeat();
    expect(screen.getByTestId("refresh-btn")).toBeDisabled();
  });

  it("renders an absent live OI change as unavailable instead of +0", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
      underlying_ltp: 24750,
    });
    renderHeat();

    const callOi = await screen.findByText("100");
    fireEvent.mouseEnter(callOi.parentElement!);

    const tooltip = await screen.findByTestId("oi-tooltip");
    expect(tooltip.textContent).toContain("OI Chg--");
    expect(tooltip.textContent).not.toContain("+0");
  });

  it("renders missing live OI as unavailable while preserving explicit zero", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [{ strike: 24750, ce: {}, pe: { oi: 0 } }],
      underlying_ltp: 24750,
    });
    renderHeat();

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
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: {}, pe: { oi: 100 } },
        { strike: 24800, ce: { oi: 200 }, pe: {} },
      ],
      underlying_ltp: 24750,
    });
    const { container } = renderHeat();

    expect(await screen.findByText("200")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(0);
  });

  it("marks only the complete positive OI side", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: {}, pe: { oi: 100 } },
        { strike: 24800, ce: { oi: 200 }, pe: { oi: 180 } },
      ],
      underlying_ltp: 24750,
    });
    const { container } = renderHeat();

    expect((await screen.findByText("180")).parentElement).toHaveAttribute("data-max-oi", "true");
    expect(screen.getByText("200").parentElement).not.toHaveAttribute("data-max-oi");
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(1);
  });

  it("drops legacy rows without a positive strike instead of rendering strike zero", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      calls: [
        { oi: 100 },
        { strike: 0, oi: 100 },
        { strike_price: 24750, oi: 120 },
      ],
      puts: [
        { strike_price: 24750, oi: 80 },
        { strike_price: 24800, oi: 90 },
      ],
      underlying_ltp: 24750,
    });

    renderHeat();

    expect(await screen.findByText("24750")).toBeInTheDocument();
    expect(screen.getByText("24800")).toBeInTheDocument();
    expect(screen.queryByText(/^0$/)).not.toBeInTheDocument();
  });

  it("preserves explicit zero OI without marking an all-zero side as maximum", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: { oi: 0 }, pe: { oi: 0 } },
        { strike: 24800, ce: { oi: 0 }, pe: { oi: 0 } },
      ],
      underlying_ltp: 24750,
    });
    const { container } = renderHeat();

    expect(await screen.findAllByText("0")).toHaveLength(4);
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(0);
  });

  it("marks the strictly positive maxima when both live sides are complete", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: [
        { strike: 24750, ce: { oi: 100 }, pe: { oi: 180 } },
        { strike: 24800, ce: { oi: 200 }, pe: { oi: 80 } },
      ],
      underlying_ltp: 24750,
    });
    const { container } = renderHeat();

    expect((await screen.findByText("200")).parentElement).toHaveAttribute("data-max-oi", "true");
    expect(screen.getByText("180").parentElement).toHaveAttribute("data-max-oi", "true");
    expect(container.querySelectorAll("[data-max-oi='true']")).toHaveLength(2);
  });

  it("does not let an older expiry request overwrite the newer selection", async () => {
    const firstExpiry = deferred<Record<string, unknown>>();
    const secondExpiry = deferred<Record<string, unknown>>();
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25", "01-MAY-25"] });
    apiMocks.getOptionChain.mockImplementation((_symbol: string, _exchange: string, expiry: string) => (
      expiry === "24-APR-25" ? firstExpiry.promise : secondExpiry.promise
    ));
    renderHeat();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "24-APR-25"));
    // The expiry strip prints a formatted label, not the raw broker token.
    fireEvent.click(await screen.findByRole("button", { name: "1 May" }));
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "01-MAY-25"));

    await act(async () => {
      secondExpiry.resolve({
        chain: [{ strike: 24800, ce: { oi: 100 }, pe: { oi: 200 } }],
        underlying_ltp: 24800,
        pcr: 2,
      });
      await secondExpiry.promise;
    });
    expect(await screen.findByText("24800")).toBeInTheDocument();

    await act(async () => {
      firstExpiry.resolve({
        chain: [{ strike: 24700, ce: { oi: 300 }, pe: { oi: 400 } }],
        underlying_ltp: 24700,
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
    apiMocks.getExpiry.mockImplementation((symbol: string) => (
      symbol === "NIFTY"
        ? Promise.resolve({ expiry: ["24-APR-25"] })
        : bankExpiry.promise
    ));
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 24750,
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
    });

    renderHeat();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));

    await selectSymbol("BANKNIFTY");
    await act(async () => { await Promise.resolve(); });
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith("BANKNIFTY", "NFO", "24-APR-25");

    await act(async () => {
      bankExpiry.resolve({ expiry: ["01-MAY-25"] });
      await bankExpiry.promise;
    });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "01-MAY-25",
    ));
  });

  it("does not let an abandoned same-key request block a validated identity round trip", async () => {
    const hungNifty = deferred<Record<string, unknown>>();
    let niftyCalls = 0;
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockImplementation((symbol: string) => Promise.resolve({
      expiry: [symbol === "NIFTY" ? "24-APR-25" : "01-MAY-25"],
    }));
    apiMocks.getOptionChain.mockImplementation((symbol: string) => {
      if (symbol === "NIFTY" && niftyCalls++ === 0) return hungNifty.promise;
      const strike = symbol === "NIFTY" ? 24750 : 55000;
      return Promise.resolve({
        underlying_ltp: strike,
        chain: [{ strike, ce: { oi: 100 }, pe: { oi: 200 } }],
      });
    });

    renderHeat();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "24-APR-25",
    ));

    await selectSymbol("BANKNIFTY");
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "01-MAY-25",
    ));

    await selectSymbol("NIFTY");
    await waitFor(() => expect(
      apiMocks.getOptionChain.mock.calls.filter(([symbol]) => symbol === "NIFTY"),
    ).toHaveLength(2));
  });

  it("clears retained heatmap rows when the current refresh fails", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValueOnce({
      chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
      underlying_ltp: 24750,
    });
    renderHeat();

    expect(await screen.findByText("24750")).toBeInTheDocument();
    apiMocks.getOptionChain.mockRejectedValueOnce(new Error("chain refresh failed"));
    fireEvent.click(screen.getByTestId("refresh-btn"));

    expect(await screen.findByText(/chain refresh failed/)).toBeInTheDocument();
    expect(screen.queryByText("24750")).not.toBeInTheDocument();
  });

  it("uses the valid strike nearest authoritative spot when ATM is absent", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 92,
      chain: [
        { strike: 50, ce: { oi: 1000 }, pe: { oi: 1100 } },
        { strike: 90, ce: { oi: 1200 }, pe: { oi: 1300 } },
        { strike: 110, ce: { oi: 1400 }, pe: { oi: 1500 } },
        { strike: 200, ce: { oi: 1600 }, pe: { oi: 1700 } },
      ],
    });

    renderHeat();

    const grid = within(await screen.findByTestId("oi-heat-grid"));
    expect(grid.getByText("90")).toHaveClass("text-accent");
    expect(grid.getByText("110")).not.toHaveClass("text-accent");
  });

  it("uses the strike nearest authoritative spot instead of stale backend ATM", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 109,
      atm_strike: 90,
      chain: [
        { strike: 90, ce: { oi: 1200 }, pe: { oi: 1300 } },
        { strike: 110, ce: { oi: 1400 }, pe: { oi: 1500 } },
      ],
    });

    renderHeat();

    const grid = within(await screen.findByTestId("oi-heat-grid"));
    expect(grid.getByText("110")).toHaveClass("text-accent");
    expect(grid.getByText("90")).not.toHaveClass("text-accent");
  });

  it("shows validated supplied volume and leaves missing volume unavailable", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 24750,
      chain: [{ strike: 24750, ce: { oi: 101, volume: 123 }, pe: { oi: 202 } }],
    });

    renderHeat();

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
      apiMocks.getExpiry.mockResolvedValue({ expiry: ["24-APR-25"] });
      apiMocks.getOptionChain.mockReturnValue(pendingChain.promise);

      renderHeat();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        pendingChain.resolve({
          underlying_ltp: 24750,
          chain: [{ strike: 24750, ce: { oi: 100 }, pe: { oi: 200 } }],
        });
        await pendingChain.promise;
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
