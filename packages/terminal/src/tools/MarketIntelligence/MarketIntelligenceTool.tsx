/**
 * MarketIntelligenceTool — Market intelligence dashboard
 * Absorbed patterns from:
 *   - etftracker/Dashboard2_MarketPulse: advances/declines, region grouping, return badges
 *   - etftracker/Dashboard3_SectorRotation: sector-wise sortable performance table
 *   - etftracker/Dashboard4_IndiaSectors: India sectoral heat map with TF toggles
 *   - etftracker/Dashboard6_ETFScreener: search + filter screener pattern
 */

import { useState, useMemo } from "react";
import {
  X,
  BarChart3,
  TrendingUp,
  TrendingDown,
  Search,
  Info,
  ArrowUpDown,
  Globe,
  Activity,
  SlidersHorizontal,
  Map,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";

// ---------------------------------------------------------------------------
// Types — mirrors etftracker AssetReturn structure
// ---------------------------------------------------------------------------

interface SectorReturn {
  ticker: string;
  name: string;
  category: string;
  returns_1d: number | null;
  returns_1w: number | null;
  returns_1m: number | null;
  returns_3m: number | null;
  returns_6m: number | null;
  returns_1y: number | null;
  current_price: number | null;
  change_pct: number | null;
}

interface MarketBreadth {
  advances: number;
  declines: number;
  unchanged: number;
  total: number;
  newHighs: number;
  newLows: number;
  label: string;
}

interface FiiDii {
  date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
}

interface ScreenerRow {
  ticker: string;
  name: string;
  sector: string;
  price: number;
  change_pct: number;
  volume: number;
  pe: number | null;
  marketCap: string;
}

// ---------------------------------------------------------------------------
// Static placeholder data — mirrors etftracker data shapes
// ---------------------------------------------------------------------------

const TIMEFRAMES = ["1D", "1W", "1M", "3M", "6M", "1Y"] as const;
type TF = typeof TIMEFRAMES[number];

const TF_KEY: Record<TF, keyof SectorReturn> = {
  "1D": "returns_1d",
  "1W": "returns_1w",
  "1M": "returns_1m",
  "3M": "returns_3m",
  "6M": "returns_6m",
  "1Y": "returns_1y",
};

const INDIA_SECTORS: SectorReturn[] = [
  { ticker: "NIFTYBANK", name: "Nifty Bank", category: "Financial", returns_1d: 0.42, returns_1w: 1.2, returns_1m: 3.8, returns_3m: 7.2, returns_6m: 11.4, returns_1y: 18.6, current_price: 48250.5, change_pct: 0.42 },
  { ticker: "NIFTYIT", name: "Nifty IT", category: "Technology", returns_1d: -0.31, returns_1w: -0.8, returns_1m: 2.1, returns_3m: 5.4, returns_6m: 8.9, returns_1y: 22.1, current_price: 33450.0, change_pct: -0.31 },
  { ticker: "NIFTYPHARMA", name: "Nifty Pharma", category: "Healthcare", returns_1d: 0.78, returns_1w: 2.1, returns_1m: 5.2, returns_3m: 9.8, returns_6m: 14.2, returns_1y: 26.4, current_price: 19800.0, change_pct: 0.78 },
  { ticker: "NIFTYAUTO", name: "Nifty Auto", category: "Auto", returns_1d: 1.12, returns_1w: 2.8, returns_1m: 6.4, returns_3m: 12.1, returns_6m: 18.5, returns_1y: 31.2, current_price: 22100.0, change_pct: 1.12 },
  { ticker: "NIFTYMETAL", name: "Nifty Metal", category: "Materials", returns_1d: -1.24, returns_1w: -2.4, returns_1m: -3.8, returns_3m: 1.2, returns_6m: 4.5, returns_1y: 8.9, current_price: 8640.0, change_pct: -1.24 },
  { ticker: "NIFTYFMCG", name: "Nifty FMCG", category: "Consumer", returns_1d: 0.18, returns_1w: 0.5, returns_1m: 1.4, returns_3m: 3.2, returns_6m: 5.8, returns_1y: 10.4, current_price: 55200.0, change_pct: 0.18 },
  { ticker: "NIFTYENERGY", name: "Nifty Energy", category: "Energy", returns_1d: 0.55, returns_1w: 1.4, returns_1m: 4.1, returns_3m: 8.6, returns_6m: 12.8, returns_1y: 20.4, current_price: 40100.0, change_pct: 0.55 },
  { ticker: "NIFTYREALTY", name: "Nifty Realty", category: "Real Estate", returns_1d: 1.89, returns_1w: 4.2, returns_1m: 9.8, returns_3m: 18.4, returns_6m: 28.2, returns_1y: 48.6, current_price: 980.0, change_pct: 1.89 },
  { ticker: "NIFTYINFRA", name: "Nifty Infra", category: "Infrastructure", returns_1d: 0.64, returns_1w: 1.6, returns_1m: 4.8, returns_3m: 9.4, returns_6m: 14.8, returns_1y: 24.2, current_price: 8450.0, change_pct: 0.64 },
  { ticker: "NIFTYMIDCAP", name: "Nifty Midcap 100", category: "Broad Market", returns_1d: 0.98, returns_1w: 2.4, returns_1m: 5.8, returns_3m: 11.2, returns_6m: 17.4, returns_1y: 28.8, current_price: 54200.0, change_pct: 0.98 },
];

const BREADTH_DATA: MarketBreadth[] = [
  { label: "NSE 500", advances: 312, declines: 164, unchanged: 24, total: 500, newHighs: 42, newLows: 8 },
  { label: "BSE 500", advances: 298, declines: 178, unchanged: 24, total: 500, newHighs: 38, newLows: 12 },
  { label: "Nifty 50", advances: 32, declines: 17, unchanged: 1, total: 50, newHighs: 6, newLows: 2 },
];

const FII_DII_DATA: FiiDii[] = [
  { date: "2024-12-27", fii_buy: 12450, fii_sell: 9820, fii_net: 2630, dii_buy: 8940, dii_sell: 7120, dii_net: 1820 },
  { date: "2024-12-26", fii_buy: 9840, fii_sell: 11250, fii_net: -1410, dii_buy: 9820, dii_sell: 7840, dii_net: 1980 },
  { date: "2024-12-24", fii_buy: 14820, fii_sell: 10490, fii_net: 4330, dii_buy: 7640, dii_sell: 8120, dii_net: -480 },
  { date: "2024-12-23", fii_buy: 8920, fii_sell: 13450, fii_net: -4530, dii_buy: 10240, dii_sell: 7840, dii_net: 2400 },
  { date: "2024-12-20", fii_buy: 11240, fii_sell: 9870, fii_net: 1370, dii_buy: 8490, dii_sell: 9120, dii_net: -630 },
];

const SCREENER_DATA: ScreenerRow[] = [
  { ticker: "RELIANCE", name: "Reliance Industries", sector: "Energy", price: 2482.5, change_pct: 0.84, volume: 8420000, pe: 22.4, marketCap: "16.8L Cr" },
  { ticker: "TCS", name: "Tata Consultancy Services", sector: "IT", price: 3845.0, change_pct: -0.42, volume: 2140000, pe: 28.6, marketCap: "14.1L Cr" },
  { ticker: "HDFCBANK", name: "HDFC Bank", sector: "Banking", price: 1684.5, change_pct: 0.61, volume: 12840000, pe: 18.2, marketCap: "12.8L Cr" },
  { ticker: "INFY", name: "Infosys", sector: "IT", price: 1842.0, change_pct: -0.28, volume: 5640000, pe: 24.8, marketCap: "7.7L Cr" },
  { ticker: "ICICIBANK", name: "ICICI Bank", sector: "Banking", price: 1082.5, change_pct: 1.14, volume: 18240000, pe: 16.4, marketCap: "7.6L Cr" },
  { ticker: "SBIN", name: "State Bank of India", sector: "Banking", price: 784.5, change_pct: 0.92, volume: 24800000, pe: 9.8, marketCap: "7.0L Cr" },
  { ticker: "BAJFINANCE", name: "Bajaj Finance", sector: "NBFC", price: 6840.0, change_pct: 1.42, volume: 2480000, pe: 32.4, marketCap: "4.1L Cr" },
  { ticker: "MARUTI", name: "Maruti Suzuki", sector: "Auto", price: 10842.0, change_pct: 1.84, volume: 980000, pe: 26.8, marketCap: "3.2L Cr" },
];

const SECTORS = ["All", "Banking", "IT", "Energy", "Auto", "NBFC", "Healthcare"] as const;

// ---------------------------------------------------------------------------
// Utility functions — absorbed from etftracker utilities
// ---------------------------------------------------------------------------

function getReturnValue(item: SectorReturn, tf: TF): number | null {
  return item[TF_KEY[tf]] as number | null;
}

function formatReturn(v: number | null): string {
  if (v === null) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function formatCr(v: number): string {
  if (v >= 10000) return `₹${(v / 10000).toFixed(0)}k Cr`;
  if (v >= 1000) return `₹${(v / 1000).toFixed(1)}k Cr`;
  return `₹${v.toFixed(0)} Cr`;
}

function formatVol(v: number): string {
  if (v >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
  if (v >= 100000) return `${(v / 100000).toFixed(1)} L`;
  if (v >= 1000) return `${(v / 1000).toFixed(0)} K`;
  return v.toString();
}

function ReturnBadge({ value, size = "sm" }: { value: number | null; size?: "sm" | "xs" }) {
  if (value === null) return <span className="text-[#6b6b8a]">--</span>;
  const isPos = value >= 0;
  const cls = [
    "font-mono font-medium",
    size === "xs" ? "text-[10px]" : "text-[11px]",
    isPos ? "text-emerald-400" : "text-red-400",
  ].join(" ");
  return <span className={cls}>{formatReturn(value)}</span>;
}

function DataSourceNotice() {
  return (
    <div className="flex items-start gap-2 rounded-md bg-[#1a1a28] border border-[#1e1e2e] p-3 mb-4">
      <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
      <p className="text-[11px] text-[#9090b0]">
        Connect a data source in{" "}
        <span className="text-[#6c8ef0]">Settings</span> for live market
        intelligence. Showing placeholder data structure.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Market Overview Tab
// ---------------------------------------------------------------------------

function MarketOverviewTab() {
  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        <DataSourceNotice />

        {/* Market breadth */}
        <div>
          <div className="text-[11px] text-[#6b6b8a] mb-2 flex items-center gap-1">
            <Activity size={11} />
            Market Breadth
          </div>
          <div className="grid grid-cols-1 gap-2">
            {BREADTH_DATA.map((bd) => {
              const advPct = ((bd.advances / bd.total) * 100).toFixed(0);
              const decPct = ((bd.declines / bd.total) * 100).toFixed(0);
              return (
                <Card key={bd.label} className="bg-[#12121a] border-[#1e1e2e]">
                  <CardContent className="pt-3 pb-3 px-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[12px] text-[#e0e0f0] font-medium">
                        {bd.label}
                      </span>
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="text-emerald-400">
                          <TrendingUp size={10} className="inline mr-1" />
                          {bd.advances} ({advPct}%)
                        </span>
                        <span className="text-[#6b6b8a]">—</span>
                        <span className="text-red-400">
                          <TrendingDown size={10} className="inline mr-1" />
                          {bd.declines} ({decPct}%)
                        </span>
                        <span className="text-[#6b6b8a]">
                          {bd.unchanged} Unch
                        </span>
                      </div>
                    </div>
                    {/* Progress bar */}
                    <div className="h-1.5 bg-[#1e1e2e] rounded-full overflow-hidden flex">
                      <div
                        className="h-full bg-emerald-500 transition-all"
                        style={{ width: `${advPct}%` }}
                      />
                      <div
                        className="h-full bg-red-500 transition-all"
                        style={{ width: `${decPct}%` }}
                      />
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-[10px] text-[#6b6b8a]">
                      <span>52W High: {bd.newHighs}</span>
                      <span>52W Low: {bd.newLows}</span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>

        {/* FII / DII flows */}
        <div>
          <div className="text-[11px] text-[#6b6b8a] mb-2 flex items-center gap-1">
            <Globe size={11} />
            FII / DII Flows (Cash Segment, ₹ Cr)
          </div>
          <div className="rounded-md border border-[#1e1e2e] overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-[#1e1e2e] hover:bg-transparent">
                  {["Date", "FII Buy", "FII Sell", "FII Net", "DII Buy", "DII Sell", "DII Net"].map(
                    (h) => (
                      <TableHead
                        key={h}
                        className="text-[10px] text-[#6b6b8a] h-8 px-2"
                      >
                        {h}
                      </TableHead>
                    )
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {FII_DII_DATA.map((row) => (
                  <TableRow
                    key={row.date}
                    className="border-[#1e1e2e] hover:bg-[#12121a] text-[11px]"
                  >
                    <TableCell className="px-2 py-1.5 font-mono text-[#9090b0]">
                      {row.date}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 font-mono text-[#e0e0f0]">
                      {formatCr(row.fii_buy)}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 font-mono text-[#e0e0f0]">
                      {formatCr(row.fii_sell)}
                    </TableCell>
                    <TableCell
                      className={[
                        "px-2 py-1.5 font-mono font-semibold",
                        row.fii_net >= 0 ? "text-emerald-400" : "text-red-400",
                      ].join(" ")}
                    >
                      {row.fii_net >= 0 ? "+" : ""}
                      {formatCr(Math.abs(row.fii_net))}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 font-mono text-[#e0e0f0]">
                      {formatCr(row.dii_buy)}
                    </TableCell>
                    <TableCell className="px-2 py-1.5 font-mono text-[#e0e0f0]">
                      {formatCr(row.dii_sell)}
                    </TableCell>
                    <TableCell
                      className={[
                        "px-2 py-1.5 font-mono font-semibold",
                        row.dii_net >= 0 ? "text-emerald-400" : "text-red-400",
                      ].join(" ")}
                    >
                      {row.dii_net >= 0 ? "+" : ""}
                      {formatCr(Math.abs(row.dii_net))}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Sector Rotation Tab — absorbed from etftracker Dashboard3_SectorRotation
// ---------------------------------------------------------------------------

function SectorRotationTab() {
  const [sortTf, setSortTf] = useState<TF>("1M");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...INDIA_SECTORS].sort((a, b) => {
      const av = getReturnValue(a, sortTf) ?? -Infinity;
      const bv = getReturnValue(b, sortTf) ?? -Infinity;
      return sortDir === "desc" ? bv - av : av - bv;
    });
  }, [sortTf, sortDir]);

  const handleTfSort = (tf: TF) => {
    if (sortTf === tf) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortTf(tf);
      setSortDir("desc");
    }
  };

  return (
    <div className="p-4">
      <DataSourceNotice />

      {/* TF sort buttons — absorbed from etftracker rotation-controls pattern */}
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-[11px] text-[#6b6b8a]">Sort by:</span>
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => handleTfSort(tf)}
            className={[
              "text-[11px] px-2 py-0.5 rounded border transition-colors",
              sortTf === tf
                ? "bg-[#1e2a4a] text-[#6c8ef0] border-[#2a3a6a]"
                : "bg-[#12121a] text-[#6b6b8a] border-[#1e1e2e] hover:border-[#3a3a5a]",
            ].join(" ")}
          >
            {tf}
          </button>
        ))}
        <button
          onClick={() => setSortDir(sortDir === "desc" ? "asc" : "desc")}
          className="ml-auto text-[11px] px-2 py-0.5 rounded border bg-[#12121a] text-[#6b6b8a] border-[#1e1e2e] hover:border-[#3a3a5a] flex items-center gap-1"
        >
          <ArrowUpDown size={10} />
          {sortDir === "desc" ? "High to Low" : "Low to High"}
        </button>
      </div>

      <div className="rounded-md border border-[#1e1e2e] overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-[#1e1e2e] hover:bg-transparent">
              <TableHead className="text-[10px] text-[#6b6b8a] h-8 px-3 w-40">
                Sector
              </TableHead>
              <TableHead className="text-[10px] text-[#6b6b8a] h-8 px-2">
                Price
              </TableHead>
              {TIMEFRAMES.map((tf) => (
                <TableHead
                  key={tf}
                  className={[
                    "text-[10px] h-8 px-2 cursor-pointer select-none",
                    sortTf === tf ? "text-[#6c8ef0]" : "text-[#6b6b8a]",
                  ].join(" ")}
                  onClick={() => handleTfSort(tf)}
                >
                  {tf}
                  {sortTf === tf && (
                    <ArrowUpDown size={9} className="inline ml-1 opacity-80" />
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((sector, i) => (
              <TableRow
                key={sector.ticker}
                className="border-[#1e1e2e] hover:bg-[#12121a] text-[12px]"
              >
                <TableCell className="px-3 py-1.5">
                  <span className="text-[10px] text-[#6b6b8a] mr-2 font-mono">
                    {i + 1}
                  </span>
                  <span className="text-[#e0e0f0]">{sector.name}</span>
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-[#9090b0]">
                  {sector.current_price?.toLocaleString("en-IN", {
                    maximumFractionDigits: 0,
                  }) ?? "--"}
                </TableCell>
                {TIMEFRAMES.map((tf) => (
                  <TableCell key={tf} className="px-2 py-1.5">
                    <ReturnBadge value={getReturnValue(sector, tf)} size="xs" />
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heat Map Tab — absorbed from etftracker Dashboard4_IndiaSectors treemap concept
// ---------------------------------------------------------------------------

function HeatMapTab() {
  const [selectedTf, setSelectedTf] = useState<TF>("1M");

  function getColor(v: number | null): string {
    if (v === null) return "#1e1e2e";
    if (v >= 10) return "#064e3b";
    if (v >= 5) return "#065f46";
    if (v >= 2) return "#047857";
    if (v >= 0) return "#059669";
    if (v >= -2) return "#b91c1c";
    if (v >= -5) return "#991b1b";
    if (v >= -10) return "#7f1d1d";
    return "#450a0a";
  }

  const sorted = useMemo(
    () =>
      [...INDIA_SECTORS].sort((a, b) => {
        const av = getReturnValue(a, selectedTf) ?? -Infinity;
        const bv = getReturnValue(b, selectedTf) ?? -Infinity;
        return bv - av;
      }),
    [selectedTf]
  );

  return (
    <div className="p-4">
      <DataSourceNotice />

      {/* TF toggles */}
      <div className="flex items-center gap-1.5 mb-4">
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            onClick={() => setSelectedTf(tf)}
            className={[
              "text-[11px] px-2.5 py-0.5 rounded border transition-colors",
              selectedTf === tf
                ? "bg-[#1e2a4a] text-[#6c8ef0] border-[#2a3a6a]"
                : "bg-[#12121a] text-[#6b6b8a] border-[#1e1e2e] hover:border-[#3a3a5a]",
            ].join(" ")}
          >
            {tf}
          </button>
        ))}
      </div>

      {/* Treemap-style grid — absorbed from etftracker India sectoral heatmap */}
      <div className="grid grid-cols-4 gap-1.5">
        {sorted.map((sector) => {
          const ret = getReturnValue(sector, selectedTf);
          const isPos = ret !== null && ret >= 0;
          return (
            <div
              key={sector.ticker}
              className="rounded-md p-3 flex flex-col justify-between min-h-[70px] cursor-default transition-all hover:opacity-90"
              style={{ backgroundColor: getColor(ret) }}
              title={`${sector.name}: ${formatReturn(ret)}`}
            >
              <div className="text-[11px] text-white/80 leading-tight font-medium">
                {sector.name}
              </div>
              <div
                className={[
                  "text-[14px] font-mono font-bold mt-1",
                  isPos ? "text-emerald-200" : "text-red-200",
                ].join(" ")}
              >
                {formatReturn(ret)}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-3 flex items-center gap-2 text-[10px] text-[#6b6b8a]">
        <Map size={10} />
        Showing Nifty sectoral indices. Connect live data for real-time updates.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Screener Tab — absorbed from etftracker Dashboard6_ETFScreener
// ---------------------------------------------------------------------------

function ScreenerTab() {
  const [search, setSearch] = useState("");
  const [sector, setSector] = useState("All");
  const [sortField, setSortField] = useState<keyof ScreenerRow>("marketCap");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const filtered = useMemo(() => {
    let list = SCREENER_DATA;
    if (sector !== "All") {
      list = list.filter((r) => r.sector === sector);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (r) =>
          r.ticker.toLowerCase().includes(q) ||
          r.name.toLowerCase().includes(q)
      );
    }
    return [...list].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "desc" ? bv - av : av - bv;
      }
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });
  }, [search, sector, sortField, sortDir]);

  const handleSort = (field: keyof ScreenerRow) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  return (
    <div className="p-4">
      <DataSourceNotice />

      {/* Toolbar — absorbed from etftracker screener-toolbar pattern */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <div className="relative flex-1 min-w-[160px]">
          <Search
            size={12}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#6b6b8a]"
          />
          <Input
            placeholder="Search symbol or name..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-7 h-8 bg-[#12121a] border-[#1e1e2e] text-[12px] placeholder:text-[#404060]"
          />
        </div>
        <div className="flex items-center gap-1">
          <SlidersHorizontal size={12} className="text-[#6b6b8a]" />
          <Select value={sector} onValueChange={setSector}>
            <SelectTrigger className="h-8 bg-[#12121a] border-[#1e1e2e] text-[12px] w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-[#12121a] border-[#1e1e2e]">
              {SECTORS.map((s) => (
                <SelectItem key={s} value={s} className="text-[12px]">
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <span className="text-[11px] text-[#6b6b8a]">
          {filtered.length} of {SCREENER_DATA.length}
        </span>
      </div>

      <div className="rounded-md border border-[#1e1e2e] overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-[#1e1e2e] hover:bg-transparent">
              {(
                [
                  ["Symbol", "ticker"],
                  ["Name", "name"],
                  ["Sector", "sector"],
                  ["Price", "price"],
                  ["Change %", "change_pct"],
                  ["Volume", "volume"],
                  ["P/E", "pe"],
                  ["Mkt Cap", "marketCap"],
                ] as [string, keyof ScreenerRow][]
              ).map(([label, field]) => (
                <TableHead
                  key={field}
                  className={[
                    "text-[10px] h-8 px-2 cursor-pointer select-none",
                    sortField === field ? "text-[#6c8ef0]" : "text-[#6b6b8a]",
                  ].join(" ")}
                  onClick={() => handleSort(field)}
                >
                  {label}
                  {sortField === field && (
                    <ArrowUpDown size={9} className="inline ml-1 opacity-80" />
                  )}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((row) => (
              <TableRow
                key={row.ticker}
                className="border-[#1e1e2e] hover:bg-[#12121a] text-[12px]"
              >
                <TableCell className="px-2 py-1.5 font-mono font-semibold text-[#6c8ef0]">
                  {row.ticker}
                </TableCell>
                <TableCell className="px-2 py-1.5 text-[#e0e0f0] max-w-[120px] truncate">
                  {row.name}
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  <Badge className="text-[9px] h-4 px-1 bg-[#12121a] text-[#9090b0] border-[#1e1e2e]">
                    {row.sector}
                  </Badge>
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-[#e0e0f0]">
                  {row.price.toLocaleString("en-IN", {
                    maximumFractionDigits: 2,
                  })}
                </TableCell>
                <TableCell className="px-2 py-1.5">
                  <ReturnBadge value={row.change_pct} size="xs" />
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-[#9090b0]">
                  {formatVol(row.volume)}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-[#9090b0]">
                  {row.pe !== null ? row.pe.toFixed(1) : "--"}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-[#9090b0]">
                  {row.marketCap}
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-center py-8 text-[#6b6b8a] text-[12px]"
                >
                  No results found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

export default function MarketIntelligenceTool({ onClose }: Props) {
  return (
    <div className="h-full flex flex-col bg-[#0a0a0f]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#1e1e2e] bg-[#12121a] shrink-0">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-[#6c8ef0]" />
          <span className="text-[13px] font-semibold text-[#e0e0f0]">
            Market Intelligence
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-[#6b6b8a] hover:text-[#e0e0f0] transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="overview" className="flex flex-col flex-1 min-h-0">
        <TabsList className="mx-4 mt-3 mb-0 h-8 bg-[#12121a] border border-[#1e1e2e] shrink-0 rounded-md w-auto self-start">
          <TabsTrigger
            value="overview"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Overview
          </TabsTrigger>
          <TabsTrigger
            value="sectors"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Sectors
          </TabsTrigger>
          <TabsTrigger
            value="heatmap"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Heat Map
          </TabsTrigger>
          <TabsTrigger
            value="screener"
            className="text-[12px] h-6 px-3 data-[state=active]:bg-[#1e1e2e] data-[state=active]:text-[#e0e0f0]"
          >
            Screener
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="flex-1 overflow-y-auto mt-0">
          <MarketOverviewTab />
        </TabsContent>
        <TabsContent value="sectors" className="flex-1 overflow-y-auto mt-0">
          <SectorRotationTab />
        </TabsContent>
        <TabsContent value="heatmap" className="flex-1 overflow-y-auto mt-0">
          <HeatMapTab />
        </TabsContent>
        <TabsContent value="screener" className="flex-1 overflow-y-auto mt-0">
          <ScreenerTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
