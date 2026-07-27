/**
 * OIChartWidget — "OI Analytics", the canonical open-interest surface.
 *
 * FOUR presentations of ONE option-chain snapshot, chosen by the workspace panel
 * parameter `params.view`:
 *   • "bars" (default) — Plotly grouped CE/PE OI bars by strike with the
 *     per-strike PCR overlay, ATM and max-pain rules.
 *   • "butterfly"      — the retired OI Profile widget's horizontal profile:
 *     CE OI extending right, PE OI extending left, ATM line and a max-pain
 *     arrow annotation, with the optional spot candlestick pane above it.
 *   • "heat"           — the retired OI Heatmap widget's CE/PE strike grid with
 *     per-cell hover readout and the colour legend.
 *   • "signals"        — the retired OI Signals widget's per-strike
 *     LB/SC/SB/LU table plus the z-score unusual-OI chips.
 *   • "pain"           — the retired Market Intelligence Max Pain tab: the
 *     per-strike call/put pain distribution with the max-pain strike called
 *     out. `getMaxPain` has always returned this curve (`strikes[]` with
 *     `call_pain`/`put_pain`/`total_pain`) and every consumer threw all of it
 *     away except `max_pain_strike` — this widget included. The curve is what
 *     says whether the level is a sharp pin or a flat basin, so it is now
 *     drawn from the SAME 60 s max-pain response the butterfly rule uses; no
 *     endpoint and no poll was added.
 *
 * WHY THEY ARE ONE WIDGET. All four answer the same question — where open
 * interest is concentrated across strikes right now. The bar chart and the heat
 * grid called the SAME two endpoints (`getOptionChain` + `getExpiry`) and each
 * re-derived the ATM window, the max-OI strikes and the PCR independently, with
 * different window sizes and — worse — different ΔOI sources. The OI Profile
 * endpoint is itself built from the same broker chain snapshot server-side.
 *
 * ONE FETCH, ONE SHAPE. The chain is normalised once into `StrikeCell[]`
 * (`oiStrikes.ts`) and every chain view renders from that array, so no two
 * views can disagree about a strike. ΔOI comes from the backend's `oi_change`
 * field alone; the bar chart's client-side diffing of successive poll snapshots
 * is deleted, because it measured the gap between two arbitrary client fetches
 * rather than the session change the broker reports — and it was the reason two
 * panels on one screen could show opposite arrows for one strike.
 *
 * The signals view keeps its OWN two endpoints (`/v1/oi/analysis` and
 * `/v1/oi/unusual`) because they are real server-side analytics, not a redraw
 * of the chain — but it now shares this widget's symbol, exchange and expiry
 * selection and its refresh cadence. It previously hard-coded exchange NFO and
 * sent an EMPTY expiry, which the backend rejects as a live-chain identity, so
 * its "Live" state was unreachable; and it had no refresh interval at all, so
 * it was frozen from mount.
 *
 * DATA HONESTY.
 *   - "Sample data" provenance badge whenever the chain plane is not live:
 *     no broker connected, or Explore mode (where `services/api` serves a mock
 *     chain while a broker still reads as connected).
 *   - The signals view carries the tri-state Live / Mixed data / Sample data
 *     badge, which requires an explicit `is_sample_data: false` from BOTH
 *     analytics responses before it will say Live — and is forced to "sample"
 *     whenever the chain plane is sample, so one header can never claim two
 *     different provenances.
 *   - Max pain is drawn only when `getMaxPain` explicitly attests
 *     `is_sample_data: false` and the visible chain has positive OI.
 *   - A missing figure renders as "--", never as 0.
 */

import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense, memo } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { AlertCircle, Loader2, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import type { WidgetProps } from "@/types/widgets";
import { useQuery } from "@tanstack/react-query";
import { getExpiry, getOptionChain, getQuotes, getMaxPain } from "@/services/api";
import {
  getOIChangeAnalysis,
  getUnusualOI,
  type OIChangeSignalRow,
} from "@/services/ftApi";
import type { MaxPainData, Quote } from "@/types/api";
import type { RawOptionChain } from "@/widgets/analysis/OptionChain/types";
import { SYMBOLS } from "@/widgets/analysis/OptionChain/types";
import { isMarketHours } from "@/lib/market";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useLatestRequest } from "@/hooks/useLatestRequest";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import {
  buildStrikeCells,
  chainHasPositiveOi,
  filterStrikeCells,
  positiveFiniteNumber,
  strikePcr,
  summariseStrikeCells,
  OI_FILTERS,
  type OIFilter,
  type StrikeCell,
} from "./oiStrikes";
import { SAMPLE_ATM, SAMPLE_MAX_PAIN, SAMPLE_PAIN_ROWS, SAMPLE_STRIKE_CELLS } from "./sampleData";
import { FlowTapeSection } from "./FlowTape";
import { SAMPLE_ANALYSIS, SAMPLE_UNUSUAL } from "./oiSignalsSample";
import { SPOT_INTERVALS, type SpotInterval } from "./spotIntervals";
import type { Data, Layout } from "plotly.js";

const PlotlyChart = lazy(() =>
  import("@/components/charts/PlotlyChart").then((m) => ({ default: m.PlotlyChart }))
);

// The spot candlestick strip pulls lightweight-charts; keep it out of the
// chunk for the panels that never open it.
const SpotPricePane = lazy(() =>
  import("./SpotPricePane").then((m) => ({ default: m.SpotPricePane }))
);

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * ONE ATM window for every view. The canonical bar chart's ±15 wins over the
 * heat grid's ±10: two views over one snapshot must aggregate the same rows, or
 * their PCR badges and support/resistance chips silently disagree. The heat
 * grid scrolls horizontally at this width.
 */
const STRIKES_AROUND_ATM = 15;

/** Underlyings, and their F&O + spot exchanges, from the canonical table. */
const SYMBOL_CHOICES = SYMBOLS;

type ViewMode = "bars" | "butterfly" | "heat" | "signals" | "pain";

const VIEW_MODES: readonly ViewMode[] = ["bars", "butterfly", "heat", "signals", "pain"];

const VIEW_LABELS: Record<ViewMode, string> = {
  bars: "Bars",
  butterfly: "Butterfly",
  heat: "Heat",
  signals: "Signals",
  pain: "Max Pain",
};

