import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../useArbitrageScanner", () => ({
  useArbitrageScanner: vi.fn(),
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

import { useArbitrageScanner } from "../useArbitrageScanner";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import ArbitrageScannerWidget from "../ArbitrageScannerWidget";
import { SAMPLE_ARBITRAGE_SCAN } from "../sampleData";

const mockHook = useArbitrageScanner as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("ArbitrageScannerWidget", () => {
  it("renders sample scan with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Arbitrage Scanner");
    // Both section tables present (exact match avoids the subtitle collision).
    expect(screen.getByText("Cash-future basis")).toBeInTheDocument();
    expect(screen.getByText("Cross-exchange gaps")).toBeInTheDocument();
    // First cash-future opportunity underlying rendered.
    expect(screen.getByText(SAMPLE_ARBITRAGE_SCAN.cash_future[0].underlying)).toBeInTheDocument();
  });

  it("renders live scan without demo affordance when connected and not sample", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
        is_sample_data: false,
        scan: {
          risk_free_rate: 0.065,
          edge_threshold_pct: 1,
          cash_future: [
            { underlying: "INFY", exchange: "NFO", spot: 1500, future_price: 1512, days_to_expiry: 8, basis: 12, basis_pct: 0.8, fair_basis: 2.1, mispricing: 9.9, annualised_return_pct: 36.5, signal: "cash_and_carry" },
          ],
          cross_exchange: [],
        },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<ArbitrageScannerWidget />, { wrapper });

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("INFY")).toBeInTheDocument();
  });
});
