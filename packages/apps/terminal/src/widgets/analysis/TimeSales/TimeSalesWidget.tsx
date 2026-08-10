/**
 * TimeSalesWidget — Tape & Microstructure (W3).
 *
 * Streams inferred trade prints for the selected instrument: the OpenAlgo
 * WebSocket carries quote ticks (LTP + cumulative volume), not per-trade data,
 * so each print is derived from a tick (size = volume delta, aggressor side by
 * the tick rule) and the header says so honestly. Follows the instrument
 * broadcast on its FDC3 user channel (red by default — the watchlist click)
 * with a local selector fallback; sample tape + preview teaser when
 * disconnected.
 *
 * Absorbed the retired Market Microstructure widget. That widget showed the
 * right statistics over invented data — it generated its own ticks with
 * `Math.random()` every 500 ms, including the bid/ask sizes the quote feed
 * never supplies. Its statistics kernel now runs on this widget's real prints
 * (`computeTapeStats` in tape.ts) and its bid/ask imbalance comes from the
 * depth endpoint through the shared `bookImbalance`; when no depth is
 * available the imbalance is OMITTED rather than guessed.
 *
 * Panel params:
 *   `view` — "tape" (default: statistics header above the print table) or
 *   "stats" (statistics only, for a narrow panel). The retired
 *   `microstructure` id maps to "stats".
 *   `channel` — FDC3 user-channel membership (services/fdc3/channels.ts).
 *   Absent means the default red channel; "none" leaves the widget joined
 *   to nothing, following only its own selector.
 */

import { memo, useCallback, useEffect, useMemo, useState } from "react";
import type { WidgetProps } from "@/types/widgets";
import { ChevronDown, ChevronRight, ClipboardList, Microscope } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { useChannelInstrument, useChannelMembership } from "@/services/fdc3/hooks";
import { useTape } from "./useTape";
import { SAMPLE_TAPE, SAMPLE_TAPE_NOW } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useDepthData } from "@/hooks/useDepthData";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { bookImbalance, normaliseDepth } from "@/lib/depth";
import { APP_VERSION_TAG } from "@/lib/appVersion";
import { computeTapeStats, type TapePrint, type TapeSide, type TapeStats } from "./tape";
import type { WsInstrument } from "@/types/api";

const FALLBACK_SYMBOLS: WsInstrument[] = [
  { symbol: "RELIANCE", exchange: "NSE" },
  { symbol: "TCS", exchange: "NSE" },
  { symbol: "HDFCBANK", exchange: "NSE" },
  { symbol: "SBIN", exchange: "NSE" },
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
];

const PRICE_FMT = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const QTY_FMT = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

// ─── Panel params ────────────────────────────────────────────────────────────

/** Presentation of the widget. `stats` is the retired Microstructure widget. */
type TapeView = "tape" | "stats";

const TAPE_VIEWS: readonly TapeView[] = ["tape", "stats"];

const VIEW_LABELS: Record<TapeView, string> = {
  tape: "Tape view",
  stats: "Statistics-only view",
};

/** Resolves the workspace `params.view` panel parameter, defaulting to the tape. */
function resolveTapeView(value: unknown): TapeView {
  return typeof value === "string" && (TAPE_VIEWS as readonly string[]).includes(value)
    ? (value as TapeView)
    : "tape";
}

interface TimeSalesPanelParams {
  /** Initial view — how the retired `microstructure` id selects its old look. */
  view?: string;
  /** FDC3 user-channel membership — resolved through `channelFromParams`. */
  channel?: string;
}

// ─── Print table ─────────────────────────────────────────────────────────────

function sideCls(side: TapeSide): string {
  if (side === "buy") return "text-green-500";
  if (side === "sell") return "text-red-500";
  return "text-text-muted";
}