function isViewMode(value: unknown): value is ViewMode {
  return typeof value === "string" && (VIEW_MODES as readonly string[]).includes(value);
}

/** Resolves the workspace `params.view` panel parameter, defaulting to bars. */
function resolveViewMode(value: unknown): ViewMode {
  return isViewMode(value) ? value : "bars";
}

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
// Formatting
// ---------------------------------------------------------------------------

const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** Compact Indian-notation OI for cells, tooltips and signal rows. */
function fmtOi(v: number): string {
  if (Math.abs(v) >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(1)}Cr`;
  if (Math.abs(v) >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

/** Signal-table ΔOI keeps two decimals at crore scale. */
function fmtSignalOi(v: number): string {
  if (Math.abs(v) >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (Math.abs(v) >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

/** Footer totals — "--" when the side is incomplete, never a partial sum. */
function fmtTotalOi(total: number | null): string {
  if (total === null) return "--";
  if (total >= 1e7) return `${(total / 1e7).toFixed(1)}Cr`;
  if (total >= 1e5) return `${(total / 1e5).toFixed(1)}L`;
  return NUM0.format(total);
}

function fmtExpiry(raw: string): string {
  if (!raw) return raw;
  try {
    const d = new Date(raw);
    if (isNaN(d.getTime())) return raw;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  } catch {
    return raw;
  }
}

function signalStyle(short: string) {
  return SIGNAL_STYLE[short] ?? SIGNAL_STYLE.N;
}

/** Poll cadence shared by the chain snapshot and the derived OI analytics. */
function refreshIntervalMs(): number {
  return isMarketHours() ? 5_000 : 30_000;
}

// ---------------------------------------------------------------------------
// Heat-grid colour ramps
// ---------------------------------------------------------------------------

/** Map a 0–1 intensity to an RGBA string for CE (indigo/accent) cells. */
function ceColour(intensity: number): string {
  const r = Math.round(22 + (99 - 22) * intensity);
  const g = Math.round(22 + (102 - 22) * intensity);
  const b = Math.round(31 + (241 - 31) * intensity);
  return `rgba(${r},${g},${b},${0.15 + 0.8 * intensity})`;
}

/** Map a 0–1 intensity to an RGBA string for PE (red/loss) cells. */
function peColour(intensity: number): string {
  const r = Math.round(22 + (239 - 22) * intensity);
  const g = Math.round(22 + (68 - 22) * intensity);
  const b = Math.round(31 + (68 - 31) * intensity);
  return `rgba(${r},${g},${b},${0.15 + 0.8 * intensity})`;
}

/** Read a CSS custom property from the document root at call time. */
function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

// ---------------------------------------------------------------------------
// Heat-grid sub-components
// ---------------------------------------------------------------------------

interface TooltipState {
  visible: boolean;
  x: number;
  y: number;
  strike: number;
  optionType: "CE" | "PE";
  oi: number | null;
  oiChange: number | null;
  volume: number | null;
  pcr: number | null;
}

interface CellProps {
  colour: string;
  oi: number | null;
  oiChange: number | null;
  isATM: boolean;
  isMaxOI: boolean;
  onMouseEnter: (e: ReactMouseEvent<HTMLDivElement>) => void;
  onMouseLeave: () => void;
}

function HeatmapCell({ colour, oi, oiChange, isATM, isMaxOI, onMouseEnter, onMouseLeave }: CellProps) {
  return (
    <div
      className={`relative flex flex-col items-center justify-center h-full cursor-default select-none transition-opacity hover:opacity-90 ${
        isATM ? "ring-1 ring-inset ring-accent/70" : ""
      } ${isMaxOI ? "ring-1 ring-inset ring-warning/60" : ""}`}
      style={{ backgroundColor: colour }}
      data-max-oi={isMaxOI ? "true" : undefined}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <span className="text-xxs font-mono text-text-primary/90 leading-none tabular-nums">
        {oi === null ? "--" : fmtOi(oi)}
      </span>
      {oiChange !== null && oiChange !== 0 && (
        <span className={`mt-0.5 ${oiChange > 0 ? "text-profit" : "text-loss"}`}>
          {oiChange > 0 ? <TrendingUp size={8} /> : <TrendingDown size={8} />}
        </span>
      )}
    </div>
  );
}

function ColourLegend() {
  const stops = Array.from({ length: 5 }, (_, i) => i / 4);
  return (
    <div className="flex-none flex items-center gap-4 px-3 py-1.5 border-t border-border-default text-xs text-text-muted flex-wrap">
      <div className="flex items-center gap-1.5">
        <span className="uppercase tracking-wide text-xxs">CE</span>
        <div className="flex h-3 rounded overflow-hidden" style={{ width: 80 }}>
          {stops.map((v, i) => (
            <div key={i} className="flex-1" style={{ backgroundColor: ceColour(v) }} />
          ))}
        </div>
        <span className="text-xxs">Low → High</span>
      </div>
      <div className="flex items-center gap-1.5">
        <span className="uppercase tracking-wide text-xxs">PE</span>
        <div className="flex h-3 rounded overflow-hidden" style={{ width: 80 }}>
          {stops.map((v, i) => (
            <div key={i} className="flex-1" style={{ backgroundColor: peColour(v) }} />
          ))}
        </div>
        <span className="text-xxs">Low → High</span>
      </div>
      <div className="flex items-center gap-2 ml-auto text-xxs">
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 ring-1 ring-accent/70 rounded-sm" />
          ATM
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-2.5 h-2.5 ring-1 ring-warning/60 rounded-sm" />
          Max OI
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel params
// ---------------------------------------------------------------------------

interface OIAnalyticsPanelParams {
  /** Initial view — how the three retired ids select their old presentation. */
  view?: string;
  /** Whether the spot candlestick strip opens with the panel. */
  price?: boolean;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OIChartWidget(props: WidgetProps) {
  const panelParams = props.params as OIAnalyticsPanelParams | undefined;
  const initialView = resolveViewMode(panelParams?.view);

  const isConnected = useBrokerConnected();
  const isExplore = useModeStore((s) => s.mode === "explore");

  const [view, setView] = useState<ViewMode>(initialView);
  // The retired OI Profile widget always showed its price strip, so a panel
  // that opens on the butterfly view keeps it unless the params say otherwise.
  const [showPrice, setShowPrice] = useState<boolean>(
    typeof panelParams?.price === "boolean" ? panelParams.price : initialView === "butterfly",
  );
  const [spotInterval, setSpotInterval] = useState<SpotInterval>("15m");

  const [symbolIdx, setSymbolIdx] = useState(0);
  const [expiries, setExpiries] = useState<string[]>([]);
  const [selectedExpiryValue, setSelectedExpiry] = useState<string | null>(null);
  const [expiryIdentity, setExpiryIdentity] = useState<string | null>(null);
  const [filter, setFilter] = useState<OIFilter>("All");
  const [priceDir, setPriceDir] = useState<PriceDir>("flat");

  const [chain, setChain] = useState<RawOptionChain | null>(null);
  const [spot, setSpot] = useState<Quote | null>(null);
  const [maxPainStrike, setMaxPainStrike] = useState<number | null>(null);
  // The pain distribution behind that strike. Held separately so the existing
  // max-pain rule keeps its exact fail-closed semantics.
  const [maxPainRows, setMaxPainRows] = useState<MaxPainData["strikes"] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false, x: 0, y: 0, strike: 0, optionType: "CE",
    oi: null, oiChange: null, volume: null, pcr: null,
  });

  const gridRef = useRef<HTMLDivElement>(null);

  const symDef = SYMBOL_CHOICES[symbolIdx];
  const exchange = symDef.exchange;
  // A broker connection change swaps the data source, so it is part of the
  // identity a response has to still match.
  const identityKey = `${isConnected}:${symDef.label}:${exchange}`;
  const currentExpiries = expiryIdentity === identityKey ? expiries : [];
  const expiryCandidate = typeof selectedExpiryValue === "string" ? selectedExpiryValue.trim() : "";
  const selectedExpiry = currentExpiries.includes(expiryCandidate) ? expiryCandidate : null;
  const requestKey = `${identityKey}:${selectedExpiry ?? ""}`;

  // Two independent guards over one identity: max pain deliberately polls on
  // its own 60 s clock and must not consume the chain loop's in-flight slot.
  const chainRequests = useLatestRequest(requestKey);
  const maxPainRequests = useLatestRequest(requestKey);

  // Clear every displayed value the moment the identity changes, so nothing
  // from the previous contract survives on screen while the next load runs.
  useEffect(() => {
    setChain(null);
    setSpot(null);
    setMaxPainStrike(null);
    setMaxPainRows(null);
    setLoading(false);
    setError(null);
    setLastRefresh(null);
    setTooltip((current) => ({ ...current, visible: false }));
  }, [requestKey]);

  // ---- Expiries ------------------------------------------------------------
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setExpiryIdentity(null);
    setChain(null);
    setSpot(null);
    setMaxPainStrike(null);
    setMaxPainRows(null);
    setLoading(false);
    setError(null);
    setLastRefresh(null);
    if (!isConnected) return;

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const rawList = Array.isArray(data)
          ? data
          : ((data as { expiry?: unknown[] })?.expiry ?? []);
        const list = rawList.flatMap((value) => {
          if (typeof value !== "string") return [];
          const expiry = value.trim();
          return expiry ? [expiry] : [];
        });
        setExpiries(list);
        setExpiryIdentity(identityKey);
        setSelectedExpiry(list[0] ?? null);
      } catch (e) {
        if (!cancelled) setError(`Expiry load failed: ${(e as Error).message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [identityKey, symDef.label, exchange, isConnected]);

  // ---- Chain + spot --------------------------------------------------------
  const fetchData = useCallback(async () => {
    if (!isConnected || !selectedExpiry) return;
    const ticket = chainRequests.begin(requestKey);
    if (!ticket) return;
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
      ]);

      if (!ticket.isCurrent()) return;

      if (chainRes.status === "fulfilled") {
        setChain(chainRes.value as unknown as RawOptionChain);
      } else {
        setChain(null);
        setError(`Chain error: ${(chainRes.reason as Error)?.message}`);
      }

      setSpot(spotRes.status === "fulfilled" ? spotRes.value : null);
    } finally {
      if (ticket.settle()) {
        setLoading(false);
        setLastRefresh(new Date());
      }
    }
  }, [
    chainRequests, requestKey, isConnected, selectedExpiry,
    symDef.label, symDef.spotSymbol, symDef.spotExchange, exchange,
  ]);

  useEffect(() => {
    if (!isConnected || !selectedExpiry) return;
    void fetchData();
    const id = setInterval(() => void fetchData(), refreshIntervalMs());
    return () => {
      clearInterval(id);
      chainRequests.invalidate();
    };
  }, [chainRequests, fetchData, isConnected, selectedExpiry]);

  // ---- Max pain (independent 60 s clock) -----------------------------------
  const fetchMaxPain = useCallback(async () => {
    if (!isConnected || !selectedExpiry) return;
    const ticket = maxPainRequests.begin(requestKey);
    if (!ticket) return;
    setMaxPainStrike(null);
    setMaxPainRows(null);
    try {
      const data = await getMaxPain(symDef.label, exchange, selectedExpiry);
      if (!ticket.isCurrent()) return;
      // Fail closed: a max pain that is not explicitly attested live is not
      // drawn at all, rather than drawn as if it were the real level.
      const isLive = data.is_sample_data === false;
      setMaxPainStrike(
        isLive
          && typeof data.max_pain_strike === "number"
          && Number.isFinite(data.max_pain_strike)
          && data.max_pain_strike > 0
          ? data.max_pain_strike
          : null,
      );
      // The curve is held to the SAME attestation as the strike — a pain
      // distribution that is not explicitly live is not charted at all. The
      // array is checked, not assumed: a broker/backend that answers with only
      // a strike must render the empty state, not crash the widget.
      setMaxPainRows(
        isLive && Array.isArray(data.strikes) && data.strikes.length > 0 ? data.strikes : null,
      );
    } catch {
      if (ticket.isCurrent()) {
        setMaxPainStrike(null);
        setMaxPainRows(null);
      }
    } finally {
      ticket.settle();
    }
  }, [maxPainRequests, requestKey, isConnected, selectedExpiry, symDef.label, exchange]);

  useEffect(() => {
    if (!isConnected || !selectedExpiry) return;
    void fetchMaxPain();
    const id = setInterval(() => void fetchMaxPain(), 60_000);
    return () => {
      clearInterval(id);
      maxPainRequests.invalidate();
    };
  }, [fetchMaxPain, maxPainRequests, isConnected, selectedExpiry]);

  // ---- Signals analytics (its own endpoints, this widget's selection) -------
  // Never fire with an empty expiry: the backend cannot resolve a live chain
  // without one, so it would answer with a sample and the view could never be
  // Live. That is exactly the bug the retired widget shipped with.
  const signalsExpiry = selectedExpiry ?? "";
  const signalsEnabled = isConnected && view === "signals" && signalsExpiry !== "";
  const analysisQuery = useQuery({
    queryKey: ["oiAnalysis", symDef.label, exchange, signalsExpiry, priceDir],
    queryFn: () => getOIChangeAnalysis(symDef.label, exchange, signalsExpiry, priceDir),
    enabled: signalsEnabled,
    refetchInterval: signalsEnabled ? refreshIntervalMs() : false,
  });
  const unusualQuery = useQuery({
    queryKey: ["oiUnusual", symDef.label, exchange, signalsExpiry],
    queryFn: () => getUnusualOI(symDef.label, exchange, signalsExpiry),
    enabled: signalsEnabled,
    refetchInterval: signalsEnabled ? refreshIntervalMs() : false,
  });

  // ---- Normalised strike cells --------------------------------------------
  const spotLtp = positiveFiniteNumber(spot?.ltp);

  const { cells: liveCells, atmStrike: liveAtm } = useMemo(
    () => buildStrikeCells(
      chain,
      spotLtp ?? positiveFiniteNumber(chain?.underlying_ltp),
      STRIKES_AROUND_ATM,
    ),
    [chain, spotLtp],
  );

  // Explore mode reports a connection while `services/api` serves a mock chain,
  // so "connected" alone is not evidence of live data.
  const showingSampleChain = !isConnected || isExplore;
  const usingSampleCells = !isConnected;

  const allCells = usingSampleCells ? SAMPLE_STRIKE_CELLS : liveCells;
  const atmStrike = usingSampleCells ? SAMPLE_ATM : liveAtm;

  const rows = useMemo(() => filterStrikeCells(allCells, filter), [allCells, filter]);
  const summary = useMemo(() => summariseStrikeCells(rows), [rows]);

  const visibleMaxPainStrike = usingSampleCells
    ? SAMPLE_MAX_PAIN
    : chain !== null && !loading && !error && chainHasPositiveOi(allCells)
      ? maxPainStrike
      : null;

  // ---- Max pain curve (the "pain" view) ------------------------------------
  // The sample curve rides the sample chain, exactly as the sample max-pain
  // rule does, so the two can never disagree about the sample.
  const painRows: MaxPainData["strikes"] = usingSampleCells
    ? SAMPLE_PAIN_ROWS
    : maxPainRows ?? [];
  const painMax = useMemo(
    () => painRows.reduce((max, row) => Math.max(max, row.total_pain), 0),
    [painRows],
  );
  /** True when every row carries the call/put split, so the stack is honest. */
  const painHasSplit = useMemo(
    () => painRows.length > 0
      && painRows.every((row) => row.call_pain !== undefined && row.put_pain !== undefined),
    [painRows],
  );

  // ---- Provenance ----------------------------------------------------------
  const analysisIsLive = isConnected
    && analysisQuery.isSuccess
    && analysisQuery.data?.is_sample_data === false;
  const unusualIsLive = isConnected
    && unusualQuery.isSuccess
    && unusualQuery.data?.is_sample_data === false;
  // The chain plane's provenance caps the signals badge: one header must not
  // claim "Live" analytics while its own spot/PCR context is a mock chain.
  const signalsProvenance: "live" | "mixed" | "sample" = showingSampleChain
    ? "sample"
    : analysisIsLive && unusualIsLive
      ? "live"
      : analysisIsLive || unusualIsLive
        ? "mixed"
        : "sample";

  const analysis = analysisQuery.data ?? SAMPLE_ANALYSIS;
  const unusual = unusualQuery.data ?? SAMPLE_UNUSUAL;
  const signalRows: OIChangeSignalRow[] = useMemo(
    () => [...analysis.signals].sort((a, b) => a.strike - b.strike),
    [analysis],
  );
  const signalsFetching = analysisQuery.isFetching || unusualQuery.isFetching;

  // ---- View + params -------------------------------------------------------
  const handleViewChange = useCallback((next: ViewMode) => {
    if (next === view) return;
    setView(next);
    props.api.updateParameters({ view: next });
  }, [panelParams, props.api, view]);

  const handlePriceToggle = useCallback(() => {
    setShowPrice((current) => {
      const next = !current;
      props.api.updateParameters({ price: next });
      return next;
    });
  }, [panelParams, props.api]);

  const handleRefresh = useCallback(() => {
    void fetchData();
    if (view === "signals") {
      void analysisQuery.refetch();
      void unusualQuery.refetch();
    }
  }, [analysisQuery, fetchData, unusualQuery, view]);

  // ---- Tooltip -------------------------------------------------------------
  const handleCellEnter = useCallback(
    (e: ReactMouseEvent<HTMLDivElement>, cell: StrikeCell, type: "CE" | "PE") => {
      const rect = gridRef.current?.getBoundingClientRect();
      setTooltip({
        visible: true,
        x: rect ? e.clientX - rect.left : e.clientX,
        y: rect ? e.clientY - rect.top : e.clientY,
        strike: cell.strike,
        optionType: type,
        oi: type === "CE" ? cell.ceOi : cell.peOi,
        oiChange: type === "CE" ? cell.ceOiChange : cell.peOiChange,
        volume: type === "CE" ? cell.ceVolume : cell.peVolume,
        pcr: strikePcr(cell),
      });
    },
    [],
  );

  const handleCellLeave = useCallback(() => {
    setTooltip((t) => ({ ...t, visible: false }));
  }, []);

  // ---- Bars geometry -------------------------------------------------------
  const { plotData, plotLayout } = useMemo<{ plotData: Data[]; plotLayout: Partial<Layout> }>(() => {
    if (view !== "bars" || rows.length === 0) return { plotData: [], plotLayout: {} };

    const strikes = rows.map((r) => r.strike);
    const pcrPerStrike = rows.map((r) => {
      const value = strikePcr(r);
      return value === null ? null : parseFloat(value.toFixed(3));
    });

    const data: Data[] = [
      {
        name: "CE OI",
        type: "bar",
        x: strikes,
        y: rows.map((r) => r.ceOi),
        marker: { color: "rgba(239, 68, 68, 0.7)" },
        hovertemplate: "Strike: %{x}<br>CE OI: %{y:,.0f}<extra></extra>",
      },
      {
        name: "PE OI",
        type: "bar",
        x: strikes,
        y: rows.map((r) => r.peOi),
        marker: { color: "rgba(34, 197, 94, 0.7)" },
        hovertemplate: "Strike: %{x}<br>PE OI: %{y:,.0f}<extra></extra>",
      },
      {
        name: "PCR",
        type: "scatter",
        mode: "lines",
        x: strikes,
        y: pcrPerStrike,
        yaxis: "y2",
        line: { color: "#60a5fa", width: 2, dash: "dot" },
        hovertemplate: "Strike: %{x}<br>PCR: %{y:.2f}<extra></extra>",
      },
    ];

    const shapes: Partial<Layout>["shapes"] = [];
    const annotations: Partial<Layout>["annotations"] = [];

    if (atmStrike != null) {
      shapes.push({
        type: "line",
        x0: atmStrike, x1: atmStrike,
        y0: 0, y1: 1,
        yref: "paper",
        line: { color: "#fbbf24", width: 2, dash: "dash" },
      });
      annotations.push({
        x: atmStrike, y: 1.04,
        xref: "x", yref: "paper",
        text: "ATM",
        showarrow: false,
        font: { color: "#fbbf24", size: 10 },
      });
    }

    if (visibleMaxPainStrike != null) {
      shapes.push({
        type: "line",
        x0: visibleMaxPainStrike, x1: visibleMaxPainStrike,
        y0: 0, y1: 1,
        yref: "paper",
        line: { color: "#a78bfa", width: 2, dash: "dash" },
      });
      annotations.push({
        x: visibleMaxPainStrike, y: 1.04,
        xref: "x", yref: "paper",
        text: "MP",
        showarrow: false,
        font: { color: "#a78bfa", size: 10 },
      });
    }

    const layout: Partial<Layout> = {
      barmode: "group",
      bargap: 0.15,
      bargroupgap: 0.05,
      margin: { t: 24, r: 55, b: 40, l: 55 },
      xaxis: {
        title: { text: "Strike", font: { size: 10 } },
        tickfont: { size: 9 },
        tickangle: -45,
      },
      yaxis: {
        title: { text: "OI", font: { size: 10 } },
        tickfont: { size: 9 },
      },
      yaxis2: {
        title: { text: "PCR", font: { size: 10 } },
        overlaying: "y",
        side: "right",
        tickfont: { size: 9 },
        range: [0, Math.max(3, ...pcrPerStrike.filter((v): v is number => v !== null)) * 1.2],
        showgrid: false,
      },
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.02,
        xanchor: "right",
        x: 1,
        font: { size: 10 },
      },
      shapes,
      annotations,
    };

    return { plotData: data, plotLayout: layout };
  }, [view, rows, atmStrike, visibleMaxPainStrike]);

  // ---- Butterfly geometry --------------------------------------------------
  const { butterflyData, butterflyLayout } = useMemo<{
    butterflyData: Data[];
    butterflyLayout: Partial<Layout>;
  }>(() => {
    if (view !== "butterfly" || rows.length === 0) return { butterflyData: [], butterflyLayout: {} };

    const strikes = rows.map((r) => r.strike);
    const data: Data[] = [
      {
        type: "bar",
        name: "CE OI",
        x: rows.map((r) => r.ceOi),
        y: strikes,
        orientation: "h",
        marker: { color: "rgba(239,68,68,0.65)" },
        hovertemplate: "Strike: %{y}<br>CE OI: %{x:.3s}<extra></extra>",
      } as Data,
      {
        type: "bar",
        name: "PE OI",
        // Negative = left of the zero line.
        x: rows.map((r) => (r.peOi === null ? null : -r.peOi)),
        y: strikes,
        orientation: "h",
        marker: { color: "rgba(34,197,94,0.65)" },
        hovertemplate: "Strike: %{y}<br>PE OI: %{x:.3s}<extra></extra>",
      } as Data,
    ];

    const annotations: Partial<Layout>["annotations"] = [];
    if (visibleMaxPainStrike != null) {
      annotations.push({
        y: visibleMaxPainStrike,
        x: 0,
        xref: "x" as const,
        text: `Max Pain ${visibleMaxPainStrike}`,
        showarrow: true,
        arrowhead: 2,
        arrowcolor: "#f59e0b",
        font: { size: 9, color: "#f59e0b" },
        ax: 50,
        ay: 0,
      });
    }

    const shapes: Partial<Layout>["shapes"] = [];
    if (atmStrike != null) {
      shapes.push({
        type: "line",
        y0: atmStrike,
        y1: atmStrike,
        x0: 0,
        x1: 1,
        xref: "paper" as const,
        line: { color: "#6366f1", width: 1, dash: "dash" },
      });
    }

    const layout: Partial<Layout> = {
      barmode: "overlay",
      xaxis: {
        title: { text: "Open Interest" },
        tickformat: ".3s",
        zeroline: true,
        zerolinecolor: getThemeColor("--color-border", "#2a2a3a"),
        zerolinewidth: 1,
        automargin: true,
      },
      yaxis: {
        title: { text: "Strike", standoff: 6 },
        tickformat: ",.0f",
        tickmode: "auto",
        // Capped so a compact panel does not overlap its strike labels.
        nticks: 8,
        automargin: true,
      },
      margin: { t: 10, r: 10, b: 45, l: 68 },
      annotations,
      shapes,
    };

    return { butterflyData: data, butterflyLayout: layout };
  }, [view, rows, atmStrike, visibleMaxPainStrike]);

  const expiryButtons = currentExpiries.slice(0, 5);
  const pcr = summary.pcr;
  const chartFallback = (
    <div role="status" className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
      <RefreshCw size={13} className="animate-spin" aria-hidden="true" />
      <span className="sr-only">Loading chart...</span>
      <span aria-hidden="true">Loading chart…</span>
    </div>
  );

  // ---- Bodies --------------------------------------------------------------
  const heatBody = (
    <div
      ref={gridRef}
      data-testid="oi-heat-grid"
      className="relative flex-1 min-h-0 flex flex-col overflow-auto px-2 py-1.5 gap-1"
    >
      <div className="flex gap-px" style={{ minHeight: 52 }}>
        <div className="flex-none w-7 flex items-center justify-center">
          <span
            className="text-xxs text-text-muted rotate-180 font-mono uppercase tracking-wider"
            style={{ writingMode: "vertical-rl" }}
          >
            CE
          </span>
        </div>
        {rows.map((cell) => (
          <div key={`ce-${cell.strike}`} className="flex-1 min-w-0" style={{ minWidth: 32, height: 52 }}>
            <HeatmapCell
              colour={ceColour(cell.ceOi !== null && summary.maxCeOi > 0 ? cell.ceOi / summary.maxCeOi : 0)}
              oi={cell.ceOi}
              oiChange={cell.ceOiChange}
              isATM={cell.strike === atmStrike}
              isMaxOI={summary.maxCeStrike !== null && cell.strike === summary.maxCeStrike}
              onMouseEnter={(e) => handleCellEnter(e, cell, "CE")}
              onMouseLeave={handleCellLeave}
            />
          </div>
        ))}
      </div>

      <div className="flex gap-px">
        <div className="flex-none w-7" />
        {rows.map((cell) => (
          <div key={`lbl-${cell.strike}`} className="flex-1 min-w-0 flex items-center justify-center" style={{ minWidth: 32 }}>
            <span className={`text-xxs font-mono tabular-nums leading-none ${
              cell.strike === atmStrike ? "text-accent font-semibold" : "text-text-muted"
            }`}>
              {cell.strike}
            </span>
          </div>
        ))}
      </div>

      <div className="flex gap-px" style={{ minHeight: 52 }}>
        <div className="flex-none w-7 flex items-center justify-center">
          <span
            className="text-xxs text-text-muted rotate-180 font-mono uppercase tracking-wider"
            style={{ writingMode: "vertical-rl" }}
          >
            PE
          </span>
        </div>
        {rows.map((cell) => (
          <div key={`pe-${cell.strike}`} className="flex-1 min-w-0" style={{ minWidth: 32, height: 52 }}>
            <HeatmapCell
              colour={peColour(cell.peOi !== null && summary.maxPeOi > 0 ? cell.peOi / summary.maxPeOi : 0)}
              oi={cell.peOi}
              oiChange={cell.peOiChange}
              isATM={cell.strike === atmStrike}
              isMaxOI={summary.maxPeStrike !== null && cell.strike === summary.maxPeStrike}
              onMouseEnter={(e) => handleCellEnter(e, cell, "PE")}
              onMouseLeave={handleCellLeave}
            />
          </div>
        ))}
      </div>

      {tooltip.visible && (
        <div
          className="absolute z-50 pointer-events-none bg-surface-card border border-border-default rounded-md shadow-lg p-2 text-xs min-w-[120px]"
          style={{ left: tooltip.x + 12, top: tooltip.y - 8 }}
          data-testid="oi-tooltip"
        >
          <div className="font-semibold text-text-primary mb-1">
            {tooltip.strike} {tooltip.optionType}
          </div>
          <div className="flex flex-col gap-0.5 text-xxs">
            <div className="flex justify-between gap-3">
              <span className="text-text-muted">OI</span>
              <span className="font-mono tabular-nums text-text-primary">
                {tooltip.oi === null ? "--" : fmtOi(tooltip.oi)}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-text-muted">OI Chg</span>
              <span className={`font-mono tabular-nums ${
                tooltip.oiChange === null
                  ? "text-text-muted"
                  : tooltip.oiChange >= 0 ? "text-profit" : "text-loss"
              }`}>
                {tooltip.oiChange === null
                  ? "--"
                  : `${tooltip.oiChange >= 0 ? "+" : ""}${fmtOi(Math.abs(tooltip.oiChange))}`}
              </span>
            </div>
            <div className="flex justify-between gap-3">
              <span className="text-text-muted">Volume</span>
              <span className="font-mono tabular-nums text-text-primary">
                {tooltip.volume === null ? "--" : fmtOi(tooltip.volume)}
              </span>
            </div>
            {tooltip.pcr !== null && (
              <div className="flex justify-between gap-3">
                <span className="text-text-muted">PCR</span>
                <span className="font-mono tabular-nums text-text-primary">{tooltip.pcr.toFixed(2)}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  const signalsBody = (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Summary chips */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex-wrap text-xxs">
        {(["Long Build-up", "Short Covering", "Short Build-up", "Long Unwinding"] as const).map((label) => {
          const short = label === "Long Build-up" ? "LB"
            : label === "Short Covering" ? "SC"
              : label === "Short Build-up" ? "SB" : "LU";
          const style = signalStyle(short);
          return (
            <span key={label} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 ${style.cls}`} title={label}>
              <span className="font-semibold">{short}</span>
              <span className="tabular-nums">{analysis.summary[label] ?? 0}</span>
            </span>
          );
        })}
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {signalRows.length === 0 ? (
          <p className="text-xs text-text-muted text-center py-8">No OI signals for {symDef.label}.</p>
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
              {signalRows.map((s, i) => {
                const style = signalStyle(s.signal_short);
                return (
                  <TableRow key={`${s.strike}-${s.option_type}-${i}`} className="border-border-subtle hover:bg-surface-hover">
                    <TableCell className="text-xs font-mono text-text-primary py-1">{s.strike}</TableCell>
                    <TableCell className="text-xs text-text-secondary py-1">{s.option_type}</TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-1 text-right tabular-nums">{fmtSignalOi(s.oi)}</TableCell>
                    <TableCell className={`text-xs font-mono py-1 text-right tabular-nums ${s.oi_change >= 0 ? "text-profit" : "text-loss"}`}>
                      {s.oi_change >= 0 ? "+" : ""}{fmtSignalOi(s.oi_change)}
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
          {signalsFetching && <span className="text-xxs text-text-muted">· updating…</span>}
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
          </div>
        )}
      </div>

      {/* Large-trade tape — folded in from the retired Options Flow widget
          (ruling D1); collapsed and sample-labelled, see FlowTape.tsx. */}
      <FlowTapeSection />
    </div>
  );

  // ---- Max Pain view -------------------------------------------------------
  // The pain curve, with the max-pain strike called out. Rows arrive already
  // gated on an explicit `is_sample_data: false`, so an unattested or failed
  // response renders the empty state rather than an unlabelled curve.
  const painBody = (
    <div className="flex-1 min-h-0 overflow-auto">
      {painRows.length === 0 ? (
        <p className="text-xs text-text-muted text-center py-8">
          {isConnected && !selectedExpiry
            ? "Select an expiry to load the pain distribution"
            : `No attested max-pain distribution for ${symDef.label}.`}
        </p>
      ) : (
        <>
          <div className="px-2 py-2 space-y-1">
            {painRows.map((row) => {
              const isMax = visibleMaxPainStrike != null && row.strike === visibleMaxPainStrike;
              const callPct = painMax > 0 && painHasSplit ? ((row.call_pain ?? 0) / painMax) * 100 : 0;
              const putPct = painMax > 0 && painHasSplit ? ((row.put_pain ?? 0) / painMax) * 100 : 0;
              const totalPct = painMax > 0 ? (row.total_pain / painMax) * 100 : 0;
              return (
                <div
                  key={row.strike}
                  className="flex items-center gap-2"
                  aria-label={`Strike ${row.strike} total pain ${row.total_pain}${isMax ? " (max pain)" : ""}`}
                >
                  <span
                    className={`w-20 shrink-0 text-xxs font-mono tabular-nums ${
                      isMax ? "text-accent font-semibold" : "text-text-secondary"
                    }`}
                  >
                    {NUM0.format(row.strike)}
                    {isMax && <span className="ml-1 text-xxs">MAX</span>}
                  </span>
                  <div className="flex-1 h-3 bg-surface-hover rounded-sm overflow-hidden flex">
                    {painHasSplit ? (
                      <>
                        <div className="h-full bg-profit/60" style={{ width: `${callPct}%` }} />
                        <div className="h-full bg-loss/60" style={{ width: `${putPct}%` }} />
                      </>
                    ) : (
                      <div className="h-full bg-accent/50" style={{ width: `${totalPct}%` }} />
                    )}
                  </div>
                  <span className="w-16 shrink-0 text-right text-xxs font-mono tabular-nums text-text-muted">
                    {fmtOi(row.total_pain)}
                  </span>
                </div>
              );
            })}
          </div>

          <Table>
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                <TableHead className="text-xxs text-text-muted font-medium">Strike</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">CE OI</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">PE OI</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">Call pain</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">Put pain</TableHead>
                <TableHead className="text-xxs text-text-muted font-medium text-right">Total pain</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {painRows.map((row) => {
                const isMax = visibleMaxPainStrike != null && row.strike === visibleMaxPainStrike;
                return (
                  <TableRow
                    key={row.strike}
                    className={`border-border-subtle hover:bg-surface-hover ${isMax ? "bg-accent/5" : ""}`}
                  >
                    <TableCell className="text-xs font-mono text-text-primary py-1">
                      {NUM0.format(row.strike)}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-loss py-1 text-right tabular-nums">
                      {row.call_oi === undefined ? "--" : fmtOi(row.call_oi)}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-profit py-1 text-right tabular-nums">
                      {row.put_oi === undefined ? "--" : fmtOi(row.put_oi)}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-1 text-right tabular-nums">
                      {row.call_pain === undefined ? "--" : fmtOi(row.call_pain)}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-secondary py-1 text-right tabular-nums">
                      {row.put_pain === undefined ? "--" : fmtOi(row.put_pain)}
                    </TableCell>
                    <TableCell className="text-xs font-mono text-text-primary py-1 text-right tabular-nums font-semibold">
                      {fmtOi(row.total_pain)}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>

          <p className="px-2 py-1.5 text-xxs text-text-muted border-t border-border-subtle">
            Pain is what option writers would pay out if the underlying expired at
            each strike. The lowest bar is where buyers collectively lose most —
            a sharp trough pins harder than a flat basin.
          </p>
        </>
      )}
    </div>
  );

  const chartBody = (
    <div className="flex-1 min-h-0 overflow-hidden">
      {isConnected && !selectedExpiry && !loading ? (
        <div className="h-full flex items-center justify-center text-text-muted text-xs">
          Select an expiry to load OI data
        </div>
      ) : loading && !chain ? (
        <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
          <Loader2 size={13} className="animate-spin" />
          Loading open interest…
        </div>
      ) : rows.length === 0 ? (
        <div className="h-full flex items-center justify-center text-text-muted text-xs">
          {filter !== "All" ? "No strikes match the filter" : "No OI data"}
        </div>
      ) : (
        <Suspense fallback={chartFallback}>
          <PlotlyChart
            data={view === "butterfly" ? butterflyData : plotData}
            layout={view === "butterfly" ? butterflyLayout : plotLayout}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%", height: "100%" }}
          />
        </Suspense>
      )}
    </div>
  );

  const emptyHeat = (
    <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
      {loading && !chain
        ? <span className="flex items-center gap-2"><Loader2 size={16} className="animate-spin" />Loading OI data...</span>
        : filter !== "All" ? "No strikes match the filter" : "Select symbol and expiry to view the OI heat grid"}
    </div>
  );

  // ---- Render --------------------------------------------------------------
  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none" data-testid="oianalytics-widget">

      {/* Header row 1 */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">
        <div className="flex items-center gap-1.5 flex-wrap">
          {view === "signals" ? (
            signalsProvenance === "live" ? (
              <span
                className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
                role="status"
                aria-label="Live: OI signals from the connected broker's option chain"
                title="Live — OI-action classification + unusual-OI from the connected broker's chain."
              >
                Live
              </span>
            ) : signalsProvenance === "mixed" ? (
              <span
                className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
                role="status"
                aria-label="Showing mixed live and sample OI data"
                title="Only one OI response is explicitly live; the other section is sample or unavailable."
              >
                Mixed data
              </span>
            ) : (
              <span
                className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
                role="status"
                aria-label="Showing sample data, not live open interest"
                title="Sample OI signals so the widget is usable in explore mode — connect a broker for live data."
              >
                Sample data
              </span>
            )
          ) : showingSampleChain ? (
            <span
              className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
              role="status"
              aria-label="Showing sample data, not live open interest"
              title="Sample data — illustrative values, not a live option chain."
            >
              Sample data
            </span>
          ) : null}

          <Select value={String(symbolIdx)} onValueChange={(v) => setSymbolIdx(Number(v))}>
            <SelectTrigger className="h-7 px-2 text-xs w-36" data-testid="symbol-select" aria-label="Underlying symbol">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {SYMBOL_CHOICES.map((s, i) => (
                <SelectItem key={s.label} value={String(i)} className="text-xs">{s.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <span className="px-2 py-1 text-xs font-medium text-text-muted bg-surface-base border border-border-default rounded">
            {exchange}
          </span>

          <div className="flex items-center gap-1" data-testid="expiry-strip">
            {expiryButtons.length === 0 && !loading && (
              <span className="text-xs text-text-muted px-1">No expiries</span>
            )}
            {expiryButtons.map((exp) => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
                  exp === selectedExpiry
                    ? "bg-accent/15 border-accent/60 text-accent"
                    : "bg-surface-hover border-border-default text-text-secondary hover:text-text-primary hover:border-accent/30"
                }`}
              >
                {fmtExpiry(exp)}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {/* View switcher */}
          <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
            {VIEW_MODES.map((mode) => (
              <button
                key={mode}
                onClick={() => handleViewChange(mode)}
                aria-pressed={mode === view}
                className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                  mode === view
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {VIEW_LABELS[mode]}
              </button>
            ))}
          </div>

          <button
            onClick={handlePriceToggle}
            aria-pressed={showPrice}
            className={`px-2 py-0.5 text-xs font-medium rounded border transition-colors ${
              showPrice
                ? "bg-accent/15 border-accent/60 text-accent"
                : "bg-surface-hover border-border-default text-text-muted hover:text-text-primary"
            }`}
            title="Show the underlying spot candlestick strip"
          >
            Spot chart
          </button>

          <button
            onClick={handleRefresh}
            disabled={!isConnected || loading || !selectedExpiry}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
            data-testid="refresh-btn"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Header row 2 — shared context, then the per-view control */}
        <div className="flex items-center gap-2 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono tabular-nums text-sm font-semibold text-text-primary">
                {spotLtp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
              </span>
            </div>
          ) : (
            <span className="text-xs text-text-muted">Spot: —</span>
          )}

          {pcr != null && (
            <span className={`px-2 py-0.5 rounded text-xxs font-medium border font-mono ${
              pcr >= 1.2
                ? "text-profit bg-profit/10 border-profit/30"
                : pcr <= 0.8
                  ? "text-loss bg-loss/10 border-loss/30"
                  : "text-warning bg-warning/10 border-warning/30"
            }`}>
              PCR: {pcr.toFixed(2)}
              <span className="ml-1 font-normal opacity-70 text-xxs">
                {pcr >= 1.2 ? "Bullish" : pcr <= 0.8 ? "Bearish" : "Neutral"}
              </span>
            </span>
          )}

          {visibleMaxPainStrike != null && (
            <span className="px-2 py-0.5 rounded text-xxs font-medium bg-purple-500/20 text-purple-400 border border-purple-500/30 font-mono">
              Max Pain: {NUM0.format(visibleMaxPainStrike)}
            </span>
          )}

          {summary.maxPeStrike != null && (
            <span className="text-xxs text-profit/80 bg-profit/10 border border-profit/20 rounded px-1 py-0.5 font-mono">
              S {NUM0.format(summary.maxPeStrike)}
            </span>
          )}
          {summary.maxCeStrike != null && (
            <span className="text-xxs text-loss/80 bg-loss/10 border border-loss/20 rounded px-1 py-0.5 font-mono">
              R {NUM0.format(summary.maxCeStrike)}
            </span>
          )}

          <div className="flex-1" />

          {showPrice && (
            <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
              {SPOT_INTERVALS.map((iv) => (
                <button
                  key={iv}
                  onClick={() => setSpotInterval(iv)}
                  className={`px-1.5 py-0.5 text-xxs font-medium transition-colors ${
                    iv === spotInterval
                      ? "bg-accent/15 text-accent"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  {iv}
                </button>
              ))}
            </div>
          )}

          {view === "signals" ? (
            <Select value={priceDir} onValueChange={(v) => setPriceDir(v as PriceDir)}>
              <SelectTrigger
                className="h-7 w-24 text-xs bg-surface-hover border-border-default text-text-primary"
                aria-label="Underlying price direction"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PRICE_DIRS.map((d) => (
                  <SelectItem key={d.value} value={d.value} className="text-xs">{d.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : view === "pain" ? (
            /* The ΔOI filter selects chain cells; the pain curve is computed
               server-side over the whole chain, so the control would sit there
               doing nothing. A dead affordance is worse than no affordance. */
            null
          ) : (
            <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
              {OI_FILTERS.map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  aria-pressed={f === filter}
                  className={`px-2 py-0.5 text-xs font-medium transition-colors ${
                    f === filter
                      ? "bg-accent/15 text-accent"
                      : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* Optional spot candlestick strip */}
      {showPrice && (
        <div className="flex-none h-[32%] border-b border-border-default">
          <Suspense fallback={<div className="h-full" />}>
            <SpotPricePane
              symbol={symDef.spotSymbol}
              spotExchange={symDef.spotExchange}
              interval={spotInterval}
            />
          </Suspense>
        </div>
      )}

      {/* Body */}
      {view === "signals"
        ? signalsBody
        : view === "pain"
          ? painBody
          : view === "heat"
            ? (rows.length > 0 ? heatBody : emptyHeat)
            : chartBody}

      {view === "heat" && rows.length > 0 && <ColourLegend />}

      {/* Footer totals — the pain view aggregates writer loss, not OI, so the
          CE/PE totals would be answering a different question there. */}
      {view !== "signals" && view !== "pain" && rows.length > 0 && (
        <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1 flex items-center gap-4 text-xs">
          <span className="text-text-muted uppercase tracking-wide">Total</span>
          <span className="text-loss font-mono tabular-nums">CE {fmtTotalOi(summary.totalCeOi)}</span>
          <span className="text-profit font-mono tabular-nums">PE {fmtTotalOi(summary.totalPeOi)}</span>
          {atmStrike != null && (
            <span className="text-text-muted ml-1">
              ATM: <span className="font-mono text-warning">{NUM0.format(atmStrike)}</span>
            </span>
          )}
          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-text-muted">
              <RefreshCw size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
              <span className="ml-1">{isMarketHours() ? "· 5s" : "· 30s"}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(OIChartWidget);
