/**
 * ThemePicker.test.tsx — Renders theme options and colour mode toggle.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/stores/themeStore", () => {
  const store = {
    activeThemeId: "graphite",
    mode: "dark" as const,
    glass: true,
    customThemes: [],
    setTheme: vi.fn(),
    setMode: vi.fn(),
    setGlass: vi.fn(),
    addCustomTheme: vi.fn(),
    getActiveTheme: vi.fn(),
  };
  return {
    useThemeStore: Object.assign(
      (selector?: (s: typeof store) => unknown) =>
        selector ? selector(store) : store,
      { getState: () => store },
    ),
  };
});

vi.mock("@/lib/cinematicThemes", () => ({
  CINEMATIC_THEMES: [
    {
      id: "graphite",
      name: "Graphite",
      description: "Default dark theme",
      icon: "layers",
      dark: {
        colors: { base: "#0a0a0f", card: "#16161f", accent: "#6366f1", accentText: "#fff", border: "#2a2a3a", text: "#e4e4e7", textMuted: "#71717a", textSecondary: "#a1a1aa" },
        glass: { tint: "rgba(10,10,15,0.6)", blur: 12, borderAlpha: 0.1 },
      },
      light: {
        colors: { base: "#fafafa", card: "#ffffff", accent: "#6366f1", accentText: "#fff", border: "#e4e4e7", text: "#18181b", textMuted: "#71717a", textSecondary: "#52525b" },
        glass: { tint: "rgba(255,255,255,0.6)", blur: 12, borderAlpha: 0.1 },
      },
    },
    {
      id: "midnight",
      name: "Midnight",
      description: "Deep blue theme",
      icon: "moon",
      dark: {
        colors: { base: "#0a0a1a", card: "#161630", accent: "#818cf8", accentText: "#fff", border: "#2a2a4a", text: "#e4e4f7", textMuted: "#71719a", textSecondary: "#a1a1ca" },
        glass: { tint: "rgba(10,10,26,0.6)", blur: 12, borderAlpha: 0.1 },
      },
      light: {
        colors: { base: "#f0f0ff", card: "#ffffff", accent: "#818cf8", accentText: "#fff", border: "#d4d4f7", text: "#18182b", textMuted: "#71719a", textSecondary: "#52526b" },
        glass: { tint: "rgba(240,240,255,0.6)", blur: 12, borderAlpha: 0.1 },
      },
    },
    {
      id: "ember",
      name: "Ember",
      description: "Warm amber theme",
      icon: "flame",
      dark: {
        colors: { base: "#0f0a0a", card: "#1f1616", accent: "#f59e0b", accentText: "#000", border: "#3a2a2a", text: "#e7e4e4", textMuted: "#7a7171", textSecondary: "#aaa1a1" },
        glass: { tint: "rgba(15,10,10,0.6)", blur: 12, borderAlpha: 0.1 },
      },
      light: {
        colors: { base: "#fffaf0", card: "#ffffff", accent: "#f59e0b", accentText: "#000", border: "#e7e4d4", text: "#1b1818", textMuted: "#7a7171", textSecondary: "#6b5252" },
        glass: { tint: "rgba(255,250,240,0.6)", blur: 12, borderAlpha: 0.1 },
      },
    },
  ],
}));

vi.mock("@/lib/contrastUtils", () => ({
  evaluateContrast: () => ({ ratio: "4.5", passes: true, label: "AA" }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { ThemePicker } from "../ThemePicker";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ThemePicker", () => {
  it("renders all three built-in theme names", () => {
    render(<ThemePicker />);
    expect(screen.getByLabelText("Graphite")).toBeInTheDocument();
    expect(screen.getByLabelText("Midnight")).toBeInTheDocument();
    expect(screen.getByLabelText("Ember")).toBeInTheDocument();
  });

  it("renders the colour mode toggle with Dark, Light, System", () => {
    render(<ThemePicker />);
    expect(screen.getByRole("button", { name: "Dark" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Light" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "System" })).toBeInTheDocument();
  });
});
