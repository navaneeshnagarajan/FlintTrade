import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../usePatternDetection", () => ({
  usePatternDetection: vi.fn(),
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

import { usePatternDetection } from "../usePatternDetection";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import PatternDetectionWidget from "../PatternDetectionWidget";

const mockHook = usePatternDetection as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("PatternDetectionWidget", () => {
  it("renders sample patterns with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<PatternDetectionWidget />, { wrapper });

    expect(screen.getByText(/Sample data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Pattern Detection");
    expect(screen.getByText("Bullish Engulfing")).toBeInTheDocument();
    expect(screen.getByText("Three White Soldiers")).toBeInTheDocument();
  });

  it("keeps the demo affordance when a connected response omits is_sample_data", () => {
    // Fail-closed: absent provenance is sample, never live.
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
        scan: {
          bar_count: 40,
          matches: [
            { index: 39, time: "2026-07-03", pattern: "shooting_star", label: "Shooting Star", direction: "bearish", strength: 0.7 },
          ],
        },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<PatternDetectionWidget />, { wrapper });

    expect(screen.getByText(/Sample data/i)).toBeInTheDocument();
    expect(screen.getByText("Shooting Star")).toBeInTheDocument();
  });

  it("renders live patterns without demo affordance when connected", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: {
        is_sample_data: false,
        scan: {
          bar_count: 40,
          matches: [
            { index: 39, time: "2026-07-03", pattern: "shooting_star", label: "Shooting Star", direction: "bearish", strength: 0.7 },
          ],
        },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<PatternDetectionWidget />, { wrapper });

    expect(screen.queryByText(/Sample data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("Shooting Star")).toBeInTheDocument();
  });

  it("shows an empty state when no patterns are found", () => {
    mockConnected.mockReturnValue(true);
    mockHook.mockReturnValue({
      data: { is_sample_data: false, scan: { bar_count: 40, matches: [] } },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<PatternDetectionWidget />, { wrapper });

    expect(screen.getByText(/No candlestick patterns detected/i)).toBeInTheDocument();
  });
});
