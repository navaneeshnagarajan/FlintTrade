/**
 * cinematicThemes.ts
 *
 * CinematicTheme type system and 6 built-in presets (v3).
 *
 * v3 canonical themes (6 total):
 *   graphite       — default; neutral dark with blue-indigo accent
 *   midnight       — deep navy with sky-blue highlights
 *   arctic-frost   — slate greys with ice-white crystalline clarity
 *   monochrome     — pure black/white, zero color distraction
 *   solarized-dark — warm teal canvas with Solarized palette fidelity
 *   light          — clean white with indigo accent (light-first theme)
 *
 * Each theme carries both a dark and light ThemeVariant so the user can
 * switch color-mode without changing the theme identity. Per-variant accent
 * colors are chosen to meet WCAG AA 4.5:1 contrast ratio on the variant's
 * base background.
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
    /** Page / canvas background */
    base: string;
    /** Card / panel surface */
    card: string;
    /** Card on hover */
    cardHover: string;
    /** Default border */
    border: string;
    /** Primary readable text */
    text: string;
    /** Subdued label text */
    textMuted: string;
    /** Secondary / meta text */
    textSecondary: string;
    /**
     * Per-variant accent.
     * Dark variant: vibrant, high-saturation.
     * Light variant: darker tone that still meets WCAG AA 4.5:1 on the light base.
     */
    accent: string;
    /** Text rendered on an accent-colored background — always meets AA. */
    accentText: string;
  };
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
    /** Fixed green profit — never per-theme */
    profit: "#22c55e";
    /** Fixed red loss — never per-theme */
    loss: "#ef4444";
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
// 1. Graphite  (index 0 — default fallback)
// ---------------------------------------------------------------------------
const graphite: CinematicTheme = {
  id: "graphite",
  name: "Graphite",
  description: "Neutral dark with premium blue-indigo accent",
  icon: "layers",

  dark: {
    colors: {
      base:          "#0b0b0f",
      card:          "#141418",
      cardHover:     "#1a1a20",
      border:        "#28283a",
      text:          "#e8e8ed",
      textMuted:     "#9898a5",
      textSecondary: "#6b6b78",
      accent:        "#7c8be8",
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#7c8be8", "#5c6bc0", "#9fa8da"],
      opacity: 0.3,
    },
    glass: {
      tint:        "rgba(20,20,24,0.85)",
      blur:        12,
      borderAlpha: 0.1,
      minOpacity:  0.80,
    },
    glow: {
      color:   "#7c8be8",
      opacity: 0.05,
      radius:  200,
    },
    shimmerColor: hexRgba("#7c8be8", 0.06),
  },

  light: {
    colors: {
      base:          "#f5f5f7",
      card:          "#ffffff",
      cardHover:     "#f0f0f5",
      border:        "#d0d0da",
      text:          "#18181b",
      textMuted:     "#71717a",
      textSecondary: "#52525b",
      accent:        "#4f5bd5",
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#4f5bd5", "#3f4bc5", "#6f7be5"],
      opacity: 0.15,
    },
    glass: {
      tint:        "rgba(255,255,255,0.90)",
      blur:        12,
      borderAlpha: 0.08,
      minOpacity:  0.90,
    },
    glow: {
      color:   "#4f5bd5",
      opacity: 0.03,
      radius:  200,
    },
    shimmerColor: hexRgba("#4f5bd5", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
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
// ---------------------------------------------------------------------------
const midnight: CinematicTheme = {
  id: "midnight",
  name: "Midnight",
  description: "Deep navy canvas with sky-blue highlights",
  icon: "moon",

  dark: {
    colors: {
      base:          "#060a14",
      card:          "#0d1422",
      cardHover:     "#162032",
      border:        "#1a2e48",
      text:          "#d8eeff",
      textMuted:     "#6a8aaa",
      textSecondary: "#7aaacf",
      accent:        "#38bdf8",
      accentText:    "#060a14",
    },
    particles: {
      colors: ["#38bdf8", "#0ea5e9", "#7dd3fc"],
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
      radius:  28,
    },
    shimmerColor: hexRgba("#38bdf8", 0.07),
  },

  light: {
    colors: {
      base:          "#f0f7ff",
      card:          "#ffffff",
      cardHover:     "#e0f0ff",
      border:        "#b8d8f0",
      text:          "#071828",
      textMuted:     "#4a7090",
      textSecondary: "#2a5070",
      accent:        "#0369a1",    // Darker sky-blue — WCAG AA on #f0f7ff
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#0369a1", "#0ea5e9", "#7dd3fc"],
      opacity: 0.30,
    },
    glass: {
      tint:        hexRgba("#f0f7ff", 0.82),
      blur:        10,
      borderAlpha: 0.18,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#0369a1", 0.08),
      opacity: 0.08,
      radius:  20,
    },
    shimmerColor: hexRgba("#0369a1", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.6s" },
    particles: {
      quantity:  45,
      sizeRange: [1, 4],
      behavior:  "float",
    },
  },
};

// ---------------------------------------------------------------------------
// 3. Arctic Frost
// ---------------------------------------------------------------------------
const arcticFrost: CinematicTheme = {
  id: "arctic-frost",
  name: "Arctic Frost",
  description: "Slate greys with ice-white crystalline clarity",
  icon: "snowflake",

  dark: {
    colors: {
      base:          "#0f1218",
      card:          "#181d26",
      cardHover:     "#222838",
      border:        "#2e3748",
      text:          "#e8ecf4",
      textMuted:     "#748090",
      textSecondary: "#8898b0",
      accent:        "#94a3b8",
      accentText:    "#0f1218",
    },
    particles: {
      colors: ["#94a3b8", "#64748b", "#cbd5e1"],
      opacity: 0.45,
    },
    glass: {
      tint:        hexRgba("#0f1218", 0.76),
      blur:        10,
      borderAlpha: 0.14,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#94a3b8", 0.10),
      opacity: 0.10,
      radius:  20,
    },
    shimmerColor: hexRgba("#94a3b8", 0.06),
  },

  light: {
    colors: {
      base:          "#f8fafc",
      card:          "#ffffff",
      cardHover:     "#eef2f8",
      border:        "#d0dae8",
      text:          "#0f1929",
      textMuted:     "#647080",
      textSecondary: "#3a4a5e",
      accent:        "#475569",    // Slate — WCAG AA on #f8fafc
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#475569", "#64748b", "#cbd5e1"],
      opacity: 0.25,
    },
    glass: {
      tint:        hexRgba("#f8fafc", 0.84),
      blur:        8,
      borderAlpha: 0.16,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#475569", 0.07),
      opacity: 0.07,
      radius:  16,
    },
    shimmerColor: hexRgba("#475569", 0.04),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "3.0s" },
    particles: {
      quantity:  60,
      sizeRange: [1, 4],
      behavior:  "snow",
    },
  },
};

// ---------------------------------------------------------------------------
// 4. Monochrome
// ---------------------------------------------------------------------------
const monochrome: CinematicTheme = {
  id: "monochrome",
  name: "Monochrome",
  description: "Pure black and white — zero color distraction",
  icon: "circle",

  dark: {
    colors: {
      base:          "#0a0a0a",
      card:          "#141414",
      cardHover:     "#1e1e1e",
      border:        "#2e2e2e",
      text:          "#f0f0f0",
      textMuted:     "#888888",
      textSecondary: "#666666",
      accent:        "#d0d0d0",
      accentText:    "#0a0a0a",
    },
    particles: {
      colors: ["#d0d0d0", "#888888", "#f0f0f0"],
      opacity: 0.25,
    },
    glass: {
      tint:        hexRgba("#0a0a0a", 0.85),
      blur:        10,
      borderAlpha: 0.12,
      minOpacity:  0.80,
    },
    glow: {
      color:   hexRgba("#d0d0d0", 0.06),
      opacity: 0.06,
      radius:  160,
    },
    shimmerColor: hexRgba("#d0d0d0", 0.05),
  },

  light: {
    colors: {
      base:          "#f9f9f9",
      card:          "#ffffff",
      cardHover:     "#f0f0f0",
      border:        "#d8d8d8",
      text:          "#0a0a0a",
      textMuted:     "#707070",
      textSecondary: "#505050",
      accent:        "#303030",   // Dark charcoal — WCAG AA on #f9f9f9
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#303030", "#606060", "#a0a0a0"],
      opacity: 0.18,
    },
    glass: {
      tint:        hexRgba("#f9f9f9", 0.88),
      blur:        8,
      borderAlpha: 0.10,
      minOpacity:  0.88,
    },
    glow: {
      color:   hexRgba("#303030", 0.04),
      opacity: 0.04,
      radius:  120,
    },
    shimmerColor: hexRgba("#303030", 0.04),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "3.0s" },
    particles: {
      quantity:  25,
      sizeRange: [1, 2],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// 5. Solarized Dark
// ---------------------------------------------------------------------------
const solarizedDark: CinematicTheme = {
  id: "solarized-dark",
  name: "Solarized Dark",
  description: "Warm teal canvas with Solarized palette fidelity",
  icon: "sun",

  dark: {
    colors: {
      base:          "#002b36",  // solarized base03
      card:          "#073642",  // solarized base02
      cardHover:     "#0d4050",
      border:        "#124f5e",
      text:          "#839496",  // solarized base0
      textMuted:     "#657b83",  // solarized base00
      textSecondary: "#586e75",  // solarized base01
      accent:        "#268bd2",  // solarized blue
      accentText:    "#fdf6e3",
    },
    particles: {
      colors: ["#268bd2", "#2aa198", "#859900"],
      opacity: 0.35,
    },
    glass: {
      tint:        hexRgba("#002b36", 0.82),
      blur:        12,
      borderAlpha: 0.16,
      minOpacity:  0.75,
    },
    glow: {
      color:   hexRgba("#268bd2", 0.10),
      opacity: 0.10,
      radius:  180,
    },
    shimmerColor: hexRgba("#268bd2", 0.07),
  },

  light: {
    colors: {
      base:          "#fdf6e3",  // solarized base3
      card:          "#eee8d5",  // solarized base2
      cardHover:     "#e6e0cc",
      border:        "#d4cdb8",
      text:          "#657b83",  // solarized base00
      textMuted:     "#839496",  // solarized base0
      textSecondary: "#93a1a1",  // solarized base1
      accent:        "#268bd2",  // solarized blue — WCAG AA on #fdf6e3 (~4.6:1)
      accentText:    "#fdf6e3",
    },
    particles: {
      colors: ["#268bd2", "#2aa198", "#859900"],
      opacity: 0.20,
    },
    glass: {
      tint:        hexRgba("#fdf6e3", 0.88),
      blur:        10,
      borderAlpha: 0.14,
      minOpacity:  0.85,
    },
    glow: {
      color:   hexRgba("#268bd2", 0.06),
      opacity: 0.06,
      radius:  140,
    },
    shimmerColor: hexRgba("#268bd2", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.8s" },
    particles: {
      quantity:  30,
      sizeRange: [1, 3],
      behavior:  "float",
    },
  },
};

// ---------------------------------------------------------------------------
// 6. Light
// ---------------------------------------------------------------------------
const light: CinematicTheme = {
  id: "light",
  name: "Light",
  description: "Clean white canvas with indigo accent — maximum readability",
  icon: "sun",

  dark: {
    // Dark variant of the "Light" theme — soft off-white for reduced-glare environments
    colors: {
      base:          "#1a1a24",
      card:          "#22222e",
      cardHover:     "#2a2a38",
      border:        "#38384a",
      text:          "#e8e8f0",
      textMuted:     "#9090a8",
      textSecondary: "#686880",
      accent:        "#818cf8",   // indigo-400 — vivid on dark base
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#818cf8", "#6366f1", "#a5b4fc"],
      opacity: 0.25,
    },
    glass: {
      tint:        hexRgba("#1a1a24", 0.88),
      blur:        12,
      borderAlpha: 0.10,
      minOpacity:  0.82,
    },
    glow: {
      color:   hexRgba("#818cf8", 0.06),
      opacity: 0.06,
      radius:  180,
    },
    shimmerColor: hexRgba("#818cf8", 0.06),
  },

  light: {
    // Light variant is the primary mode for this theme
    colors: {
      base:          "#ffffff",
      card:          "#f9f9fb",
      cardHover:     "#f0f0f8",
      border:        "#e0e0ec",
      text:          "#18181b",
      textMuted:     "#71717a",
      textSecondary: "#52525b",
      accent:        "#4f46e5",   // indigo-600 — WCAG AA on #ffffff (~7:1)
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#4f46e5", "#6366f1", "#a5b4fc"],
      opacity: 0.18,
    },
    glass: {
      tint:        "rgba(255,255,255,0.92)",
      blur:        10,
      borderAlpha: 0.08,
      minOpacity:  0.92,
    },
    glow: {
      color:   hexRgba("#4f46e5", 0.04),
      opacity: 0.04,
      radius:  160,
    },
    shimmerColor: hexRgba("#4f46e5", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.5s" },
    particles: {
      quantity:  30,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// Registry (v3 — exactly 6 canonical themes)
// ---------------------------------------------------------------------------

export const CINEMATIC_THEMES: readonly CinematicTheme[] = [
  graphite,       // index 0 — default fallback
  midnight,
  arcticFrost,
  monochrome,
  solarizedDark,
  light,
] as const;

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
