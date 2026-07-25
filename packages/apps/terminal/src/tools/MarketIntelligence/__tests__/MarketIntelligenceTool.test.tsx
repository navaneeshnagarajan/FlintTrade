/**
 * MarketIntelligenceTool.test.tsx
 *
 * Tests for the Market Intelligence canvas tool.
 * Verifies rendering, heading, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const marketIntelMocks = vi.hoisted(() => ({
  gexData: undefined as
    | {
        is_sample_data: boolean;
        rows: Array<{
          strike: number;
          call_gex: number;
          put_gex: number;
          net_gex: number;
          call_oi: number;
          put_oi: number;
        }>;
      }
    | undefined,
  gexIsError: false,
  fiiDiiData: undefined as { is_sample_data?: boolean } | undefined,
  ivSmileData: undefined as
    | {
        is_sample_data: boolean;
        points: Array<{
          strike: number;
          call_iv: number;
          put_iv: number;
          moneyness: number;
        }>;
      }
    | undefined,
  ivSmileIsError: false,
  maxPainData: undefined as
    | {
        is_sample_data: boolean;
        max_pain_strike: number | null;
        strikes: Array<{
          strike: number;
          call_oi?: number;
          put_oi?: number;
          call_pain?: number;
          put_pain?: number;
          total_pain: number;
        }>;
    }
    | undefined,
  maxPainIsError: false,
  oiProfileData: undefined as
    | {
        is_sample_data: boolean;
        rows: Array<{
          strike: number;
          type: "CE" | "PE";
          oi: number;
          oi_delta_d?: number;
          ltp?: number;
          price_change?: number;
        }>;
      }
    | undefined,
  oiProfileIsError: false,
}));

// Mock market intel hooks
vi.mock("@/hooks/useMarketIntel", () => ({
  useGex: () => ({
    data: marketIntelMocks.gexData,
    isLoading: false,
    isError: marketIntelMocks.gexIsError,
    error: marketIntelMocks.gexIsError ? new Error("GEX refresh failed") : null,
    refetch: vi.fn(),
  }),
  useIVSmile: () => ({
    data: marketIntelMocks.ivSmileData,
    isLoading: false,
    isError: marketIntelMocks.ivSmileIsError,
    error: marketIntelMocks.ivSmileIsError ? new Error("refresh failed") : null,
    refetch: vi.fn(),
  }),
  useMaxPain: () => ({
    data: marketIntelMocks.maxPainData,
    isLoading: false,
    isError: marketIntelMocks.maxPainIsError,
    error: marketIntelMocks.maxPainIsError ? new Error("Max Pain refresh failed") : null,
    refetch: vi.fn(),
  }),
  useOIProfile: () => ({
    data: marketIntelMocks.oiProfileData,
    isLoading: false,
    isError: marketIntelMocks.oiProfileIsError,
    error: marketIntelMocks.oiProfileIsError ? new Error("OI Profile refresh failed") : null,
    refetch: vi.fn(),
  }),
}));

// Mock API calls
vi.mock("@/services/api", () => ({
  getExpiry: vi.fn().mockResolvedValue([]),
}));

vi.mock("@/services/ftApi.screener", () => ({
  getFiiDiiData: () => Promise.resolve(marketIntelMocks.fiiDiiData),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import MarketIntelligenceTool from "../MarketIntelligenceTool";
import { useModeStore } from "@/stores/modeStore";

/**
 * Render the tool inside a query client.
 *
 * Only the FII/DII tab reaches TanStack Query directly — every other tab goes
 * through the mocked useMarketIntel hooks — so the rest of this suite renders
 * bare.
 */
