/**
 * bentoStore — Zustand store for bento dashboard card layout.
 *
 * Manages the card config array, add/remove/resize/reorder operations,
 * and named preset save/load. Persisted to localStorage.
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { BentoCardSize } from "@/components/bento/BentoCard";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BentoCardConfig {
  id: string;
  componentId: string;
  size: BentoCardSize;
  order: number;
}

export interface BentoPreset {
  id: string;
  name: string;
  cards: BentoCardConfig[];
}

interface BentoStore {
  cards: BentoCardConfig[];
  presets: BentoPreset[];
  activePresetId: string | null;

  // Card operations
  addCard: (componentId: string, size?: BentoCardSize) => void;
  removeCard: (id: string) => void;
  resizeCard: (id: string, size: BentoCardSize) => void;
  reorderCards: (ids: string[]) => void;

  // Preset operations
  savePreset: (name: string) => void;
  loadPreset: (presetId: string) => void;
  deletePreset: (presetId: string) => void;
  resetToDefault: () => void;
}

// ---------------------------------------------------------------------------
// Default card layout (persona: trader default)
// ---------------------------------------------------------------------------

export const DEFAULT_CARDS: BentoCardConfig[] = [
  { id: "card-welcome",   componentId: "WelcomeCard",   size: "wide",    order: 0 },
  { id: "card-ai",        componentId: "AIPulseCard",   size: "default", order: 1 },
  { id: "card-positions", componentId: "PositionsCard", size: "tall",    order: 2 },
  { id: "card-chart",     componentId: "MiniChartCard", size: "wide",    order: 3 },
  { id: "card-portfolio", componentId: "PortfolioCard", size: "default", order: 4 },
  { id: "card-watchlist", componentId: "WatchlistCard", size: "default", order: 5 },
  { id: "card-news",      componentId: "NewsCard",      size: "wide",    order: 6 },
  { id: "card-breadth",   componentId: "BreadthCard",   size: "default", order: 7 },
  { id: "card-sector",    componentId: "SectorCard",    size: "default", order: 8 },
  { id: "card-sip",       componentId: "SIPCard",       size: "default", order: 9 },
  { id: "card-global",    componentId: "GlobalCard",    size: "default", order: 10 },
  { id: "card-orders",    componentId: "OrdersCard",    size: "default", order: 11 },
];

function generateId(): string {
  return `BENTO-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<
  BentoStore,
  [["zustand/devtools", never], ["zustand/persist", unknown]]
> = (set, get) => ({
  cards: DEFAULT_CARDS,
  presets: [],
  activePresetId: null,

  addCard: (componentId, size = "default") => {
    const cards = get().cards;
    const id = generateId();
    const order = cards.length;
    set((state) => ({
      cards: [...state.cards, { id, componentId, size, order }],
    }));
  },

  removeCard: (id) => {
    set((state) => {
      const filtered = state.cards
        .filter((c) => c.id !== id)
        .map((c, i) => ({ ...c, order: i }));
      return { cards: filtered };
    });
  },

  resizeCard: (id, size) => {
    set((state) => ({
      cards: state.cards.map((c) => (c.id === id ? { ...c, size } : c)),
    }));
  },

  reorderCards: (ids) => {
    set((state) => {
      const cardMap = new Map(state.cards.map((c) => [c.id, c]));
      const reordered = ids
        .map((id, i) => {
          const card = cardMap.get(id);
          return card ? { ...card, order: i } : null;
        })
        .filter((c): c is BentoCardConfig => c !== null);
      // Append any cards not in the ids list (safety net)
      const remaining = state.cards
        .filter((c) => !ids.includes(c.id))
        .map((c, i) => ({ ...c, order: reordered.length + i }));
      return { cards: [...reordered, ...remaining] };
    });
  },

  savePreset: (name) => {
    const id = generateId();
    const cards = get().cards.map((c) => ({ ...c }));
    set((state) => ({
      presets: [...state.presets, { id, name, cards }],
      activePresetId: id,
    }));
  },

  loadPreset: (presetId) => {
    const preset = get().presets.find((p) => p.id === presetId);
    if (!preset) return;
    set({ cards: preset.cards.map((c) => ({ ...c })), activePresetId: presetId });
  },

  deletePreset: (presetId) => {
    set((state) => ({
      presets: state.presets.filter((p) => p.id !== presetId),
      activePresetId: state.activePresetId === presetId ? null : state.activePresetId,
    }));
  },

  resetToDefault: () => {
    set({ cards: DEFAULT_CARDS.map((c) => ({ ...c })), activePresetId: null });
  },
});

export const useBentoStore = create<BentoStore>()(
  devtools(
    persist(storeImpl, {
      name: "flinttrade:bento",
      partialize: (state) => ({
        cards: state.cards,
        presets: state.presets,
        activePresetId: state.activePresetId,
      }),
    }),
    { name: "BentoStore" }
  )
);
