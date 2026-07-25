/**
 * SectorsTab — sector performance for the Market Overview widget.
 *
 * Union of two retired surfaces plus one Market Intelligence tab:
 *   - SectorMap: squarified treemap / grid / table over the operator's own
 *     positions, with drill-down, the cross-widget sector atom, and the
 *     day-change labelling fix — against live data the colours encode
 *     unrealised P&L % vs entry (a portfolio map), NOT the day's market
 *     move, and the legend says which is on screen.
 *   - SectorPerformance: the timeframe-ranked sector bar view. It was
 *     sample-only; here it gains a live path through the backend
 *     `sectors/rotation` endpoint, with the widget's single sample sector
 *     dataset as the disclosed fail-closed fallback.
 *   - Market Intelligence's sector rotation tab is dominated by the bar view
 *     over the same rotation rows (its INDIA_SECTORS table collapses into
 *     ../sampleSectors.ts). Its sector HEATMAP is not: the market-cap-weighted
 *     projection is the "heatmap" view below, because ranking by return alone
 *     throws away which sectors actually move the index. `market_cap_cr` is
 *     already on every rotation row (services/ftApi.analysis.ts) on both the
 *     live and sample paths, so the weighting needs no new fetch and invents
 *     no figure.
 *
 * The bars and heatmap views read ONE query (`marketOverview/sectorRotation`)
 * through {@link useSectorRotationRows}; TanStack dedupes the key, so the
 * second projection costs no extra request.
 */

import { useMemo, useState, useRef, useCallback, useEffect, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart, LayoutGrid, Grid3X3, BarChart3, Map as MapIcon, TrendingUp, TrendingDown } from "lucide-react";
import { atom, useAtom } from "jotai";
import { FlintWeightedHeatmap } from "@flinttrade/design-system";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { usePositions } from "@/hooks/usePositions";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { useModeStore } from "@/stores/modeStore";
import { getSectorRotation } from "@/services/ftApi";
import type { SectorRotationRow } from "@/services/ftApi.analysis";
import type { Position } from "@/types/api";
import { divergingColourScale } from "@/lib/colourScale";
import { cn } from "@/lib/utils";

import { calculateTreemapLayout } from "../treemapLayout";
import { TreemapView, GridView, SectorTableView, EmptyView } from "../SectorRenderModes";
import { SampleBadge } from "../shared";
import { SAMPLE_SECTOR_ROTATION } from "../sampleSectors";
import type {
  SectorView,
  SizingMode,
  StockData,
  SectorItem,
  TreemapSectorLayout,
  ContainerSize,
  TreemapLayoutItem,
} from "../types";

// ---------------------------------------------------------------------------
// Color helper
// ---------------------------------------------------------------------------

const getChangeColor = divergingColourScale;

// ---------------------------------------------------------------------------
// Sector mapping (NSE sectors — simplified static map)
// ---------------------------------------------------------------------------

const SECTOR_MAP: Record<string, string> = {
  RELIANCE: "Energy", ONGC: "Energy", IOC: "Energy", BPCL: "Energy",
  TCS: "IT", INFY: "IT", WIPRO: "IT", HCLTECH: "IT", TECHM: "IT",
  HDFCBANK: "Banking", ICICIBANK: "Banking", SBIN: "Banking", KOTAKBANK: "Banking", AXISBANK: "Banking",
  HINDUNILVR: "FMCG", ITC: "FMCG", NESTLEIND: "FMCG", BRITANNIA: "FMCG",
  MARUTI: "Auto", TATAMOTORS: "Auto", M_M: "Auto", BAJAJ_AUTO: "Auto",
  SUNPHARMA: "Pharma", DRREDDY: "Pharma", CIPLA: "Pharma", DIVISLAB: "Pharma",
  LT: "Infra", POWERGRID: "Infra", NTPC: "Infra",
  BAJFINANCE: "NBFC", BAJAJFINSV: "NBFC", HDFCLIFE: "NBFC",
  TITAN: "Consumer", ASIANPAINT: "Consumer", ADANIPORTS: "Logistics",
};

