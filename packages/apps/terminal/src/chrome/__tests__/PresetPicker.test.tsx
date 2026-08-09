/**
 * PresetPicker.test.tsx — Renders the preset dialog with every workspace preset.
 *
 * The name/description assertions are driven from WORKSPACE_PRESETS so the test
 * can never silently fall behind the registry again (it previously hard-coded
 * "12 presets" and missed the mission-named Options Scalper + Everything).
 */

import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const {
  mockCloneWorkspace,
  mockNewFromTemplate,
  mockRenameWorkspace,
  mockReconcileWorkspaceStore,
} = vi.hoisted(() => ({
  mockCloneWorkspace: vi.fn(),
  mockNewFromTemplate: vi.fn(),
  mockRenameWorkspace: vi.fn(),
  mockReconcileWorkspaceStore: vi.fn(),
}));

const mockLayoutState = {
  applyPreset: vi.fn(),
  activeTabId: "tab-1",
  layoutStorageError: null as Error | null,
  tabs: [{ id: "tab-1", name: "Workspace" }],
  renameTab: vi.fn(),
  removeTab: vi.fn(),
  addTab: vi.fn(),
  commitTabCreation: vi.fn(),
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
  reconcileWorkspaceStore: mockReconcileWorkspaceStore,
  useWorkspaceLifecycle: () => ({
    cloneWorkspace: mockCloneWorkspace,
    newFromTemplate: mockNewFromTemplate,
    renameWorkspace: mockRenameWorkspace,
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
    mockLayoutState.activeTabId = "tab-1";
    mockLayoutState.layoutStorageError = null;
    mockLayoutState.tabs = [{ id: "tab-1", name: "Workspace" }];
    mockLayoutState.workspaceApiTabId = "ws-previous";
    mockCloneWorkspace.mockReturnValue({ ok: true, id: "ws-copy" });
    mockNewFromTemplate.mockReturnValue({ ok: true, id: "ws-template" });
    mockRenameWorkspace.mockReturnValue({ ok: true, id: "tab-2" });
    mockReconcileWorkspaceStore.mockReturnValue({ metadataLessTabIds: [] });
    mockLayoutState.getTabLayout.mockReturnValue({ source: "stored-active-tab" });
  });

  it("renders the dialog title when open", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);
    expect(screen.getByText("Choose a Workspace Template")).toBeInTheDocument();
  });

  it("surfaces corrupt layout storage and skips metadata reconciliation", () => {
    mockLayoutState.layoutStorageError = new Error(
      "Workspace layout storage is corrupted and could not be read.",
    );

    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Workspace layout storage is corrupted and could not be read.",
    );
    expect(mockReconcileWorkspaceStore).not.toHaveBeenCalled();
  });

  it("removes metadata-less transaction ghosts during reload reconciliation", async () => {
    mockLayoutState.tabs = [
      { id: "tab-1", name: "Workspace" },
      { id: "ws_ghost", name: "Uncommitted Copy" },
    ];
    mockReconcileWorkspaceStore.mockReturnValue({ metadataLessTabIds: ["ws_ghost"] });

    render(<PresetPicker isOpen={false} onClose={vi.fn()} />);

    await waitFor(() => expect(mockLayoutState.removeTab).toHaveBeenCalledWith("ws_ghost"));
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

  it("refreshes an open Rename dialog when the active workspace changes", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<PresetPicker isOpen={true} onClose={onClose} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace actions" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: 'Rename "Workspace"' }));
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Workspace");

    mockLayoutState.activeTabId = "tab-2";
    mockLayoutState.tabs = [
      { id: "tab-1", name: "Workspace" },
      { id: "tab-2", name: "Trading Desk (Copy)" },
    ];
    rerender(<PresetPicker isOpen={true} onClose={onClose} />);

    const input = screen.getByRole("textbox", { name: "Name" });
    await waitFor(() => expect(input).toHaveValue("Trading Desk (Copy)"));
    fireEvent.change(input, { target: { value: "Intended Desk" } });
    fireEvent.submit(input.closest("form")!);

    expect(mockRenameWorkspace).toHaveBeenCalledWith(
      "tab-2",
      "Trading Desk (Copy)",
      "Intended Desk",
      mockLayoutState.renameTab,
    );
  });

  it("drops a cancelled rename draft when switching to a same-name workspace", async () => {
    const onClose = vi.fn();
    const { rerender } = render(<PresetPicker isOpen={true} onClose={onClose} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace actions" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: 'Rename "Workspace"' }));
    const firstInput = screen.getByRole("textbox", { name: "Name" });
    fireEvent.change(firstInput, { target: { value: "Unsaved draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    mockLayoutState.activeTabId = "tab-2";
    mockLayoutState.tabs = [
      { id: "tab-1", name: "Workspace" },
      { id: "tab-2", name: "Workspace" },
    ];
    rerender(<PresetPicker isOpen={true} onClose={onClose} />);

    fireEvent.pointerDown(screen.getByRole("button", { name: "Workspace actions" }), {
      button: 0,
      ctrlKey: false,
    });
    fireEvent.click(screen.getByRole("menuitem", { name: 'Rename "Workspace"' }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue("Workspace")
    );
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
      mockLayoutState.commitTabCreation,
    );
  });

  it("does not apply a preset to a live model owned by another workspace", () => {
    render(<PresetPicker isOpen={true} onClose={vi.fn()} />);

    const presetButton = screen.getByRole("button", { name: /^Market Watch / });

    expect(presetButton).toBeDisabled();
    expect(mockLayoutState.applyPreset).not.toHaveBeenCalled();
  });

  it("keeps the picker open and surfaces a per-tab quarantine error", () => {
    const onClose = vi.fn();
    mockLayoutState.workspaceApiTabId = "tab-1";
    mockLayoutState.applyPreset.mockImplementationOnce(() => {
      throw new Error('Workspace "Corrupt" layout is corrupted and has been quarantined.');
    });

    render(<PresetPicker isOpen={true} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: /^Market Watch / }));

    expect(screen.getByRole("alert")).toHaveTextContent(/has been quarantined/i);
    expect(onClose).not.toHaveBeenCalled();
  });
});
