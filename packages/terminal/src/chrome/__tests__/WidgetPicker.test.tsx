/**
 * WidgetPicker.test.tsx — Render tests for the widget catalog dialog.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Layout store
vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: Record<string, unknown>) => unknown) =>
    selector({ dockviewApi: null }),
}));

// Widget catalog — provide a small test catalog
vi.mock("@/layout/widgetFactory", () => ({
  widgetCatalog: [
    { id: "dashboard", name: "Dashboard", icon: "LayoutDashboard", category: "Trading" },
    { id: "scalper", name: "Scalper", icon: "Zap", category: "Trading" },
    { id: "chart", name: "Chart", icon: "CandlestickChart", category: "Analysis" },
    { id: "watchlist", name: "Watchlist", icon: "Star", category: "Utility" },
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

  it("shows category headings", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Trading")).toBeInTheDocument();
    expect(screen.getByText("Analysis")).toBeInTheDocument();
    expect(screen.getByText("Utility")).toBeInTheDocument();
  });

  it("displays widget names from the catalog", () => {
    render(<WidgetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Scalper")).toBeInTheDocument();
    expect(screen.getByText("Chart")).toBeInTheDocument();
    expect(screen.getByText("Watchlist")).toBeInTheDocument();
  });
});
