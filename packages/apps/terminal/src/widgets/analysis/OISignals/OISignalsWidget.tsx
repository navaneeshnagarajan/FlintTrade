/**
 * OISignalsWidget — Open-Interest action signals + unusual-OI activity.
 *
 * Wired to the FlintTrade screener backend:
 *   - POST /ft-api/v1/oi/analysis  → per-strike Long Build-up / Short Covering /
 *     Short Build-up / Long Unwinding classification (given price direction).
 *   - POST /ft-api/v1/oi/unusual   → z-score OI-change outliers.
 *
 * Live when a broker is connected (the backend uses the live option chain);
 * otherwise a badged sample so the widget is usable in explore mode. No
 * fabricated "live" data ever reaches an order path — this is read-only analysis.
 */

import { useState, memo } from "react";
import { Activity, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import {
  getOIChangeAnalysis,
  getUnusualOI,
  type OIChangeSignalRow,
} from "@/services/ftApi";
import { SAMPLE_ANALYSIS, SAMPLE_UNUSUAL } from "./sampleData";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"] as const;
const EXCHANGE = "NFO";

type PriceDir = "up" | "down" | "flat";
const PRICE_DIRS: { value: PriceDir; label: string }[] = [
  { value: "up", label: "Price ↑" },
  { value: "flat", label: "Price → " },
  { value: "down", label: "Price ↓" },
];

/** Signal short-code → Tailwind colour + bullish/bearish lean. */
const SIGNAL_STYLE: Record<string, { cls: string; lean: string }> = {
  LB: { cls: "text-profit border-profit/40 bg-profit/10", lean: "bullish" },
  SC: { cls: "text-profit border-profit/30 bg-profit/5", lean: "bullish" },
  SB: { cls: "text-loss border-loss/40 bg-loss/10", lean: "bearish" },
  LU: { cls: "text-loss border-loss/30 bg-loss/5", lean: "bearish" },
  OA: { cls: "text-warning border-warning/30 bg-warning/10", lean: "neutral" },
  OR: { cls: "text-warning border-warning/30 bg-warning/5", lean: "neutral" },
  N: { cls: "text-text-muted border-border-default", lean: "neutral" },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Compact Indian-notation OI (e.g. 41,00,000 → "41.0L"). */
function fmtOI(v: number): string {
  if (Math.abs(v) >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (Math.abs(v) >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

function signalStyle(short: string) {
  return SIGNAL_STYLE[short] ?? SIGNAL_STYLE.N;
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

function OISignalsWidget() {
  const isConnected = useBrokerConnected();
  const [symbol, setSymbol] = useState<string>("NIFTY");
  const [priceDir, setPriceDir] = useState<PriceDir>("flat");

  const analysisQuery = useQuery({
    queryKey: ["oiAnalysis", symbol, priceDir],
    queryFn: () => getOIChangeAnalysis(symbol, EXCHANGE, "", priceDir),
    enabled: isConnected,
  });
  const unusualQuery = useQuery({
    queryKey: ["oiUnusual", symbol],
    queryFn: () => getUnusualOI(symbol, EXCHANGE, ""),
    enabled: isConnected,
  });

  const isLive = isConnected && !!analysisQuery.data;
  const analysis = isLive && analysisQuery.data ? analysisQuery.data : SAMPLE_ANALYSIS;
  const unusual = isLive && unusualQuery.data ? unusualQuery.data : SAMPLE_UNUSUAL;
  const isFetching = analysisQuery.isFetching || unusualQuery.isFetching;

  // Order signals by strike for a stable, readable table.
  const signals: OIChangeSignalRow[] = [...analysis.signals].sort(
    (a, b) => a.strike - b.strike,
  );

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Activity size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">OI Signals</span>
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
            role="status"
            aria-label="Live: OI signals from the connected broker's option chain"
            title="Live — OI-action classification + unusual-OI from the connected broker's chain."
          >
            Live
          </span>
        ) : (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for live OI signals"
            title="Sample OI signals so the widget is usable in explore mode — connect a broker for live data."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
        <Select value={priceDir} onValueChange={(v) => setPriceDir(v as PriceDir)}>
          <SelectTrigger className="h-7 w-24 text-xs bg-surface-hover border-border-default text-text-primary" aria-label="Underlying price direction">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PRICE_DIRS.map((d) => (
              <SelectItem key={d.value} value={d.value} className="text-xs">{d.label}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-7 w-28 text-xs bg-surface-hover border-border-default text-text-primary" aria-label="Underlying symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Summary chips */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex-wrap text-xxs">
        {(["Long Build-up", "Short Covering", "Short Build-up", "Long Unwinding"] as const).map((label) => {
          const short = label === "Long Build-up" ? "LB" : label === "Short Covering" ? "SC" : label === "Short Build-up" ? "SB" : "LU";
          const style = signalStyle(short);
          return (
            <span key={label} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 ${style.cls}`}>
              <span className="font-semibold">{short}</span>
              <span className="tabular-nums">{analysis.summary[label] ?? 0}</span>
            </span>
          );
        })}
      </div>

      {/* Signals table */}
      <div className="flex-1 min-h-0 overflow-auto">
        {signals.length === 0 ? (
          <p className="text-xs text-text-muted text-center py-8">No OI signals for {symbol}.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xxs text-text-muted font-medium">Strike</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium">Type</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">OI</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">ΔOI</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium">Signal</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {signals.map((s, i) => {
                const style = signalStyle(s.signal_short);
                return (
                  <TableRow key={`${s.strike}-${s.option_type}-${i}`} className="border-border-subtle hover:bg-surface-hover">
                    <TableCell className="text-xs font-mono text-text-primary py-1">{s.strike}</TableCell>
                    <TableCell className="text-xs text-text-secondary py-1">{s.option_type}</TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-1 text-right tabular-nums">{fmtOI(s.oi)}</TableCell>
                    <TableCell className={`text-xs font-mono py-1 text-right tabular-nums ${s.oi_change >= 0 ? "text-profit" : "text-loss"}`}>
                      {s.oi_change >= 0 ? "+" : ""}{fmtOI(s.oi_change)}
                    </TableCell>
                    <TableCell className="py-1">
                      <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-xxs font-medium ${style.cls}`} title={`${s.signal} (${style.lean})`}>
                        {s.signal_short}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Unusual OI footer */}
      <div className="flex-none bg-surface-card border-t border-border-default px-2 py-1.5">
        <div className="flex items-center gap-1.5 mb-1">
          <span className="text-xxs uppercase tracking-wide text-text-muted">Unusual OI</span>
          <span className="text-xxs text-text-muted">· |z| ≥ {unusual.threshold.toFixed(1)}</span>
          {isFetching && <span className="text-xxs text-text-muted">· updating…</span>}
        </div>
        {unusual.unusual.length === 0 ? (
          <p className="text-xxs text-text-muted">No unusual OI activity.</p>
        ) : (
          <div className="flex items-center gap-2 flex-wrap">
            {unusual.unusual.slice(0, 6).map((u, i) => (
              <span
                key={`${u.strike}-${u.option_type}-${i}`}
                className="inline-flex items-center gap-1 rounded border border-border-default px-1.5 py-0.5 text-xxs"
                title={`${u.option_type} ${u.strike}: ΔOI ${u.change_pct.toFixed(1)}% (z ${u.z_score.toFixed(1)}, ${u.direction})`}
              >
                {u.direction === "addition"
                  ? <TrendingUp size={10} className="text-profit" aria-hidden="true" />
                  : <TrendingDown size={10} className="text-loss" aria-hidden="true" />}
                <span className="font-mono text-text-primary">{u.strike}{u.option_type}</span>
                <span className="text-text-muted tabular-nums">z{u.z_score.toFixed(1)}</span>
              </span>
            ))}
            {unusual.unusual.length === 0 && <Minus size={10} className="text-text-muted" aria-hidden="true" />}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(OISignalsWidget);
