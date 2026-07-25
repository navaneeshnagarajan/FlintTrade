/**
 * FlowsTab — FII/DII flows and positioning for the Market Overview widget.
 *
 * Union of three surfaces:
 *   - FiiLongShort widget: the aggregate futures directional-bias gauge and
 *     the per-segment FII long/short table (server-aggregated, with L/S
 *     ratio and long %), via the same /screener/fii-long-short service call.
 *   - Market Intelligence's FII/DII flows tab (the live wiring): the 10-day
 *     cash-segment table and the DII derivative-positioning rows, via the
 *     same getFiiDiiData(10) call — reused, not duplicated. The FII
 *     derivative rows of that tab's stats table are dominated by the
 *     long/short segment table above (same OI fields plus ratio and long %).
 *   - MarketSummary's FII/DII net section: dominated by the cash table's
 *     latest row (same fii_net/dii_net fields with buy/sell detail).
 *
 * Provenance: each of the two sources carries its own fail-closed
 * Live/Sample chip; sample fallbacks are disclosed.
 */

import { memo, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Loader2, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useFiiLongShort } from "../useFiiLongShort";
import { SAMPLE_FII_DII_CASH, SAMPLE_FII_LONG_SHORT } from "../sampleData";
import { ProvChip } from "../shared";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { getFiiDiiData } from "@/services/ftApi.screener";
import type { FiiBiasLabel, FiiDiiSnapshot, FiiLongShortSegment } from "@/services/ftApi.screener";
import type { FiiDiiCashRow } from "../types";

/** Days of cash-segment history to request from the backend. */
const FII_DII_DAYS = 10;

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

function formatCr(v: number): string {
  if (Math.abs(v) >= 10000) return `₹${(v / 10000).toFixed(0)}k Cr`;
  if (Math.abs(v) >= 1000) return `₹${(v / 1000).toFixed(1)}k Cr`;
  return `₹${v.toFixed(0)} Cr`;
}

function netColor(v: number): string {
  return v >= 0 ? "text-profit" : "text-loss";
}

