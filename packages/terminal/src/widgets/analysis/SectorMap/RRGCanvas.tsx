/**
 * RRGCanvas — canvas-based Relative Rotation Graph scatter plot.
 *
 * Layout:
 *   - x-axis: RS-Ratio  (centre = 100)
 *   - y-axis: RS-Momentum (centre = 100, y-up convention)
 *   - Four coloured quadrant backgrounds
 *   - Sector trails (fading dots) with current position as filled circle
 *   - Axis labels and quadrant labels
 */

import { useRef, useState, useCallback, useEffect, memo } from "react";
import type { MouseEvent } from "react";
import type { RRGResponse, SectorRRG, RRGQuadrant } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Quadrant fill colours (semi-transparent) and dot colours (opaque). */
export const RRG_QUADRANT_COLOURS: Record<RRGQuadrant | "neutral", { fill: string; dot: string; label: string }> = {
  leading:   { fill: "rgba(0, 200, 83, 0.07)",   dot: "#00C853", label: "Leading" },
  weakening: { fill: "rgba(255, 193, 7, 0.07)",  dot: "#FFC107", label: "Weakening" },
  improving: { fill: "rgba(33, 150, 243, 0.07)", dot: "#2196F3", label: "Improving" },
  lagging:   { fill: "rgba(244, 67, 54, 0.07)",  dot: "#F44336", label: "Lagging" },
  neutral:   { fill: "rgba(120, 120, 120, 0.05)",dot: "#888888", label: "Neutral" },
};

