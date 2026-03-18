/**
 * StraddleWidget — ATM straddle price tracker for FlintTrade terminal.
 *
 * Features:
 *   - Symbol selector (NIFTY / BANKNIFTY / FINNIFTY) + Expiry selector
 *   - ATM strike auto-detected from spot LTP
 *   - Three headline values: Straddle Price (CE LTP + PE LTP), CE Price, PE Price
 *   - TradingView Lightweight Charts v5 line chart of straddle price over time
 *     - Uses LineSeries (v5 API: chart.addSeries(LineSeries, options))
 *     - Accumulates live data points; falls back gracefully when history unavailable
 *   - Overlay toggles: Straddle / Spot / Synthetic Future
 *   - Auto-refresh: 3s market hours, 30s off-market
 *   - P&L display when a straddle position is detected in positions data
 */

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { createChart, LineSeries } from "lightweight-charts";
import {
  RefreshCw,
  ChevronDown,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  Activity,
} from "lucide-react";
import {
  getExpiry,
  getOptionChain,
  getQuotes,
  getPositionbook,
} from "../../../services/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = [
  { label: "NIFTY",     exchange: "NFO", spotSymbol: "NIFTY",     spotExchange: "NSE_INDEX" },
  { label: "BANKNIFTY", exchange: "NFO", spotSymbol: "BANKNIFTY", spotExchange: "NSE_INDEX" },
  { label: "FINNIFTY",  exchange: "NFO", spotSymbol: "FINNIFTY",  spotExchange: "NSE_INDEX" },
];

const OVERLAYS = ["Straddle", "Spot", "SynFut"];

