import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

// Mock useCountdown to return a static string — prevents setInterval from
// firing during async tests and causing act() warnings.
vi.mock("../useCountdown", () => ({
  useCountdown: () => "7h 30m",
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/components/teasers", () => ({
  FeatureTeaser: ({
    children,
    featureName,
  }: {
    children: React.ReactNode;
    featureName: string;
  }) => (
    <div data-testid="feature-teaser" data-feature={featureName}>
      {children}
    </div>
  ),
}));

vi.mock("@/services/ftApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/ftApi")>();
  return {
    ...actual,
    getCryptoFundingRates: vi.fn(),
  };
});

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getCryptoFundingRates } from "@/services/ftApi";
import FundingRateWidget from "../FundingRateWidget";
import { SAMPLE_FUNDING_RATES } from "../sampleData";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetCryptoFundingRates = getCryptoFundingRates as ReturnType<typeof vi.fn>;

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


describe("FundingRateWidget", () => {
  it("renders FeatureTeaser and sample data when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.getByTestId("feature-teaser")).toBeTruthy();
    expect(screen.getByTestId("feature-teaser").getAttribute("data-feature")).toBe(
      "Funding Rates",
    );
  });

  it("renders sample data table rows when disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    // Should show BTCUSD from sample data
    expect(screen.getByText("BTCUSD")).toBeTruthy();
    expect(screen.getByText("ETHUSD")).toBeTruthy();
  });

  it("shows loading state when connected and fetching", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockReturnValue(new Promise(() => {})); // never resolves

    render(<FundingRateWidget />, { wrapper });

    expect(screen.getByText(/loading funding rates/i)).toBeTruthy();
  });

  it("renders error banner when query fails", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockRejectedValue(new Error("Funding rate API unavailable"));

    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={qc}>
        <FundingRateWidget />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByText(/funding rate api unavailable/i)).toBeTruthy();
    });
  });

  it("renders live data table when connected with data", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue(SAMPLE_FUNDING_RATES);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={qc}>
        <FundingRateWidget />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.queryByText("BTCUSD")).toBeTruthy();
    });
  });

  it("shows summary banner with positive/negative counts", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.getByText("Positive")).toBeTruthy();
    expect(screen.getByText("Negative")).toBeTruthy();
    expect(screen.getByText("Avg Rate")).toBeTruthy();
  });

  it("table headers are rendered", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.getByText("Symbol")).toBeTruthy();
    expect(screen.getByText("Rate (8h)")).toBeTruthy();
    expect(screen.getByText("Predicted")).toBeTruthy();
    expect(screen.getByText("Next Funding")).toBeTruthy();
  });

  it("sort button is present and cycles sort mode", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    const sortBtn = screen.getByLabelText("Cycle sort order");
    expect(sortBtn).toBeTruthy();
    expect(sortBtn.textContent).toContain("Sort: Magnitude");

    fireEvent.click(sortBtn);
    expect(sortBtn.textContent).toContain("Sort: Rate");

    fireEvent.click(sortBtn);
    expect(sortBtn.textContent).toContain("Sort: A–Z");

    fireEvent.click(sortBtn);
    expect(sortBtn.textContent).toContain("Sort: Magnitude");
  });

  it("refresh button is present", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.getByLabelText("Refresh funding rates")).toBeTruthy();
  });

  it("renders sparklines for each row", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    const sparklines = screen.getAllByRole("img", {
      name: /7-day funding rate sparkline/i,
    });
    // One sparkline per symbol
    expect(sparklines.length).toBe(SAMPLE_FUNDING_RATES.rates.length);
    expect(sparklines[0].getAttribute("viewBox")).toBe("0 0 160 42");
    expect(sparklines[0].querySelector("polyline")).toBeNull();
    expect(sparklines[0].querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("positive rate rows show TrendingUp indicator", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    // BTCUSD has a positive rate (0.0001)
    const btcRow = screen.getByText("BTCUSD").closest("tr");
    expect(btcRow).toBeTruthy();
    // Rate text should include "+"
    expect(btcRow?.textContent).toContain("+");
  });
});

// ---------------------------------------------------------------------------
// Sample data unit tests
// ---------------------------------------------------------------------------

describe("SAMPLE_FUNDING_RATES", () => {
  it("has 10 entries matching CRYPTO_PAIRS catalogue", () => {
    expect(SAMPLE_FUNDING_RATES.rates).toHaveLength(10);
  });

  it("all entries have history arrays of length 21 (7d × 3 periods/day)", () => {
    for (const entry of SAMPLE_FUNDING_RATES.rates) {
      expect(entry.history).toHaveLength(21);
    }
  });

  it("all rates are within realistic bounds (-0.2% to +0.2%)", () => {
    for (const entry of SAMPLE_FUNDING_RATES.rates) {
      expect(Math.abs(entry.rate)).toBeLessThanOrEqual(0.002);
    }
  });

  it("next_funding_ms is in the future", () => {
    const now = Date.now();
    for (const entry of SAMPLE_FUNDING_RATES.rates) {
      expect(entry.next_funding_ms).toBeGreaterThan(now - 10_000); // allow 10s clock skew
    }
  });

  it("updated_at is a valid ISO timestamp", () => {
    expect(() => new Date(SAMPLE_FUNDING_RATES.updated_at)).not.toThrow();
    expect(new Date(SAMPLE_FUNDING_RATES.updated_at).getTime()).toBeGreaterThan(0);
  });

  it("has both positive and negative rate entries", () => {
    const hasPositive = SAMPLE_FUNDING_RATES.rates.some((r) => r.rate > 0);
    const hasNegative = SAMPLE_FUNDING_RATES.rates.some((r) => r.rate < 0);
    expect(hasPositive).toBe(true);
    expect(hasNegative).toBe(true);
  });
});