/** Unique dot colour per sector index (12 sectors). */
const SECTOR_DOT_COLOURS: string[] = [
  "#29B6F6", // IT         — light blue
  "#66BB6A", // Banking    — green
  "#AB47BC", // Pharma     — purple
  "#FFA726", // FMCG       — orange
  "#EF5350", // Auto       — red
  "#26C6DA", // Metals     — cyan
  "#D4E157", // Realty     — lime
  "#FF7043", // Energy     — deep orange
  "#78909C", // Infra      — blue grey
  "#EC407A", // Media      — pink
  "#42A5F5", // FinServ    — blue
  "#26A69A", // Healthcare — teal
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RRGCanvasProps {
  data: RRGResponse;
  tailLength: number;
}

export const RRGCanvas = memo(function RRGCanvas({ data, tailLength }: RRGCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredSector, setHoveredSector] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  const AXIS_MIN = 96.5;
  const AXIS_MAX = 103.5;

  const toCanvasX = useCallback((rsRatio: number, canvasW: number, pad: number): number => {
    return pad + ((rsRatio - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasW - 2 * pad);
  }, []);

  const toCanvasY = useCallback((rsMomentum: number, canvasH: number, pad: number): number => {
    return (canvasH - pad) - ((rsMomentum - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasH - 2 * pad);
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const PAD = 32;
    const cx = toCanvasX(100, W, PAD);
    const cy = toCanvasY(100, H, PAD);

    ctx.clearRect(0, 0, W, H);

    // Quadrant fills
    ctx.fillStyle = RRG_QUADRANT_COLOURS.leading.fill;
    ctx.fillRect(cx, PAD, W - cx - PAD, cy - PAD);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.weakening.fill;
    ctx.fillRect(cx, cy, W - cx - PAD, H - cy - PAD);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.improving.fill;
    ctx.fillRect(PAD, PAD, cx - PAD, cy - PAD);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.lagging.fill;
    ctx.fillRect(PAD, cy, cx - PAD, H - cy - PAD);

    // Grid lines at centre
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(cx, PAD);
    ctx.lineTo(cx, H - PAD);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(PAD, cy);
    ctx.lineTo(W - PAD, cy);
    ctx.stroke();
    ctx.setLineDash([]);

    // Axis labels
    ctx.font = "9px Inter, sans-serif";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.textAlign = "center";
    ctx.fillText("100", cx, H - PAD + 12);
    ctx.textAlign = "left";
    ctx.fillText("RS-Ratio →", W - PAD - 36, H - PAD + 12);

    ctx.save();
    ctx.translate(12, cy);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("RS-Momentum ↑", 0, 0);
    ctx.restore();

    // Quadrant corner labels
    const labelSize = 8;
    ctx.font = `bold ${labelSize}px Inter, sans-serif`;
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

    // Sector trails and dots
    data.sectors.forEach((sector, idx) => {
      const dotColour = SECTOR_DOT_COLOURS[idx % SECTOR_DOT_COLOURS.length];
      const tail = sector.tail;
      if (tail.length === 0) return;

      const isHovered = hoveredSector === sector.symbol;

      if (tail.length >= 2) {
        for (let i = 1; i < tail.length; i++) {
          const prev = tail[i - 1];
          const curr = tail[i];
          const alpha = (i / (tail.length - 1)) * 0.6 + 0.1;
          ctx.strokeStyle = dotColour.replace(")", `,${alpha})`).replace("rgb", "rgba");
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
        ctx.fillStyle = dotColour.replace(")", `,${alpha})`).replace("rgb", "rgba");
        ctx.fill();
      });

      const last = tail[tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dotR = isHovered ? 7 : 5;

      ctx.beginPath();
      ctx.arc(lx, ly, dotR, 0, Math.PI * 2);
      ctx.fillStyle = dotColour;
      ctx.fill();
      if (isHovered) {
        ctx.strokeStyle = "rgba(255,255,255,0.8)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      const shortName = sector.name.replace("NIFTY ", "").replace(" INDEX", "");
      ctx.font = isHovered ? "bold 9px Inter, sans-serif" : "9px Inter, sans-serif";
      ctx.fillStyle = isHovered ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)";
      ctx.textAlign = lx > W / 2 ? "right" : "left";
      const lxLabel = lx > W / 2 ? lx - dotR - 2 : lx + dotR + 2;
      ctx.fillText(shortName, lxLabel, ly + 3);
    });
  }, [data, hoveredSector, toCanvasX, toCanvasY]);

  useEffect(() => {
    draw();
  }, [draw]);

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

  const handleMouseMove = useCallback((e: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = canvas.getBoundingClientRect().width;
    const H = canvas.getBoundingClientRect().height;
    const PAD = 32;

    let closestSym: string | null = null;
    let minDist = Infinity;

    data.sectors.forEach((sector) => {
      if (sector.tail.length === 0) return;
      const last = sector.tail[sector.tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dist = Math.hypot(mx - lx, my - ly);
      if (dist < minDist) {
        minDist = dist;
        closestSym = sector.symbol;
      }
    });

    if (minDist < 20) {
      setHoveredSector(closestSym);
      setTooltipPos({ x: e.clientX, y: e.clientY });
    } else {
      setHoveredSector(null);
    }
  }, [data.sectors, toCanvasX, toCanvasY]);

  const hoveredData: SectorRRG | undefined = hoveredSector
    ? data.sectors.find((s) => s.symbol === hoveredSector)
    : undefined;

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        ref={canvasRef}
        className="block w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredSector(null)}
      />

      {/* Sample data indicator */}
      {data.is_sample_data && (
        <div className="absolute top-1 right-1 text-xxs text-text-disabled bg-surface-card/80 px-1 py-0.5 rounded border border-border-default">
          sample data
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredData && (
        <div
          className="fixed z-50 pointer-events-none rounded border border-border-default bg-surface-card text-xs shadow-lg min-w-40"
          style={{ left: tooltipPos.x + 12, top: tooltipPos.y - 8 }}
        >
          <div className="flex items-center justify-between px-2 py-1 border-b border-border-default gap-3">
            <span className="font-mono font-bold text-text-primary">{hoveredData.name}</span>
            <span
              className="font-bold text-xs uppercase"
              style={{ color: RRG_QUADRANT_COLOURS[hoveredData.current_quadrant].dot }}
            >
              {RRG_QUADRANT_COLOURS[hoveredData.current_quadrant].label}
            </span>
          </div>
          {hoveredData.tail.length > 0 && (() => {
            const last = hoveredData.tail[hoveredData.tail.length - 1];
            return (
              <div className="px-2 py-1 space-y-0.5">
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">RS-Ratio</span>
                  <span className="font-mono tabular-nums text-text-primary">{last.rs_ratio.toFixed(2)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">RS-Momentum</span>
                  <span className="font-mono tabular-nums text-text-primary">{last.rs_momentum.toFixed(2)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">Date</span>
                  <span className="font-mono text-text-secondary">{last.date}</span>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Tail length label */}
      <div className="absolute bottom-1 left-1 text-xxs text-text-disabled">
        tail: {tailLength}w · benchmark: {data.benchmark}
      </div>
    </div>
  );
});
