import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { PersistStorage, StorageValue } from "zustand/middleware";
import type { StateCreator } from "zustand";
import { Model } from "flexlayout-react";
import type { IJsonModel } from "flexlayout-react";
import type { WorkspaceApi } from "@/layout/flexLayoutAdapter";
import { applyPreset as applyPresetImpl } from "@/layout/workspacePresets";

export class WorkspaceStorageError extends Error {
  constructor(message = "Workspace storage is corrupted and could not be read.") {
    super(message);
    this.name = "WorkspaceStorageError";
  }
}

export interface WorkspaceCreationTransaction {
  id: string;
  state: "pending" | "committed";
}

interface LayoutTab {
  id: string;
  name: string;
  serializedLayout?: Record<string, unknown>;
  creationTransaction?: WorkspaceCreationTransaction;
}

interface LayoutStore {
  tabs: LayoutTab[];
  activeTabId: string;
  layoutStorageError: WorkspaceStorageError | null;
  layoutStorageQuarantined: boolean;
  workspaceApi: WorkspaceApi | null;
  workspaceApiTabId: string | null;
  widgetPickerOpen: boolean;
  presetPickerOpen: boolean;
  addTab: (
    name?: string,
    initialLayout?: Record<string, unknown>,
    providedId?: string,
    creationTransaction?: WorkspaceCreationTransaction,
  ) => void;
  commitTabCreation: (id: string, transactionId: string) => void;
  removeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  renameTab: (id: string, name: string) => void;
  saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
  getTabLayout: (id: string) => Record<string, unknown> | undefined;
  setWorkspaceApi: (api: WorkspaceApi | null, tabId?: string) => void;
  setWidgetPickerOpen: (open: boolean) => void;
  setPresetPickerOpen: (open: boolean) => void;
  applyPreset: (presetId: string) => void;
}

type PersistedLayoutState = Pick<LayoutStore, "tabs" | "activeTabId">;

const LAYOUT_STORAGE_KEY = "flinttrade:layouts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type SerializedLayoutKind = "empty" | "setup" | "dockview" | "flexlayout" | "corrupt";

export function classifySerializedLayout(
  layout: Record<string, unknown> | undefined,
): SerializedLayoutKind {
  if (layout === undefined || Object.keys(layout).length === 0) return "empty";

  const keys = Object.keys(layout);
  if (
    keys.length === 1
    && keys[0] === "__pendingPreset"
    && typeof layout.__pendingPreset === "string"
  ) {
    return "setup";
  }

  if (isRecord(layout.grid) && isRecord(layout.panels)) return "dockview";

  try {
    Model.fromJson(layout as unknown as IJsonModel);
    return "flexlayout";
  } catch {
    return "corrupt";
  }
}

function corruptLayoutStorageError(): WorkspaceStorageError {
  return new WorkspaceStorageError(
    "Workspace layout storage is corrupted and could not be read.",
  );
}

function parsePersistedLayoutValue(raw: string): StorageValue<PersistedLayoutState> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw corruptLayoutStorageError();
  }

  if (!isRecord(parsed) || !isRecord(parsed.state)) {
    throw corruptLayoutStorageError();
  }
  const { tabs, activeTabId } = parsed.state;
  if (!Array.isArray(tabs) || typeof activeTabId !== "string") {
    throw corruptLayoutStorageError();
  }
  const validTabs = tabs.every((tab) =>
    isRecord(tab)
    && typeof tab.id === "string"
    && typeof tab.name === "string"
    && (tab.serializedLayout === undefined || isRecord(tab.serializedLayout))
    && (
      tab.creationTransaction === undefined
      || (
        isRecord(tab.creationTransaction)
        && typeof tab.creationTransaction.id === "string"
        && (
          tab.creationTransaction.state === "pending"
          || tab.creationTransaction.state === "committed"
        )
      )
    )
  );
  if (!validTabs || !tabs.some((tab) => (tab as Record<string, unknown>).id === activeTabId)) {
    throw corruptLayoutStorageError();
  }
  if (parsed.version !== undefined && typeof parsed.version !== "number") {
    throw corruptLayoutStorageError();
  }
  return parsed as StorageValue<PersistedLayoutState>;
}

interface InitialLayoutStorageInspection {
  error: WorkspaceStorageError | null;
  quarantined: boolean;
}

function hasQuarantinedTab(value: StorageValue<PersistedLayoutState>): boolean {
  return value.state.tabs.some((tab) =>
    classifySerializedLayout(tab.serializedLayout) === "corrupt"
  );
}

function inspectInitialLayoutStorage(): InitialLayoutStorageInspection {
  if (typeof window === "undefined") return { error: null, quarantined: false };
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown storage error";
    return {
      error: new WorkspaceStorageError(`Workspace layout storage could not be read: ${detail}`),
      quarantined: false,
    };
  }
  if (raw === null) return { error: null, quarantined: false };
  try {
    const value = parsePersistedLayoutValue(raw);
    return { error: null, quarantined: hasQuarantinedTab(value) };
  } catch (error) {
    return {
      error: error instanceof WorkspaceStorageError ? error : corruptLayoutStorageError(),
      quarantined: false,
    };
  }
}

const initialLayoutStorage = inspectInitialLayoutStorage();
let layoutStorageError = initialLayoutStorage.error;
let layoutStorageQuarantined = initialLayoutStorage.quarantined;

