import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("../useTape", () => ({
  useTape: vi.fn().mockReturnValue([]),
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

import { useTape } from "../useTape";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import TimeSalesWidget from "../TimeSalesWidget";
import { SAMPLE_TAPE } from "../sampleData";

const mockUseTape = useTape as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

describe("TimeSalesWidget", () => {
  it("renders the sample tape with demo affordance when disconnected", () => {
    mockConnected.mockReturnValue(false);
    mockUseTape.mockReturnValue([]);

    render(<TimeSalesWidget />);

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Time & Sales");
    // Sample prints render (unique first-row time from the sample tape).
    expect(screen.getByText(SAMPLE_TAPE[0].time)).toBeInTheDocument();
    // Honest inference labelling always visible.
    expect(screen.getByText(/inferred from quote ticks/i)).toBeInTheDocument();
  });

  it("renders live prints without demo affordance when connected", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([
      { id: 2, time: "11:00:02", price: 2852.1, qty: 500, side: "buy" },
      { id: 1, time: "11:00:01", price: 2852.0, qty: 120, side: "sell" },
    ]);

    render(<TimeSalesWidget />);

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("11:00:02")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("shows a waiting state when connected with no ticks yet", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([]);

    render(<TimeSalesWidget />);

    expect(screen.getByText(/Waiting for ticks/i)).toBeInTheDocument();
  });
});
