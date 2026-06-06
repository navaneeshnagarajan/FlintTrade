/**
 * GreeksHeatmapWidget — Option Greeks heatmap across strikes and expiries.
 *
 * Displays a 2D grid where:
 *   - Rows  : expiry dates (near → far)
 *   - Columns: strikes (OTM → ATM → ITM)
 *   - Cell colour intensity encodes the selected Greek magnitude
 *
 * Useful for identifying delta-neutral zones, high-theta strikes, or
 * gamma-concentrated expiries at a glance.
 *
 * DATA HONESTY: greeks are NOT in the OpenAlgo option-chain feed, so when a
 * broker is connected the widget fetches the live IV smile (`getFtIVSmile` —
 * the same screener source GreeksSurface uses) and derives the aligned greek
 * grid client-side via the shared Black–Scholes approximation
 * (`greeksHeatmapTransform`), showing a "Live" badge. When disconnected — or no
 * IV-bearing strike is shared across expiries — it falls back to deterministic
 * sample data with an amber "Sample data" badge so the figures are never
 * mistaken for live market data.
 */

import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { Grid3x3 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getExpiry } from "@/services/api";
import { getFtIVSmile } from "@/services/ftApi.analysis";
import type { IVSmileData } from "@/types/api";
import { SYMBOLS as OPTION_SYMBOLS } from "@/widgets/analysis/OptionChain/types";
import { buildGreeksHeatmap } from "./greeksHeatmapTransform";
import type { ExpiryRow, HeatCell } from "./greeksHeatmapTransform";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type GreekKey = "delta" | "gamma" | "theta" | "vega";

// ---------------------------------------------------------------------------
// Sample data — 3 expiries × 9 strikes
// ---------------------------------------------------------------------------

const SAMPLE_STRIKES = [21500, 21600, 21700, 21800, 21900, 22000, 22100, 22200, 22300];
const ATM_STRIKE = 22000;

function makeSampleRow(expiry: string, label: string, dte: number, baseIV: number): ExpiryRow {
  // Deterministic offsets per strike index (no Math.random) for testability
  const deltaJitter = [0.02, 0.01, 0.01, 0.00, 0.00, 0.00, -0.01, -0.01, -0.02];
  const gammaJitter = [0.9, 1.0, 1.05, 1.1, 1.1, 1.05, 1.0, 0.95, 0.9];
  const cells: HeatCell[] = SAMPLE_STRIKES.map((strike, i) => {
    const d = (strike - ATM_STRIKE) / ATM_STRIKE;
    const moneyness: "OTM" | "ATM" | "ITM" =
      Math.abs(d) < 0.001 ? "ATM" : d < 0 ? "OTM" : "ITM";
    const delta = parseFloat(Math.max(0.01, Math.min(0.99, 0.5 - d * 4 + deltaJitter[i])).toFixed(3));
    const gamma = parseFloat((0.003 * Math.exp(-Math.pow(d * 12, 2)) * gammaJitter[i] * (30 / Math.max(dte, 1))).toFixed(6));
    const theta = parseFloat((-0.4 * baseIV * Math.exp(-Math.pow(d * 8, 2)) - 0.05).toFixed(2));
    const vega  = parseFloat((0.12 * Math.exp(-Math.pow(d * 6, 2)) * Math.sqrt(dte / 30)).toFixed(3));
    return { strike, moneyness, delta, gamma, theta, vega };
  });
  return { expiry, label, dte, cells };
}

