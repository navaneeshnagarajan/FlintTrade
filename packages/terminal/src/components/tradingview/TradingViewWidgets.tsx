/**
 * TradingViewWidgets.tsx
 *
 * Reusable TradingView free widget embeds for the FlintTrade terminal.
 * Each widget uses TradingView's official script-based embed approach:
 * a container div receives a dynamically created <script> tag whose text
 * content is the JSON config. TradingView's embed script reads that config
 * and injects the iframe into the sibling `.tradingview-widget-container__widget` div.
 *
 * All widgets:
 *  - Accept a `colorTheme` prop ("dark" | "light"), defaulting to "dark"
 *  - Are wrapped in React.memo to prevent unnecessary re-renders
 *  - Carry aria-label for screen-reader accessibility
 *  - Clean up the injected script element on unmount
 *  - Use `width: "100%"` so they fill their Dockview panel naturally
 */

import { useEffect, useRef, memo } from "react";

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

/**
 * Injects a TradingView embed script into `container`.
 * TradingView's embed pattern requires:
 *   1. A wrapper div with class "tradingview-widget-container"
 *   2. An inner div with class "tradingview-widget-container__widget"
 *   3. A <script> whose text is the JSON config, appended AFTER the inner div
 *
 * Returns the created script element so the caller can remove it on cleanup.
 */
function injectTVScript(
  container: HTMLDivElement,
  scriptSrc: string,
  config: Record<string, unknown>
): HTMLScriptElement {
  const script = document.createElement("script");
  script.type = "text/javascript";
  script.src = scriptSrc;
  script.async = true;
  // TradingView reads the script's innerHTML as JSON config
  script.innerHTML = JSON.stringify(config);
  container.appendChild(script);
  return script;
}

// ---------------------------------------------------------------------------
// Ticker Tape
// ---------------------------------------------------------------------------

export interface TVTickerTapeProps {
  colorTheme?: "dark" | "light";
  /** Height of the widget container in pixels. Defaults to 76. */
  height?: number;
}

/**
 * TVTickerTape — Horizontal scrolling price ribbon.
 * Displays NIFTY 50, BANK NIFTY, SENSEX, NIFTY IT, GOLD and CRUDE OIL.
 */
