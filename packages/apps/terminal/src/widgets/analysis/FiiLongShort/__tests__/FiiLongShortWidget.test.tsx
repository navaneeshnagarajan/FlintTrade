import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock the data hook so no network call happens.
vi.mock("../useFiiLongShort", () => ({
  useFiiLongShort: vi.fn(),
}));

// Default: disconnected → sample data + teaser wrapper.
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

import { useFiiLongShort } from "../useFiiLongShort";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import FiiLongShortWidget from "../FiiLongShortWidget";
import { SAMPLE_FII_LONG_SHORT } from "../sampleData";

const mockUseHook = useFiiLongShort as ReturnType<typeof vi.fn>;
const mockUseConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("FiiLongShortWidget", () => {
  it("renders sample data with a demo affordance when disconnected", () => {
    mockUseConnected.mockReturnValue(false);
    mockUseHook.mockReturnValue({ data: undefined, isLoading: false, isFetching: false, refetch: vi.fn() });

    render(<FiiLongShortWidget />, { wrapper });

    // Demo affordance is visible and the teaser wraps the content.
    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "FII Long/Short");
    // All four segments render.
    for (const seg of SAMPLE_FII_LONG_SHORT.segments) {
      expect(screen.getByText(seg.label)).toBeInTheDocument();
    }
  });

  it("renders live data without the demo affordance when connected", () => {
    mockUseConnected.mockReturnValue(true);
    mockUseHook.mockReturnValue({
      data: {
        is_sample_data: false,
        ratio: { ...SAMPLE_FII_LONG_SHORT, bias_label: "Strongly Long", futures_bias: 68.0 },
      },
      isLoading: false,
      isFetching: false,
      refetch: vi.fn(),
    });

    render(<FiiLongShortWidget />, { wrapper });

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("Strongly Long")).toBeInTheDocument();
  });
});
