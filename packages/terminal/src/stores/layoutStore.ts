import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { DockviewApi } from "dockview-react";

interface LayoutTab {
  id: string;
  name: string;
  serializedLayout?: Record<string, unknown>;
}

interface LayoutStore {
  tabs: LayoutTab[];
  activeTabId: string;
  dockviewApi: DockviewApi | null;
  addTab: (name?: string) => void;
  removeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  renameTab: (id: string, name: string) => void;
  saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
  getTabLayout: (id: string) => Record<string, unknown> | undefined;
  setDockviewApi: (api: DockviewApi | null) => void;
}

function generateId(): string {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

const defaultTabId = generateId();

export const useLayoutStore = create<LayoutStore>()(
  devtools(
    persist(
      (set, get) => ({
        tabs: [{ id: defaultTabId, name: "Workspace" }],
        activeTabId: defaultTabId,
        dockviewApi: null,
        addTab: (name) => {
          const id = generateId();
          const tabName = name || `Layout ${get().tabs.length + 1}`;
          set(
            (state) => ({
              tabs: [...state.tabs, { id, name: tabName }],
              activeTabId: id,
            }),
            false,
            "addTab"
          );
        },
        removeTab: (id) => {
          set(
            (state) => {
              const remaining = state.tabs.filter((t) => t.id !== id);
              if (remaining.length === 0) return state;
              const newActive =
                state.activeTabId === id ? remaining[0].id : state.activeTabId;
              return { tabs: remaining, activeTabId: newActive };
            },
            false,
            "removeTab"
          );
        },
        setActiveTab: (id) => set({ activeTabId: id }, false, "setActiveTab"),
        renameTab: (id, name) => {
          set(
            (state) => ({
              tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
            }),
            false,
            "renameTab"
          );
        },
        saveTabLayout: (id, layout) => {
          set(
            (state) => ({
              tabs: state.tabs.map((t) =>
                t.id === id ? { ...t, serializedLayout: layout } : t
              ),
            }),
            false,
            "saveTabLayout"
          );
        },
        getTabLayout: (id) => {
          return get().tabs.find((t) => t.id === id)?.serializedLayout;
        },
        setDockviewApi: (api) => set({ dockviewApi: api }, false, "setDockviewApi"),
      }),
      {
        name: "flinttrade:layouts",
        partialize: (state) => ({
          tabs: state.tabs,
          activeTabId: state.activeTabId,
        }),
      }
    ),
    { name: "layout" }
  )
);
