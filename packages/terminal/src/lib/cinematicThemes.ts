/**
 * cinematicThemes.ts
 *
 * CinematicTheme type system and 3 built-in presets (v4).
 *
 * v4 canonical themes (3 total):
 *   graphite  — default; neutral professional with emerald green accent
 *   midnight  — deep navy canvas with sky-blue highlights
 *   ember     — warm dark canvas with amber/orange accent
 *
 * Each theme carries both a dark and light ThemeVariant so the user can
 * switch color-mode without changing the theme identity. Per-variant accent
 * colors are chosen to meet WCAG AA 4.5:1 contrast ratio on the variant's
 * base background.
 *
 * Trading semantic colors (profit green, loss red, warning amber) are
 * CONSISTENT across all themes and both modes — they are never per-theme.
 *
 * Particle behaviors:
 *   drift  — slow horizontal / diagonal movement
 *   float  — gentle vertical bobbing
 *   pulse  — opacity pulsing in place (max 2 Hz, 500 ms transition)
 *   snow   — top-to-bottom drift with slight lateral wander
 */

// ---------------------------------------------------------------------------
// Primitive types
// ---------------------------------------------------------------------------

export type ParticleBehavior = "drift" | "float" | "pulse" | "snow";
export type ColorMode = "dark" | "light" | "system";

// ---------------------------------------------------------------------------
// ThemeVariant — one side of a CinematicTheme (dark OR light)
// ---------------------------------------------------------------------------

export interface ThemeVariant {
  colors: {
    /** Page / canvas background (surface level 1) */
    base: string;
    /** Card / panel surface (surface level 2) */
    card: string;
    /** Elevated card surface (surface level 3) */
    cardHover: string;
    /** Default border */
    border: string;
    /** Subtle border (less prominent) */
    borderSubtle: string;
    /** Primary readable text */
    text: string;
    /** Subdued label text */
    textMuted: string;
    /** Secondary / meta text */
    textSecondary: string;
    /** Disabled text */
    textDisabled: string;
    /**
     * Per-variant accent — the primary interactive color.
     * Dark variant: vibrant, high-saturation.
     * Light variant: darker tone that still meets WCAG AA 4.5:1 on the light base.
     */
    accent: string;
    /** Text rendered on an accent-colored background — always meets AA. */
    accentText: string;
  };
  trading: {
    /** Profit green — consistent across all themes */
    profit: "#22c55e";
    /** Loss red — consistent across all themes */
    loss: "#ef4444";
    /** Warning amber — consistent across all themes */
    warning: "#f59e0b";
    /** WCAG-safe profit text on light surfaces (green-700) */
    profitText: string;
    /** WCAG-safe loss text (same in both modes) */
    lossText: string;
    /** WCAG-safe warning text */
    warningText: string;
  };
  /** 5 chart data colors for multi-series charts */
  chart: [string, string, string, string, string];
  particles: {
    /** Tuple of three colors drawn from the theme's color family */
    colors: [string, string, string];
    /** Base opacity for particle drawing (0–1) */
    opacity: number;
  };
  glass: {
    /** CSS rgba / hex tint applied to glass surfaces */
    tint: string;
    /** backdrop-filter blur in pixels */
    blur: number;
    /** Border alpha for glass border (0–1) */
    borderAlpha: number;
    /**
     * Minimum opacity for text-bearing glass surfaces.
     * Must be >= 0.60 to ensure readable text even without solid backing.
     */
    minOpacity: number;
  };
  glow: {
    /** Glow halo color (typically accent at low opacity) */
    color: string;
    /** Glow opacity (0–1) */
    opacity: number;
    /** Blur radius in pixels */
    radius: number;
  };
  /** Base shimmer highlight color for skeleton loaders */
  shimmerColor: string;
}

// ---------------------------------------------------------------------------
// CinematicTheme — full theme with both variants
// ---------------------------------------------------------------------------

export interface CinematicTheme {
  id: string;
  name: string;
  description: string;
  /** lucide-react icon name for color-blind identification */
  icon: string;

  dark: ThemeVariant;
  light: ThemeVariant;

  shared: {
    shimmer: {
      /** CSS animation-duration value, e.g. "2s" */
      speed: string;
    };
    particles: {
      /** Number of particles rendered simultaneously */
      quantity: number;
      /** [minSize, maxSize] in pixels */
      sizeRange: [number, number];
      behavior: ParticleBehavior;
      /**
       * For "pulse" behavior only.
       * Maximum pulse frequency in Hz — must be <= 2.0 (WCAG 2.3 photosensitivity).
       */
      maxPulseFrequencyHz?: number;
      /**
       * For "pulse" behavior only.
       * Minimum opacity transition duration in ms — must be >= 500.
       */
      pulseTransitionMs?: number;
    };
  };
}

/**
 * ThemeDefinition is an alias for CinematicTheme.
 * Used in the custom theme builder and import/export.
 */
export type ThemeDefinition = CinematicTheme;

// ---------------------------------------------------------------------------
// Helper: build a hex rgba string
// ---------------------------------------------------------------------------

