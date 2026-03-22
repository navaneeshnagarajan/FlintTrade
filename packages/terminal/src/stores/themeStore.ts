/**
 * themeStore.ts
 *
 * Zustand v5 store for FlintTrade's theme system.
 * Persists to localStorage under "flinttrade-theme".
 *
 * Responsibilities:
 *   - Track which theme is active (built-in or custom)
 *   - Store user-authored custom themes
 *   - Persist glass-morphism and background overrides
 *   - Write CSS custom properties to document.documentElement on demand
 *
 * This store is intentionally separate from settingsStore so the theme
 * system can evolve independently without touching the settings migration
 * chain. The settingsStore.theme field (a ThemeId string) remains the
 * canonical "last selected" preference; this store drives the live DOM.
 */

import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import {
  BUILTIN_THEMES,
  findBuiltinTheme,
} from "@/components/theme/themePresets";
import type { FlintTradeTheme } from "@/components/theme/themePresets";

// ---------------------------------------------------------------------------
// Border-radius map — converts the enum value to a rem token
// ---------------------------------------------------------------------------
const RADIUS_MAP: Record<FlintTradeTheme["effects"]["borderRadius"], string> = {
  none: "0rem",
  sm: "0.25rem",
  md: "0.5rem",
  lg: "0.75rem",
  xl: "1rem",
};

// ---------------------------------------------------------------------------
// State and action types
// ---------------------------------------------------------------------------

interface GlassSettings {
  enabled: boolean;
  /** 0–100: % of the theme's base transparency to apply */
  transparency: number;
  /** backdrop-blur radius in pixels */
  blur: number;
}

interface BackgroundSettings {
  type: string;
  value: string;
  overlay: string;
}

export interface ThemeState {
  activeThemeId: string;
  customThemes: FlintTradeTheme[];
  glass: GlassSettings;
  background: BackgroundSettings;

