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
 * PROVENANCE: breadth (/v1/breadth/current), FII/DII (/screener/fii-dii),
 * and movers/sectors (the NIFTY 50 quote sweep via useSectorMovers) are
 * live-backed with PER-SECTION Sample/Live chips driven by each source's own
 * flag. The index cards now read the live WebSocket tick atoms — the same
 * source Dashboard and the Ticker consume — and show an explicit "awaiting
 * tick" state rather than a fabricated level. The remaining SAMPLE_*
 * constants stay as the disclosed fallbacks for their own sections.
 */

import { useEffect, memo } from "react";
import { useAtomValue } from "jotai";
import { useQuery } from "@tanstack/react-query";
import { getBreadthCurrent, getFiiDiiData } from "@/services/ftApi.screener";
import { useSectorMovers } from "@/hooks/useSectorMovers";
import { LayoutDashboard, TrendingUp, TrendingDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { tickKeyFor } from "@/lib/market";

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

/**
 * Indices shown in the summary strip, read from the live tick stream.
 *
 * This replaces a hardcoded SAMPLE_INDICES array that was rendered
 * unconditionally with the provenance chip pinned to "sample" — fabricated
 * index levels that a connected operator could never replace with real ones.
 */
const LIVE_INDICES: ReadonlyArray<{ symbol: string; exchange: string }> = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "NIFTYIT", exchange: "NSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
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

/**
 * A single index card backed by the live WebSocket tick stream.
 *
 * These cards used to render `SAMPLE_INDICES` unconditionally with the
 * provenance chip hardwired to `live={false}` — permanently fabricated index
 * levels with no path to real data, even for a connected operator. The tick
 * atoms that Dashboard and Ticker already consume carry exactly this data, so
 * the honest fix is to read them rather than to invent numbers.
 *
 * Renders an explicit waiting state rather than a fabricated level when no
 * tick has arrived.
 */
function LiveIndexCard({ symbol, exchange }: { symbol: string; exchange: string }) {
  const tick = useAtomValue(tickAtomFamily(tickKeyFor(symbol, exchange)));
  const ltp = tick?.ltp ?? 0;
  // prevClose is REST-fetched; tick.close covers quote/fallback modes.
  const prevClose = tick?.prevClose ?? tick?.close ?? 0;

  if (!tick || ltp <= 0 || prevClose <= 0) {
    return (
      <div
        className="flex flex-col gap-0.5 bg-surface-hover rounded px-2.5 py-2 min-w-28"
        aria-label={`${symbol} awaiting live price`}
      >
        <span className="text-xxs text-text-muted font-medium">{symbol}</span>
        <span className="text-sm font-semibold font-mono text-text-muted">—</span>
        <span className="text-xxs text-text-muted">Awaiting tick</span>
      </div>
    );
  }

  const change = ltp - prevClose;
  return <IndexCard d={{ symbol, ltp, change, changePct: (change / prevClose) * 100 }} />;
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

function ProvChip({ live }: { live: boolean }) {
  return (
    <span
      role="status"
      className={cn(
        "ml-1.5 px-1 py-0.5 text-xxs rounded border align-middle",
        live
          ? "text-profit bg-profit/10 border-profit/30"
          : "text-warning bg-warning/10 border-warning/30",
      )}
    >
      {live ? "Live" : "Sample"}
    </span>
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

  const breadthQuery = useQuery({
    queryKey: ["marketSummary", "breadth"],
    queryFn: getBreadthCurrent,
    staleTime: 60_000,
    retry: 1,
  });
  const fiiDiiQuery = useQuery({
    queryKey: ["marketSummary", "fiiDii"],
    queryFn: () => getFiiDiiData(),
    staleTime: 5 * 60_000,
    retry: 1,
  });
  const sectorMovers = useSectorMovers();

  const breadthLive =
    breadthQuery.isSuccess && breadthQuery.data.is_sample_data === false;
  const breadth: BreadthData = breadthLive
    ? {
        advances: breadthQuery.data!.advances,
        declines: breadthQuery.data!.declines,
        unchanged: breadthQuery.data!.unchanged,
      }
    : SAMPLE_BREADTH;

  const fiiDiiLive =
    fiiDiiQuery.isSuccess && fiiDiiQuery.data.is_sample_data === false;
  const fiiDii: FiiDiiData = fiiDiiLive
    ? {
        fii: fiiDiiQuery.data!.latest.fii_net,
        dii: fiiDiiQuery.data!.latest.dii_net,
        date: fiiDiiQuery.data!.latest.trade_date,
      }
    : SAMPLE_FII_DII;

  const moversLive = sectorMovers.isLive
    && sectorMovers.movers.gainers.length + sectorMovers.movers.losers.length > 0;
  const gainers: MoverData[] = moversLive
    ? sectorMovers.movers.gainers.map((m) => ({ symbol: m.symbol, changePct: m.changePct }))
    : SAMPLE_GAINERS;
  const losers: MoverData[] = moversLive
    ? sectorMovers.movers.losers.map((m) => ({ symbol: m.symbol, changePct: m.changePct }))
    : SAMPLE_LOSERS;

  const sectorsLive = sectorMovers.isLive;
  const sectors: SectorData[] = sectorsLive
    ? sectorMovers.data.map((s) => ({ name: s.sector, changePct: s.avgChange }))
    : SAMPLE_SECTORS;

  // Index cards read the live tick stream directly; a tick for the lead index
  // is the evidence that the strip is live. Each card still renders its own
  // "awaiting tick" state, so a partially-populated strip never claims data
  // it does not have.
  const niftyTick = useAtomValue(
    tickAtomFamily(tickKeyFor(LIVE_INDICES[0].symbol, LIVE_INDICES[0].exchange)),
  );
  const indicesLive = (niftyTick?.ltp ?? 0) > 0;

  const anyLive = indicesLive || breadthLive || fiiDiiLive || moversLive || sectorsLive;
  const fiiPositive = fiiDii.fii >= 0;
  const diiPositive = fiiDii.dii >= 0;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Market Summary widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <LayoutDashboard size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Summary</span>
        {/* Per-section provenance chips carry the detail; the header badge
            summarises. It reads "Sample data" only when EVERY section is on
            its disclosed fallback — a partially-live view is labelled Mixed
            so nothing implies the whole board is live. */}
        <span
          className={cn(
            "px-1.5 py-0.5 text-xxs rounded border",
            anyLive
              ? "bg-accent/10 text-accent border-accent/30"
              : "bg-warning/10 text-warning border-warning/30",
          )}
          role="status"
          aria-label={anyLive ? "Some sections show live data; see per-section chips" : "Showing sample data in every section"}
        >
          {anyLive ? "Mixed — see section chips" : "Sample data"}
        </span>
        <div className="flex-1" />
      </div>

      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-3">

        {/* Indices — live WebSocket ticks, the same source Dashboard and the
            Ticker read. Previously a hardcoded sample with no path to live. */}
        <section aria-labelledby="ms-indices">
          <SectionHeading id="ms-indices">Indices<ProvChip live={indicesLive} /></SectionHeading>
          <div className="flex gap-2 flex-wrap">
            {LIVE_INDICES.map((idx) => (
              <LiveIndexCard key={idx.symbol} symbol={idx.symbol} exchange={idx.exchange} />
            ))}
          </div>
        </section>

        {/* Market breadth */}
        <section aria-labelledby="ms-breadth">
          <SectionHeading id="ms-breadth">Market Breadth (NSE)<ProvChip live={breadthLive} /></SectionHeading>
          <BreadthBar b={breadth} />
        </section>

        {/* FII / DII */}
        <section aria-labelledby="ms-fiidii">
          <SectionHeading id="ms-fiidii">FII / DII — {fiiDii.date}<ProvChip live={fiiDiiLive} /></SectionHeading>
          <div className="flex gap-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-xxs text-text-muted">FII Net</span>
              <span className={cn("text-xs font-semibold font-mono tabular-nums", fiiPositive ? "text-profit" : "text-loss")}>
                {fmtCr(fiiDii.fii)}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="text-xxs text-text-muted">DII Net</span>
              <span className={cn("text-xs font-semibold font-mono tabular-nums", diiPositive ? "text-profit" : "text-loss")}>
                {fmtCr(fiiDii.dii)}
              </span>
            </div>
          </div>
        </section>

        {/* Gainers & Losers */}
        <section aria-labelledby="ms-movers">
          <SectionHeading id="ms-movers">Top Movers<ProvChip live={moversLive} /></SectionHeading>
          <div className="grid grid-cols-2 gap-3">
            <MoversList movers={gainers} title="Gainers" isGainer />
            <MoversList movers={losers}  title="Losers"  isGainer={false} />
          </div>
        </section>

        {/* Sectors */}
        <section aria-labelledby="ms-sectors">
          <SectionHeading id="ms-sectors">Sector Performance<ProvChip live={sectorsLive} /></SectionHeading>
          <SectorBars sectors={sectors} />
        </section>
      </div>
    </div>
  );
}

export default memo(MarketSummaryWidget);
