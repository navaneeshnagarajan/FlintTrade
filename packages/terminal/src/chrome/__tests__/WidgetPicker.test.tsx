/**
 * WidgetPicker.test.tsx — Render and search tests for the widget catalog dialog.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Layout store
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ dockviewApi: null }),
}));

// Widget catalog — provide a representative test catalog
vi.mock("@/layout/widgetFactory", () => ({
  widgetCatalog: [
    { id: "dashboard", name: "Dashboard", icon: "LayoutDashboard", category: "Trading" },
    { id: "scalper", name: "Scalper", icon: "Zap", category: "Trading" },
    { id: "chart", name: "Chart", icon: "CandlestickChart", category: "Analysis" },
    { id: "optionchain", name: "Option Chain", icon: "Grid3x3", category: "Analysis" },
    { id: "watchlist", name: "Watchlist", icon: "Star", category: "Utility" },
    { id: "calculator", name: "Calculator", icon: "Calculator", category: "Utility" },
  ],
}));

// Feature gate — all widgets unlocked
vi.mock("@/hooks/useFeatureGate", () => ({
  useFeatureGate: () => "unlocked" as const,
}));

// shadcn Dialog — render content directly when open
vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div data-testid="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="dialog-content">{children}</div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
}));

// shadcn Input — pass through to native input
vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import WidgetPicker from "../WidgetPicker";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WidgetPicker", () => {
  it("renders the widget catalog when open", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Add Widget")).toBeInTheDocument();
  });

  it("shows category headings in grouped view", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Trading")).toBeInTheDocument();
    expect(screen.getByText("Analysis")).toBeInTheDocument();
    expect(screen.getByText("Utility")).toBeInTheDocument();
  });

  it("displays all widget names from the catalog", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Scalper")).toBeInTheDocument();
    expect(screen.getByText("Chart")).toBeInTheDocument();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });

  it("shows a search input", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByRole("searchbox", { name: /search widgets/i })).toBeInTheDocument();
  });

  it("shows total widget count when search is empty", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("6 widgets")).toBeInTheDocument();
  });

  it("filters widgets by name when searching", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: /search widgets/i });
    fireEvent.change(input, { target: { value: "chart" } });

    // Should show Chart and Option Chain (contains "chain" but not "chart") — only "chart" matches
    expect(screen.getByText("Chart")).toBeInTheDocument();
    // Dashboard should not appear
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
  });

  it("search is case-insensitive", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: /search widgets/i });
    fireEvent.change(input, { target: { value: "WATCH" } });
    // HighlightMatch splits the name across <mark> elements.
    // Query by button aria-label instead of text content.
    expect(
      screen.getByRole("button", { name: /add watchlist widget/i })
    ).toBeInTheDocument();
  });

  it("shows matching count when searching", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: /search widgets/i });
    // "Watchlist" is unique in the mock catalog — gives exactly 1 match.
    fireEvent.change(input, { target: { value: "watchlist" } });
    // The aria-live span shows "N matching" — query with a regex
    expect(screen.getByText(/matching/i)).toBeInTheDocument();
  });

  it("hides category headings when searching", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: /search widgets/i });
    fireEvent.change(input, { target: { value: "chart" } });
    // Category headings should not appear in flat search results
    expect(screen.queryByText("Trading")).not.toBeInTheDocument();
    expect(screen.queryByText("Utility")).not.toBeInTheDocument();
  });

  it("shows an empty state when no widgets match", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: /search widgets/i });
    fireEvent.change(input, { target: { value: "xyznotawidget" } });
    expect(screen.getByText(/no widgets match/i)).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(<WidgetPicker isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByText("Add Widget")).not.toBeInTheDocument();
  });

  it("respects allowedIds prop — hides non-allowed widgets", () => {
    render(
      <WidgetPicker isOpen={true} onClose={vi.fn()} allowedIds={["dashboard", "chart"]} />
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Chart")).toBeInTheDocument();
    expect(screen.queryByText("Scalper")).not.toBeInTheDocument();
    expect(screen.queryByText("Watchlist")).not.toBeInTheDocument();
  });
});
