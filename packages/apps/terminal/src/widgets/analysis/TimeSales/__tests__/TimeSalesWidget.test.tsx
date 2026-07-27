/**
 * TimeSalesWidget (Tape & Microstructure) tests.
 *
 * Three of the retired Market Microstructure widget's twelve cases existed only
 * to pin the honesty of fabricated data — an unconditional "Sample data" badge
 * and the absence of a "Live updating" affordance over `Math.random()` ticks.
 * They are moot now that the statistics run on real prints, and are replaced
 * here by pins that the numbers come FROM those prints, that a disconnected
 * widget still discloses its sample tape, and that bid/ask imbalance is omitted
 * rather than invented when no depth book is available.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";

vi.mock("../useTape", () => ({
  useTape: vi.fn().mockReturnValue([]),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useDepthData", () => ({
  useDepthData: vi.fn().mockReturnValue({ data: undefined }),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
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
import { useDepthData } from "@/hooks/useDepthData";
import TimeSalesWidget from "../TimeSalesWidget";
import { SAMPLE_TAPE } from "../sampleData";
import type { TapePrint } from "../tape";

const mockUseTape = useTape as ReturnType<typeof vi.fn>;
const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockDepth = useDepthData as ReturnType<typeof vi.fn>;

const defaultProps = makeWidgetPanelProps();
const statsViewProps = makeWidgetPanelProps({ params: { view: "stats" } });

/** A print `agoMs` before now, so it lands inside the live statistics window. */
function livePrint(id: number, agoMs: number, qty: number, side: TapePrint["side"]): TapePrint {
  return { id, ts: Date.now() - agoMs, time: "11:00:00", price: 2852, qty, side };
}

beforeEach(() => {
  mockConnected.mockReturnValue(false);
  mockUseTape.mockReturnValue([]);
  mockDepth.mockReturnValue({ data: undefined });
});

describe("TimeSalesWidget — tape", () => {
  it("renders the sample tape with demo affordance when disconnected", () => {
    render(<TimeSalesWidget {...defaultProps} />);

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toHaveAttribute("data-feature", "Tape & Microstructure");
    // Sample prints render (unique first-row time from the sample tape).
    expect(screen.getByText(SAMPLE_TAPE[0].time)).toBeInTheDocument();
    // Honest inference labelling always visible.
    expect(screen.getByText(/inferred from quote ticks/i)).toBeInTheDocument();
  });

  it("renders live prints without demo affordance when connected", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([
      { id: 2, ts: Date.now(), time: "11:00:02", price: 2852.1, qty: 500, side: "buy" },
      { id: 1, ts: Date.now() - 1_000, time: "11:00:01", price: 2852.0, qty: 120, side: "sell" },
    ]);

    render(<TimeSalesWidget {...defaultProps} />);

    expect(screen.queryByText(/Demo data/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("feature-teaser")).not.toBeInTheDocument();
    expect(screen.getByText("11:00:02")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
  });

  it("shows a waiting state when connected with no ticks yet", () => {
    mockConnected.mockReturnValue(true);
    render(<TimeSalesWidget {...defaultProps} />);

    expect(screen.getByText(/Waiting for ticks/i)).toBeInTheDocument();
  });

  it("labels the widget container for assistive technology", () => {
    mockConnected.mockReturnValue(true);
    render(<TimeSalesWidget {...defaultProps} />);

    expect(screen.getByLabelText("Tape and Microstructure widget")).toBeInTheDocument();
  });

  it("keeps the inference labelling in the statistics-only view too", () => {
    // The label is what makes every number below it defensible: these are not
    // exchange prints, and the widget must never stop saying so.
    mockConnected.mockReturnValue(true);
    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText(/inferred from quote ticks/i)).toBeInTheDocument();
  });
});

