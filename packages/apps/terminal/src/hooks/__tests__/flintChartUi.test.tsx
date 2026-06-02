import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  FlintChartDrawStatus,
  FlintChartDrawingList,
  FlintChartDrawingInspector,
  FlintChartDrawingStyleEditor,
  FlintChartDrawingToolbar,
  FlintChartIntervalPills,
  FlintChartLegend,
  FlintBaselineSparkline,
  FlintBandedLineChart,
  FlintCategoricalBarChart,
  FlintDivergingBarList,
  FlintLinearMeter,
  FlintDonutBreakdown,
  FlintMultiLineChart,
  FlintPayoffChart,
  FlintRadialGauge,
  FlintRankedBarList,
  FlintScatterChart,
  FlintSignedCategoricalBarChart,
  FlintStackedBarChart,
  FlintThresholdLineChart,
  FlintWeightedHeatmap,
  getFlintChartCrosshairReadout,
  getFlintChartKeyboardAction,
  getFlintChartDrawInstruction,
  getFlintChartWorkspaceLayout,
} from "@flinttrade/design-system";

describe("core Flint chart UI primitives", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("renders the OHLCV legend with Indian market number formatting", () => {
    render(
      <FlintChartLegend
        legend={{
          open: 22222.5,
          high: 22310,
          low: 22180.25,
          close: 22290.75,
          volume: 123456,
          bull: true,
        }}
      />,
    );

    expect(screen.getByText("22,222.50")).toBeInTheDocument();
    expect(screen.getByText("22,310.00")).toBeInTheDocument();
    expect(screen.getByText("22,180.25")).toBeInTheDocument();
    expect(screen.getByText("22,290.75")).toBeInTheDocument();
    expect(screen.getByText("1.23L")).toBeInTheDocument();
  });

  it("renders a baseline sparkline for compact equity curves", () => {
    render(
      <FlintBaselineSparkline
        points={[10000, 10120, 10080, 10250]}
        baseline={10000}
        positive
        ariaLabel="Strategy equity curve"
        className="h-10 w-full"
      />,
    );

    const sparkline = screen.getByRole("img", { name: "Strategy equity curve" });
    expect(sparkline).toHaveAttribute("viewBox", "0 0 160 42");
    expect(sparkline.querySelector("polyline")).not.toBeInTheDocument();
    expect(sparkline.querySelector("line")).toBeInTheDocument();
    expect(sparkline.querySelectorAll("path").length).toBeGreaterThan(0);
  });

  it("renders a shared donut breakdown without nested SVG geometry", () => {
    render(
      <FlintDonutBreakdown
        ariaLabel="Portfolio allocation donut chart"
        slices={[
          { label: "Equity", value: 125000, color: "#6366f1" },
          { label: "F&O", value: 42000, color: "#f59e0b" },
          { label: "Cash", value: 18000, color: "#94a3b8" },
        ]}
        centerValue="₹1.85L"
        centerLabel="Total"
      />,
    );

    const chart = screen.getByRole("img", { name: "Portfolio allocation donut chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "donut");
    expect(chart).toHaveClass("rounded-full");
    expect(chart.getAttribute("style")).toContain("conic-gradient");
    expect(chart.querySelector("svg")).not.toBeInTheDocument();
    expect(screen.getByText("₹1.85L")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("renders a shared ranked bar list with a chart marker", () => {
    render(
      <FlintRankedBarList
        ariaLabel="Top symbol P&L"
        entries={[
          { label: "NIFTY", value: 4200, color: "#22c55e" },
          { label: "BANKNIFTY", value: -1800, color: "#ef4444" },
        ]}
        valueFormatter={(value) => `${value}`}
      />,
    );

    const list = screen.getByRole("list", { name: "Top symbol P&L" });
    expect(list).toHaveAttribute("data-flint-chart", "ranked-bar-list");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("renders a ranked bar list against an explicit max scale", () => {
    render(
      <FlintRankedBarList
        ariaLabel="Win rate over time"
        entries={[
          { label: "2026-W22", value: 50, color: "#22c55e" },
          { label: "2026-W23", value: 75, color: "#22c55e" },
        ]}
        maxValue={100}
        valueFormatter={(value) => `${value.toFixed(0)}%`}
      />,
    );

    const list = screen.getByRole("list", { name: "Win rate over time" });
    expect(list).toHaveAttribute("data-flint-chart", "ranked-bar-list");
    expect(list.querySelector('[data-ranked-bar-fill="2026-W22"]')).toHaveStyle({ width: "50%" });
  });

  it("renders a reusable radial gauge for risk metrics", () => {
    render(
      <FlintRadialGauge
        value={72}
        ariaLabel="Margin utilisation gauge"
        color="#f59e0b"
        size={56}
      />,
    );

    const gauge = screen.getByRole("img", { name: "Margin utilisation gauge" });
    expect(gauge).toHaveAttribute("data-flint-chart", "radial-gauge");
    expect(gauge).toHaveAttribute("viewBox", "0 0 56 56");
    expect(gauge.querySelectorAll("circle").length).toBe(2);
    expect(gauge.querySelector("[data-gauge-value]")).toBeInTheDocument();
  });

  it("renders a reusable banded line chart with marker points", () => {
    render(
      <FlintBandedLineChart
        ariaLabel="Volatility cone chart"
        bands={[
          {
            id: "normal-range",
            label: "Normal range",
            color: "rgba(99,102,241,0.12)",
            upper: [{ x: 5, y: 20 }, { x: 30, y: 23 }, { x: 90, y: 27 }],
            lower: [{ x: 5, y: 11 }, { x: 30, y: 15 }, { x: 90, y: 17 }],
          },
        ]}
        series={[
          {
            id: "median",
            label: "Median",
            color: "rgba(99,102,241,0.5)",
            dash: "4,2",
            points: [{ x: 5, y: 16 }, { x: 30, y: 19 }, { x: 90, y: 22 }],
          },
        ]}
        markers={[
          { id: "iv-5", label: "5d IV", x: 5, y: 17.4, color: "#f59e0b" },
          { id: "iv-90", label: "90d IV", x: 90, y: 22.5, color: "#f59e0b" },
        ]}
        xDomain={[5, 90]}
        yDomain={[8, 35]}
        xTicks={[5, 30, 90]}
        yTicks={[10, 20, 30]}
        xFormatter={(value) => `${value}d`}
        yFormatter={(value) => `${value}%`}
        width={520}
        height={200}
      />,
    );

    const chart = screen.getByRole("img", { name: "Volatility cone chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "banded-line");
    expect(chart).toHaveAttribute("viewBox", "0 0 520 200");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-banded-line-band]").length).toBe(1);
    expect(chart.querySelectorAll("[data-banded-line-series]").length).toBe(1);
    expect(chart.querySelectorAll("[data-banded-line-marker]").length).toBe(2);
  });

  it("renders a reusable categorical bar chart", () => {
    render(
      <FlintCategoricalBarChart
        ariaLabel="Trade distribution by day of week"
        entries={[
          { label: "Mon", value: 4, color: "#6366f1" },
          { label: "Tue", value: 8, color: "#6366f1" },
          { label: "Wed", value: 5, color: "#6366f1" },
        ]}
        width={200}
        height={60}
      />,
    );

    const chart = screen.getByRole("img", { name: "Trade distribution by day of week" });
    expect(chart).toHaveAttribute("data-flint-chart", "categorical-bar");
    expect(chart).toHaveAttribute("viewBox", "0 0 200 60");
    expect(chart.querySelectorAll("[data-categorical-bar]").length).toBe(3);
    expect(chart.textContent).toContain("Mon");
    expect(chart.textContent).toContain("8");
  });

  it("renders a reusable linear meter with fill and marker positions", () => {
    render(
      <FlintLinearMeter
        ariaLabel="India VIX 52-week range"
        value={14.28}
        minValue={10.84}
        maxValue={28.42}
        fillColor="linear-gradient(90deg, #22c55e, #ef4444)"
        marker
      />,
    );

    const meter = screen.getByRole("img", { name: "India VIX 52-week range" });
    expect(meter).toHaveAttribute("data-flint-chart", "linear-meter");
    expect(meter.querySelector("[data-linear-meter-fill]")).toBeInTheDocument();
    expect(meter.querySelector("[data-linear-meter-marker]")).toBeInTheDocument();
  });

  it("renders a reusable diverging bar list around a centre label", () => {
    render(
      <FlintDivergingBarList
        ariaLabel="OI profile by strike"
        leftHeading="PE OI"
        rightHeading="CE OI"
        entries={[
          { label: "23,400", leftValue: 120000, rightValue: 80000, leftLabel: "1.20 L", rightLabel: "80.0 K" },
          { label: "23,500", leftValue: 90000, rightValue: 140000, leftLabel: "90.0 K", rightLabel: "1.40 L" },
        ]}
      />,
    );

    const list = screen.getByRole("list", { name: "OI profile by strike" });
    expect(list).toHaveAttribute("data-flint-chart", "diverging-bar-list");
    expect(list.querySelectorAll("[data-diverging-bar-side='left']").length).toBe(2);
    expect(list.querySelectorAll("[data-diverging-bar-side='right']").length).toBe(2);
  });

  it("renders a reusable weighted heatmap with stable tile markers", () => {
    render(
      <FlintWeightedHeatmap
        ariaLabel="Sector heatmap"
        entries={[
          {
            id: "NIFTYBANK",
            label: "Nifty Bank",
            valueLabel: "+0.4%",
            detailLabel: "14.2L Cr",
            weight: 1420000,
            color: "#065f46",
            textColor: "#a7f3d0",
          },
          {
            id: "NIFTYIT",
            label: "Nifty IT",
            valueLabel: "-0.3%",
            detailLabel: "9.8L Cr",
            weight: 980000,
            color: "#991b1b",
            textColor: "#fca5a5",
          },
        ]}
      />,
    );

    const heatmap = screen.getByRole("list", { name: "Sector heatmap" });
    expect(heatmap).toHaveAttribute("data-flint-chart", "weighted-heatmap");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(heatmap.querySelector('[data-weighted-heatmap-tile="NIFTYBANK"]')).toBeInTheDocument();
  });

  it("renders a reusable signed categorical bar chart", () => {
    render(
      <FlintSignedCategoricalBarChart
        ariaLabel="P&L by day of week"
        entries={[
          { label: "Mon", value: 2500, color: "#22c55e" },
          { label: "Tue", value: -1200, color: "#ef4444" },
          { label: "Wed", value: 600, color: "#22c55e" },
        ]}
        valueFormatter={(value) => `${value}`}
        width={220}
        height={90}
      />,
    );

    const chart = screen.getByRole("img", { name: "P&L by day of week" });
    expect(chart).toHaveAttribute("data-flint-chart", "signed-categorical-bar");
    expect(chart).toHaveAttribute("viewBox", "0 0 220 90");
    expect(chart.querySelectorAll("[data-signed-categorical-bar]").length).toBe(3);
    expect(chart.textContent).toContain("Tue");
    expect(chart.textContent).toContain("-1200");
  });

  it("renders a reusable stacked bar chart without local SVG geometry", () => {
    render(
      <FlintStackedBarChart
        ariaLabel="Shareholding trend stacked bar chart"
        labels={["Mar 2025", "Dec 2024"]}
        series={[
          { label: "Promoter", color: "#6366f1", values: [50.34, 50.41] },
          { label: "FII", color: "#22d3ee", values: [20.15, 20.42] },
          { label: "DII", color: "#34d399", values: [16.42, 15.98] },
          { label: "Public", color: "#a78bfa", values: [13.09, 13.19] },
        ]}
      />,
    );

    const chart = screen.getByRole("img", { name: "Shareholding trend stacked bar chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "stacked-bar");
    expect(chart.querySelector("svg")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-stacked-bar-segment]").length).toBe(8);
    expect(screen.getByText("Promoter")).toBeInTheDocument();
    expect(screen.getByText("50.3%")).toBeInTheDocument();
  });

  it("renders a threshold line chart with bands without local polylines", () => {
    render(
      <FlintThresholdLineChart
        ariaLabel="PCR trend chart"
        points={[
          { label: "Mar 10", value: 1.42 },
          { label: "Mar 11", value: 1.31 },
          { label: "Mar 12", value: 1.18 },
          { label: "Mar 13", value: 0.91 },
        ]}
        minValue={0}
        maxValue={2}
        bands={[
          { min: 0, max: 0.7, color: "rgba(34,197,94,0.10)", label: "Bullish Extreme" },
          { min: 1.3, max: 2, color: "rgba(239,68,68,0.12)", label: "Bearish Extreme" },
        ]}
        thresholds={[
          { value: 0.7, color: "rgba(34,197,94,0.5)", dash: "4,2" },
          { value: 1, color: "rgba(156,163,175,0.4)", dash: "4,2" },
          { value: 1.3, color: "rgba(239,68,68,0.5)", dash: "4,2" },
        ]}
        yTicks={[0, 0.5, 1, 1.5, 2]}
        xLabelIndices={[0, 2, 3]}
        lineColor="rgba(99,102,241,0.85)"
        fillColor="rgba(99,102,241,0.18)"
      />,
    );

    const chart = screen.getByRole("img", { name: "PCR trend chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "threshold-line");
    expect(chart).toHaveAttribute("viewBox", "0 0 500 180");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-threshold-band]").length).toBe(2);
    expect(chart.querySelectorAll("path").length).toBeGreaterThanOrEqual(2);
  });

  it("renders a reusable scatter chart with labelled points", () => {
    render(
      <FlintScatterChart
        ariaLabel="Gap fill scatter chart"
        points={[
          { id: "gap-050", label: "Gap 0.50% fill rate 75%", x: 0.5, y: 75, radius: 4, color: "#34d399" },
          { id: "gap-125", label: "Gap 1.25% fill rate 33%", x: 1.25, y: 33, radius: 5, color: "#f87171" },
        ]}
        xDomain={[0, 1.5]}
        yDomain={[0, 100]}
        xTicks={[0.5, 1.0, 1.5]}
        yTicks={[0, 50, 100]}
        xFormatter={(value) => `${value.toFixed(1)}%`}
        yFormatter={(value) => `${value}%`}
        xAxisLabel="Gap size"
        yAxisLabel="Fill probability"
        width={340}
        height={120}
      />,
    );

    const chart = screen.getByRole("img", { name: "Gap fill scatter chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "scatter");
    expect(chart).toHaveAttribute("viewBox", "0 0 340 120");
    expect(chart.querySelectorAll("[data-scatter-point]").length).toBe(2);
    expect(chart.textContent).toContain("Gap size");
    expect(chart.textContent).toContain("Fill probability");
  });

  it("reports active scatter points through the shared primitive", () => {
    const onPointHover = vi.fn();
    render(
      <FlintScatterChart
        ariaLabel="Risk-return scatter chart"
        points={[
          { id: "NIFTYBEES", label: "NIFTYBEES risk return", x: 15.8, y: 14.2, radius: 8, color: "#3b82f6" },
        ]}
        xDomain={[0, 40]}
        yDomain={[0, 50]}
        onPointHover={onPointHover}
      />,
    );

    const point = screen.getByTestId("scatter-point-NIFTYBEES");
    fireEvent.mouseEnter(point);
    expect(onPointHover).toHaveBeenCalledWith(
      expect.objectContaining({ id: "NIFTYBEES", label: "NIFTYBEES risk return" }),
    );
    fireEvent.mouseLeave(point);
    expect(onPointHover).toHaveBeenLastCalledWith(null);
  });

  it("renders a reusable multi-line chart without local polylines", () => {
    render(
      <FlintMultiLineChart
        ariaLabel="Instrument comparison chart"
        series={[
          {
            id: "NIFTY",
            label: "NIFTY",
            color: "#6366f1",
            points: [
              { x: 0, y: 0 },
              { x: 1, y: 1.4 },
              { x: 2, y: 2.1 },
            ],
          },
          {
            id: "BANKNIFTY",
            label: "BANKNIFTY",
            color: "#22c55e",
            points: [
              { x: 0, y: 0 },
              { x: 1, y: 0.8 },
              { x: 2, y: 2.7 },
            ],
          },
        ]}
        xDomain={[0, 2]}
        yDomain={[-1, 3]}
        yTicks={[-1, 0, 1, 2, 3]}
        referenceLines={[{ axis: "y", value: 0, dash: "4,2" }]}
        yFormatter={(value) => `${value > 0 ? "+" : ""}${value}%`}
        width={520}
        height={180}
      />,
    );

    const chart = screen.getByRole("img", { name: "Instrument comparison chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "multi-line");
    expect(chart).toHaveAttribute("viewBox", "0 0 520 180");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelectorAll("[data-line-series]").length).toBe(2);
    expect(chart.querySelectorAll("[data-series-endpoint]").length).toBe(2);
  });

  it("renders a reusable payoff chart with profit and loss zones", () => {
    render(
      <FlintPayoffChart
        ariaLabel="Spread payoff diagram"
        points={[
          { x: 23900, y: -1125 },
          { x: 24000, y: -1125 },
          { x: 24045, y: 0 },
          { x: 24200, y: 3875 },
          { x: 24300, y: 3875 },
        ]}
        breakeven={24045}
        xTicks={[23900, 24100, 24300]}
        yTicks={[-1125, 0, 3875]}
        xFormatter={(value) => value.toLocaleString("en-IN")}
        yFormatter={(value) => value >= 1000 ? `${(value / 1000).toFixed(0)}k` : `${value}`}
        width={500}
        height={140}
      />,
    );

    const chart = screen.getByRole("img", { name: "Spread payoff diagram" });
    expect(chart).toHaveAttribute("data-flint-chart", "payoff");
    expect(chart).toHaveAttribute("viewBox", "0 0 500 140");
    expect(chart.querySelector("polyline")).not.toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='profit']")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-zone='loss']")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-breakeven]")).toBeInTheDocument();
  });

  it("renders options payoff markers and hover state from the shared primitive", () => {
    render(
      <FlintPayoffChart
        ariaLabel="Options payoff chart"
        points={[
          { x: 21700, y: 15000 },
          { x: 22000, y: 0 },
          { x: 22300, y: -15000 },
        ]}
        breakevens={[21700, 22300]}
        strikeMarkers={[22000]}
        spotPrice={22050}
        maxProfit={15000}
        maxLoss={-15000}
        xTicks={[21700, 22000, 22300]}
        yTicks={[-15000, 0, 15000]}
        xFormatter={(value) => value.toFixed(0)}
        yFormatter={(value) => `${value}`}
        interactive
        width={600}
        height={220}
      />,
    );

    const chart = screen.getByRole("img", { name: "Options payoff chart" });
    expect(chart).toHaveAttribute("data-flint-chart", "payoff");
    expect(chart.querySelectorAll("[data-payoff-breakeven]").length).toBe(2);
    expect(chart.querySelector("[aria-label='Strike 22000']")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-spot]")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-max-profit]")).toBeInTheDocument();
    expect(chart.querySelector("[data-payoff-max-loss]")).toBeInTheDocument();
    expect(chart.querySelector("[data-testid='zero-line']")).toBeInTheDocument();

    Object.defineProperty(chart, "getBoundingClientRect", {
      value: () => ({ left: 0, top: 0, width: 600, height: 220 }),
      writable: true,
    });

    fireEvent.mouseMove(chart, { clientX: 260, clientY: 110 });
    expect(chart.querySelector("[data-payoff-tooltip-point]")).toBeInTheDocument();
  });

  it("derives crosshair OHLCV readout state from the shared core event contract", () => {
    const candleSeries = {};
    const volumeSeries = {};

    expect(
      getFlintChartCrosshairReadout(
        {
          time: 1717040700,
          seriesData: new Map([
            [candleSeries, { open: 24100, high: 24180, low: 24080, close: 24155 }],
            [volumeSeries, { value: 150000 }],
          ]),
        },
        candleSeries,
        volumeSeries,
      ),
    ).toEqual({
      time: 1717040700,
      open: 24100,
      high: 24180,
      low: 24080,
      close: 24155,
      volume: 150000,
      bull: true,
    });

    expect(
      getFlintChartCrosshairReadout(
        {
          time: 1717040760,
          seriesData: new Map([
            [candleSeries, { open: 24155, high: 24160, low: 24020, close: 24050 }],
          ]),
        },
        candleSeries,
        volumeSeries,
      ),
    ).toEqual({
      time: 1717040760,
      open: 24155,
      high: 24160,
      low: 24020,
      close: 24050,
      volume: null,
      bull: false,
    });
  });

  it("clears the shared crosshair readout when the candle payload is absent", () => {
    const candleSeries = {};

    expect(
      getFlintChartCrosshairReadout(
        { time: 1717040700, seriesData: new Map() },
        candleSeries,
      ),
    ).toBeNull();

    expect(
      getFlintChartCrosshairReadout(
        { seriesData: new Map([[candleSeries, { open: 1, high: 2, low: 1, close: 2 }]]) },
        candleSeries,
      ),
    ).toBeNull();
  });

  it("selects intervals from the shared chart pill control", () => {
    const onSelect = vi.fn();
    render(
      <FlintChartIntervalPills
        intervals={[
          { label: "1m", value: "1m" },
          { label: "5m", value: "5m" },
          { label: "15m", value: "15m" },
        ]}
        active="5m"
        onSelect={onSelect}
      />,
    );

    expect(screen.getByRole("button", { name: "5m" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "15m" }));
    expect(onSelect).toHaveBeenCalledWith("15m");
  });

  it("routes drawing rail actions through the core toolbar", () => {
    const onToggle = vi.fn();
    render(
      <FlintChartDrawingToolbar
        drawMode={null}
        onToggle={onToggle}
        onClearAll={vi.fn()}
        storageKeyPrefix="flinttrade:test-chart-toolbar"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Trend Line" }));
    expect(onToggle).toHaveBeenCalledWith("trendline");
  });

  it("supports horizontal drawing tools for compact chart workspaces", () => {
    const onToggle = vi.fn();
    render(
      <FlintChartDrawingToolbar
        drawMode={null}
        onToggle={onToggle}
        onClearAll={vi.fn()}
        storageKeyPrefix="flinttrade:test-horizontal-chart-toolbar"
        orientation="horizontal"
      />,
    );

    const toolbar = screen.getByRole("toolbar", { name: "Drawing tools" });
    expect(toolbar).toHaveAttribute("aria-orientation", "horizontal");
    expect(toolbar).toHaveAttribute("data-orientation", "horizontal");

    fireEvent.click(screen.getByRole("button", { name: "Trend Line" }));
    expect(onToggle).toHaveBeenCalledWith("trendline");

    fireEvent.click(screen.getByRole("button", { name: "Expand lines tools" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });

  it("derives compact chart workspace layout from core breakpoints", () => {
    expect(getFlintChartWorkspaceLayout(0)).toEqual({
      compact: false,
      toolbarOrientation: "vertical",
    });
    expect(getFlintChartWorkspaceLayout(519)).toEqual({
      compact: true,
      toolbarOrientation: "horizontal",
    });
    expect(getFlintChartWorkspaceLayout(520)).toEqual({
      compact: false,
      toolbarOrientation: "vertical",
    });
  });

  it("derives draw-mode instructions from shared core state", () => {
    expect(
      getFlintChartDrawInstruction({
        drawMode: "trendline",
        pendingPoint: null,
        awaitingText: null,
      }),
    ).toBe("Click first point");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "trendline",
        pendingPoint: { time: 1, price: 2 },
        awaitingText: null,
      }),
    ).toBe("Click second point");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "parallel_channel",
        pendingPoint: { time: 2, price: 3 },
        pendingPoints: [
          { time: 1, price: 2 },
          { time: 2, price: 3 },
        ],
        awaitingText: null,
      }),
    ).toBe("Click channel width");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "fib_extension",
        pendingPoint: { time: 2, price: 3 },
        pendingPoints: [
          { time: 1, price: 2 },
          { time: 2, price: 3 },
        ],
        awaitingText: null,
      }),
    ).toBe("Click extension anchor");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "long_position",
        pendingPoint: null,
        pendingPoints: [],
        awaitingText: null,
      }),
    ).toBe("Click entry point");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "short_position",
        pendingPoint: { time: 1, price: 2 },
        pendingPoints: [{ time: 1, price: 2 }],
        awaitingText: null,
      }),
    ).toBe("Click target point");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "long_position",
        pendingPoint: { time: 2, price: 3 },
        pendingPoints: [
          { time: 1, price: 2 },
          { time: 2, price: 3 },
        ],
        awaitingText: null,
      }),
    ).toBe("Click stop point");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "elliott_impulse",
        pendingPoint: null,
        pendingPoints: [],
        awaitingText: null,
      }),
    ).toBe("Click wave 0");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "elliott_impulse",
        pendingPoint: { time: 4, price: 5 },
        pendingPoints: [
          { time: 1, price: 2 },
          { time: 2, price: 3 },
          { time: 3, price: 4 },
          { time: 4, price: 5 },
        ],
        awaitingText: null,
      }),
    ).toBe("Click wave 4");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "elliott_correction",
        pendingPoint: { time: 3, price: 4 },
        pendingPoints: [
          { time: 1, price: 2 },
          { time: 2, price: 3 },
          { time: 3, price: 4 },
        ],
        awaitingText: null,
      }),
    ).toBe("Click wave C");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "brush",
        pendingPoint: null,
        awaitingText: null,
      }),
    ).toBe("Drag to draw");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "text",
        pendingPoint: null,
        awaitingText: { time: 1, price: 2 },
      }),
    ).toBe("Type text below");

    expect(
      getFlintChartDrawInstruction({
        drawMode: "eraser",
        pendingPoint: null,
        awaitingText: null,
      }),
    ).toBe("Click drawing to erase");
  });

  it("renders drawing count and active draw instruction together", () => {
    render(
      <FlintChartDrawStatus
        drawMode="fib"
        drawingCount={2}
        pendingPoint={null}
        awaitingText={null}
      />,
    );

    expect(screen.getByText("2 drawings")).toBeInTheDocument();
    expect(screen.getByText("Click first point")).toBeInTheDocument();
  });

  it("renders selectable drawing summaries and delete actions from the core UI", () => {
    const onSelectDrawing = vi.fn();
    const onDeleteDrawing = vi.fn();

    render(
      <FlintChartDrawingList
        drawings={[
          { kind: "hline", id: "support", price: 22100 },
          {
            kind: "text",
            id: "note",
            point: { time: 3, price: 22320 },
            label: "Breakout",
          },
        ]}
        selectedDrawingId="support"
        onSelectDrawing={onSelectDrawing}
        onDeleteDrawing={onDeleteDrawing}
      />,
    );

    expect(screen.getByRole("button", { name: "Select Horizontal Line 22,100.00" }))
      .toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Select Text: Breakout" }));
    expect(onSelectDrawing).toHaveBeenCalledWith("note");

    fireEvent.click(screen.getByRole("button", { name: "Delete Horizontal Line 22,100.00" }));
    expect(onDeleteDrawing).toHaveBeenCalledWith("support");
  });

  it("shows locked and hidden drawing state in the shared drawing list", () => {
    const onSelectDrawing = vi.fn();
    const onDeleteDrawing = vi.fn();

    render(
      <FlintChartDrawingList
        drawings={[
          { kind: "hline", id: "support", price: 22100, locked: true },
          {
            kind: "text",
            id: "note",
            point: { time: 3, price: 22320 },
            label: "Breakout",
            hidden: true,
          },
        ]}
        selectedDrawingId="support"
        onSelectDrawing={onSelectDrawing}
        onDeleteDrawing={onDeleteDrawing}
      />,
    );

    expect(screen.getByText("Locked")).toBeInTheDocument();
    expect(screen.getByText("Hidden")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete Horizontal Line 22,100.00" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Delete Horizontal Line 22,100.00" }));
    expect(onDeleteDrawing).not.toHaveBeenCalled();
  });

  it("edits selected drawing style through core swatches and segmented controls", () => {
    const onChange = vi.fn();

    render(
      <FlintChartDrawingStyleEditor
        drawing={{ kind: "hline", id: "support", price: 22100 }}
        value={{ color: "#3b82f6", lineWidth: 1, lineStyle: "solid" }}
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Set drawing colour teal" }));
    expect(onChange).toHaveBeenCalledWith({ color: "#14b8a6" });

    fireEvent.click(screen.getByRole("button", { name: "Set drawing line style dashed" }));
    expect(onChange).toHaveBeenCalledWith({ lineStyle: "dashed" });

    fireEvent.click(screen.getByRole("button", { name: "Set drawing line width 3" }));
    expect(onChange).toHaveBeenCalledWith({ lineWidth: 3 });
  });

  it("disables drawing style controls when the selected drawing is locked", () => {
    const onChange = vi.fn();

    render(
      <FlintChartDrawingStyleEditor
        drawing={{ kind: "hline", id: "support", price: 22100, locked: true }}
        value={{ color: "#3b82f6", lineWidth: 1, lineStyle: "solid" }}
        onChange={onChange}
      />,
    );

    const tealButton = screen.getByRole("button", { name: "Set drawing colour teal" });
    expect(tealButton).toBeDisabled();
    fireEvent.click(tealButton);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("renders a selected drawing inspector with state actions and style controls", () => {
    const onStyleChange = vi.fn();
    const onToggleHidden = vi.fn();
    const onToggleLocked = vi.fn();
    const onDeleteDrawing = vi.fn();

    render(
      <FlintChartDrawingInspector
        drawing={{ kind: "hline", id: "support", price: 22100 }}
        value={{ color: "#3b82f6", lineWidth: 1, lineStyle: "solid" }}
        onStyleChange={onStyleChange}
        onToggleHidden={onToggleHidden}
        onToggleLocked={onToggleLocked}
        onDeleteDrawing={onDeleteDrawing}
      />,
    );

    expect(screen.getByText("Selected drawing")).toBeInTheDocument();
    expect(screen.getByText("Horizontal Line 22,100.00")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Hide Horizontal Line 22,100.00" }));
    expect(onToggleHidden).toHaveBeenCalledWith("support", true);

    fireEvent.click(screen.getByRole("button", { name: "Lock Horizontal Line 22,100.00" }));
    expect(onToggleLocked).toHaveBeenCalledWith("support", true);

    fireEvent.click(screen.getByRole("button", { name: "Delete selected Horizontal Line 22,100.00" }));
    expect(onDeleteDrawing).toHaveBeenCalledWith("support");

    fireEvent.click(screen.getByRole("button", { name: "Set drawing colour teal" }));
    expect(onStyleChange).toHaveBeenCalledWith({ color: "#14b8a6" });
  });

  it("lets locked selected drawings be unlocked but not deleted or restyled", () => {
    const onStyleChange = vi.fn();
    const onToggleHidden = vi.fn();
    const onToggleLocked = vi.fn();
    const onDeleteDrawing = vi.fn();

    render(
      <FlintChartDrawingInspector
        drawing={{ kind: "hline", id: "support", price: 22100, locked: true, hidden: true }}
        value={{ color: "#3b82f6", lineWidth: 1, lineStyle: "solid" }}
        onStyleChange={onStyleChange}
        onToggleHidden={onToggleHidden}
        onToggleLocked={onToggleLocked}
        onDeleteDrawing={onDeleteDrawing}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show Horizontal Line 22,100.00" }));
    expect(onToggleHidden).toHaveBeenCalledWith("support", false);

    fireEvent.click(screen.getByRole("button", { name: "Unlock Horizontal Line 22,100.00" }));
    expect(onToggleLocked).toHaveBeenCalledWith("support", false);

    expect(screen.getByRole("button", { name: "Delete selected Horizontal Line 22,100.00" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set drawing colour teal" })).toBeDisabled();
  });

  it("maps chart keyboard shortcuts in core while ignoring editable fields", () => {
    expect(getFlintChartKeyboardAction({ key: "2" })).toEqual({
      kind: "set-tool",
      tool: "trendline",
    });
    expect(getFlintChartKeyboardAction({ key: "Escape" })).toEqual({ kind: "cancel-drawing" });
    expect(getFlintChartKeyboardAction({ key: "z", metaKey: true })).toEqual({ kind: "undo-drawing" });
    expect(getFlintChartKeyboardAction({ key: "Backspace" })).toEqual({ kind: "delete-last-drawing" });

    const input = document.createElement("input");
    expect(getFlintChartKeyboardAction({ key: "2", target: input })).toBeNull();
  });
});
