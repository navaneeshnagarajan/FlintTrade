/**
 * themePresets.ts
 *
 * Canonical interface and 12 built-in theme presets for FlintTrade.
 * Colors map 1-to-1 with the CSS custom properties in index.css and the
 * theme CSS files under src/themes/. The applyTheme action in themeStore
 * writes these values directly to document.documentElement.style so the
 * entire token cascade picks them up instantly.
 *
 * Color naming conventions:
 *   background           → --color-surface-base
 *   backgroundSecondary  → --color-surface-stripe
 *   card                 → --color-surface-card
 *   cardHover            → --color-surface-hover
 *   border               → --color-border-default
 *   borderHover          → --color-border-strong
 *   textPrimary          → --color-text-primary
 *   textSecondary        → --color-text-secondary
 *   textMuted            → --color-text-muted
 *   accent               → drives --primary (HSL) via applyTheme mapping
 *   accentHover          → accent at ~10% darker
 *   accentMuted          → accent at 15% opacity (rgba)
 *   profit               → --color-profit
 *   loss                 → --color-loss
 *   warning              → --color-warning
 */

export interface FlintTradeTheme {
  id: string;
  name: string;
  mode: "dark" | "light";
  colors: {
    background: string;
    backgroundSecondary: string;
    card: string;
    cardHover: string;
    border: string;
    borderHover: string;
    textPrimary: string;
    textSecondary: string;
    textMuted: string;
    accent: string;
    accentHover: string;
    accentMuted: string;
    profit: string;
    loss: string;
    warning: string;
  };
  effects: {
    /** 0–100: percentage of transparency to apply on glass surfaces */
    transparency: number;
    /** backdrop-blur radius in pixels */
    blur: number;
    borderRadius: "none" | "sm" | "md" | "lg" | "xl";
  };
  background?: {
    type: "solid" | "gradient" | "image" | "pattern";
    value: string;
    overlay?: string;
  };
}

// ---------------------------------------------------------------------------
// 1. midnight (default) — deep navy-black, vivid blue accent
// ---------------------------------------------------------------------------
const midnight: FlintTradeTheme = {
  id: "midnight",
  name: "Midnight",
  mode: "dark",
  colors: {
    background: "#0a0a0f",
    backgroundSecondary: "#0e0e16",
    card: "#16161f",
    cardHover: "#24242e",
    border: "#2a2a3a",
    borderHover: "#3a3a4a",
    textPrimary: "#e4e4e7",
    textSecondary: "#8b8b95",
    textMuted: "#7e7e8a",
    accent: "#3b82f6",
    accentHover: "#2563eb",
    accentMuted: "rgba(59,130,246,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#0a0a0f",
  },
};

// ---------------------------------------------------------------------------
// 2. obsidian — near-black with cool-grey tint, indigo-purple accent
// ---------------------------------------------------------------------------
const obsidian: FlintTradeTheme = {
  id: "obsidian",
  name: "Obsidian",
  mode: "dark",
  colors: {
    background: "#0c0c14",
    backgroundSecondary: "#0c0c10",
    card: "#111114",
    cardHover: "#1f1f25",
    border: "#222228",
    borderHover: "#38383f",
    textPrimary: "#ebebef",
    textSecondary: "#9898a0",
    textMuted: "#6b6b75",
    accent: "#818cf8",
    accentHover: "#6366f1",
    accentMuted: "rgba(129,140,248,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#0c0c14",
  },
};

// ---------------------------------------------------------------------------
// 3. terminal-green — phosphor monitor feel, vivid green accent
// ---------------------------------------------------------------------------
const terminalGreen: FlintTradeTheme = {
  id: "terminal-green",
  name: "Terminal Green",
  mode: "dark",
  colors: {
    background: "#0a0f0a",
    backgroundSecondary: "#0e1613",
    card: "#131c19",
    cardHover: "#1f2e29",
    border: "#2a3d36",
    borderHover: "#3a5a4e",
    textPrimary: "#d4e8df",
    textSecondary: "#8aaa9a",
    textMuted: "#7da08e",
    accent: "#22c55e",
    accentHover: "#16a34a",
    accentMuted: "rgba(34,197,94,0.15)",
    profit: "#4ade80",
    loss: "#f87171",
    warning: "#fbbf24",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "sm",
  },
  background: {
    type: "solid",
    value: "#0a0f0a",
  },
};

