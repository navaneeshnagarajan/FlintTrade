/**
 * FlowBuilderTool.test.tsx
 *
 * Tests for the Flow Builder canvas tool.
 * Verifies rendering, the backend-persisted saved-flows list (TanStack Query
 * over a mocked ftApi.flows client), save/delete mutations, the one-time
 * localStorage → backend import, and the honest workspace-persistence framing.
 *
 * @xyflow/react is mocked because it requires a ResizeObserver and canvas
 * environment not available in jsdom.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

// ---------------------------------------------------------------------------
// Mocks — localStorage (legacy draft import) + ftApi.flows client
// ---------------------------------------------------------------------------

const localStorageMock: Record<string, string> = {};

vi.stubGlobal("localStorage", {
  getItem: vi.fn((key: string) => localStorageMock[key] ?? null),
  setItem: vi.fn((key: string, value: string) => {
    localStorageMock[key] = value;
  }),
  removeItem: vi.fn((key: string) => {
    delete localStorageMock[key];
  }),
  clear: vi.fn(),
  length: 0,
  key: vi.fn(),
});

vi.mock("@/services/ftApi.flows", () => ({
  listFlows: vi.fn(),
  getFlow: vi.fn(),
  putFlow: vi.fn(),
  deleteFlow: vi.fn(),
}));

// Mock ResizeObserver (required by @xyflow/react internals)
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
);

// ---------------------------------------------------------------------------
// Mock @xyflow/react — avoids canvas/DOM requirements in test env
// ---------------------------------------------------------------------------

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-flow-canvas">{children}</div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: "dots" },
  Controls: () => null,
  MiniMap: () => null,
  Panel: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  applyNodeChanges: vi.fn((_, nodes) => nodes),
  applyEdgeChanges: vi.fn((_, edges) => edges),
  addEdge: vi.fn((connection, edges) => [...edges, connection]),
  useStore: vi.fn(() => ({ inProgress: false })),
  Handle: ({ type, position }: { type: string; position: string }) => (
    <div data-testid={`handle-${type}-${position}`} />
  ),
  Position: { Top: "top", Bottom: "bottom", Left: "left", Right: "right" },
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import FlowBuilderTool from "../FlowBuilderTool";
import { HowItWorksTab } from "../flow/HowItWorksTab";
import { TemplatesTab } from "../flow/TemplatesTab";
import { LEGACY_FLOWS_KEY } from "../flow/legacyFlowImport";
import { useFlowStore, type SavedWorkflow } from "@/stores/flowStore";
import { useModeStore } from "@/stores/modeStore";
import {
  listFlows,
  getFlow,
  putFlow,
  deleteFlow,
  type FlowSummary,
  type StoredWorkflow,
} from "@/services/ftApi.flows";

const mockListFlows = vi.mocked(listFlows);
const mockGetFlow = vi.mocked(getFlow);
const mockPutFlow = vi.mocked(putFlow);
const mockDeleteFlow = vi.mocked(deleteFlow);

// ---------------------------------------------------------------------------
// Fixtures / helpers
// ---------------------------------------------------------------------------

function makeSummary(overrides: Partial<FlowSummary> = {}): FlowSummary {
  return {
    id: "flow_1",
    name: "Breakout alerts",
    updatedAt: "2026-07-19T09:15:00Z",
    node_count: 3,
    saved_at: "2026-07-19T09:15:01Z",
    ...overrides,
  };
}

function makeWorkflow(overrides: Partial<SavedWorkflow> = {}): SavedWorkflow {
  return {
    id: "flow_1",
    name: "Breakout alerts",
    nodes: [],
    edges: [],
    updatedAt: "2026-07-19T09:15:00Z",
    ...overrides,
  };
}

function asStored(flow: SavedWorkflow): StoredWorkflow {
  return { ...flow, saved_at: "2026-07-19T09:15:01Z" };
}

function renderWithClient(ui: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FlowBuilderTool", () => {
  beforeEach(() => {
    // resetAllMocks clears call history and once-queues on the module-mocked
    // flows client; the localStorage stub keeps its creation-time impls.
    vi.resetAllMocks();
    // Clear stored keys (legacy drafts + persisted mode) between tests
    Object.keys(localStorageMock).forEach((k) => delete localStorageMock[k]);
    // Reset canvas/UI store state
    useFlowStore.setState({
      nodes: [],
      edges: [],
      selectedNodeId: null,
      isRunning: false,
      executionLog: [],
      activeFlowId: null,
    });
    useModeStore.setState({ mode: "explore" });
    // Default client behaviour: empty backend store, happy-path writes
    mockListFlows.mockResolvedValue([]);
    mockGetFlow.mockResolvedValue(asStored(makeWorkflow()));
    mockPutFlow.mockImplementation((flow) =>
      Promise.resolve({ ...asStored(flow), validation: [] })
    );
    mockDeleteFlow.mockResolvedValue(undefined);
  });

  it("renders without crashing", () => {
    const { container } = renderWithClient(<FlowBuilderTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Flow Builder heading", () => {
    renderWithClient(<FlowBuilderTool />);
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
  });

  it("displays the node count badge", () => {
    renderWithClient(<FlowBuilderTool />);
    // The badge is derived from the canonical node registry.
    const badge = screen.getByText(/\d+ nodes/);
    expect(badge).toBeInTheDocument();
  });

  it("shows Flows, Templates, and How It Works tabs", () => {
    renderWithClient(<FlowBuilderTool />);
    expect(screen.getByText("Flows")).toBeInTheDocument();
    expect(screen.getByText("Templates")).toBeInTheDocument();
    expect(screen.getByText("How It Works")).toBeInTheDocument();
  });

  it("shows empty state message when the backend has no flows", async () => {
    renderWithClient(<FlowBuilderTool />);
    expect(await screen.findByText("No flows yet")).toBeInTheDocument();
    expect(mockListFlows).toHaveBeenCalled();
  });

  it("lists saved flows from the backend workspace", async () => {
    mockListFlows.mockResolvedValue([
      makeSummary(),
      makeSummary({ id: "flow_2", name: "Gap scanner", node_count: 5 }),
    ]);

    renderWithClient(<FlowBuilderTool />);

    expect(await screen.findByText("Breakout alerts")).toBeInTheDocument();
    expect(screen.getByText("Gap scanner")).toBeInTheDocument();
    expect(screen.getByText("2 flows saved in your workspace")).toBeInTheDocument();
    expect(screen.getByText("5 nodes")).toBeInTheDocument();
  });

  it("surfaces a list-load failure instead of claiming an empty store", async () => {
    mockListFlows.mockRejectedValue(new Error("backend unreachable"));

    renderWithClient(<FlowBuilderTool />);

    expect(
      await screen.findByText(/Could not load saved flows — backend unreachable/)
    ).toBeInTheDocument();
    expect(screen.queryByText("No flows yet")).not.toBeInTheDocument();
  });

  it("opens the real canvas editor and PUTs the new flow to the backend", async () => {
    renderWithClient(<FlowBuilderTool />);

    fireEvent.click(screen.getAllByRole("button", { name: "New Flow" })[0]);

    expect(screen.getByTestId("react-flow-canvas")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(1));
    expect(mockPutFlow.mock.calls[0][0]).toEqual(
      expect.objectContaining({ name: "New Flow", nodes: [], edges: [] })
    );
  });

  it("saves the edited flow through the backend mutation", async () => {
    const user = userEvent.setup();
    renderWithClient(<FlowBuilderTool />);
    await user.click(screen.getAllByRole("button", { name: "New Flow" })[0]);
    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(1));

    await user.type(screen.getByRole("textbox", { name: "Flow name" }), "!");
    expect(screen.getByText("Unsaved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(2));
    expect(mockPutFlow.mock.calls[1][0]).toEqual(
      expect.objectContaining({ name: "New Flow!" })
    );
    await waitFor(() => {
      expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    });
  });

  it("keeps the honest not-saved label when the backend save fails", async () => {
    const user = userEvent.setup();
    renderWithClient(<FlowBuilderTool />);
    await user.click(screen.getAllByRole("button", { name: "New Flow" })[0]);
    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(1));

    mockPutFlow.mockRejectedValue(new Error("backend unreachable"));
    await user.type(screen.getByRole("textbox", { name: "Flow name" }), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(/Not saved — backend unreachable/)
    ).toBeInTheDocument();
  });

  it("opens a saved flow by fetching its full graph from the backend", async () => {
    const user = userEvent.setup();
    mockListFlows.mockResolvedValue([makeSummary({ node_count: 1 })]);
    mockGetFlow.mockResolvedValue(
      asStored(
        makeWorkflow({
          nodes: [
            {
              id: "n_1",
              type: "flowNode",
              position: { x: 0, y: 0 },
              data: { label: "LTP", nodeType: "ltp", category: "data", color: "#fff", config: {} },
            },
          ],
        })
      )
    );

    renderWithClient(<FlowBuilderTool />);
    await user.click(await screen.findByRole("button", { name: "Open" }));

    expect(mockGetFlow).toHaveBeenCalledWith("flow_1");
    expect(await screen.findByTestId("react-flow-canvas")).toBeInTheDocument();
    expect(screen.getByText("1 nodes · 0 edges")).toBeInTheDocument();
  });

  it("deletes a saved flow via the backend and refreshes the list", async () => {
    const user = userEvent.setup();
    mockListFlows
      .mockResolvedValueOnce([makeSummary()])
      .mockResolvedValue([]);

    renderWithClient(<FlowBuilderTool />);
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => expect(mockDeleteFlow).toHaveBeenCalledWith("flow_1"));
    expect(await screen.findByText("No flows yet")).toBeInTheDocument();
  });

  it("lets Enter on a palette button add a node to the canvas", async () => {
    const user = userEvent.setup();
    renderWithClient(<FlowBuilderTool />);
    await user.click(screen.getAllByRole("button", { name: "New Flow" })[0]);

    expect(screen.getByRole("textbox", { name: "Flow name" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Search nodes" }), "Search Symbol");
    await user.click(screen.getByRole("button", { name: /Data/ }));
    screen.getByRole("button", { name: "Search Symbol" }).focus();
    await user.keyboard("{Enter}");

    expect(screen.getByText("1 nodes · 0 edges")).toBeInTheDocument();
  });

  it("imports legacy localStorage drafts once and removes the key after success", async () => {
    useModeStore.setState({ mode: "practice" });
    localStorageMock[LEGACY_FLOWS_KEY] = JSON.stringify({
      flows: [
        makeWorkflow({ id: "flow_legacy_1", name: "Old draft one" }),
        makeWorkflow({ id: "flow_legacy_2", name: "Old draft two" }),
      ],
    });

    renderWithClient(<FlowBuilderTool />);

    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(2));
    expect(mockPutFlow).toHaveBeenCalledWith(
      expect.objectContaining({ id: "flow_legacy_1" })
    );
    expect(mockPutFlow).toHaveBeenCalledWith(
      expect.objectContaining({ id: "flow_legacy_2" })
    );
    await waitFor(() => {
      expect(localStorageMock[LEGACY_FLOWS_KEY]).toBeUndefined();
    });
  });

  it("keeps the legacy key when any import PUT fails, so the next mount retries", async () => {
    useModeStore.setState({ mode: "practice" });
    localStorageMock[LEGACY_FLOWS_KEY] = JSON.stringify({
      flows: [
        makeWorkflow({ id: "flow_legacy_1", name: "Old draft one" }),
        makeWorkflow({ id: "flow_legacy_2", name: "Old draft two" }),
      ],
    });
    mockPutFlow
      .mockRejectedValueOnce(new Error("backend unreachable"))
      .mockImplementation((flow) => Promise.resolve({ ...asStored(flow), validation: [] }));

    renderWithClient(<FlowBuilderTool />);

    await waitFor(() => expect(mockPutFlow).toHaveBeenCalledTimes(2));
    expect(localStorageMock[LEGACY_FLOWS_KEY]).toBeDefined();
  });

  it("skips the legacy import in Explore mode", async () => {
    useModeStore.setState({ mode: "explore" });
    localStorageMock[LEGACY_FLOWS_KEY] = JSON.stringify({
      flows: [makeWorkflow({ id: "flow_legacy_1" })],
    });

    renderWithClient(<FlowBuilderTool />);

    expect(await screen.findByText("No flows yet")).toBeInTheDocument();
    expect(mockPutFlow).not.toHaveBeenCalled();
    expect(localStorageMock[LEGACY_FLOWS_KEY]).toBeDefined();
  });

  it("describes saved flows as workspace-persisted drafts, not executable automation", () => {
    render(<HowItWorksTab />);

    expect(screen.getByText(/visual draft editor/i)).toBeInTheDocument();
    expect(screen.getByText(/stored in your FlintTrade workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/backend flow execution is not wired/i)).toBeInTheDocument();
    expect(screen.queryByText(/remain in this browser/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/flows run on the FlintTrade Python backend/i)).not.toBeInTheDocument();
  });

  it("labels templates as saved drafts and only loads their canvas data", async () => {
    const user = userEvent.setup();
    const onUse = vi.fn();
    render(<TemplatesTab onUse={onUse} />);

    expect(screen.getByText(/saves a draft to your workspace/i)).toBeInTheDocument();
    expect(screen.getByText(/does not execute a workflow or send an order/i)).toBeInTheDocument();
    expect(screen.queryByText(/timed execution/i)).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Load draft" })[0]);
    expect(onUse).toHaveBeenCalledOnce();
  });
});