const layoutStorage: PersistStorage<PersistedLayoutState> = {
  getItem: (name) => {
    if (layoutStorageError) return null;
    const raw = window.localStorage.getItem(name);
    if (raw === null) return null;
    try {
      const value = parsePersistedLayoutValue(raw);
      layoutStorageQuarantined = hasQuarantinedTab(value);
      return value;
    } catch (error) {
      layoutStorageError = error instanceof WorkspaceStorageError
        ? error
        : corruptLayoutStorageError();
      return null;
    }
  },
  setItem: (name, value) => {
    // A corrupt snapshot is evidence, not an empty store. Keep the exact bytes
    // until an explicit recovery flow exists; transient UI state may still move.
    if (layoutStorageError || layoutStorageQuarantined) return;
    window.localStorage.setItem(name, JSON.stringify(value));
  },
  removeItem: (name) => {
    if (layoutStorageError || layoutStorageQuarantined) return;
    window.localStorage.removeItem(name);
  },
};

function assertLayoutStorageHealthy(state: LayoutStore): void {
  if (state.layoutStorageError) throw state.layoutStorageError;
  if (state.layoutStorageQuarantined) {
    throw new WorkspaceStorageError(
      "Workspace layout storage contains a quarantined document and is read-only until recovery.",
    );
  }
}

function getCorruptTabLayoutError(tab: LayoutTab): WorkspaceStorageError | null {
  if (classifySerializedLayout(tab.serializedLayout) !== "corrupt") return null;
  return new WorkspaceStorageError(
    `Workspace "${tab.name}" layout is corrupted and has been quarantined.`,
  );
}

function assertTabLayoutReadable(tab: LayoutTab): void {
  const error = getCorruptTabLayoutError(tab);
  if (error) throw error;
}

function generateId(): string {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

const defaultTabId = generateId();

const storeImpl: StateCreator<LayoutStore, [["zustand/persist", unknown]]> = (set, get) => ({
  tabs: [{ id: defaultTabId, name: "Workspace" }],
  activeTabId: defaultTabId,
  layoutStorageError,
  layoutStorageQuarantined,
  workspaceApi: null,
  workspaceApiTabId: null,
  widgetPickerOpen: false,
  presetPickerOpen: false,
  addTab: (name, initialLayout, providedId, creationTransaction) => {
    assertLayoutStorageHealthy(get());
    const id = providedId || generateId();
    const tabName = name || `Layout ${get().tabs.length + 1}`;
    const newTab: LayoutTab = {
      id,
      name: tabName,
      ...(creationTransaction ? { creationTransaction: { ...creationTransaction } } : {}),
    };
    if (initialLayout) {
      newTab.serializedLayout = initialLayout;
    }
    assertTabLayoutReadable(newTab);
    set((state) => ({
      tabs: [...state.tabs, newTab],
      activeTabId: id,
    }));
  },
  commitTabCreation: (id, transactionId) => {
    assertLayoutStorageHealthy(get());
    const tab = get().tabs.find((candidate) => candidate.id === id);
    if (!tab || tab.creationTransaction?.id !== transactionId) {
      throw new WorkspaceStorageError(
        `Workspace creation transaction "${transactionId}" could not be committed.`,
      );
    }
    set((state) => ({
      tabs: state.tabs.map((candidate) =>
        candidate.id === id
          ? {
              ...candidate,
              creationTransaction: { id: transactionId, state: "committed" },
            }
          : candidate
      ),
    }));
  },
  removeTab: (id) => {
    assertLayoutStorageHealthy(get());
    set((state) => {
      const remaining = state.tabs.filter((t) => t.id !== id);
      if (remaining.length === 0) return state;
      const newActive =
        state.activeTabId === id ? remaining[0].id : state.activeTabId;
      return { tabs: remaining, activeTabId: newActive };
    });
  },
  setActiveTab: (id) => {
    assertLayoutStorageHealthy(get());
    const tab = get().tabs.find((candidate) => candidate.id === id);
    if (tab) {
      assertTabLayoutReadable(tab);
      set({ activeTabId: id });
    }
  },
  renameTab: (id, name) => {
    assertLayoutStorageHealthy(get());
    set((state) => ({
      tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
    }));
  },
  saveTabLayout: (id, layout) => {
    assertLayoutStorageHealthy(get());
    const existing = get().tabs.find((tab) => tab.id === id);
    if (existing) assertTabLayoutReadable(existing);
    set((state) => ({
      tabs: state.tabs.map((t) =>
        t.id === id ? { ...t, serializedLayout: layout } : t
      ),
    }));
  },
  getTabLayout: (id) => {
    return get().tabs.find((t) => t.id === id)?.serializedLayout;
  },
  setWorkspaceApi: (api, tabId) => set({
    workspaceApi: api,
    workspaceApiTabId: api ? (tabId ?? get().activeTabId) : null,
  }),
  setWidgetPickerOpen: (open) => set({ widgetPickerOpen: open }),
  setPresetPickerOpen: (open) => set({ presetPickerOpen: open }),
  applyPreset: (presetId) => {
    assertLayoutStorageHealthy(get());
    const api = get().workspaceApi;
    if (!api) return;
    applyPresetImpl(api, presetId);
    // After applying, the model-level change listener TerminalRoute
    // registers in loadModel auto-saves the new layout to the tab that
    // owns the model — no manual save needed, mounted view or not.
  },
});

const persistedStore = persist(storeImpl, {
  name: LAYOUT_STORAGE_KEY,
  storage: layoutStorage,
  partialize: (state): PersistedLayoutState => ({
    tabs: state.tabs,
    activeTabId: state.activeTabId,
  }),
});

export const useLayoutStore = import.meta.env.DEV
  ? create<LayoutStore>()(devtools(persistedStore, { name: "layout" }))
  : create<LayoutStore>()(persistedStore);
