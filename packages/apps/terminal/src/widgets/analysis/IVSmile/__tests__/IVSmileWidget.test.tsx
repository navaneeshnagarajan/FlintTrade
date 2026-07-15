import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useIVSmile", () => ({
  useIVSmile: vi.fn(),
}));

// Mock useBrokerConnected — default: disconnected
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

// Mock FeatureTeaser to render children + sentinel
vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({ children, featureName }: { children: React.ReactNode; featureName: string }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>{children}</div>
  ),
}));

import { useIVSmile } from "../useIVSmile";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import IVSmileWidget from "../IVSmileWidget";
import { SAMPLE_IV_SMILE_DATA } from "../sampleData";

const mockUseIVSmile = useIVSmile as ReturnType<typeof vi.fn>;
const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("IVSmileWidget", () => {
  it("renders loading state when connected and loading", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<IVSmileWidget />, { wrapper });
    expect(screen.getByText(/loading iv smile/i)).toBeTruthy();
  });

  it("renders empty state when connected but no data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<IVSmileWidget />, { wrapper });
    expect(screen.getByText(/select symbol to view iv smile/i)).toBeTruthy();
  });

  it("renders chart and metrics when connected with live data", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
        is_sample_data: false,
        curves: [
          {
            expiry: "2026-03-27",
            days_to_expiry: 3,
            atm_iv: 0.186,
            atm_strike: 24200,
            skew_25delta: 0.032,
            points: [
              { strike: 24000, moneyness: 0.9917, call_iv: 0.22, put_iv: 0.28 },
              { strike: 24200, moneyness: 1.0, call_iv: 0.186, put_iv: 0.186 },
              { strike: 24400, moneyness: 1.0083, call_iv: 0.19, put_iv: 0.18 },
            ],
          },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<IVSmileWidget />, { wrapper });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/ATM IV/i)).toBeTruthy();
    expect(screen.getByText(/25d Skew/i)).toBeTruthy();
  });

  it("treats a connected payload with missing provenance as demo data", () => {
    const { is_sample_data: _flag, ...unknownProvenance } = SAMPLE_IV_SMILE_DATA;
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: unknownProvenance,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });

    render(<IVSmileWidget />, { wrapper });

    expect(screen.getByText("Demo data")).toBeTruthy();
  });

  it("does not render a connected half-complete option-leg point as live IV", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
        is_sample_data: false,
        curves: [
          {
            expiry: "2026-03-27",
            days_to_expiry: 3,
            atm_iv: 0.186,
            atm_strike: 24200,
            skew_25delta: 0.032,
            points: [
              { strike: 24200, moneyness: 1, call_iv: 0.186, put_iv: 0 },
            ],
          },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });

    render(<IVSmileWidget />, { wrapper });

    expect(screen.queryByTestId("plotly-chart")).toBeNull();
    expect(screen.getByText(/no iv data available/i)).toBeTruthy();
    expect(screen.queryByText(/ATM IV/i)).toBeNull();
  });

  it("renders error banner", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockUseIVSmile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("IV data unavailable"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<IVSmileWidget />, { wrapper });
    expect(screen.getByText(/iv data unavailable/i)).toBeTruthy();
  });

  it("renders sample data with FeatureTeaser when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    mockUseIVSmile.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<IVSmileWidget />, { wrapper });
    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
  });
});
