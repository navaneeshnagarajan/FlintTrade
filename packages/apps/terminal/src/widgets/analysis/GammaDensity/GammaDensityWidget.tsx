/**
 * GammaDensityWidget — the canonical "Dealer Gamma" surface (merge 2.3).
 *
 * One widget, two views over ONE option-chain plane:
 *
 *   • "density" (default) — per-strike Γ×OI density at two horizons (intraday
 *     sharper, to-expiry wider) with the ±1σ convexity-zone reference lines
 *     around spot, plus the ATM IV / daily-1σ / gamma-wall stat cards.
 *   • "exposure" — the presentation of the retired standalone GEX Dashboard:
 *     call-GEX vs put-GEX grouped bars per strike, the signed Net GEX area
 *     with its positive/negative zero-fill split, and the dealer-zone footer.
 *
 * The two views read the two EXISTING endpoints — POST /api/v1/gammadensity
 * and POST /api/v1/gex — which the backend derives from the same snapshot: the
 * gammadensity route's docstring states it "Reuses the same option-chain
 * snapshot the GEX endpoint builds — no extra broker fetch". Two panels over
 * one snapshot was the duplication; this is the merge. No third fetch was
 * added, and only the ACTIVE view's query is enabled, so the merge does not
 * double the 30s market-hours poll.
 *
 * The initial view comes from the workspace panel parameter `params.view`,
 * which is how the retired `gex` widget id resolves to its original look.
 * Toggling writes the choice back into the panel params so saved layouts
 * round-trip.
 *
 * DROPPED IN THE MERGE — the GEX widget's gamma-flip annotation (the amber
 * "Flip: <strike>" arrow, the dotted vertical line, and the footer chip). The
 * server sets `gamma_flip_strike = None` unconditionally
 * (packages/services/screener/src/flinttrade_screener/analysis_routes.py:
 * "A true gamma-flip level requires repricing the whole chain over a spot
 * sweep. A per-strike sign change at one fixed spot is not that quantity.").
 * The flip UI was therefore unreachable code advertising a level the backend
 * cannot compute. Removing dead UI that implies non-existent data is not a
 * capability loss — nothing was ever rendered by it, and its presence made the
 * widget look as though the level merely happened to be missing today. If the
 * backend ever computes a real flip level, re-add the annotation then.
 *
 * Provenance is FAIL-CLOSED for both payloads: a response counts as live only
 * when it explicitly attests `is_sample_data: false`. A missing, malformed or
 * true flag renders the "Demo data" affordance. (The retired GEX widget's
 * check originally failed OPEN — a payload that omitted the flag rendered as
 * live. That posture does not survive here.)
 */

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { AlertCircle, BarChart3, ChevronDown, LineChart, Loader2, RefreshCw } from "lucide-react";
import type { WidgetProps } from "@/types/widgets";
import type { Data, Layout } from "plotly.js";
import { FlintMultiLineChart } from "@flinttrade/design-system";
import { useGammaDensity } from "./useGammaDensity";
import { useGEX } from "./useGEX";
import { SAMPLE_GAMMA_DENSITY, SAMPLE_GEX_DATA } from "./sampleData";
import { PlotlyChart } from "@/components/charts/PlotlyChart";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { getExpiry } from "@/services/api";
import { selectFutureExpiry } from "@/lib/optionSymbols";

/**
 * Re-exported for this widget's own tests, which pin the IST calendar
 * semantics. The implementation moved to `@/lib/optionSymbols` when the IV
 * Smile merge needed the same nearest-future-expiry choice.
 */
export { selectFutureExpiry };

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const SYMBOL_EXCHANGE: Record<string, string> = {
  NIFTY: "NFO",
  BANKNIFTY: "NFO",
  FINNIFTY: "NFO",
  MIDCPNIFTY: "NFO",
  SENSEX: "BFO",
};

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

// ---------------------------------------------------------------------------
// View mode (workspace panel params)
// ---------------------------------------------------------------------------

/** Presentation of the dealer-gamma plane. `exposure` is the retired GEX widget. */
export type DealerGammaView = "density" | "exposure";

const VIEW_MODES: readonly DealerGammaView[] = ["density", "exposure"];

const VIEW_LABELS: Record<DealerGammaView, string> = {
  density: "Gamma density view",
  exposure: "Gamma exposure view",
};