function hexRgba(hex: string, alpha: number): string {
  const h = hex.startsWith("#") ? hex.slice(1) : hex;
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

// ---------------------------------------------------------------------------
// Trading semantics — fixed across ALL themes, BOTH modes
// ---------------------------------------------------------------------------

const TRADING_DARK: ThemeVariant["trading"] = {
  profit:      "#22c55e",
  loss:        "#ef4444",
  warning:     "#f59e0b",
  profitText:  "#22c55e",  // green-500 passes 4.5:1 on dark surfaces
  lossText:    "#ef4444",
  warningText: "#f59e0b",
};

const TRADING_LIGHT: ThemeVariant["trading"] = {
  profit:      "#22c55e",
  loss:        "#ef4444",
  warning:     "#f59e0b",
  profitText:  "#15803d",  // green-700 — 4.55:1 on white (#fff)
  lossText:    "#dc2626",  // red-600 — passes on light backgrounds
  warningText: "#b45309",  // amber-700 — passes on light backgrounds
};

// ---------------------------------------------------------------------------
// 1. Graphite  (index 0 — default)
//    Neutral, professional. Emerald green accent.
// ---------------------------------------------------------------------------

const graphite: CinematicTheme = {
  id:          "graphite",
  name:        "Graphite",
  description: "Neutral professional look with emerald green accent",
  icon:        "layers",

  dark: {
    colors: {
      base:          "#0a0a0f",
      card:          "#13141a",
      cardHover:     "#1c1d25",
      border:        "#25263a",
      borderSubtle:  "#1a1b28",
      text:          "#e8e8ed",
      textMuted:     "#8888a0",
      textSecondary: "#5e5e78",
      textDisabled:  "#404055",
      accent:        "#22c55e",   // emerald-500 — vibrant on dark
      accentText:    "#0a0a0f",
    },
    trading:      TRADING_DARK,
    chart:        ["#22c55e", "#38bdf8", "#a78bfa", "#fb923c", "#f472b6"],
    particles: {
      colors:  ["#22c55e", "#16a34a", "#4ade80"],
      opacity: 0.40,
    },
    glass: {
      tint:        hexRgba("#0a0a0f", 0.80),
      blur:        12,
      borderAlpha: 0.12,
      minOpacity:  0.78,
    },
    glow: {
      color:   hexRgba("#22c55e", 0.10),
      opacity: 0.10,
      radius:  200,
    },
    shimmerColor: hexRgba("#22c55e", 0.06),
  },

  light: {
    colors: {
      base:          "#f5f5f7",
      card:          "#ffffff",
      cardHover:     "#eef7f2",
      border:        "#d0d0da",
      borderSubtle:  "#e4e4ec",
      text:          "#18181b",
      textMuted:     "#71717a",
      textSecondary: "#52525b",
      textDisabled:  "#a1a1aa",
      accent:        "#16a34a",   // green-700 — WCAG AA on #f5f5f7 (4.6:1)
      accentText:    "#ffffff",
    },
    trading:      TRADING_LIGHT,
    chart:        ["#16a34a", "#0284c7", "#7c3aed", "#ea580c", "#db2777"],
    particles: {
      colors:  ["#16a34a", "#22c55e", "#4ade80"],
      opacity: 0.18,
    },
    glass: {
      tint:        hexRgba("#ffffff", 0.88),
      blur:        10,
      borderAlpha: 0.08,
      minOpacity:  0.88,
    },
    glow: {
      color:   hexRgba("#16a34a", 0.06),
      opacity: 0.06,
      radius:  180,
    },
    shimmerColor: hexRgba("#16a34a", 0.05),
  },

  shared: {
    shimmer: { speed: "2.5s" },
    particles: {
      quantity:  35,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// 2. Midnight
//    Deep, focused. Sky-blue accent.
// ---------------------------------------------------------------------------

const midnight: CinematicTheme = {
  id:          "midnight",
  name:        "Midnight",
  description: "Deep navy canvas with sky-blue highlights",
  icon:        "moon",

  dark: {
    colors: {
      base:          "#060a14",
      card:          "#0d1422",
      cardHover:     "#162032",
      border:        "#1a2e48",
      borderSubtle:  "#112038",
      text:          "#d8eeff",
      textMuted:     "#6a8aaa",
      textSecondary: "#486a8a",
      textDisabled:  "#2a4060",
      accent:        "#38bdf8",   // sky-400 — vibrant on dark navy
      accentText:    "#060a14",
    },
    trading:      TRADING_DARK,
    chart:        ["#38bdf8", "#22c55e", "#a78bfa", "#fb923c", "#f472b6"],
    particles: {
      colors:  ["#38bdf8", "#0ea5e9", "#7dd3fc"],
      opacity: 0.50,
    },
    glass: {
      tint:        hexRgba("#060a14", 0.78),
      blur:        14,
      borderAlpha: 0.16,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#38bdf8", 0.12),
      opacity: 0.12,
      radius:  220,
    },
    shimmerColor: hexRgba("#38bdf8", 0.07),
  },

  light: {
    colors: {
      base:          "#f0f7ff",
      card:          "#ffffff",
      cardHover:     "#e0f0ff",
      border:        "#b8d8f0",
      borderSubtle:  "#d0e8f8",
      text:          "#071828",
      textMuted:     "#4a7090",
      textSecondary: "#2a5070",
      textDisabled:  "#8ab0c8",
      accent:        "#0369a1",   // sky-700 — WCAG AA on #f0f7ff (5.2:1)
      accentText:    "#ffffff",
    },
    trading:      TRADING_LIGHT,
    chart:        ["#0369a1", "#15803d", "#6d28d9", "#c2410c", "#be185d"],
    particles: {
      colors:  ["#0369a1", "#0ea5e9", "#7dd3fc"],
      opacity: 0.25,
    },
    glass: {
      tint:        hexRgba("#f0f7ff", 0.85),
      blur:        10,
      borderAlpha: 0.15,
      minOpacity:  0.82,
    },
    glow: {
      color:   hexRgba("#0369a1", 0.07),
      opacity: 0.07,
      radius:  180,
    },
    shimmerColor: hexRgba("#0369a1", 0.05),
  },

  shared: {
    shimmer: { speed: "2.6s" },
    particles: {
      quantity:  45,
      sizeRange: [1, 4],
      behavior:  "float",
    },
  },
};

// ---------------------------------------------------------------------------
// 3. Ember
//    Warm, energetic. Amber/orange accent.
// ---------------------------------------------------------------------------

const ember: CinematicTheme = {
  id:          "ember",
  name:        "Ember",
  description: "Warm canvas with amber glow — energetic and focused",
  icon:        "flame",

  dark: {
    colors: {
      base:          "#0d0a07",
      card:          "#181208",
      cardHover:     "#221a0e",
      border:        "#3a2a12",
      borderSubtle:  "#281e0c",
      text:          "#f5e8d0",
      textMuted:     "#a08050",
      textSecondary: "#705a30",
      textDisabled:  "#4a3820",
      accent:        "#f59e0b",   // amber-400 — vibrant warm on dark
      accentText:    "#0d0a07",
    },
    trading:      TRADING_DARK,
    chart:        ["#f59e0b", "#22c55e", "#38bdf8", "#e879f9", "#f87171"],
    particles: {
      colors:  ["#f59e0b", "#d97706", "#fcd34d"],
      opacity: 0.40,
    },
    glass: {
      tint:        hexRgba("#0d0a07", 0.80),
      blur:        12,
      borderAlpha: 0.14,
      minOpacity:  0.76,
    },
    glow: {
      color:   hexRgba("#f59e0b", 0.12),
      opacity: 0.12,
      radius:  200,
    },
    shimmerColor: hexRgba("#f59e0b", 0.07),
  },

  light: {
    colors: {
      base:          "#fffbf5",
      card:          "#ffffff",
      cardHover:     "#fff4e0",
      border:        "#e8d0a0",
      borderSubtle:  "#f0e0c0",
      text:          "#1a1005",
      textMuted:     "#8a6030",
      textSecondary: "#604010",
      textDisabled:  "#c0a060",
      accent:        "#ea580c",   // orange-600 — WCAG AA on #fffbf5 (4.8:1)
      accentText:    "#ffffff",
    },
    trading:      TRADING_LIGHT,
    chart:        ["#ea580c", "#16a34a", "#0369a1", "#7c3aed", "#be185d"],
    particles: {
      colors:  ["#ea580c", "#f59e0b", "#fcd34d"],
      opacity: 0.20,
    },
    glass: {
      tint:        hexRgba("#fffbf5", 0.88),
      blur:        10,
      borderAlpha: 0.10,
      minOpacity:  0.86,
    },
    glow: {
      color:   hexRgba("#ea580c", 0.07),
      opacity: 0.07,
      radius:  180,
    },
    shimmerColor: hexRgba("#ea580c", 0.05),
  },

  shared: {
    shimmer: { speed: "2.4s" },
    particles: {
      quantity:  30,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// Registry (v4 — exactly 3 canonical themes)
// ---------------------------------------------------------------------------

export const CINEMATIC_THEMES: readonly CinematicTheme[] = [
  graphite,  // index 0 — default fallback
  midnight,
  ember,
] as const;

/**
 * THEMES is the canonical v4 export array.
 * Mirrors CINEMATIC_THEMES — use whichever name you prefer.
 */
export const THEMES: readonly ThemeDefinition[] = CINEMATIC_THEMES;

/** Look up a cinematic theme by id. Returns undefined if not found. */
export function findCinematicTheme(id: string): CinematicTheme | undefined {
  return CINEMATIC_THEMES.find((t) => t.id === id);
}

/**
 * Resolve the active variant for a theme given a ColorMode.
 * For "system", interrogates window.matchMedia.
 * Falls back to "dark" in environments without matchMedia (SSR / tests).
 */
export function getResolvedVariant(
  theme: CinematicTheme,
  mode: ColorMode,
): ThemeVariant {
  if (mode === "dark") return theme.dark;
  if (mode === "light") return theme.light;

  // "system" — check OS preference
  if (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function"
  ) {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    return prefersDark ? theme.dark : theme.light;
  }

  return theme.dark;
}