describe("TimeSalesWidget — microstructure statistics", () => {
  it("computes the statistics from the real prints on the tape", () => {
    // 4 prints in the last 10 s → 0.4 prints/s; sizes 100/100/100/500 → avg
    // 200, so only the 500 exceeds twice the average. Three buys, one sell →
    // 75% up / 25% down. Every one of these is arithmetic over the prints the
    // WebSocket fold produced, not over a generated tick array.
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([
      livePrint(4, 500, 500, "buy"),
      livePrint(3, 1_500, 100, "buy"),
      livePrint(2, 2_500, 100, "sell"),
      livePrint(1, 3_500, 100, "buy"),
    ]);

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText("0.4 prints/s")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();          // avg trade size
    expect(screen.getByText("75% up / 25% down")).toBeInTheDocument();
    const large = screen.getByText("Large Prints (60s)").closest("div");
    expect(within(large as HTMLElement).getByText("1")).toBeInTheDocument();
  });

  it("reports no trade sizes when the feed carries no volume", () => {
    // An LTP-only feed gives every print a zero volume delta. Averaging those
    // in would report a trade size of 0 as though it were measured.
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(2, 500, 0, "buy"), livePrint(1, 1_500, 0, "sell")]);

    render(<TimeSalesWidget {...statsViewProps} />);

    const avgRow = screen.getByText("Avg Trade Size").closest("div") as HTMLElement;
    expect(within(avgRow).getByText("no size on feed")).toBeInTheDocument();
    expect(within(avgRow).getByText("—")).toBeInTheDocument();
    expect(within(avgRow).queryByText("0")).not.toBeInTheDocument();
  });

  it("a disconnected widget still discloses that its statistics are the sample tape", () => {
    // Replaces the retired widget's unconditional "Sample data" badge: the data
    // is real when connected, so the disclosure is now tied to sample mode —
    // but it must still be impossible to read demo statistics as live ones.
    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText(/Demo data/i)).toBeInTheDocument();
    expect(screen.getByTestId("feature-teaser")).toBeInTheDocument();
    // Sample statistics are the sample tape's own: 20 prints, 10 buys, 9 sells.
    expect(screen.getByText("50% up / 45% down")).toBeInTheDocument();
  });

  it("renders the velocity sparkline over the 60-second buckets", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);

    render(<TimeSalesWidget {...statsViewProps} />);

    const sparkline = screen.getByRole("img", { name: /tick velocity sparkline/i });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renders the tick-rule aggressor split as a direction badge", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(2, 500, 100, "buy"), livePrint(1, 1_500, 100, "sell")]);

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(
      screen.getByLabelText(/trade direction: uptick 50% downtick 50% neutral 0%/i),
    ).toBeInTheDocument();
  });
});

describe("TimeSalesWidget — bid/ask imbalance", () => {
  it("omits the imbalance instead of inventing one when no depth book is available", () => {
    // The quote tape carries no resting bid/ask sizes — which is exactly why
    // the retired widget fabricated them. An omitted statistic is honest.
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);
    mockDepth.mockReturnValue({ data: undefined });

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText(/needs the depth feed/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/bid ask imbalance/i)).not.toBeInTheDocument();
  });

  it("treats an empty book as unavailable rather than as balanced", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);
    mockDepth.mockReturnValue({ data: { buy: [], sell: [] } });

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText(/needs the depth feed/i)).toBeInTheDocument();
  });

  it("renders the imbalance from the depth endpoint via the shared bookImbalance", () => {
    // 900 resting on the bid against 300 on the ask → signed +0.5 → 75% bid.
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);
    mockDepth.mockReturnValue({
      data: {
        buy: [{ price: 2852, quantity: 600, orders: 3 }, { price: 2851.9, quantity: 300, orders: 2 }],
        sell: [{ price: 2852.1, quantity: 300, orders: 1 }],
      },
    });

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.getByText("75.0% bid")).toBeInTheDocument();
    expect(screen.getByLabelText(/bid ask imbalance: bid 75% ask 25%/i)).toBeInTheDocument();
    expect(screen.queryByText(/needs the depth feed/i)).not.toBeInTheDocument();
  });

  it("only queries depth when connected and the statistics are on screen", () => {
    render(<TimeSalesWidget {...defaultProps} />);
    // Disconnected: the poll must stay disabled rather than fetching a book
    // that would then be displayed beside demo statistics.
    expect(mockDepth).toHaveBeenCalledWith(expect.any(String), expect.any(String), false);
  });
});

describe("TimeSalesWidget — panel params", () => {
  it("defaults to the tape view, statistics above the print table", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);

    render(<TimeSalesWidget {...defaultProps} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /tick velocity sparkline/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /tape view/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("view=stats drops the print table — the retired microstructure panel", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);

    render(<TimeSalesWidget {...statsViewProps} />);

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: /tick velocity sparkline/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /statistics-only view/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("an unrecognised view param falls back to the tape", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);

    render(<TimeSalesWidget {...makeWidgetPanelProps({ params: { view: "candlestick" } })} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("the statistics header collapses in the tape view", () => {
    mockConnected.mockReturnValue(true);
    mockUseTape.mockReturnValue([livePrint(1, 500, 100, "buy")]);

    render(<TimeSalesWidget {...defaultProps} />);
    const toggle = screen.getByRole("button", { name: /microstructure statistics/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("img", { name: /tick velocity sparkline/i })).not.toBeInTheDocument();
    // The tape itself stays.
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
