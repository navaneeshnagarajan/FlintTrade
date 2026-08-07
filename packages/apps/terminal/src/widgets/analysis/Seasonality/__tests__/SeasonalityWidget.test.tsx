/**
 * SeasonalityWidget tests.
 *
 * Pins the data-honesty contract (sample rows only behind the disconnected
 * guard with the amber affordances; connected failures fail closed rather
 * than rendering sample rows), FDC3 channel following, and the partial
 * `updateParameters` view persistence.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";
import { createStore, Provider } from "jotai";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { broadcastInstrument, DEFAULT_CHANNEL_ID } from "@/services/fdc3/channels";

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("../api", () => ({
  fetchSeasonality: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { fetchSeasonality, type SeasonalityData } from "../api";
import SeasonalityWidget from "../SeasonalityWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockFetch = fetchSeasonality as ReturnType<typeof vi.fn>;

function liveData(): SeasonalityData {
  return {
    symbol: "NIFTY",
    exchange: "NSE_INDEX",
    is_sample_data: false,
    monthly: [
      {
        month: 7,
        month_name: "July",
        avg_return_pct: 2.34,
        median_return_pct: 2.1,
        std_pct: 2.9,
        positive_rate: 0.8,
        years_count: 9,
        best_year: [2022, 8.7],
        worst_year: [2019, -5.7],
      },
      {
        month: 9,
        month_name: "September",
        avg_return_pct: -1.87,
        median_return_pct: -1.2,
        std_pct: 3.4,
        positive_rate: 0.33,
        years_count: 9,
        best_year: [2019, 4.1],
        worst_year: [2022, -3.7],
      },
    ],
    weekday: [
      {
        weekday: 4,
        weekday_name: "Friday",
        avg_return_pct: 0.123,
        std_pct: 1.0,
        positive_rate: 0.56,
        sample_count: 481,
      },
    ],
    day_of_month: [{ day: 28, avg_return_pct: 0.31 }],
    matrix: { years: [2024], months: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], returns: [] },
  };
}

function renderWidget(options?: {
  store?: ReturnType<typeof createStore>;
  props?: ReturnType<typeof makeWidgetPanelProps>;
}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const props = options?.props ?? makeWidgetPanelProps();
  const tree = (
    <QueryClientProvider client={qc}>
      <SeasonalityWidget {...props} />
    </QueryClientProvider>
  );
  const rendered = options?.store
    ? render(<Provider store={options.store}>{tree}</Provider>)
    : render(tree);
  return { ...rendered, props };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockFetch.mockResolvedValue(liveData());
});

describe("SeasonalityWidget — data honesty", () => {
  it("disconnected renders the sample statistics behind the amber affordances", () => {
    renderWidget();

    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText(/· Sample data/)).toBeInTheDocument();
    // Sample monthly tiles render (all 12 months present in the sample set).
    expect(screen.getByText("Jan")).toBeInTheDocument();
    expect(screen.getByText("Dec")).toBeInTheDocument();
    // And no live fetch is even attempted.
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("connected renders analyser output with a Live badge and no demo affordance", async () => {
    mockConnected.mockReturnValue(true);
    renderWidget();

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.getByText("Jul")).toBeInTheDocument();
    expect(screen.getByText("+2.34%")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByText(/· Sample data/)).not.toBeInTheDocument();
    // The live payload has two months only — no sample-set bleed-through.
    expect(screen.queryByText("Jan")).not.toBeInTheDocument();
  });

  it("a connected fetch failure fails closed: error text, no sample rows, no Live badge", async () => {
    mockConnected.mockReturnValue(true);
    mockFetch.mockRejectedValue(new Error("Not enough daily history for NIFTY"));
    renderWidget();

    expect(
      await screen.findByText(/Seasonality unavailable: Not enough daily history/i),
    ).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByText("Jan")).not.toBeInTheDocument();
  });

  it("a backend payload flagged is_sample_data keeps the amber affordances", async () => {
    mockConnected.mockReturnValue(true);
    mockFetch.mockResolvedValue({ ...liveData(), is_sample_data: true });
    renderWidget();

    expect(await screen.findByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText(/· Sample data/)).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("shows the monthly extremes footer from the rendered data", async () => {
    mockConnected.mockReturnValue(true);
    renderWidget();

    expect(await screen.findByText(/Best month:/i)).toBeInTheDocument();
    expect(screen.getByText(/July \+2.34%/)).toBeInTheDocument();
    expect(screen.getByText(/September -1.87%/)).toBeInTheDocument();
  });
});

describe("SeasonalityWidget — views and persistence", () => {
  it("defaults to the monthly view", () => {
    renderWidget();
    expect(screen.getByRole("button", { name: "Monthly view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("params.view selects the initial view; unknown values fall back to monthly", () => {
    const { unmount } = renderWidget({
      props: makeWidgetPanelProps({ params: { view: "dom" } }),
    });
    expect(screen.getByRole("button", { name: "Day-of-month view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Day 1")).toBeInTheDocument();
    unmount();

    renderWidget({ props: makeWidgetPanelProps({ params: { view: "yearly" } }) });
    expect(screen.getByRole("button", { name: "Monthly view" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("switching views persists a PARTIAL updateParameters patch", () => {
    const props = makeWidgetPanelProps();
    renderWidget({ props });

    fireEvent.click(screen.getByRole("button", { name: "Weekday view" }));

    expect(screen.getByText("Monday")).toBeInTheDocument();
    expect(props.updateParametersCalls).toEqual([{ view: "weekday" }]);

    // Re-selecting the active view must not spam the persisted config.
    fireEvent.click(screen.getByRole("button", { name: "Weekday view" }));
    expect(props.updateParametersCalls).toHaveLength(1);
  });
});

describe("SeasonalityWidget — FDC3 channel", () => {
  const INFY = { symbol: "INFY", exchange: "NSE" };

  it("follows an instrument broadcast on its default (red) channel", async () => {
    mockConnected.mockReturnValue(true);
    const store = createStore();
    renderWidget({ store });

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith("NIFTY", "NSE_INDEX"),
    );

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, INFY));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledWith("INFY", "NSE"));
    expect(screen.getByLabelText("Selected symbol: INFY")).toBeInTheDocument();
  });

  it('joined to no channel (params.channel: "none") ignores broadcasts', () => {
    const store = createStore();
    renderWidget({
      store,
      props: makeWidgetPanelProps({ params: { channel: "none" } }),
    });

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, INFY));

    expect(screen.getByLabelText("Selected symbol: NIFTY")).toBeInTheDocument();
  });

  it("a local selector pick beats a later channel broadcast", () => {
    const store = createStore();
    renderWidget({ store });

    act(() => broadcastInstrument(store, DEFAULT_CHANNEL_ID, INFY));
    expect(screen.getByLabelText("Selected symbol: INFY")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Selected symbol: INFY"));
    fireEvent.click(screen.getByRole("option", { name: "TCS" }));
    expect(screen.getByLabelText("Selected symbol: TCS")).toBeInTheDocument();

    act(() =>
      broadcastInstrument(store, DEFAULT_CHANNEL_ID, { symbol: "SBIN", exchange: "NSE" }),
    );
    expect(screen.getByLabelText("Selected symbol: TCS")).toBeInTheDocument();
  });
});
