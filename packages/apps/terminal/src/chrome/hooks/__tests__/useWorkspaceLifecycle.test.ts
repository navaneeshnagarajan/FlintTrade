/**
 * useWorkspaceLifecycle.test.ts
 *
 * Tests for the workspace lifecycle hook and its localStorage helpers.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  readWorkspaceStore,
  reconcileWorkspaceStore,
  writeWorkspaceStore,
  upsertWorkspaceMeta,
  deleteWorkspaceMeta,
  getWorkspaceMeta,
  WorkspaceStorageError,
  useWorkspaceLifecycle,
} from "../useWorkspaceLifecycle";
import type { WorkspaceMeta } from "../useWorkspaceLifecycle";
import { useLayoutStore } from "@/stores/layoutStore";

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  let writeError: Error | undefined;
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      if (writeError) throw writeError;
      store[key] = value;
    },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; writeError = undefined; },
    failWritesWith: (error: Error) => { writeError = error; },
  };
})();

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: localStorageMock,
    writable: true,
  });
  localStorageMock.clear();
  // Reset layout store for id-unification and clone tests (RED-GREEN for orphan defect)
  useLayoutStore.setState(useLayoutStore.getInitialState());
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// readWorkspaceStore / writeWorkspaceStore
// ---------------------------------------------------------------------------

describe("readWorkspaceStore", () => {
  it("returns empty object when localStorage is empty", () => {
    expect(readWorkspaceStore()).toEqual({});
  });

  it("reports malformed JSON instead of silently replacing it", () => {
    localStorageMock.setItem("flinttrade:workspaces", "not-json");
    expect(() => readWorkspaceStore()).toThrow(WorkspaceStorageError);
  });

  it("reports an invalid stored shape instead of silently replacing it", () => {
    localStorageMock.setItem("flinttrade:workspaces", JSON.stringify([]));
    expect(() => readWorkspaceStore()).toThrow(WorkspaceStorageError);
  });

  it("returns the stored workspace map", () => {
    const data = {
      tab1: { id: "tab1", name: "My Layout", createdAt: "2026-04-13T10:00:00Z", updatedAt: "2026-04-13T10:00:00Z" },
    };
    writeWorkspaceStore(data);
    expect(readWorkspaceStore()).toEqual(data);
  });
});

describe("reconcileWorkspaceStore", () => {
  it("migrates legacy metadata to the matching canonical layout ID", () => {
    writeWorkspaceStore({
      ws_legacy: {
        id: "ws_legacy",
        name: "Trading Desk",
        createdAt: "2026-04-13T00:00:00Z",
        updatedAt: "2026-04-13T00:00:00Z",
        sourcePresetId: "trading-desk",
      },
      ws_orphan: {
        id: "ws_orphan",
        name: "Deleted Workspace",
        createdAt: "2026-04-13T00:00:00Z",
        updatedAt: "2026-04-13T00:00:00Z",
      },
    });

    reconcileWorkspaceStore([{ id: "LAY-canonical", name: "Trading Desk" }]);

    expect(readWorkspaceStore()).toEqual({
      "LAY-canonical": expect.objectContaining({
        id: "LAY-canonical",
        name: "Trading Desk",
        sourcePresetId: "trading-desk",
      }),
    });
  });

  it("preserves ambiguous legacy metadata instead of guessing or deleting it", () => {
    const first = {
      id: "ws_legacy_one",
      name: "Trading Desk",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
    };
    const second = { ...first, id: "ws_legacy_two" };
    writeWorkspaceStore({
      [first.id]: first,
      [second.id]: second,
    });

    reconcileWorkspaceStore([
      { id: "LAY-one", name: "Trading Desk" },
      { id: "LAY-two", name: "Trading Desk" },
    ]);

    expect(readWorkspaceStore()).toEqual({
      [first.id]: first,
      [second.id]: second,
    });
  });
});

describe("writeWorkspaceStore", () => {
  it("persists a workspace map to localStorage", () => {
    const meta: WorkspaceMeta = {
      id: "ws1",
      name: "Scalper",
      createdAt: "2026-04-13T10:00:00Z",
      updatedAt: "2026-04-13T10:00:00Z",
    };
    writeWorkspaceStore({ ws1: meta });
    const raw = localStorageMock.getItem("flinttrade:workspaces");
    expect(JSON.parse(raw!)).toEqual({ ws1: meta });
  });
});

// ---------------------------------------------------------------------------
// upsertWorkspaceMeta
// ---------------------------------------------------------------------------

describe("upsertWorkspaceMeta", () => {
  it("creates a new entry", () => {
    upsertWorkspaceMeta({
      id: "abc",
      name: "Trade Desk",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
    });
    const store = readWorkspaceStore();
    expect(store["abc"]).toBeDefined();
    expect(store["abc"].name).toBe("Trade Desk");
  });

  it("updates updatedAt when upserting an existing entry", () => {
    const original: WorkspaceMeta = {
      id: "abc",
      name: "Trade Desk",
      createdAt: "2026-04-01T00:00:00Z",
      updatedAt: "2026-04-01T00:00:00Z",
    };
    writeWorkspaceStore({ abc: original });

    const before = new Date().toISOString();
    upsertWorkspaceMeta({ ...original, name: "Trade Desk v2" });
    const after = new Date().toISOString();

    const updated = readWorkspaceStore()["abc"];
    expect(updated.name).toBe("Trade Desk v2");
    expect(updated.updatedAt >= before).toBe(true);
    expect(updated.updatedAt <= after).toBe(true);
  });

  it("preserves sourcePresetId", () => {
    upsertWorkspaceMeta({
      id: "x",
      name: "Options",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
      sourcePresetId: "options-desk",
    });
    expect(readWorkspaceStore()["x"].sourcePresetId).toBe("options-desk");
  });
});

// ---------------------------------------------------------------------------
// deleteWorkspaceMeta
// ---------------------------------------------------------------------------

describe("deleteWorkspaceMeta", () => {
  it("removes the entry from the store", () => {
    const meta: WorkspaceMeta = {
      id: "del1",
      name: "Temp",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
    };
    writeWorkspaceStore({ del1: meta });
    deleteWorkspaceMeta("del1");
    expect(readWorkspaceStore()["del1"]).toBeUndefined();
  });

  it("is a no-op for non-existent id", () => {
    expect(() => deleteWorkspaceMeta("ghost")).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getWorkspaceMeta
// ---------------------------------------------------------------------------

describe("getWorkspaceMeta", () => {
  it("returns undefined for missing id", () => {
    expect(getWorkspaceMeta("missing")).toBeUndefined();
  });

  it("returns the stored meta for a known id", () => {
    const meta: WorkspaceMeta = {
      id: "get1",
      name: "Analysis",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
    };
    writeWorkspaceStore({ get1: meta });
    expect(getWorkspaceMeta("get1")?.name).toBe("Analysis");
  });
});

// ---------------------------------------------------------------------------
// useWorkspaceLifecycle — cloneWorkspace
// ---------------------------------------------------------------------------

describe("useWorkspaceLifecycle.cloneWorkspace", () => {
  it("calls addTab with the cloned name", () => {
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.cloneWorkspace("tab-1", "My Layout", addTab, removeTab);
    });

    expect(addTab).toHaveBeenCalledWith("My Layout (Copy)", undefined, expect.stringMatching(/^ws_/));
  });

  it("persists a new metadata entry with matching canonical ID (unification)", () => {
    // Use REAL addTab (not mock) so unification of ws_ id between meta and layout tab can be asserted
    const { result } = renderHook(() => useWorkspaceLifecycle());
    const realAddTab = useLayoutStore.getState().addTab;
    const realRemoveTab = useLayoutStore.getState().removeTab;

    act(() => {
      result.current.cloneWorkspace("tab-1", "Scalper Zone", realAddTab, realRemoveTab);
    });

    const store = readWorkspaceStore();
    const entries = Object.values(store);
    expect(entries.length).toBe(1);
    expect(entries[0].name).toBe("Scalper Zone (Copy)");

    const meta = entries[0];
    const layoutTabs = useLayoutStore.getState().tabs;
    const matchingTab = layoutTabs.find((tab) => tab.id === meta.id);
    expect(matchingTab).toBeDefined(); // unified canonical ID
    expect(matchingTab?.name).toBe("Scalper Zone (Copy)");
    expect(matchingTab?.serializedLayout).toBeUndefined(); // no layout passed in this test
  });

  it("clones serializedLayout when provided (unified id)", () => {
    const { result } = renderHook(() => useWorkspaceLifecycle());
    const realAddTab = useLayoutStore.getState().addTab;
    const realRemoveTab = useLayoutStore.getState().removeTab;
    const fakeLayout = { root: { type: "row", children: [{ id: "chart" }] } };

    act(() => {
      result.current.cloneWorkspace("tab-1", "With Layout", realAddTab, realRemoveTab, fakeLayout);
    });

    const entries = Object.values(readWorkspaceStore());
    const meta = entries.find((entry) => entry.name === "With Layout (Copy)");
    expect(meta).toBeDefined();
    const layoutTabs = useLayoutStore.getState().tabs;
    const tab = layoutTabs.find((layoutTab) => layoutTab.id === meta?.id);
    expect(tab?.serializedLayout).toEqual(fakeLayout);
  });
  it("preserves sourcePresetId from the source workspace", () => {
    upsertWorkspaceMeta({
      id: "tab-src",
      name: "Options Desk",
      createdAt: "2026-04-01T00:00:00Z",
      updatedAt: "2026-04-01T00:00:00Z",
      sourcePresetId: "options-desk",
    });

    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.cloneWorkspace("tab-src", "Options Desk", addTab, removeTab);
    });

    const entries = Object.values(readWorkspaceStore()).filter(
      (e) => e.name === "Options Desk (Copy)"
    );
    expect(entries[0].sourcePresetId).toBe("options-desk");
  });

  it("rolls back the layout tab when metadata persistence fails", () => {
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());
    localStorageMock.failWritesWith(new Error("quota exceeded"));

    let outcome: ReturnType<typeof result.current.cloneWorkspace> | undefined;
    act(() => {
      outcome = result.current.cloneWorkspace("tab-1", "Layout", addTab, removeTab);
    });

    expect(outcome).toEqual({ ok: false, error: "Workspace could not be saved: quota exceeded" });
    expect(addTab).toHaveBeenCalledOnce();
    const createdId = addTab.mock.calls[0][2];
    expect(removeTab).toHaveBeenCalledWith(createdId);
    expect(localStorageMock.getItem("flinttrade:workspaces")).toBeNull();
  });

  it("does not create a layout tab when workspace metadata is corrupt", () => {
    localStorageMock.setItem("flinttrade:workspaces", "not-json");
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    let outcome: ReturnType<typeof result.current.cloneWorkspace> | undefined;
    act(() => {
      outcome = result.current.cloneWorkspace("tab-1", "Layout", addTab, removeTab);
    });

    expect(outcome).toEqual({
      ok: false,
      error: "Workspace metadata is corrupted and could not be read.",
    });
    expect(addTab).not.toHaveBeenCalled();
    expect(removeTab).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// useWorkspaceLifecycle — newFromTemplate
// ---------------------------------------------------------------------------

describe("useWorkspaceLifecycle.newFromTemplate", () => {
  const preset = {
    id: "scalper-zone",
    name: "Scalper Zone",
    description: "Test preset",
    icon: "Zap",
    build: vi.fn(() => ({ layout: { type: "row" as const, children: [] } })),
  };

  it("creates the preset layout and metadata with one canonical id", () => {
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.newFromTemplate(preset, addTab, removeTab);
    });

    const canonicalId = addTab.mock.calls[0][2];
    expect(addTab).toHaveBeenCalledWith("Scalper Zone", preset.build(), canonicalId);
    expect(readWorkspaceStore()[canonicalId]).toMatchObject({
      id: canonicalId,
      name: "Scalper Zone",
      sourcePresetId: "scalper-zone",
    });
  });

  it("persists metadata with sourcePresetId", () => {
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.newFromTemplate(preset, addTab, removeTab);
    });

    const entries = Object.values(readWorkspaceStore());
    expect(entries.length).toBe(1);
    expect(entries[0].sourcePresetId).toBe("scalper-zone");
    expect(entries[0].name).toBe("Scalper Zone");
  });

  it("rolls back the template tab when metadata persistence fails", () => {
    const addTab = vi.fn();
    const removeTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());
    localStorageMock.failWritesWith(new Error("quota exceeded"));

    let outcome: ReturnType<typeof result.current.newFromTemplate> | undefined;
    act(() => {
      outcome = result.current.newFromTemplate(preset, addTab, removeTab);
    });

    expect(outcome).toEqual({ ok: false, error: "Workspace could not be saved: quota exceeded" });
    const createdId = addTab.mock.calls[0][2];
    expect(removeTab).toHaveBeenCalledWith(createdId);
    expect(localStorageMock.getItem("flinttrade:workspaces")).toBeNull();
  });
});

describe("useWorkspaceLifecycle rename and delete", () => {
  const existing: WorkspaceMeta = {
    id: "ws-existing",
    name: "Original",
    createdAt: "2026-04-13T00:00:00Z",
    updatedAt: "2026-04-13T00:00:00Z",
    sourcePresetId: "trading-desk",
  };

  it("rolls back a rename when metadata persistence fails", () => {
    writeWorkspaceStore({ [existing.id]: existing });
    localStorageMock.failWritesWith(new Error("quota exceeded"));
    const renameTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    let outcome: ReturnType<typeof result.current.renameWorkspace> | undefined;
    act(() => {
      outcome = result.current.renameWorkspace(
        existing.id,
        existing.name,
        "Renamed",
        renameTab,
      );
    });

    expect(outcome).toEqual({ ok: false, error: "Workspace could not be saved: quota exceeded" });
    expect(renameTab.mock.calls).toEqual([
      [existing.id, "Renamed"],
      [existing.id, existing.name],
    ]);
  });

  it("restores a removed tab when metadata deletion fails", () => {
    writeWorkspaceStore({ [existing.id]: existing });
    localStorageMock.failWritesWith(new Error("quota exceeded"));
    const removeTab = vi.fn();
    const addTab = vi.fn();
    const layout = { layout: { type: "row" } };
    const { result } = renderHook(() => useWorkspaceLifecycle());

    let outcome: ReturnType<typeof result.current.deleteWorkspace> | undefined;
    act(() => {
      outcome = result.current.deleteWorkspace(
        existing.id,
        existing.name,
        layout,
        removeTab,
        addTab,
      );
    });

    expect(outcome).toEqual({ ok: false, error: "Workspace could not be saved: quota exceeded" });
    expect(removeTab).toHaveBeenCalledWith(existing.id);
    expect(addTab).toHaveBeenCalledWith(existing.name, layout, existing.id);
  });
});
