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
  widgetPickerOpen: boolean;
  presetPickerOpen: boolean;
  addTab: (name?: string) => void;
  removeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  renameTab: (id: string, name: string) => void;
  saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
  getTabLayout: (id: string) => Record<string, unknown> | undefined;
  setWorkspaceApi: (api: WorkspaceApi | null) => void;
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
  widgetPickerOpen: false,
  presetPickerOpen: false,
  addTab: (name) => {
    const id = generateId();
    const tabName = name || `Layout ${get().tabs.length + 1}`;
    set((state) => ({
      tabs: [...state.tabs, { id, name: tabName }],
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
  setActiveTab: (id) => set({ activeTabId: id }),
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
  setWorkspaceApi: (api) => set({ workspaceApi: api }),
  setWidgetPickerOpen: (open) => set({ widgetPickerOpen: open }),
  setPresetPickerOpen: (open) => set({ presetPickerOpen: open }),
  applyPreset: (presetId) => {
    const api = get().workspaceApi;
    if (!api) return;
    applyPresetImpl(api, presetId);
    // After applying, the onModelChange listener in TerminalRoute will
    // auto-save the new layout to the active tab — no manual save needed.
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
