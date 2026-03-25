/**
 * Shared Plotly.js wrapper with FlintTrade theme defaults.
 * Lazy-loaded — only imported by analysis widgets that need Plotly.
 */
import { memo, useMemo } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout, Config } from "plotly.js";
import { useThemeStore } from "@/stores/themeStore";

interface PlotlyChartProps {
  data: Data[];
  layout?: Partial<Layout>;
  config?: Partial<Config>;
  className?: string;
  style?: React.CSSProperties;
  onHover?: (event: Plotly.PlotHoverEvent) => void;
  onClick?: (event: Plotly.PlotMouseEvent) => void;
}

const DEFAULT_CONFIG: Partial<Config> = {
  displayModeBar: true,
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["toImage", "sendDataToCloud", "lasso2d", "select2d"],
};

export const PlotlyChart = memo(function PlotlyChart({
  data,
  layout: userLayout,
  config: userConfig,
  className,
  style,
  onHover,
  onClick,
}: PlotlyChartProps) {
  const resolvedMode = useThemeStore((s) => s.getResolvedMode());

  const themedLayout = useMemo<Partial<Layout>>(() => {
    const isDark = resolvedMode === "dark";
    return {
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: {
        family: "Inter, system-ui, sans-serif",
        color: isDark ? "#a0a0b0" : "#404050",
        size: 11,
      },
      margin: { t: 30, r: 20, b: 40, l: 50 },
      xaxis: {
        gridcolor: isDark ? "#1e1e2e" : "#e5e7eb",
        zerolinecolor: isDark ? "#2a2a3a" : "#d1d5db",
      },
      yaxis: {
        gridcolor: isDark ? "#1e1e2e" : "#e5e7eb",
        zerolinecolor: isDark ? "#2a2a3a" : "#d1d5db",
      },
      legend: {
        bgcolor: "transparent",
        font: { size: 10 },
      },
      ...userLayout,
    };
  }, [resolvedMode, userLayout]);

  const mergedConfig = useMemo(
    () => ({
      ...DEFAULT_CONFIG,
      ...userConfig,
    }),
    [userConfig],
  );

  return (
    <Plot
      data={data}
      layout={themedLayout}
      config={mergedConfig}
      className={className}
      style={{ width: "100%", height: "100%", ...style }}
      useResizeHandler
      onHover={onHover}
      onClick={onClick}
    />
  );
});