  // --- Actions ---
  setTheme: (id: string) => void;
  addCustomTheme: (theme: FlintTradeTheme) => void;
  removeCustomTheme: (id: string) => void;
  setGlass: (glass: Partial<GlassSettings>) => void;
  setBackground: (bg: Partial<BackgroundSettings>) => void;
  getActiveTheme: () => FlintTradeTheme;
  applyTheme: () => void;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<
  ThemeState,
  [["zustand/persist", unknown]]
> = (set, get) => ({
  activeThemeId: "midnight",
  customThemes: [],
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
    // Apply immediately after updating state.
    // We call get() here so applyTheme always reads the freshest state.
    get().applyTheme();
  },

  // --- addCustomTheme ---
  addCustomTheme: (theme) => {
    set((state: ThemeState) => ({
      customThemes: [
        ...state.customThemes.filter((t: FlintTradeTheme) => t.id !== theme.id),
        theme,
      ],
    }));
  },

  // --- removeCustomTheme ---
  removeCustomTheme: (id) => {
    set((state: ThemeState) => ({
      customThemes: state.customThemes.filter(
        (t: FlintTradeTheme) => t.id !== id,
      ),
      // Fall back to midnight if we just removed the active theme
      activeThemeId:
        state.activeThemeId === id ? "midnight" : state.activeThemeId,
    }));
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

    const builtin = findBuiltinTheme(activeThemeId);
    if (builtin) return builtin;

    // Fallback — midnight is always guaranteed to exist
    return BUILTIN_THEMES[0];
  },

  // --- applyTheme ---
  applyTheme: () => {
    const { glass, background, getActiveTheme } = get();
    const theme = getActiveTheme();
    const root = document.documentElement;
    const style = root.style;

    // -- Surface / structural colors --
    style.setProperty("--color-surface-base", theme.colors.background);
    style.setProperty(
      "--color-surface-stripe",
      theme.colors.backgroundSecondary,
    );
    style.setProperty("--color-surface-card", theme.colors.card);
    style.setProperty("--color-surface-elevated", theme.colors.card);
    style.setProperty("--color-surface-hover", theme.colors.cardHover);
    style.setProperty("--color-surface-active", theme.colors.cardHover);

    // -- Border colors --
    style.setProperty("--color-border-default", theme.colors.border);
    style.setProperty("--color-border-subtle", theme.colors.border);
    style.setProperty("--color-border-strong", theme.colors.borderHover);

    // -- Text colors --
    style.setProperty("--color-text-primary", theme.colors.textPrimary);
    style.setProperty("--color-text-secondary", theme.colors.textSecondary);
    style.setProperty("--color-text-muted", theme.colors.textMuted);
    style.setProperty("--color-text-disabled", theme.colors.textMuted);

    // -- Trading semantic colors --
    style.setProperty("--color-profit", theme.colors.profit);
    style.setProperty("--color-loss", theme.colors.loss);
    style.setProperty("--color-warning", theme.colors.warning);

    // Derived bullish / bearish / atm tokens using the theme's profit/loss/warning
    style.setProperty(
      "--color-bullish-text",
      theme.colors.profit,
    );
    style.setProperty(
      "--color-bullish-bg",
      hexToRgba(theme.colors.profit, 0.1),
    );
    style.setProperty(
      "--color-bullish-border",
      hexToRgba(theme.colors.profit, 0.3),
    );
    style.setProperty("--color-bearish-text", theme.colors.loss);
    style.setProperty(
      "--color-bearish-bg",
      hexToRgba(theme.colors.loss, 0.1),
    );
    style.setProperty(
      "--color-bearish-border",
      hexToRgba(theme.colors.loss, 0.3),
    );
    style.setProperty("--color-atm-text", theme.colors.warning);
    style.setProperty(
      "--color-atm-bg",
      hexToRgba(theme.colors.warning, 0.08),
    );
    style.setProperty(
      "--color-atm-border",
      hexToRgba(theme.colors.warning, 0.3),
    );
    style.setProperty("--color-itm-text", theme.colors.profit);
    style.setProperty("--color-otm-text", theme.colors.warning);

    // -- Neutral token (accent-based) --
    style.setProperty("--color-neutral-text", theme.colors.accent);
    style.setProperty(
      "--color-neutral-bg",
      hexToRgba(theme.colors.accent, 0.1),
    );
    style.setProperty(
      "--color-neutral-border",
      hexToRgba(theme.colors.accent, 0.3),
    );

    // -- shadcn/ui HSL tokens (primary, ring) --
    const accentHsl = hexToHslString(theme.colors.accent);
    style.setProperty("--primary", accentHsl);
    style.setProperty("--ring", accentHsl);

    // Dark/light base tokens for shadcn/ui
    if (theme.mode === "light") {
      style.setProperty("--background", "0 0% 98%");
      style.setProperty("--foreground", "240 10% 10%");
      style.setProperty("--card", "0 0% 100%");
      style.setProperty("--card-foreground", "240 10% 10%");
      style.setProperty("--popover", "0 0% 98%");
      style.setProperty("--popover-foreground", "240 10% 10%");
      style.setProperty("--muted", "240 5% 94%");
      style.setProperty("--muted-foreground", "240 4% 46%");
      style.setProperty("--border", "240 6% 90%");
      style.setProperty("--input", "240 6% 90%");
    } else {
      style.setProperty("--background", "240 10% 3.9%");
      style.setProperty("--foreground", "240 5% 89%");
      style.setProperty("--card", "240 8% 8.5%");
      style.setProperty("--card-foreground", "240 5% 89%");
      style.setProperty("--popover", "240 8% 11%");
      style.setProperty("--popover-foreground", "240 5% 89%");
      style.setProperty("--muted", "240 5% 15%");
      style.setProperty("--muted-foreground", "240 4% 46%");
      style.setProperty("--border", "240 8% 18%");
      style.setProperty("--input", "240 8% 18%");
    }

    // -- Border radius --
    style.setProperty("--radius", RADIUS_MAP[theme.effects.borderRadius]);

    // -- Glass overrides (merge store override on top of theme defaults) --
    const effectiveTransparency = glass.enabled
      ? glass.transparency
      : theme.effects.transparency;
    const effectiveBlur = glass.enabled ? glass.blur : theme.effects.blur;
    style.setProperty("--glass-transparency", String(effectiveTransparency));
    style.setProperty("--glass-blur", `${effectiveBlur}px`);

    // -- Background override --
    const bgValue =
      background.value !== ""
        ? background.value
        : theme.background?.value ?? theme.colors.background;
    style.setProperty("--theme-background", bgValue);

    // -- data-theme attribute (used for Dockview light overrides in index.css) --
    root.setAttribute("data-theme", theme.id);

    // Add/remove theme-light class so the existing CSS overrides in index.css
    // and the theme/*.css files continue to work alongside the JS-driven tokens.
    if (theme.mode === "light") {
      root.classList.add("theme-light");
    } else {
      root.classList.remove("theme-light");
    }

    // Sync theme class for the legacy CSS theme files that target
    // html.theme-<id> selectors (obsidian.css, terminal-green.css, etc.).
    // We add the new class first then remove stale ones to avoid a flash.
    const newClass = `theme-${theme.id}`;
    if (!root.classList.contains(newClass)) {
      root.classList.add(newClass);
    }
    root.classList.forEach((cls) => {
      if (cls.startsWith("theme-") && cls !== newClass) {
        root.classList.remove(cls);
      }
    });
  },
});

// ---------------------------------------------------------------------------
// Store creation
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade-theme",
  version: 1,
  migrate: (persistedState: unknown, _version: number): ThemeState => {
    // For v1 there is nothing to migrate yet; return as-is.
    return persistedState as ThemeState;
  },
});

export const useThemeStore = import.meta.env.DEV
  ? create<ThemeState>()(devtools(persistedStore, { name: "theme" }))
  : create<ThemeState>()(persistedStore);

// ---------------------------------------------------------------------------
// Utility helpers (module-private)
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
  if (cleaned.length !== 6) return "217 91% 60%"; // fallback to midnight accent
  const r = parseInt(cleaned.slice(0, 2), 16) / 255;
  const g = parseInt(cleaned.slice(2, 4), 16) / 255;
  const b = parseInt(cleaned.slice(4, 6), 16) / 255;
  if (isNaN(r) || isNaN(g) || isNaN(b)) return "217 91% 60%";

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
