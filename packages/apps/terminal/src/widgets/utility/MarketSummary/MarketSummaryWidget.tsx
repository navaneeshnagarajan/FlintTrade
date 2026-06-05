/**
 * MarketSummaryWidget — At-a-glance market overview for start of day.
 *
 * Sections:
 *   - Index performance: NIFTY, BANKNIFTY, NIFTYIT, VIX
 *   - Market breadth: advances/declines ratio with progress bar
 *   - FII/DII net activity (cash segment)
 *   - Top 5 gainers and losers
 *   - Sector performance bars (colour-coded)
 *
 * HONESTY NOTE: every section renders from the SAMPLE_* constants below. No
 * backend endpoint feeds this widget yet, so the data is identical whether or
 * not a broker is connected. The "Sample data" badge is therefore shown at all
 * times (it must NOT be gated on connection state) and there is no auto-refresh
 * or "live updating" affordance — nothing here should imply the figures are
 * live. Wiring a real market-overview endpoint is a separate future task.
 */

import { useEffect, memo } from "react";
import { LayoutDashboard, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IndexData {
  symbol: string;
  ltp: number;
  change: number;
  changePct: number;
}

interface BreadthData {
  advances: number;
  declines: number;
  unchanged: number;
}

interface FiiDiiData {
  fii: number;
  dii: number;
  date: string;
}

interface MoverData {
  symbol: string;
  changePct: number;
}

interface SectorData {
  name: string;
  changePct: number;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_INDICES: IndexData[] = [
  { symbol: "NIFTY",    ltp: 22150.40, change:  185.25, changePct:  0.84 },
  { symbol: "BANKNIFTY", ltp: 47830.60, change: -210.50, changePct: -0.44 },
  { symbol: "NIFTYIT",  ltp: 36420.80, change:  520.30, changePct:  1.45 },
  { symbol: "INDIA VIX", ltp:  14.82,  change:  -0.63,  changePct: -4.08 },
];

const SAMPLE_BREADTH: BreadthData = {
  advances: 1247,
  declines:  892,
  unchanged:  61,
};

const SAMPLE_FII_DII: FiiDiiData = {
  fii: -1245.60,
  dii:  2340.80,
  date: "08 Apr",
};

const SAMPLE_GAINERS: MoverData[] = [
  { symbol: "INFY",        changePct: 3.42 },
  { symbol: "TCS",         changePct: 2.87 },
  { symbol: "HCLTECH",     changePct: 2.61 },
  { symbol: "WIPRO",       changePct: 2.14 },
  { symbol: "TECHM",       changePct: 1.93 },
];

const SAMPLE_LOSERS: MoverData[] = [
  { symbol: "BANKBARODA",  changePct: -2.83 },
  { symbol: "UNIONBANK",   changePct: -2.41 },
  { symbol: "CANBK",       changePct: -2.19 },
  { symbol: "PNB",         changePct: -1.97 },
  { symbol: "INDUSINDBK",  changePct: -1.62 },
];

const SAMPLE_SECTORS: SectorData[] = [
  { name: "IT",           changePct:  1.82 },
  { name: "Pharma",       changePct:  0.93 },
  { name: "Auto",         changePct:  0.67 },
  { name: "FMCG",         changePct:  0.41 },
  { name: "Realty",       changePct: -0.28 },
  { name: "Metal",        changePct: -0.84 },
  { name: "PSU Bank",     changePct: -1.36 },
  { name: "Media",        changePct: -1.71 },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtChange(v: number, pct: number): string {
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)} (${sign}${pct.toFixed(2)}%)`;
}

function fmtCr(v: number): string {
  const sign = v >= 0 ? "+" : "−";
  return `${sign}₹${Math.abs(v).toFixed(2)} Cr`;
}

// ---------------------------------------------------------------------------
// Index card
// ---------------------------------------------------------------------------

function IndexCard({ d }: { d: IndexData }) {
  const isUp = d.change >= 0;
  return (
    <div
      className="flex flex-col gap-0.5 bg-surface-hover rounded px-2.5 py-2 min-w-28"
      aria-label={`${d.symbol} ${d.ltp} ${fmtChange(d.change, d.changePct)}`}
    >
      <span className="text-xxs text-text-muted font-medium">{d.symbol}</span>
      <span className="text-sm font-semibold font-mono tabular-nums text-text-primary">
        {d.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
      </span>
      <span className={cn("text-xxs font-mono tabular-nums", isUp ? "text-profit" : "text-loss")}>
        {fmtChange(d.change, d.changePct)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Breadth bar
// ---------------------------------------------------------------------------

function BreadthBar({ b }: { b: BreadthData }) {
  const total = b.advances + b.declines + b.unchanged;
  const advPct = (b.advances / total) * 100;
  const decPct = (b.declines / total) * 100;

  return (
    <div aria-label={`Market breadth: ${b.advances} advances, ${b.declines} declines, ${b.unchanged} unchanged`}>
      <div className="flex justify-between text-xxs font-mono mb-1">
        <span className="text-profit">↑ {b.advances}</span>
        <span className="text-text-muted">{b.unchanged} unch</span>
        <span className="text-loss">↓ {b.declines}</span>
      </div>
      <div className="flex h-2 rounded-full overflow-hidden bg-surface-base">
        <div className="bg-profit/80" style={{ width: `${advPct}%` }} />
        <div className="bg-border-subtle" style={{ width: `${(b.unchanged / total) * 100}%` }} />
        <div className="bg-loss/80 flex-1" style={{ width: `${decPct}%` }} />
      </div>
      <div className="text-xxs text-text-muted mt-0.5 text-center">
        A/D ratio {(b.advances / Math.max(b.declines, 1)).toFixed(2)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sector bars
// ---------------------------------------------------------------------------

function SectorBars({ sectors }: { sectors: SectorData[] }) {
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.changePct)), 0.1);
  return (
    <div className="space-y-1" aria-label="Sector performance">
      {sectors.map((s) => {
        const barPct = (Math.abs(s.changePct) / maxAbs) * 100;
        const isUp = s.changePct >= 0;
        return (
          <div key={s.name} className="flex items-center gap-1.5">
            <span className="text-xxs text-text-muted w-16 shrink-0 truncate">{s.name}</span>
            <div className="flex-1 h-3 bg-surface-base rounded-sm overflow-hidden">
              <div
                className={cn("h-full rounded-sm", isUp ? "bg-profit/70" : "bg-loss/70")}
                style={{ width: `${barPct}%` }}
              />
            </div>
            <span className={cn("text-xxs font-mono w-12 text-right tabular-nums", isUp ? "text-profit" : "text-loss")}>
              {isUp ? "+" : ""}{s.changePct.toFixed(2)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Movers list
// ---------------------------------------------------------------------------

function MoversList({ movers, title, isGainer }: { movers: MoverData[]; title: string; isGainer: boolean }) {
  return (
    <div>
      <div className="flex items-center gap-1 mb-1.5">
        {isGainer
          ? <TrendingUp size={11} className="text-profit" aria-hidden="true" />
          : <TrendingDown size={11} className="text-loss" aria-hidden="true" />
        }
        <span className="text-xxs font-medium text-text-muted uppercase tracking-wide">{title}</span>
      </div>
      <div className="space-y-0.5">
        {movers.map((m) => (
          <div key={m.symbol} className="flex justify-between items-center">
            <span className="text-xs text-text-secondary font-medium">{m.symbol}</span>
            <span className={cn("text-xs font-mono tabular-nums", m.changePct >= 0 ? "text-profit" : "text-loss")}>
              {m.changePct >= 0 ? "+" : ""}{m.changePct.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p id={id} className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
      {children}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function MarketSummaryWidget() {
  const track = useTrackBehavior();

  useEffect(() => {
    track("trade", "widget_view_market_summary");
  }, [track]);

  const fiiPositive = SAMPLE_FII_DII.fii >= 0;
  const diiPositive = SAMPLE_FII_DII.dii >= 0;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Market Summary widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <LayoutDashboard size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Summary</span>
        {/* Honest disclosure — every section reads from the SAMPLE_* constants
            above; no backend market-overview endpoint is wired yet. The badge
            was previously hidden once a broker connected (`!isConnected`),
            which masked the fact that the figures stayed sample even on a live
            connection. Keep it visible at all times. There is deliberately no
            timestamp or refresh control here: a "last updated" clock or a
            spinning refresh button would falsely imply the data is live. */}
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live market-overview source is wired yet"
          title="No live data wired yet — showing a sample market overview so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-3">

        {/* Indices */}
        <section aria-labelledby="ms-indices">
          <SectionHeading id="ms-indices">Indices</SectionHeading>
          <div className="flex gap-2 flex-wrap">
            {SAMPLE_INDICES.map((d) => <IndexCard key={d.symbol} d={d} />)}
          </div>
        </section>

        {/* Market breadth */}
        <section aria-labelledby="ms-breadth">
          <SectionHeading id="ms-breadth">Market Breadth (NSE)</SectionHeading>
          <BreadthBar b={SAMPLE_BREADTH} />
        </section>

        {/* FII / DII */}
        <section aria-labelledby="ms-fiidii">
          <SectionHeading id="ms-fiidii">FII / DII — {SAMPLE_FII_DII.date}</SectionHeading>
          <div className="flex gap-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-xxs text-text-muted">FII Net</span>
              <span className={cn("text-xs font-semibold font-mono tabular-nums", fiiPositive ? "text-profit" : "text-loss")}>
                {fmtCr(SAMPLE_FII_DII.fii)}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xxs text-text-muted">DII Net</span>
              <span className={cn("text-xs font-semibold font-mono tabular-nums", diiPositive ? "text-profit" : "text-loss")}>
                {fmtCr(SAMPLE_FII_DII.dii)}
              </span>
            </div>
          </div>
        </section>

        {/* Gainers & Losers */}
        <section aria-labelledby="ms-movers">
          <SectionHeading id="ms-movers">Top Movers</SectionHeading>
          <div className="grid grid-cols-2 gap-3">
            <MoversList movers={SAMPLE_GAINERS} title="Gainers" isGainer />
            <MoversList movers={SAMPLE_LOSERS}  title="Losers"  isGainer={false} />
          </div>
        </section>

        {/* Sectors */}
        <section aria-labelledby="ms-sectors">
          <SectionHeading id="ms-sectors">Sector Performance</SectionHeading>
          <SectorBars sectors={SAMPLE_SECTORS} />
        </section>
      </div>
    </div>
  );
}

export default memo(MarketSummaryWidget);
