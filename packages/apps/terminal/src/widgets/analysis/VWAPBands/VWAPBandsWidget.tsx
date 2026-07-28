/**
 * VWAPBandsWidget — Intraday VWAP with 1σ/2σ/3σ bands for FlintTrade terminal.
 *
 * Features:
 *   - Pure SVG line chart — VWAP + price line
 *   - Upper/lower bands at 1σ, 2σ, 3σ — filled between bands
 *   - Symbol selector
 *
 * DATA HONESTY: when a broker is connected, the widget fetches live intraday
 * 5-minute bars via the shared `/api/v1/history` path (`getHistory`) and shows
 * a "Live" badge. The bands for those real bars come from the backend route
 * POST /v1/indicators/vwap (server maths is CANONICAL — volume-weighted σ
 * about the running VWAP, i.e. anchored-VWAP bands); while that call is in
 * flight or if it fails (e.g. an all-zero-volume index session has no defined
 * VWAP server-side), the widget computes locally from the SAME live bars, so
 * the "Live" badge stays honest either way. When no broker is connected — or
 * the broker returns no bars for the latest session (market closed, holiday) —
 * the widget falls back to deterministic SAMPLE bars and shows an amber
 * "Sample data" badge so the data is never mistaken for live. There is no
 * deceptive "auto-refresh" clock; TanStack Query owns refetching.
 */

import { useState, useMemo, memo } from "react";
import { Waves, ChevronDown } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { FlintBandedLineChart } from "@flinttrade/design-system";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import type { OHLCVBar as ApiBar } from "@/types/api";
import { postVwapBands, type VwapBandsResponse } from "./api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OHLCVBar {
  time: string;  // HH:MM
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/** A live session bar — an {@link OHLCVBar} that also carries the ISO
 *  wall-clock timestamp the server VWAP route needs. */
interface SessionBar extends OHLCVBar {
  timestamp: string; // "YYYY-MM-DDTHH:MM:SS" (IST)
}

interface VWAPPoint {
  time: string;
  price: number;
  vwap: number;
  upper1: number;
  lower1: number;
  upper2: number;
  lower2: number;
  upper3: number;
  lower3: number;
}

// ---------------------------------------------------------------------------
// VWAP computation — LOCAL FALLBACK ONLY
// ---------------------------------------------------------------------------
//
// The backend route POST /v1/indicators/vwap is canonical when a broker is
// connected. Its maths differs from this fallback: the server uses the
// volume-weighted deviation of typical price about the running VWAP (anchored-
// VWAP bands), whereas this local version uses the UNWEIGHTED std-dev of
// typical prices about their own mean — so bands visibly change width when
// the server responds. This version stays for (a) sample bars in Explore /
// disconnected states, and (b) an honest live fallback while the server call
// is in flight or when it fails (a zero-volume index session has no defined
// VWAP server-side, but real prices are still worth charting).

function computeVWAP(bars: OHLCVBar[]): VWAPPoint[] {
  let cumTPV = 0;
  let cumVol = 0;
  const points: VWAPPoint[] = [];
  const typicals: number[] = [];

  bars.forEach((bar) => {
    const tp = (bar.high + bar.low + bar.close) / 3;
    cumTPV += tp * bar.volume;
    cumVol += bar.volume;
    typicals.push(tp);
    const vwap = cumVol > 0 ? cumTPV / cumVol : tp;

    // Rolling std dev of typical prices
    const mean = typicals.reduce((s, v) => s + v, 0) / typicals.length;
    const variance =
      typicals.reduce((s, v) => s + (v - mean) ** 2, 0) / typicals.length;
    const std = Math.sqrt(variance);

    points.push({
      time: bar.time,
      price: bar.close,
      vwap,
      upper1: vwap + std,
      lower1: vwap - std,
      upper2: vwap + 2 * std,
      lower2: vwap - 2 * std,
      upper3: vwap + 3 * std,
      lower3: vwap - 3 * std,
    });
  });

  return points;
}

// ---------------------------------------------------------------------------
// Live intraday bars (via /api/v1/history) → single-session widget bars
// ---------------------------------------------------------------------------

const IST_OFFSET_SECONDS = 5.5 * 3600; // +05:30, applied as a fixed wall-clock shift

/**
 * Collapse a multi-day history response into the most recent trading session,
 * mapped to the widget's `{ time: "HH:MM", ... }` bar shape.
 *
 * VWAP resets each session, so we keep only the latest date present in the
 * data — this also makes the widget usable outside market hours (it shows the
 * last completed session rather than an empty chart).
 *
 * Epoch timestamps are shifted by a fixed +05:30 and formatted from the UTC
 * fields so the displayed wall-clock is IST regardless of the viewer's local
 * timezone (and deterministic under test).
 */