// ---------------------------------------------------------------------------
// 4. ocean-blue — deep ocean tones, cyan accent
// ---------------------------------------------------------------------------
const oceanBlue: FlintTradeTheme = {
  id: "ocean-blue",
  name: "Ocean Blue",
  mode: "dark",
  colors: {
    background: "#0a0e14",
    backgroundSecondary: "#0d1218",
    card: "#131a24",
    cardHover: "#1f2c3a",
    border: "#223040",
    borderHover: "#325068",
    textPrimary: "#d4e4f0",
    textSecondary: "#7a98b0",
    textMuted: "#7a9ab0",
    accent: "#38bdf8",
    accentHover: "#0ea5e9",
    accentMuted: "rgba(56,189,248,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#0a0e14",
  },
};

// ---------------------------------------------------------------------------
// 5. light — clean daylight workspace, blue accent
// ---------------------------------------------------------------------------
const light: FlintTradeTheme = {
  id: "light",
  name: "Light",
  mode: "light",
  colors: {
    background: "#fafafa",
    backgroundSecondary: "#f6f6f8",
    card: "#ffffff",
    cardHover: "#e8e8ec",
    border: "#e4e4e7",
    borderHover: "#a1a1aa",
    textPrimary: "#18181b",
    textSecondary: "#52525b",
    textMuted: "#71717a",
    accent: "#2563eb",
    accentHover: "#1d4ed8",
    accentMuted: "rgba(37,99,235,0.12)",
    profit: "#16a34a",
    loss: "#dc2626",
    warning: "#d97706",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#fafafa",
  },
};

// ---------------------------------------------------------------------------
// 6. sunset — warm dark reds and oranges, orange accent
// ---------------------------------------------------------------------------
const sunset: FlintTradeTheme = {
  id: "sunset",
  name: "Sunset",
  mode: "dark",
  colors: {
    background: "#140a0a",
    backgroundSecondary: "#180d0c",
    card: "#1e1210",
    cardHover: "#2c1c18",
    border: "#3a2420",
    borderHover: "#5a3830",
    textPrimary: "#f0e0d8",
    textSecondary: "#b09088",
    textMuted: "#b09088",
    accent: "#f97316",
    accentHover: "#ea6c0a",
    accentMuted: "rgba(249,115,22,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#140a0a",
  },
};

// ---------------------------------------------------------------------------
// 7. arctic — crisp light greys with cool blue tones, blue accent
// ---------------------------------------------------------------------------
const arctic: FlintTradeTheme = {
  id: "arctic",
  name: "Arctic",
  mode: "light",
  colors: {
    background: "#f0f4f8",
    backgroundSecondary: "#e8edf2",
    card: "#ffffff",
    cardHover: "#dde4ec",
    border: "#c8d4de",
    borderHover: "#94a8bc",
    textPrimary: "#0f2132",
    textSecondary: "#4a637a",
    textMuted: "#6880a0",
    accent: "#0369a1",
    accentHover: "#0258880",
    accentMuted: "rgba(3,105,161,0.12)",
    profit: "#15803d",
    loss: "#b91c1c",
    warning: "#b45309",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "lg",
  },
  background: {
    type: "solid",
    value: "#f0f4f8",
  },
};

// ---------------------------------------------------------------------------
// 8. neon — cyberpunk-influenced dark, hot pink/magenta accent
// ---------------------------------------------------------------------------
const neon: FlintTradeTheme = {
  id: "neon",
  name: "Neon",
  mode: "dark",
  colors: {
    background: "#0a0a14",
    backgroundSecondary: "#0d0d18",
    card: "#12121e",
    cardHover: "#1e1e2e",
    border: "#2a2a42",
    borderHover: "#4a4a70",
    textPrimary: "#e8e0ff",
    textSecondary: "#9888cc",
    textMuted: "#9080cc",
    accent: "#e879f9",
    accentHover: "#d946ef",
    accentMuted: "rgba(232,121,249,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 10,
    blur: 8,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#0a0a14",
  },
};

