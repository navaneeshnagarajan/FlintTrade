/**
 * cinematicThemes.ts
 *
 * CinematicTheme type system and 6 built-in presets.
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
// 1. Emerald Night
// ---------------------------------------------------------------------------
const emeraldNight: CinematicTheme = {
  id: "emerald-night",
  name: "Emerald Night",
  description: "Deep black canvas with vibrant green accents",
  icon: "leaf",

  dark: {
    colors: {
      base:          "#0a0a0f",
      card:          "#13151a",
      cardHover:     "#1c1f27",
      border:        "#1e2430",
      text:          "#e2ffe8",
      textMuted:     "#7a9a86",
      textSecondary: "#8ab89a",
      accent:        "#22c55e",
      accentText:    "#0a0a0f",
    },
    particles: {
      colors: ["#22c55e", "#16a34a", "#4ade80"],
      opacity: 0.55,
    },
    glass: {
      tint:        hexRgba("#0a0a0f", 0.75),
      blur:        12,
      borderAlpha: 0.18,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#22c55e", 0.15),
      opacity: 0.15,
      radius:  24,
    },
    shimmerColor: hexRgba("#22c55e", 0.08),
  },

  light: {
    colors: {
      base:          "#f8faf9",
      card:          "#ffffff",
      cardHover:     "#edf7f1",
      border:        "#cce8d6",
      text:          "#0f2318",
      textMuted:     "#6a907a",
      textSecondary: "#3d6b52",
      accent:        "#15803d",    // Darker green — WCAG AA on #f8faf9
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#15803d", "#16a34a", "#4ade80"],
      opacity: 0.35,
    },
    glass: {
      tint:        hexRgba("#f8faf9", 0.80),
      blur:        10,
      borderAlpha: 0.20,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#15803d", 0.10),
      opacity: 0.10,
      radius:  20,
    },
    shimmerColor: hexRgba("#15803d", 0.06),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.4s" },
    particles: {
      quantity:  40,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// 2. Ocean Depth
// ---------------------------------------------------------------------------
const oceanDepth: CinematicTheme = {
  id: "ocean-depth",
  name: "Ocean Depth",
  description: "Abyssal blues with sky-blue highlights",
  icon: "waves",

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
// 3. Solar Flare
// ---------------------------------------------------------------------------
const solarFlare: CinematicTheme = {
  id: "solar-flare",
  name: "Solar Flare",
  description: "Volcanic dark with fiery orange energy",
  icon: "sun",

  dark: {
    colors: {
      base:          "#0f0a06",
      card:          "#1a1008",
      cardHover:     "#251810",
      border:        "#3a2010",
      text:          "#fff3e6",
      textMuted:     "#9a7050",
      textSecondary: "#c0854a",
      accent:        "#fb923c",
      accentText:    "#0f0a06",
    },
    particles: {
      colors: ["#fb923c", "#f97316", "#fdba74"],
      opacity: 0.52,
    },
    glass: {
      tint:        hexRgba("#0f0a06", 0.76),
      blur:        12,
      borderAlpha: 0.20,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#fb923c", 0.14),
      opacity: 0.14,
      radius:  26,
    },
    shimmerColor: hexRgba("#fb923c", 0.07),
  },

  light: {
    colors: {
      base:          "#fffbf5",
      card:          "#ffffff",
      cardHover:     "#fff3e0",
      border:        "#f5d8b0",
      text:          "#1f0e00",
      textMuted:     "#8a5520",
      textSecondary: "#6b3e10",
      accent:        "#c2410c",    // Darker burnt orange — WCAG AA on #fffbf5
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#c2410c", "#ea580c", "#fdba74"],
      opacity: 0.28,
    },
    glass: {
      tint:        hexRgba("#fffbf5", 0.83),
      blur:        10,
      borderAlpha: 0.18,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#c2410c", 0.08),
      opacity: 0.08,
      radius:  18,
    },
    shimmerColor: hexRgba("#c2410c", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.2s" },
    particles: {
      quantity:  35,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// 4. Neon Pulse
// ---------------------------------------------------------------------------
const neonPulse: CinematicTheme = {
  id: "neon-pulse",
  name: "Neon Pulse",
  description: "Cyberpunk violet with electric purple glow",
  icon: "zap",

  dark: {
    colors: {
      base:          "#0a0610",
      card:          "#120a1e",
      cardHover:     "#1c102c",
      border:        "#2e1650",
      text:          "#f0e8ff",
      textMuted:     "#8068b0",
      textSecondary: "#9870c8",
      accent:        "#a855f7",
      accentText:    "#0a0610",
    },
    particles: {
      colors: ["#a855f7", "#9333ea", "#d8b4fe"],
      opacity: 0.58,
    },
    glass: {
      tint:        hexRgba("#0a0610", 0.78),
      blur:        16,
      borderAlpha: 0.22,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#a855f7", 0.18),
      opacity: 0.18,
      radius:  32,
    },
    shimmerColor: hexRgba("#a855f7", 0.08),
  },

  light: {
    colors: {
      base:          "#faf5ff",
      card:          "#ffffff",
      cardHover:     "#f3e8ff",
      border:        "#ddb6f8",
      text:          "#1a0530",
      textMuted:     "#7048a0",
      textSecondary: "#5b2e8a",
      accent:        "#7c3aed",    // Darker violet — WCAG AA on #faf5ff
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#7c3aed", "#9333ea", "#d8b4fe"],
      opacity: 0.32,
    },
    glass: {
      tint:        hexRgba("#faf5ff", 0.82),
      blur:        12,
      borderAlpha: 0.20,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#7c3aed", 0.10),
      opacity: 0.10,
      radius:  22,
    },
    shimmerColor: hexRgba("#7c3aed", 0.06),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "1.8s" },
    particles: {
      quantity:  50,
      sizeRange: [1, 3],
      behavior:  "pulse",
      maxPulseFrequencyHz: 2.0,
      pulseTransitionMs:   500,
    },
  },
};

// ---------------------------------------------------------------------------
// 5. Arctic Frost
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
// 6. Blood Moon
// ---------------------------------------------------------------------------
const bloodMoon: CinematicTheme = {
  id: "blood-moon",
  name: "Blood Moon",
  description: "Crimson-tinged dark for high-intensity sessions",
  icon: "moon",

  dark: {
    colors: {
      base:          "#0a0606",
      card:          "#170808",
      cardHover:     "#220c0c",
      border:        "#3a1010",
      text:          "#ffe8e8",
      textMuted:     "#9a5050",
      textSecondary: "#c05050",
      accent:        "#dc2626",
      accentText:    "#fff0f0",
    },
    particles: {
      colors: ["#dc2626", "#b91c1c", "#fca5a5"],
      opacity: 0.50,
    },
    glass: {
      tint:        hexRgba("#0a0606", 0.76),
      blur:        12,
      borderAlpha: 0.22,
      minOpacity:  0.60,
    },
    glow: {
      color:   hexRgba("#dc2626", 0.16),
      opacity: 0.16,
      radius:  28,
    },
    shimmerColor: hexRgba("#dc2626", 0.07),
  },

  light: {
    colors: {
      base:          "#fff5f5",
      card:          "#ffffff",
      cardHover:     "#ffe8e8",
      border:        "#fcc0c0",
      text:          "#200808",
      textMuted:     "#8a3030",
      textSecondary: "#6b1818",
      accent:        "#b91c1c",    // Darker red — WCAG AA on #fff5f5
      accentText:    "#ffffff",
    },
    particles: {
      colors: ["#b91c1c", "#dc2626", "#fca5a5"],
      opacity: 0.28,
    },
    glass: {
      tint:        hexRgba("#fff5f5", 0.83),
      blur:        10,
      borderAlpha: 0.18,
      minOpacity:  0.70,
    },
    glow: {
      color:   hexRgba("#b91c1c", 0.08),
      opacity: 0.08,
      radius:  18,
    },
    shimmerColor: hexRgba("#b91c1c", 0.05),
  },

  shared: {
    profit: "#22c55e",
    loss:   "#ef4444",
    shimmer: { speed: "2.0s" },
    particles: {
      quantity:  38,
      sizeRange: [1, 3],
      behavior:  "drift",
    },
  },
};

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const CINEMATIC_THEMES: readonly CinematicTheme[] = [
  emeraldNight,
  oceanDepth,
  solarFlare,
  neonPulse,
  arcticFrost,
  bloodMoon,
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
