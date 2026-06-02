/**
 * Shared Plotly.js wrapper with FlintTrade theme defaults.
 * Lazy-loaded — only imported by analysis widgets that need Plotly.
 */
import { memo, useEffect, useMemo, useRef } from "react";
import * as PlotlyRuntime from "plotly.js-dist-min";
import type { Data, Layout, Config } from "plotly.js";
import {
  FLINT_PLOTLY_DEFAULT_CONFIG,
  mergeFlintPlotlyLayout,
} from "@flinttrade/design-system";
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

interface PlotlyRuntimeApi {
  react: (
    root: HTMLElement,
    data: Data[],
    layout: Partial<Layout>,
    config: Partial<Config>,
  ) => Promise<unknown> | unknown;
  purge: (root: HTMLElement) => void;
  Plots?: {
    resize?: (root: HTMLElement) => Promise<unknown> | unknown;
  };
}

interface PlotlyEventTarget extends HTMLDivElement {
  on?: (event: "plotly_hover" | "plotly_click", handler: (event: unknown) => void) => void;
  removeAllListeners?: (event?: "plotly_hover" | "plotly_click") => void;
}

const Plotly = (
  (PlotlyRuntime as unknown as { default?: PlotlyRuntimeApi }).default ?? PlotlyRuntime
) as PlotlyRuntimeApi;

function isDisplayedPlotlyContainer(container: HTMLElement): boolean {
  if (!container.isConnected) return false;
  const rect = container.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

export const PlotlyChart = memo(function PlotlyChart({
  data,
  layout: userLayout,
  config: userConfig,
  className,
  style,
  onHover,
  onClick,
}: PlotlyChartProps) {
  const containerRef = useRef<PlotlyEventTarget | null>(null);
  const baseTheme = usePlotlyTheme();

  const themedLayout = useMemo<Partial<Layout>>(() => {
    return mergeFlintPlotlyLayout(
      baseTheme as Parameters<typeof mergeFlintPlotlyLayout>[0],
      userLayout as Parameters<typeof mergeFlintPlotlyLayout>[1],
    ) as Partial<Layout>;
  }, [baseTheme, userLayout]);

  const mergedConfig = useMemo(
    () => ({
      ...FLINT_PLOTLY_DEFAULT_CONFIG,
      ...userConfig,
    }) as Partial<Config>,
    [userConfig],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let disposed = false;
    const attachEvents = () => {
      if (disposed) return;
      container.removeAllListeners?.("plotly_hover");
      container.removeAllListeners?.("plotly_click");
      if (onHover) container.on?.("plotly_hover", onHover as (event: unknown) => void);
      if (onClick) container.on?.("plotly_click", onClick as (event: unknown) => void);
    };

    Promise.resolve(Plotly.react(container, data, themedLayout, mergedConfig))
      .then(attachEvents)
      .catch((error: unknown) => {
        if (!disposed) {
          console.error("Plotly chart render failed:", error);
        }
      });

    return () => {
      disposed = true;
      container.removeAllListeners?.("plotly_hover");
      container.removeAllListeners?.("plotly_click");
      Plotly.purge(container);
    };
  }, [data, mergedConfig, onClick, onHover, themedLayout]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(() => {
      if (!isDisplayedPlotlyContainer(container)) return;
      Promise.resolve(Plotly.Plots?.resize?.(container)).catch((error: unknown) => {
        if (isDisplayedPlotlyContainer(container)) {
          console.error("Plotly chart resize failed:", error);
        }
      });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: "100%", height: "100%", ...style }}
    />
  );
});
