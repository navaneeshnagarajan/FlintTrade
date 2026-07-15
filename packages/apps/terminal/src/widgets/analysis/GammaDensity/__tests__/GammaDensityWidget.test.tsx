import { beforeEach, describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@flinttrade/design-system", () => ({
  FlintMultiLineChart: () => <div data-testid="density-chart" />,
}));

vi.mock("../useGammaDensity", () => ({
  useGammaDensity: vi.fn(),
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
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import GammaDensityWidget, { selectFutureExpiry } from "../GammaDensityWidget";

const mockHook = useGammaDensity as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

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

describe("GammaDensityWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: false,
      refetch: vi.fn(),
    });
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-07-30"] });
  });

  it("renders sample surface with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({
      data: undefined,
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: false,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Gamma Density");
    expect(screen.getByTestId("density-chart")).toBeInTheDocument();
    // Gamma-wall stat card present.
    expect(screen.getByText(/Gamma wall/i)).toBeInTheDocument();
  });

  it("selects the earliest authoritative future expiry before enabling the live request", async () => {
    mockConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue({ expiry: ["2099-08-06", "2099-07-30", "2020-01-01"] });
    mockHook.mockReturnValue({
      data: { ...LIVE_GAMMA_DENSITY, is_sample_data: false },
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: false,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

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
    mockHook.mockReturnValue({
      data: { atm_iv: 99 },
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: false,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

    expect(await screen.findByText(/No future expiry/i)).toBeInTheDocument();
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh gamma density" })).toBeDisabled();
    expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "", false);
  });

  it("parses ISO and market expiry formats while excluding the current IST date", () => {
    expect(selectFutureExpiry(
      ["24JUL26", "2026-07-30", "23-JUL-26"],
      new Date("2026-07-24T00:00:00Z"),
    )).toBe("2026-07-30");
  });

  it("uses Asia/Kolkata calendar semantics around UTC midnight", () => {
    expect(selectFutureExpiry(
      ["23-JUL-26", "24-JUL-26", "25-JUL-26"],
      new Date("2026-07-23T19:00:00Z"),
    )).toBe("25-JUL-26");
  });

  it.each([
    ["missing", undefined],
    ["malformed", "false"],
    ["sample", true],
  ])("fails closed when Gamma Density provenance is %s", async (_label, flag) => {
    mockConnected.mockReturnValue(true);
    const data = { ...LIVE_GAMMA_DENSITY } as Record<string, unknown>;
    if (flag !== undefined) data.is_sample_data = flag;
    mockHook.mockReturnValue({
      data,
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: false,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
  });

  it("does not retain a live-labelled Gamma Density payload after a refetch error", async () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: { ...LIVE_GAMMA_DENSITY, is_sample_data: false },
      isLoading: false,
      isFetching: false,
      isError: false,
      isRefetchError: true,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

    await waitFor(() => expect(mockHook).toHaveBeenLastCalledWith("NIFTY", "NFO", "2099-07-30", true));
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.queryByText("16.4%")).not.toBeInTheDocument();
  });
});
