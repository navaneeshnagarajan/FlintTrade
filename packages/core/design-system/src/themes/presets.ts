export const themePresets = {
  default: {
    name: "Default",
    mode: "dark",
  },
  graphite: {
    name: "Graphite",
    mode: "dark",
  },
  ember: {
    name: "Ember",
    mode: "dark",
  },
} as const

export type ThemePresetName = keyof typeof themePresets
