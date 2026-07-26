import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";

vi.mock("@flinttrade/design-system", () => ({
  FlintMultiLineChart: () => <div data-testid="density-chart" />,
}));

// Plotly is mocked away — the exposure view only needs to prove it renders the
// two panes, not that Plotly draws them.
vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useGammaDensity", () => ({
  useGammaDensity: vi.fn(),
}));

vi.mock("../useGEX", () => ({
  useGEX: vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
}));

vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useGammaDensity } from "../useGammaDensity";
import { useGEX } from "../useGEX";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import GammaDensityWidget, { selectFutureExpiry } from "../GammaDensityWidget";

const mockHook = useGammaDensity as ReturnType<typeof vi.fn>;
const mockGexHook = useGEX as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** Default panel props — density view, the widget's default presentation. */
function densityProps(overrides?: Parameters<typeof makeDockviewPanelProps>[0]) {
  return makeDockviewPanelProps(overrides);
}

/** Panel props carrying the retired `gex` id's view parameter. */
function exposureProps(overrides?: Parameters<typeof makeDockviewPanelProps>[0]) {
  return makeDockviewPanelProps({ params: { view: "exposure" }, ...overrides });
}

const IDLE_QUERY = {
  data: undefined,
  isLoading: false,
  isFetching: false,
  isError: false,
  isRefetchError: false,
  error: null,
  refetch: vi.fn(),
};

const LIVE_GAMMA_DENSITY = {
  underlying: "NIFTY",
  exchange: "NFO",
  spot_price: 24000,
  atm_strike: 24000,
  atm_iv: 16.4,
  dte_days: 3,
  peak_intraday_strike: 24100,
  peak_expiry_strike: 24000,
  intraday_band: { sigma_move: 150, one_sigma_low: 23850, one_sigma_high: 24150, two_sigma_low: 23700, two_sigma_high: 24300 },
  expiry_band: { sigma_move: 300, one_sigma_low: 23700, one_sigma_high: 24300, two_sigma_low: 23400, two_sigma_high: 24600 },
  strikes: [
    { strike: 23900, ce_oi: 1000, pe_oi: 1000, iv: 16, density_intraday: 500, density_expiry: 300 },
    { strike: 24000, ce_oi: 2000, pe_oi: 2000, iv: 16.4, density_intraday: 900, density_expiry: 600 },
    { strike: 24100, ce_oi: 1500, pe_oi: 1500, iv: 16.2, density_intraday: 700, density_expiry: 400 },
  ],
};

const LIVE_GEX = {
  underlying: "NIFTY",
  spot_price: 24200,
  atm_strike: 24200,
  strikes: [
    { strike: 24000, call_gex: 1e8, put_gex: -5e7, net_gex: 5e7, call_oi: 1000, put_oi: 500 },
    { strike: 24200, call_gex: 2e8, put_gex: -1e8, net_gex: 1e8, call_oi: 2000, put_oi: 800 },
  ],
  gamma_flip_strike: null,
  dealer_zone: "Dealer Long Gamma",
  total_call_gex: 3e8,
  total_put_gex: -1.5e8,
  net_gex: 1.5e8,
};

