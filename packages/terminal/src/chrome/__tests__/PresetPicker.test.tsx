/**
 * PresetPicker.test.tsx — Renders the preset dialog with all 12 workspace names.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockLayoutState = {
  applyPreset: vi.fn(),
  activeTabId: "tab-1",
  tabs: [{ id: "tab-1", name: "Workspace" }],
  renameTab: vi.fn(),
  removeTab: vi.fn(),
  addTab: vi.fn(),
};

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: typeof mockLayoutState) => unknown) =>
    selector(mockLayoutState),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import PresetPicker from "../PresetPicker";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PresetPicker", () => {
  it("renders the dialog title when open", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Choose a Workspace Template")).toBeInTheDocument();
  });

  it("shows all original 6 preset names", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    const originalPresets = [
      "Scalper Zone",
      "Options Desk",
      "Market Watch",
      "Analysis",
      "Risk Monitor",
      "Investor View",
    ];
    for (const name of originalPresets) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("shows all 6 new preset names", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    const newPresets = [
      "Options Analysis",
      "Sector View",
      "Algo Trading",
      "Portfolio Manager",
      "Market Overview",
      "Quick Scalper",
    ];
    for (const name of newPresets) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
  });

  it("shows all 12 preset descriptions", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    // Spot-check a few descriptions from original and new presets
    expect(
      screen.getByText(/Watchlist \+ Chart \+ Ticker \+ Dashboard/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Option Chain \+ IV Skew \+ Greeks Heatmap/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Quick Trade \+ Order Ladder \+ Depth Heatmap/i)
    ).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(<PresetPicker isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByText("Choose a Workspace Template")).not.toBeInTheDocument();
  });
});
