import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { WorkspaceApi } from "@/layout/flexLayoutAdapter";
import { applyPreset as applyPresetImpl } from "@/layout/workspacePresets";

interface LayoutTab {
  id: string;
  name: string;
  serializedLayout?: Record<string, unknown>;
}

interface LayoutStore {
  tabs: LayoutTab[];
  activeTabId: string;
  workspaceApi: WorkspaceApi | null;
  workspaceApiTabId: string | null;
  widgetPickerOpen: boolean;
  presetPickerOpen: boolean;
  addTab: (name?: string, initialLayout?: Record<string, unknown>, providedId?: string) => void;
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

function generateId(): string {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

const defaultTabId = generateId();

const storeImpl: StateCreator<LayoutStore, [["zustand/persist", unknown]]> = (set, get) => ({
  tabs: [{ id: defaultTabId, name: "Workspace" }],
  activeTabId: defaultTabId,
  workspaceApi: null,
  workspaceApiTabId: null,
  widgetPickerOpen: false,
  presetPickerOpen: false,
  addTab: (name, initialLayout, providedId) => {
    const id = providedId || generateId();
    const tabName = name || `Layout ${get().tabs.length + 1}`;
    const newTab: LayoutTab = { id, name: tabName };
    if (initialLayout) {
      newTab.serializedLayout = initialLayout;
    }
    set((state) => ({
      tabs: [...state.tabs, newTab],
      activeTabId: id,
    }));
  },
  removeTab: (id) => {
    set((state) => {
      const remaining = state.tabs.filter((t) => t.id !== id);
      if (remaining.length === 0) return state;
      const newActive =
        state.activeTabId === id ? remaining[0].id : state.activeTabId;
      return { tabs: remaining, activeTabId: newActive };
    });
  },
  setActiveTab: (id) => {
    if (get().tabs.some((tab) => tab.id === id)) {
      set({ activeTabId: id });
    }
  },
  renameTab: (id, name) => {
    set((state) => ({
      tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
    }));
  },
  saveTabLayout: (id, layout) => {
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
    const api = get().workspaceApi;
    if (!api) return;
    applyPresetImpl(api, presetId);
    // After applying, the model-level change listener TerminalRoute
    // registers in loadModel auto-saves the new layout to the tab that
    // owns the model — no manual save needed, mounted view or not.
  },
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:layouts",
  partialize: (state) => ({
    tabs: state.tabs,
    activeTabId: state.activeTabId,
  }) as LayoutStore,
});

export const useLayoutStore = import.meta.env.DEV
  ? create<LayoutStore>()(devtools(persistedStore, { name: "layout" }))
  : create<LayoutStore>()(persistedStore);