describe("Dealer Gamma widget — density view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ ...IDLE_QUERY });
    mockGexHook.mockReturnValue({ ...IDLE_QUERY });
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-07-30"] });
  });

  it("renders sample surface with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);

    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Dealer Gamma");
    expect(screen.getByTestId("density-chart")).toBeInTheDocument();
    // Gamma-wall stat card present.
    expect(screen.getByText(/Gamma wall/i)).toBeInTheDocument();
  });

  it("selects the earliest authoritative future expiry before enabling the live request", async () => {
    mockConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-08-06", "2099-07-30", "2020-01-01"] });
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { ...LIVE_GAMMA_DENSITY, is_sample_data: false } });

    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    await waitFor(() => {
      expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true);
    });
    expect(apiMocks.getExpiry).toHaveBeenCalledWith("NIFTY", "NFO", "options");
    expect(screen.getByText(/2099-07-30/)).toBeInTheDocument();
    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("16.4%")).toBeInTheDocument();
  });

  it("keeps gamma density in a labelled unavailable state when no future expiry exists", async () => {
    mockConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2020-01-01", "31-DEC-20"] });
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { atm_iv: 99 } });

    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    expect(await screen.findByText(/No future expiry/i)).toBeInTheDocument();
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh dealer gamma" })).toBeDisabled();
    expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "", false);
  });

  it("parses ISO and market expiry formats, keeping today's expiry before the IST close", () => {
    // 00:00 UTC = 05:30 IST on the 24th — the front contract is still trading.
    expect(selectFutureExpiry(
      ["24JUL26", "2026-07-30", "23-JUL-26"],
      new Date("2026-07-24T00:00:00Z"),
    )).toBe("24JUL26");
    // 10:30 UTC = 16:00 IST — past the 15:30 close, today's contract is done.
    expect(selectFutureExpiry(
      ["24JUL26", "2026-07-30", "23-JUL-26"],
      new Date("2026-07-24T10:30:00Z"),
    )).toBe("2026-07-30");
  });

  it("uses Asia/Kolkata calendar semantics around UTC midnight", () => {
    // 19:00 UTC on the 23rd = 00:30 IST on the 24th — the 23rd is stale and
    // the 24th is the front contract for the coming session.
    expect(selectFutureExpiry(
      ["23-JUL-26", "24-JUL-26", "25-JUL-26"],
      new Date("2026-07-23T19:00:00Z"),
    )).toBe("24-JUL-26");
  });

  it.each([
    ["missing", undefined],
    ["malformed", "false"],
    ["sample", true],
  ])("fails closed when Gamma Density provenance is %s", async (_label, flag) => {
    mockConnected.mockReturnValue(true);
    const data = { ...LIVE_GAMMA_DENSITY } as Record<string, unknown>;
    if (flag !== undefined) data.is_sample_data = flag;
    mockHook.mockReturnValue({ ...IDLE_QUERY, data });

    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
  });

  it("does not retain a live-labelled Gamma Density payload after a refetch error", async () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      ...IDLE_QUERY,
      data: { ...LIVE_GAMMA_DENSITY, is_sample_data: false },
      isRefetchError: true,
    });

    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.queryByText("16.4%")).not.toBeInTheDocument();
  });
});

// The exposure view is the retired GEX Dashboard's presentation. The five
// cases below are its original suite (loading / empty / live chart+summary /
// error banner / disconnected teaser), rewritten against the merged widget.
describe("Dealer Gamma widget — exposure view (absorbed GEX)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ ...IDLE_QUERY });
    mockGexHook.mockReturnValue({ ...IDLE_QUERY });
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-07-30"] });
  });

  it("renders the loading state when connected and loading", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({ ...IDLE_QUERY, isLoading: true, isFetching: true });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    expect(await screen.findByText(/loading dealer gamma data/i)).toBeInTheDocument();
  });

  it("renders an empty state when the live exposure payload has no strikes", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({
      ...IDLE_QUERY,
      data: { ...LIVE_GEX, strikes: [], is_sample_data: false },
    });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    expect(await screen.findByText(/No exposure data/i)).toBeInTheDocument();
  });

  it("renders both panes and the dealer-zone footer when connected with live data", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({ ...IDLE_QUERY, data: { ...LIVE_GEX, is_sample_data: false } });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    // Grouped call/put bars + signed Net GEX area = two Plotly panes.
    expect(screen.getAllByTestId("plotly-chart")).toHaveLength(2);
    expect(screen.getByText(/Net GEX/i)).toBeInTheDocument();
    expect(screen.getByText(/Dealer Long Gamma/i)).toBeInTheDocument();
    // Net GEX 1.5e8 formatted, and the ATM readout from the footer chrome.
    expect(screen.getByText("+150.00M")).toBeInTheDocument();
    expect(screen.getByText("24,200")).toBeInTheDocument();
    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    // The density surface is not mounted in this view.
    expect(screen.queryByTestId("density-chart")).not.toBeInTheDocument();
  });

  it("renders an error banner on failure", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({ ...IDLE_QUERY, isError: true, error: new Error("Network error") });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    expect(await screen.findByText(/network error/i)).toBeInTheDocument();
    // A failed fetch still shows the sample surface, and must say so.
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
  });

  it("renders sample exposure behind the teaser when disconnected", () => {
    mockConnected.mockReturnValue(false);

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Dealer Gamma");
    expect(screen.getAllByTestId("plotly-chart")).toHaveLength(2);
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
  });

  // Provenance coverage the retired GEX suite never had: its flag check failed
  // OPEN, so a payload that omitted `is_sample_data` rendered as live.
  //
  // The posture matches the density view's: the served payload IS what the
  // endpoint returned (often the backend's own flagged sample chain), so it
  // still renders — swapping in a client-side fabrication would show MORE
  // invented data, not less. What fails closed is the LABEL: anything short of
  // an explicit `is_sample_data: false` is badged as demo data.
  it.each([
    ["missing", undefined],
    ["malformed", "false"],
    ["sample", true],
  ])("fails closed when gamma-exposure provenance is %s", async (_label, flag) => {
    mockConnected.mockReturnValue(true);
    const data = { ...LIVE_GEX } as Record<string, unknown>;
    if (flag !== undefined) data.is_sample_data = flag;
    mockGexHook.mockReturnValue({ ...IDLE_QUERY, data });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(await screen.findByText(/Demo data/i)).toBeInTheDocument();
    // Rendered, but never without the affordance.
    expect(screen.getByText("+150.00M")).toBeInTheDocument();
  });

  it("does not retain a live-labelled exposure payload after a refetch error", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({
      ...IDLE_QUERY,
      data: { ...LIVE_GEX, is_sample_data: false },
      isRefetchError: true,
    });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.queryByText("+150.00M")).not.toBeInTheDocument();
  });

  // The backend returns `gamma_flip_strike: None` unconditionally, so the GEX
  // widget's flip annotation was dead UI implying a level it cannot compute.
  // Even a payload that carries one must not resurrect the annotation.
  it("renders no gamma-flip level even when a payload carries one", async () => {
    mockConnected.mockReturnValue(true);
    mockGexHook.mockReturnValue({
      ...IDLE_QUERY,
      data: { ...LIVE_GEX, gamma_flip_strike: 24100, is_sample_data: false },
    });

    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.queryByText(/flip/i)).not.toBeInTheDocument();
    expect(screen.queryByText("24,100")).not.toBeInTheDocument();
  });
});

