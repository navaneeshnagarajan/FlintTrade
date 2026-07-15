import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
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

beforeEach(() => {
  vi.clearAllMocks();
  mockUseBrokerConnected.mockReturnValue(false);
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

  it("renders an explicitly live response when connected", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue({
      ...SAMPLE_FUNDING_RATES,
      is_sample_data: false,
    });

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

  it("badges a connected response flagged is_sample_data — stub rates must never render as live", async () => {
    // The backend endpoint is currently a hardcoded stub that declares
    // is_sample_data: true even for connected users. The badge must key off
    // the response flag, not connection state.
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue({
      ...SAMPLE_FUNDING_RATES,
      is_sample_data: true,
    });

    render(<FundingRateWidget />, { wrapper });

    await waitFor(() => {
      expect(screen.queryByText("BTCUSD")).toBeTruthy();
    });
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.queryByLabelText("Refresh funding rates")).toBeNull();
  });

  it("treats missing connected provenance as sample or unknown", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue({
      ...SAMPLE_FUNDING_RATES,
      updated_at: "2026-07-14T09:30:00.000Z",
    });

    render(<FundingRateWidget />, { wrapper });

    await waitFor(() => {
      expect(screen.queryByText("BTCUSD")).toBeTruthy();
    });
    expect(screen.getByText("Sample data")).toBeTruthy();
    expect(screen.queryByLabelText("Refresh funding rates")).toBeNull();
    expect(screen.queryByText(/Updated:/)).toBeNull();
  });

  it("shows no sample badge only for an explicitly live response", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue({
      ...SAMPLE_FUNDING_RATES,
      is_sample_data: false,
    });

    render(<FundingRateWidget />, { wrapper });

    await waitFor(() => {
      expect(screen.queryByText("BTCUSD")).toBeTruthy();
    });
    expect(screen.queryByText("Sample data")).toBeNull();
    expect(screen.getByLabelText("Refresh funding rates")).toBeTruthy();
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

  it("hides refresh while showing disconnected sample data", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.queryByLabelText("Refresh funding rates")).toBeNull();
  });

  it("does not show a live countdown for local sample rows", () => {
    mockUseBrokerConnected.mockReturnValue(false);

    render(<FundingRateWidget />, { wrapper });

    expect(screen.queryAllByText("7h 30m")).toHaveLength(0);
  });

  it("shows refresh when connected to the live funding endpoint", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockGetCryptoFundingRates.mockResolvedValue({
      ...SAMPLE_FUNDING_RATES,
      is_sample_data: false,
    });

    render(<FundingRateWidget />, { wrapper });

    await waitFor(() => {
      expect(screen.getByLabelText("Refresh funding rates")).toBeTruthy();
    });
  });

  it("stops automatic polling after a response with missing provenance", async () => {
    vi.useFakeTimers();
    mockUseBrokerConnected.mockReturnValue(true);

    let resolveRequest: ((value: typeof SAMPLE_FUNDING_RATES) => void) | undefined;
    mockGetCryptoFundingRates.mockImplementation(
      () => new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(
      <QueryClientProvider client={qc}>
        <FundingRateWidget />
      </QueryClientProvider>,
    );

    try {
      expect(mockGetCryptoFundingRates).toHaveBeenCalledTimes(1);
      await act(async () => {
        resolveRequest?.(SAMPLE_FUNDING_RATES);
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByText("BTCUSD")).toBeTruthy();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      expect(mockGetCryptoFundingRates).toHaveBeenCalledTimes(1);
    } finally {
      view.unmount();
      qc.clear();
      vi.useRealTimers();
    }
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

  it("does not mint module-load timestamps for sample data", () => {
    expect(SAMPLE_FUNDING_RATES.updated_at).toBeUndefined();
    for (const entry of SAMPLE_FUNDING_RATES.rates) {
      expect(entry.next_funding_ms).toBe(0);
    }
  });

  it("has both positive and negative rate entries", () => {
    const hasPositive = SAMPLE_FUNDING_RATES.rates.some((r) => r.rate > 0);
    const hasNegative = SAMPLE_FUNDING_RATES.rates.some((r) => r.rate < 0);
    expect(hasPositive).toBe(true);
    expect(hasNegative).toBe(true);
  });
});
