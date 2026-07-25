/**
 * ContributionTab — index movers by constituent weight (W7), carried over
 * from the retired IndexContribution widget (decision D9: it is the
 * seventh surface folded into Market Overview).
 *
 * Decomposes an index's day move into its constituents' point contributions
 * (free-float weight × return), ranked largest-mover first, with a diverging
 * bar showing each name's push on the index. Weights are indicative (NSE
 * factsheet, as-of date shown). Live via a one-shot constituent quote sweep
 * when connected; otherwise a clearly-marked sample (fail-closed: an absent
 * is_sample_data flag is sample).
 */

import { memo, useMemo, useState } from "react";
import { ChevronDown, RefreshCw, Loader2, TrendingUp, TrendingDown } from "lucide-react";
import { useIndexContribution } from "../useIndexContribution";
import { SAMPLE_INDEX_CONTRIBUTION } from "../sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { IndexConstituent } from "@/services/ftApi.screener";

const INDICES = ["NIFTY", "BANKNIFTY"];

function Selector({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-20"
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

function ConstituentRow({ c, maxAbs }: { c: IndexConstituent; maxAbs: number }) {
  const positive = c.contribution_pct >= 0;
  const widthPct = maxAbs > 0 ? (Math.abs(c.contribution_pct) / maxAbs) * 100 : 0;
  return (
    <tr className="border-b border-border-default/50 last:border-0">
      <td className="py-1.5 pr-2 text-text-primary font-medium">{c.symbol}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-muted">{c.weight.toFixed(1)}%</td>
      <td className={`py-1.5 px-2 text-right font-mono tabular-nums ${positive ? "text-green-500" : "text-red-500"}`}>
        {positive ? "+" : ""}{c.change_pct.toFixed(2)}%
      </td>
      <td className="py-1.5 pl-2 w-28">
        <div className="flex items-center gap-1.5">
          {/* Diverging bar: left half red, right half green, anchored at centre. */}
          <div className="relative flex-1 h-2 flex items-center">
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-text-muted/40" />
            {positive ? (
              <div className="absolute left-1/2 h-1.5 bg-green-500/70 rounded-r" style={{ width: `${widthPct / 2}%` }} />
            ) : (
              <div className="absolute right-1/2 h-1.5 bg-red-500/70 rounded-l" style={{ width: `${widthPct / 2}%` }} />
            )}
          </div>
          <span className={`font-mono tabular-nums text-[10px] w-12 text-right ${positive ? "text-green-500" : "text-red-500"}`}>
            {positive ? "+" : ""}{c.contribution_points.toFixed(1)}
          </span>
        </div>
      </td>
    </tr>
  );
}

function ContributionTab() {
  const [index, setIndex] = useState("NIFTY");
  const isConnected = useBrokerConnected();
  const { data: live, isLoading, isFetching, refetch } = useIndexContribution(index, isConnected);

  const response = isConnected && live ? live : { is_sample_data: true, contribution: SAMPLE_INDEX_CONTRIBUTION };
  const contribution = response.contribution;
  const isSample = response.is_sample_data !== false;

  const maxAbs = useMemo(
    () => contribution.constituents.reduce((m, c) => Math.max(m, Math.abs(c.contribution_pct)), 0),
    [contribution],
  );

  const changePositive = contribution.index_change_pct >= 0;

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">Index Contribution</h3>
          <p className="text-[10px] text-text-muted">
            Weights as of {contribution.weights_as_of}
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Selector value={index} options={INDICES} onChange={setIndex} />
          {isConnected && (
            <button
              type="button"
              onClick={() => void refetch()}
              className="p-1 rounded hover:bg-surface-hover text-text-muted"
              aria-label="Refresh index contribution"
            >
              {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            </button>
          )}
        </div>
      </div>

      {/* Index headline */}
      <div className="rounded-md border border-border-default bg-surface-card p-2.5 flex items-center justify-between">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-text-muted">{contribution.index_name}</div>
          <div className="font-mono tabular-nums text-lg text-text-primary">
            {contribution.index_level > 0 ? contribution.index_level.toLocaleString("en-IN") : "—"}
          </div>
        </div>
        <div className={`flex flex-col items-end ${changePositive ? "text-green-500" : "text-red-500"}`}>
          <span className="flex items-center gap-1 font-semibold">
            {changePositive ? <TrendingUp size={13} /> : <TrendingDown size={13} />}
            {changePositive ? "+" : ""}{contribution.index_change_pct.toFixed(2)}%
          </span>
          <span className="text-[10px] font-mono tabular-nums">
            {changePositive ? "+" : ""}{contribution.index_change_points.toFixed(1)} pts
          </span>
        </div>
      </div>

      <div className="flex gap-3 text-[10px] text-text-muted">
        <span className="text-green-500">{contribution.advancers} advancing</span>
        <span className="text-red-500">{contribution.decliners} declining</span>
      </div>

      {isLoading && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                <th className="py-1 pr-2 text-left font-medium">Scrip</th>
                <th className="py-1 px-2 text-right font-medium">Wt</th>
                <th className="py-1 px-2 text-right font-medium">Chg</th>
                <th className="py-1 pl-2 text-left font-medium">Contribution (pts)</th>
              </tr>
            </thead>
            <tbody>
              {contribution.constituents.map((c) => (
                <ConstituentRow key={c.symbol} c={c} maxAbs={maxAbs} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Index Contribution" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(ContributionTab);