describe("Dealer Gamma widget — view mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({ ...IDLE_QUERY, data: { ...LIVE_GAMMA_DENSITY, is_sample_data: false } });
    mockGexHook.mockReturnValue({ ...IDLE_QUERY, data: { ...LIVE_GEX, is_sample_data: false } });
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-07-30"] });
  });

  it("defaults to the density view and enables only that query", async () => {
    render(<GammaDensityWidget {...densityProps()} />, { wrapper });

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    // One endpoint at a time: the exposure query stays disabled off-screen, so
    // the merge does not double the market-hours poll.
    expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", false);
    expect(screen.getByTestId("density-chart")).toBeInTheDocument();
    expect(screen.queryAllByTestId("plotly-chart")).toHaveLength(0);
  });

  it("honours params.view=exposure and enables only the exposure query", async () => {
    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", false);
    expect(screen.getAllByTestId("plotly-chart")).toHaveLength(2);
  });

  it("falls back to the density view for an unrecognised params.view", async () => {
    render(
      <GammaDensityWidget {...makeDockviewPanelProps({ params: { view: "candlestick" } })} />,
      { wrapper },
    );

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByTestId("density-chart")).toBeInTheDocument();
  });

  it("persists a view switch into the panel params", async () => {
    const updateParameters = vi.fn();
    const props = makeDockviewPanelProps({ params: { view: "density" } });
    render(
      <GammaDensityWidget {...props} api={{ ...props.api, updateParameters }} />,
      { wrapper },
    );

    await screen.findByTestId("density-chart");
    await userEvent.click(screen.getByRole("button", { name: "Gamma exposure view" }));

    expect(updateParameters).toHaveBeenCalledWith({ view: "exposure" });
    expect(screen.getAllByTestId("plotly-chart")).toHaveLength(2);
    await waitFor(() => expect(mockGexHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
  });

  it("marks the active view on its toggle", () => {
    render(<GammaDensityWidget {...exposureProps()} />, { wrapper });

    expect(screen.getByRole("button", { name: "Gamma exposure view" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Gamma density view" })).toHaveAttribute("aria-pressed", "false");
  });
});