export const SAMPLE_GREEKS_HEATMAP_DATA: ExpiryRow[] = [
  makeSampleRow("2026-04-17", "17 Apr", 8,  1.0),
  makeSampleRow("2026-04-24", "24 Apr", 15, 0.85),
  makeSampleRow("2026-05-29", "29 May", 50, 0.65),
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const GREEK_LABELS: Record<GreekKey, string> = {
  delta: "Delta",
  gamma: "Gamma",
  theta: "Theta",
  vega:  "Vega",
};

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

// ---------------------------------------------------------------------------
// Colour scale: 0→1 → blue (low) → green → yellow → red (high)
// ---------------------------------------------------------------------------

function normToHsl(norm: number): string {
  const hue = Math.round(240 - norm * 240);
  return `hsl(${hue},70%,${32 + norm * 18}%)`;
}

function getCellValue(cell: HeatCell, greek: GreekKey): number {
  switch (greek) {
    case "delta": return cell.delta;
    case "gamma": return cell.gamma;
    case "theta": return Math.abs(cell.theta);
    case "vega":  return cell.vega;
  }
}

function formatCell(val: number, greek: GreekKey): string {
  switch (greek) {
    case "delta": return val.toFixed(2);
    case "gamma": return val.toFixed(4);
    case "theta": return `−${val.toFixed(2)}`;
    case "vega":  return val.toFixed(3);
  }
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

interface TooltipState {
  cell: HeatCell;
  expiry: string;
  x: number;
  y: number;
}

function CellTooltip({ tip }: { tip: TooltipState }) {
  return (
    <div
      className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded px-2.5 py-2 shadow-lg text-xs min-w-44"
      style={{ left: tip.x + 14, top: tip.y - 8 }}
      role="tooltip"
    >
      <div className="font-semibold text-text-primary mb-1">
        {tip.cell.strike} · {tip.cell.moneyness} · {tip.expiry}
      </div>
      <div className="space-y-0.5 text-text-secondary">
        {(["delta", "gamma", "theta", "vega"] as GreekKey[]).map((g) => (
          <div key={g} className="flex justify-between gap-4">
            <span className="capitalize">{g}</span>
            <span className="font-mono text-text-primary">
              {g === "theta" ? `−${Math.abs(tip.cell.theta).toFixed(2)}` : tip.cell[g].toFixed(g === "gamma" ? 4 : 3)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heatmap grid
// ---------------------------------------------------------------------------

interface HeatGridProps {
  rows: ExpiryRow[];
  greek: GreekKey;
}

function HeatGrid({ rows, greek }: HeatGridProps) {
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const { minVal, maxVal } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const row of rows) {
      for (const cell of row.cells) {
        const v = getCellValue(cell, greek);
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    return { minVal: min, maxVal: max };
  }, [rows, greek]);

  const range = maxVal - minVal || 1;

  const handleEnter = useCallback(
    (e: React.MouseEvent, cell: HeatCell, expiry: string) => {
      setTooltip({ cell, expiry, x: e.clientX, y: e.clientY });
    },
    [],
  );

  const handleMove = useCallback((e: React.MouseEvent) => {
    setTooltip((prev) => prev ? { ...prev, x: e.clientX, y: e.clientY } : prev);
  }, []);

  const handleLeave = useCallback(() => setTooltip(null), []);

  const strikes = rows[0]?.cells.map((c) => c.strike) ?? [];

  return (
    <>
      <div
        className="overflow-auto"
        role="grid"
        aria-label={`${GREEK_LABELS[greek]} heatmap`}
      >
        <table className="text-xs border-collapse">
          {/* Column headers — strikes */}
          <thead>
            <tr>
              <th className="text-left px-2 py-1 text-xxs text-text-muted font-medium uppercase tracking-wide sticky left-0 bg-surface-card z-10 min-w-16">
                Expiry
              </th>
              {strikes.map((s) => (
                <th
                  key={s}
                  className="px-1 py-1 text-xxs text-text-muted font-medium text-center min-w-14 whitespace-nowrap"
                  scope="col"
                >
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.expiry} role="row">
                {/* Row header — expiry */}
                <td
                  className="px-2 py-1.5 text-xxs text-text-secondary font-medium whitespace-nowrap sticky left-0 bg-surface-card z-10 border-r border-border-subtle"
                  role="rowheader"
                >
                  <div className="font-semibold">{row.label}</div>
                  <div className="text-text-muted">{row.dte}d</div>
                </td>
                {/* Cells */}
                {row.cells.map((cell) => {
                  const val = getCellValue(cell, greek);
                  const norm = (val - minVal) / range;
                  const bg = normToHsl(norm);
                  const isATM = cell.moneyness === "ATM";
                  return (
                    <td
                      key={cell.strike}
                      role="gridcell"
                      aria-label={`${row.label} ${cell.strike} ${GREEK_LABELS[greek]}: ${formatCell(val, greek)}`}
                      className={cn(
                        "text-center py-2 px-1 cursor-default transition-opacity hover:opacity-80 relative",
                        isATM && "ring-1 ring-inset ring-white/20",
                      )}
                      style={{ background: bg }}
                      onMouseEnter={(e) => handleEnter(e, cell, row.label)}
                      onMouseMove={handleMove}
                      onMouseLeave={handleLeave}
                    >
                      <span className="font-mono tabular-nums text-white/90 text-xxs font-medium drop-shadow-sm">
                        {formatCell(val, greek)}
                      </span>
                      {isATM && (
                        <span className="absolute top-0.5 right-0.5 text-xxs leading-none text-white/60">
                          ▲
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {tooltip && <CellTooltip tip={tooltip} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Colour legend bar
// ---------------------------------------------------------------------------

function ColourBar({ greek, minVal, maxVal }: { greek: GreekKey; minVal: number; maxVal: number }) {
  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <span className="text-xxs text-text-muted">{GREEK_LABELS[greek]}</span>
      <div
        className="h-2 w-24 rounded flex-none"
        style={{ background: "linear-gradient(to right,hsl(240,70%,32%),hsl(120,70%,40%),hsl(60,70%,44%),hsl(0,70%,40%))" }}
        aria-label="Colour scale low to high"
      />
      <span className="text-xxs font-mono text-text-muted">
        {formatCell(minVal, greek)} – {formatCell(maxVal, greek)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GreeksHeatmapWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbol, setSymbol] = useState("NIFTY");
  const [greek, setGreek] = useState<GreekKey>("delta");

  useEffect(() => {
    track("trade", "widget_view_greeks_heatmap");
  }, [track]);

  // Resolve the option-chain exchange (NFO/BFO/…) for the selected underlying.
  const symDef = useMemo(
    () => OPTION_SYMBOLS.find((s) => s.label === symbol) ?? { label: symbol, exchange: "NFO" },
    [symbol],
  );

  // Live greeks grid — fetch the IV smile for the nearest expiries (the
  // single-expiry endpoint is called once per expiry, so each carries a real
  // days-to-expiry and thus non-degenerate time-decay greeks) and derive the
  // aligned greek grid client-side. Only runs once a broker is connected.
  const { data: liveRows } = useQuery({
    queryKey: ["greeks-heatmap", symbol, symDef.exchange],
    queryFn: async () => {
      const expResp = await getExpiry(symDef.label, symDef.exchange, "options");
      const expiries = (expResp?.expiry ?? []).slice(0, 3);
      if (expiries.length === 0) return null;
      const smiles = await Promise.all(
        expiries.map((expiry) => getFtIVSmile(symDef.label, symDef.exchange, [expiry])),
      );
      const curves = smiles.flatMap((s) => s?.curves ?? []);
      const merged: IVSmileData = {
        underlying: symbol,
        spot_price: smiles.find((s) => s?.spot_price)?.spot_price ?? 0,
        curves,
      };
      return buildGreeksHeatmap(merged);
    },
    enabled: isConnected,
    staleTime: 30_000,
    refetchInterval: isConnected ? 30_000 : false,
    retry: false,
  });

  const isLive = isConnected && liveRows != null && liveRows.length > 0;
  const data: ExpiryRow[] = isLive && liveRows ? liveRows : SAMPLE_GREEKS_HEATMAP_DATA;

  const { minVal, maxVal } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const row of data) {
      for (const cell of row.cells) {
        const v = getCellValue(cell, greek);
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    return { minVal: min, maxVal: max };
  }, [data, greek]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Greeks Heatmap widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Grid3x3 size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Greeks Heatmap</span>
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the chain yielded an aligned greek grid. Otherwise it stays on
            the honest amber "Sample data" affordance so the figures are never
            mistaken for live market data. */}
        {isLive ? (
          <span
            className="px-1.5 py-0.5 text-xxs bg-profit/10 text-profit border border-profit/30 rounded"
            role="status"
            aria-label="Showing live Greeks derived from the connected broker's IV smile"
            title="Live Greeks Black–Scholes-derived from the connected broker's IV smile."
          >
            Live
          </span>
        ) : (
          <span
            className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample data; no live backend endpoint yet"
            title="No live data wired yet — showing a sample Greeks heatmap so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <div className="flex-1" />
      </div>

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-elevated border-b border-border-subtle flex-wrap">
        {/* Symbol */}
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-6 w-32 text-xs bg-surface-hover border-border-default" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Greek toggle */}
        <div
          className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden"
          role="group"
          aria-label="Select Greek"
        >
          {(["delta", "gamma", "theta", "vega"] as GreekKey[]).map((g) => (
            <button
              key={g}
              onClick={() => setGreek(g)}
              aria-pressed={g === greek}
              className={cn(
                "px-2.5 py-0.5 text-xs font-medium capitalize transition-colors",
                g === greek
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              {GREEK_LABELS[g]}
            </button>
          ))}
        </div>
      </div>

      {/* Legend */}
      <ColourBar greek={greek} minVal={minVal} maxVal={maxVal} />

      {/* ATM indicator legend */}
      <div className="flex-none flex items-center gap-2 px-2 pb-1">
        <span className="text-xxs text-text-muted">▲ = ATM strike</span>
        <span className="text-xxs text-text-muted">· Rows: near → far expiry · Cols: low → high strike · CE greeks</span>
      </div>

      {/* Grid */}
      <div className="flex-1 min-h-0 overflow-auto">
        <HeatGrid rows={data} greek={greek} />
      </div>

      {/* Footer */}
      <div className="flex-none px-2 py-1 bg-surface-card border-t border-border-subtle">
        <span className="text-xxs text-text-muted">{symbol} · {data.length} expiries · {data[0]?.cells.length ?? 0} strikes</span>
      </div>
    </div>
  );
}

export default memo(GreeksHeatmapWidget);
