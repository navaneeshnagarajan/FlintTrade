/**
 * PortfolioRRGTab -- custom symbol portfolio plotted on the RRG canvas.
 *
 * Users can add/remove symbols to track.
 * Symbols are persisted in localStorage.
 * Portfolio RRG data is fetched from /ft-api/v1/rrg/portfolio.
 *
 * Drill-down: clicking a sector symbol on the canvas opens a mini-RRG
 * showing individual stock positions within that sector, fetched from
 * GET /ft-api/v1/screener/sector-constituents?sector=<symbol>.
 *
 * Absorbed pattern: RRGCanvas draw loop from RRGCanvas.tsx.
 */

import { useState, useEffect, useRef, useCallback, memo } from "react";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { useQuery } from "@tanstack/react-query";
import { Plus, X, RefreshCw, AlertCircle, Target, ArrowLeft } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { RRG_QUADRANT_COLOURS } from "./RRGCanvas";
import type { RRGResponse, SectorConstituentsResponse } from "@/services/ftApi";
import { getSectorConstituents } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Storage key
// ---------------------------------------------------------------------------

const LS_KEY = "flinttrade_portfolio_rrg_symbols";

/** Up to 20 distinct colours for portfolio symbols. */
const PORTFOLIO_COLOURS: string[] = [
  "#29B6F6", "#66BB6A", "#AB47BC", "#FFA726", "#EF5350",
  "#26C6DA", "#D4E157", "#FF7043", "#78909C", "#EC407A",
  "#42A5F5", "#26A69A", "#F06292", "#AED581", "#FFD54F",
  "#80CBC4", "#CE93D8", "#FFAB91", "#90CAF9", "#A5D6A7",
];

// ---------------------------------------------------------------------------
// API call
// ---------------------------------------------------------------------------

async function fetchPortfolioRRG(symbols: string[]): Promise<RRGResponse> {
  if (symbols.length === 0) {
    return { benchmark: "", tail_length: 8, is_sample_data: false, sectors: [] };
  }
  const res = await fetch(
    `/ft-api/v1/rrg/portfolio?symbols=${encodeURIComponent(symbols.join(","))}`,
  );
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<RRGResponse>;
}

// ---------------------------------------------------------------------------
// Shared canvas drawing helpers
// ---------------------------------------------------------------------------

const AXIS_MIN = 96.5;
const AXIS_MAX = 103.5;