function PrintRow({ p }: { p: TapePrint }) {
  return (
    <tr className="border-b border-border-default/40 last:border-0">
      <td className="py-0.5 pr-2 font-mono tabular-nums text-text-muted">{p.time}</td>
      <td className={`py-0.5 px-2 text-right font-mono tabular-nums ${sideCls(p.side)}`}>
        {PRICE_FMT.format(p.price)}
      </td>
      <td className="py-0.5 px-2 text-right font-mono tabular-nums text-text-primary">
        {p.qty > 0 ? QTY_FMT.format(p.qty) : "—"}
      </td>
      <td className={`py-0.5 pl-2 uppercase text-[10px] font-semibold ${sideCls(p.side)}`}>
        {p.side === "neutral" ? "—" : p.side}
      </td>
    </tr>
  );
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
        <div className="absolute top-full right-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full max-h-48 overflow-y-auto">
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

// ─── Statistics presentation (absorbed from Market Microstructure) ───────────

function StatRow({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border-default last:border-0">
      <span className="text-[10px] text-text-muted">{label}</span>
      <div className="flex items-baseline gap-1.5">
        <span className={`text-xs font-mono tabular-nums font-semibold ${accent ?? "text-text-primary"}`}>
          {value}
        </span>
        {sub && <span className="text-[10px] text-text-muted">{sub}</span>}
      </div>
    </div>
  );
}

/** Tick-rule aggressor split across the last 60 s of prints. */
function DirectionBadge({ uptickPct, downtickPct }: { uptickPct: number; downtickPct: number }) {
  const neutralPct = Math.max(0, 100 - uptickPct - downtickPct);
  return (
    <div
      className="flex h-3 rounded overflow-hidden bg-surface-hover"
      aria-label={`Trade direction: uptick ${uptickPct.toFixed(0)}% downtick ${downtickPct.toFixed(0)}% neutral ${neutralPct.toFixed(0)}%`}
    >
      <div className="bg-green-500/70 transition-all" style={{ width: `${uptickPct}%` }} />
      <div className="bg-text-muted/30 transition-all" style={{ width: `${neutralPct}%` }} />
      <div className="bg-red-500/70 transition-all" style={{ width: `${downtickPct}%` }} />
    </div>
  );
}

/** Resting bid/ask split from the depth book — never from the tape. */
function ImbalanceBar({ bidPct }: { bidPct: number }) {
  return (
    <div
      className="flex h-3 rounded overflow-hidden"
      aria-label={`Bid ask imbalance: bid ${bidPct.toFixed(0)}% ask ${(100 - bidPct).toFixed(0)}%`}
    >
      <div className="bg-green-500/70 transition-all duration-300" style={{ width: `${bidPct}%` }} />
      <div className="bg-red-500/70 transition-all duration-300" style={{ width: `${100 - bidPct}%` }} />
    </div>
  );
}

interface TapeStatsPanelProps {
  stats: TapeStats;
  /** Signed −1…+1 book imbalance, or null when no depth book is available. */
  imbalance: number | null;
}

function TapeStatsPanel({ stats, imbalance }: TapeStatsPanelProps) {
  const velocityColour =
    stats.velocity > 5 ? "text-amber-500" : stats.velocity > 2 ? "text-text-primary" : "text-text-muted";
  const largeColour = stats.largeOrderCount > 5 ? "text-amber-500" : "text-text-primary";
  const hasSizes = stats.sizedCount > 0;
  const bidPct = imbalance === null ? 50 : ((imbalance + 1) / 2) * 100;
  const imbalanceColour =
    imbalance === null
      ? "text-text-muted"
      : imbalance > 0.2
        ? "text-green-500"
        : imbalance < -0.2
          ? "text-red-500"
          : "text-text-secondary";

  return (
    <div className="space-y-2">
      {/* Velocity sparkline */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-text-muted uppercase tracking-wide">Print velocity (60s)</span>
          <span className={`text-xs font-mono font-semibold tabular-nums ${velocityColour}`}>
            {stats.velocity} prints/s
          </span>
        </div>
        <div className="bg-surface-card border border-border-default rounded p-1">
          <FlintMiniSparkline
            points={stats.velocityHistory}
            positive
            ariaLabel="Tick velocity sparkline over last 60 seconds"
            className="h-9 w-full text-accent"
          />
        </div>
      </div>

      {/* Size statistics */}
      <div className="bg-surface-card border border-border-default rounded px-2">
        <StatRow label="Print velocity" value={`${stats.velocity}`} sub="prints/s" accent={velocityColour} />
        <StatRow
          label="Avg Trade Size"
          value={hasSizes ? QTY_FMT.format(Math.round(stats.avgTradeSize)) : "—"}
          sub={hasSizes ? "qty" : "no size on feed"}
        />
        <StatRow
          label="Large Prints (60s)"
          value={hasSizes ? String(stats.largeOrderCount) : "—"}
          sub="> 2× avg"
          accent={hasSizes ? largeColour : "text-text-muted"}
        />
      </div>

      {/* Tick-rule aggressor split */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-text-muted uppercase tracking-wide">Aggressor, tick rule (60s)</span>
          <span className="text-[10px] text-text-secondary font-mono tabular-nums">
            {stats.uptickPct.toFixed(0)}% up / {stats.downtickPct.toFixed(0)}% down
          </span>
        </div>
        <DirectionBadge uptickPct={stats.uptickPct} downtickPct={stats.downtickPct} />
        <div className="flex justify-between text-[10px] text-text-muted">
          <span className="text-green-500">Uptick</span>
          <span>Neutral</span>
          <span className="text-red-500">Downtick</span>
        </div>
      </div>

      {/* Resting book imbalance — depth feed only, omitted when unavailable */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-text-muted uppercase tracking-wide">Bid / Ask Imbalance</span>
          <span className={`text-xs font-mono font-semibold tabular-nums ${imbalanceColour}`}>
            {imbalance === null ? "—" : `${bidPct.toFixed(1)}% bid`}
          </span>
        </div>
        {imbalance === null ? (
          <p className="text-[10px] text-text-muted">
            Needs the depth feed — the quote tape carries no resting bid/ask sizes, so this is left blank
            rather than estimated.
          </p>
        ) : (
          <>
            <ImbalanceBar bidPct={bidPct} />
            <div className="flex justify-between text-[10px] text-text-muted">
              <span>Bid</span>
              <span className="text-text-muted/70">top 5 levels, depth snapshot</span>
              <span>Ask</span>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Main widget ─────────────────────────────────────────────────────────────

function TimeSalesWidget(props: WidgetProps) {
  const panelParams = props.params as TimeSalesPanelParams | undefined;
  const panelView = panelParams?.view;
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const channelInstrument = useChannelInstrument(useChannelMembership(props.api.id, props.params));
  const [manual, setManual] = useState<WsInstrument | null>(null);
  const [view, setView] = useState<TapeView>(() => resolveTapeView(panelView));
  const [statsOpen, setStatsOpen] = useState(true);

  // The channel's broadcast wins unless the user picked one locally after that.
  const instrument = manual ?? channelInstrument ?? FALLBACK_SYMBOLS[0];

  const liveTape = useTape(instrument, isConnected);
  const tape = isConnected ? liveTape : SAMPLE_TAPE;
  const isSample = !isConnected;
  const showStats = view === "stats" || statsOpen;

  // A clock so the rolling windows decay when the feed goes quiet: without it a
  // dead feed would keep reporting the velocity it had when the last print
  // arrived. Sample mode measures from the sample tape's own newest print.
  const [clock, setClock] = useState(() => Date.now());
  useEffect(() => {
    if (isSample || !showStats) return;
    const id = setInterval(() => setClock(Date.now()), 1_000);
    return () => clearInterval(id);
  }, [isSample, showStats]);

  useEffect(() => {
    if (showStats) track("trade", "microstructure_opened");
  }, [showStats, track]);

  const statsNow = isSample ? SAMPLE_TAPE_NOW : clock;
  const stats = useMemo(() => computeTapeStats(tape, statsNow), [tape, statsNow]);

  // Imbalance is resting-book data; the tape cannot supply it. Shares the
  // depth query key with every other depth surface, so opening this alongside
  // the DOM heatmap costs no extra polling.
  const depth = useDepthData(instrument.symbol, instrument.exchange, isConnected && showStats);
  const imbalance = useMemo(() => {
    const book = normaliseDepth(depth.data);
    const resting =
      book.bids.reduce((s, l) => s + l.qty, 0) + book.asks.reduce((s, l) => s + l.qty, 0);
    return resting > 0 ? bookImbalance(book.bids, book.asks) : null;
  }, [depth.data]);

  const buyQty = useMemo(() => tape.filter((p) => p.side === "buy").reduce((s, p) => s + p.qty, 0), [tape]);
  const sellQty = useMemo(() => tape.filter((p) => p.side === "sell").reduce((s, p) => s + p.qty, 0), [tape]);
  const total = buyQty + sellQty;
  const buyPct = total > 0 ? (buyQty / total) * 100 : 50;

  // Persist the chosen view into the panel params so a saved layout reopens in
  // the same mode (this is also how the retired `microstructure` id survives).
  const handleViewChange = useCallback((next: TapeView) => {
    if (next === view) return;
    setView(next);
    props.api.updateParameters({ view: next });
  }, [props.api, view]);

  const content = (
    <div className="flex flex-col h-full gap-2 p-3 text-xs" aria-label="Tape and Microstructure widget">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-text-primary flex items-center gap-1.5">
            <ClipboardList size={14} /> Tape &amp; Microstructure
          </h3>
          {/* The honesty note is the reason this widget is defensible: these are
              not exchange trade prints, they are prints inferred from quote
              ticks by the tick rule, and every statistic below is computed from
              them. Keep it visible in both views. */}
          <p className="text-[10px] text-text-muted">
            {instrument.symbol} · prints inferred from quote ticks (tick rule)
            {isSample && <span className="ml-1 text-amber-500">· Sample data</span>}
          </p>
        </div>
        <div className="flex items-center gap-1 flex-none">
          <div className="flex items-center gap-0.5 rounded border border-border-default p-0.5">
            <button
              type="button"
              onClick={() => handleViewChange("tape")}
              className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                view === "tape" ? "bg-surface-hover text-text-primary" : "text-text-muted hover:text-text-secondary"
              }`}
              aria-pressed={view === "tape"}
              aria-label={VIEW_LABELS.tape}
              title={VIEW_LABELS.tape}
            >
              <ClipboardList size={12} aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={() => handleViewChange("stats")}
              className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                view === "stats" ? "bg-surface-hover text-text-primary" : "text-text-muted hover:text-text-secondary"
              }`}
              aria-pressed={view === "stats"}
              aria-label={VIEW_LABELS.stats}
              title={VIEW_LABELS.stats}
            >
              <Microscope size={12} aria-hidden="true" />
            </button>
          </div>
          <Selector
            value={instrument.symbol}
            options={FALLBACK_SYMBOLS.map((s) => s.symbol)}
            onChange={(sym) => setManual(FALLBACK_SYMBOLS.find((s) => s.symbol === sym) ?? null)}
          />
        </div>
      </div>

      {view === "tape" && (
        <button
          type="button"
          onClick={() => setStatsOpen((p) => !p)}
          className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-text-muted hover:text-text-secondary transition-colors"
          aria-expanded={statsOpen}
          aria-label="Microstructure statistics"
        >
          {statsOpen ? <ChevronDown size={11} aria-hidden="true" /> : <ChevronRight size={11} aria-hidden="true" />}
          Microstructure
        </button>
      )}

      {showStats && <TapeStatsPanel stats={stats} imbalance={imbalance} />}

      {view === "tape" && (
        <>
          {/* Buy/sell pressure bar over the visible tape */}
          <div>
            <div className="relative h-1.5 rounded-full bg-red-500/25 overflow-hidden">
              <div className="h-full bg-green-500/70" style={{ width: `${buyPct}%` }} />
            </div>
            <div className="flex justify-between mt-0.5 text-[10px] text-text-muted font-mono tabular-nums">
              <span className="text-green-500">B {QTY_FMT.format(buyQty)}</span>
              <span className="text-red-500">S {QTY_FMT.format(sellQty)}</span>
            </div>
          </div>

          {tape.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-text-muted text-center">
              {isConnected ? "Waiting for ticks…" : "No prints"}
            </div>
          ) : (
            <div className="flex-1 overflow-auto">
              <table className="w-full">
                <thead className="sticky top-0 bg-surface-card">
                  <tr className="text-[10px] uppercase tracking-wide text-text-muted border-b border-border-default">
                    <th className="py-1 pr-2 text-left font-medium">Time</th>
                    <th className="py-1 px-2 text-right font-medium">Price</th>
                    <th className="py-1 px-2 text-right font-medium">Qty</th>
                    <th className="py-1 pl-2 text-left font-medium">Side</th>
                  </tr>
                </thead>
                <tbody>
                  {tape.map((p) => (
                    <PrintRow key={p.id} p={p} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {view === "stats" && tape.length === 0 && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-center">
          {isConnected ? "Waiting for ticks…" : "No prints"}
        </div>
      )}
    </div>
  );

  return isConnected ? (
    content
  ) : (
    <FeatureTeaser status="preview" featureName="Tape & Microstructure" version={APP_VERSION_TAG}>
      {content}
    </FeatureTeaser>
  );
}

export default memo(TimeSalesWidget);
