/**
 * GammaDensityWidget — dealer gamma density surface (DP2).
 *
 * Renders the per-strike Γ×OI density at two horizons (intraday sharper,
 * to-expiry wider) with the ±1σ / ±2σ convexity-zone reference lines around
 * spot. Stat cards surface ATM IV, the daily expected move, and the peak-density
 * ("gamma wall") strikes. Live data is gated on a connected session; otherwise a
 * clearly-marked sample surface renders behind a preview teaser.
 */

import { memo, useMemo, useState } from "react";
import { ChevronDown, RefreshCw, Loader2 } from "lucide-react";
import { FlintMultiLineChart } from "@flinttrade/design-system";
import { useGammaDensity } from "./useGammaDensity";
import { SAMPLE_GAMMA_DENSITY } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const SYMBOL_EXCHANGE: Record<string, string> = {
  NIFTY: "NFO",
  BANKNIFTY: "NFO",
  FINNIFTY: "NFO",
  MIDCPNIFTY: "NFO",
  SENSEX: "BFO",
};

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

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

function GammaDensityWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const { data: liveData, isLoading, isFetching, refetch } = useGammaDensity(symbol, exchange, "", isConnected);
  const data = isConnected && liveData ? liveData : SAMPLE_GAMMA_DENSITY;
  const isSample = !(isConnected && liveData);

  const chartState = useMemo(() => {
    const rows = data.strikes;
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
  }, [data]);

  const refLines = useMemo(
    () => [
      { axis: "x" as const, value: data.spot_price, color: "var(--color-primary, #818cf8)", dash: "4,3" },
      { axis: "x" as const, value: data.intraday_band.one_sigma_low, color: "#22c55e", dash: "2,3" },
      { axis: "x" as const, value: data.intraday_band.one_sigma_high, color: "#22c55e", dash: "2,3" },
    ],
    [data],
  );

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Gamma Density</h3>
          <p className="text-[10px] text-text-muted">
            Γ×OI · {data.dte_days.toFixed(0)}d
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Selector value={symbol} options={SYMBOLS} onChange={setSymbol} />
          {isConnected && (
            <button
              type="button"
              onClick={() => void refetch()}
              className="p-1 rounded hover:bg-surface-hover text-text-muted"
              aria-label="Refresh gamma density"
            >
              {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <StatCard label="ATM IV" value={`${data.atm_iv.toFixed(1)}%`} />
        <StatCard label="Daily 1σ" value={`±${INR.format(data.intraday_band.sigma_move)}`} hint={`${INR.format(data.intraday_band.one_sigma_low)}–${INR.format(data.intraday_band.one_sigma_high)}`} />
        <StatCard label="Gamma wall" value={data.peak_expiry_strike !== null ? INR.format(data.peak_expiry_strike) : "—"} hint="peak density" />
      </div>

      {isLoading && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : chartState ? (
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
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Gamma Density" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(GammaDensityWidget);