function toCanvasX(rsRatio: number, canvasW: number, pad: number): number {
  return pad + ((rsRatio - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasW - 2 * pad);
}

function toCanvasY(rsMomentum: number, canvasH: number, pad: number): number {
  return (canvasH - pad) - ((rsMomentum - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasH - 2 * pad);
}

/** Draw quadrant background, axes, and labels on a 2D context. */
function drawQuadrantBackground(ctx: CanvasRenderingContext2D, W: number, H: number, PAD: number): void {
  const cx = toCanvasX(100, W, PAD);
  const cy = toCanvasY(100, H, PAD);

  // Quadrant fills
  ctx.fillStyle = RRG_QUADRANT_COLOURS.leading.fill;
  ctx.fillRect(cx, PAD, W - cx - PAD, cy - PAD);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.weakening.fill;
  ctx.fillRect(cx, cy, W - cx - PAD, H - cy - PAD);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.improving.fill;
  ctx.fillRect(PAD, PAD, cx - PAD, cy - PAD);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.lagging.fill;
  ctx.fillRect(PAD, cy, cx - PAD, H - cy - PAD);

  // Centre axes
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(cx, PAD); ctx.lineTo(cx, H - PAD);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(PAD, cy); ctx.lineTo(W - PAD, cy);
  ctx.stroke();
  ctx.setLineDash([]);

  // Axis labels
  ctx.font = "9px Inter, sans-serif";
  ctx.fillStyle = "rgba(255,255,255,0.35)";
  ctx.textAlign = "center";
  ctx.fillText("100", cx, H - PAD + 12);
  ctx.textAlign = "left";
  ctx.fillText("RS-Ratio \u2192", W - PAD - 36, H - PAD + 12);
  ctx.save();
  ctx.translate(12, cy);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText("RS-Momentum \u2191", 0, 0);
  ctx.restore();

  // Quadrant corner labels
  ctx.font = "bold 8px Inter, sans-serif";
  ctx.fillStyle = RRG_QUADRANT_COLOURS.leading.dot;
  ctx.textAlign = "right";
  ctx.fillText("LEADING", W - PAD - 2, PAD + 10);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.weakening.dot;
  ctx.fillText("WEAKENING", W - PAD - 2, H - PAD - 4);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.improving.dot;
  ctx.textAlign = "left";
  ctx.fillText("IMPROVING", PAD + 2, PAD + 10);
  ctx.fillStyle = RRG_QUADRANT_COLOURS.lagging.dot;
  ctx.fillText("LAGGING", PAD + 2, H - PAD - 4);
}

// ---------------------------------------------------------------------------
// Portfolio canvas (sector-level view)
// ---------------------------------------------------------------------------

interface PortfolioCanvasProps {
  data: RRGResponse;
  onSymbolClick?: (symbol: string) => void;
}

const PortfolioCanvas = memo(function PortfolioCanvas({ data, onSymbolClick }: PortfolioCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredSymbol, setHoveredSymbol] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width / (window.devicePixelRatio || 1);
    const H = canvas.height / (window.devicePixelRatio || 1);
    const PAD = 32;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawQuadrantBackground(ctx, W, H, PAD);

    // Symbols
    data.sectors.forEach((item, idx) => {
      const colour = PORTFOLIO_COLOURS[idx % PORTFOLIO_COLOURS.length];
      const tail = item.tail;
      if (tail.length === 0) return;
      const isHovered = hoveredSymbol === item.symbol;

      if (tail.length >= 2) {
        for (let i = 1; i < tail.length; i++) {
          const prev = tail[i - 1];
          const curr = tail[i];
          const alpha = (i / (tail.length - 1)) * 0.6 + 0.1;
          ctx.strokeStyle = colour + Math.round(alpha * 255).toString(16).padStart(2, "0");
          ctx.lineWidth = isHovered ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(toCanvasX(prev.rs_ratio, W, PAD), toCanvasY(prev.rs_momentum, H, PAD));
          ctx.lineTo(toCanvasX(curr.rs_ratio, W, PAD), toCanvasY(curr.rs_momentum, H, PAD));
          ctx.stroke();
        }
      }

      tail.slice(0, -1).forEach((pt, i) => {
        const alpha = ((i + 1) / tail.length) * 0.45;
        const r = isHovered ? 3 : 2;
        ctx.beginPath();
        ctx.arc(toCanvasX(pt.rs_ratio, W, PAD), toCanvasY(pt.rs_momentum, H, PAD), r, 0, Math.PI * 2);
        ctx.fillStyle = colour + Math.round(alpha * 255).toString(16).padStart(2, "0");
        ctx.fill();
      });

      const last = tail[tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dotR = isHovered ? 7 : 5;

      ctx.beginPath();
      ctx.arc(lx, ly, dotR, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.fill();
      if (isHovered) {
        ctx.strokeStyle = "rgba(255,255,255,0.8)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      ctx.font = isHovered ? "bold 9px Inter, sans-serif" : "9px Inter, sans-serif";
      ctx.fillStyle = isHovered ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.65)";
      ctx.textAlign = lx > W / 2 ? "right" : "left";
      ctx.fillText(item.symbol, lx > W / 2 ? lx - dotR - 2 : lx + dotR + 2, ly + 3);
    });
  }, [data, hoveredSymbol]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const { width, height } = entry.contentRect;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext("2d");
        if (ctx) ctx.scale(dpr, dpr);
        draw();
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [draw]);

  const findClosestSymbol = useCallback((mx: number, my: number, W: number, H: number): { symbol: string | null; dist: number } => {
    const PAD = 32;
    let closestSym: string | null = null;
    let minDist = Infinity;

    data.sectors.forEach((item) => {
      if (item.tail.length === 0) return;
      const last = item.tail[item.tail.length - 1];
      const dist = Math.hypot(mx - toCanvasX(last.rs_ratio, W, PAD), my - toCanvasY(last.rs_momentum, H, PAD));
      if (dist < minDist) { minDist = dist; closestSym = item.symbol; }
    });

    return { symbol: closestSym, dist: minDist };
  }, [data.sectors]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const { symbol, dist } = findClosestSymbol(mx, my, rect.width, rect.height);

    if (dist < 20) {
      setHoveredSymbol(symbol);
      setTooltipPos({ x: e.clientX, y: e.clientY });
    } else {
      setHoveredSymbol(null);
    }
  }, [findClosestSymbol]);

  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onSymbolClick) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const { symbol, dist } = findClosestSymbol(mx, my, rect.width, rect.height);

    if (dist < 20 && symbol) {
      onSymbolClick(symbol);
    }
  }, [findClosestSymbol, onSymbolClick]);

  const hoveredData = hoveredSymbol
    ? data.sectors.find((s) => s.symbol === hoveredSymbol)
    : undefined;

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        ref={canvasRef}
        className="block w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredSymbol(null)}
        onClick={handleClick}
      />
      {hoveredData && (
        <div
          className="fixed z-50 pointer-events-none bg-surface-floating border border-border-default rounded shadow-xl px-3 py-2 text-xs space-y-0.5"
          style={{ left: tooltipPos.x + 12, top: tooltipPos.y - 8 }}
        >
          <div className="font-semibold font-mono text-text-primary">{hoveredData.symbol}</div>
          <div className="text-text-secondary">Quadrant: <span className="font-medium capitalize">{hoveredData.current_quadrant}</span></div>
          {hoveredData.tail.length > 0 && (() => {
            const last = hoveredData.tail[hoveredData.tail.length - 1];
            return (
              <>
                <div className="text-text-muted font-mono">RS-Ratio: {last.rs_ratio.toFixed(2)}</div>
                <div className="text-text-muted font-mono">RS-Mom: {last.rs_momentum.toFixed(2)}</div>
              </>
            );
          })()}
          <div className="text-accent text-xxs mt-1">Click to drill down</div>
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Constituent drill-down canvas (stock-level mini RRG)
// ---------------------------------------------------------------------------

interface ConstituentCanvasProps {
  data: SectorConstituentsResponse;
}

const ConstituentCanvas = memo(function ConstituentCanvas({ data }: ConstituentCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredSymbol, setHoveredSymbol] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width / (window.devicePixelRatio || 1);
    const H = canvas.height / (window.devicePixelRatio || 1);
    const PAD = 32;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    drawQuadrantBackground(ctx, W, H, PAD);

    // Constituents
    data.constituents.forEach((item, idx) => {
      const colour = PORTFOLIO_COLOURS[idx % PORTFOLIO_COLOURS.length];
      const tail = item.tail;
      if (tail.length === 0) return;
      const isHovered = hoveredSymbol === item.symbol;

      // Draw trail
      if (tail.length >= 2) {
        for (let i = 1; i < tail.length; i++) {
          const prev = tail[i - 1];
          const curr = tail[i];
          const alpha = (i / (tail.length - 1)) * 0.6 + 0.1;
          ctx.strokeStyle = colour + Math.round(alpha * 255).toString(16).padStart(2, "0");
          ctx.lineWidth = isHovered ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(toCanvasX(prev.rs_ratio, W, PAD), toCanvasY(prev.rs_momentum, H, PAD));
          ctx.lineTo(toCanvasX(curr.rs_ratio, W, PAD), toCanvasY(curr.rs_momentum, H, PAD));
          ctx.stroke();
        }
      }

      // Trail dots
      tail.slice(0, -1).forEach((pt, i) => {
        const alpha = ((i + 1) / tail.length) * 0.45;
        const r = isHovered ? 3 : 2;
        ctx.beginPath();
        ctx.arc(toCanvasX(pt.rs_ratio, W, PAD), toCanvasY(pt.rs_momentum, H, PAD), r, 0, Math.PI * 2);
        ctx.fillStyle = colour + Math.round(alpha * 255).toString(16).padStart(2, "0");
        ctx.fill();
      });

      // Current position dot
      const last = tail[tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dotR = isHovered ? 6 : 4;

      ctx.beginPath();
      ctx.arc(lx, ly, dotR, 0, Math.PI * 2);
      ctx.fillStyle = colour;
      ctx.fill();
      if (isHovered) {
        ctx.strokeStyle = "rgba(255,255,255,0.8)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Label
      ctx.font = isHovered ? "bold 8px Inter, sans-serif" : "8px Inter, sans-serif";
      ctx.fillStyle = isHovered ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.55)";
      ctx.textAlign = lx > W / 2 ? "right" : "left";
      ctx.fillText(item.symbol, lx > W / 2 ? lx - dotR - 2 : lx + dotR + 2, ly + 3);
    });
  }, [data, hoveredSymbol]);

  useEffect(() => { draw(); }, [draw]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const { width, height } = entry.contentRect;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext("2d");
        if (ctx) ctx.scale(dpr, dpr);
        draw();
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [draw]);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = rect.width;
    const H = rect.height;
    const PAD = 32;

    let closestSym: string | null = null;
    let minDist = Infinity;

    data.constituents.forEach((item) => {
      if (item.tail.length === 0) return;
      const last = item.tail[item.tail.length - 1];
      const dist = Math.hypot(mx - toCanvasX(last.rs_ratio, W, PAD), my - toCanvasY(last.rs_momentum, H, PAD));
      if (dist < minDist) { minDist = dist; closestSym = item.symbol; }
    });

    if (minDist < 20) {
      setHoveredSymbol(closestSym);
      setTooltipPos({ x: e.clientX, y: e.clientY });
    } else {
      setHoveredSymbol(null);
    }
  }, [data.constituents]);

  const hoveredData = hoveredSymbol
    ? data.constituents.find((s) => s.symbol === hoveredSymbol)
    : undefined;

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        ref={canvasRef}
        className="block w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredSymbol(null)}
      />
      {hoveredData && (
        <div
          className="fixed z-50 pointer-events-none bg-surface-floating border border-border-default rounded shadow-xl px-3 py-2 text-xs space-y-0.5"
          style={{ left: tooltipPos.x + 12, top: tooltipPos.y - 8 }}
        >
          <div className="font-semibold font-mono text-text-primary">{hoveredData.symbol}</div>
          <div className="text-text-secondary">{hoveredData.name}</div>
          <div className="text-text-secondary">Quadrant: <span className="font-medium capitalize">{hoveredData.current_quadrant}</span></div>
          {hoveredData.tail.length > 0 && (() => {
            const last = hoveredData.tail[hoveredData.tail.length - 1];
            return (
              <>
                <div className="text-text-muted font-mono">RS-Ratio: {last.rs_ratio.toFixed(2)}</div>
                <div className="text-text-muted font-mono">RS-Mom: {last.rs_momentum.toFixed(2)}</div>
              </>
            );
          })()}
          <div className="text-text-muted font-mono">Weight: {(hoveredData.weight * 100).toFixed(1)}%</div>
        </div>
      )}
    </div>
  );
});

