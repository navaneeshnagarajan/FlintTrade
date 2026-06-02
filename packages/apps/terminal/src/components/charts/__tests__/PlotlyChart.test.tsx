import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import type { Data } from "plotly.js";

const plotlyMocks = vi.hoisted(() => ({
  purge: vi.fn(),
  react: vi.fn(() => Promise.resolve()),
  resize: vi.fn(() => Promise.resolve()),
}));

vi.mock("plotly.js-dist-min", () => ({
  default: {
    react: plotlyMocks.react,
    purge: plotlyMocks.purge,
    Plots: {
      resize: plotlyMocks.resize,
    },
  },
}));

vi.mock("@/hooks/usePlotlyTheme", () => ({
  usePlotlyTheme: () => ({
    paper_bgcolor: "#05070d",
    plot_bgcolor: "#05070d",
    xaxis: { gridcolor: "#223" },
    yaxis: { gridcolor: "#223" },
  }),
}));

import { PlotlyChart } from "../PlotlyChart";

describe("PlotlyChart", () => {
  beforeEach(() => {
    plotlyMocks.purge.mockClear();
    plotlyMocks.react.mockClear();
    plotlyMocks.resize.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders through the local Plotly runtime without react-plotly default interop", async () => {
    const data: Data[] = [{ type: "bar", x: [1, 2], y: [3, 4] } as Data];

    const { container, unmount } = render(
      <PlotlyChart
        data={data}
        layout={{ margin: { t: 8, r: 8, b: 20, l: 32 } }}
      />,
    );

    await waitFor(() => expect(plotlyMocks.react).toHaveBeenCalledTimes(1));
    const [root, plottedData] = plotlyMocks.react.mock.calls[0] as unknown as [Element, Data[]];
    expect(root).toBe(container.firstElementChild);
    expect(plottedData).toBe(data);

    unmount();
    expect(plotlyMocks.purge).toHaveBeenCalledTimes(1);
  });

  it("does not ask Plotly to resize a hidden chart container", async () => {
    const resizeCallbacks: ResizeObserverCallback[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class ResizeObserver {
        constructor(callback: ResizeObserverCallback) {
          resizeCallbacks.push(callback);
        }

        observe = vi.fn();
        disconnect = vi.fn();
      },
    );

    render(<PlotlyChart data={[{ type: "bar", x: [1], y: [1] } as Data]} />);
    await waitFor(() => expect(plotlyMocks.react).toHaveBeenCalledTimes(1));

    resizeCallbacks[0]?.([] as unknown as ResizeObserverEntry[], {} as ResizeObserver);

    expect(plotlyMocks.resize).not.toHaveBeenCalled();
  });
});
