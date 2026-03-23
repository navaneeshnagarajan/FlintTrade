// Crosshair OHLCV legend component.
// Renders the O/H/L/C/V strip that appears in the header row when the
// user hovers over the chart.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LegendState {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  bull: boolean;
}

// ---------------------------------------------------------------------------
// Helpers (local — not exported because they duplicate the ones in the
// main ChartWidget; those helpers remain the single source of truth for
// the full component)
// ---------------------------------------------------------------------------

function fmt(v: number | null | undefined): string {
  if (v == null) return "--";
  return Number(v).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function fmtVol(v: number | null): string {
  if (v == null) return "--";
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(2)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(2)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return String(v);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ChartLegendProps {
  legend: LegendState;
}

export function ChartLegend({ legend }: ChartLegendProps) {
  return (
    <div className="flex items-center gap-2 bg-surface-card rounded px-2 py-0.5">
      <span className="text-xxs text-text-muted uppercase">O</span>
      <span className="text-xs font-mono text-text-primary">{fmt(legend.open)}</span>
      <span className="text-xxs text-text-muted uppercase">H</span>
      <span className="text-xs font-mono text-text-primary">{fmt(legend.high)}</span>
      <span className="text-xxs text-text-muted uppercase">L</span>
      <span className="text-xs font-mono text-text-primary">{fmt(legend.low)}</span>
      <span className="text-xxs text-text-muted uppercase">C</span>
      <span className="text-xs font-mono text-text-primary">{fmt(legend.close)}</span>
      {legend.volume != null && (
        <>
          <span className="text-xxs text-text-muted uppercase">V</span>
          <span className="text-xs font-mono text-text-primary">
            {fmtVol(legend.volume)}
          </span>
        </>
      )}
    </div>
  );
}
