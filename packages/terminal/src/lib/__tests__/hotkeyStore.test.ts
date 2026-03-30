/**
 * hotkeyStore tests
 *
 * Tests hotkey normalization, conflict detection, and persistence.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import {
  normalizeKeyCombo,
  eventToKeys,
  formatKeyCombo,
  detectConflicts,
  findConflict,
  loadCustomHotkeys,
  saveHotkeyOverride,
  resetHotkeyToDefault,
  resetAllHotkeys,
  DEFAULT_HOTKEYS,
  type HotkeyBinding,
} from "../hotkeyStore";

// ---------------------------------------------------------------------------
// Mock localStorage
// ---------------------------------------------------------------------------

const store: Record<string, string> = {};

beforeEach(() => {
  for (const key of Object.keys(store)) delete store[key];
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, val: string) => { store[key] = val; },
    removeItem: (key: string) => { delete store[key]; },
  });
});

// ---------------------------------------------------------------------------
// normalizeKeyCombo
// ---------------------------------------------------------------------------

describe("normalizeKeyCombo", () => {
  it("joins single key", () => {
    expect(normalizeKeyCombo(["Escape"])).toBe("Escape");
  });

  it("sorts modifiers alphabetically before main key", () => {
    expect(normalizeKeyCombo(["Shift", "Ctrl", "X"])).toBe("Ctrl+Shift+X");
  });

  it("handles Ctrl+K", () => {
    expect(normalizeKeyCombo(["Ctrl", "K"])).toBe("Ctrl+K");
  });

  it("returns same result regardless of input order", () => {
    expect(normalizeKeyCombo(["X", "Shift"])).toBe("Shift+X");
    expect(normalizeKeyCombo(["Shift", "X"])).toBe("Shift+X");
  });
});

// ---------------------------------------------------------------------------
// eventToKeys
// ---------------------------------------------------------------------------

describe("eventToKeys", () => {
  it("returns single key for plain keypress", () => {
    const e = new KeyboardEvent("keydown", { key: "c" });
    expect(eventToKeys(e)).toEqual(["C"]);
  });

  it("includes Ctrl modifier", () => {
    const e = new KeyboardEvent("keydown", { key: "k", ctrlKey: true });
    expect(eventToKeys(e)).toEqual(["Ctrl", "K"]);
  });

  it("includes Shift modifier", () => {
    const e = new KeyboardEvent("keydown", { key: "X", shiftKey: true });
    expect(eventToKeys(e)).toEqual(["Shift", "X"]);
  });

  it("does not include bare modifier keys as main key", () => {
    const e = new KeyboardEvent("keydown", { key: "Shift", shiftKey: true });
    expect(eventToKeys(e)).toEqual(["Shift"]);
  });

  it("preserves special key names", () => {
    const e = new KeyboardEvent("keydown", { key: "Escape" });
    expect(eventToKeys(e)).toEqual(["Escape"]);
  });
});

// ---------------------------------------------------------------------------
// formatKeyCombo
// ---------------------------------------------------------------------------

describe("formatKeyCombo", () => {
  it("joins with + separator", () => {
    expect(formatKeyCombo(["Ctrl", "K"])).toBe("Ctrl + K");
  });

  it("handles single key", () => {
    expect(formatKeyCombo(["Escape"])).toBe("Escape");
  });
});

// ---------------------------------------------------------------------------
// detectConflicts
// ---------------------------------------------------------------------------

describe("detectConflicts", () => {
  it("returns empty for no conflicts", () => {
    const bindings: HotkeyBinding[] = [
      { id: "a", action: "A", category: "global", keys: ["A"], customizable: true, description: "" },
      { id: "b", action: "B", category: "global", keys: ["B"], customizable: true, description: "" },
    ];
    expect(detectConflicts(bindings)).toEqual([]);
  });

  it("detects duplicate key combos", () => {
    const bindings: HotkeyBinding[] = [
      { id: "a", action: "A", category: "global", keys: ["C"], customizable: true, description: "" },
      { id: "b", action: "B", category: "global", keys: ["C"], customizable: true, description: "" },
    ];
    const conflicts = detectConflicts(bindings);
    expect(conflicts.length).toBe(1);
    expect(conflicts[0].bindingIds).toContain("a");
    expect(conflicts[0].bindingIds).toContain("b");
  });

  it("treats different modifier combos as different", () => {
    const bindings: HotkeyBinding[] = [
      { id: "a", action: "A", category: "global", keys: ["C"], customizable: true, description: "" },
      { id: "b", action: "B", category: "global", keys: ["Ctrl", "C"], customizable: true, description: "" },
    ];
    expect(detectConflicts(bindings)).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// findConflict
// ---------------------------------------------------------------------------

describe("findConflict", () => {
  const bindings: HotkeyBinding[] = [
    { id: "a", action: "A", category: "global", keys: ["C"], customizable: true, description: "" },
    { id: "b", action: "B", category: "global", keys: ["X"], customizable: true, description: "" },
  ];

  it("returns null when no conflict", () => {
    expect(findConflict(["B"], "a", bindings)).toBeNull();
  });

  it("excludes self from check", () => {
    expect(findConflict(["C"], "a", bindings)).toBeNull();
  });

  it("returns conflicting id", () => {
    expect(findConflict(["X"], "a", bindings)).toBe("b");
  });
});

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

describe("loadCustomHotkeys", () => {
  it("returns defaults when no overrides saved", () => {
    const hotkeys = loadCustomHotkeys();
    expect(hotkeys.length).toBe(DEFAULT_HOTKEYS.length);
    expect(hotkeys[0].keys).toEqual(DEFAULT_HOTKEYS[0].keys);
  });

  it("merges saved overrides with defaults", () => {
    store["flinttrade_custom_hotkeys"] = JSON.stringify({
      "quick-buy": ["G"],
    });
    const hotkeys = loadCustomHotkeys();
    const quickBuy = hotkeys.find((h) => h.id === "quick-buy");
    expect(quickBuy).toBeDefined();
    expect(quickBuy!.keys).toEqual(["G"]);
  });

  it("does not override non-customizable bindings", () => {
    store["flinttrade_custom_hotkeys"] = JSON.stringify({
      "escape": ["Q"],
    });
    const hotkeys = loadCustomHotkeys();
    const escape = hotkeys.find((h) => h.id === "escape");
    expect(escape!.keys).toEqual(["Escape"]);
  });
});

describe("saveHotkeyOverride", () => {
  it("persists override to localStorage", () => {
    saveHotkeyOverride("quick-buy", ["G"]);
    const saved = JSON.parse(store["flinttrade_custom_hotkeys"]);
    expect(saved["quick-buy"]).toEqual(["G"]);
  });

  it("preserves existing overrides", () => {
    saveHotkeyOverride("quick-buy", ["G"]);
    saveHotkeyOverride("quick-sell", ["H"]);
    const saved = JSON.parse(store["flinttrade_custom_hotkeys"]);
    expect(saved["quick-buy"]).toEqual(["G"]);
    expect(saved["quick-sell"]).toEqual(["H"]);
  });
});

describe("resetHotkeyToDefault", () => {
  it("returns default keys", () => {
    saveHotkeyOverride("quick-buy", ["G"]);
    const keys = resetHotkeyToDefault("quick-buy");
    expect(keys).toEqual(["B"]);
  });

  it("removes override from storage", () => {
    saveHotkeyOverride("quick-buy", ["G"]);
    resetHotkeyToDefault("quick-buy");
    const saved = JSON.parse(store["flinttrade_custom_hotkeys"]);
    expect(saved["quick-buy"]).toBeUndefined();
  });

  it("returns null for unknown id", () => {
    expect(resetHotkeyToDefault("nonexistent")).toBeNull();
  });
});

describe("resetAllHotkeys", () => {
  it("removes all overrides from storage", () => {
    saveHotkeyOverride("quick-buy", ["G"]);
    saveHotkeyOverride("quick-sell", ["H"]);
    resetAllHotkeys();
    expect(store["flinttrade_custom_hotkeys"]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// DEFAULT_HOTKEYS integrity
// ---------------------------------------------------------------------------

describe("DEFAULT_HOTKEYS", () => {
  it("has no conflicts in defaults", () => {
    const conflicts = detectConflicts(DEFAULT_HOTKEYS);
    expect(conflicts).toEqual([]);
  });

  it("every binding has a unique id", () => {
    const ids = DEFAULT_HOTKEYS.map((h) => h.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
