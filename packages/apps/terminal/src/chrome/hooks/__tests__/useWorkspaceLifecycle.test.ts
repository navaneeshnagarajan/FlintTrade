/**
 * useWorkspaceLifecycle.test.ts
 *
 * Tests for the workspace lifecycle hook and its localStorage helpers.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  readWorkspaceStore,
  writeWorkspaceStore,
  upsertWorkspaceMeta,
  deleteWorkspaceMeta,
  getWorkspaceMeta,
  useWorkspaceLifecycle,
} from "../useWorkspaceLifecycle";
import type { WorkspaceMeta } from "../useWorkspaceLifecycle";

// ---------------------------------------------------------------------------
// localStorage mock
// ---------------------------------------------------------------------------

const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => { store[key] = value; },
    removeItem: (key: string) => { delete store[key]; },
    clear: () => { store = {}; },
  };
})();

beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: localStorageMock,
    writable: true,
  });
  localStorageMock.clear();
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

  it("returns empty object for malformed JSON", () => {
    localStorageMock.setItem("flinttrade:workspaces", "not-json");
    expect(readWorkspaceStore()).toEqual({});
  });

  it("returns empty object when stored value is an array", () => {
    localStorageMock.setItem("flinttrade:workspaces", JSON.stringify([]));
    expect(readWorkspaceStore()).toEqual({});
  });

  it("returns the stored workspace map", () => {
    const data = {
      tab1: { id: "tab1", name: "My Layout", createdAt: "2026-04-13T10:00:00Z", updatedAt: "2026-04-13T10:00:00Z" },
    };
    writeWorkspaceStore(data);
    expect(readWorkspaceStore()).toEqual(data);
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
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.cloneWorkspace("tab-1", "My Layout", addTab);
    });

    expect(addTab).toHaveBeenCalledWith("My Layout (Copy)");
  });

  it("persists a new metadata entry", () => {
    const addTab = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.cloneWorkspace("tab-1", "Scalper Zone", addTab);
    });

    const store = readWorkspaceStore();
    const entries = Object.values(store);
    expect(entries.length).toBe(1);
    expect(entries[0].name).toBe("Scalper Zone (Copy)");
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
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.cloneWorkspace("tab-src", "Options Desk", addTab);
    });

    const entries = Object.values(readWorkspaceStore()).filter(
      (e) => e.name === "Options Desk (Copy)"
    );
    expect(entries[0].sourcePresetId).toBe("options-desk");
  });

  it("works without addTab argument", () => {
    const { result } = renderHook(() => useWorkspaceLifecycle());
    expect(() => {
      act(() => {
        result.current.cloneWorkspace("tab-1", "Layout");
      });
    }).not.toThrow();
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

  it("calls addTab with the preset name", () => {
    const addTab = vi.fn();
    const applyPreset = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.newFromTemplate(preset, addTab, applyPreset);
    });

    expect(addTab).toHaveBeenCalledWith("Scalper Zone");
  });

  it("calls applyPreset with the preset id", () => {
    const addTab = vi.fn();
    const applyPreset = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.newFromTemplate(preset, addTab, applyPreset);
    });

    expect(applyPreset).toHaveBeenCalledWith("scalper-zone");
  });

  it("persists metadata with sourcePresetId", () => {
    const addTab = vi.fn();
    const applyPreset = vi.fn();
    const { result } = renderHook(() => useWorkspaceLifecycle());

    act(() => {
      result.current.newFromTemplate(preset, addTab, applyPreset);
    });

    const entries = Object.values(readWorkspaceStore());
    expect(entries.length).toBe(1);
    expect(entries[0].sourcePresetId).toBe("scalper-zone");
    expect(entries[0].name).toBe("Scalper Zone");
  });
});
