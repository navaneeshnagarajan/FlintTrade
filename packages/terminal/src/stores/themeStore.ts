/**
 * themeStore.ts
 *
 * Zustand v5 store for FlintTrade's CinematicTheme system.
 * Persists to localStorage under "flinttrade-theme" (version 3).
 *
 * Responsibilities:
 *   - Track active CinematicTheme id
 *   - Track color mode: "dark" | "light" | "system"
 *   - Store user-authored custom CinematicThemes
 *   - Persist glass-morphism and background overrides
 *   - Track reduceMotion preference
 *   - Write 50+ CSS custom properties to document.documentElement on demand
 *
 * Persist version history:
 *   v1 — FlintTradeTheme (12 presets, single mode per theme)
 *   v2 — CinematicTheme (6 presets, dark + light variants, mode field)
 *   v3 — Pruned to 6 canonical themes; removed emerald-night, ocean-depth,
 *         solar-flare, neon-pulse, blood-moon. Default is now "graphite".
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import {
  CINEMATIC_THEMES,
  findCinematicTheme,
  getResolvedVariant,
} from "@/lib/cinematicThemes";
import type { CinematicTheme, ColorMode } from "@/lib/cinematicThemes";

// ---------------------------------------------------------------------------
// Sub-interfaces
// ---------------------------------------------------------------------------

export interface GlassSettings {
  enabled: boolean;
  /** 0–100: percentage of transparency to apply on glass surfaces */
  transparency: number;
  /** backdrop-blur radius in pixels */
  blur: number;
}

export interface BackgroundSettings {
  type: string;
  value: string;
  overlay: string;
}

// ---------------------------------------------------------------------------
// ThemeState
// ---------------------------------------------------------------------------

export interface ThemeState {
  activeThemeId: string;
  mode: ColorMode;
  customThemes: CinematicTheme[];
  glass: GlassSettings;
  background: BackgroundSettings;
  reduceMotion: boolean;

  // --- Actions ---
  setTheme: (id: string) => void;
  setMode: (mode: ColorMode) => void;
  setReduceMotion: (v: boolean) => void;
  addCustomTheme: (theme: CinematicTheme) => void;
  removeCustomTheme: (id: string) => void;
  setGlass: (glass: Partial<GlassSettings>) => void;
  setBackground: (bg: Partial<BackgroundSettings>) => void;
  getActiveTheme: () => CinematicTheme;
  getResolvedMode: () => "dark" | "light";
  applyTheme: () => void;
}

// ---------------------------------------------------------------------------
// Migration map: old FlintTradeTheme IDs → new CinematicTheme IDs
// ---------------------------------------------------------------------------

const V1_THEME_MAP: Record<string, string> = {
  midnight:         "midnight",
  obsidian:         "emerald-night",
  "terminal-green": "emerald-night",
  "ocean-blue":     "ocean-depth",
  light:            "arctic-frost",
  sunset:           "solar-flare",
  arctic:           "arctic-frost",
  neon:             "neon-pulse",
  forest:           "emerald-night",
  monochrome:       "monochrome",
  "solarized-dark": "solarized-dark",
  "solarized-light":"solarized-dark",
};

// ---------------------------------------------------------------------------
// Migration map: deprecated v2 CinematicTheme IDs → canonical v3 theme IDs
// ---------------------------------------------------------------------------

const V2_TO_V3_THEME_MAP: Record<string, string> = {
  "emerald-night": "graphite",
  "ocean-depth":   "midnight",
  "solar-flare":   "graphite",
  "neon-pulse":    "graphite",
  "blood-moon":    "graphite",
};

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Convert a 6-digit hex color to an rgba() string.
 * Handles both "#rrggbb" and "rrggbb" formats.
 * Non-hex or shorthand values are returned as-is.
 */
function hexToRgba(hex: string, alpha: number): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) return hex;
  const r = parseInt(cleaned.slice(0, 2), 16);
  const g = parseInt(cleaned.slice(2, 4), 16);
  const b = parseInt(cleaned.slice(4, 6), 16);
  if (isNaN(r) || isNaN(g) || isNaN(b)) return hex;
  return `rgba(${r},${g},${b},${alpha})`;
}

/**
 * Convert a 6-digit hex color to an "H S% L%" string compatible with
 * shadcn/ui's CSS variable convention (no `hsl()` wrapper).
 */
