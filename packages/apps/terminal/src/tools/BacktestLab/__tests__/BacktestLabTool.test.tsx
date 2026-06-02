import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const chartMocks = vi.hoisted(() => {
  const lineSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];
  const setData = vi.fn();

  const createSeries = () => ({
    applyOptions: vi.fn(),
    setData,
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
    resize: vi.fn(),
    timeScale: vi.fn(() => ({ fitContent: vi.fn() })),
  };

  const shellRuntime = {
    createChart: vi.fn(() => chart),
  };

  const lineRuntime = {
    createChart: shellRuntime.createChart,
    addLineSeries: vi.fn((_chart: unknown, options: unknown) => {
      lineSeriesOptions.push(options);
      return createSeries();
    }),
  };

  return {
    chart,
    lineRuntime,
    lineSeriesOptions,
    localSeriesOptions,
    reset() {
      lineSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      setData.mockClear();
    },
  };
});

const apiMocks = vi.hoisted(() => ({
  runBacktest: vi.fn(),
}));

vi.mock("lightweight-charts", () => ({
  createChart: chartMocks.lineRuntime.createChart,
  LineSeries: "LineSeries",
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: chartMocks.lineRuntime,
  lightweightLineRuntime: chartMocks.lineRuntime,
}));

vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    crosshair: {},
    rightPriceScale: {},
    timeScale: {},
    handleScale: false,
    handleScroll: false,
    kineticScroll: {},
    trackingMode: {},
  }),
}));

vi.mock("@/services/ftApi", () => ({
  runBacktest: apiMocks.runBacktest,
}));

vi.mock("@/components/ui/select", async () => {
  const React = await import("react");
  const SelectContext = React.createContext<{
    onValueChange?: (value: string) => void;
    value?: string;
  }>({});

  return {
    Select({
      children,
      onValueChange,
      value,
    }: {
      children: React.ReactNode;
      onValueChange?: (value: string) => void;
      value?: string;
    }) {
      return React.createElement(
        SelectContext.Provider,
        { value: { onValueChange, value } },
        children,
      );
    },
    SelectContent({ children }: { children: React.ReactNode }) {
      return React.createElement("div", null, children);
    },
    SelectItem({
      children,
      value,
    }: {
      children: React.ReactNode;
      value: string;
    }) {
      const context = React.useContext(SelectContext);
      return React.createElement(
        "button",
        {
          "aria-selected": context.value === value,
          onClick: () => context.onValueChange?.(value),
          role: "option",
          type: "button",
        },
        children,
      );
    },
    SelectTrigger({ children }: { children: React.ReactNode }) {
      return React.createElement("button", { type: "button" }, children);
    },
    SelectValue({ placeholder }: { placeholder?: string }) {
      return React.createElement("span", null, placeholder);
    },
  };
});

import BacktestLabTool from "../BacktestLabTool";

const testDir = dirname(fileURLToPath(import.meta.url));
const backtestLabSource = () =>
  readFileSync(resolve(testDir, "../BacktestLabTool.tsx"), "utf8");

function renderBacktestLab() {
  const queryClient = new QueryClient({
    defaultOptions: {
      mutations: { retry: false },
      queries: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <BacktestLabTool />
    </QueryClientProvider>,
  );
}

describe("BacktestLabTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    chartMocks.reset();
    apiMocks.runBacktest.mockRejectedValue(new Error("Backend unavailable"));
  });

  it("routes the equity curve through the shared Flint line chart runtime", async () => {
    const user = userEvent.setup();
    renderBacktestLab();

    await user.click(screen.getByRole("option", { name: /EMA Crossover/i }));
    await user.type(screen.getByPlaceholderText("RELIANCE"), "RELIANCE");
    await user.click(screen.getByRole("button", { name: /Run Backtest/i }));

    await screen.findByText("Mock data");

    await waitFor(() => {
      expect(chartMocks.lineRuntime.addLineSeries).toHaveBeenCalledTimes(1);
    });
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.lineSeriesOptions).toEqual([
      expect.objectContaining({
        color: "#34d399",
        lineWidth: 2,
        priceFormat: { type: "price", precision: 0, minMove: 1 },
      }),
    ]);
  });

  it("keeps fallback chart artwork out of local inline SVG markup", () => {
    expect(backtestLabSource()).not.toContain("<" + "svg");
    expect(backtestLabSource()).not.toContain("<" + "polyline");
    expect(backtestLabSource()).not.toContain("<" + "polygon");
  });
});
