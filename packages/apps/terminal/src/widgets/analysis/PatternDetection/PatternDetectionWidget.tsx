/**
 * PatternDetectionWidget — candlestick pattern detection (W4).
 *
 * Scans a symbol's recent daily bars for the six candlestick patterns
 * FlintTrade backtests (doji, hammer/shooting-star, engulfing, morning/evening
 * star, three soldiers/crows) and lists the detected patterns with their
 * bullish/bearish direction and strength. Live via the bridge history when
 * connected; otherwise a clearly-marked sample scan.
 */

import { memo, useState } from "react";
import { ChevronDown, RefreshCw, Loader2, TrendingUp, TrendingDown, Minus, CandlestickChart } from "lucide-react";
import { usePatternDetection } from "./usePatternDetection";
import { SAMPLE_PATTERN_SCAN } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import type { PatternDirection, PatternMatch } from "@/types/api";

const SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN"];

function directionStyle(direction: PatternDirection): { cls: string; Icon: typeof TrendingUp } {
  if (direction === "bullish") return { cls: "text-green-500", Icon: TrendingUp };
  if (direction === "bearish") return { cls: "text-red-500", Icon: TrendingDown };
  return { cls: "text-text-muted", Icon: Minus };
}

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
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full max-h-48 overflow-y-auto">
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

function PatternRow({ m }: { m: PatternMatch }) {
  const { cls, Icon } = directionStyle(m.direction);
  return (
    <div className="flex items-center gap-2 py-1.5 border-b border-border-default/50 last:border-0">
      <Icon size={14} className={cls} />
      <div className="flex-1 min-w-0">
        <div className="text-text-primary font-medium truncate">{m.label}</div>
        <div className="text-[10px] text-text-muted">{m.time || `bar ${m.index}`}</div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <div className="w-12 h-1.5 rounded-full bg-surface-hover overflow-hidden">
          <div className={`h-full ${m.direction === "bearish" ? "bg-red-500/70" : m.direction === "bullish" ? "bg-green-500/70" : "bg-text-muted/60"}`} style={{ width: `${Math.round(m.strength * 100)}%` }} />
        </div>
        <span className="font-mono tabular-nums text-[10px] text-text-muted w-8 text-right">
          {Math.round(m.strength * 100)}%
        </span>
      </div>
    </div>
  );
}

function PatternDetectionWidget() {
  const [symbol, setSymbol] = useState("RELIANCE");
  const isConnected = useBrokerConnected();
  const { data: live, isLoading, isFetching, refetch } = usePatternDetection(symbol, "NSE", isConnected);

  const response = isConnected && live ? live : { is_sample_data: true, scan: SAMPLE_PATTERN_SCAN };
  const scan = response.scan;
  const isSample = response.is_sample_data !== false;

  const bullish = scan.matches.filter((m) => m.direction === "bullish").length;
  const bearish = scan.matches.filter((m) => m.direction === "bearish").length;

  const content = (
    <div className="flex flex-col h-full gap-3 p-3 text-xs">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
            <CandlestickChart size={14} /> Pattern Detection
          </h3>
          <p className="text-[10px] text-text-muted">
            {scan.bar_count} daily bars · {scan.matches.length} patterns
            {isSample && <span className="ml-1 text-amber-500">· Sample data</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Selector value={symbol} options={SYMBOLS} onChange={setSymbol} />
          {isConnected && (
            <button
              type="button"
              onClick={() => void refetch()}
              className="p-1 rounded hover:bg-surface-hover text-text-muted"
              aria-label="Refresh pattern scan"
            >
              {isFetching ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-3 text-[10px]">
        <span className="text-green-500">{bullish} bullish</span>
        <span className="text-red-500">{bearish} bearish</span>
      </div>

      {isLoading && isConnected ? (
        <div className="flex-1 flex items-center justify-center text-text-muted">
          <Loader2 size={16} className="animate-spin" />
        </div>
      ) : scan.matches.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-text-muted text-center">
          No candlestick patterns detected in the recent bars.
        </div>
      ) : (
        <div className="flex-1 overflow-auto">
          {scan.matches
            .slice()
            .sort((a, b) => b.index - a.index)
            .map((m) => (
              <PatternRow key={`${m.index}-${m.pattern}`} m={m} />
            ))}
        </div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Pattern Detection" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(PatternDetectionWidget);