// ---------------------------------------------------------------------------
// Drill-down panel
// ---------------------------------------------------------------------------

interface DrillDownPanelProps {
  sector: string;
  onBack: () => void;
}

const DrillDownPanel = memo(function DrillDownPanel({ sector, onBack }: DrillDownPanelProps) {
  const { data, isLoading, isError, refetch } = useQuery<SectorConstituentsResponse>({
    queryKey: ["sectorConstituents", sector],
    queryFn: () => getSectorConstituents(sector),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    retry: false,
  });

  return (
    <div className="flex flex-col h-full">
      {/* Header with back button */}
      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-border-default shrink-0">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onBack}
          aria-label="Back to sector view"
          className="h-6 w-6 shrink-0 text-text-muted hover:text-text-primary"
        >
          <ArrowLeft size={13} />
        </Button>
        <span className="text-xs font-semibold text-text-primary font-mono">{sector}</span>
        <span className="text-xxs text-text-muted">Constituents</span>
        <div className="flex-1" />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void refetch()}
          aria-label="Refresh constituents"
          className="h-6 w-6 shrink-0 text-text-muted hover:text-text-primary"
        >
          <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} />
        </Button>
      </div>

      {/* Content */}
      <div className="flex-1 relative overflow-hidden">
        {isLoading && (
          <div className="flex items-center justify-center h-full">
            <RefreshCw size={20} className="animate-spin text-text-muted" />
          </div>
        )}

        {isError && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-text-muted">
            <AlertCircle size={20} className="text-loss" />
            <span className="text-xs">Failed to load constituents for {sector}</span>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs h-6 text-text-muted hover:text-text-primary"
              onClick={() => void refetch()}
            >
              <RefreshCw size={11} className="mr-1" />
              Retry
            </Button>
          </div>
        )}

        {!isLoading && !isError && data && (
          <ConstituentCanvas data={data} />
        )}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Main tab component