function toSessionBars(raw: ApiBar[] | undefined | null): SessionBar[] {
  if (!raw || raw.length === 0) return [];

  const dated = raw.map((bar) => {
    const shifted = new Date((bar.timestamp + IST_OFFSET_SECONDS) * 1000);
    const iso = shifted.toISOString();
    return {
      date: iso.slice(0, 10),        // YYYY-MM-DD (IST)
      time: iso.slice(11, 16),       // HH:MM (IST)
      timestamp: iso.slice(0, 19),   // YYYY-MM-DDTHH:MM:SS (IST) — server bar shape
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
      volume: bar.volume,
    };
  });

  const latestDate = dated.reduce((acc, bar) => (bar.date > acc ? bar.date : acc), dated[0].date);
  return dated
    .filter((bar) => bar.date === latestDate)
    .map(({ date: _date, ...bar }) => bar);
}

/**
 * Zip a server VWAP-bands response with the live bars it was computed from.
 *
 * Returns `null` when the payload is unusable (missing, or any series does
 * not match the bar count — a contract break), so the caller can fall back to
 * the local computation from the same real bars. Individual bars whose values
 * are not finite numbers (e.g. a zero-cumulative-volume prefix, where VWAP is
 * undefined) are skipped rather than plotted as garbage; fewer than two
 * usable points also yields `null`.
 */
function toServerPoints(
  data: VwapBandsResponse | undefined,
  bars: SessionBar[],
): VWAPPoint[] | null {
  if (!data) return null;
  const series = [
    data.vwap,
    data.upper_1, data.upper_2, data.upper_3,
    data.lower_1, data.lower_2, data.lower_3,
  ];
  if (series.some((arr) => !Array.isArray(arr) || arr.length !== bars.length)) return null;

  const points: VWAPPoint[] = [];
  bars.forEach((bar, index) => {
    const values = series.map((arr) => arr[index]);
    if (values.some((value) => typeof value !== "number" || !Number.isFinite(value))) return;
    points.push({
      time: bar.time,
      price: bar.close,
      vwap: data.vwap[index],
      upper1: data.upper_1[index],
      lower1: data.lower_1[index],
      upper2: data.upper_2[index],
      lower2: data.lower_2[index],
      upper3: data.upper_3[index],
      lower3: data.lower_3[index],
    });
  });
  return points.length >= 2 ? points : null;
}

/** Inclusive YYYY-MM-DD range covering ~the last week, so at least one full
 *  trading session is present even across weekends and holidays. */
function historyRange(): { start: string; end: string } {
  const end = new Date();
  const start = new Date(end.getTime() - 6 * 24 * 3600 * 1000);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
  };
}

// ---------------------------------------------------------------------------
// Sample bars
// ---------------------------------------------------------------------------

function buildSampleBars(basePrice: number): OHLCVBar[] {
  const bars: OHLCVBar[] = [];
  const times = [
    "09:15","09:30","09:45","10:00","10:15","10:30","10:45","11:00",
    "11:15","11:30","11:45","12:00","12:15","12:30","12:45","13:00",
    "13:15","13:30","13:45","14:00","14:15","14:30","14:45","15:00","15:15","15:30",
  ];
  let price = basePrice;
  let rng = 42; // deterministic pseudo-random seed
  times.forEach((t) => {
    rng = (rng * 1664525 + 1013904223) & 0x7fffffff;
    const delta = ((rng % 200) - 100) * 0.01 * (basePrice / 100);
    const open = price;
    price = price + delta;
    const high = Math.max(open, price) + Math.abs(delta) * 0.3;
    const low = Math.min(open, price) - Math.abs(delta) * 0.3;
    bars.push({
      time: t,
      open,
      high,
      low,
      close: price,
      volume: 50_000 + (rng % 200_000),
    });
  });
  return bars;
}

const SYMBOLS = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY"];
const BASE_PRICES: Record<string, number> = {
  NIFTY: 22_500,
  BANKNIFTY: 48_200,
  RELIANCE: 2_950,
  HDFCBANK: 1_680,
  INFY: 1_410,
};
const INDEX_SYMBOLS = new Set(["NIFTY", "BANKNIFTY"]);

/** OpenAlgo history needs the index exchange for index underlyings. */
function exchangeFor(symbol: string): string {
  return INDEX_SYMBOLS.has(symbol) ? "NSE_INDEX" : "NSE";
}

