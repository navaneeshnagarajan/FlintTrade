/**
 * PresetPicker.test.tsx — Renders the preset dialog with every workspace preset.
 *
 * The name/description assertions are driven from WORKSPACE_PRESETS so the test
 * can never silently fall behind the registry again (it previously hard-coded
 * "12 presets" and missed the mission-named Options Scalper + Everything).
 */

import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockCloneWorkspace, mockNewFromTemplate } = vi.hoisted(() => ({
  mockCloneWorkspace: vi.fn(),
  mockNewFromTemplate: vi.fn(),
}));

const mockLayoutState = {
  applyPreset: vi.fn(),
  activeTabId: "tab-1",
  tabs: [{ id: "tab-1", name: "Workspace" }],
  renameTab: vi.fn(),
  removeTab: vi.fn(),
  addTab: vi.fn(),
  getTabLayout: vi.fn(),
  workspaceApi: { toJSON: vi.fn(() => ({ source: "live-previous-tab" })) },
  workspaceApiTabId: "ws-previous",
};

vi.mock("@/stores/layoutStore", () => ({
  useLayoutStore: (selector: (s: typeof mockLayoutState) => unknown) =>
    selector(mockLayoutState),
}));

vi.mock("../hooks/useWorkspaceLifecycle", () => ({
  WorkspaceStorageError: class WorkspaceStorageError extends Error {},
  reconcileWorkspaceStore: vi.fn(),
  useWorkspaceLifecycle: () => ({
    cloneWorkspace: mockCloneWorkspace,
    newFromTemplate: mockNewFromTemplate,
    renameWorkspace: vi.fn(() => ({ ok: true, id: "tab-1" })),
    deleteWorkspace: vi.fn(() => ({ ok: true, id: "tab-1" })),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import PresetPicker from "../PresetPicker";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PresetPicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCloneWorkspace.mockReturnValue({ ok: true, id: "ws-copy" });
    mockNewFromTemplate.mockReturnValue({ ok: true, id: "ws-template" });
    mockLayoutState.getTabLayout.mockReturnValue({ source: "stored-active-tab" });
  });

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

  it("keeps the dialog open and reports a clone persistence failure", () => {
    mockCloneWorkspace.mockReturnValue({
      ok: false,
      error: "Workspace could not be saved: quota exceeded",
    });
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace actions" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Clone Current" }));

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Workspace could not be saved: quota exceeded",
    );
    expect(screen.getByText("Choose a Workspace Template")).toBeInTheDocument();
  });

  it("clones the stored active layout while the live model is still bound to the previous tab", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace actions" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "Clone Current" }));

    expect(mockCloneWorkspace).toHaveBeenCalledWith(
      "tab-1",
      "Workspace",
      mockLayoutState.addTab,
      mockLayoutState.removeTab,
      { source: "stored-active-tab" },
    );
  });

  it("does not apply a preset to a live model owned by another workspace", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);

    const presetButton = screen.getByRole("button", { name: /^Market Watch / });

    expect(presetButton).toBeDisabled();
    expect(mockLayoutState.applyPreset).not.toHaveBeenCalled();
  });
});