export const TVTickerTape = memo(function TVTickerTape({
  colorTheme = "dark",
  height = 76,
}: TVTickerTapeProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Clear any previously injected widget (e.g. after a theme change)
    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';

    const script = injectTVScript(
      container,
      "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js",
      {
        symbols: [
          { proName: "BSE:SENSEX", title: "SENSEX" },
          { proName: "NSE:NIFTY", title: "NIFTY 50" },
          { proName: "NSE:BANKNIFTY", title: "BANK NIFTY" },
          { proName: "NSE:NIFTYIT", title: "NIFTY IT" },
          { proName: "MCX:GOLD1!", title: "GOLD" },
          { proName: "MCX:CRUDEOIL1!", title: "CRUDE OIL" },
        ],
        showSymbolLogo: true,
        isTransparent: true,
        displayMode: "adaptive",
        colorTheme,
        locale: "en",
      }
    );

    return () => {
      if (container.contains(script)) container.removeChild(script);
    };
  }, [colorTheme]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full overflow-hidden"
      style={{ height }}
      aria-label="TradingView Ticker Tape — live market prices"
      role="region"
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Mini Chart
// ---------------------------------------------------------------------------

export interface TVMiniChartProps {
  symbol?: string;
  colorTheme?: "dark" | "light";
  /** Height of the widget container in pixels. Defaults to 220. */
  height?: number;
}

/**
 * TVMiniChart — Compact single-symbol price chart.
 * Use for quick sparkline-style views inside cards or side panels.
 */
export const TVMiniChart = memo(function TVMiniChart({
  symbol = "NSE:NIFTY",
  colorTheme = "dark",
  height = 220,
}: TVMiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';

    const script = injectTVScript(
      container,
      "https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js",
      {
        symbol,
        width: "100%",
        height,
        locale: "en",
        dateRange: "1D",
        colorTheme,
        isTransparent: true,
        autosize: true,
        largeChartUrl: "",
      }
    );

    return () => {
      if (container.contains(script)) container.removeChild(script);
    };
  }, [symbol, colorTheme, height]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full"
      style={{ height }}
      aria-label={`TradingView Mini Chart — ${symbol}`}
      role="region"
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Market Overview
// ---------------------------------------------------------------------------

export interface TVMarketOverviewProps {
  colorTheme?: "dark" | "light";
  /** Height of the widget container in pixels. Defaults to 400. */
  height?: number;
}

/**
 * TVMarketOverview — Multi-tab market summary with Indices, Futures and Commodities.
 */
export const TVMarketOverview = memo(function TVMarketOverview({
  colorTheme = "dark",
  height = 400,
}: TVMarketOverviewProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';

    const script = injectTVScript(
      container,
      "https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js",
      {
        colorTheme,
        dateRange: "1D",
        showChart: true,
        locale: "en",
        width: "100%",
        height,
        isTransparent: true,
        showSymbolLogo: true,
        showFloatingTooltip: false,
        plotLineColorGrowing: "rgba(41, 98, 255, 1)",
        plotLineColorFalling: "rgba(41, 98, 255, 1)",
        gridLineColor: "rgba(42, 46, 57, 0)",
        scaleFontColor: "rgba(134, 137, 147, 1)",
        belowLineFillColorGrowing: "rgba(41, 98, 255, 0.12)",
        belowLineFillColorFalling: "rgba(41, 98, 255, 0.12)",
        belowLineFillColorGrowingBottom: "rgba(41, 98, 255, 0)",
        belowLineFillColorFallingBottom: "rgba(41, 98, 255, 0)",
        symbolActiveColor: "rgba(41, 98, 255, 0.12)",
        tabs: [
          {
            title: "Indices",
            symbols: [
              { s: "BSE:SENSEX", d: "SENSEX" },
              { s: "NSE:NIFTY", d: "NIFTY 50" },
              { s: "NSE:BANKNIFTY", d: "BANK NIFTY" },
              { s: "NSE:NIFTYIT", d: "NIFTY IT" },
              { s: "NSE:NIFTYMIDCAP100", d: "NIFTY MIDCAP 100" },
              { s: "NSE:NIFTYSMALLCAP100", d: "NIFTY SMALLCAP 100" },
            ],
          },
          {
            title: "Futures",
            symbols: [
              { s: "NSE:NIFTY1!", d: "NIFTY FUT" },
              { s: "NSE:BANKNIFTY1!", d: "BANK NIFTY FUT" },
              { s: "NSE:FINNIFTY1!", d: "FIN NIFTY FUT" },
              { s: "NSE:MIDCPNIFTY1!", d: "MIDCAP NIFTY FUT" },
              { s: "COMEX:GC1!", d: "GOLD FUT" },
              { s: "NYMEX:CL1!", d: "CRUDE OIL FUT" },
            ],
          },
          {
            title: "Commodities",
            symbols: [
              { s: "MCX:GOLD1!", d: "MCX GOLD" },
              { s: "MCX:SILVER1!", d: "MCX SILVER" },
              { s: "MCX:CRUDEOIL1!", d: "MCX CRUDE OIL" },
              { s: "MCX:NATURALGAS1!", d: "MCX NAT GAS" },
              { s: "MCX:COPPER1!", d: "MCX COPPER" },
              { s: "MCX:ALUMINIUM1!", d: "MCX ALUMINIUM" },
            ],
          },
        ],
      }
    );

    return () => {
      if (container.contains(script)) container.removeChild(script);
    };
  }, [colorTheme, height]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full"
      style={{ height }}
      aria-label="TradingView Market Overview — Indices, Futures and Commodities"
      role="region"
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Technical Analysis
// ---------------------------------------------------------------------------

export interface TVTechnicalAnalysisProps {
  symbol?: string;
  colorTheme?: "dark" | "light";
  /** Height of the widget container in pixels. Defaults to 450. */
  height?: number;
  /** Chart interval for the analysis. Defaults to "1D". */
  interval?: "1" | "5" | "15" | "30" | "60" | "1D" | "1W" | "1M";
}

/**
 * TVTechnicalAnalysis — Buy / Sell / Neutral gauge with oscillator and moving-average summary.
 */
export const TVTechnicalAnalysis = memo(function TVTechnicalAnalysis({
  symbol = "NSE:NIFTY",
  colorTheme = "dark",
  height = 450,
  interval = "1D",
}: TVTechnicalAnalysisProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';

    const script = injectTVScript(
      container,
      "https://s3.tradingview.com/external-embedding/embed-widget-technical-analysis.js",
      {
        interval,
        width: "100%",
        isTransparent: true,
        height,
        symbol,
        showIntervalTabs: true,
        displayMode: "single",
        locale: "en",
        colorTheme,
      }
    );

    return () => {
      if (container.contains(script)) container.removeChild(script);
    };
  }, [symbol, colorTheme, height, interval]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full"
      style={{ height }}
      aria-label={`TradingView Technical Analysis — ${symbol}`}
      role="region"
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Screener
// ---------------------------------------------------------------------------

export interface TVScreenerProps {
  colorTheme?: "dark" | "light";
  /** Height of the widget container in pixels. Defaults to 550. */
  height?: number;
  /** Default screener to show. Defaults to "india". */
  defaultScreen?: string;
}

/**
 * TVScreener — Market screener widget pre-configured for Indian equities.
 * Allows filtering by performance, volatility, volume, and fundamentals.
 */
export const TVScreener = memo(function TVScreener({
  colorTheme = "dark",
  height = 550,
  defaultScreen = "most_capitalized",
}: TVScreenerProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.innerHTML =
      '<div class="tradingview-widget-container__widget"></div>';

    const script = injectTVScript(
      container,
      "https://s3.tradingview.com/external-embedding/embed-widget-screener.js",
      {
        width: "100%",
        height,
        defaultColumn: "overview",
        defaultScreen,
        market: "india",
        showToolbar: true,
        colorTheme,
        locale: "en",
        isTransparent: true,
      }
    );

    return () => {
      if (container.contains(script)) container.removeChild(script);
    };
  }, [colorTheme, height, defaultScreen]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full"
      style={{ height }}
      aria-label="TradingView Stock Screener — Indian equities"
      role="region"
    >
      <div className="tradingview-widget-container__widget" />
    </div>
  );
});