function isDealerGammaView(value: unknown): value is DealerGammaView {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the workspace `params.view` panel parameter, defaulting to density. */
export function resolveDealerGammaView(value: unknown): DealerGammaView {
  return isDealerGammaView(value) ? value : "density";
}

interface DealerGammaPanelParams {
  /** Initial view — how the retired `gex` id selects its original look. */
  view?: string;
}

// ---------------------------------------------------------------------------
// Provenance + formatting helpers
// ---------------------------------------------------------------------------

/**
 * Live provenance is accepted only when the backend explicitly attests
 * `is_sample_data: false`. Missing or malformed flags fail closed as sample.
 *
 * ONE check for BOTH payloads: the density surface and the gamma-exposure
 * decomposition come off the same snapshot and are held to the same standard.
 */
function carriesExplicitLiveFlag(payload: unknown): boolean {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as { is_sample_data?: unknown }).is_sample_data === false
  );
}

/** Read a CSS custom property from the document root at call time. */
function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

function fmtGEX(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "+";
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Selector({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-16"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${opt === value ? "text-accent" : "text-text-primary"}`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border-default bg-surface-card px-2.5 py-1.5">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-sm font-mono tabular-nums text-text-primary">{value}</div>
      {hint && <div className="text-[10px] text-text-muted">{hint}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GammaDensityWidget(props: WidgetProps) {
  const panelParams = props.params as DealerGammaPanelParams | undefined;
  const [view, setView] = useState<DealerGammaView>(() => resolveDealerGammaView(panelParams?.view));
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiry, setExpiry] = useState<string | null>(null);
  const [expiryLoading, setExpiryLoading] = useState(false);
  const [expiryUnavailable, setExpiryUnavailable] = useState(false);
  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  // Persist the chosen view into the panel params so a saved layout reopens in
  // the same mode (this is also how the retired `gex` id survives).
  const handleViewChange = useCallback((next: DealerGammaView) => {
    setView((current) => {
      if (current === next) return current;
      props.api.updateParameters({ ...(panelParams ?? {}), view: next });
      return next;
    });
  }, [panelParams, props.api]);

  useEffect(() => {
    setExpiry(null);
    setExpiryUnavailable(false);
    if (!isConnected) {
      setExpiryLoading(false);
      return;
    }

    let cancelled = false;
    setExpiryLoading(true);
    void getExpiry(symbol, exchange, "options")
      .then((response) => {
        if (cancelled) return;
        const expiries = Array.isArray(response) ? response : response.expiry ?? [];
        const selected = selectFutureExpiry(expiries);
        setExpiry(selected);
        setExpiryUnavailable(selected === null);
      })
      .catch(() => {
        if (!cancelled) setExpiryUnavailable(true);
      })
      .finally(() => {
        if (!cancelled) setExpiryLoading(false);
      });
    return () => { cancelled = true; };
  }, [exchange, isConnected, symbol]);

  // Exactly one endpoint is live at a time — the one the operator is looking
  // at. Both already existed; the merge adds none and doubles no poll.
  const densityQueryEnabled = isConnected && expiry !== null && view === "density";
  const exposureQueryEnabled = isConnected && expiry !== null && view === "exposure";

  const {
    data: liveDensity,
    isLoading: densityLoading,
    isFetching: densityFetching,
    isError: densityIsError,
    isRefetchError: densityRefetchError,
    error: densityError,
    refetch: refetchDensity,
  } = useGammaDensity(symbol, exchange, expiry ?? "", densityQueryEnabled);

  const {
    data: liveExposure,
    isLoading: exposureLoading,
    isFetching: exposureFetching,
    isError: exposureIsError,
    isRefetchError: exposureRefetchError,
    error: exposureError,
    refetch: refetchExposure,
  } = useGEX(symbol, exchange, expiry ?? "", exposureQueryEnabled);

  // A payload that errored — including a refetch error over a previously good
  // one — is never shown as live: TanStack retains the last successful data,
  // which would otherwise keep a stale surface labelled live indefinitely.
  const usableDensity = densityQueryEnabled && !densityIsError && !densityRefetchError ? liveDensity : undefined;
  const densityData = isConnected && usableDensity ? usableDensity : SAMPLE_GAMMA_DENSITY;
  const densityIsSample = !isConnected || !usableDensity || !carriesExplicitLiveFlag(usableDensity);

  const usableExposure = exposureQueryEnabled && !exposureIsError && !exposureRefetchError ? liveExposure : undefined;
  const exposureData = isConnected && usableExposure ? usableExposure : SAMPLE_GEX_DATA;
  const exposureIsSample = !isConnected || !usableExposure || !carriesExplicitLiveFlag(usableExposure);

  const isDensityView = view === "density";
  const isSample = isDensityView ? densityIsSample : exposureIsSample;
  const isFetching = isDensityView ? densityFetching : exposureFetching;
  const isLoading = isDensityView ? densityLoading : exposureLoading;
  const queryEnabled = isDensityView ? densityQueryEnabled : exposureQueryEnabled;
  const failed = isDensityView
    ? densityIsError || densityRefetchError
    : exposureIsError || exposureRefetchError;
  const failure = isDensityView ? densityError : exposureError;
  const refetchActive = isDensityView ? refetchDensity : refetchExposure;

  const chartState = useMemo(() => {
    if (view !== "density") return null;
    const rows = densityData.strikes;
    if (!rows.length) return null;
    const strikes = rows.map((r) => r.strike);
    const xMin = Math.min(...strikes);
    const xMax = Math.max(...strikes);
    const yMax = Math.max(
      1,
      ...rows.map((r) => Math.max(r.density_intraday, r.density_expiry)),
    ) * 1.1;
    const tickEvery = Math.max(1, Math.ceil(rows.length / 5));
    return {
      xDomain: [xMin, xMax] as const,
      yDomain: [0, yMax] as const,
      xTicks: strikes.filter((_, i) => i % tickEvery === 0),
      yTicks: [0, Math.round(yMax / 2), Math.round(yMax)],
      series: [
        {
          id: "expiry",
          label: "To Expiry",
          color: "#f59e0b",
          points: rows.map((r) => ({ x: r.strike, y: r.density_expiry, label: `${INR.format(r.strike)} · to-expiry ${r.density_expiry.toFixed(0)}` })),
        },
        {
          id: "intraday",
          label: "Intraday",
          color: "#0ea5e9",
          points: rows.map((r) => ({ x: r.strike, y: r.density_intraday, label: `${INR.format(r.strike)} · intraday ${r.density_intraday.toFixed(0)}` })),
        },
      ],
    };
  }, [densityData, view]);

  const refLines = useMemo(
    () => [
      { axis: "x" as const, value: densityData.spot_price, color: "var(--color-primary, #818cf8)", dash: "4,3" },
      { axis: "x" as const, value: densityData.intraday_band.one_sigma_low, color: "#22c55e", dash: "2,3" },
      { axis: "x" as const, value: densityData.intraday_band.one_sigma_high, color: "#22c55e", dash: "2,3" },
    ],
    [densityData],
  );

  // Gamma-exposure traces: call-vs-put grouped bars plus the signed Net GEX
  // area with its positive/negative zero-fill split. Absorbed wholesale from
  // the retired GEX widget MINUS the gamma-flip annotation (see file header).
  const exposureCharts = useMemo<{
    barData: Data[];
    areaData: Data[];
    barLayout: Partial<Layout>;
    areaLayout: Partial<Layout>;
  }>(() => {
    const empty = { barData: [], areaData: [], barLayout: {}, areaLayout: {} };
    if (view !== "exposure" || !exposureData.strikes.length) return empty;

    const strikes = exposureData.strikes.map((s) => s.strike);
    const callGex = exposureData.strikes.map((s) => s.call_gex);
    const putGex = exposureData.strikes.map((s) => s.put_gex);
    const netGex = exposureData.strikes.map((s) => s.net_gex);
    const hasAtm = strikes.includes(exposureData.atm_strike);

    const barData: Data[] = [
      {
        type: "bar",
        name: "Call GEX",
        x: strikes,
        y: callGex,
        marker: { color: "rgba(34,197,94,0.75)" },
        hovertemplate: "Strike: %{x}<br>Call GEX: %{y:.2e}<extra></extra>",
      } as Data,
      {
        type: "bar",
        name: "Put GEX",
        x: strikes,
        y: putGex,
        marker: { color: "rgba(239,68,68,0.75)" },
        hovertemplate: "Strike: %{x}<br>Put GEX: %{y:.2e}<extra></extra>",
      } as Data,
    ];

    const barLayout: Partial<Layout> = {
      barmode: "group",
      xaxis: { title: { text: "Strike" }, tickformat: ",.0f" },
      yaxis: { title: { text: "GEX" }, tickformat: ".2s" },
      margin: { t: 20, r: 10, b: 40, l: 55 },
      shapes: hasAtm
        ? [
            {
              type: "line",
              x0: exposureData.atm_strike,
              x1: exposureData.atm_strike,
              y0: 0,
              y1: 1,
              yref: "paper" as const,
              line: { color: "#6366f1", width: 1, dash: "dash" },
            },
          ]
        : [],
      annotations: hasAtm
        ? [
            {
              x: exposureData.atm_strike,
              y: 1,
              yref: "paper" as const,
              text: "ATM",
              showarrow: false,
              font: { size: 9, color: "#6366f1" },
              yanchor: "top",
            },
          ]
        : [],
    };

    // Net GEX — split into above-zero (green) and below-zero (red) fills.
    const positiveY = netGex.map((v) => (v >= 0 ? v : 0));
    const negativeY = netGex.map((v) => (v < 0 ? v : 0));

    const areaData: Data[] = [
      {
        type: "scatter",
        mode: "none",
        name: "Net GEX (pos)",
        x: strikes,
        y: positiveY,
        fill: "tozeroy",
        fillcolor: "rgba(34,197,94,0.25)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "none",
        name: "Net GEX (neg)",
        x: strikes,
        y: negativeY,
        fill: "tozeroy",
        fillcolor: "rgba(239,68,68,0.25)",
        hoverinfo: "skip",
      } as Data,
      {
        type: "scatter",
        mode: "lines",
        name: "Net GEX",
        x: strikes,
        y: netGex,
        line: { color: "#a0a0b8", width: 1.5 },
        hovertemplate: "Strike: %{x}<br>Net GEX: %{y:.2e}<extra></extra>",
      } as Data,
    ];

    const areaLayout: Partial<Layout> = {
      xaxis: { tickformat: ",.0f" },
      yaxis: { title: { text: "Net GEX" }, tickformat: ".2s" },
      margin: { t: 10, r: 10, b: 40, l: 55 },
      shapes: [
        {
          type: "line",
          x0: 0,
          x1: 1,
          xref: "paper" as const,
          y0: 0,
          y1: 0,
          line: { color: getThemeColor("--color-border", "#2a2a3a"), width: 1 },
        },
      ],
    };

    return { barData, areaData, barLayout, areaLayout };
  }, [exposureData, view]);

  const dealerIsLong = exposureData.dealer_zone?.toLowerCase().includes("long") ?? false;
  const hasExposureStrikes = exposureData.strikes.length > 0;

  const subtitle = isDensityView
    ? `Γ×OI · ${densityData.dte_days.toFixed(0)}d`
    : "Call / Put GEX by strike";

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Dealer Gamma</h3>
          <p className="text-[10px] text-text-muted">
            {subtitle}
            {expiry && !isSample && <span className="ml-1">· {expiry}</span>}
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
            {expiryUnavailable && <span className="ml-1 text-amber-500">· No future expiry</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Selector
            value={symbol}
            options={SYMBOLS}
            onChange={(nextSymbol) => {
              setExpiry(null);
              setExpiryUnavailable(false);
              setSymbol(nextSymbol);
            }}
          />
          <div className="flex items-center gap-0.5 rounded border border-border-default p-0.5">
            <button
              type="button"
              onClick={() => handleViewChange("density")}
              className={`flex h-5 w-5 items-center justify-center rounded transition-colors ${
                isDensityView
                  ? "bg-surface-active text-text-primary"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
              aria-pressed={isDensityView}
              aria-label={VIEW_LABELS.density}
              title={VIEW_LABELS.density}
            >
              <LineChart size={11} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => handleViewChange("exposure")}
              className={`flex h-5 w-5 items-center justify-center rounded transition-colors ${
                isDensityView
                  ? "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  : "bg-surface-active text-text-primary"
              }`}
              aria-pressed={!isDensityView}
              aria-label={VIEW_LABELS.exposure}
              title={VIEW_LABELS.exposure}
            >
              <BarChart3 size={11} aria-hidden="true" />
            </button>
          </div>
          {isConnected && (
            <button
              type="button"
              onClick={() => { if (expiry !== null) void refetchActive(); }}
              disabled={expiry === null || isFetching}
              className="p-1 rounded hover:bg-surface-hover text-text-muted disabled:opacity-40"
              aria-label="Refresh dealer gamma"
              title={expiry === null ? "No future expiry available" : "Refresh dealer gamma"}
            >
              {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            </button>
          )}
        </div>
      </div>

      {failed && (
        <div className="flex items-center gap-2 px-2 py-1 rounded bg-loss/10 border border-loss/20 text-loss">
          <AlertCircle size={11} className="flex-none" />
          <span>{(failure as Error | null)?.message ?? "Failed to load dealer gamma data"}</span>
        </div>
      )}

      {isDensityView && (
        <div className="grid grid-cols-3 gap-2">
          <StatCard label="ATM IV" value={`${densityData.atm_iv.toFixed(1)}%`} />
          <StatCard label="Daily 1σ" value={`±${INR.format(densityData.intraday_band.sigma_move)}`} hint={`${INR.format(densityData.intraday_band.one_sigma_low)}–${INR.format(densityData.intraday_band.one_sigma_high)}`} />
          <StatCard label="Gamma wall" value={densityData.peak_expiry_strike !== null ? INR.format(densityData.peak_expiry_strike) : "—"} hint="peak density" />
        </div>
      )}

      {(expiryLoading || (isLoading && queryEnabled)) && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
          <span className="sr-only">Loading dealer gamma data</span>
        </div>
      ) : isDensityView ? (
        chartState ? (
          <div className="flex-1 min-h-0">
            <div className="flex items-center gap-4 mb-1 text-[10px]">
              <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-amber-500 inline-block" /><span className="text-text-muted">To Expiry</span></span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded bg-sky-500 inline-block" /><span className="text-text-muted">Intraday</span></span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-2 rounded border border-green-500 inline-block" /><span className="text-text-muted">±1σ zone</span></span>
            </div>
            <div className="rounded-md border border-border-default bg-surface-card/40 p-2">
              <FlintMultiLineChart
                ariaLabel="Gamma density by strike at intraday and to-expiry horizons"
                series={chartState.series}
                xDomain={chartState.xDomain}
                yDomain={chartState.yDomain}
                xTicks={chartState.xTicks}
                yTicks={chartState.yTicks}
                xFormatter={(v) => INR.format(v)}
                yFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}k` : v.toFixed(0))}
                xAxisLabel="Strike"
                yAxisLabel="Γ×OI"
                referenceLines={refLines}
                width={560}
                height={220}
              />
            </div>
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-text-muted">No density data</div>
        )
      ) : hasExposureStrikes ? (
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Call GEX vs Put GEX per strike */}
          <div className="flex-1 min-h-0">
            <PlotlyChart data={exposureCharts.barData} layout={exposureCharts.barLayout} />
          </div>

          {/* Signed Net GEX area, zero-fill split */}
          <div className="flex-none h-[30%] border-t border-border-default">
            <PlotlyChart data={exposureCharts.areaData} layout={exposureCharts.areaLayout} />
          </div>

          {/* Dealer-zone footer chrome */}
          <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className="text-text-muted uppercase tracking-wide">Net GEX</span>
              <span className={`font-mono tabular-nums font-semibold ${exposureData.net_gex >= 0 ? "text-profit" : "text-loss"}`}>
                {fmtGEX(exposureData.net_gex)}
              </span>
            </div>

            <div className="flex items-center gap-1.5">
              <span className={`px-1.5 py-0.5 text-xxs font-medium rounded border ${
                dealerIsLong
                  ? "text-profit bg-profit/10 border-profit/30"
                  : "text-loss bg-loss/10 border-loss/30"
              }`}>
                {exposureData.dealer_zone || "—"}
              </span>
            </div>

            {exposureData.atm_strike > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-text-muted uppercase tracking-wide">ATM</span>
                <span className="font-mono tabular-nums text-accent">
                  {INR.format(exposureData.atm_strike)}
                </span>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="flex-1 flex items-center justify-center text-text-muted">No exposure data</div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Dealer Gamma" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(GammaDensityWidget);
