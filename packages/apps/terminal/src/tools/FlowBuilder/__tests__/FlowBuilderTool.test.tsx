/**
 * FlowBuilderTool.test.tsx
 *
 * Tests for the Flow Builder canvas tool.
 * Verifies rendering, heading, and key UI elements.
 *
 * @xyflow/react is mocked because it requires a ResizeObserver and canvas
 * environment not available in jsdom.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — localStorage for stored flows
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

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FlowBuilderTool", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // Clear stored flows between tests
    Object.keys(localStorageMock).forEach((k) => delete localStorageMock[k]);
  });

  it("renders without crashing", () => {
    const { container } = render(<FlowBuilderTool />);
    expect(container).toBeInTheDocument();
  });

  it("shows the Flow Builder heading", () => {
    render(<FlowBuilderTool />);
    expect(screen.getByText("Flow Builder")).toBeInTheDocument();
  });

  it("displays the node count badge", () => {
    render(<FlowBuilderTool />);
    // The badge is derived from the canonical node registry.
    const badge = screen.getByText(/\d+ nodes/);
    expect(badge).toBeInTheDocument();
  });

  it("shows Flows, Templates, and How It Works tabs", () => {
    render(<FlowBuilderTool />);
    expect(screen.getByText("Flows")).toBeInTheDocument();
    expect(screen.getByText("Templates")).toBeInTheDocument();
    expect(screen.getByText("How It Works")).toBeInTheDocument();
  });

  it("shows empty state message when no flows exist", () => {
    render(<FlowBuilderTool />);
    expect(screen.getByText("No flows yet")).toBeInTheDocument();
  });

  it("opens the real canvas editor without advertising an unwired Run action", () => {
    render(<FlowBuilderTool />);

    fireEvent.click(screen.getAllByRole("button", { name: "New Flow" })[0]);

    expect(screen.getByTestId("react-flow-canvas")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
  });

  it("lets Enter on a palette button add a node to the canvas", async () => {
    const user = userEvent.setup();
    render(<FlowBuilderTool />);
    await user.click(screen.getAllByRole("button", { name: "New Flow" })[0]);

    expect(screen.getByRole("textbox", { name: "Flow name" })).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Search nodes" }), "Search Symbol");
    await user.click(screen.getByRole("button", { name: /Data/ }));
    screen.getByRole("button", { name: "Search Symbol" }).focus();
    await user.keyboard("{Enter}");

    expect(screen.getByText("1 nodes · 0 edges")).toBeInTheDocument();
  });

  it("describes saved flows as local drafts rather than executable automation", () => {
    render(<HowItWorksTab />);

    expect(screen.getByText(/local visual draft editor/i)).toBeInTheDocument();
    expect(screen.getByText(/backend flow execution is not wired/i)).toBeInTheDocument();
    expect(screen.queryByText(/flows run on the FlintTrade Python backend/i)).not.toBeInTheDocument();
  });

  it("labels templates as local drafts and only loads their canvas data", async () => {
    const user = userEvent.setup();
    const onUse = vi.fn();
    render(<TemplatesTab onUse={onUse} />);

    expect(screen.getByText(/local drafts only/i)).toBeInTheDocument();
    expect(screen.queryByText(/timed execution/i)).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Load draft" })[0]);
    expect(onUse).toHaveBeenCalledOnce();
  });
});
