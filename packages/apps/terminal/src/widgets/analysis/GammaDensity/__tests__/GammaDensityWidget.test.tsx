import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

import { useGammaDensity } from "../useGammaDensity";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import GammaDensityWidget from "../GammaDensityWidget";

const mockHook = useGammaDensity as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("GammaDensityWidget", () => {
  it("renders sample surface with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<GammaDensityWidget />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Gamma Density");
    expect(screen.getByTestId("density-chart")).toBeInTheDocument();
    // Gamma-wall stat card present.
    expect(screen.getByText(/Gamma wall/i)).toBeInTheDocument();
  });

  it("renders live surface without demo affordance when connected", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
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
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<GammaDensityWidget />, { wrapper });

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("16.4%")).toBeInTheDocument();
  });
});