function formatOINum(v: number): string {
  if (Math.abs(v) >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
  if (Math.abs(v) >= 100000) return `${(v / 100000).toFixed(2)} L`;
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)} K`;
  return v.toString();
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
// FII long/short segment row
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
// Cash-segment table (from the Market Intelligence flows tab)
// ---------------------------------------------------------------------------

function CashSegmentTable({ rows }: { rows: FiiDiiCashRow[] }) {
  return (
    <div className="rounded-md border border-border-default overflow-auto">
      <table className="w-full text-xs" aria-label="FII/DII capital market segment">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
            {["Date", "FII Buy", "FII Sell", "FII Net", "DII Buy", "DII Sell", "DII Net"].map((h) => (
              <th key={h} className="py-1 px-2 text-right first:text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.date} className="border-b border-border-default/50 last:border-0">
              <td className="py-1.5 px-2 font-mono text-text-secondary">{row.date}</td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatCr(row.fii_buy)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatCr(row.fii_sell)}</td>
              <td className={`py-1.5 px-2 text-right font-mono font-semibold ${netColor(row.fii_net)}`}>
                {row.fii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.fii_net))}
              </td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatCr(row.dii_buy)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatCr(row.dii_sell)}</td>
              <td className={`py-1.5 px-2 text-right font-mono font-semibold ${netColor(row.dii_net)}`}>
                {row.dii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.dii_net))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DII derivative positioning (the rows the long/short table does not cover)
// ---------------------------------------------------------------------------

function DiiDerivativeTable({ snapshot }: { snapshot: FiiDiiSnapshot }) {
  const rows = [
    { label: "DII Index Futures", long: snapshot.dii_idx_fut_long, short: snapshot.dii_idx_fut_short, net: snapshot.dii_idx_fut_net },
    { label: "DII Stock Futures", long: snapshot.dii_stk_fut_long, short: snapshot.dii_stk_fut_short, net: snapshot.dii_stk_fut_net },
  ];
  return (
    <div className="rounded-md border border-border-default overflow-auto">
      <table className="w-full text-xs" aria-label="DII derivative positioning">
        <thead>
          <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
            {["Segment", "Long", "Short", "Net"].map((h) => (
              <th key={h} className="py-1 px-2 text-right first:text-left font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-b border-border-default/50 last:border-0">
              <td className="py-1.5 px-2 text-text-secondary">{r.label}</td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatOINum(r.long)}</td>
              <td className="py-1.5 px-2 text-right font-mono text-text-primary">{formatOINum(r.short)}</td>
              <td className={`py-1.5 px-2 text-right font-mono font-semibold ${netColor(r.net)}`}>
                {r.net >= 0 ? "+" : ""}{formatOINum(Math.abs(r.net))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab
// ---------------------------------------------------------------------------

function FlowsTab() {
  const isConnected = useBrokerConnected();
  const longShortQuery = useFiiLongShort(isConnected);
  const {
    data: longShortData,
    isLoading: longShortLoading,
    isFetching: longShortFetching,
    refetch: refetchLongShort,
  } = longShortQuery;

  const fiiDiiQuery = useQuery({
    queryKey: ["marketOverview", "fii-dii", FII_DII_DAYS],
    queryFn: () => getFiiDiiData(FII_DII_DAYS),
    enabled: isConnected,
    staleTime: 5 * 60_000,
    refetchInterval: isConnected ? 5 * 60_000 : false,
  });

  // --- FII long/short (fail-closed) ---
  const response = isConnected
    ? longShortData
    : { is_sample_data: true, ratio: SAMPLE_FII_LONG_SHORT };
  const ratio = response?.ratio ?? SAMPLE_FII_LONG_SHORT;
  const longShortSample = response?.is_sample_data !== false;

  const { cls, Icon } = useMemo(() => biasStyle(ratio.bias_label), [ratio.bias_label]);
  const biasFill = Math.max(0, Math.min(100, ratio.futures_bias));

  // --- FII/DII cash flows (fail-closed) ---
  const fiiDiiLive = isConnected && fiiDiiQuery.data?.is_sample_data === false;
  const snapshots: FiiDiiSnapshot[] = fiiDiiQuery.data?.trend?.snapshots?.length
    ? fiiDiiQuery.data.trend.snapshots
    : fiiDiiQuery.data?.latest
      ? [fiiDiiQuery.data.latest]
      : [];
  const cashRows: FiiDiiCashRow[] = snapshots.length
    ? snapshots.map((s) => ({
        date: s.trade_date,
        fii_buy: s.fii_buy,
        fii_sell: s.fii_sell,
        fii_net: s.fii_net,
        dii_buy: s.dii_buy,
        dii_sell: s.dii_sell,
        dii_net: s.dii_net,
      }))
    : SAMPLE_FII_DII_CASH;

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">FII Long/Short</h3>
          <p className="text-[10px] text-text-muted">
            Participant OI · {ratio.trade_date || "—"}
            {longShortSample && <span className="ml-1 text-amber-500">· Demo data</span>}
          </p>
        </div>
        {isConnected && (
          <button
            type="button"
            onClick={() => void refetchLongShort()}
            className="p-1 rounded hover:bg-surface-hover text-text-muted"
            aria-label="Refresh FII long/short data"
          >
            {longShortFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
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
      {longShortLoading && isConnected ? (
        <div className="flex items-center justify-center py-6 text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-xs" aria-label="FII long/short by segment">
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

      {/* Cash-segment flows */}
      <div>
        <p className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
          Capital Market Segment (₹ Cr)
          <ProvChip live={fiiDiiLive} />
        </p>
        <CashSegmentTable rows={cashRows} />
      </div>

      {/* DII derivative positioning — the rows the FII table above does not
          carry. Only rendered from a real snapshot; never fabricated. */}
      {fiiDiiQuery.data?.latest && (
        <div>
          <p className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
            DII Derivative Positioning — {fiiDiiQuery.data.latest.trade_date} (contracts)
            <ProvChip live={fiiDiiLive} />
          </p>
          <DiiDerivativeTable snapshot={fiiDiiQuery.data.latest} />
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

export default memo(FlowsTab);