function buildVWAPChart(points: VWAPPoint[]) {
  if (points.length === 0) {
    return {
      bands: [],
      series: [],
      xDomain: [0, 1] as const,
      yDomain: [0, 1] as const,
      xTicks: [],
      yTicks: [],
    };
  }

  const allPrices = points.flatMap((p) => [p.lower3, p.upper3, p.price]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const range = maxP - minP || 1;
  const pointFor = (point: VWAPPoint, value: number, index: number) => ({
    x: index,
    y: value,
    label: `${point.time} ${value.toFixed(2)}`,
  });
  const lineFor = (getter: (point: VWAPPoint) => number) => (
    points.map((point, index) => pointFor(point, getter(point), index))
  );
  const xTicks = points
    .map((_, index) => index)
    .filter((index) => index % 4 === 0 || index === points.length - 1);

  return {
    bands: [
      {
        id: "sigma-3",
        label: "Three standard deviation VWAP band",
        color: "rgba(99,102,241,0.06)",
        upper: lineFor((point) => point.upper3),
        lower: lineFor((point) => point.lower3),
      },
      {
        id: "sigma-2",
        label: "Two standard deviation VWAP band",
        color: "rgba(99,102,241,0.09)",
        upper: lineFor((point) => point.upper2),
        lower: lineFor((point) => point.lower2),
      },
      {
        id: "sigma-1",
        label: "One standard deviation VWAP band",
        color: "rgba(99,102,241,0.14)",
        upper: lineFor((point) => point.upper1),
        lower: lineFor((point) => point.lower1),
      },
    ],
    series: [
      { id: "upper3", label: "Upper 3 sigma", color: "#6366f1", dash: "3 3", strokeWidth: 0.8, points: lineFor((point) => point.upper3) },
      { id: "lower3", label: "Lower 3 sigma", color: "#6366f1", dash: "3 3", strokeWidth: 0.8, points: lineFor((point) => point.lower3) },
      { id: "upper2", label: "Upper 2 sigma", color: "#8b5cf6", dash: "4 2", strokeWidth: 0.8, points: lineFor((point) => point.upper2) },
      { id: "lower2", label: "Lower 2 sigma", color: "#8b5cf6", dash: "4 2", strokeWidth: 0.8, points: lineFor((point) => point.lower2) },
      { id: "upper1", label: "Upper 1 sigma", color: "#a78bfa", strokeWidth: 1, points: lineFor((point) => point.upper1) },
      { id: "lower1", label: "Lower 1 sigma", color: "#a78bfa", strokeWidth: 1, points: lineFor((point) => point.lower1) },
      { id: "vwap", label: "VWAP", color: "#f59e0b", strokeWidth: 1.8, points: lineFor((point) => point.vwap) },
      { id: "price", label: "Price", color: "#22c55e", strokeWidth: 1.4, points: lineFor((point) => point.price) },
    ],
    xDomain: [0, Math.max(points.length - 1, 1)] as const,
    yDomain: [minP, maxP] as const,
    xTicks,
    yTicks: [0, 0.33, 0.67, 1].map((fraction) => minP + fraction * range),
  };
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function VWAPBandsWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbol, setSymbol] = useState("NIFTY");
  const [showSymbolMenu, setShowSymbolMenu] = useState(false);

  // Live intraday bars — only fetched once a broker is connected. TanStack
  // Query owns caching/refetching; we never fabricate a "live" refresh clock.
  const { data: liveRaw } = useQuery({
    queryKey: ["vwap-history", symbol],
    queryFn: () => {
      const { start, end } = historyRange();
      return getHistory(symbol, exchangeFor(symbol), "5m", start, end);
    },
    enabled: isConnected,
    staleTime: 60_000,
    refetchInterval: isConnected ? 60_000 : false,
    retry: false,
  });

  const liveBars = useMemo(() => toSessionBars(liveRaw), [liveRaw]);
  const isLive = isConnected && liveBars.length >= 2;

  // Server-computed bands (canonical) — POST the live session bars to the
  // backend VWAP route. Only enabled once a broker is connected AND a usable
  // session exists: posting an empty bar list would make the backend fall
  // back to SYNTHETIC sample bars, which must never surface under a "Live"
  // badge. The queryKey fingerprints EVERY bar's OHLCV — the server compute
  // is cumulative over the whole session, so a revised historical candle must
  // invalidate the cache, not just a new final bar.
  const sessionFingerprint = useMemo(() => {
    let hash = 0;
    for (const bar of liveBars) {
      const chunk = `${bar.timestamp}|${bar.open}|${bar.high}|${bar.low}|${bar.close}|${bar.volume}`;
      for (let i = 0; i < chunk.length; i += 1) {
        hash = (Math.imul(hash, 31) + chunk.charCodeAt(i)) | 0;
      }
    }
    return hash;
  }, [liveBars]);
  const { data: serverBands } = useQuery({
    queryKey: ["vwap-bands", symbol, liveBars.length, sessionFingerprint],
    queryFn: () =>
      postVwapBands(
        liveBars.map(({ timestamp, open, high, low, close, volume }) => ({
          timestamp, open, high, low, close, volume,
        })),
      ),
    enabled: isLive,
    staleTime: 60_000,
    retry: false,
  });

  const bars = useMemo(
    () => (isLive ? liveBars : buildSampleBars(BASE_PRICES[symbol] ?? 22500)),
    [isLive, liveBars, symbol],
  );
  // Server bands win whenever they are present and usable; otherwise compute
  // locally — from the live bars while the server call is pending/failed, or
  // from the labelled sample bars when disconnected (behaviour unchanged).
  const serverPoints = useMemo(
    () => (isLive ? toServerPoints(serverBands, liveBars) : null),
    [isLive, serverBands, liveBars],
  );
  const points = useMemo(() => serverPoints ?? computeVWAP(bars), [serverPoints, bars]);
  const vwapChart = useMemo(() => buildVWAPChart(points), [points]);

  const latestPoint = points[points.length - 1];
  const priceVsVWAP = latestPoint
    ? latestPoint.price - latestPoint.vwap
    : 0;
  const priceColour = priceVsVWAP >= 0 ? "text-profit" : "text-loss";
  const priceSign = priceVsVWAP >= 0 ? "+" : "";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Waves size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">VWAP Bands</span>
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the broker returned a usable session of intraday bars. Otherwise
            it stays on the honest amber "Sample data" affordance so a viewer is
            never misled into trusting fabricated prices. */}
        {isLive ? (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing live intraday data from the connected broker"
            title="Live intraday 5-minute bars from the connected broker; bands are computed by the FlintTrade backend when available."
          >
            Live
          </span>
        ) : (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample data; no live backend endpoint yet"
            title="No live data wired yet — showing sample VWAP bands so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />

        {/* Symbol selector */}
        <div className="relative">
          <button
            onClick={() => setShowSymbolMenu((v) => !v)}
            aria-label={`Selected symbol: ${symbol}`}
            aria-expanded={showSymbolMenu}
            className="flex items-center gap-1 px-2 py-0.5 text-xs text-text-primary bg-surface-hover rounded border border-border-default hover:border-accent transition-colors"
          >
            {symbol}
            <ChevronDown size={10} aria-hidden="true" />
          </button>
          {showSymbolMenu && (
            <div
              className="absolute right-0 top-full mt-1 z-30 bg-surface-card border border-border-default rounded shadow-lg min-w-25"
              role="listbox"
              aria-label="Symbol selection"
            >
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  role="option"
                  aria-selected={s === symbol}
                  onClick={() => { setSymbol(s); setShowSymbolMenu(false); track("trade", "vwapbands_symbol_change"); }}
                  className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${s === symbol ? "text-accent" : "text-text-primary"}`}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">

        {/* VWAP stats row */}
        {latestPoint && (
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Price</div>
              <div className="text-sm font-mono font-semibold text-text-primary tabular-nums">
                {latestPoint.price.toFixed(2)}
              </div>
            </div>
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">VWAP</div>
              <div className="text-sm font-mono font-semibold text-[#f59e0b] tabular-nums">
                {latestPoint.vwap.toFixed(2)}
              </div>
            </div>
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Δ VWAP</div>
              <div className={`text-sm font-mono font-semibold tabular-nums ${priceColour}`}>
                {priceSign}{priceVsVWAP.toFixed(2)}
              </div>
            </div>
          </div>
        )}

        {/* Chart */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          {points.length < 2 ? (
            <div className="flex items-center justify-center h-full text-xxs text-text-muted">
              No data
            </div>
          ) : (
            <FlintBandedLineChart
              ariaLabel="VWAP bands chart"
              bands={vwapChart.bands}
              series={vwapChart.series}
              xDomain={vwapChart.xDomain}
              yDomain={vwapChart.yDomain}
              xTicks={vwapChart.xTicks}
              yTicks={vwapChart.yTicks}
              xFormatter={(value) => points[value]?.time ?? String(value)}
              yFormatter={(value) => value >= 1000 ? `${(value / 1000).toFixed(1)}k` : value.toFixed(0)}
              width={360}
              height={160}
            />
          )}
        </div>

        {/* Band legend */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">Bands</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {[
              { label: "Price", colour: "#22c55e", dash: false },
              { label: "VWAP", colour: "#f59e0b", dash: false },
              { label: "± 1σ", colour: "#a78bfa", dash: false },
              { label: "± 2σ", colour: "#8b5cf6", dash: true },
              { label: "± 3σ", colour: "#6366f1", dash: true },
            ].map(({ label, colour, dash }) => (
              <div key={label} className="flex items-center gap-1.5 text-xxs text-text-secondary">
                <span
                  className="inline-block w-4 border-t"
                  style={{
                    borderColor: colour,
                    borderTopStyle: dash ? "dashed" : "solid",
                    borderTopWidth: dash ? 1 : 1.5,
                  }}
                  aria-hidden="true"
                />
                {label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(VWAPBandsWidget);
