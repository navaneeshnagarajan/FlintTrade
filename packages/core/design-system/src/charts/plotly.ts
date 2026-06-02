export interface FlintPlotlyPalette {
  grid: string
  text: string
  accent: string
  profit: string
  loss: string
  warning: string
  border: string
}

export interface FlintPlotlyAxisTheme {
  gridcolor: string
  linecolor: string
  zerolinecolor: string
  [key: string]: unknown
}

export interface FlintPlotlyTheme {
  paper_bgcolor: string
  plot_bgcolor: string
  font: {
    family: string
    color: string
    size: number
  }
  xaxis: FlintPlotlyAxisTheme
  yaxis: FlintPlotlyAxisTheme
  legend: {
    bgcolor: string
    font: { size: number }
  }
  colorway: string[]
  [key: string]: unknown
}

export type FlintPlotlyLayout = Record<string, unknown> & {
  xaxis?: Record<string, unknown>
  yaxis?: Record<string, unknown>
  margin?: Record<string, unknown>
}

export const FLINT_PLOTLY_DEFAULT_CONFIG = {
  displayModeBar: true,
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["toImage", "sendDataToCloud", "lasso2d", "select2d"],
} as const

export const FLINT_PLOTLY_DEFAULT_MARGIN = {
  t: 30,
  r: 20,
  b: 40,
  l: 50,
} as const

export function createFlintPlotlyTheme(palette: FlintPlotlyPalette): FlintPlotlyTheme {
  return {
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {
      family: "Inter, system-ui, sans-serif",
      color: palette.text,
      size: 11,
    },
    xaxis: {
      gridcolor: palette.grid,
      linecolor: palette.border,
      zerolinecolor: palette.border,
    },
    yaxis: {
      gridcolor: palette.grid,
      linecolor: palette.border,
      zerolinecolor: palette.border,
    },
    legend: {
      bgcolor: "transparent",
      font: { size: 10 },
    },
    colorway: [
      palette.accent,
      palette.profit,
      palette.loss,
      palette.warning,
      "#818cf8",
      "#06b6d4",
    ],
  }
}

export function mergeFlintPlotlyLayout(
  baseTheme: FlintPlotlyTheme,
  userLayout: FlintPlotlyLayout = {},
): FlintPlotlyLayout {
  return {
    ...baseTheme,
    margin: FLINT_PLOTLY_DEFAULT_MARGIN,
    ...userLayout,
    xaxis: { ...baseTheme.xaxis, ...userLayout.xaxis },
    yaxis: { ...baseTheme.yaxis, ...userLayout.yaxis },
  }
}
