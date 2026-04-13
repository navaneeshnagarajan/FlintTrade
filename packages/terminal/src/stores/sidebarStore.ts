/**
 * sidebarStore.ts
 *
 * Zustand v5 store for the macOS dock-style DockSidebar.
 * Persists to localStorage under "flinttrade:sidebar" (version 1).
 *
 * Responsibilities:
 *   - Track sidebar display mode: icons / expanded / auto-hide / hidden
 *   - Maintain ordered list of sidebar items (routes + separators)
 *   - Track hover state for auto-hide expansion
 *   - Reorder items via drag-and-drop
 */

import { create } from "zustand";
import { createJSONStorage, devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SidebarMode = "icons" | "expanded" | "auto-hide" | "hidden";

export interface SidebarItem {
  id: string;
  label: string;
  /** lucide-react icon name */
  icon: string;
  route: string;
  type: "route" | "separator";
}

export interface SidebarState {
  mode: SidebarMode;
  items: SidebarItem[];
  isHovered: boolean;
  setMode: (mode: SidebarMode) => void;
  reorderItems: (fromIndex: number, toIndex: number) => void;
  setHovered: (hovered: boolean) => void;
}

// ---------------------------------------------------------------------------
// Default items
// ---------------------------------------------------------------------------

const DEFAULT_ITEMS: SidebarItem[] = [
  { id: "home",      label: "Home",      icon: "Home",          route: "/",         type: "route" },
  { id: "trade",     label: "Trade",     icon: "TrendingUp",    route: "/trade",    type: "route" },
  { id: "invest",    label: "Invest",    icon: "Wallet",        route: "/invest",   type: "route" },
  { id: "learn",     label: "Learn",     icon: "BookOpen",      route: "/learn",    type: "route" },
  { id: "lab",       label: "Lab",       icon: "FlaskConical",  route: "/lab",      type: "route" },
  { id: "automate",  label: "Automate",  icon: "Zap",           route: "/automate", type: "route" },
  { id: "sep-1",     label: "",          icon: "",              route: "",          type: "separator" },
  { id: "ai",        label: "AI Hub",    icon: "Bot",           route: "/ai",       type: "route" },
  { id: "ditto",     label: "Ditto",     icon: "Copy",          route: "/ditto",    type: "route" },
  { id: "admin",     label: "Admin",     icon: "Shield",        route: "/admin",    type: "route" },
  { id: "sep-2",     label: "",          icon: "",              route: "",          type: "separator" },
  { id: "settings",  label: "Settings",  icon: "Settings",      route: "/settings", type: "route" },
];

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<
  SidebarState,
  [["zustand/persist", unknown]]
> = (set) => ({
  mode: "icons",
  items: DEFAULT_ITEMS,
  isHovered: false,

  setMode: (mode) => set({ mode }),

  reorderItems: (fromIndex, toIndex) =>
    set((state) => {
      const items = [...state.items];
      const [moved] = items.splice(fromIndex, 1);
      items.splice(toIndex, 0, moved);
      return { items };
    }),

  setHovered: (isHovered) => set({ isHovered }),
});

// ---------------------------------------------------------------------------
// Store with persist
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:sidebar",
  version: 1,
  storage: createJSONStorage(() => localStorage),
  // Only persist user preferences, not transient hover state
  partialize: (state) => ({
    mode: state.mode,
    items: state.items,
  }),
  // Merge persisted items with new defaults so additions in future versions
  // are picked up without a full reset
  merge: (persisted, current) => {
    const p = persisted as Partial<SidebarState>;
    return {
      ...current,
      ...p,
      items: p.items && p.items.length > 0 ? p.items : current.items,
    };
  },
});

export const useSidebarStore = import.meta.env.DEV
  ? create<SidebarState>()(devtools(persistedStore, { name: "sidebar" }))
  : create<SidebarState>()(persistedStore);