function renderWithQuery() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MarketIntelligenceTool />
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MarketIntelligenceTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    marketIntelMocks.gexData = undefined;
    marketIntelMocks.fiiDiiData = undefined;
    marketIntelMocks.gexIsError = false;
    marketIntelMocks.ivSmileData = undefined;
    marketIntelMocks.ivSmileIsError = false;
    marketIntelMocks.maxPainData = undefined;
    marketIntelMocks.maxPainIsError = false;
    marketIntelMocks.oiProfileData = undefined;
    marketIntelMocks.oiProfileIsError = false;
    useModeStore.setState({ mode: "explore" });
  });

  it("renders without crashing", () => {
    const { container } = render(<MarketIntelligenceTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Market Intelligence heading", () => {
    render(<MarketIntelligenceTool />);
    expect(screen.getByText("Market Intelligence")).toBeInTheDocument();
  });

  it("shows the Sample Data badge for sample-data tabs", () => {
    render(<MarketIntelligenceTool />);
    // The default tab (breadth) uses sample data
    expect(screen.getByText("Sample Data")).toBeInTheDocument();
  });

  it("labels option-intel tabs as sample data in explore mode", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "GEX" }));

    expect(screen.getByText("Sample Data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  // The header badge and the tab body must never contradict each other. They
  // did: `fiidii` was dropped from SAMPLE_DATA_TABS when its rows became live,
  // but it was not added to the provenance-reporting list, so the header
  // asserted "Live" unconditionally while the body rendered its sample notice.
  it("does not label sample FII/DII rows as live", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.fiiDiiData = {
      is_sample_data: true,
    };
    renderWithQuery();

    fireEvent.click(screen.getByRole("button", { name: "FII/DII Flows" }));

    expect(await screen.findByText("Sample Data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("labels FII/DII rows live only when the backend says so", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.fiiDiiData = {
      is_sample_data: false,
    };
    renderWithQuery();

    fireEvent.click(screen.getByRole("button", { name: "FII/DII Flows" }));

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
  });

  it("treats FII/DII rows with no provenance flag as sample", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.fiiDiiData = {};
    renderWithQuery();

    fireEvent.click(screen.getByRole("button", { name: "FII/DII Flows" }));

    expect(await screen.findByText("Sample Data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("uses IV Smile response provenance and decimal units in live mode", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.ivSmileData = {
      is_sample_data: false,
      points: [
        { strike: 23900, call_iv: 0.14, put_iv: 0.15, moneyness: 0.995833 },
        { strike: 24000, call_iv: 0.13, put_iv: 0.131, moneyness: 1 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(await screen.findByText("Live")).toBeInTheDocument();
    expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
    expect(screen.getByText("13.00%")).toBeInTheDocument();
    expect(screen.getByText("0.00%")).toBeInTheDocument();
    expect(screen.getByText("ATM")).toBeInTheDocument();
  });

  it("does not label an IV Smile sample fallback as live", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.ivSmileData = {
      is_sample_data: true,
      points: [{ strike: 24000, call_iv: 0.13, put_iv: 0.131, moneyness: 1 }],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(await screen.findByText("Sample Data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("does not label an unavailable empty live IV Smile response as live", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.ivSmileData = {
      is_sample_data: false,
      points: [],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(await screen.findByText("No IV Smile data available. Select a symbol and expiry above.")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
  });

  it("clears provenance for empty untrusted option-intelligence payloads", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.gexData = { is_sample_data: true, rows: [] };
    marketIntelMocks.ivSmileData = { is_sample_data: true, points: [] };
    marketIntelMocks.maxPainData = { is_sample_data: true, max_pain_strike: null, strikes: [] };
    marketIntelMocks.oiProfileData = { is_sample_data: true, rows: [] };
    render(<MarketIntelligenceTool />);

    for (const tab of ["GEX", "IV Smile", "Max Pain", "OI Profile"]) {
      fireEvent.click(screen.getByRole("button", { name: tab }));
      expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole("button", { name: "Max Pain" }));
    expect(screen.getByText("No Max Pain data available. Select a symbol and expiry above.")).toBeInTheDocument();
    expect(screen.queryByText("Max Pain Strike")).not.toBeInTheDocument();
  });

  it("clears live provenance while a retained IV Smile refresh is failing", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.ivSmileData = {
      is_sample_data: false,
      points: [{ strike: 24000, call_iv: 0.13, put_iv: 0.131, moneyness: 1 }],
    };
    marketIntelMocks.ivSmileIsError = true;
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(await screen.findByText("refresh failed")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
  });

  it("uses response provenance for GEX, Max Pain, and OI Profile sample fallbacks", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.gexData = {
      is_sample_data: true,
      rows: [{ strike: 24000, call_gex: 1, put_gex: -1, net_gex: 0, call_oi: 10, put_oi: 10 }],
    };
    marketIntelMocks.maxPainData = {
      is_sample_data: true,
      max_pain_strike: 24000,
      strikes: [{ strike: 24000, call_oi: 10, put_oi: 10, call_pain: 1, put_pain: 1, total_pain: 2 }],
    };
    marketIntelMocks.oiProfileData = {
      is_sample_data: true,
      rows: [{ strike: 24000, type: "CE", oi: 10, oi_delta_d: 1, ltp: 100 }],
    };
    render(<MarketIntelligenceTool />);

    for (const tab of ["GEX", "Max Pain", "OI Profile"]) {
      fireEvent.click(screen.getByRole("button", { name: tab }));
      expect(await screen.findByText("Sample Data")).toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
    }
  });

  it("labels GEX, Max Pain, and OI Profile live only with explicit usable live data", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.gexData = {
      is_sample_data: false,
      rows: [{ strike: 24000, call_gex: 1, put_gex: -1, net_gex: 0, call_oi: 10, put_oi: 10 }],
    };
    marketIntelMocks.maxPainData = {
      is_sample_data: false,
      max_pain_strike: 24000,
      strikes: [{ strike: 24000, call_oi: 10, put_oi: 10, call_pain: 1, put_pain: 1, total_pain: 2 }],
    };
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [{ strike: 24000, type: "CE", oi: 10, oi_delta_d: 1, ltp: 100 }],
    };
    render(<MarketIntelligenceTool />);

    for (const tab of ["GEX", "Max Pain", "OI Profile"]) {
      fireEvent.click(screen.getByRole("button", { name: tab }));
      expect(await screen.findByText("Live")).toBeInTheDocument();
      expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
    }
  });

  it("clears retained live provenance when GEX, Max Pain, or OI Profile refresh fails", async () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.gexData = {
      is_sample_data: false,
      rows: [{ strike: 24000, call_gex: 1, put_gex: -1, net_gex: 0, call_oi: 10, put_oi: 10 }],
    };
    marketIntelMocks.maxPainData = {
      is_sample_data: false,
      max_pain_strike: 24000,
      strikes: [{ strike: 24000, call_oi: 10, put_oi: 10, call_pain: 1, put_pain: 1, total_pain: 2 }],
    };
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [{ strike: 24000, type: "CE", oi: 10, oi_delta_d: 1, ltp: 100 }],
    };
    marketIntelMocks.gexIsError = true;
    marketIntelMocks.maxPainIsError = true;
    marketIntelMocks.oiProfileIsError = true;
    render(<MarketIntelligenceTool />);

    for (const [tab, message] of [
      ["GEX", "GEX refresh failed"],
      ["Max Pain", "Max Pain refresh failed"],
      ["OI Profile", "OI Profile refresh failed"],
    ] as const) {
      fireEvent.click(screen.getByRole("button", { name: tab }));
      expect(await screen.findByText(message)).toBeInTheDocument();
      expect(screen.queryByText("Live")).not.toBeInTheDocument();
      expect(screen.queryByText("Sample Data")).not.toBeInTheDocument();
    }
  });

  it("treats zero OI or price change as Neutral and malformed change as unavailable", async () => {
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [
        { strike: 24000, type: "CE", oi: 1000, oi_delta_d: 100, ltp: 10, price_change: 0 },
        { strike: 24050, type: "CE", oi: 1000, oi_delta_d: Number.NaN, ltp: 10, price_change: 1 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    await waitFor(() => expect(screen.getAllByText("24,000").length).toBeGreaterThan(0));
    const neutralRow = screen.getAllByText("24,000").find((element) => element.closest("tr"))?.closest("tr");
    const unavailableRow = screen.getAllByText("24,050").find((element) => element.closest("tr"))?.closest("tr");
    expect(neutralRow).not.toBeNull();
    expect(unavailableRow).not.toBeNull();
    expect(within(neutralRow!).getByText("Neutral")).toBeInTheDocument();
    expect(within(unavailableRow!).getAllByText("--").length).toBeGreaterThan(0);
    expect(within(unavailableRow!).queryByText(/Build Up|Covering|Unwinding/)).not.toBeInTheDocument();
  });

  it("does not claim the static global-indices table can become live through Settings", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Global Indices" }));

    expect(
      screen.getByText("Static illustrative values only. This tab is not connected to a live market-data feed."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Live data during market hours/i)).not.toBeInTheDocument();
  });

  it("renders market breadth distribution through the shared stacked-bar primitive", () => {
    render(<MarketIntelligenceTool />);

    expect(screen.getByRole("img", { name: "Market breadth by index" })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
  });

  it("renders India VIX range through the shared linear-meter primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "India VIX" }));

    expect(screen.getByRole("img", { name: "India VIX 52-week range" })).toHaveAttribute(
      "data-flint-chart",
      "linear-meter",
    );
  });

  it("renders delivery percentages through the shared linear-meter primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Delivery Data" }));

    expect(screen.getByRole("img", { name: "HDFCBANK delivery percentage" })).toHaveAttribute(
      "data-flint-chart",
      "linear-meter",
    );
  });

  it("sorts delivery rows through accessible table header controls", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Delivery Data" }));
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));
    fireEvent.click(screen.getByRole("button", { name: "Sort by Symbol" }));

    const rows = screen.getAllByRole("row");
    expect(within(rows[0]).getByText("Symbol")).toBeInTheDocument();
    expect(within(rows[1]).getByText("AXISBANK")).toBeInTheDocument();
  });

  it("renders sector heatmap through the shared weighted-heatmap primitive", () => {
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Sector Heatmap" }));

    expect(screen.getByRole("list", { name: "Sector heatmap by 1D return and market cap" })).toHaveAttribute(
      "data-flint-chart",
      "weighted-heatmap",
    );
  });

  it("renders IV Smile through the shared multi-line primitive", () => {
    marketIntelMocks.ivSmileData = {
      is_sample_data: true,
      points: [
        { strike: 23400, call_iv: 0.124, put_iv: 0.168, moneyness: 23400 / 23500 },
        { strike: 23500, call_iv: 0.118, put_iv: 0.132, moneyness: 1 },
        { strike: 23600, call_iv: 0.141, put_iv: 0.126, moneyness: 23600 / 23500 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "IV Smile" }));

    expect(screen.getByRole("img", { name: "IV Smile call and put volatility by strike" })).toHaveAttribute(
      "data-flint-chart",
      "multi-line",
    );
  });

  it("renders max pain distribution through the shared stacked-bar primitive", () => {
    marketIntelMocks.maxPainData = {
      is_sample_data: true,
      max_pain_strike: 23500,
      strikes: [
        { strike: 23400, call_oi: 120000, put_oi: 98000, call_pain: 900000, put_pain: 300000, total_pain: 1200000 },
        { strike: 23500, call_oi: 140000, put_oi: 125000, call_pain: 600000, put_pain: 600000, total_pain: 1200000 },
        { strike: 23600, call_oi: 94000, put_oi: 152000, call_pain: 250000, put_pain: 750000, total_pain: 1000000 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Max Pain" }));

    expect(screen.getByRole("img", { name: "Max pain distribution across strikes" })).toHaveAttribute(
      "data-flint-chart",
      "stacked-bar",
    );
  });

  it("renders unavailable live Max Pain components as unavailable, not zero", () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.maxPainData = {
      is_sample_data: false,
      max_pain_strike: 23500,
      strikes: [{ strike: 23500, total_pain: 1_200_000 }],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Max Pain" }));

    const dataRow = screen.getAllByRole("row")[1];
    const cells = within(dataRow).getAllByRole("cell");
    expect(cells.slice(1, 5).map((cell) => cell.textContent)).toEqual(["--", "--", "--", "--"]);
    expect(cells[5]).toHaveTextContent("12.00 L");
  });

  it("does not show live provenance or a zero headline when the Max Pain strike is unavailable", () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.maxPainData = {
      is_sample_data: false,
      max_pain_strike: null,
      strikes: [{ strike: 23500, total_pain: 1_200_000 }],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "Max Pain" }));

    expect(screen.getByText("No Max Pain data available. Select a symbol and expiry above.")).toBeInTheDocument();
    expect(screen.queryByText("Max Pain Strike")).not.toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("renders GEX through the shared diverging-bar primitive", () => {
    marketIntelMocks.gexData = {
      is_sample_data: true,
      rows: [
        { strike: 23400, call_gex: 0.24, put_gex: -0.18, net_gex: 0.06, call_oi: 120000, put_oi: 98000 },
        { strike: 23500, call_gex: 0.16, put_gex: -0.42, net_gex: -0.26, call_oi: 140000, put_oi: 125000 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "GEX" }));

    expect(screen.getByRole("list", { name: "Net gamma exposure by strike" })).toHaveAttribute(
      "data-flint-chart",
      "diverging-bar-list",
    );
    expect(screen.getByRole("columnheader", { name: "Call Exposure" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Put Exposure" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Net Exposure" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Call Gamma" })).not.toBeInTheDocument();
  });

  it("presents exact zero net GEX as neutral", () => {
    marketIntelMocks.gexData = {
      is_sample_data: false,
      rows: [
        { strike: 23500, call_gex: 0.2, put_gex: -0.2, net_gex: 0, call_oi: 100, put_oi: 100 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "GEX" }));

    const chartRow = screen.getByRole("listitem");
    expect(chartRow).toHaveTextContent("Neutral");
    expect(chartRow).not.toHaveTextContent("+0.00");
    const dataRow = screen.getAllByRole("row")[1];
    expect(within(dataRow).getAllByRole("cell")[3]).toHaveTextContent("0.0000 Neutral");
  });

  it("renders OI profile through the shared diverging-bar primitive", () => {
    marketIntelMocks.oiProfileData = {
      is_sample_data: true,
      rows: [
        { strike: 23400, type: "PE", oi: 120000, oi_delta_d: 4000, ltp: 82.5 },
        { strike: 23400, type: "CE", oi: 80000, oi_delta_d: -2400, ltp: 126.5 },
        { strike: 23500, type: "PE", oi: 90000, oi_delta_d: 3200, ltp: 112.5 },
        { strike: 23500, type: "CE", oi: 140000, oi_delta_d: 5200, ltp: 72.5 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    expect(screen.getByRole("list", { name: "OI profile by strike" })).toHaveAttribute(
      "data-flint-chart",
      "diverging-bar-list",
    );
  });

  it("keeps an absent OI side unavailable while preserving explicit zero", () => {
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [
        { strike: 23500, type: "CE", oi: 0 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    const chartRow = screen.getByRole("listitem");
    expect(chartRow).toHaveTextContent("--");
    expect(chartRow).toHaveTextContent("0");
    const dataRow = screen.getAllByRole("row")[1];
    const cells = within(dataRow).getAllByRole("cell");
    expect(cells[1]).toHaveTextContent("0");
    expect(cells[2]).toHaveTextContent("--");
  });

  it("classifies zero OI with zero OI change as Neutral", () => {
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [
        { strike: 23500, type: "CE", oi: 0, oi_delta_d: 0, ltp: 10, price_change: 1 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    const dataRow = screen.getAllByRole("row")[1];
    expect(within(dataRow).getAllByRole("cell")[7]).toHaveTextContent("Neutral");
  });

  it("does not infer a live build-up direction from current LTP", () => {
    useModeStore.setState({ mode: "live" });
    marketIntelMocks.oiProfileData = {
      is_sample_data: false,
      rows: [
        { strike: 23500, type: "CE", oi: 140000, oi_delta_d: 5200, ltp: 72.5 },
        { strike: 23500, type: "PE", oi: 90000 },
      ],
    };
    render(<MarketIntelligenceTool />);

    fireEvent.click(screen.getByRole("button", { name: "OI Profile" }));

    const dataRow = screen.getAllByRole("row")[1];
    const cells = within(dataRow).getAllByRole("cell");
    expect(cells.slice(3).map((cell) => cell.textContent)).toEqual(["+5.2 K", "--", "72.50", "--", "--"]);
    expect(screen.queryByText("Neutral")).not.toBeInTheDocument();
    expect(screen.queryByText("Long Build Up")).not.toBeInTheDocument();
    expect(screen.queryByText("Short Build Up")).not.toBeInTheDocument();
  });
});