// ---------------------------------------------------------------------------

export const PortfolioRRGTab = memo(function PortfolioRRGTab() {
  // Persisted symbol list
  const [symbols, setSymbols] = useState<string[]>(() =>
    safeParse(localStorage.getItem(LS_KEY), z.array(z.string())) ?? [],
  );

  const [inputValue, setInputValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Drill-down state: when set, show constituent view for this sector
  const [drillDownSector, setDrillDownSector] = useState<string | null>(null);

  // Persist to localStorage on every change
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify(symbols));
    } catch { /* ignore */ }
  }, [symbols]);

  const addSymbol = useCallback(() => {
    const sym = inputValue.trim().toUpperCase();
    if (!sym || symbols.includes(sym) || symbols.length >= 20) return;
    setSymbols((prev) => [...prev, sym]);
    setInputValue("");
    inputRef.current?.focus();
  }, [inputValue, symbols]);

  const removeSymbol = useCallback((sym: string) => {
    setSymbols((prev) => prev.filter((s) => s !== sym));
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") { e.preventDefault(); addSymbol(); }
  }, [addSymbol]);

  // Fetch portfolio RRG data
  const { data, isLoading, isError, refetch } = useQuery<RRGResponse>({
    queryKey: ["portfolioRRG", symbols],
    queryFn: () => fetchPortfolioRRG(symbols),
    enabled: symbols.length > 0,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });

  const handleSymbolClick = useCallback((symbol: string) => {
    setDrillDownSector(symbol);
  }, []);

  const handleBack = useCallback(() => {
    setDrillDownSector(null);
  }, []);

  // If drilling down, show constituent view
  if (drillDownSector) {
    return <DrillDownPanel sector={drillDownSector} onBack={handleBack} />;
  }

  return (
    <div className="flex flex-col h-full">
      {/* Symbol input row */}
      <div className="flex items-center gap-1.5 px-2 py-1.5 border-b border-border-default shrink-0">
        <Target size={11} className="text-accent shrink-0" aria-hidden="true" />
        <Input
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value.toUpperCase())}
          onKeyDown={handleKeyDown}
          placeholder="Add symbol (e.g. RELIANCE)"
          className="h-6 flex-1 text-xs bg-surface-hover border-border-default text-text-primary placeholder:text-text-muted focus-visible:ring-0 focus-visible:border-accent font-mono"
          maxLength={20}
          aria-label="Add symbol to portfolio RRG"
        />
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={addSymbol}
          disabled={!inputValue.trim() || symbols.length >= 20}
          aria-label="Add symbol"
          className="h-6 w-6 shrink-0 border-border-default bg-surface-hover text-text-muted hover:text-text-primary hover:bg-surface-card"
        >
          <Plus size={11} />
        </Button>
        {symbols.length > 0 && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => void refetch()}
            aria-label="Refresh portfolio RRG"
            className="h-6 w-6 shrink-0 text-text-muted hover:text-text-primary"
          >
            <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} />
          </Button>
        )}
      </div>

      {/* Symbol chips */}
      {symbols.length > 0 && (
        <div className="flex flex-wrap gap-1 px-2 py-1.5 border-b border-border-subtle shrink-0 max-h-16 overflow-y-auto">
          {symbols.map((sym, idx) => (
            <Badge
              key={sym}
              variant="outline"
              className="flex items-center gap-1 px-1.5 py-0 text-xxs font-mono border-border-default"
              style={{ color: PORTFOLIO_COLOURS[idx % PORTFOLIO_COLOURS.length] }}
            >
              {sym}
              <button
                type="button"
                onClick={() => removeSymbol(sym)}
                aria-label={`Remove ${sym}`}
                className="ml-0.5 text-text-muted hover:text-loss transition-colors"
              >
                <X size={9} />
              </button>
            </Badge>
          ))}
        </div>
      )}

      {/* Canvas / empty state */}
      <div className="flex-1 relative overflow-hidden">
        {symbols.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-text-muted">
            <Target size={24} />
            <span className="text-xs">Add symbols above to plot them on the RRG</span>
          </div>
        )}

        {symbols.length > 0 && isLoading && (
          <div className="flex items-center justify-center h-full">
            <RefreshCw size={20} className="animate-spin text-text-muted" />
          </div>
        )}

        {symbols.length > 0 && isError && (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-text-muted">
            <AlertCircle size={20} className="text-loss" />
            <span className="text-xs">Failed to load RRG data</span>
            <Button
              variant="ghost"
              size="sm"
              className="text-xs h-6 text-text-muted hover:text-text-primary"
              onClick={() => void refetch()}
            >
              <RefreshCw size={11} className="mr-1" />
              Retry
            </Button>
          </div>
        )}

        {symbols.length > 0 && !isLoading && !isError && data && (
          <PortfolioCanvas data={data} onSymbolClick={handleSymbolClick} />
        )}
      </div>
    </div>
  );
});
