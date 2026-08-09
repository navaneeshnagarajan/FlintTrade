import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const LAYOUTS_KEY = "flinttrade:layouts";
const METADATA_KEY = "flinttrade:workspaces";

describe("layoutStore corrupt top-level persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
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

  it.each([
    { layout: {} },
    { layout: "x" },
    { layout: { type: "row", children: null } },
  ])("quarantines a parser-permissive malformed FlexLayout root: %j", async (malformedLayout) => {
    const raw = `${JSON.stringify({
      state: {
        activeTabId: "ws-malformed",
        tabs: [{ id: "ws-malformed", name: "Malformed", serializedLayout: malformedLayout }],
      },
      version: 0,
    }, null, 2)}\n`;
    localStorage.setItem(LAYOUTS_KEY, raw);

    const { classifySerializedLayout, useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");

    expect(classifySerializedLayout(malformedLayout as Record<string, unknown>)).toBe("corrupt");
    expect(() => useLayoutStore.getState().setActiveTab("ws-malformed"))
      .toThrow(WorkspaceStorageError);
    useLayoutStore.getState().setWorkspaceApi(null);
    useLayoutStore.getState().setPresetPickerOpen(true);
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

  it("keeps healthy sibling workspaces writable while corrupt evidence is quarantined per tab", async () => {
    const corruptLayout = { global: {}, borders: [] };
    const healthyLayout = {
      global: {},
      borders: [],
      layout: { type: "row", children: [] },
    };
    const originalRaw = `${JSON.stringify({
      state: {
        activeTabId: "ws-healthy",
        tabs: [
          { id: "ws-healthy", name: "Healthy" },
          { id: "ws-corrupt", name: "Corrupt", serializedLayout: corruptLayout },
          {
            id: "ws-ghost",
            name: "Pending ghost",
            creationTransaction: { id: "txn-ghost", state: "pending" },
          },
        ],
      },
      version: 0,
    }, null, 2)}\n`;
    localStorage.setItem(LAYOUTS_KEY, originalRaw);

    const { useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");
    const state = useLayoutStore.getState();

    expect(state.layoutStorageQuarantined).toBe(true);
    expect(() => state.renameTab("ws-healthy", "Healthy renamed")).not.toThrow();
    expect(() => state.saveTabLayout("ws-healthy", healthyLayout)).not.toThrow();
    expect(() => state.removeTab("ws-ghost")).not.toThrow();
    expect(() => state.addTab("Fresh", undefined, "ws-fresh")).not.toThrow();

    let durable = JSON.parse(localStorage.getItem(LAYOUTS_KEY)!) as {
      state: { tabs: Array<{ id: string; name: string; serializedLayout?: unknown }> };
    };
    expect(durable.state.tabs.find((tab) => tab.id === "ws-healthy")).toMatchObject({
      name: "Healthy renamed",
      serializedLayout: healthyLayout,
    });
    expect(durable.state.tabs.find((tab) => tab.id === "ws-corrupt")?.serializedLayout)
      .toEqual(corruptLayout);
    expect(durable.state.tabs.some((tab) => tab.id === "ws-ghost")).toBe(false);
    expect(durable.state.tabs.some((tab) => tab.id === "ws-fresh")).toBe(true);
    const evidenceKeys = Array.from({ length: localStorage.length }, (_, index) =>
      localStorage.key(index)
    ).filter((key): key is string => key?.startsWith(`${LAYOUTS_KEY}:quarantine:`) === true);
    expect(evidenceKeys).toHaveLength(1);
    expect(localStorage.getItem(evidenceKeys[0])).toBe(originalRaw);

    expect(() => useLayoutStore.getState().renameTab("ws-corrupt", "Must stay frozen"))
      .toThrow(WorkspaceStorageError);
    expect(() => useLayoutStore.getState().saveTabLayout("ws-corrupt", healthyLayout))
      .toThrow(WorkspaceStorageError);
    expect(() => useLayoutStore.getState().saveTabLayout("ws-healthy", corruptLayout))
      .toThrow(WorkspaceStorageError);
    expect(useLayoutStore.getState().getTabLayout("ws-corrupt")).toEqual(corruptLayout);

    expect(() => useLayoutStore.getState().removeTab("ws-corrupt")).not.toThrow();
    expect(useLayoutStore.getState().layoutStorageQuarantined).toBe(false);
    durable = JSON.parse(localStorage.getItem(LAYOUTS_KEY)!) as typeof durable;
    expect(durable.state.tabs.some((tab) => tab.id === "ws-corrupt")).toBe(false);
  });

  it("fails before mutation when exact quarantine evidence cannot be saved", async () => {
    const raw = JSON.stringify({
      state: {
        activeTabId: "ws-healthy",
        tabs: [
          { id: "ws-healthy", name: "Healthy" },
          {
            id: "ws-corrupt",
            name: "Corrupt",
            serializedLayout: { global: {}, borders: [] },
          },
        ],
      },
      version: 0,
    });
    localStorage.setItem(LAYOUTS_KEY, raw);
    const { useLayoutStore, WorkspaceStorageError } = await import("../layoutStore");
    const originalSetItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function setItem(
      this: Storage,
      key: string,
      value: string,
    ) {
      if (key.startsWith(`${LAYOUTS_KEY}:quarantine:`)) {
        throw new DOMException("quota exceeded", "QuotaExceededError");
      }
      return originalSetItem.call(this, key, value);
    });

    expect(() => useLayoutStore.getState().renameTab("ws-healthy", "Must not persist"))
      .toThrow(WorkspaceStorageError);
    expect(useLayoutStore.getState().tabs.find((tab) => tab.id === "ws-healthy")?.name)
      .toBe("Healthy");
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
