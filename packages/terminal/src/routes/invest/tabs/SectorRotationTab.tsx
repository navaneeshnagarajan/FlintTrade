/**
 * SectorRotationTab.tsx
 *
 * Sector rotation heatmap for the Invest route.
 *
 * Layout:
 *   1. Treemap-style heatmap — divs sized by market cap, coloured by 1D%
 *   2. Returns table — sortable 1D/1W/1M/3M/6M/1Y columns
 *   3. Momentum sub-tab — horizontal bar chart of momentum scores
 *
 * Data flow:
 *   GET /ft-api/api/v1/sectors/rotation → TanStack Query (5 min stale)
 *
 * Design absorbed from:
 *   - etftracker Dashboard4_IndiaSectors: heatmap tile approach
 *   - SectorTab.tsx: sort-header pattern, GlassCard usage
 *
 * Accessibility:
 *   - Heatmap tiles include aria-label with name + return value
 *   - Table has aria-label, aria-sort on sortable columns
 *   - Active sub-tab uses aria-selected
 *   - Colour is supplemented by ± prefix on return values
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, ArrowUpDown, ArrowUp, ArrowDown, AlertCircle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import {
  getSectorRotation,
  type SectorRotationRow,
} from "@/services/ftApi";
import { formatPercent } from "../formatters";

// ─── Demo data ─────────────────────────────────────────────────────────────

const DEMO_SECTORS: SectorRotationRow[] = [
  { symbol: "NIFTYIT", name: "Nifty IT", change_1d: 1.24, change_1w: 3.10, change_1m: 6.80, change_3m: 12.40, change_6m: 18.20, change_1y: 32.10, market_cap_cr: 980000, momentum_score: 82, quadrant: "leading" },
  { symbol: "NIFTYBANK", name: "Nifty Bank", change_1d: -0.38, change_1w: 0.80, change_1m: 2.10, change_3m: 3.80, change_6m: 6.20, change_1y: 14.40, market_cap_cr: 1240000, momentum_score: 48, quadrant: "improving" },
  { symbol: "NIFTYPHARMA", name: "Nifty Pharma", change_1d: -0.72, change_1w: -1.20, change_1m: 0.60, change_3m: 2.40, change_6m: 4.80, change_1y: 12.20, market_cap_cr: 420000, momentum_score: 38, quadrant: "weakening" },
  { symbol: "NIFTYAUTO", name: "Nifty Auto", change_1d: 0.84, change_1w: 2.10, change_1m: 4.20, change_3m: 8.60, change_6m: 14.20, change_1y: 26.80, market_cap_cr: 560000, momentum_score: 74, quadrant: "leading" },
  { symbol: "NIFTYENERGY", name: "Nifty Energy", change_1d: 0.45, change_1w: 1.30, change_1m: 3.40, change_3m: 5.20, change_6m: 8.80, change_1y: 18.60, market_cap_cr: 720000, momentum_score: 62, quadrant: "leading" },
  { symbol: "NIFTYFMCG", name: "Nifty FMCG", change_1d: -0.18, change_1w: -0.40, change_1m: -1.20, change_3m: -2.40, change_6m: -0.80, change_1y: 6.20, market_cap_cr: 480000, momentum_score: 28, quadrant: "lagging" },
  { symbol: "NIFTYREALTY", name: "Nifty Realty", change_1d: 1.62, change_1w: 4.20, change_1m: 8.40, change_3m: 14.80, change_6m: 22.60, change_1y: 44.20, market_cap_cr: 280000, momentum_score: 91, quadrant: "leading" },
  { symbol: "NIFTYMETAL", name: "Nifty Metal", change_1d: -0.94, change_1w: -2.10, change_1m: -4.80, change_3m: -8.20, change_6m: -6.40, change_1y: 4.80, market_cap_cr: 320000, momentum_score: 18, quadrant: "lagging" },
  { symbol: "NIFTYINFRA", name: "Nifty Infra", change_1d: 0.62, change_1w: 1.80, change_1m: 3.60, change_3m: 6.80, change_6m: 11.20, change_1y: 22.80, market_cap_cr: 410000, momentum_score: 68, quadrant: "leading" },
  { symbol: "NIFTYFINSERV", name: "Nifty Fin Services", change_1d: -0.28, change_1w: 0.60, change_1m: 1.80, change_3m: 3.20, change_6m: 5.80, change_1y: 12.60, market_cap_cr: 920000, momentum_score: 44, quadrant: "improving" },
];

// ─── Colour helpers ────────────────────────────────────────────────────────────

/** Return a Tailwind bg class based on 1D% change — 5-step gradient. */
function heatColour(change: number): string {
  if (change >= 2) return "bg-emerald-600 text-white";
  if (change >= 0.5) return "bg-emerald-500/80 text-white";
  if (change >= -0.5) return "bg-surface-card text-text-primary border border-border-default";
  if (change >= -2) return "bg-rose-500/80 text-white";
  return "bg-rose-700 text-white";
}

