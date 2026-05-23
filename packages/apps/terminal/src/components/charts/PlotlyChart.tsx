/**
 * Shared Plotly.js wrapper with FlintTrade theme defaults.
 * Lazy-loaded — only imported by analysis widgets that need Plotly.
 */
import { memo, useMemo } from "react";
import Plot from "react-plotly.js";
import type { Data, Layout, Config } from "plotly.js";
import { usePlotlyTheme } from "@/hooks/usePlotlyTheme";

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
  const baseTheme = usePlotlyTheme();

  const themedLayout = useMemo<Partial<Layout>>(() => {
    return {
      ...baseTheme,
      margin: { t: 30, r: 20, b: 40, l: 50 },
      // userLayout values override base theme, but xaxis/yaxis need merging
      ...userLayout,
      xaxis: { ...baseTheme.xaxis, ...userLayout?.xaxis },
      yaxis: { ...baseTheme.yaxis, ...userLayout?.yaxis },
    };
  }, [baseTheme, userLayout]);

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