function getSector(symbol: string): string {
  const clean = symbol.replace(/[-&.]/g, "_").toUpperCase();
  return SECTOR_MAP[clean] ?? "Others";
}

// ---------------------------------------------------------------------------
// Jotai atom for sector data (allows cross-widget sharing later)
// ---------------------------------------------------------------------------

export const sectorDataAtom = atom<StockData[]>([]);

// ---------------------------------------------------------------------------
// Bars view — timeframe-ranked sector performance
// ---------------------------------------------------------------------------

type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";

const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M", "6M", "1Y"];

const TF_FIELD: Record<Timeframe, keyof Pick<
  SectorRotationRow,
  "change_1d" | "change_1w" | "change_1m" | "change_3m" | "change_6m" | "change_1y"
>> = {
  "1D": "change_1d",
  "1W": "change_1w",
  "1M": "change_1m",
  "3M": "change_3m",
  "6M": "change_6m",
  "1Y": "change_1y",
};

/**
 * The one sector-rotation read, shared by the bars and heatmap projections.
 *
 * Provenance fails closed: only an explicit `is_sample_data === false` on a
 * connected response renders as live; anything else falls back to THE one
 * sample sector dataset, disclosed by the caller's badge.
 */
function useSectorRotationRows(): {
  rows: SectorRotationRow[];
  isLive: boolean;
  updatedAt: string | null;
} {
  const isConnected = useBrokerConnected();

  const rotationQuery = useQuery({
    queryKey: ["marketOverview", "sectorRotation"],
    queryFn: getSectorRotation,
    enabled: isConnected,
    // Poll only while the backend explicitly claims live rows.
    refetchInterval: (query) =>
      isConnected && query.state.data?.is_sample_data === false ? 300_000 : false,
    staleTime: 120_000,
  });

  const isLive = isConnected && rotationQuery.data?.is_sample_data === false;
  return {
    rows: isLive && rotationQuery.data ? rotationQuery.data.sectors : SAMPLE_SECTOR_ROTATION.sectors,
    isLive,
    // A timestamp is a freshness claim — sample rows never carry one.
    updatedAt: isLive ? rotationQuery.data?.updated_at ?? null : null,
  };
}

/** Timeframe pills shared by the two rotation projections. */
function TimeframePills({
  timeframe,
  onSelect,
}: {
  timeframe: Timeframe;
  onSelect: (tf: Timeframe) => void;
}) {
  return (
    <>
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          role="tab"
          aria-selected={tf === timeframe}
          onClick={() => onSelect(tf)}
          className={cn(
            "px-2.5 py-0.5 text-xxs font-medium rounded transition-colors",
            tf === timeframe
              ? "bg-accent/15 text-accent border border-accent/30"
              : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
          )}
        >
          {tf}
        </button>
      ))}
    </>
  );
}

interface BarRowProps {
  name: string;
  changePct: number;
  maxAbs: number;
}

function BarRow({ name, changePct, maxAbs }: BarRowProps) {
  const isUp = changePct >= 0;
  const barPct = maxAbs > 0 ? (Math.abs(changePct) / maxAbs) * 100 : 0;

  return (
    <div
      className="flex items-center gap-2"
      aria-label={`${name} ${changePct >= 0 ? "+" : ""}${changePct.toFixed(2)}%`}
    >
      <span className="text-xxs text-text-secondary w-20 shrink-0 truncate">{name}</span>
      <div className="flex-1 h-4 bg-surface-hover rounded-sm overflow-hidden relative">
        <div
          className={cn("h-full rounded-sm transition-all duration-300", isUp ? "bg-profit/70" : "bg-loss/70")}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <span
        className={cn(
          "text-xxs font-mono tabular-nums w-14 text-right shrink-0",
          isUp ? "text-profit" : "text-loss",
        )}
      >
        {isUp ? "+" : ""}{changePct.toFixed(2)}%
      </span>
    </div>
  );
}

