/**
 * OptionChainWidget.test.tsx
 *
 * Smoke tests for the option chain widget.
 * Mocks API calls, Glide Data Grid, and custom hooks.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Provider as JotaiProvider, createStore } from "jotai";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const gridMocks = vi.hoisted(() => ({
  onCellClicked: null as ((item: [number, number]) => void) | null,
}));

// Glide Data Grid — canvas-based, cannot render in jsdom
vi.mock("@glideapps/glide-data-grid", () => {
  const DataEditor = vi.fn((props: { onCellClicked?: (item: [number, number]) => void }) => {
    gridMocks.onCellClicked = props.onCellClicked ?? null;
    return null;
  });
  return {
    __esModule: true,
    default: DataEditor,
  };
});

vi.mock("@glideapps/glide-data-grid/dist/index.css", () => ({}));

// Custom hooks
const optionChainHookMocks = vi.hoisted(() => ({
  overrides: {} as Record<string, unknown>,
}));

vi.mock("../useOptionChainData", () => ({
  useOptionChainData: () => ({
    expiries: ["2026-04-10", "2026-04-17", "2026-04-24"],
    selectedExpiry: null,
    setSelectedExpiry: vi.fn(),
    chain: null,
    loading: false,
    error: null,
    lastRefresh: null,
    fetchData: vi.fn(),
    strikes: [],
    atmStrike: null,
    maxCallOI: 0,
    maxPutOI: 0,
    totalCallOI: null,
    totalPutOI: null,
    spotLtp: null,
    spotChange: null,
    spotChangePct: null,
    spotUp: true,
    pcr: null,
    ...optionChainHookMocks.overrides,
  }),
}));

vi.mock("@/hooks/useGlideTheme", () => ({
  useGlideTheme: () => ({}),
}));

vi.mock("@/hooks/useSyntheticFuture", () => ({
  useSyntheticFuture: () => ({ data: null }),
}));

// Services
vi.mock("@/services/api", () => ({
  getInstruments: vi.fn().mockResolvedValue([]),
  getOptionSymbol: vi.fn().mockResolvedValue({ symbol: "TEST", exchange: "NFO" }),
  getSymbol: vi.fn().mockResolvedValue({}),
  placeOrder: vi.fn().mockResolvedValue({}),
  getMaxPain: vi.fn().mockResolvedValue({}),
  basketOrder: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Grid config
vi.mock("../gridConfig", () => ({
  getColumns: () => [{ id: "c_act", title: "CALL", width: 52 }],
  buildGetCellContent: () => () => ({ kind: "text", data: "", displayData: "" }),
  ATM_ROW_THEME: {},
}));

// TanStack Query — provide a wrapper
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import OptionChainWidget from "../OptionChainWidget";
import { getMaxPain, getSymbol } from "@/services/api";
import { broadcastInstrument, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OptionChainWidget", () => {
  beforeEach(() => {
    queryClient.clear();
    vi.clearAllMocks();
    optionChainHookMocks.overrides = {};
    gridMocks.onCellClicked = null;
    vi.mocked(getSymbol).mockReset().mockResolvedValue({} as never);
    vi.mocked(getMaxPain).mockReset().mockResolvedValue({} as never);
  });

  it("renders without crashing", () => {
    const { container } = render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(container.firstChild).toBeInTheDocument();
  });

  it("honours a pinned symbol from panel params (options-scalper preset pins NIFTY)", async () => {
    // The widget must seed from props.params.symbol, not just SYMBOLS[0].
    render(<OptionChainWidget params={{ symbol: "BANKNIFTY" }} />, { wrapper: Wrapper });
    await vi.waitFor(() =>
      expect(getSymbol).toHaveBeenCalledWith("BANKNIFTY", "NFO"),
    );
  });

  it("shows expiry buttons from the data hook", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    // The useOptionChainData mock returns 3 expiries; the widget shows up to 5.
    // Each expiry is formatted via fmtExpiry. Check at least one is present.
    const buttons = screen.getAllByRole("button");
    // There should be expiry buttons + view toggles + basket + strategy + refresh
    expect(buttons.length).toBeGreaterThan(3);
  });

  it("shows loading state when no expiry is selected", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(screen.getByText("Select an expiry to load chain")).toBeInTheDocument();
  });

  it("renders the Build Strategy button", () => {
    render(<OptionChainWidget />, { wrapper: Wrapper });
    const btn = screen.getByTitle("Build multi-leg option strategy");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });

  it("renders an incomplete live OI total as unavailable instead of adding zero", () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [] },
      strikes: [
        { strike: 25000, call: {}, put: { oi: 100 } },
        { strike: 25100, call: { oi: 50 }, put: { oi: 50 } },
      ],
      atmStrike: 25000,
      maxCallOI: 50,
      maxPutOI: 100,
      totalCallOI: null,
      totalPutOI: 150,
    };

    render(<OptionChainWidget />, { wrapper: Wrapper });

    expect(screen.getByText("CE: --")).toBeInTheDocument();
    expect(screen.getByText("PE: 150")).toBeInTheDocument();
    const accessibleRows = screen.getByRole("table", { name: "Option chain data (accessible view)" })
      .querySelectorAll("tbody tr");
    expect(accessibleRows[0]?.querySelector("td")?.textContent).toBe("--");
  });

  it("renders explicit zero OI in the grid view and totals instead of marking it unavailable", () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { oi: 0 }, pe: { oi: 0 } }] },
      strikes: [{ strike: 25000, call: { oi: 0 }, put: { oi: 0 } }],
      atmStrike: 25000,
      maxCallOI: 0,
      maxPutOI: 0,
      totalCallOI: 0,
      totalPutOI: 0,
    };

    render(<OptionChainWidget />, { wrapper: Wrapper });

    expect(screen.getByText("CE: 0")).toBeInTheDocument();
    expect(screen.getByText("PE: 0")).toBeInTheDocument();
    const cells = screen.getByRole("table", { name: "Option chain data (accessible view)" })
      .querySelectorAll("tbody td");
    expect(cells[0]?.textContent).toBe("0");
    expect(cells[cells.length - 1]?.textContent).toBe("0");
  });

  it("shows Max Pain only for an explicit live, positive, settled current query", async () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }] },
      strikes: [{ strike: 25000, call: { oi: 10 }, put: { oi: 20 } }],
      atmStrike: 25000,
      totalCallOI: 10,
      totalPutOI: 20,
    };
    vi.mocked(getMaxPain).mockResolvedValue({
      is_sample_data: false,
      max_pain_strike: 25000,
      strikes: [],
    });

    render(<OptionChainWidget />, { wrapper: Wrapper });

    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();
  });

  it.each([
    ["sample", { is_sample_data: true, max_pain_strike: 25000, strikes: [] }],
    ["missing provenance", { max_pain_strike: 25000, strikes: [] }],
    ["non-positive strike", { is_sample_data: false, max_pain_strike: 0, strikes: [] }],
  ])("withholds %s Max Pain data", async (_label, response) => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }] },
      strikes: [{ strike: 25000, call: { oi: 10 }, put: { oi: 20 } }],
      atmStrike: 25000,
    };
    vi.mocked(getMaxPain).mockResolvedValue(response as never);

    render(<OptionChainWidget />, { wrapper: Wrapper });

    await vi.waitFor(() => expect(getMaxPain).toHaveBeenCalled());
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
  });

  it("clears Max Pain during a key change and does not reuse the prior expiry result", async () => {
    let resolveNextExpiry!: (value: unknown) => void;
    const nextExpiry = new Promise((resolve) => { resolveNextExpiry = resolve; });
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }] },
      strikes: [{ strike: 25000, call: { oi: 10 }, put: { oi: 20 } }],
      atmStrike: 25000,
    };
    vi.mocked(getMaxPain)
      .mockResolvedValueOnce({ is_sample_data: false, max_pain_strike: 25000, strikes: [] })
      .mockReturnValueOnce(nextExpiry as never);

    const { rerender } = render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();

    optionChainHookMocks.overrides = {
      ...optionChainHookMocks.overrides,
      selectedExpiry: "2026-04-17",
    };
    rerender(<OptionChainWidget params={{ symbol: "NIFTY" }} />);
    await vi.waitFor(() => expect(getMaxPain).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-17",
      expect.any(AbortSignal),
    ));
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();

    resolveNextExpiry({ is_sample_data: false, max_pain_strike: 25100, strikes: [] });
  });

  it("clears retained Max Pain after a failed refetch", async () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }] },
      strikes: [{ strike: 25000, call: { oi: 10 }, put: { oi: 20 } }],
      atmStrike: 25000,
    };
    vi.mocked(getMaxPain).mockResolvedValueOnce({
      is_sample_data: false,
      max_pain_strike: 25000,
      strikes: [],
    });

    render(<OptionChainWidget />, { wrapper: Wrapper });
    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();

    vi.mocked(getMaxPain).mockRejectedValue(new Error("Max Pain unavailable"));
    await queryClient.refetchQueries({ queryKey: ["maxpain", "NIFTY", "NFO", "2026-04-10"] });
    await vi.waitFor(() => {
      expect(queryClient.getQueryState(["maxpain", "NIFTY", "NFO", "2026-04-10"])?.fetchStatus).toBe("idle");
    }, { timeout: 4000 });
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
  });

  it("configures Max Pain to refetch every 60 seconds only while visible", () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [] },
    };

    render(<OptionChainWidget />, { wrapper: Wrapper });

    const query = queryClient.getQueryCache().find({
      queryKey: ["maxpain", "NIFTY", "NFO", "2026-04-10"],
    });
    expect(query?.options).toMatchObject({
      refetchInterval: 60_000,
      refetchIntervalInBackground: false,
    });
  });

  it("aborts an in-flight Max Pain request when the widget unmounts", async () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [] },
    };
    vi.mocked(getMaxPain).mockReturnValue(new Promise(() => {}) as never);

    const { unmount } = render(<OptionChainWidget />, { wrapper: Wrapper });
    await vi.waitFor(() => expect(getMaxPain).toHaveBeenCalledOnce());
    const signal = vi.mocked(getMaxPain).mock.calls[0]?.[3] as AbortSignal;

    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("clears basket legs when the selected contract identity changes", async () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [{ strike: 25000, ce: { ltp: 100 }, pe: null }] },
      strikes: [{ strike: 25000, call: { ltp: 100 }, put: null }],
      atmStrike: 25000,
    };
    const { rerender } = render(<OptionChainWidget />, { wrapper: Wrapper });

    act(() => gridMocks.onCellClicked?.([0, 0]));
    expect(screen.getByText("Basket (1)")).toBeInTheDocument();

    optionChainHookMocks.overrides = {
      ...optionChainHookMocks.overrides,
      selectedExpiry: "2026-04-17",
    };
    rerender(<OptionChainWidget />);

    await waitFor(() => expect(screen.queryByText("Basket (1)")).not.toBeInTheDocument());
  });

  it("mirrors visual change aliases and unavailable values in the accessible table", () => {
    optionChainHookMocks.overrides = {
      selectedExpiry: "2026-04-10",
      chain: { chain: [] },
      strikes: [{
        strike: 25000,
        call: { oi: 0, change_percent: 0, volume: 0, iv: 0, ltp: 0 },
        put: { change_pct: -1.25 },
      }],
      atmStrike: 25000,
      totalCallOI: 0,
      totalPutOI: null,
    };

    render(<OptionChainWidget />, { wrapper: Wrapper });

    const cells = Array.from(
      screen.getByRole("table", { name: "Option chain data (accessible view)" })
        .querySelectorAll("tbody tr:first-child > *"),
    ).map((cell) => cell.textContent);
    expect(cells).toEqual([
      "0", "0", "0", "0", "0", "25000", "--", "--", "--", "-1.25", "--",
    ]);
  });

  it("toggles LegBuilder panel when Build Strategy is clicked", async () => {
    const { user } = await import("@testing-library/user-event").then((m) => ({
      user: m.default.setup(),
    }));
    render(<OptionChainWidget />, { wrapper: Wrapper });

    const btn = screen.getByTitle("Build multi-leg option strategy");
    // Panel is hidden initially
    expect(screen.queryByRole("region", { name: "Strategy leg builder" })).toBeNull();

    await user.click(btn);
    expect(screen.getByRole("region", { name: "Strategy leg builder" })).toBeInTheDocument();
    expect(btn).toHaveAttribute("aria-pressed", "true");

    // Click again → hides panel
    await user.click(btn);
    expect(screen.queryByRole("region", { name: "Strategy leg builder" })).toBeNull();
    expect(btn).toHaveAttribute("aria-pressed", "false");
  });
});

// ---------------------------------------------------------------------------
// FDC3 channel following (Phase 2)
// ---------------------------------------------------------------------------

describe("OptionChainWidget — FDC3 channel following", () => {
  const BANKNIFTY = { symbol: "BANKNIFTY", exchange: "NSE_INDEX" };

  // Radix Popover (SymbolSearch) uses ResizeObserver internally.
  beforeAll(() => {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  beforeEach(() => {
    queryClient.clear();
    vi.clearAllMocks();
    optionChainHookMocks.overrides = {};
    gridMocks.onCellClicked = null;
    vi.mocked(getSymbol).mockReset().mockResolvedValue({} as never);
    vi.mocked(getMaxPain).mockReset().mockResolvedValue({} as never);
  });

  /** Wrap in an explicit jotai store so tests can broadcast onto channels. */
  function channelWrapper(store: ReturnType<typeof createStore>) {
    return function ChannelWrapper({ children }: { children: React.ReactNode }) {
      return (
        <JotaiProvider store={store}>
          <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        </JotaiProvider>
      );
    };
  }

  it("follows an instrument broadcast on its channel", async () => {
    const store = createStore();
    render(<OptionChainWidget {...makeWidgetPanelProps()} />, {
      wrapper: channelWrapper(store),
    });
    expect(screen.getByText(/strikes loaded for NIFTY/)).toBeInTheDocument();

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, BANKNIFTY));

    // The broadcast SYMBOL becomes the chain underlying, normalised onto the
    // chain's own exchange (NFO), not the broadcast spot exchange.
    expect(screen.getByText(/strikes loaded for BANKNIFTY/)).toBeInTheDocument();
    await vi.waitFor(() => expect(getSymbol).toHaveBeenCalledWith("BANKNIFTY", "NFO"));
  });

  it("adopts the channel's current context on mount", async () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "GOLD", exchange: "MCX" });

    render(<OptionChainWidget {...makeWidgetPanelProps()} />, {
      wrapper: channelWrapper(store),
    });

    expect(screen.getByText(/strikes loaded for GOLD/)).toBeInTheDocument();
    await vi.waitFor(() => expect(getSymbol).toHaveBeenCalledWith("GOLD", "MCX"));
  });

  it('ignores broadcasts when joined to no channel (channel: "none")', async () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, BANKNIFTY);

    render(
      <OptionChainWidget {...makeWidgetPanelProps({ params: { channel: "none" } })} />,
      { wrapper: channelWrapper(store) },
    );
    expect(screen.getByText(/strikes loaded for NIFTY/)).toBeInTheDocument();

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "GOLD", exchange: "MCX" }));

    expect(screen.getByText(/strikes loaded for NIFTY/)).toBeInTheDocument();
    await vi.waitFor(() => expect(getSymbol).toHaveBeenCalledWith("NIFTY", "NFO"));
    expect(getSymbol).not.toHaveBeenCalledWith("BANKNIFTY", expect.anything());
    expect(getSymbol).not.toHaveBeenCalledWith("GOLD", expect.anything());
  });

  it("keeps ignoring broadcasts when pinned by params.symbol", async () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, BANKNIFTY);

    render(
      <OptionChainWidget {...makeWidgetPanelProps({ params: { symbol: "GOLD" } })} />,
      { wrapper: channelWrapper(store) },
    );
    expect(screen.getByText(/strikes loaded for GOLD/)).toBeInTheDocument();

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "SENSEX", exchange: "BSE_INDEX" }));

    expect(screen.getByText(/strikes loaded for GOLD/)).toBeInTheDocument();
    await vi.waitFor(() => expect(getSymbol).toHaveBeenCalledWith("GOLD", "MCX"));
    expect(getSymbol).not.toHaveBeenCalledWith("BANKNIFTY", expect.anything());
    expect(getSymbol).not.toHaveBeenCalledWith("SENSEX", expect.anything());
  });

  it("keeps the current underlying when the broadcast symbol is not a supported underlying", async () => {
    const store = createStore();
    render(<OptionChainWidget {...makeWidgetPanelProps()} />, {
      wrapper: channelWrapper(store),
    });

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "RELIANCE", exchange: "NSE" }));

    expect(screen.getByText(/strikes loaded for NIFTY/)).toBeInTheDocument();
    await vi.waitFor(() => expect(getSymbol).toHaveBeenCalledWith("NIFTY", "NFO"));
    expect(getSymbol).not.toHaveBeenCalledWith("RELIANCE", expect.anything());
  });

  it("lets a local pick beat the stale channel context, while a new broadcast still retargets", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    const store = createStore();
    render(<OptionChainWidget {...makeWidgetPanelProps()} />, {
      wrapper: channelWrapper(store),
    });

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, BANKNIFTY));
    expect(screen.getByText(/strikes loaded for BANKNIFTY/)).toBeInTheDocument();

    // Local pick: GOLD from the Popular list in the symbol combobox.
    await user.click(screen.getByRole("button", { name: "Select symbol" }));
    await user.click(await screen.findByText("GOLD"));
    expect(screen.getByText(/strikes loaded for GOLD/)).toBeInTheDocument();

    // The stale BANKNIFTY context must not re-apply on subsequent renders.
    await waitFor(() =>
      expect(screen.getByText(/strikes loaded for GOLD/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/strikes loaded for BANKNIFTY/)).not.toBeInTheDocument();

    // A NEW broadcast still retargets the chain.
    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "SENSEX", exchange: "BSE_INDEX" }));
    expect(screen.getByText(/strikes loaded for SENSEX/)).toBeInTheDocument();
  });
});