function hexToHslString(hex: string): string {
  const cleaned = hex.startsWith("#") ? hex.slice(1) : hex;
  if (cleaned.length !== 6) return "233 70% 70%"; // fallback to graphite accent
  const r = parseInt(cleaned.slice(0, 2), 16) / 255;
  const g = parseInt(cleaned.slice(2, 4), 16) / 255;
  const b = parseInt(cleaned.slice(4, 6), 16) / 255;
  if (isNaN(r) || isNaN(g) || isNaN(b)) return "233 70% 70%";

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
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<
  ThemeState,
  [["zustand/persist", unknown]]
> = (set, get) => ({
  activeThemeId: "graphite",
  mode: "system",
  customThemes: [],
  reduceMotion: false,
  glass: {
    enabled: false,
    transparency: 0,
    blur: 0,
  },
  background: {
    type: "solid",
    value: "",
    overlay: "",
  },

  // --- setTheme ---
  setTheme: (id) => {
    set({ activeThemeId: id });
    get().applyTheme();
  },

  // --- setMode ---
  setMode: (mode) => {
    set({ mode });
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
        ...state.customThemes.filter((t: CinematicTheme) => t.id !== theme.id),
        theme,
      ],
    }));
  },

  // --- removeCustomTheme ---
  removeCustomTheme: (id) => {
    set((state: ThemeState) => ({
      customThemes: state.customThemes.filter(
        (t: CinematicTheme) => t.id !== id,
      ),
      activeThemeId:
        state.activeThemeId === id ? "graphite" : state.activeThemeId,
    }));
    get().applyTheme();
  },

  // --- setGlass ---
  setGlass: (glass) => {
    set((state: ThemeState) => ({ glass: { ...state.glass, ...glass } }));
    get().applyTheme();
  },

  // --- setBackground ---
  setBackground: (bg) => {
    set((state: ThemeState) => ({
      background: { ...state.background, ...bg },
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

    // Fallback — graphite (index 0) is always guaranteed to exist in v3
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

    const { glass, background, getActiveTheme, getResolvedMode, reduceMotion } = get();
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

    // ---- Text tokens ----
    style.setProperty("--color-text",           variant.colors.text);
    style.setProperty("--color-text-muted",     variant.colors.textMuted);
    style.setProperty("--color-text-secondary", variant.colors.textSecondary);

    // ---- Accent tokens ----
    style.setProperty("--color-accent",      variant.colors.accent);
    style.setProperty("--color-accent-text", variant.colors.accentText);

    // ---- Fixed trading semantic colors ----
    style.setProperty("--color-profit", shared.profit);
    style.setProperty("--color-loss",   shared.loss);

    // Derived bullish / bearish tokens
    // In light mode, green-500 (#22c55e) on white is only 3.30:1 — fails WCAG AA.
    // Use green-700 (#15803d) on light surfaces for 4.55:1 compliance.
    const bullishText = resolvedMode === "light" ? "#15803d" : shared.profit;
    style.setProperty("--color-bullish-text",   bullishText);
    style.setProperty("--color-bullish-bg",     hexToRgba(shared.profit, 0.1));
    style.setProperty("--color-bullish-border", hexToRgba(shared.profit, 0.3));
    style.setProperty("--color-bearish-text",   shared.loss);
    style.setProperty("--color-bearish-bg",     hexToRgba(shared.loss,   0.1));
    style.setProperty("--color-bearish-border", hexToRgba(shared.loss,   0.3));

    // Neutral accent-based tokens
    style.setProperty("--color-neutral-text",   variant.colors.accent);
    style.setProperty("--color-neutral-bg",     hexToRgba(variant.colors.accent, 0.1));
    style.setProperty("--color-neutral-border", hexToRgba(variant.colors.accent, 0.3));

    // ---- Particle tokens ----
    style.setProperty("--particle-primary",   variant.particles.colors[0]);
    style.setProperty("--particle-secondary", variant.particles.colors[1]);
    style.setProperty("--particle-tertiary",  variant.particles.colors[2]);
    style.setProperty("--particle-opacity",   String(variant.particles.opacity));

    // ---- Glass tokens ----
    const effectiveBlur = glass.enabled ? glass.blur : variant.glass.blur;
    const effectiveTransparency = glass.enabled
      ? glass.transparency / 100
      : variant.glass.minOpacity;

    style.setProperty("--glass-tint",         variant.glass.tint);
    style.setProperty("--glass-blur",         `${effectiveBlur}px`);
    style.setProperty("--glass-border-alpha", String(variant.glass.borderAlpha));
    style.setProperty("--glass-min-opacity",  String(variant.glass.minOpacity));
    style.setProperty("--glass-transparency", String(effectiveTransparency));

    // ---- Glow tokens ----
    style.setProperty("--glow-color",   variant.glow.color);
    style.setProperty("--glow-opacity", String(variant.glow.opacity));
    style.setProperty("--glow-radius",  `${variant.glow.radius}px`);

    // ---- Shimmer tokens ----
    style.setProperty("--shimmer-color", variant.shimmerColor);
    style.setProperty("--shimmer-speed", shared.shimmer.speed);

    // ---- Chart tokens ----
    style.setProperty("--chart-up",   shared.profit);
    style.setProperty("--chart-down", shared.loss);
    style.setProperty("--chart-grid", hexToRgba(variant.colors.border, 0.6));
    style.setProperty("--chart-bg",   variant.colors.base);
    style.setProperty("--chart-text", variant.colors.textMuted);

    // ---- Scroll / focus / skeleton tokens ----
    style.setProperty("--scrollbar-thumb",   hexToRgba(variant.colors.accent, 0.2));
    style.setProperty("--focus-ring",        hexToRgba(variant.colors.accent, 0.6));
    style.setProperty("--skeleton-shimmer",  hexToRgba(variant.colors.accent, 0.05));

    // ---- Legacy surface aliases (for widgets not yet on new tokens) ----
    style.setProperty("--color-surface-base",     variant.colors.base);
    style.setProperty("--color-surface-card",     variant.colors.card);

    // Compute elevated as card lightened by ~5 L* units (bump each channel by 12)
    const cardR = parseInt(variant.colors.card.slice(1, 3), 16);
    const cardG = parseInt(variant.colors.card.slice(3, 5), 16);
    const cardB = parseInt(variant.colors.card.slice(5, 7), 16);
    const bump = 12; // ~5 L* units in sRGB space
    const elevatedHex =
      `#${Math.min(255, cardR + bump).toString(16).padStart(2, "0")}` +
      `${Math.min(255, cardG + bump).toString(16).padStart(2, "0")}` +
      `${Math.min(255, cardB + bump).toString(16).padStart(2, "0")}`;
    style.setProperty("--color-surface-elevated", elevatedHex);
    style.setProperty("--color-surface-stripe",   hexToRgba(variant.colors.base, 0.5));

    style.setProperty("--color-surface-hover",    variant.colors.cardHover);
    style.setProperty("--color-surface-active",   variant.colors.cardHover);
    style.setProperty("--color-border-default",   variant.colors.border);
    style.setProperty("--color-border-subtle",    variant.colors.border);
    style.setProperty("--color-border-strong",    variant.colors.border);
    style.setProperty("--color-text-primary",     variant.colors.text);
    style.setProperty("--color-text-disabled",    variant.colors.textMuted);
    style.setProperty("--color-warning",          "#eab308");
    style.setProperty("--color-atm-text",         "#eab308");
    style.setProperty("--color-atm-bg",           hexToRgba("#eab308", 0.08));
    style.setProperty("--color-atm-border",       hexToRgba("#eab308", 0.3));
    style.setProperty("--color-itm-text",         shared.profit);
    style.setProperty("--color-otm-text",         "#eab308");

    // ---- Surface hierarchy tokens (v0.3.0) ----
    // Floating layer sits one step above elevated — use cardHover as its base
    // so it remains visually distinct even in themes without a dedicated floating color.
    style.setProperty("--color-surface-floating", variant.colors.cardHover);

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
      style.setProperty("--background",          "0 0% 98%");
      style.setProperty("--foreground",          "240 10% 10%");
      style.setProperty("--card",                "0 0% 100%");
      style.setProperty("--card-foreground",     "240 10% 10%");
      style.setProperty("--popover",             "0 0% 98%");
      style.setProperty("--popover-foreground",  "240 10% 10%");
      style.setProperty("--muted",               "240 5% 94%");
      style.setProperty("--muted-foreground",    "240 4% 46%");
      style.setProperty("--border",              "240 6% 90%");
      style.setProperty("--input",               "240 6% 90%");
    } else {
      style.setProperty("--background",          "240 10% 3.9%");
      style.setProperty("--foreground",          "240 5% 89%");
      style.setProperty("--card",                "240 8% 8.5%");
      style.setProperty("--card-foreground",     "240 5% 89%");
      style.setProperty("--popover",             "240 8% 11%");
      style.setProperty("--popover-foreground",  "240 5% 89%");
      style.setProperty("--muted",               "240 5% 15%");
      style.setProperty("--muted-foreground",    "240 4% 46%");
      style.setProperty("--border",              "240 8% 18%");
      style.setProperty("--input",               "240 8% 18%");
    }

    // ---- Background override ----
    const bgValue =
      background.value !== ""
        ? background.value
        : variant.colors.base;
    style.setProperty("--theme-background", bgValue);

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
  name: "flinttrade-theme",
  version: 3,
  migrate: (persisted: unknown, version: number): Partial<ThemeState> => {
    const p = (persisted ?? {}) as Record<string, unknown>;

    if (version < 2) {
      const oldId = typeof p["activeThemeId"] === "string" ? p["activeThemeId"] : "midnight";
      p["activeThemeId"] = V1_THEME_MAP[oldId] ?? "graphite";
      p["mode"] = "system";
      p["customThemes"] = [];
      p["reduceMotion"] = false;
    }

    if (version < 3) {
      const currentId = typeof p["activeThemeId"] === "string" ? p["activeThemeId"] : "graphite";
      const mapped = V2_TO_V3_THEME_MAP[currentId];
      if (mapped) {
        p["activeThemeId"] = mapped;
      }
    }

    return p as Partial<ThemeState>;
  },
});

export const useThemeStore = import.meta.env.DEV
  ? create<ThemeState>()(devtools(persistedStore, { name: "theme" }))
  : create<ThemeState>()(persistedStore);