// Chart theme colours aligned with FlintTrade dark theme
const CHART_COLORS = {
  straddle:   "#3b82f6",  // accent blue
  spot:       "#eab308",  // warning yellow
  synfut:     "#a78bfa",  // purple
  background: "#0a0a0f",
  text:       "#71717a",
  grid:       "#1e1e2e",
  border:     "#1e1e2e",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isMarketHours() {
  const now = new Date();
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= 555 && mins <= 930;
}

const NUM = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const NUM0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function fmtPrice(v) {
  if (v == null || v === 0) return "—";
  return NUM.format(v);
}

function fmtExpiry(raw) {
  if (!raw) return raw;
  try {
    const d = new Date(raw);
    if (isNaN(d.getTime())) return raw;
    return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
  } catch {
    return raw;
  }
}

/** Convert a JS Date to a lightweight-charts UTC seconds timestamp. */
function toChartTime(date) {
  return Math.floor(date.getTime() / 1000);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Selector({ value, options, onChange, className = "" }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function onOut(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener("mousedown", onOut);
    return () => document.removeEventListener("mousedown", onOut);
  }, []);

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors"
      >
        {value}
        <ChevronDown size={10} className={`transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full">
          {options.map((opt) => (
            <button
              key={opt}
              onClick={() => { onChange(opt); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                opt === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** The three headline price boxes. */
function PriceHeadline({ straddlePrice, cePrice, pePrice }) {
  return (
    <div className="flex items-stretch gap-px bg-border-default">
      {/* Straddle = CE + PE */}
      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-[10px] text-text-muted uppercase tracking-wider">Straddle</span>
        <span className="font-mono text-xl font-bold text-text-primary leading-none">
          {straddlePrice != null ? fmtPrice(straddlePrice) : "—"}
        </span>
        <span className="text-[9px] text-text-muted font-normal">CE + PE</span>
      </div>

      {/* CE price */}
      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-[10px] text-text-muted uppercase tracking-wider">CE</span>
        <span className="font-mono text-base font-semibold text-loss leading-none">
          {cePrice != null ? fmtPrice(cePrice) : "—"}
        </span>
        <span className="text-[9px] text-loss/60">Call</span>
      </div>

      {/* PE price */}
      <div className="flex-1 bg-surface-card px-3 py-2 flex flex-col items-center justify-center gap-0.5">
        <span className="text-[10px] text-text-muted uppercase tracking-wider">PE</span>
        <span className="font-mono text-base font-semibold text-profit leading-none">
          {pePrice != null ? fmtPrice(pePrice) : "—"}
        </span>
        <span className="text-[9px] text-profit/60">Put</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart component (internal — isolated lifecycle)
// ---------------------------------------------------------------------------

function StraddleChart({ dataPoints, spotPoints, synfutPoints, activeOverlays, height = 180 }) {
  const containerRef = useRef(null);
  const chartRef     = useRef(null);
  const straddleRef  = useRef(null);
  const spotRef      = useRef(null);
  const synfutRef    = useRef(null);

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: {
        background:  { color: CHART_COLORS.background },
        textColor:   CHART_COLORS.text,
        fontSize:    10,
        fontFamily:  "'JetBrains Mono', ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: CHART_COLORS.grid },
        horzLines: { color: CHART_COLORS.grid },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: CHART_COLORS.border },
      timeScale: {
        borderColor:    CHART_COLORS.border,
        timeVisible:    true,
        secondsVisible: false,
        ticksVisible:   true,
      },
      handleScale:  { mouseWheel: true },
      handleScroll: { mouseWheel: true },
    });

    straddleRef.current = chart.addSeries(LineSeries, {
      color:     CHART_COLORS.straddle,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    spotRef.current = chart.addSeries(LineSeries, {
      color:     CHART_COLORS.spot,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: true,
      visible: false,
    });

    synfutRef.current = chart.addSeries(LineSeries, {
      color:     CHART_COLORS.synfut,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      visible: false,
    });

    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    const ro = new ResizeObserver(handleResize);
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [height]);

  // Update data
  useEffect(() => {
    if (!straddleRef.current) return;
    if (dataPoints.length > 0) {
      straddleRef.current.setData(dataPoints);
    }
  }, [dataPoints]);

  useEffect(() => {
    if (!spotRef.current) return;
    if (spotPoints.length > 0) {
      spotRef.current.setData(spotPoints);
    }
  }, [spotPoints]);

  useEffect(() => {
    if (!synfutRef.current) return;
    if (synfutPoints.length > 0) {
      synfutRef.current.setData(synfutPoints);
    }
  }, [synfutPoints]);

  // Toggle overlay visibility
  useEffect(() => {
    if (!straddleRef.current || !spotRef.current || !synfutRef.current) return;
    straddleRef.current.applyOptions({ visible: activeOverlays.includes("Straddle") });
    spotRef.current.applyOptions({    visible: activeOverlays.includes("Spot") });
    synfutRef.current.applyOptions({  visible: activeOverlays.includes("SynFut") });
  }, [activeOverlays]);

  return <div ref={containerRef} className="w-full" style={{ height }} />;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

export default function StraddleWidget({ node }) {
  // ── selector state ──
  const [activeSymbolIdx, setActiveSymbolIdx] = useState(0);
  const [expiries, setExpiries]               = useState([]);
  const [selectedExpiry, setSelectedExpiry]   = useState(null);
  const [activeOverlays, setActiveOverlays]   = useState(["Straddle"]);

  // ── data state ──
  const [chain, setChain]         = useState(null);
  const [spot, setSpot]           = useState(null);
  const [positions, setPositions] = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const [lastRefresh, setLastRefresh] = useState(null);

  // ── accumulated chart data ──
  // Each point: { time: UTC seconds, value: number }
  const straddlePointsRef = useRef([]);
  const spotPointsRef     = useRef([]);
  const synfutPointsRef   = useRef([]);
  const [chartVersion, setChartVersion] = useState(0); // trigger re-render for chart data

  const symDef   = SYMBOLS[activeSymbolIdx];
  const exchange = symDef.exchange;

  // ── fetch expiries ──
  useEffect(() => {
    setExpiries([]);
    setSelectedExpiry(null);
    setChain(null);
    setError(null);
    straddlePointsRef.current = [];
    spotPointsRef.current     = [];
    synfutPointsRef.current   = [];

    let cancelled = false;
    (async () => {
      try {
        const data = await getExpiry(symDef.label, exchange);
        if (cancelled) return;
        const list = Array.isArray(data) ? data : (data?.expiry ?? []);
        setExpiries(list);
        if (list.length > 0) setSelectedExpiry(list[0]);
      } catch (e) {
        if (!cancelled) setError(`Expiry load failed: ${e.message}`);
      }
    })();

    return () => { cancelled = true; };
  }, [activeSymbolIdx, symDef.label, exchange]);

  // ── main data fetch ──
  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return;
    setLoading(true);
    setError(null);

    try {
      const [chainRes, spotRes, posRes] = await Promise.allSettled([
        getOptionChain(symDef.label, exchange, selectedExpiry),
        getQuotes(symDef.spotSymbol, symDef.spotExchange),
        getPositionbook(),
      ]);

      let newChain = null;
      let newSpot  = null;

      if (chainRes.status === "fulfilled") {
        newChain = chainRes.value;
        setChain(newChain);
      } else {
        setError(`Chain error: ${chainRes.reason?.message}`);
      }

      if (spotRes.status === "fulfilled") {
        newSpot = spotRes.value;
        setSpot(newSpot);
      }

      if (posRes.status === "fulfilled") {
        setPositions(posRes.value);
      }

      // ── Accumulate chart data points ──
      if (newChain && newSpot) {
        const spotLtp = Number(newSpot.ltp ?? 0);
        const atm = findAtm(newChain, spotLtp);
        if (atm != null) {
          const ce = findOption(newChain.calls ?? [], atm);
          const pe = findOption(newChain.puts  ?? [], atm);
          const ceLtp = Number(ce?.ltp ?? ce?.last_price ?? 0);
          const peLtp = Number(pe?.ltp ?? pe?.last_price ?? 0);
          const straddleVal = ceLtp + peLtp;

          if (straddleVal > 0) {
            const t = toChartTime(new Date());

            // Append to straddle series (deduplicate same-second)
            appendPoint(straddlePointsRef.current, { time: t, value: straddleVal });

            if (spotLtp > 0) {
              appendPoint(spotPointsRef.current, { time: t, value: spotLtp });
            }

            // Synthetic future = spot + CE - PE
            const synfutVal = spotLtp + ceLtp - peLtp;
            if (synfutVal > 0) {
              appendPoint(synfutPointsRef.current, { time: t, value: synfutVal });
            }

            setChartVersion((v) => v + 1);
          }
        }
      }
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  }, [selectedExpiry, symDef, exchange]);

  // ── auto-refresh ──
  useEffect(() => {
    fetchData();
    const interval = isMarketHours() ? 3000 : 30000;
    const id = setInterval(fetchData, interval);
    return () => clearInterval(id);
  }, [fetchData]);

  // ── derived values ──
  const { atmStrike, ceLtp, peLtp, straddlePrice, pnl } = useMemo(() => {
    if (!chain || !spot) {
      return { atmStrike: null, ceLtp: null, peLtp: null, straddlePrice: null, pnl: null };
    }

    const spotLtp = Number(spot.ltp ?? 0);
    const atm     = findAtm(chain, spotLtp);
    if (atm == null) return { atmStrike: null, ceLtp: null, peLtp: null, straddlePrice: null, pnl: null };

    const ce = findOption(chain.calls ?? [], atm);
    const pe = findOption(chain.puts  ?? [], atm);

    const ceLtpVal = Number(ce?.ltp ?? ce?.last_price ?? 0) || null;
    const peLtpVal = Number(pe?.ltp ?? pe?.last_price ?? 0) || null;
    const straddleVal = (ceLtpVal != null && peLtpVal != null) ? ceLtpVal + peLtpVal : null;

    // P&L: look for matching positions (CE + PE at ATM strike)
    let pnlVal = null;
    if (positions && Array.isArray(positions)) {
      const straddlePos = positions.filter((p) => {
        const sym = (p.symbol ?? p.tradingsymbol ?? "").toUpperCase();
        return sym.includes(String(atm)) && (sym.endsWith("CE") || sym.endsWith("PE"));
      });
      if (straddlePos.length > 0) {
        pnlVal = straddlePos.reduce((s, p) => {
          return s + Number(p.pnl ?? p.unrealised_pnl ?? p.m2m ?? 0);
        }, 0);
      }
    }

    return { atmStrike: atm, ceLtp: ceLtpVal, peLtp: peLtpVal, straddlePrice: straddleVal, pnl: pnlVal };
  }, [chain, spot, positions]);

  // ── toggle overlay ──
  function toggleOverlay(name) {
    setActiveOverlays((prev) =>
      prev.includes(name) ? prev.filter((o) => o !== name) : [...prev, name]
    );
  }

  // ── expiry buttons (first 5) ──
  const expiryButtons = expiries.slice(0, 5);
  const spotLtp = spot?.ltp ?? null;
  const spotChange = spot?.ltp && spot?.prev_close
    ? Number(spot.ltp) - Number(spot.prev_close)
    : null;
  const spotUp = spotChange == null ? null : spotChange >= 0;

  // Stable chart data arrays (only change when chartVersion bumps)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const chartStraddlePoints = useMemo(() => [...straddlePointsRef.current], [chartVersion]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const chartSpotPoints     = useMemo(() => [...spotPointsRef.current],     [chartVersion]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const chartSynfutPoints   = useMemo(() => [...synfutPointsRef.current],   [chartVersion]);

  const hasChartData = chartStraddlePoints.length > 0;

  // ────────────────────────────────────────────────────────────────────────
  // Render
  // ────────────────────────────────────────────────────────────────────────
  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden select-none">

      {/* ── Header ── */}
      <div className="flex-none bg-surface-card border-b border-border-default px-2 py-1.5 space-y-1.5">

        {/* Row 1: symbol, expiry, refresh */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <Selector
            value={symDef.label}
            options={SYMBOLS.map((s) => s.label)}
            onChange={(val) => {
              const idx = SYMBOLS.findIndex((s) => s.label === val);
              setActiveSymbolIdx(idx);
            }}
          />

          {/* Expiry buttons */}
          <div className="flex items-center gap-1">
            {expiryButtons.length === 0 && !loading && (
              <span className="text-[10px] text-text-muted px-1">No expiries</span>
            )}
            {expiryButtons.map((exp) => (
              <button
                key={exp}
                onClick={() => setSelectedExpiry(exp)}
                className={`px-2 py-0.5 text-[10px] font-medium rounded border transition-colors ${
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

          {/* ATM strike badge */}
          {atmStrike != null && (
            <span className="px-2 py-0.5 text-[10px] font-mono font-semibold text-accent bg-accent/10 border border-accent/30 rounded">
              ATM {NUM0.format(atmStrike)}
            </span>
          )}

          {/* Manual refresh */}
          <button
            onClick={fetchData}
            disabled={loading}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
            title="Refresh"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>

        {/* Row 2: spot price + change */}
        <div className="flex items-center gap-3 flex-wrap">
          {spotLtp != null ? (
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-text-muted uppercase tracking-wide">Spot</span>
              <span className="font-mono text-sm font-semibold text-text-primary">
                {NUM.format(spotLtp)}
              </span>
              {spotChange != null && (
                <span className={`flex items-center gap-0.5 text-xs font-mono ${spotUp ? "text-profit" : "text-loss"}`}>
                  {spotUp ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                  {spotChange >= 0 ? "+" : ""}{spotChange.toFixed(1)}
                </span>
              )}
            </div>
          ) : (
            <span className="text-[10px] text-text-muted">Spot: —</span>
          )}

          {/* P&L badge */}
          {pnl != null && (
            <div className={`flex items-center gap-1 ml-2 px-2 py-0.5 rounded border text-xs font-mono font-semibold ${
              pnl >= 0
                ? "text-profit bg-profit/10 border-profit/30"
                : "text-loss bg-loss/10 border-loss/30"
            }`}>
              P&L {pnl >= 0 ? "+" : ""}{NUM.format(pnl)}
            </div>
          )}

          {lastRefresh && (
            <div className="flex items-center gap-1 ml-auto text-[10px] text-text-muted">
              <Activity size={9} />
              {lastRefresh.toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false })}
              <span className="ml-1">{isMarketHours() ? "· 3s" : "· 30s"}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Error banner ── */}
      {error && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} />
          <span>{error}</span>
        </div>
      )}

      {/* ── Headline prices ── */}
      <div className="flex-none">
        <PriceHeadline
          straddlePrice={straddlePrice}
          cePrice={ceLtp}
          pePrice={peLtp}
        />
      </div>

      {/* ── Overlay toggles ── */}
      <div className="flex-none flex items-center gap-1 px-2 py-1 bg-surface-card border-b border-border-default">
        <span className="text-[10px] text-text-muted mr-1">Overlay</span>
        {OVERLAYS.map((name) => {
          const color = name === "Straddle" ? "#3b82f6" : name === "Spot" ? "#eab308" : "#a78bfa";
          const active = activeOverlays.includes(name);
          return (
            <button
              key={name}
              onClick={() => toggleOverlay(name)}
              className={`px-2 py-0.5 text-[10px] font-medium rounded border transition-colors ${
                active
                  ? "bg-surface-hover border-border-default text-text-primary"
                  : "border-transparent text-text-muted hover:text-text-secondary"
              }`}
            >
              {active && (
                <span
                  className="inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle"
                  style={{ background: color }}
                />
              )}
              {name}
            </button>
          );
        })}
      </div>

      {/* ── Chart area ── */}
      <div className="flex-1 overflow-hidden relative">
        {!selectedExpiry && !loading ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs">
            Select an expiry to load straddle data
          </div>
        ) : loading && !chain ? (
          <div className="h-full flex items-center justify-center text-text-muted text-xs gap-2">
            <RefreshCw size={13} className="animate-spin" />
            Loading straddle…
          </div>
        ) : !hasChartData ? (
          <div className="h-full flex flex-col items-center justify-center text-text-muted text-xs gap-2">
            <Activity size={20} className="text-accent/40" />
            <span>Live tracking will start on next tick</span>
            <span className="text-[10px] text-text-muted/60">
              Straddle price will accumulate here during market hours
            </span>
          </div>
        ) : (
          <StraddleChartFill
            straddlePoints={chartStraddlePoints}
            spotPoints={chartSpotPoints}
            synfutPoints={chartSynfutPoints}
            activeOverlays={activeOverlays}
          />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Full-height chart container — fills whatever flex-1 gives it
// ---------------------------------------------------------------------------

function StraddleChartFill({ straddlePoints, spotPoints, synfutPoints, activeOverlays }) {
  const wrapRef = useRef(null);
  const [height, setHeight] = useState(180);

  useEffect(() => {
    if (!wrapRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setHeight(Math.max(80, entry.contentRect.height));
      }
    });
    ro.observe(wrapRef.current);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={wrapRef} className="w-full h-full">
      <StraddleChart
        dataPoints={straddlePoints}
        spotPoints={spotPoints}
        synfutPoints={synfutPoints}
        activeOverlays={activeOverlays}
        height={height}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pure helpers (no hooks — safe to call inside useMemo)
// ---------------------------------------------------------------------------

/** Find the ATM strike from an option chain + spot price. */
function findAtm(chain, spotLtp) {
  if (!chain) return null;

  if (chain.atm_strike) return Number(chain.atm_strike);

  if (!spotLtp) return null;

  const strikes = Array.from(new Set([
    ...(chain.calls ?? []).map((c) => Number(c.strike_price ?? c.strike)),
    ...(chain.puts  ?? []).map((p) => Number(p.strike_price ?? p.strike)),
  ])).filter(Boolean).sort((a, b) => a - b);

  if (strikes.length === 0) return null;

  return strikes.reduce((prev, cur) =>
    Math.abs(cur - spotLtp) < Math.abs(prev - spotLtp) ? cur : prev,
    strikes[0]
  );
}

/** Find a specific option row by strike from a calls or puts array. */
function findOption(arr, strike) {
  return arr.find((o) => Number(o.strike_price ?? o.strike) === Number(strike)) ?? null;
}

/**
 * Append a data point to a sorted chart series array.
 * Replaces the last point if its timestamp matches (same second).
 * Keeps the array sorted by time (lightweight-charts requirement).
 */
function appendPoint(arr, point) {
  if (arr.length > 0 && arr[arr.length - 1].time === point.time) {
    arr[arr.length - 1] = point;
  } else {
    arr.push(point);
  }
}
