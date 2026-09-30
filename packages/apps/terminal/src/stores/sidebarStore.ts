/**
 * sidebarStore.ts
 *
 * Zustand v5 store for the app navigation sidebar (DockSidebar).
 * Persists to localStorage under "flinttrade:sidebar" (version 2).
 *
 * Responsibilities:
 *   - Track sidebar display mode: icons / expanded / auto-hide / hidden
 *   - Maintain the ordered list of sidebar items (routes + labelled group
 *     separators)
 *   - Track hover state for auto-hide expansion and the phone drawer state
 *   - Reorder items via drag-and-drop
 *
 * Every route label is the H1 of the page it opens, so the sidebar and the
 * page always agree on what a place is called.
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
  /** Route label, or the group heading for a separator ("" for a plain rule). */
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
  /** Phone-width navigation drawer. Never persisted. */
  mobileOpen: boolean;
  setMode: (mode: SidebarMode) => void;
  reorderItems: (fromIndex: number, toIndex: number) => void;
  setHovered: (hovered: boolean) => void;
  setMobileOpen: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Default items
// ---------------------------------------------------------------------------

const BASE_DEFAULT_ITEMS: SidebarItem[] = [
  { id: "home",      label: "Home",         icon: "Home",          route: "/home",     type: "route" },
  { id: "trade",     label: "Trade",        icon: "TrendingUp",    route: "/trade",    type: "route" },
  { id: "invest",    label: "Invest",       icon: "Wallet",        route: "/invest",   type: "route" },
  { id: "learn",     label: "Learn",        icon: "BookOpen",      route: "/learn",    type: "route" },
  { id: "sep-1",     label: "Tools",        icon: "",              route: "",          type: "separator" },
  { id: "lab",       label: "Strategy Lab", icon: "FlaskConical",  route: "/lab",      type: "route" },
  { id: "automate",  label: "Automate",     icon: "Zap",           route: "/automate", type: "route" },
  { id: "ai",        label: "AI Centre",    icon: "Bot",           route: "/ai",       type: "route" },
  { id: "sep-2",     label: "Manage",       icon: "",              route: "",          type: "separator" },
  { id: "ditto",     label: "Accounts",     icon: "Users",         route: "/ditto",    type: "route" },
  { id: "admin",     label: "Admin",        icon: "Shield",        route: "/admin",    type: "route" },
  { id: "settings",  label: "Settings",     icon: "Settings",      route: "/settings", type: "route" },
];

const DEFAULT_ITEMS: SidebarItem[] = import.meta.env.DEV
  ? BASE_DEFAULT_ITEMS
  : BASE_DEFAULT_ITEMS.filter((item) => item.id !== "admin");

function isSidebarItemAllowed(item: SidebarItem): boolean {
  return import.meta.env.DEV || item.id !== "admin";
}

function reconcileSidebarItems(persistedItems: SidebarItem[] | undefined): SidebarItem[] {
  if (!persistedItems || persistedItems.length === 0) return DEFAULT_ITEMS;

  const defaultsById = new Map(DEFAULT_ITEMS.map((item) => [item.id, item]));
  const seenIds = new Set<string>();
  const reconciled = persistedItems.flatMap((item) => {
    if (!isSidebarItemAllowed(item)) return [];
    const defaultItem = defaultsById.get(item.id);
    if (!defaultItem) return [item];
    seenIds.add(item.id);
    return [defaultItem];
  });

  for (const item of DEFAULT_ITEMS) {
    if (!seenIds.has(item.id)) reconciled.push(item);
  }

  return reconciled;
}

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
  mobileOpen: false,

  setMode: (mode) => set({ mode }),

  reorderItems: (fromIndex, toIndex) =>
    set((state) => {
      const items = [...state.items];
      const [moved] = items.splice(fromIndex, 1);
      items.splice(toIndex, 0, moved);
      return { items };
    }),

  setHovered: (isHovered) => set({ isHovered }),

  setMobileOpen: (mobileOpen) => set({ mobileOpen }),
});

// ---------------------------------------------------------------------------
// Store with persist
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:sidebar",
  version: 2,
  storage: createJSONStorage(() => localStorage),
  // Only persist user preferences, not transient hover or drawer state
  partialize: (state) => ({
    mode: state.mode,
    items: state.items.filter(isSidebarItemAllowed),
  }),
  // v2 regrouped the navigation (Tools / Manage). A v1 custom order predates
  // those groups, so it restarts from the new default order.
  migrate: (persisted, version) => {
    const p = (persisted ?? {}) as Partial<SidebarState>;
    if (version < 2) return (p.mode ? { mode: p.mode } : {}) as Partial<SidebarState>;
    return p;
  },
  // Merge persisted items with new defaults so additions in future versions
  // are picked up without a full reset
  merge: (persisted, current) => {
    const p = persisted as Partial<SidebarState>;
    return {
      ...current,
      ...p,
      items: reconcileSidebarItems(p.items),
    };
  },
});

export const useSidebarStore = import.meta.env.DEV
  ? create<SidebarState>()(devtools(persistedStore, { name: "sidebar" }))
  : create<SidebarState>()(persistedStore);
