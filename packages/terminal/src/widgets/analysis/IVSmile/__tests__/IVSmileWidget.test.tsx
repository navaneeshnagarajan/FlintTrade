import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useIVSmile", () => ({
  useIVSmile: vi.fn(),
}));

import { useIVSmile } from "../useIVSmile";
import IVSmileWidget from "../IVSmileWidget";

const mockUseIVSmile = useIVSmile as ReturnType<typeof vi.fn>;

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
  it("renders loading state", () => {
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

  it("renders empty state when no data", () => {
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

  it("renders chart and metrics when data is present", () => {
    mockUseIVSmile.mockReturnValue({
      data: {
        underlying: "NIFTY",
        spot_price: 24200,
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

  it("renders error banner", () => {
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
});