function SectorBarsView() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  const { rows, isLive, updatedAt } = useSectorRotationRows();

  const field = TF_FIELD[timeframe];
  const ranked = useMemo(
    () => [...rows].sort((a, b) => b[field] - a[field]),
    [rows, field],
  );
  const maxAbs = Math.max(...ranked.map((r) => Math.abs(r[field])), 0.1);
  const positiveCount = ranked.filter((r) => r[field] >= 0).length;
  const negativeCount = ranked.length - positiveCount;

  return (
    <div className="h-full flex flex-col overflow-hidden" aria-label="Sector performance bars view">
      {/* Timeframe tabs */}
      <div
        className="flex-none flex items-center gap-px px-2.5 py-1.5 bg-surface-elevated border-b border-border-subtle"
        role="tablist"
        aria-label="Timeframe"
      >
        <TimeframePills timeframe={timeframe} onSelect={setTimeframe} />
        <div className="flex-1" />
        {!isLive && (
          <SampleBadge title="No live sector rotation data yet — showing the widget's sample sector table. Do not base trading decisions on these figures." />
        )}
        <span className="ml-2 text-xxs text-profit font-mono">{positiveCount}↑</span>
        <span className="mx-1 text-border-default">·</span>
        <span className="text-xxs text-loss font-mono">{negativeCount}↓</span>
      </div>

      {/* Bars */}
      <div
        className="flex-1 min-h-0 overflow-y-auto px-2.5 py-2 space-y-1.5"
        aria-label="Sector performance bars"
      >
        {ranked.map((row) => (
          <BarRow key={row.symbol} name={row.name} changePct={row[field]} maxAbs={maxAbs} />
        ))}
      </div>

      {/* A timestamp is a freshness claim — sample rows never render one. */}
      {updatedAt ? (
        <div className="flex-none px-2.5 py-1 text-xxs text-text-muted border-t border-border-subtle">
          Updated: {updatedAt}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heatmap view — market-cap-weighted sector projection (from the retired
// Market Intelligence sector heatmap)
// ---------------------------------------------------------------------------

/** ₹ crore → the "L Cr" (lakh crore) scale Indian desks read index caps in. */
function formatMarketCap(cr: number): string {
  if (cr >= 100000) return `${(cr / 100000).toFixed(1)}L Cr`;
  if (cr >= 1000) return `${(cr / 1000).toFixed(0)}k Cr`;
  return `${cr.toFixed(0)} Cr`;
}

function formatReturn(v: number): string {
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/**
 * The rotation rows sized by market capitalisation and coloured by return.
 *
 * This is the projection the ranked bars cannot make: the bars answer "which
 * sector moved most", this answers "which sector moved the index". Both read
 * the same rows, so they can never disagree about a figure.
 */
function SectorWeightedHeatmapView() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");
  const { rows, isLive, updatedAt } = useSectorRotationRows();

  const field = TF_FIELD[timeframe];
  const entries = useMemo(
    () =>
      [...rows]
        .sort((a, b) => b.market_cap_cr - a.market_cap_cr)
        .map((row) => ({
          id: row.symbol,
          label: row.name,
          valueLabel: formatReturn(row[field]),
          detailLabel: formatMarketCap(row.market_cap_cr),
          weight: row.market_cap_cr,
          color: divergingColourScale(row[field]),
        })),
    [rows, field],
  );

  return (
    <div className="h-full flex flex-col overflow-hidden" aria-label="Sector weighted heatmap view">
      <div
        className="flex-none flex items-center gap-px px-2.5 py-1.5 bg-surface-elevated border-b border-border-subtle"
        role="tablist"
        aria-label="Timeframe"
      >
        <TimeframePills timeframe={timeframe} onSelect={setTimeframe} />
        <div className="flex-1" />
        {!isLive && (
          <SampleBadge title="No live sector rotation data yet — showing the widget's sample sector table. Do not base trading decisions on these figures." />
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-2.5 py-2">
        <FlintWeightedHeatmap
          ariaLabel={`Sector heatmap by ${timeframe} return and market capitalisation`}
          entries={entries}
        />
      </div>

      <div className="flex-none flex items-center gap-2 px-2.5 py-1 border-t border-border-subtle text-xxs text-text-muted">
        <MapIcon size={9} aria-hidden="true" />
        <span>Tile size = market cap · Colour = {timeframe} change</span>
        <div className="flex-1" />
        <span className="flex items-center gap-1">
          <span className="h-1.5 w-6 rounded" style={{ background: "linear-gradient(to right,#8B3030,#3D8B80,#00C853)" }} />
          -4% → +4%
        </span>
        {updatedAt ? <span className="ml-2">Updated: {updatedAt}</span> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab — map views (from SectorMap) + bars view (from SectorPerformance)
// ---------------------------------------------------------------------------

const SECTOR_VIEWS: { id: SectorView; label: string; icon: typeof LayoutGrid }[] = [
  { id: "bars", label: "Bars", icon: BarChart },
  { id: "heatmap", label: "Heatmap", icon: MapIcon },
  { id: "treemap", label: "Treemap", icon: LayoutGrid },
  { id: "grid", label: "Grid", icon: Grid3X3 },
  { id: "table", label: "Sectors", icon: BarChart3 },
];

/**
 * Views that render the sector-rotation plane rather than the operator's
 * positions. They carry their own timeframe pills, counts and provenance, so
 * the tab's position-derived stats badges and legend footer stay off.
 */
const ROTATION_VIEWS: readonly SectorView[] = ["bars", "heatmap"];

interface SectorsTabProps {
  /** Opening view — how retired ids reproduce their presentation. */
  initialView?: SectorView;
}

function SectorsTab({ initialView }: SectorsTabProps) {
  const [activeView, setActiveView] = useState<SectorView>(initialView ?? "treemap");
  const [sizingMode, setSizingMode] = useState<SizingMode>("equal");
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [hoveredStock, setHoveredStock] = useState<StockData | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [containerSize, setContainerSize] = useState<ContainerSize>({ width: 0, height: 0 });
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [, setSectorData] = useAtom(sectorDataAtom);
  const mode = useModeStore((state) => state.mode);
  const isBrokerConnected = useBrokerConnected();
  const accountReadsEnabled = resolveAccountReadsEnabled(mode, isBrokerConnected);

  const { data: positionsData } = usePositions({ enabled: accountReadsEnabled });
  const isSampleSectorData = mode === "explore";
  /**
   * What the colours actually encode. The explore sample carries day-change
   * figures; the live path is built from the operator's own positions, so it
   * is unrealised P&L against entry. Naming it stops the live view being read
   * as market performance.
   */
  const metricLabel = isSampleSectorData ? "day change %" : "unrealised P&L % vs entry";

  // Memoized callback ref for treemap container (adapted from source)
  const setTreemapRef = useCallback((node: HTMLDivElement | null): void => {
    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect();
      resizeObserverRef.current = null;
    }
    if (node) {
      const rect = node.getBoundingClientRect();
      setContainerSize({ width: rect.width, height: rect.height });
      resizeObserverRef.current = new ResizeObserver((entries) => {
        for (const entry of entries) {
          setContainerSize({
            width: entry.contentRect.width,
            height: entry.contentRect.height,
          });
        }
      });
      resizeObserverRef.current.observe(node);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (resizeObserverRef.current) resizeObserverRef.current.disconnect();
    };
  }, []);

  // Build stock data from positions
  const stockData = useMemo<StockData[]>(() => {
    if (isSampleSectorData) {
      return [
        { symbol: "RELIANCE", ltp: 2890, change: 1.2, sector: "Energy" },
        { symbol: "TCS", ltp: 3950, change: -0.4, sector: "IT" },
        { symbol: "INFY", ltp: 1730, change: 0.8, sector: "IT" },
        { symbol: "HDFCBANK", ltp: 1680, change: -1.1, sector: "Banking" },
        { symbol: "ICICIBANK", ltp: 1290, change: 2.3, sector: "Banking" },
        { symbol: "SBIN", ltp: 820, change: -0.6, sector: "Banking" },
        { symbol: "HINDUNILVR", ltp: 2430, change: 0.3, sector: "FMCG" },
        { symbol: "ITC", ltp: 470, change: 1.8, sector: "FMCG" },
        { symbol: "MARUTI", ltp: 12500, change: -2.1, sector: "Auto" },
        { symbol: "TATAMOTORS", ltp: 890, change: 3.4, sector: "Auto" },
        { symbol: "SUNPHARMA", ltp: 1650, change: -0.9, sector: "Pharma" },
        { symbol: "LT", ltp: 3700, change: 0.5, sector: "Infra" },
        { symbol: "BAJFINANCE", ltp: 6800, change: -1.7, sector: "NBFC" },
        { symbol: "TITAN", ltp: 3500, change: 1.1, sector: "Consumer" },
        { symbol: "WIPRO", ltp: 470, change: -0.2, sector: "IT" },
        { symbol: "KOTAKBANK", ltp: 1820, change: 0.7, sector: "Banking" },
      ];
    }

    // NOTE ON WHAT THIS METRIC IS. Against live data this view maps the
    // operator's OWN POSITIONS, so `change` here is unrealised P&L percent
    // against the average entry price — NOT the instrument's move on the day.
    // The two are unrelated: a stock up 2% today can sit at -15% against an
    // entry from last month. The legend and the header say which one is on
    // screen so the colours cannot be read as market performance.
    return ((positionsData ?? []) as Position[]).map((p) => {
      const ltp = p.ltp ?? 0;
      const avgPrice = p.averagePrice ?? 0;
      const change = avgPrice > 0 ? ((ltp - avgPrice) / avgPrice) * 100 : 0;
      return {
        symbol: p.symbol,
        ltp,
        change,
        sector: getSector(p.symbol),
      };
    });
  }, [isSampleSectorData, positionsData]);

  // Sync atom
  useEffect(() => {
    setSectorData(stockData);
  }, [stockData, setSectorData]);

  const filteredStockData = useMemo<StockData[]>(() => {
    if (!selectedSector) return stockData;
    return stockData.filter((s) => s.sector === selectedSector);
  }, [stockData, selectedSector]);

  // Sector aggregation
  const sectorData = useMemo<SectorItem[]>(() => {
    const groups: Record<string, { stocks: StockData[]; totalChange: number }> = {};
    filteredStockData.forEach((item) => {
      if (!groups[item.sector]) groups[item.sector] = { stocks: [], totalChange: 0 };
      groups[item.sector].stocks.push(item);
      groups[item.sector].totalChange += item.change;
    });
    return Object.entries(groups)
      .map(([sector, g]) => ({
        sector,
        stockCount: g.stocks.length,
        avgChange: g.stocks.length > 0 ? g.totalChange / g.stocks.length : 0,
        stocks: g.stocks,
      }))
      .filter((s) => s.stockCount > 0)
      .sort((a, b) => b.stockCount - a.stockCount);
  }, [filteredStockData]);

  // Market stats
  const stats = useMemo(() => {
    const gainers = filteredStockData.filter((s) => s.change > 0.1).length;
    const losers = filteredStockData.filter((s) => s.change < -0.1).length;
    const avgChange =
      filteredStockData.length > 0
        ? filteredStockData.reduce((sum, s) => sum + s.change, 0) / filteredStockData.length
        : 0;
    return { gainers, losers, avgChange };
  }, [filteredStockData]);

  // Treemap layout
  const treemapLayout = useMemo<TreemapSectorLayout[]>(() => {
    if (containerSize.width === 0 || containerSize.height === 0) return [];
    const sectorItems = sectorData
      .map((s) => ({ ...s, value: sizingMode === "equal" ? s.stocks.length : s.stockCount * 100 }))
      .sort((a, b) => b.value - a.value);

    const sectorLayout = calculateTreemapLayout(
      sectorItems,
      0, 0,
      containerSize.width,
      containerSize.height,
    ) as Array<SectorItem & TreemapLayoutItem>;

    return sectorLayout.map((sector) => {
      const stockItems = sector.stocks.map((stock) => ({ ...stock, value: 1 }));
      const padding = selectedSector ? 0 : 1;
      const headerHeight = selectedSector ? 0 : 18;
      const stockLayout = calculateTreemapLayout(
        stockItems,
        padding,
        headerHeight,
        Math.max(sector.width - padding * 2, 0),
        Math.max(sector.height - headerHeight - padding, 0),
      ) as Array<StockData & TreemapLayoutItem>;
      return { ...sector, stockLayout };
    });
  }, [sectorData, containerSize, selectedSector, sizingMode]);

  const handleSectorClick = (sector: string) => {
    setSelectedSector(sector);
    setActiveView("treemap");
  };

  const isMapView = !ROTATION_VIEWS.includes(activeView);

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header toolbar */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0 gap-2">
        <div className="flex items-center gap-2">
          {selectedSector && isMapView && (
            <button
              className="text-text-muted hover:text-text-primary transition-colors"
              onClick={() => setSelectedSector(null)}
              title="Back to all sectors"
            >
              <LayoutGrid size={13} />
            </button>
          )}
          <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
            {selectedSector && isMapView ? selectedSector : "Sectors"}
          </span>
          {isMapView && isSampleSectorData && (
            <Badge
              variant="outline"
              className="text-xxs px-1.5 py-0 border-warning/30 text-warning bg-warning/10"
            >
              Sample data
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Stats badges (map views only — the bars view carries its own counts) */}
          {isMapView && (
            <>
              <Badge variant="outline" className="text-xs px-1 py-0 border-profit/30 text-profit gap-0.5">
                <TrendingUp size={9} />
                {stats.gainers}
              </Badge>
              <Badge variant="outline" className="text-xs px-1 py-0 border-loss/30 text-loss gap-0.5">
                <TrendingDown size={9} />
                {stats.losers}
              </Badge>
              <span
                className="font-mono text-xs font-semibold"
                style={{ color: getChangeColor(stats.avgChange) }}
              >
                {stats.avgChange >= 0 ? "+" : ""}{stats.avgChange.toFixed(2)}%
              </span>
            </>
          )}

          {/* Sizing mode (treemap only) */}
          {activeView === "treemap" && (
            <Select
              value={sizingMode}
              onValueChange={(v) => setSizingMode(v as SizingMode)}
            >
              <SelectTrigger className="h-7 text-xs px-1.5 border-border-default bg-surface-card text-text-secondary w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default text-xs">
                <SelectItem value="equal">Equal</SelectItem>
                <SelectItem value="value">Value</SelectItem>
              </SelectContent>
            </Select>
          )}

          {/* View tabs */}
          <div className="flex items-center border border-border-default rounded overflow-hidden">
            {SECTOR_VIEWS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                title={label}
                className={`flex items-center justify-center w-6 h-7 transition-colors ${
                  activeView === id
                    ? "bg-surface-elevated text-text-primary"
                    : "text-text-muted hover:text-text-secondary"
                }`}
                onClick={() => setActiveView(id)}
              >
                <Icon size={11} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {activeView === "bars"
          ? <SectorBarsView />
          : activeView === "heatmap"
          ? <SectorWeightedHeatmapView />
          : filteredStockData.length === 0
          ? <EmptyView />
          : activeView === "treemap"
          ? (
            <TreemapView
              treemapLayout={treemapLayout}
              selectedSector={selectedSector}
              hoveredStock={hoveredStock}
              tooltipPos={tooltipPos}
              setHoveredStock={setHoveredStock}
              setTooltipPos={setTooltipPos}
              onSectorClick={handleSectorClick}
              containerRef={setTreemapRef}
            />
          )
          : activeView === "grid"
          ? <GridView stocks={filteredStockData} />
          : <SectorTableView sectors={sectorData} onSectorClick={handleSectorClick} />}
      </div>

      {/* Legend footer (map views only) */}
      {isMapView && (
        <div className="flex items-center justify-between px-2 py-0.5 border-t border-border-default shrink-0">
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1">
              <div className="h-1.5 w-6 rounded" style={{ background: "linear-gradient(to right,#8B3030,#3D8B80,#00C853)" }} />
              <span className="text-xxs text-text-disabled">-4% → +4%</span>
            </div>
          </div>
          <span className="text-xxs text-text-disabled">
            {activeView === "treemap"
              ? `Tile = equal weight · Colour = ${metricLabel}`
              : `Colour = ${metricLabel}`}
          </span>
        </div>
      )}
    </div>
  );
}

export default memo(SectorsTab);