// ---------------------------------------------------------------------------
// 9. forest — deep woodland greens, emerald accent
// ---------------------------------------------------------------------------
const forest: FlintTradeTheme = {
  id: "forest",
  name: "Forest",
  mode: "dark",
  colors: {
    background: "#0a0f0c",
    backgroundSecondary: "#0c1410",
    card: "#111a14",
    cardHover: "#1a2a1e",
    border: "#203828",
    borderHover: "#305840",
    textPrimary: "#d0e8d8",
    textSecondary: "#7aaa88",
    textMuted: "#78a688",
    accent: "#10b981",
    accentHover: "#059669",
    accentMuted: "rgba(16,185,129,0.15)",
    profit: "#34d399",
    loss: "#f87171",
    warning: "#fbbf24",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "md",
  },
  background: {
    type: "solid",
    value: "#0a0f0c",
  },
};

// ---------------------------------------------------------------------------
// 10. monochrome — pure greyscale, white accent
// ---------------------------------------------------------------------------
const monochrome: FlintTradeTheme = {
  id: "monochrome",
  name: "Monochrome",
  mode: "dark",
  colors: {
    background: "#0a0a0a",
    backgroundSecondary: "#0e0e0e",
    card: "#161616",
    cardHover: "#242424",
    border: "#2a2a2a",
    borderHover: "#404040",
    textPrimary: "#e8e8e8",
    textSecondary: "#8c8c8c",
    textMuted: "#6a6a6a",
    accent: "#d4d4d4",
    accentHover: "#f0f0f0",
    accentMuted: "rgba(212,212,212,0.15)",
    profit: "#22c55e",
    loss: "#ef4444",
    warning: "#eab308",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "none",
  },
  background: {
    type: "solid",
    value: "#0a0a0a",
  },
};

// ---------------------------------------------------------------------------
// 11. solarized-dark — Ethan Schoonover's dark palette, yellow-gold accent
// ---------------------------------------------------------------------------
const solarizedDark: FlintTradeTheme = {
  id: "solarized-dark",
  name: "Solarized Dark",
  mode: "dark",
  colors: {
    background: "#002b36",
    backgroundSecondary: "#00222c",
    card: "#073642",
    cardHover: "#094050",
    border: "#0a4a5a",
    borderHover: "#1a6070",
    textPrimary: "#eee8d5",
    textSecondary: "#93a1a1",
    textMuted: "#657b83",
    accent: "#b58900",
    accentHover: "#9a7500",
    accentMuted: "rgba(181,137,0,0.15)",
    profit: "#a3b900",
    loss: "#dc322f",
    warning: "#cb4b16",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "sm",
  },
  background: {
    type: "solid",
    value: "#002b36",
  },
};

// ---------------------------------------------------------------------------
// 12. solarized-light — Ethan Schoonover's light palette, yellow-gold accent
// ---------------------------------------------------------------------------
const solarizedLight: FlintTradeTheme = {
  id: "solarized-light",
  name: "Solarized Light",
  mode: "light",
  colors: {
    background: "#fdf6e3",
    backgroundSecondary: "#f5eed8",
    card: "#eee8d5",
    cardHover: "#ddd8c6",
    border: "#cdc8b8",
    borderHover: "#a8a090",
    textPrimary: "#073642",
    textSecondary: "#586e75",
    textMuted: "#657b83",
    accent: "#b58900",
    accentHover: "#9a7500",
    accentMuted: "rgba(181,137,0,0.15)",
    profit: "#859900",
    loss: "#dc322f",
    warning: "#cb4b16",
  },
  effects: {
    transparency: 0,
    blur: 0,
    borderRadius: "sm",
  },
  background: {
    type: "solid",
    value: "#fdf6e3",
  },
};

// ---------------------------------------------------------------------------
// Canonical registry — order matches the UI picker display order
// ---------------------------------------------------------------------------
export const BUILTIN_THEMES: readonly FlintTradeTheme[] = [
  midnight,
  obsidian,
  terminalGreen,
  oceanBlue,
  light,
  sunset,
  arctic,
  neon,
  forest,
  monochrome,
  solarizedDark,
  solarizedLight,
] as const;

/** Look up a built-in theme by id. Returns undefined if not found. */
export function findBuiltinTheme(id: string): FlintTradeTheme | undefined {
  return BUILTIN_THEMES.find((t) => t.id === id);
}