/** Quadrant badge colour. */
function quadrantColour(q: SectorRotationRow["quadrant"]): string {
  switch (q) {
    case "leading": return "text-emerald-400";
    case "improving": return "text-sky-400";
    case "weakening": return "text-amber-400";
    case "lagging": return "text-rose-400";
  }
}

// ─── Treemap tile ─────────────────────────────────────────────────────────────

function HeatTile({ sector, maxCap }: { sector: SectorRotationRow; maxCap: number }) {
  const sizePct = Math.max(0.08, sector.market_cap_cr / maxCap);
  const colour = heatColour(sector.change_1d);
  const positive = sector.change_1d >= 0;

  return (
    <div
      className={cn("rounded-lg p-3 flex flex-col justify-between transition-transform hover:scale-[1.02] cursor-default", colour)}
      style={{ flexBasis: `${Math.max(12, sizePct * 100)}%`, flexGrow: sizePct }}
      aria-label={`${sector.name}: ${formatPercent(sector.change_1d)} today`}
      role="img"
    >
      <div className="font-mono text-xs font-bold truncate">{sector.symbol.replace("NIFTY", "")}</div>
      <div>
        <div className={cn("font-mono text-sm font-bold tabular-nums", positive ? "" : "")}>
          {formatPercent(sector.change_1d)}
        </div>
        <div className="text-xs opacity-80 truncate leading-tight">{sector.name}</div>
      </div>
    </div>
  );
}

// ─── Sort header ──────────────────────────────────────────────────────────────

type SortField = "name" | "change_1d" | "change_1w" | "change_1m" | "change_3m" | "change_6m" | "change_1y" | "momentum_score";
type SortDir = "asc" | "desc";

function SortHeader({
  label,
  field,
  active,
  dir,
  onSort,
}: {
  label: string;
  field: SortField;
  active: boolean;
  dir: SortDir;
  onSort: (f: SortField) => void;
}) {
  return (
    <button
      className="flex items-center gap-1 text-xxs font-medium text-text-muted uppercase tracking-wider hover:text-text-secondary transition-colors"
      onClick={() => onSort(field)}
      aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"}
    >
      {label}
      {active ? (
        dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />
      ) : (
        <ArrowUpDown className="size-3 opacity-40" />
      )}
    </button>
  );
}

// ─── Sub-tab bar ──────────────────────────────────────────────────────────────

type SubTab = "heatmap" | "momentum";

// ─── Main component ───────────────────────────────────────────────────────────

