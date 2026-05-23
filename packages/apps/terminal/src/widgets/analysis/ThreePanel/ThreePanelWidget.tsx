/**
 * ThreePanelWidget.tsx
 *
 * Three-panel synchronised chart widget: CE | Index | PE
 *
 * Displays three Lightweight Charts instances side-by-side with time-scale
 * synchronisation (scroll/zoom in one syncs all three). The index chart is
 * slightly wider than the option legs.
 *
 * Header controls: underlying symbol, expiry, strike (defaults to ATM).
 * CE and PE option symbols are derived from underlying + expiry + strike via
 * the OpenAlgo `optionsymbol` endpoint.
 */

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  memo,
} from "react";
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
} from "lightweight-charts";
import type {
  IChartApi,
  ISeriesApi,
  Time,
  IRange,
} from "lightweight-charts";
import type { OHLCVBar } from "@/types/api";
import { ChevronDown, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { getHistory, getExpiry, getOptionSymbol, getOptionChain } from "@/services/api";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PanelLabel {
  symbol: string;
  exchange: string;
  title: string;
  color: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DEFAULT_UNDERLYING = "NIFTY";
const DEFAULT_EXCHANGE = "NSE_INDEX";
const OPTION_EXCHANGE = "NFO";

const LOOKBACK_DAYS: Record<string, number> = {
  "1m": 3, "3m": 5, "5m": 7, "15m": 15, "30m": 20,
  "1h": 45, "1D": 180,
};

const INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "1D"];

// Colour tokens matching FlintTrade design system
const CE_COLOR = "rgba(34, 197, 94, 0.9)";   // profit green
const INDEX_COLOR = "rgba(148, 163, 184, 0.9)"; // slate text-secondary
const PE_COLOR = "rgba(239, 68, 68, 0.9)";    // loss red

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getStartDate(interval: string): string {
  const d = new Date();
  d.setDate(d.getDate() - (LOOKBACK_DAYS[interval] ?? 10));
  return formatDate(d);
}

/**
 * Derive CE / PE option symbol strings from the option chain ATM strike.
 * Returns null if data is unavailable.
 */
async function resolveOptionSymbols(
  underlying: string,
  expiry: string,
  strikeOffset: string,
): Promise<{ ce: { symbol: string; exchange: string } | null; pe: { symbol: string; exchange: string } | null }> {
  const [ceResult, peResult] = await Promise.allSettled([
    getOptionSymbol(underlying, OPTION_EXCHANGE, expiry, "CE", strikeOffset),
    getOptionSymbol(underlying, OPTION_EXCHANGE, expiry, "PE", strikeOffset),
  ]);

  const ce = ceResult.status === "fulfilled" && ceResult.value
    ? (ceResult.value as { symbol: string; exchange: string })
    : null;
  const pe = peResult.status === "fulfilled" && peResult.value
    ? (peResult.value as { symbol: string; exchange: string })
    : null;

  return { ce, pe };
}

/**
 * Fetch ATM strike from option chain and return it as an offset string ("0"
 * means ATM). Falls back to "0" on error.
 */
async function resolveATMStrike(
  underlying: string,
  expiry: string,
): Promise<string> {
  try {
    const chain = await getOptionChain(underlying, OPTION_EXCHANGE, expiry);
    const raw = chain as unknown as { atm_strike?: number } | null;
    if (raw?.atm_strike) {
      return String(raw.atm_strike);
    }
  } catch { /* fall through */ }
  return "0";
}

// ---------------------------------------------------------------------------
// Single chart panel hook
// ---------------------------------------------------------------------------

interface UsePanelChartOptions {
  label: PanelLabel;
  interval: string;
  syncGroup: React.MutableRefObject<IChartApi[]>;
}

function usePanelChart({ label, interval, syncGroup }: UsePanelChartOptions) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const isSyncingRef = useRef(false);
  const chartTheme = useLightweightChartTheme();

  // Initialise chart
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: chartTheme.layout,
      grid: chartTheme.grid,
      crosshair: chartTheme.crosshair,
      rightPriceScale: chartTheme.rightPriceScale,
      timeScale: {
        ...(chartTheme.timeScale ?? {}),
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      ...(chartTheme.candle ?? {}),
      upColor: label.color === CE_COLOR ? "#22c55e" : label.color === PE_COLOR ? "#ef4444" : "#94a3b8",
      downColor: label.color === CE_COLOR ? "#16a34a" : label.color === PE_COLOR ? "#dc2626" : "#64748b",
      borderUpColor: label.color === CE_COLOR ? "#22c55e" : label.color === PE_COLOR ? "#ef4444" : "#94a3b8",
      borderDownColor: label.color === CE_COLOR ? "#16a34a" : label.color === PE_COLOR ? "#dc2626" : "#64748b",
      wickUpColor: label.color === CE_COLOR ? "#22c55e" : label.color === PE_COLOR ? "#ef4444" : "#94a3b8",
      wickDownColor: label.color === CE_COLOR ? "#16a34a" : label.color === PE_COLOR ? "#dc2626" : "#64748b",
    });

    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // WCAG: aria-label on canvas
    const canvas = containerRef.current?.querySelector("canvas");
    if (canvas) {
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", `${label.title} price chart`);
    }

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // Register in sync group
    syncGroup.current.push(chart);

    // Time-scale sync
    chart.timeScale().subscribeVisibleTimeRangeChange((range: IRange<Time> | null) => {
      if (!range || isSyncingRef.current) return;
      isSyncingRef.current = true;
      syncGroup.current.forEach((peer) => {
        if (peer !== chart) {
          peer.timeScale().setVisibleRange(range);
        }
      });
      isSyncingRef.current = false;
    });

    // Resize observer
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      syncGroup.current = syncGroup.current.filter((c) => c !== chart);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Apply theme changes
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const { candle: _candle, ...chartOptions } = chartTheme;
    chart.applyOptions(chartOptions);
  }, [chartTheme]);

  // Fetch OHLCV data when symbol/interval changes
  useEffect(() => {
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!candle || !volume || !label.symbol) return;

    let cancelled = false;

    (async () => {
      try {
        const endDate = formatDate(new Date());
        const startDate = getStartDate(interval);
        const data = await getHistory(label.symbol, label.exchange, interval, startDate, endDate);
        if (cancelled || !Array.isArray(data) || data.length === 0) return;

        const bars = data as OHLCVBar[];
        const candles = bars.map((b) => ({
          time: b.timestamp as unknown as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        const volumes = bars.map((b) => ({
          time: b.timestamp as unknown as Time,
          value: b.volume,
          color: b.close >= b.open ? "rgba(34,197,94,0.25)" : "rgba(239,68,68,0.25)",
        }));

        candle.setData(candles);
        volume.setData(volumes);
        chartRef.current?.timeScale().fitContent();
      } catch { /* data unavailable — chart stays empty */ }
    })();

    return () => { cancelled = true; };
  }, [label.symbol, label.exchange, interval]);

  return { containerRef };
}

// ---------------------------------------------------------------------------
// Panel subcomponent
// ---------------------------------------------------------------------------

interface ChartPanelProps {
  label: PanelLabel;
  interval: string;
  syncGroup: React.MutableRefObject<IChartApi[]>;
  flex?: string;
}

const ChartPanel = memo(function ChartPanel({ label, interval, syncGroup, flex = "flex-1" }: ChartPanelProps) {
  const { containerRef } = usePanelChart({ label, interval, syncGroup });

  return (
    <div className={`${flex} flex flex-col min-w-0 overflow-hidden border-r border-border-default last:border-r-0`}>
      {/* Panel header label */}
      <div
        className="flex items-center justify-between px-2 py-1 shrink-0 border-b border-border-default"
        style={{ borderBottomColor: label.color.replace(/[\d.]+\)$/, "0.3)") }}
      >
        <div className="flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: label.color }}
          />
          <span className="text-xs font-heading font-semibold text-text-primary truncate">
            {label.title}
          </span>
        </div>
        <span className="text-xxs font-mono text-text-muted truncate max-w-28">
          {label.symbol || "—"}
        </span>
      </div>

      {/* Chart canvas container */}
      <div ref={containerRef} className="flex-1 w-full" />
    </div>
  );
});

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function ThreePanelWidget() {
  const [underlying, setUnderlying] = useState(DEFAULT_UNDERLYING);
  const [underlyingInput, setUnderlyingInput] = useState(DEFAULT_UNDERLYING);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState<string>("");
  const [strike, setStrike] = useState<string>("0");
  const [interval, setInterval] = useState("5m");
  const [loading, setLoading] = useState(false);

  const [ceLabel, setCeLabel] = useState<PanelLabel>({
    symbol: "",
    exchange: OPTION_EXCHANGE,
    title: "CE",
    color: CE_COLOR,
  });
  const [indexLabel] = useState<PanelLabel>({
    symbol: DEFAULT_UNDERLYING,
    exchange: DEFAULT_EXCHANGE,
    title: "Index",
    color: INDEX_COLOR,
  });
  const [peLabel, setPeLabel] = useState<PanelLabel>({
    symbol: "",
    exchange: OPTION_EXCHANGE,
    title: "PE",
    color: PE_COLOR,
  });
  const [indexLabelState, setIndexLabelState] = useState<PanelLabel>(indexLabel);

  // Shared time-scale sync group
  const syncGroupRef = useRef<IChartApi[]>([]);

  // ---------------------------------------------------------------------------
  // Load expiries on mount / underlying change
  // ---------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const result = await getExpiry(underlying, OPTION_EXCHANGE, "options");
        if (cancelled) return;
        const list: string[] = result?.expiry ?? [];
        setExpiries(list);
        if (list.length > 0 && !expiry) {
          setExpiry(list[0]);
        }
      } catch { /* expiry endpoint unavailable */ }
    })();

    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying]);

  // ---------------------------------------------------------------------------
  // Resolve CE/PE symbols when underlying/expiry/strike changes
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!underlying || !expiry) return;
    let cancelled = false;
    setLoading(true);

    (async () => {
      try {
        // Determine ATM strike when strike is "0" (default)
        const strikeOffset = strike === "0" ? await resolveATMStrike(underlying, expiry) : strike;

        const { ce, pe } = await resolveOptionSymbols(underlying, expiry, strikeOffset);
        if (cancelled) return;

        setCeLabel((prev) => ({
          ...prev,
          symbol: ce?.symbol ?? "",
          exchange: ce?.exchange ?? OPTION_EXCHANGE,
          title: ce ? `CE ${strikeOffset}` : "CE",
        }));
        setPeLabel((prev) => ({
          ...prev,
          symbol: pe?.symbol ?? "",
          exchange: pe?.exchange ?? OPTION_EXCHANGE,
          title: pe ? `PE ${strikeOffset}` : "PE",
        }));
      } catch { /* symbol resolution failed */ }
      finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [underlying, expiry, strike]);

  // Update index label when underlying changes
  useEffect(() => {
    setIndexLabelState({
      symbol: underlying,
      exchange: DEFAULT_EXCHANGE,
      title: underlying,
      color: INDEX_COLOR,
    });
  }, [underlying]);

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleUnderlyingCommit = useCallback(() => {
    const trimmed = underlyingInput.trim().toUpperCase();
    if (trimmed && trimmed !== underlying) {
      setUnderlying(trimmed);
      setExpiry("");
      setStrike("0");
    }
  }, [underlyingInput, underlying]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") handleUnderlyingCommit();
    },
    [handleUnderlyingCommit],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-full w-full bg-surface-base overflow-hidden" data-tour-target="threepanel">

      {/* ------------------------------------------------------------------ */}
      {/* Header                                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex items-center gap-2 px-2 py-1 bg-surface-base border-b border-border-default shrink-0 flex-wrap">

        {/* Underlying input */}
        <div className="flex items-center gap-1">
          <span className="text-xxs text-text-muted uppercase tracking-wider">Underlying</span>
          <Input
            value={underlyingInput}
            onChange={(e) => setUnderlyingInput(e.target.value.toUpperCase())}
            onBlur={handleUnderlyingCommit}
            onKeyDown={handleKeyDown}
            className="h-7 w-24 text-xs font-mono uppercase bg-surface-card border-border-default"
            placeholder="NIFTY"
            spellCheck={false}
          />
        </div>

        {/* Expiry selector */}
        <div className="flex items-center gap-1">
          <span className="text-xxs text-text-muted uppercase tracking-wider">Expiry</span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className="h-7 px-2 text-xs font-mono bg-surface-card border-border-default gap-1 min-w-22"
              >
                {expiry || "—"}
                <ChevronDown size={11} className="text-text-muted" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="max-h-56 overflow-y-auto bg-surface-card border-border-default text-text-primary"
            >
              {expiries.length === 0 && (
                <DropdownMenuItem disabled className="text-xs text-text-muted">
                  No expiries available
                </DropdownMenuItem>
              )}
              {expiries.map((e) => (
                <DropdownMenuItem
                  key={e}
                  className="text-xs font-mono"
                  onSelect={() => setExpiry(e)}
                >
                  {e}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Strike input */}
        <div className="flex items-center gap-1">
          <span className="text-xxs text-text-muted uppercase tracking-wider">Strike</span>
          <Input
            value={strike}
            onChange={(e) => setStrike(e.target.value)}
            onBlur={() => { /* trigger re-resolve via effect */ }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                // force re-run by toggling and restoring is not needed —
                // the effect re-runs when `strike` state changes on blur
                const el = e.target as HTMLInputElement;
                el.blur();
              }
            }}
            className="h-7 w-20 text-xs font-mono bg-surface-card border-border-default"
            placeholder="ATM"
          />
        </div>

        {/* Interval pills */}
        <div className="flex items-center gap-0.5 ml-auto">
          {INTERVALS.map((iv) => (
            <button
              key={iv}
              onClick={() => setInterval(iv)}
              className={`px-2 py-0.5 text-xs font-mono rounded transition-colors ${
                interval === iv
                  ? "bg-accent/15 text-accent border border-accent/40"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {iv}
            </button>
          ))}
        </div>

        {/* Loading indicator */}
        {loading && (
          <RefreshCw size={12} className="text-text-muted animate-spin shrink-0" />
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Three-panel chart area                                              */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        <ChartPanel
          key={`ce-${ceLabel.symbol}-${interval}`}
          label={ceLabel}
          interval={interval}
          syncGroup={syncGroupRef}
          flex="flex-1"
        />
        <ChartPanel
          key={`index-${indexLabelState.symbol}-${interval}`}
          label={indexLabelState}
          interval={interval}
          syncGroup={syncGroupRef}
          flex="flex-[1.5]"
        />
        <ChartPanel
          key={`pe-${peLabel.symbol}-${interval}`}
          label={peLabel}
          interval={interval}
          syncGroup={syncGroupRef}
          flex="flex-1"
        />
      </div>
    </div>
  );
}

export default memo(ThreePanelWidget);
