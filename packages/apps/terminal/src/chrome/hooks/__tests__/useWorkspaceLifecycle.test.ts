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
  let writeInterceptor: ((key: string, value: string) => void) | undefined;
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      writeInterceptor?.(key, value);
      if (writeError) throw writeError;
      store[key] = value;
    },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => {
      store = {};
      writeError = undefined;
      writeInterceptor = undefined;
    },
    failWritesWith: (error: Error) => { writeError = error; },
    interceptWritesWith: (interceptor: (key: string, value: string) => void) => {
      writeInterceptor = interceptor;
    },
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

  it("identifies metadata-less ws_ tabs for durable reload cleanup", () => {
    writeWorkspaceStore({});
    const reloadedTabs = [
      { id: "LAY-default", name: "Workspace" },
      {
        id: "ws-ghost",
        name: "Uncommitted Copy",
        creationTransaction: { id: "txn_ws-ghost", state: "pending" as const },
      },
    ];
    useLayoutStore.setState({ tabs: reloadedTabs, activeTabId: "ws-ghost" });

    const reconciliation = reconcileWorkspaceStore(reloadedTabs);
    for (const tabId of reconciliation.metadataLessTabIds) {
      useLayoutStore.getState().removeTab(tabId);
    }

    expect(reconciliation.metadataLessTabIds).toEqual(["ws-ghost"]);
    expect(useLayoutStore.getState().tabs).toEqual([reloadedTabs[0]]);
    expect(useLayoutStore.getState().activeTabId).toBe("LAY-default");
    const durable = JSON.parse(localStorageMock.getItem("flinttrade:layouts")!) as {
      state: { tabs: Array<{ id: string }> };
    };
    expect(durable.state.tabs.some((tab) => tab.id === "ws-ghost")).toBe(false);
    expect(localStorageMock.getItem("flinttrade:workspaces")).toBe("{}");
  });

  it("never blesses a pending creation ghost with same-name legacy metadata", () => {
    const legacy = {
      id: "ws_legacy",
      name: "Uncommitted Copy",
      createdAt: "2026-04-13T00:00:00Z",
      updatedAt: "2026-04-13T00:00:00Z",
    };
    writeWorkspaceStore({ [legacy.id]: legacy });
    const reloadedTabs = [
      { id: "LAY-default", name: "Workspace" },
      {
        id: "ws_ghost",
        name: "Uncommitted Copy",
        creationTransaction: { id: "txn_ghost", state: "pending" as const },
      },
    ];
    useLayoutStore.setState({ tabs: reloadedTabs, activeTabId: "ws_ghost" });

    const reconciliation = reconcileWorkspaceStore(reloadedTabs);
    for (const tabId of reconciliation.metadataLessTabIds) {
      useLayoutStore.getState().removeTab(tabId);
    }

    expect(reconciliation.metadataLessTabIds).toEqual(["ws_ghost"]);
    expect(readWorkspaceStore()).toEqual({ [legacy.id]: legacy });
    expect(useLayoutStore.getState().tabs.map((tab) => tab.id)).toEqual(["LAY-default"]);
    const durable = JSON.parse(localStorageMock.getItem("flinttrade:layouts")!) as {
      state: { tabs: Array<{ id: string }> };
    };
    expect(durable.state.tabs.some((tab) => tab.id === "ws_ghost")).toBe(false);
  });

  it("preserves an unmarked healthy ws_ layout instead of guessing it is a transaction ghost", () => {
    writeWorkspaceStore({});
    const tabs = [{ id: "ws_healthy", name: "Healthy Legacy Layout" }];

    const reconciliation = reconcileWorkspaceStore(tabs);

    expect(reconciliation.metadataLessTabIds).toEqual([]);
  });

  it("rebuilds canonical metadata for a committed creation identity", () => {
    writeWorkspaceStore({});
    const tabs = [{
      id: "ws_committed",
      name: "Committed Desk",
      creationTransaction: { id: "txn_ws_committed", state: "committed" as const },
    }];

    const reconciliation = reconcileWorkspaceStore(tabs);

    expect(reconciliation.metadataLessTabIds).toEqual([]);
    expect(readWorkspaceStore()["ws_committed"]).toMatchObject({
      id: "ws_committed",
      name: "Committed Desk",
      creationTransactionId: "txn_ws_committed",
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

    const canonicalId = addTab.mock.calls[0][2];
    expect(addTab).toHaveBeenCalledWith(
      "My Layout (Copy)",
      undefined,
      canonicalId,
      { id: `txn_${canonicalId}`, state: "pending" },
    );
  });

  it("persists a new metadata entry with matching canonical ID (unification)", () => {
    // Use REAL addTab (not mock) so unification of ws_ id between meta and layout tab can be asserted
    const { result } = renderHook(() => useWorkspaceLifecycle());
    const realAddTab = useLayoutStore.getState().addTab;
    const realRemoveTab = useLayoutStore.getState().removeTab;
    const realCommitTabCreation = useLayoutStore.getState().commitTabCreation;

    act(() => {
      result.current.cloneWorkspace(
        "tab-1",
        "Scalper Zone",
        realAddTab,
        realRemoveTab,
        undefined,
        realCommitTabCreation,
      );
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
    expect(matchingTab?.creationTransaction).toEqual({
      id: meta.creationTransactionId,
      state: "committed",
    });
    expect(meta.creationTransactionId).toMatch(/^txn_ws_/);
  });

  it("clones layout structure while reminting every FlexLayout node id", () => {
    const { result } = renderHook(() => useWorkspaceLifecycle());
    const realAddTab = useLayoutStore.getState().addTab;
    const realRemoveTab = useLayoutStore.getState().removeTab;
    const realCommitTabCreation = useLayoutStore.getState().commitTabCreation;
    const fakeLayout = {
      global: {},
      borders: [],
      layout: {
        type: "row",
        id: "source-row",
        children: [{
          type: "tabset",
          id: "source-tabset",
          children: [{
            type: "tab",
            id: "source-chart",
            component: "chart",
            name: "Chart",
            config: { symbol: "NIFTY", grid: false },
          }],
        }],
      },
    };

    act(() => {
      result.current.cloneWorkspace(
        "tab-1",
        "With Layout",
        realAddTab,
        realRemoveTab,
        fakeLayout,
        realCommitTabCreation,
      );
    });

    const entries = Object.values(readWorkspaceStore());
    const meta = entries.find((entry) => entry.name === "With Layout (Copy)");
    expect(meta).toBeDefined();
    const layoutTabs = useLayoutStore.getState().tabs;
    const clonedLayout = layoutTabs.find((layoutTab) => layoutTab.id === meta?.id)?.serializedLayout;
    expect(clonedLayout).toBeDefined();
    expect(clonedLayout).not.toBe(fakeLayout);

    const collectIds = (value: unknown, ids = new Set<string>()): Set<string> => {
      if (Array.isArray(value)) {
        for (const item of value) collectIds(item, ids);
      } else if (value !== null && typeof value === "object") {
        const record = value as Record<string, unknown>;
        if (typeof record.id === "string") ids.add(record.id);
        for (const item of Object.values(record)) collectIds(item, ids);
      }
      return ids;
    };
    const sourceIds = collectIds(fakeLayout);
    const cloneIds = collectIds(clonedLayout);
    expect([...cloneIds].filter((id) => sourceIds.has(id))).toEqual([]);
    expect(clonedLayout).toMatchObject({
      layout: {
        type: "row",
        children: [{
          type: "tabset",
          children: [{
            type: "tab",
            component: "chart",
            name: "Chart",
            config: { symbol: "NIFTY", grid: false },
          }],
        }],
      },
    });
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

  it("reports an explicit durable failure when metadata and rollback persistence both fail", () => {
    const { result } = renderHook(() => useWorkspaceLifecycle());
    const realAddTab = useLayoutStore.getState().addTab;
    const realRemoveTab = useLayoutStore.getState().removeTab;
    let layoutWrites = 0;
    localStorageMock.interceptWritesWith((key) => {
      if (key === "flinttrade:workspaces") {
        throw new Error("metadata unavailable");
      }
      if (key === "flinttrade:layouts" && ++layoutWrites === 2) {
        throw new Error("rollback unavailable");
      }
    });

    let outcome: ReturnType<typeof result.current.cloneWorkspace> | undefined;
    act(() => {
      outcome = result.current.cloneWorkspace(
        "tab-1",
        "Layout",
        realAddTab,
        realRemoveTab,
      );
    });

    expect(outcome).toMatchObject({ ok: false });
    expect(outcome && !outcome.ok ? outcome.error : "").toContain("metadata unavailable");
    expect(outcome && !outcome.ok ? outcome.error : "").toContain(
      "durable rollback failed: rollback unavailable",
    );
    const persisted = JSON.parse(localStorageMock.getItem("flinttrade:layouts")!) as {
      state: {
        tabs: Array<{
          id: string;
          name: string;
          creationTransaction?: { id: string; state: string };
        }>;
      };
    };
    const persistedGhost = persisted.state.tabs.find((tab) => tab.name === "Layout (Copy)");
    expect(persistedGhost).toMatchObject({
      creationTransaction: {
        id: expect.stringMatching(/^txn_/),
        state: "pending",
      },
    });
    expect(useLayoutStore.getState().tabs.some((tab) => tab.name === "Layout (Copy)"))
      .toBe(false);
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
    expect(addTab).toHaveBeenCalledWith(
      "Scalper Zone",
      preset.build(),
      canonicalId,
      { id: `txn_${canonicalId}`, state: "pending" },
    );
    expect(readWorkspaceStore()[canonicalId]).toMatchObject({
      id: canonicalId,
      name: "Scalper Zone",
      sourcePresetId: "scalper-zone",
      creationTransactionId: `txn_${canonicalId}`,
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
