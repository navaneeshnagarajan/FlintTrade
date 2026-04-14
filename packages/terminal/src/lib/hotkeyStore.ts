/**
 * hotkeyStore — Hotkey customization storage and conflict detection.
 *
 * Stores user-customized hotkeys in localStorage. Pure functions for
 * conflict detection and key normalization are testable independently.
 */

import { z } from "zod";
import { safeParse } from "@/lib/safeParse";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HotkeyBinding {
  /** Unique identifier for the action */
  id: string;
  /** Human-readable action description */
  action: string;
  /** Category for grouping in UI */
  category: "global" | "scalper" | "chart" | "trading";
  /** Key combo, e.g. ["Ctrl", "K"] or ["Shift", "X"] */
  keys: string[];
  /** Whether this binding can be customized */
  customizable: boolean;
  /** Short description */
  description: string;
}

export interface HotkeyConflict {
  /** The normalized key combo that conflicts */
  combo: string;
  /** IDs of bindings sharing this combo */
  bindingIds: string[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade_custom_hotkeys";

export const DEFAULT_HOTKEYS: HotkeyBinding[] = [
  // Global
  {
    id: "escape",
    action: "Close overlay / dismiss panel",
    category: "global",
    keys: ["Escape"],
    customizable: false,
    description: "Closes any open tool overlay, basket, or dropdown",
  },
  {
    id: "command-palette",
    action: "Command palette / symbol search",
    category: "global",
    keys: ["Ctrl", "K"],
    customizable: false,
    description: "Open the global symbol and action search bar",
  },
  {
    id: "open-settings",
    action: "Open settings",
    category: "global",
    keys: ["Ctrl", ","],
    customizable: false,
    description: "Open the Settings tool overlay",
  },

  // Scalper — position management
  {
    id: "cancel-orders",
    action: "Cancel all orders",
    category: "scalper",
    keys: ["C"],
    customizable: true,
    description: "Cancel all pending/open orders in the current strategy",
  },
  {
    id: "exit-confirm",
    action: "Exit all positions (confirm)",
    category: "scalper",
    keys: ["X"],
    customizable: true,
    description: "Prompts confirmation before squaring off all open positions",
  },
  {
    id: "exit-immediate",
    action: "Exit all positions immediately",
    category: "scalper",
    keys: ["Shift", "X"],
    customizable: true,
    description: "Square off all open positions without confirmation",
  },

  // New trading hotkeys
  {
    id: "quick-buy",
    action: "Quick buy",
    category: "trading",
    keys: ["B"],
    customizable: true,
    description: "Place a quick buy order at current market price",
  },
  {
    id: "quick-sell",
    action: "Quick sell",
    category: "trading",
    keys: ["S"],
    customizable: true,
    description: "Place a quick sell order at current market price",
  },
  {
    id: "flatten-all",
    action: "Flatten / close all",
    category: "trading",
    keys: ["F"],
    customizable: true,
    description: "Close all open positions and cancel all pending orders",
  },
  {
    id: "toggle-timeframe",
    action: "Toggle chart timeframe",
    category: "chart",
    keys: ["T"],
    customizable: true,
    description: "Cycle through chart timeframes (1m, 5m, 15m, 1h, 1D)",
  },
];

// ---------------------------------------------------------------------------
// Key normalization
// ---------------------------------------------------------------------------

/**
 * Normalizes a key combination to a canonical string for comparison.
 * Sorts modifiers alphabetically, joins with "+".
 * E.g. ["Shift", "X"] -> "Shift+X", ["Ctrl", "K"] -> "Ctrl+K"
 */
export function normalizeKeyCombo(keys: string[]): string {
  const modifiers = ["Alt", "Ctrl", "Meta", "Shift"];
  const mods = keys.filter((k) => modifiers.includes(k)).sort();
  const regular = keys.filter((k) => !modifiers.includes(k));
  return [...mods, ...regular].join("+");
}

/**
 * Parses a keyboard event into a key array matching our binding format.
 */
export function eventToKeys(e: KeyboardEvent): string[] {
  const keys: string[] = [];
  if (e.ctrlKey || e.metaKey) keys.push("Ctrl");
  if (e.shiftKey) keys.push("Shift");
  if (e.altKey) keys.push("Alt");

  // Don't include modifier keys themselves as the main key
  const ignoreKeys = new Set(["Control", "Shift", "Alt", "Meta"]);
  if (!ignoreKeys.has(e.key)) {
    keys.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
  }

  return keys;
}

/**
 * Formats a key combo for display (human-readable label).
 */
export function formatKeyCombo(keys: string[]): string {
  return keys.join(" + ");
}

// ---------------------------------------------------------------------------
// Conflict detection
// ---------------------------------------------------------------------------

/**
 * Detects conflicts in a set of hotkey bindings.
 * Returns an array of conflicts (empty if none).
 */
export function detectConflicts(bindings: HotkeyBinding[]): HotkeyConflict[] {
  const comboMap = new Map<string, string[]>();

  for (const b of bindings) {
    const combo = normalizeKeyCombo(b.keys);
    const ids = comboMap.get(combo) ?? [];
    ids.push(b.id);
    comboMap.set(combo, ids);
  }

  const conflicts: HotkeyConflict[] = [];
  for (const [combo, bindingIds] of comboMap.entries()) {
    if (bindingIds.length > 1) {
      conflicts.push({ combo, bindingIds });
    }
  }

  return conflicts;
}

/**
 * Checks if a specific key combo conflicts with existing bindings.
 * Returns the conflicting binding ID or null.
 */
export function findConflict(
  keys: string[],
  excludeId: string,
  bindings: HotkeyBinding[],
): string | null {
  const combo = normalizeKeyCombo(keys);
  for (const b of bindings) {
    if (b.id === excludeId) continue;
    if (normalizeKeyCombo(b.keys) === combo) return b.id;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

/** Saved overrides: only customized bindings, keyed by ID. */
type SavedOverrides = Record<string, string[]>;

const savedOverridesSchema = z.record(z.string(), z.array(z.string()));

/**
 * Loads custom hotkey overrides from localStorage.
 * Returns the merged binding list (defaults + overrides).
 */
export function loadCustomHotkeys(): HotkeyBinding[] {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return [...DEFAULT_HOTKEYS];
  const overrides = safeParse(raw, savedOverridesSchema);
  if (!overrides) return [...DEFAULT_HOTKEYS];
  return DEFAULT_HOTKEYS.map((def) => {
    const custom = overrides[def.id];
    if (custom && def.customizable) {
      return { ...def, keys: custom };
    }
    return { ...def };
  });
}

/**
 * Saves a single hotkey override to localStorage.
 */
export function saveHotkeyOverride(id: string, keys: string[]): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const overrides: SavedOverrides = (raw ? safeParse(raw, savedOverridesSchema) : undefined) ?? {};
    overrides[id] = keys;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    // localStorage might be full or disabled
  }
}

/**
 * Resets a single hotkey to its default.
 */
export function resetHotkeyToDefault(id: string): string[] | null {
  const def = DEFAULT_HOTKEYS.find((h) => h.id === id);
  if (!def) return null;

  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const overrides = safeParse(raw, savedOverridesSchema);
      if (overrides) {
        delete overrides[id];
        localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
      }
    }
  } catch {
    // noop
  }

  return def.keys;
}

/**
 * Resets all hotkeys to defaults.
 */
export function resetAllHotkeys(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // noop
  }
}
