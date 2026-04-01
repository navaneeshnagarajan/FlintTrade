/**
 * themeStore.ts
 *
 * Zustand v5 store for FlintTrade's CinematicTheme system (v4).
 * Persists to localStorage under "flinttrade-theme" (version 4).
 *
 * Responsibilities:
 *   - Track active CinematicTheme id
 *   - Track color mode: "dark" | "light" | "system"
 *     System mode auto-switches via matchMedia listener in real time.
 *   - Store user-authored custom CinematicThemes (ThemeDefinition[])
 *   - Glass effects toggle (default: true)
 *   - reduceMotion preference
 *   - Write 50+ CSS custom properties to document.documentElement on demand
 *
 * Persist version history:
 *   v1 — FlintTradeTheme (12 presets, single mode per theme)
 *   v2 — CinematicTheme (6 presets, dark + light variants, mode field)
 *   v3 — Pruned to 6 canonical themes; default "graphite"
 *   v4 — 3 themes (graphite, midnight, ember); glass as boolean; trading
 *         semantics added to ThemeVariant; system mode matchMedia listener.
 *         All existing users migrated to "graphite".
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import {
  CINEMATIC_THEMES,
  findCinematicTheme,
  getResolvedVariant,
} from "@/lib/cinematicThemes";
import type { CinematicTheme, ColorMode, ThemeDefinition } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// ThemeState
// ---------------------------------------------------------------------------

export interface ThemeState {
  activeThemeId: string;
  /** "dark" | "light" | "system" — system auto-follows OS preference */
  mode: ColorMode;
  /** Custom themes authored by the user via the theme builder */
  customThemes: ThemeDefinition[];
  /** Whether glass/backdrop-blur effects are enabled (default: true) */
  glass: boolean;
  reduceMotion: boolean;

  // --- Actions ---
  setTheme: (id: string) => void;
  setMode: (mode: ColorMode) => void;
  setGlass: (enabled: boolean) => void;
  setReduceMotion: (v: boolean) => void;
  addCustomTheme: (theme: ThemeDefinition) => void;
  removeCustomTheme: (id: string) => void;
  getActiveTheme: () => CinematicTheme;
  getResolvedMode: () => "dark" | "light";
  applyTheme: () => void;
}

// ---------------------------------------------------------------------------
// Migration maps — all legacy theme ids → "graphite" in v4
// ---------------------------------------------------------------------------

const ALL_LEGACY_TO_V4: Record<string, string> = {
  // v1 FlintTradeTheme ids
  midnight:           "midnight",
  obsidian:           "graphite",
  "terminal-green":   "graphite",
  "ocean-blue":       "midnight",
  light:              "graphite",
  sunset:             "ember",
  arctic:             "graphite",
  neon:               "graphite",
  forest:             "graphite",
  monochrome:         "graphite",
  "solarized-dark":   "graphite",
  "solarized-light":  "graphite",
  // v2 ids removed in v3
  "emerald-night":    "graphite",
  "ocean-depth":      "midnight",
  "solar-flare":      "ember",
  "neon-pulse":       "graphite",
  "blood-moon":       "ember",
  // v3 ids removed in v4
  "arctic-frost":     "graphite",
  "solarized-dark-v3":"graphite",
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) return hex;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) return hex;
  return `rgba(${r},${g},${b},${alpha})`;
}

function hexToHslString(hex: string): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) return "142 76% 45%"; // fallback to graphite emerald
  const r = parseInt(cleaned.slice(0, 2), 16) / 255;
  const g = parseInt(cleaned.slice(2, 4), 16) / 255;
  const b = parseInt(cleaned.slice(4, 6), 16) / 255;
  if (isNaN(r) || isNaN(g) || isNaN(b)) return "142 76% 45%";

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const delta = max - min;
  const l = (max + min) / 2;

  let h = 0;
  let s = 0;

  if (delta !== 0) {
    s = delta / (1 - Math.abs(2 * l - 1));
    if (max === r) {
      h = ((g - b) / delta + (g < b ? 6 : 0)) / 6;
    } else if (max === g) {
      h = ((b - r) / delta + 2) / 6;
    } else {
      h = ((r - g) / delta + 4) / 6;
    }
  }

  return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