export function SectorRotationTab() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["sector-rotation"],
    queryFn: getSectorRotation,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  const [subTab, setSubTab] = useState<SubTab>("heatmap");
  const [sortField, setSortField] = useState<SortField>("change_1d");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const isDemo = isError || (!isLoading && (!data || data.is_sample_data));
  const sectors = data?.sectors ?? DEMO_SECTORS;

  const maxCap = useMemo(() => Math.max(...sectors.map((s) => s.market_cap_cr)), [sectors]);

  const sorted = useMemo(() => {
    return [...sectors].sort((a, b) => {
      const av = a[sortField as keyof SectorRotationRow] as number;
      const bv = b[sortField as keyof SectorRotationRow] as number;
      const cmp = typeof av === "string"
        ? String(av).localeCompare(String(bv))
        : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [sectors, sortField, sortDir]);

  function handleSort(field: SortField) {
    if (field === sortField) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  }

  if (isLoading) {
    return (
      <div
        className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted"
        role="status"
        aria-live="polite"
      >
        <RefreshCw className="size-5 animate-spin" aria-hidden="true" />
        <span className="text-sm">Loading sector rotation data...</span>
      </div>
    );
  }

  if (isError && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 text-text-muted">
        <AlertCircle className="size-6" aria-hidden="true" />
        <p className="text-sm">Could not load sector rotation data.</p>
        <Button variant="ghost" size="sm" onClick={() => void refetch()} aria-label="Retry loading sector rotation">
          <RefreshCw className="size-3 mr-1.5" aria-hidden="true" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {isDemo && <DemoBanner />}

      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h3 className="font-heading font-semibold text-sm text-text-primary">Sector Rotation</h3>
          <p className="text-xs text-text-muted mt-0.5">
            Nifty sectoral indices — heatmap sized by market cap, coloured by 1D% change
          </p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void refetch()}
          className="text-xs text-text-muted h-6 px-2 gap-1 shrink-0"
          aria-label="Refresh sector rotation"
        >
          <RefreshCw className="size-3" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Sub-tab bar */}
      <div
        role="tablist"
        aria-label="Sector rotation views"
        className="flex gap-1 border-b border-border-default"
      >
        {(["heatmap", "momentum"] as SubTab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={subTab === t}
            onClick={() => setSubTab(t)}
            className={cn(
              "px-4 py-2 text-xs font-medium border-b-2 transition-colors capitalize",
              subTab === t
                ? "text-accent border-accent"
                : "text-text-secondary border-transparent hover:text-text-primary",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {subTab === "heatmap" ? (
        <>
          {/* Heatmap */}
          <GlassCard
            className="p-4"
            role="tabpanel"
            aria-label="Sector heatmap"
          >
            <div className="flex flex-wrap gap-2">
              {sectors.map((s) => (
                <HeatTile key={s.symbol} sector={s} maxCap={maxCap} />
              ))}
            </div>
            {/* Legend */}
            <div className="flex items-center gap-3 mt-4 pt-3 border-t border-border-default">
              <span className="text-xxs text-text-muted">Return today:</span>
              {[
                { label: ">+2%", colour: "bg-emerald-600" },
                { label: "+0.5–2%", colour: "bg-emerald-500/80" },
                { label: "±0.5%", colour: "bg-surface-card border border-border-default" },
                { label: "−0.5–2%", colour: "bg-rose-500/80" },
                { label: "<−2%", colour: "bg-rose-700" },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-1">
                  <span className={cn("size-2.5 rounded-sm", item.colour)} aria-hidden="true" />
                  <span className="text-xxs text-text-muted">{item.label}</span>
                </div>
              ))}
            </div>
          </GlassCard>

          {/* Returns table */}
          <GlassCard className="p-0 overflow-hidden" role="tabpanel" aria-label="Sector returns table">
            <div className="overflow-x-auto">
              <Table aria-label="Sector returns — click column headers to sort">
                <TableHeader>
                  <TableRow className="border-border-default hover:bg-transparent">
                    <TableHead className="h-9 pl-4">
                      <SortHeader label="Sector" field="name" active={sortField === "name"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right">
                      <SortHeader label="1D%" field="change_1d" active={sortField === "change_1d"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right">
                      <SortHeader label="1W%" field="change_1w" active={sortField === "change_1w"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right">
                      <SortHeader label="1M%" field="change_1m" active={sortField === "change_1m"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right">
                      <SortHeader label="3M%" field="change_3m" active={sortField === "change_3m"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right">
                      <SortHeader label="6M%" field="change_6m" active={sortField === "change_6m"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                    <TableHead className="h-9 text-right pr-4">
                      <SortHeader label="1Y%" field="change_1y" active={sortField === "change_1y"} dir={sortDir} onSort={handleSort} />
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sorted.map((s) => (
                    <TableRow key={s.symbol} className="border-border-default hover:bg-surface-card transition-colors">
                      <TableCell className="pl-4 py-2">
                        <div className="font-semibold text-xs text-text-primary">{s.name}</div>
                        <div className={cn("text-xxs font-medium capitalize", quadrantColour(s.quadrant))}>{s.quadrant}</div>
                      </TableCell>
                      {(["change_1d", "change_1w", "change_1m", "change_3m", "change_6m", "change_1y"] as const).map((key, i) => {
                        const v = s[key];
                        const pos = v >= 0;
                        return (
                          <TableCell key={key} className={cn("py-2 text-right font-mono tabular-nums text-xs font-semibold", i === 5 ? "pr-4" : "", pos ? "text-profit" : "text-loss")}>
                            {formatPercent(v)}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </GlassCard>
        </>
      ) : (
        /* Momentum tab */
        <GlassCard className="p-5 space-y-4" role="tabpanel" aria-label="Sector momentum scores">
          <div>
            <p className="text-xxs text-text-muted uppercase tracking-wider">Momentum score (0–100)</p>
            <p className="text-xs text-text-muted mt-0.5">
              Based on multi-period return, RSI, and relative strength vs Nifty 50
            </p>
          </div>
          {[...sectors]
            .sort((a, b) => b.momentum_score - a.momentum_score)
            .map((s) => {
              const score = s.momentum_score;
              const barColour =
                score >= 70 ? "bg-emerald-500" :
                score >= 40 ? "bg-amber-500" :
                "bg-rose-500";

              return (
                <div key={s.symbol} className="flex items-center gap-3">
                  <div className="w-36 shrink-0">
                    <div className="font-semibold text-xs text-text-primary truncate">{s.name}</div>
                    <div className={cn("text-xxs font-medium capitalize", quadrantColour(s.quadrant))}>{s.quadrant}</div>
                  </div>
                  <div className="flex-1 relative h-5 bg-border-default/50 rounded-sm overflow-hidden" role="presentation" aria-label={`Momentum score: ${score}`}>
                    <div
                      className={cn("absolute inset-y-0 left-0 rounded-sm transition-[width] duration-700", barColour)}
                      style={{ width: `${score}%` }}
                    />
                  </div>
                  <div className="font-mono tabular-nums text-xs font-bold text-text-primary w-8 text-right shrink-0">
                    {score}
                  </div>
                </div>
              );
            })}
          <p className="text-xs text-text-muted pt-2 border-t border-border-default">
            Green ≥70 (strong momentum) · Amber 40–69 · Red &lt;40 (weak momentum)
          </p>
        </GlassCard>
      )}

      <p className="text-xs text-text-muted">
        Sector data sourced from NSE sectoral indices. Market cap is approximate.
        {isDemo ? " Sample data shown — connect broker for live data." : ""}
      </p>
    </div>
  );
}

export default SectorRotationTab;
