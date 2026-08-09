import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const LAYOUTS_KEY = "flinttrade:layouts";
const METADATA_KEY = "flinttrade:workspaces";

describe("layoutStore corrupt top-level persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it("quarantines a non-empty FlexLayout document whose layout root is missing", async () => {
    const missingRoot = { global: {}, borders: [] };
    const raw = JSON.stringify({
      state: {
        activeTabId: "ws-healthy",
        tabs: [
          { id: "ws-healthy", name: "Healthy" },
          { id: "ws-missing-root", name: "Missing Root", serializedLayout: missingRoot },
        ],
      },
      version: 0,
    });
    localStorage.setItem(LAYOUTS_KEY, raw);

    const { useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");

    expect(() => useLayoutStore.getState().setActiveTab("ws-missing-root"))
      .toThrow(WorkspaceStorageError);
    expect(useLayoutStore.getState().activeTabId).toBe("ws-healthy");
    expect(useLayoutStore.getState().getTabLayout("ws-missing-root")).toEqual(missingRoot);
    expect(localStorage.getItem(LAYOUTS_KEY)).toBe(raw);
  });

  it("preserves the exact quarantined envelope across mount-style transient state setup", async () => {
    const prettyRaw = `${JSON.stringify({
      state: {
        activeTabId: "ws-corrupt",
        tabs: [
          {
            id: "ws-corrupt",
            name: "Corrupt",
            serializedLayout: { global: {}, borders: [] },
          },
        ],
      },
      version: 0,
    }, null, 2)}\n`;
    localStorage.setItem(LAYOUTS_KEY, prettyRaw);

    const { useLayoutStore } = await import("../layoutStore");
    const state = useLayoutStore.getState();

    state.setWorkspaceApi(null);
    state.setPresetPickerOpen(true);
    state.setWidgetPickerOpen(true);

    expect(localStorage.getItem(LAYOUTS_KEY)).toBe(prettyRaw);
    expect(useLayoutStore.getState().getTabLayout("ws-corrupt")).toEqual({
      global: {},
      borders: [],
    });
  });

  it("quarantines an invalid per-workspace FlexLayout document without switching or rewriting it", async () => {
    const corruptLayout = {
      global: {},
      borders: [],
      layout: null,
    };
    const raw = JSON.stringify({
      state: {
        activeTabId: "ws-healthy",
        tabs: [
          { id: "ws-healthy", name: "Healthy" },
          { id: "ws-corrupt", name: "Corrupt", serializedLayout: corruptLayout },
        ],
      },
      version: 0,
    });
    localStorage.setItem(LAYOUTS_KEY, raw);

    const { useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");

    expect(() => useLayoutStore.getState().setActiveTab("ws-corrupt"))
      .toThrow(WorkspaceStorageError);
    expect(useLayoutStore.getState().activeTabId).toBe("ws-healthy");
    expect(useLayoutStore.getState().getTabLayout("ws-corrupt")).toEqual(corruptLayout);
    expect(localStorage.getItem(LAYOUTS_KEY)).toBe(raw);
  });

  it("fails closed with WorkspaceStorageError and preserves corrupt layouts plus valid metadata byte-for-byte", async () => {
    const corruptLayouts = '{"state":{"tabs":[';
    const validMetadata = '{"ws-healthy":{"id":"ws-healthy","name":"Healthy","createdAt":"2026-08-09T00:00:00.000Z","updatedAt":"2026-08-09T00:00:00.000Z"}}';
    localStorage.setItem(LAYOUTS_KEY, corruptLayouts);
    localStorage.setItem(METADATA_KEY, validMetadata);

    const { useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");
    const state = useLayoutStore.getState() as ReturnType<typeof useLayoutStore.getState> & {
      layoutStorageError?: Error | null;
    };

    expect.soft(state.layoutStorageError).toBeInstanceOf(WorkspaceStorageError);
    expect.soft(state.layoutStorageError?.message).toMatch(/workspace layout storage is corrupted/i);

    state.setPresetPickerOpen(true);
    expect.soft(localStorage.getItem(LAYOUTS_KEY)).toBe(corruptLayouts);

    expect(() => state.addTab("Must not be created", undefined, "ws-ghost"))
      .toThrow(WorkspaceStorageError);
    expect.soft(useLayoutStore.getState().tabs.some((tab) => tab.id === "ws-ghost")).toBe(false);
    expect.soft(localStorage.getItem(LAYOUTS_KEY)).toBe(corruptLayouts);
    expect.soft(localStorage.getItem(METADATA_KEY)).toBe(validMetadata);
  });
});