// ---------------------------------------------------------------------------
// matchMedia listener for "system" mode
// Stored at module level so it can be attached/removed across store calls.
// ---------------------------------------------------------------------------

let _systemMediaQuery: MediaQueryList | null = null;
let _systemListener: ((e: MediaQueryListEvent) => void) | null = null;

function attachSystemListener(onSwitch: () => void): void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;

  detachSystemListener();

  _systemMediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
  _systemListener = (_e: MediaQueryListEvent) => {
    onSwitch();
  };

  // Use addEventListener if available (modern browsers); fallback to addListener
  if (_systemMediaQuery.addEventListener) {
    _systemMediaQuery.addEventListener("change", _systemListener);
  } else {
    // Safari < 14 fallback
    (_systemMediaQuery as MediaQueryList).addListener(_systemListener);
  }
}

function detachSystemListener(): void {
  if (_systemMediaQuery && _systemListener) {
    if (_systemMediaQuery.removeEventListener) {
      _systemMediaQuery.removeEventListener("change", _systemListener);
    } else {
      (_systemMediaQuery as MediaQueryList).removeListener(_systemListener);
    }
    _systemMediaQuery = null;
    _systemListener = null;
  }
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<
  ThemeState,
  [["zustand/persist", unknown]]
> = (set, get) => ({
  activeThemeId: "graphite",
  mode:          "system",
  customThemes:  [],
  glass:         true,
  reduceMotion:  false,

  // --- setTheme ---
  setTheme: (id) => {
    set({ activeThemeId: id });
    get().applyTheme();
  },

  // --- setMode ---
  setMode: (mode) => {
    set({ mode });
    if (mode === "system") {
      attachSystemListener(() => get().applyTheme());
    } else {
      detachSystemListener();
    }
    get().applyTheme();
  },

  // --- setGlass ---
  setGlass: (enabled) => {
    set({ glass: enabled });
    get().applyTheme();
  },

  // --- setReduceMotion ---
  setReduceMotion: (v) => {
    set({ reduceMotion: v });
    if (typeof document !== "undefined") {
      if (v) {
        document.documentElement.classList.add("reduce-motion");
      } else {
        document.documentElement.classList.remove("reduce-motion");
      }
    }
  },

  // --- addCustomTheme ---
  addCustomTheme: (theme) => {
    set((state: ThemeState) => ({
      customThemes: [
        ...state.customThemes.filter((t: ThemeDefinition) => t.id !== theme.id),
        theme,
      ],
    }));
  },

  // --- removeCustomTheme ---
  removeCustomTheme: (id) => {
    set((state: ThemeState) => ({
      customThemes: state.customThemes.filter(
        (t: ThemeDefinition) => t.id !== id,
      ),
      activeThemeId:
        state.activeThemeId === id ? "graphite" : state.activeThemeId,
    }));
    get().applyTheme();
  },

  // --- getActiveTheme ---
  getActiveTheme: () => {
    const { activeThemeId, customThemes } = get();

    // Search custom themes first so users can override built-ins by id
    const custom = customThemes.find((t) => t.id === activeThemeId);
    if (custom) return custom;

    const builtin = findCinematicTheme(activeThemeId);
    if (builtin) return builtin;

    // Fallback — graphite (index 0) is always guaranteed to exist in v4
    return CINEMATIC_THEMES[0];
  },

  // --- getResolvedMode ---
  getResolvedMode: () => {
    const { mode } = get();
    if (mode === "dark") return "dark";
    if (mode === "light") return "light";

    // "system" — check OS preference
    if (
      typeof window !== "undefined" &&
      typeof window.matchMedia === "function"
    ) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light";
    }

    return "dark";
  },

  // --- applyTheme ---
  applyTheme: () => {
    if (typeof document === "undefined") return;

    const { glass, getActiveTheme, getResolvedMode, reduceMotion } = get();
    const theme = getActiveTheme();
    const resolvedMode = getResolvedMode();
    const variant = getResolvedVariant(theme, resolvedMode === "dark" ? "dark" : "light");
    const { shared } = theme;

    const root = document.documentElement;
    const style = root.style;

    // ---- Base surface tokens ----
    style.setProperty("--color-base",       variant.colors.base);
    style.setProperty("--color-card",       variant.colors.card);
    style.setProperty("--color-card-hover", variant.colors.cardHover);
    style.setProperty("--color-border",     variant.colors.border);
    style.setProperty("--color-border-subtle", variant.colors.borderSubtle);

    // ---- Text tokens ----
    style.setProperty("--color-text",           variant.colors.text);
    style.setProperty("--color-text-muted",     variant.colors.textMuted);
    style.setProperty("--color-text-secondary", variant.colors.textSecondary);
    style.setProperty("--color-text-disabled",  variant.colors.textDisabled);

    // ---- Accent tokens ----
    style.setProperty("--color-accent",      variant.colors.accent);
    style.setProperty("--color-accent-text", variant.colors.accentText);

    // ---- Fixed trading semantic colors ----
    // These are consistent across ALL themes and modes.
    style.setProperty("--color-profit",  variant.trading.profit);
    style.setProperty("--color-loss",    variant.trading.loss);
    style.setProperty("--color-warning", variant.trading.warning);

    // Derived bullish / bearish / warning tokens (WCAG AA compliant per mode)
    style.setProperty("--color-bullish-text",   variant.trading.profitText);
    style.setProperty("--color-bullish-bg",     hexToRgba(variant.trading.profit, 0.10));
    style.setProperty("--color-bullish-border", hexToRgba(variant.trading.profit, 0.30));
    style.setProperty("--color-bearish-text",   variant.trading.lossText);
    style.setProperty("--color-bearish-bg",     hexToRgba(variant.trading.loss,   0.10));
    style.setProperty("--color-bearish-border", hexToRgba(variant.trading.loss,   0.30));
    style.setProperty("--color-warning-text",   variant.trading.warningText);
    style.setProperty("--color-warning-bg",     hexToRgba(variant.trading.warning, 0.08));
    style.setProperty("--color-warning-border", hexToRgba(variant.trading.warning, 0.30));

    // Neutral accent-based tokens
    style.setProperty("--color-neutral-text",   variant.colors.accent);
    style.setProperty("--color-neutral-bg",     hexToRgba(variant.colors.accent, 0.10));
    style.setProperty("--color-neutral-border", hexToRgba(variant.colors.accent, 0.30));

    // ---- Chart tokens ----
    style.setProperty("--chart-up",    variant.trading.profitText);
    style.setProperty("--chart-down",  variant.trading.lossText);
    style.setProperty("--chart-grid",  hexToRgba(variant.colors.border, 0.60));
    style.setProperty("--chart-bg",    variant.colors.base);
    style.setProperty("--chart-text",  variant.colors.textMuted);
    style.setProperty("--chart-color-1", variant.chart[0]);
    style.setProperty("--chart-color-2", variant.chart[1]);
    style.setProperty("--chart-color-3", variant.chart[2]);
    style.setProperty("--chart-color-4", variant.chart[3]);
    style.setProperty("--chart-color-5", variant.chart[4]);

    // ---- Particle tokens ----
    style.setProperty("--particle-primary",   variant.particles.colors[0]);
    style.setProperty("--particle-secondary", variant.particles.colors[1]);
    style.setProperty("--particle-tertiary",  variant.particles.colors[2]);
    style.setProperty("--particle-opacity",   String(variant.particles.opacity));

    // ---- Glass tokens ----
    // When glass is enabled: use theme's blur value + transparent glass tint.
    // When glass is disabled: set blur to 0 and use solid card surface.
    const glassBlur   = glass ? variant.glass.blur        : 0;
    const glassTint   = glass ? variant.glass.tint        : variant.colors.card;
    const glassAlpha  = glass ? variant.glass.borderAlpha : 0;
    const glassOpacity = glass ? variant.glass.minOpacity : 1.0;

    style.setProperty("--glass-tint",         glassTint);
    style.setProperty("--glass-blur",         `${glassBlur}px`);
    style.setProperty("--glass-border-alpha", String(glassAlpha));
    style.setProperty("--glass-min-opacity",  String(glassOpacity));
    style.setProperty("--glass-transparency", String(glassOpacity));
    // Expose raw glass enabled state for CSS consumers
    style.setProperty("--glass-enabled", glass ? "1" : "0");

    // ---- Glow tokens ----
    style.setProperty("--glow-color",   variant.glow.color);
    style.setProperty("--glow-opacity", String(variant.glow.opacity));
    style.setProperty("--glow-radius",  `${variant.glow.radius}px`);

    // ---- Shimmer tokens ----
    style.setProperty("--shimmer-color", variant.shimmerColor);
    style.setProperty("--shimmer-speed", shared.shimmer.speed);

    // ---- Scroll / focus / skeleton tokens ----
    style.setProperty("--scrollbar-thumb",  hexToRgba(variant.colors.accent, 0.20));
    style.setProperty("--focus-ring",       hexToRgba(variant.colors.accent, 0.60));
    style.setProperty("--skeleton-shimmer", hexToRgba(variant.colors.accent, 0.05));

    // ---- Legacy surface aliases (for widgets not yet on new tokens) ----
    style.setProperty("--color-surface-base",     variant.colors.base);
    style.setProperty("--color-surface-card",     variant.colors.card);

    // Compute elevated as card lightened by ~5 L* units
    const cardR = parseInt(variant.colors.card.slice(1, 3), 16);
    const cardG = parseInt(variant.colors.card.slice(3, 5), 16);
    const cardB = parseInt(variant.colors.card.slice(5, 7), 16);
    const bump = 12;
    const elevatedHex =
      `#${Math.min(255, cardR + bump).toString(16).padStart(2, "0")}` +
      `${Math.min(255, cardG + bump).toString(16).padStart(2, "0")}` +
      `${Math.min(255, cardB + bump).toString(16).padStart(2, "0")}`;
    style.setProperty("--color-surface-elevated", elevatedHex);
    style.setProperty("--color-surface-floating", variant.colors.cardHover);
    style.setProperty("--color-surface-stripe",   hexToRgba(variant.colors.base, 0.50));
    style.setProperty("--color-surface-hover",    variant.colors.cardHover);
    style.setProperty("--color-surface-active",   variant.colors.cardHover);

    style.setProperty("--color-border-default",   variant.colors.border);
    style.setProperty("--color-border-subtle",    variant.colors.borderSubtle);
    style.setProperty("--color-border-strong",    variant.colors.border);

    style.setProperty("--color-text-primary",     variant.colors.text);
    style.setProperty("--color-text-disabled",    variant.colors.textDisabled);

    // Warning / ATM tokens (consistent across themes)
    style.setProperty("--color-atm-text",   variant.trading.warningText);
    style.setProperty("--color-atm-bg",     hexToRgba(variant.trading.warning, 0.08));
    style.setProperty("--color-atm-border", hexToRgba(variant.trading.warning, 0.30));
    style.setProperty("--color-itm-text",   variant.trading.profitText);
    style.setProperty("--color-otm-text",   variant.trading.warningText);

    // ---- Toggle <html class="dark"> for shadcn/ui dark-mode HSL tokens ----
    if (resolvedMode === "dark") {
      root.classList.add("dark");
    } else {
      root.classList.remove("dark");
    }
    // Also set a data attribute for CSS selectors
    root.dataset.mode = resolvedMode;

    // ---- Body background (prevent white flash) ----
    document.body.style.backgroundColor = variant.colors.base;
    document.body.style.color = variant.colors.text;

    // ---- Shadow scale (mode-aware) ----
    if (resolvedMode === "light") {
      style.setProperty("--shadow-raised",   "0 1px 3px rgba(0,0,0,0.08)");
      style.setProperty("--shadow-elevated", "0 4px 12px rgba(0,0,0,0.12)");
      style.setProperty("--shadow-floating", "0 8px 24px rgba(0,0,0,0.16)");
    } else {
      style.setProperty("--shadow-raised",   "none");
      style.setProperty("--shadow-elevated", "0 4px 16px rgba(0,0,0,0.4)");
      style.setProperty("--shadow-floating", "0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05)");
    }

    // ---- shadcn/ui HSL tokens ----
    const accentHsl = hexToHslString(variant.colors.accent);
    style.setProperty("--primary", accentHsl);
    style.setProperty("--ring",    accentHsl);

    if (resolvedMode === "light") {
      style.setProperty("--background",         "0 0% 98%");
      style.setProperty("--foreground",         "240 10% 10%");
      style.setProperty("--card",               "0 0% 100%");
      style.setProperty("--card-foreground",    "240 10% 10%");
      style.setProperty("--popover",            "0 0% 98%");
      style.setProperty("--popover-foreground", "240 10% 10%");
      style.setProperty("--muted",              "240 5% 94%");
      style.setProperty("--muted-foreground",   "240 4% 46%");
      style.setProperty("--border",             "240 6% 90%");
      style.setProperty("--input",              "240 6% 90%");
    } else {
      style.setProperty("--background",         "240 10% 3.9%");
      style.setProperty("--foreground",         "240 5% 89%");
      style.setProperty("--card",               "240 8% 8.5%");
      style.setProperty("--card-foreground",    "240 5% 89%");
      style.setProperty("--popover",            "240 8% 11%");
      style.setProperty("--popover-foreground", "240 5% 89%");
      style.setProperty("--muted",              "240 5% 15%");
      style.setProperty("--muted-foreground",   "240 4% 46%");
      style.setProperty("--border",             "240 8% 18%");
      style.setProperty("--input",              "240 8% 18%");
    }

    // ---- Background token ----
    style.setProperty("--theme-background", variant.colors.base);

    // ---- data-theme attribute ----
    root.setAttribute("data-theme", theme.id);

    // ---- Light / dark class for Tailwind and legacy CSS ----
    if (resolvedMode === "light") {
      root.classList.add("theme-light");
    } else {
      root.classList.remove("theme-light");
    }

    // Sync theme-<id> class for legacy CSS overrides
    const newClass = `theme-${theme.id}`;
    if (!root.classList.contains(newClass)) {
      root.classList.add(newClass);
    }
    root.classList.forEach((cls) => {
      if (cls.startsWith("theme-") && cls !== newClass && cls !== "theme-light") {
        root.classList.remove(cls);
      }
    });

    // ---- Reduce-motion class ----
    if (reduceMotion) {
      root.classList.add("reduce-motion");
    } else {
      root.classList.remove("reduce-motion");
    }
  },
});

