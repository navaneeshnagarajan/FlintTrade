/**
 * PortfolioPivotWidget.test.tsx
 *
 * The Perspective engine boundary is mocked (WASM workers cannot run in
 * jsdom); a stub `perspective-viewer` custom element captures load/
 * restore/save calls. Pins: fail-closed connect gating with no sample
 * rows, schema-first table creation, position rows streamed via
 * replace(), saved-view restore, and view persistence as a PARTIAL
 * updateParameters patch.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockState = vi.hoisted(() => ({
  brokerConnected: true,
  positions: [] as Position[],
  table: {
    replace: vi.fn(async () => {}),
    delete: vi.fn(async () => {}),
  },
  workerTable: vi.fn(),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => mockState.brokerConnected,
}));

vi.mock("@/hooks/usePositions", () => ({
  usePositions: () => ({ data: mockState.positions }),
}));

vi.mock("@finos/perspective", () => ({
  default: {
    worker: vi.fn(async () => ({
      table: mockState.workerTable,
    })),
  },
}));
vi.mock("@finos/perspective-viewer", () => ({}));
vi.mock("@finos/perspective-viewer-datagrid", () => ({}));

// Stub custom element capturing the viewer API surface the widget uses.
const viewerCalls = vi.hoisted(() => ({
  load: vi.fn(async () => {}),
  restore: vi.fn(async () => {}),
  save: vi.fn(async () => ({ group_by: ["product"] })),
  delete: vi.fn(async () => {}),
}));

class StubPerspectiveViewer extends HTMLElement {
  load = viewerCalls.load;
  restore = viewerCalls.restore;
  save = viewerCalls.save;
  delete = viewerCalls.delete;
}
if (!customElements.get("perspective-viewer")) {
  customElements.define("perspective-viewer", StubPerspectiveViewer);
}

import PortfolioPivotWidget from "../PortfolioPivotWidget";

const POSITIONS: Position[] = [
  {
    symbol: "NIFTY24AUGFUT",
    exchange: "NFO",
    product: "NRML",
    quantity: 50,
    averagePrice: 24800,
    ltp: 24900,
    pnl: 5000,
    pnlPercent: 0.4,
  },
];

describe("PortfolioPivotWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockState.brokerConnected = true;
    mockState.positions = POSITIONS;
    mockState.workerTable.mockResolvedValue(mockState.table);
  });

  it("fails closed with a connect affordance (and no sample rows) when no broker is connected", () => {
    mockState.brokerConnected = false;
    render(<PortfolioPivotWidget {...makeWidgetPanelProps()} />);

    expect(screen.getByTestId("portfolio-pivot-disconnected")).toBeInTheDocument();
    expect(screen.getByText(/connect a broker/i)).toBeInTheDocument();
    expect(mockState.workerTable).not.toHaveBeenCalled();
  });

  it("creates the table with the explicit position schema and loads the viewer", async () => {
    render(<PortfolioPivotWidget {...makeWidgetPanelProps()} />);

    await waitFor(() => expect(viewerCalls.load).toHaveBeenCalledTimes(1));
    expect(mockState.workerTable).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: "string", pnl: "float", quantity: "integer" }),
    );
  });

  it("streams the position book into the table via replace()", async () => {
    render(<PortfolioPivotWidget {...makeWidgetPanelProps()} />);

    await waitFor(() => expect(mockState.table.replace).toHaveBeenCalled());
    expect(mockState.table.replace).toHaveBeenCalledWith([
      expect.objectContaining({ symbol: "NIFTY24AUGFUT", pnl: 5000, product: "NRML" }),
    ]);
  });

  it("restores a saved view config from panel params", async () => {
    render(
      <PortfolioPivotWidget
        {...makeWidgetPanelProps({ params: { viewConfig: { group_by: ["exchange"] } } })}
      />,
    );

    await waitFor(() =>
      expect(viewerCalls.restore).toHaveBeenCalledWith({ group_by: ["exchange"] }),
    );
  });

  it("persists view changes as a partial updateParameters patch", async () => {
    const props = makeWidgetPanelProps();
    render(<PortfolioPivotWidget {...props} />);
    await waitFor(() => expect(viewerCalls.load).toHaveBeenCalled());

    const viewer = screen
      .getByTestId("portfolio-pivot-viewer-host")
      .querySelector("perspective-viewer");
    expect(viewer).not.toBeNull();
    await act(async () => {
      viewer!.dispatchEvent(new Event("perspective-config-update"));
      // The widget debounces persistence by 500ms.
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    expect(props.updateParametersCalls).toEqual([{ viewConfig: { group_by: ["product"] } }]);
  });

  it("shows the failure card with a retry action when the engine cannot start", async () => {
    mockState.workerTable.mockRejectedValueOnce(new Error("wasm failed"));
    render(<PortfolioPivotWidget {...makeWidgetPanelProps()} />);

    expect(await screen.findByTestId("portfolio-pivot-failed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
