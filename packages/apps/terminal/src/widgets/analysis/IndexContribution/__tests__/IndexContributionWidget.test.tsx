import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../useIndexContribution", () => ({
  useIndexContribution: vi.fn(),
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

import { useIndexContribution } from "../useIndexContribution";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import IndexContributionWidget from "../IndexContributionWidget";
import { SAMPLE_INDEX_CONTRIBUTION } from "../sampleData";

const mockHook = useIndexContribution as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("IndexContributionWidget", () => {
  it("renders sample decomposition with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<IndexContributionWidget />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Index Contribution");
    // Top constituent from the sample is shown.
    expect(screen.getByText(SAMPLE_INDEX_CONTRIBUTION.constituents[0].symbol)).toBeInTheDocument();
    expect(screen.getByText(/advancing/i)).toBeInTheDocument();
  });

  it("keeps the demo affordance when a connected response omits is_sample_data", () => {
    // Fail-closed: absent provenance is sample, never live.
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
        contribution: {
          index_name: "BANKNIFTY",
          index_level: 52000,
          index_change_pct: -0.35,
          index_change_points: -182,
          weights_as_of: "2026-06-30",
          advancers: 4,
          decliners: 8,
          constituents: [
            { symbol: "HDFCBANK", weight: 28, ltp: 990, prev_close: 1000, change_pct: -1, contribution_pct: -0.28, contribution_points: -145 },
          ],
        },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<IndexContributionWidget />, { wrapper });

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });

  it("renders live decomposition without demo affordance when connected", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
        is_sample_data: false,
        contribution: {
          index_name: "BANKNIFTY",
          index_level: 52000,
          index_change_pct: -0.35,
          index_change_points: -182,
          weights_as_of: "2026-06-30",
          advancers: 4,
          decliners: 8,
          constituents: [
            { symbol: "HDFCBANK", weight: 28, ltp: 990, prev_close: 1000, change_pct: -1, contribution_pct: -0.28, contribution_points: -145 },
          ],
        },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<IndexContributionWidget />, { wrapper });

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("BANKNIFTY")).toBeInTheDocument();
  });
});