// ---------------------------------------------------------------------------
// Store creation with persist + migration
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name:    "flinttrade-theme",
  version: 4,
  migrate: (persisted: unknown, version: number): Partial<ThemeState> => {
    const p = (persisted ?? {}) as Record<string, unknown>;

    // All versions < 4: map any legacy theme id → v4 canonical id
    const rawId = typeof p["activeThemeId"] === "string" ? p["activeThemeId"] : "graphite";
    const mapped = ALL_LEGACY_TO_V4[rawId];
    if (mapped) {
      p["activeThemeId"] = mapped;
    } else if (version < 4) {
      // Unknown id from an older version → default to graphite
      const validIds = new Set(["graphite", "midnight", "ember"]);
      if (!validIds.has(rawId)) {
        p["activeThemeId"] = "graphite";
      }
    }

    if (version < 4) {
      // Migrate glass from object to boolean (was GlassSettings { enabled, transparency, blur })
      const oldGlass = p["glass"];
      if (typeof oldGlass === "object" && oldGlass !== null) {
        const g = oldGlass as Record<string, unknown>;
        p["glass"] = typeof g["enabled"] === "boolean" ? g["enabled"] : true;
      } else if (typeof oldGlass !== "boolean") {
        p["glass"] = true;
      }

      // Remove legacy background settings field (no longer in ThemeState v4)
      delete p["background"];

      p["mode"]        = p["mode"] ?? "system";
      p["customThemes"] = Array.isArray(p["customThemes"]) ? p["customThemes"] : [];
      p["reduceMotion"] = typeof p["reduceMotion"] === "boolean" ? p["reduceMotion"] : false;
    }

    return p as Partial<ThemeState>;
  },
  onRehydrateStorage: () => (state) => {
    if (!state) return;
    // Re-attach system listener if mode is "system" after hydration
    if (state.mode === "system") {
      attachSystemListener(() => state.applyTheme());
    }
    // Apply theme immediately after hydration
    state.applyTheme();
  },
});

export const useThemeStore = import.meta.env.DEV
  ? create<ThemeState>()(devtools(persistedStore, { name: "theme" }))
  : create<ThemeState>()(persistedStore);
