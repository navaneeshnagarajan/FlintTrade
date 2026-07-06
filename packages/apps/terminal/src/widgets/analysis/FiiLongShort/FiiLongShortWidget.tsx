/**
 * FiiLongShortWidget — FII long/short positioning across F&O segments (DP1).
 *
 * Features:
 *   - Aggregate futures directional bias gauge (long % of futures OI) with a
 *     plain-English label (Strongly Long … Strongly Short)
 *   - Per-segment table: long / short OI, net, long-short ratio, long %
 *   - Derived server-side from the NSE participant-OI already captured by the
 *     FII/DII tracker — no extra broker connection needed for the data itself,
 *     but live refresh is gated on a connected session; otherwise sample data.
 */

import { memo, useMemo } from "react";
import { RefreshCw, Loader2, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useFiiLongShort } from "./useFiiLongShort";
import { SAMPLE_FII_LONG_SHORT } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { FiiBiasLabel, FiiLongShortSegment } from "@/services/ftApi.screener";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const OI_FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtOi(v: number): string {
  return OI_FMT.format(v);
}

function fmtNet(v: number): string {
  return (v >= 0 ? "+" : "") + OI_FMT.format(v);
}

/** Colour token + icon for a directional bias label. */
function biasStyle(label: FiiBiasLabel): { cls: string; Icon: typeof TrendingUp } {
  if (label === "Strongly Long" || label === "Long") {
    return { cls: "text-green-500", Icon: TrendingUp };
  }
  if (label === "Strongly Short" || label === "Short") {
    return { cls: "text-red-500", Icon: TrendingDown };
  }
  return { cls: "text-text-muted", Icon: Minus };
}

// ---------------------------------------------------------------------------
// Segment row
// ---------------------------------------------------------------------------

function SegmentRow({ seg }: { seg: FiiLongShortSegment }) {
  const netCls = seg.net > 0 ? "text-green-500" : seg.net < 0 ? "text-red-500" : "text-text-muted";
  // long % fill for the mini bar (0–100)
  const longPct = Math.max(0, Math.min(100, seg.long_pct));
  return (
    <tr className="border-b border-border-default/50 last:border-0">
      <td className="py-1.5 pr-2 text-text-primary">{seg.label}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-green-500">{fmtOi(seg.long)}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-red-500">{fmtOi(seg.short)}</td>
      <td className={`py-1.5 px-2 text-right font-mono tabular-nums ${netCls}`}>{fmtNet(seg.net)}</td>
      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-text-primary">
        {seg.ls_ratio.toFixed(2)}
      </td>
      <td className="py-1.5 pl-2 w-24">
        <div className="flex items-center gap-1.5">
          <div className="flex-1 h-1.5 rounded-full bg-red-500/25 overflow-hidden">
            <div className="h-full bg-green-500/70" style={{ width: `${longPct}%` }} />
          </div>
          <span className="font-mono tabular-nums text-text-muted text-[10px] w-8 text-right">
            {seg.long_pct.toFixed(0)}%
          </span>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function FiiLongShortWidget() {
  const isConnected = useBrokerConnected();
  const { data: liveData, isLoading, isFetching, refetch } = useFiiLongShort(isConnected);

  const response = isConnected ? liveData : { is_sample_data: true, ratio: SAMPLE_FII_LONG_SHORT };
  const ratio = response?.ratio ?? SAMPLE_FII_LONG_SHORT;
  const isSample = response?.is_sample_data ?? true;

  const { cls, Icon } = useMemo(() => biasStyle(ratio.bias_label), [ratio.bias_label]);
  const biasFill = Math.max(0, Math.min(100, ratio.futures_bias));

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">FII Long/Short</h3>
          <p className="text-[10px] text-text-muted">
            Participant OI · {ratio.trade_date || "—"}
            {isSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        {isConnected && (
          <button
            type="button"
            onClick={() => void refetch()}
            className="p-1 rounded hover:bg-surface-hover text-text-muted"
            aria-label="Refresh FII long/short data"
          >
            {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
          </button>
        )}
      </div>

      {/* Aggregate futures bias gauge */}
      <div className="rounded-md border border-border-default bg-surface-card p-2.5">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] uppercase tracking-wide text-text-muted">Futures bias</span>
          <span className={`flex items-center gap-1 font-semibold ${cls}`}>
            <Icon size={13} />
            {ratio.bias_label}
          </span>
        </div>
        <div className="relative h-2 rounded-full bg-red-500/25 overflow-hidden">
          <div className="h-full bg-green-500/70" style={{ width: `${biasFill}%` }} />
          <div className="absolute inset-y-0 left-1/2 w-px bg-text-muted/50" />
        </div>
        <div className="flex justify-between mt-1 text-[10px] text-text-muted font-mono tabular-nums">
          <span>Short {fmtOi(ratio.futures_short)}</span>
          <span className={cls}>{ratio.futures_bias.toFixed(1)}% long</span>
          <span>Long {fmtOi(ratio.futures_long)}</span>
        </div>
      </div>

      {/* Per-segment table */}
      {isLoading && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                <th className="py-1 pr-2 text-left font-medium">Segment</th>
                <th className="py-1 px-2 text-right font-medium">Long</th>
                <th className="py-1 px-2 text-right font-medium">Short</th>
                <th className="py-1 px-2 text-right font-medium">Net</th>
                <th className="py-1 px-2 text-right font-medium">L/S</th>
                <th className="py-1 pl-2 text-left font-medium">Long %</th>
              </tr>
            </thead>
            <tbody>
              {ratio.segments.map((seg) => (
                <SegmentRow key={seg.segment} seg={seg} />
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
    <FeatureTeaser status="preview" featureName="FII Long/Short" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(FiiLongShortWidget);
