import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: () => <div data-testid="plotly-chart" />,
}));

vi.mock("../useStraddlePnL", () => ({
  useStraddlePnL: vi.fn(),
}));

import { useStraddlePnL } from "../useStraddlePnL";
import StraddlePnLWidget from "../StraddlePnLWidget";

const mockUseStraddlePnL = useStraddlePnL as ReturnType<typeof vi.fn>;

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

describe("StraddlePnLWidget", () => {
  it("renders loading state", () => {
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: true,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/simulating p&l/i)).toBeTruthy();
  });

  it("renders empty state with no data", () => {
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/enter symbol and expiry/i)).toBeTruthy();
  });

  it("renders chart and summary when data is present", () => {
    const curve = Array.from({ length: 50 }, (_, i) => ({
      spot_price: 23000 + i * 50,
      pnl: -180 + Math.abs(i - 25) * 20,
    }));

    mockUseStraddlePnL.mockReturnValue({
      data: {
        underlying: "NIFTY",
        atm_strike: 24200,
        call_premium: 180,
        put_premium: 165,
        break_even_low: 23855,
        break_even_high: 24545,
        max_loss: -34500,
        curve,
        legs: [
          { strike: 24200, type: "CE", action: "BUY", premium: 180, lots: 1 },
          { strike: 24200, type: "PE", action: "BUY", premium: 165, lots: 1 },
        ],
      },
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByTestId("plotly-chart")).toBeTruthy();
    expect(screen.getByText(/Max Loss/i)).toBeTruthy();
    expect(screen.getByText(/Base Straddle/i)).toBeTruthy();
  });

  it("renders error banner", () => {
    mockUseStraddlePnL.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new Error("Simulation failed"),
      refetch: vi.fn(),
      isFetching: false,
    });
    render(<StraddlePnLWidget />, { wrapper });
    expect(screen.getByText(/simulation failed/i)).toBeTruthy();
  });
});
