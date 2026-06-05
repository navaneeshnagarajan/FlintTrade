/**
 * PresetPicker.test.tsx — Renders the preset dialog with every workspace preset.
 *
 * The name/description assertions are driven from WORKSPACE_PRESETS so the test
 * can never silently fall behind the registry again (it previously hard-coded
 * "12 presets" and missed the mission-named Options Scalper + Everything).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";

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

  it("renders a card for every registered preset (no preset is hidden)", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    // Drive directly from the registry so adding a preset can't slip past the UI.
    for (const preset of WORKSPACE_PRESETS) {
      expect(
        screen.getByText(preset.name),
        `preset card "${preset.name}" is missing from the picker`,
      ).toBeInTheDocument();
      expect(
        screen.getByText(preset.description),
        `description for "${preset.name}" is missing from the picker`,
      ).toBeInTheDocument();
    }
  });

  it("surfaces the mission-named Options Scalper four-chart desk", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Options Scalper")).toBeInTheDocument();
    expect(screen.getByText(/Four-chart desk/i)).toBeInTheDocument();
  });

  it("does not render when closed", () => {
    render(<PresetPicker isOpen={false} onClose={vi.fn()} />);
    expect(screen.queryByText("Choose a Workspace Template")).not.toBeInTheDocument();
  });
});
