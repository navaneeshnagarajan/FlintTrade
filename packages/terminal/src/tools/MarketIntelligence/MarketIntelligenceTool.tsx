/**
 * MarketIntelligenceTool — 10-tab market intelligence dashboard
 * Absorbed patterns from:
 *   - etftracker/Dashboard2_MarketPulse: advances/declines, breadth
 *   - etftracker/Dashboard3_SectorRotation: sector sortable table
 *   - etftracker/Dashboard4_IndiaSectors: India sectoral heatmap
 *   - etftracker/Dashboard6_ETFScreener: search + filter screener
 *   - oipulse/42-fii-capital-market: FII/DII flows table
 *   - oipulse/44-participant-wise-oi: participant OI breakdown
 *   - oipulse/40-delivery-data: delivery data table
 *   - oipulse/47-vix-index: India VIX card
 *   - oipulse/46-world-indices: global indices table
 *   - oipulse/38-sector-heatmap: CSS treemap
 *   - oipulse/41-announcement: corporate announcements feed
 */

import { useState, useMemo } from "react";
import {
  X,
  BarChart3,
  TrendingUp,
  TrendingDown,
  Info,
  ArrowUpDown,
  Globe,
  Activity,
  Map,
  Zap,
  Users,
  Package,
  Grid3X3,
  Megaphone,
  ChevronRight,
  ShieldAlert,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// ---------------------------------------------------------------------------
// Types
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
  market_cap_cr: number;
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

interface FiiDiiRow {
  date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
}

interface GlobalIndex {
  name: string;
  region: string;
  ltp: number;
  change: number;
  change_pct: number;
  currency: string;
}

interface ParticipantOI {
  participant: string;
  long_index_fut: number;
  short_index_fut: number;
  long_index_opt: number;
  short_index_opt: number;
  long_stock_fut: number;
  short_stock_fut: number;
  net_index_fut: number;
}

interface DeliveryRow {
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume_lakh: number;
  delivery_pct: number;
  series: string;
}

interface Announcement {
  symbol: string;
  exchange: string;
  subject: string;
  date: string;
  category: string;
}

// ---------------------------------------------------------------------------
// Static placeholder data
// ---------------------------------------------------------------------------

const TIMEFRAMES = ["1D", "1W", "1M", "3M", "6M", "1Y"] as const;
type TF = (typeof TIMEFRAMES)[number];

const TF_KEY: Record<TF, keyof SectorReturn> = {
  "1D": "returns_1d",
  "1W": "returns_1w",
  "1M": "returns_1m",
  "3M": "returns_3m",
  "6M": "returns_6m",
  "1Y": "returns_1y",
};

const INDIA_SECTORS: SectorReturn[] = [
  { ticker: "NIFTYBANK", name: "Nifty Bank", category: "Financial", returns_1d: 0.42, returns_1w: 1.2, returns_1m: 3.8, returns_3m: 7.2, returns_6m: 11.4, returns_1y: 18.6, current_price: 48250.5, change_pct: 0.42, market_cap_cr: 1420000 },
  { ticker: "NIFTYIT", name: "Nifty IT", category: "Technology", returns_1d: -0.31, returns_1w: -0.8, returns_1m: 2.1, returns_3m: 5.4, returns_6m: 8.9, returns_1y: 22.1, current_price: 33450.0, change_pct: -0.31, market_cap_cr: 980000 },
  { ticker: "NIFTYPHARMA", name: "Nifty Pharma", category: "Healthcare", returns_1d: 0.78, returns_1w: 2.1, returns_1m: 5.2, returns_3m: 9.8, returns_6m: 14.2, returns_1y: 26.4, current_price: 19800.0, change_pct: 0.78, market_cap_cr: 620000 },
  { ticker: "NIFTYAUTO", name: "Nifty Auto", category: "Auto", returns_1d: 1.12, returns_1w: 2.8, returns_1m: 6.4, returns_3m: 12.1, returns_6m: 18.5, returns_1y: 31.2, current_price: 22100.0, change_pct: 1.12, market_cap_cr: 540000 },
  { ticker: "NIFTYMETAL", name: "Nifty Metal", category: "Materials", returns_1d: -1.24, returns_1w: -2.4, returns_1m: -3.8, returns_3m: 1.2, returns_6m: 4.5, returns_1y: 8.9, current_price: 8640.0, change_pct: -1.24, market_cap_cr: 310000 },
  { ticker: "NIFTYFMCG", name: "Nifty FMCG", category: "Consumer", returns_1d: 0.18, returns_1w: 0.5, returns_1m: 1.4, returns_3m: 3.2, returns_6m: 5.8, returns_1y: 10.4, current_price: 55200.0, change_pct: 0.18, market_cap_cr: 720000 },
  { ticker: "NIFTYENERGY", name: "Nifty Energy", category: "Energy", returns_1d: 0.55, returns_1w: 1.4, returns_1m: 4.1, returns_3m: 8.6, returns_6m: 12.8, returns_1y: 20.4, current_price: 40100.0, change_pct: 0.55, market_cap_cr: 890000 },
  { ticker: "NIFTYREALTY", name: "Nifty Realty", category: "Real Estate", returns_1d: 1.89, returns_1w: 4.2, returns_1m: 9.8, returns_3m: 18.4, returns_6m: 28.2, returns_1y: 48.6, current_price: 980.0, change_pct: 1.89, market_cap_cr: 240000 },
  { ticker: "NIFTYINFRA", name: "Nifty Infra", category: "Infrastructure", returns_1d: 0.64, returns_1w: 1.6, returns_1m: 4.8, returns_3m: 9.4, returns_6m: 14.8, returns_1y: 24.2, current_price: 8450.0, change_pct: 0.64, market_cap_cr: 480000 },
  { ticker: "NIFTYMIDCAP", name: "Nifty Midcap 100", category: "Broad Market", returns_1d: 0.98, returns_1w: 2.4, returns_1m: 5.8, returns_3m: 11.2, returns_6m: 17.4, returns_1y: 28.8, current_price: 54200.0, change_pct: 0.98, market_cap_cr: 1100000 },
];

const BREADTH_DATA: MarketBreadth[] = [
  { label: "NSE 500", advances: 312, declines: 164, unchanged: 24, total: 500, newHighs: 42, newLows: 8 },
  { label: "BSE 500", advances: 298, declines: 178, unchanged: 24, total: 500, newHighs: 38, newLows: 12 },
  { label: "Nifty 50", advances: 32, declines: 17, unchanged: 1, total: 50, newHighs: 6, newLows: 2 },
];

const FII_DII_DATA: FiiDiiRow[] = [
  { date: "2024-12-27", fii_buy: 12450, fii_sell: 9820, fii_net: 2630, dii_buy: 8940, dii_sell: 7120, dii_net: 1820 },
  { date: "2024-12-26", fii_buy: 9840, fii_sell: 11250, fii_net: -1410, dii_buy: 9820, dii_sell: 7840, dii_net: 1980 },
  { date: "2024-12-24", fii_buy: 14820, fii_sell: 10490, fii_net: 4330, dii_buy: 7640, dii_sell: 8120, dii_net: -480 },
  { date: "2024-12-23", fii_buy: 8920, fii_sell: 13450, fii_net: -4530, dii_buy: 10240, dii_sell: 7840, dii_net: 2400 },
  { date: "2024-12-20", fii_buy: 11240, fii_sell: 9870, fii_net: 1370, dii_buy: 8490, dii_sell: 9120, dii_net: -630 },
  { date: "2024-12-19", fii_buy: 7840, fii_sell: 14280, fii_net: -6440, dii_buy: 11240, dii_sell: 6480, dii_net: 4760 },
  { date: "2024-12-18", fii_buy: 15640, fii_sell: 8920, fii_net: 6720, dii_buy: 7840, dii_sell: 9120, dii_net: -1280 },
];

const GLOBAL_INDICES: GlobalIndex[] = [
  { name: "S&P 500", region: "USA", ltp: 4782.82, change: 24.18, change_pct: 0.51, currency: "USD" },
  { name: "NASDAQ 100", region: "USA", ltp: 16832.92, change: -42.14, change_pct: -0.25, currency: "USD" },
  { name: "Dow Jones", region: "USA", ltp: 37440.67, change: 158.11, change_pct: 0.42, currency: "USD" },
  { name: "FTSE 100", region: "UK", ltp: 7648.30, change: -18.20, change_pct: -0.24, currency: "GBP" },
  { name: "Nikkei 225", region: "Japan", ltp: 33431.51, change: 442.80, change_pct: 1.34, currency: "JPY" },
  { name: "Hang Seng", region: "Hong Kong", ltp: 16524.33, change: -132.60, change_pct: -0.80, currency: "HKD" },
  { name: "DAX", region: "Germany", ltp: 16751.48, change: 84.20, change_pct: 0.50, currency: "EUR" },
  { name: "Shanghai Comp.", region: "China", ltp: 2962.28, change: -8.44, change_pct: -0.28, currency: "CNY" },
  { name: "SGX Nifty", region: "Singapore", ltp: 21842.0, change: 108.5, change_pct: 0.50, currency: "USD" },
];

const PARTICIPANT_OI: ParticipantOI[] = [
  { participant: "FII", long_index_fut: 284120, short_index_fut: 312480, long_index_opt: 8420180, short_index_opt: 6284200, long_stock_fut: 142840, short_stock_fut: 128640, net_index_fut: -28360 },
  { participant: "Pro", long_index_fut: 198420, short_index_fut: 184200, long_index_opt: 4284200, short_index_opt: 6420480, long_stock_fut: 84200, short_stock_fut: 92840, net_index_fut: 14220 },
  { participant: "DII", long_index_fut: 48200, short_index_fut: 24800, long_index_opt: 248200, short_index_opt: 184200, long_stock_fut: 42840, short_stock_fut: 28400, net_index_fut: 23400 },
  { participant: "Client", long_index_fut: 420840, short_index_fut: 428480, long_index_opt: 2148200, short_index_opt: 2212200, long_stock_fut: 284200, short_stock_fut: 302200, net_index_fut: -7640 },
];

const DELIVERY_DATA: DeliveryRow[] = [
  { symbol: "HDFCBANK", open: 1672.0, high: 1698.5, low: 1668.0, close: 1689.5, volume_lakh: 128.4, delivery_pct: 78.4, series: "EQ" },
  { symbol: "TCS", open: 3840.0, high: 3880.0, low: 3824.0, close: 3848.5, volume_lakh: 24.8, delivery_pct: 72.1, series: "EQ" },
  { symbol: "RELIANCE", open: 2468.0, high: 2492.0, low: 2456.0, close: 2481.5, volume_lakh: 84.2, delivery_pct: 68.9, series: "EQ" },
  { symbol: "INFY", open: 1834.0, high: 1858.5, low: 1828.0, close: 1842.0, volume_lakh: 56.4, delivery_pct: 65.3, series: "EQ" },
  { symbol: "ITC", open: 458.5, high: 465.0, low: 455.0, close: 461.5, volume_lakh: 184.2, delivery_pct: 62.8, series: "EQ" },
  { symbol: "SBIN", open: 778.0, high: 792.0, low: 774.0, close: 784.5, volume_lakh: 248.0, delivery_pct: 58.4, series: "EQ" },
  { symbol: "WIPRO", open: 524.0, high: 530.5, low: 519.5, close: 526.0, volume_lakh: 42.8, delivery_pct: 55.2, series: "EQ" },
  { symbol: "BAJFINANCE", open: 6820.0, high: 6892.0, low: 6810.0, close: 6848.0, volume_lakh: 24.8, delivery_pct: 52.7, series: "EQ" },
  { symbol: "KOTAKBANK", open: 1748.0, high: 1768.0, low: 1742.0, close: 1754.0, volume_lakh: 38.4, delivery_pct: 48.9, series: "EQ" },
  { symbol: "AXISBANK", open: 1082.0, high: 1098.0, low: 1078.5, close: 1092.5, volume_lakh: 92.4, delivery_pct: 44.2, series: "EQ" },
];

const ANNOUNCEMENTS: Announcement[] = [
  { symbol: "HDFCBANK", exchange: "BSE", subject: "Board Meeting to consider Q3 FY25 financial results on January 22, 2025", date: "2024-12-27", category: "Board Meeting" },
  { symbol: "TCS", exchange: "NSE", subject: "Outcome of Board Meeting — Declaration of Interim Dividend of ₹10 per share", date: "2024-12-27", category: "Dividend" },
  { symbol: "RELIANCE", exchange: "BSE", subject: "Allotment of Non-Convertible Debentures under Private Placement", date: "2024-12-26", category: "Debt" },
  { symbol: "INFY", exchange: "NSE", subject: "Trading Window Closure Notice — Insider Trading Regulations", date: "2024-12-26", category: "Compliance" },
  { symbol: "SBIN", exchange: "BSE", subject: "Change in Director / Key Managerial Personnel — appointment of MD & CEO", date: "2024-12-24", category: "Appointment" },
  { symbol: "BAJFINANCE", exchange: "NSE", subject: "Outcome of Board Meeting — Q2 FY25 Results, Rights Issue approval", date: "2024-12-24", category: "Results" },
  { symbol: "WIPRO", exchange: "BSE", subject: "Buyback of equity shares — record date January 10, 2025", date: "2024-12-23", category: "Buyback" },
  { symbol: "ICICIBANK", exchange: "NSE", subject: "Credit Rating — reaffirmation of AAA (Stable) by CRISIL", date: "2024-12-23", category: "Rating" },
  { symbol: "TATAMOTORS", exchange: "BSE", subject: "Preferential Issue — 4.2 crore equity shares at ₹842 per share", date: "2024-12-20", category: "Equity" },
  { symbol: "LTIM", exchange: "NSE", subject: "Board Meeting to consider Interim Dividend for FY2024-25", date: "2024-12-20", category: "Dividend" },
];

// Correlation matrix (illustrative — approximate 1-year rolling correlations)
// Assets: VIX | Nifty | Gold | Crude | USD-INR
const CORR_ASSETS = ["VIX", "Nifty", "Gold", "Crude", "USD-INR"];
const CORR_MATRIX: number[][] = [
  [ 1.00, -0.72,  0.18,  0.12,  0.34],
  [-0.72,  1.00, -0.08,  0.42, -0.62],
  [ 0.18, -0.08,  1.00,  0.28,  0.48],
  [ 0.12,  0.42,  0.28,  1.00, -0.18],
  [ 0.34, -0.62,  0.48, -0.18,  1.00],
];

// ---------------------------------------------------------------------------
// Utility functions
// ---------------------------------------------------------------------------

function getReturnValue(item: SectorReturn, tf: TF): number | null {
  return item[TF_KEY[tf]] as number | null;
}

function formatReturn(v: number | null): string {
  if (v === null) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function formatCr(v: number): string {
  if (Math.abs(v) >= 10000) return `₹${(v / 10000).toFixed(0)}k Cr`;
  if (Math.abs(v) >= 1000) return `₹${(v / 1000).toFixed(1)}k Cr`;
  return `₹${v.toFixed(0)} Cr`;
}

function netColor(v: number): string {
  return v >= 0 ? "text-emerald-400" : "text-red-400";
}

function ReturnBadge({ value, size = "sm" }: { value: number | null; size?: "sm" | "xs" }) {
  if (value === null) return <span className="text-text-muted">--</span>;
  const isPos = value >= 0;
  const cls = [
    "font-mono font-medium",
    size === "xs" ? "text-xs" : "text-xs",
    isPos ? "text-emerald-400" : "text-red-400",
  ].join(" ");
  return <span className={cls}>{formatReturn(value)}</span>;
}

function DataNotice({ text }: { text?: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md bg-surface-elevated border border-border-default p-3 mb-4">
      <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
      <p className="text-xs text-text-secondary">
        {text ?? (
          <>
            Live data available during market hours. Connect a data source in{" "}
            <span className="text-primary">Settings</span> for real-time updates.
            Showing representative data structure.
          </>
        )}
      </p>
    </div>
  );
}

function SectionLabel({ icon: Icon, label }: { icon: typeof Activity; label: string }) {
  return (
    <div className="text-xs text-text-muted mb-2 flex items-center gap-1.5">
      <Icon size={11} />
      {label}
    </div>
  );
}

function TfButton({
  tf,
  active,
  onClick,
}: {
  tf: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        "text-xs px-2 py-0.5 rounded border transition-colors",
        active
          ? "bg-neutral-bg text-primary border-neutral-border"
          : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
      ].join(" ")}
    >
      {tf}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab 1: Market Breadth
// ---------------------------------------------------------------------------

function MarketBreadthTab() {
  const totalAdvances = BREADTH_DATA.reduce((a, b) => a + b.advances, 0);
  const totalDeclines = BREADTH_DATA.reduce((a, b) => a + b.declines, 0);
  const totalUnchanged = BREADTH_DATA.reduce((a, b) => a + b.unchanged, 0);
  const totalStocks = BREADTH_DATA.reduce((a, b) => a + b.total, 0);

  const adRatio = totalDeclines > 0 ? (totalAdvances / totalDeclines).toFixed(2) : "--";
  // Breadth thrust: ratio of advances to (advances+declines), 10-day EMA > 0.615 = bullish signal
  const breadthThrustRaw =
    totalAdvances + totalDeclines > 0
      ? (totalAdvances / (totalAdvances + totalDeclines)) * 100
      : 0;

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        <DataNotice />

        {/* Summary cards */}
        <div className="grid grid-cols-3 gap-2">
          {[
            { label: "Advances", value: totalAdvances, color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" },
            { label: "Declines", value: totalDeclines, color: "text-red-400", bg: "bg-red-500/10 border-red-500/20" },
            { label: "Unchanged", value: totalUnchanged, color: "text-text-secondary", bg: "bg-surface-card border-border-default" },
          ].map((c) => (
            <Card key={c.label} className={`border ${c.bg}`}>
              <CardContent className="pt-3 pb-3 px-4">
                <div className={`text-xl font-mono font-bold tabular-nums ${c.color}`}>{c.value}</div>
                <div className="text-xs text-text-muted mt-0.5">{c.label} (of {totalStocks})</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* A/D Ratio + Breadth Thrust */}
        <div className="grid grid-cols-2 gap-2">
          <Card className="bg-surface-card border-border-default">
            <CardContent className="pt-3 pb-3 px-4">
              <div className="text-xs text-text-muted mb-1">A/D Ratio</div>
              <div className={`text-xl font-mono font-bold tabular-nums ${parseFloat(adRatio) >= 1 ? "text-emerald-400" : "text-red-400"}`}>
                {adRatio}
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                {parseFloat(adRatio) >= 1.5
                  ? "Strongly Bullish"
                  : parseFloat(adRatio) >= 1.0
                  ? "Mildly Bullish"
                  : parseFloat(adRatio) >= 0.67
                  ? "Mildly Bearish"
                  : "Strongly Bearish"}
              </div>
            </CardContent>
          </Card>
          <Card className="bg-surface-card border-border-default">
            <CardContent className="pt-3 pb-3 px-4">
              <div className="text-xs text-text-muted mb-1">Breadth Thrust</div>
              <div className={`text-xl font-mono font-bold tabular-nums ${breadthThrustRaw >= 61.5 ? "text-emerald-400" : breadthThrustRaw >= 40 ? "text-text-secondary" : "text-red-400"}`}>
                {breadthThrustRaw.toFixed(1)}%
              </div>
              <div className="text-xs text-text-muted mt-0.5">
                {breadthThrustRaw >= 61.5 ? "Bullish signal (>61.5%)" : breadthThrustRaw >= 40 ? "Neutral zone" : "Bearish zone (<40%)"}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Per-index progress bars */}
        <div>
          <SectionLabel icon={Activity} label="Index-wise Breadth" />
          <div className="space-y-2">
            {BREADTH_DATA.map((bd) => {
              const advPct = ((bd.advances / bd.total) * 100).toFixed(0);
              const decPct = ((bd.declines / bd.total) * 100).toFixed(0);
              const unchPct = (100 - parseInt(advPct) - parseInt(decPct)).toFixed(0);
              return (
                <Card key={bd.label} className="bg-surface-card border-border-default">
                  <CardContent className="pt-3 pb-3 px-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-text-primary font-medium">{bd.label}</span>
                      <div className="flex items-center gap-3 text-xs">
                        <span className="text-emerald-400">
                          <TrendingUp size={10} className="inline mr-0.5" />
                          {bd.advances} ({advPct}%)
                        </span>
                        <span className="text-red-400">
                          <TrendingDown size={10} className="inline mr-0.5" />
                          {bd.declines} ({decPct}%)
                        </span>
                        <span className="text-text-muted">{bd.unchanged} Unch</span>
                      </div>
                    </div>
                    <div className="h-2 bg-surface-elevated rounded-full overflow-hidden flex gap-px">
                      <div className="h-full bg-emerald-500 transition-all" style={{ width: `${advPct}%` }} />
                      <div className="h-full bg-surface-active transition-all" style={{ width: `${unchPct}%` }} />
                      <div className="h-full bg-red-500 transition-all" style={{ width: `${decPct}%` }} />
                    </div>
                    <div className="flex items-center gap-4 mt-2 text-xs text-text-muted">
                      <span>52W High: <span className="text-emerald-400">{bd.newHighs}</span></span>
                      <span>52W Low: <span className="text-red-400">{bd.newLows}</span></span>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Tab 2: FII/DII Flows
// ---------------------------------------------------------------------------

function FiiDiiFlowsTab() {
  const cashRows = FII_DII_DATA;
  // Derivative segment placeholder — same structure, different values
  const derivRows: FiiDiiRow[] = [
    { date: "2024-12-27", fii_buy: 184200, fii_sell: 168400, fii_net: 15800, dii_buy: 42800, dii_sell: 38400, dii_net: 4400 },
    { date: "2024-12-26", fii_buy: 152400, fii_sell: 174200, fii_net: -21800, dii_buy: 38400, dii_sell: 29800, dii_net: 8600 },
    { date: "2024-12-24", fii_buy: 198400, fii_sell: 142000, fii_net: 56400, dii_buy: 28400, dii_sell: 34200, dii_net: -5800 },
    { date: "2024-12-23", fii_buy: 124800, fii_sell: 198400, fii_net: -73600, dii_buy: 48200, dii_sell: 28800, dii_net: 19400 },
    { date: "2024-12-20", fii_buy: 168400, fii_sell: 148200, fii_net: 20200, dii_buy: 32800, dii_sell: 42400, dii_net: -9600 },
  ];

  const FiiDiiTable = ({ rows, title }: { rows: FiiDiiRow[]; title: string }) => (
    <div className="mb-5">
      <SectionLabel icon={Globe} label={title} />
      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {["Date", "FII Buy", "FII Sell", "FII Net", "DII Buy", "DII Sell", "DII Net"].map((h) => (
                <TableHead key={h} className="text-xs text-text-muted h-8 px-2">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={`${title}-${row.date}`} className="border-border-default hover:bg-surface-card text-xs">
                <TableCell className="px-2 py-1.5 font-mono text-text-secondary">{row.date}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.fii_buy)}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.fii_sell)}</TableCell>
                <TableCell className={`px-2 py-1.5 font-mono font-semibold ${netColor(row.fii_net)}`}>
                  {row.fii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.fii_net))}
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.dii_buy)}</TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-text-primary">{formatCr(row.dii_sell)}</TableCell>
                <TableCell className={`px-2 py-1.5 font-mono font-semibold ${netColor(row.dii_net)}`}>
                  {row.dii_net >= 0 ? "+" : ""}{formatCr(Math.abs(row.dii_net))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );

  return (
    <ScrollArea className="h-full">
      <div className="p-4">
        <DataNotice />
        <FiiDiiTable rows={cashRows} title="Capital Market Segment (₹ Cr)" />
        <FiiDiiTable rows={derivRows} title="Derivative Segment (₹ Cr)" />
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Tab 3: Sector Rotation
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
      <DataNotice />
      <div className="flex items-center gap-1.5 mb-3">
        <span className="text-xs text-text-muted">Sort by:</span>
        {TIMEFRAMES.map((tf) => (
          <TfButton key={tf} tf={tf} active={sortTf === tf} onClick={() => handleTfSort(tf)} />
        ))}
        <button
          onClick={() => setSortDir(sortDir === "desc" ? "asc" : "desc")}
          className="ml-auto text-xs px-2 py-0.5 rounded border bg-surface-card text-text-muted border-border-default hover:border-border-strong flex items-center gap-1"
        >
          <ArrowUpDown size={10} />
          {sortDir === "desc" ? "High to Low" : "Low to High"}
        </button>
      </div>

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              <TableHead className="text-xs text-text-muted h-8 px-3 w-44">Sector</TableHead>
              <TableHead className="text-xs text-text-muted h-8 px-2">Price</TableHead>
              {TIMEFRAMES.map((tf) => (
                <TableHead
                  key={tf}
                  className={["text-xs h-8 px-2 cursor-pointer select-none", sortTf === tf ? "text-primary" : "text-text-muted"].join(" ")}
                  onClick={() => handleTfSort(tf)}
                >
                  {tf}
                  {sortTf === tf && <ArrowUpDown size={9} className="inline ml-1 opacity-80" />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((sector, i) => (
              <TableRow key={sector.ticker} className="border-border-default hover:bg-surface-card">
                <TableCell className="px-3 py-1.5">
                  <span className="text-xs text-text-muted mr-2 font-mono">{i + 1}</span>
                  <span className="text-xs text-text-primary">{sector.name}</span>
                </TableCell>
                <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">
                  {sector.current_price?.toLocaleString("en-IN", { maximumFractionDigits: 0 }) ?? "--"}
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
// Tab 4: Sector Heatmap
// ---------------------------------------------------------------------------

function SectorHeatmapTab() {
  const [selectedTf, setSelectedTf] = useState<TF>("1D");

  function getCellColor(v: number | null): string {
    if (v === null) return "#1e1e2e";
    if (v >= 3) return "#064e3b";
    if (v >= 1.5) return "#065f46";
    if (v >= 0.5) return "#047857";
    if (v >= 0) return "#059669";
    if (v >= -0.5) return "#991b1b";
    if (v >= -1.5) return "#7f1d1d";
    if (v >= -3) return "#6b1212";
    return "#450a0a";
  }

  function getTextColor(v: number | null): string {
    if (v === null) return "#6b6b8a";
    return v >= 0 ? "#a7f3d0" : "#fca5a5";
  }

  const sorted = useMemo(
    () =>
      [...INDIA_SECTORS].sort((a, b) => {
        return b.market_cap_cr - a.market_cap_cr;
      }),
    []
  );

  // Determine cell size by market cap (largest = 2x2, mid = 1x2, small = 1x1)
  // Use a simple flex wrap with varying widths
  const totalCap = sorted.reduce((a, b) => a + b.market_cap_cr, 0);

  return (
    <div className="p-4">
      <DataNotice />
      <div className="flex items-center gap-1.5 mb-4">
        {TIMEFRAMES.map((tf) => (
          <TfButton key={tf} tf={tf} active={selectedTf === tf} onClick={() => setSelectedTf(tf)} />
        ))}
      </div>

      {/* CSS treemap-style grid weighted by market cap */}
      <div className="flex flex-wrap gap-1.5">
        {sorted.map((sector) => {
          const ret = getReturnValue(sector, selectedTf);
          const capWeight = (sector.market_cap_cr / totalCap) * 100;
          // Map weight to width percentage: min 12%, max 28%
          const widthPct = Math.max(12, Math.min(28, capWeight * 0.8));
          const heightPx = capWeight >= 10 ? 84 : capWeight >= 6 ? 72 : 62;

          return (
            <div
              key={sector.ticker}
              className="rounded-md flex flex-col justify-between p-2.5 cursor-default transition-opacity hover:opacity-90 shrink-0"
              style={{
                backgroundColor: getCellColor(ret),
                width: `calc(${widthPct}% - 6px)`,
                height: `${heightPx}px`,
              }}
              title={`${sector.name}: ${formatReturn(ret)}`}
            >
              <div className="text-xs text-white/75 leading-tight font-medium truncate">
                {sector.name}
              </div>
              <div className="flex items-end justify-between gap-1">
                <div
                  className="text-sm font-mono font-bold"
                  style={{ color: getTextColor(ret) }}
                >
                  {formatReturn(ret)}
                </div>
                <div className="text-xxs text-white/40 font-mono">
                  {(sector.market_cap_cr / 100000).toFixed(1)}L Cr
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 mt-4 text-xs text-text-muted">
        <Map size={10} />
        <span>Cell size = market cap weight</span>
        <span className="ml-1">Color:</span>
        {[
          { label: ">3%", color: "#064e3b" },
          { label: "1.5-3%", color: "#065f46" },
          { label: "0-1.5%", color: "#059669" },
          { label: "0 to -1.5%", color: "#991b1b" },
          { label: "<-3%", color: "#450a0a" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1">
            <span className="w-3 h-3 rounded" style={{ backgroundColor: l.color }} />
            <span>{l.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 5: India VIX
// ---------------------------------------------------------------------------

function IndiaVixTab() {
  // Static representative VIX value — live data via OpenAlgo quotes
  const vixValue = 14.28;
  const vixChange = -0.42;
  const vixChangePct = -2.86;

  function getVixZone(v: number): { label: string; description: string; color: string; bg: string } {
    if (v < 12) return { label: "Extreme Complacency", description: "Markets are extremely calm. Options are cheap. Consider buying protection.", color: "text-blue-400", bg: "bg-blue-500/10 border-blue-500/20" };
    if (v < 16) return { label: "Low Volatility", description: "Fear is low. Markets are trending. Options premiums are affordable.", color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/20" };
    if (v < 20) return { label: "Moderate Volatility", description: "Normal market conditions. Options are fairly priced.", color: "text-amber-400", bg: "bg-amber-500/10 border-amber-500/20" };
    if (v < 25) return { label: "Elevated Fear", description: "Increased uncertainty. Traders are hedging more aggressively.", color: "text-orange-400", bg: "bg-orange-500/10 border-orange-500/20" };
    if (v < 30) return { label: "High Fear", description: "Significant market stress. Strong sell-off likely in progress.", color: "text-red-400", bg: "bg-red-500/10 border-red-500/20" };
    return { label: "Panic Zone", description: "Extreme fear and market stress. Historically a contrarian buy signal.", color: "text-red-500", bg: "bg-red-600/20 border-red-600/30" };
  }

  const zone = getVixZone(vixValue);

  // 52-week range
  const vix52wLow = 10.84;
  const vix52wHigh = 28.42;
  const vixRangePct = ((vixValue - vix52wLow) / (vix52wHigh - vix52wLow)) * 100;

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="India VIX is the NSE volatility index. Connect OpenAlgo quotes endpoint for live VIX data. Values shown are representative." />

        {/* Main VIX card */}
        <Card className={`border ${zone.bg}`}>
          <CardContent className="pt-4 pb-4 px-5">
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs text-text-muted mb-1 flex items-center gap-1">
                  <ShieldAlert size={11} />
                  India VIX — Volatility Index
                </div>
                <div className={`text-4xl font-mono font-bold tabular-nums leading-none ${zone.color}`}>
                  {vixValue.toFixed(2)}
                </div>
                <div className={`text-sm font-mono tabular-nums mt-1 ${vixChange >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {vixChange >= 0 ? "+" : ""}{vixChange.toFixed(2)} ({vixChangePct.toFixed(2)}%)
                </div>
              </div>
              <Badge className={`text-xs px-2.5 py-1 border ${zone.bg} ${zone.color}`}>
                {zone.label}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* 52-week range bar */}
        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-4 pb-4 px-5">
            <div className="text-xs text-text-muted mb-3">52-Week Range</div>
            <div className="relative h-2 bg-surface-elevated rounded-full">
              <div
                className="absolute top-0 left-0 h-full bg-gradient-to-r from-emerald-600 to-red-600 rounded-full"
                style={{ width: `${vixRangePct}%` }}
              />
              <div
                className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-primary shadow"
                style={{ left: `calc(${vixRangePct}% - 6px)` }}
              />
            </div>
            <div className="flex justify-between mt-2 text-xs font-mono">
              <span className="text-emerald-400">{vix52wLow.toFixed(2)} (52W Low)</span>
              <span className="text-red-400">{vix52wHigh.toFixed(2)} (52W High)</span>
            </div>
          </CardContent>
        </Card>

        {/* What is India VIX */}
        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-4 pb-4 px-5 space-y-3">
            <div className="text-xs font-semibold text-text-primary">What is India VIX?</div>
            <p className="text-xs text-text-secondary leading-relaxed">
              India VIX (Volatility Index) is computed by NSE based on the order book of Nifty options.
              It represents the market&apos;s expectation of volatility over the next 30 calendar days.
              A higher VIX means higher expected volatility and uncertainty — traders call it the
              &quot;fear gauge&quot;.
            </p>
            <div className="space-y-2">
              {[
                { range: "Below 12", meaning: "Extreme complacency — markets at peak confidence", color: "text-blue-400" },
                { range: "12 – 16", meaning: "Low volatility — trending bull market", color: "text-emerald-400" },
                { range: "16 – 20", meaning: "Normal volatility — healthy market conditions", color: "text-amber-400" },
                { range: "20 – 25", meaning: "Elevated fear — watch for trend reversal", color: "text-orange-400" },
                { range: "25 – 30", meaning: "High fear — significant selling pressure", color: "text-red-400" },
                { range: "Above 30", meaning: "Panic zone — historically extreme buy signal", color: "text-red-500" },
              ].map((row) => (
                <div key={row.range} className="flex items-start gap-2 text-xs">
                  <span className={`font-mono font-medium w-20 shrink-0 ${row.color}`}>{row.range}</span>
                  <span className="text-text-secondary">{row.meaning}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Current interpretation */}
        <Card className={`border ${zone.bg}`}>
          <CardContent className="pt-3 pb-3 px-5">
            <div className={`text-xs font-semibold mb-1 ${zone.color}`}>Current Interpretation</div>
            <p className="text-xs text-text-secondary">{zone.description}</p>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Tab 6: Global Indices
// ---------------------------------------------------------------------------

function GlobalIndicesTab() {
  const [sortField, setSortField] = useState<keyof GlobalIndex>("change_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...GLOBAL_INDICES].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "desc" ? bv - av : av - bv;
      }
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });
  }, [sortField, sortDir]);

  const handleSort = (field: keyof GlobalIndex) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const headers: { label: string; field: keyof GlobalIndex }[] = [
    { label: "Index", field: "name" },
    { label: "Region", field: "region" },
    { label: "LTP", field: "ltp" },
    { label: "Change", field: "change" },
    { label: "Change %", field: "change_pct" },
  ];

  return (
    <div className="p-4">
      <DataNotice text="Global indices data requires a market data provider. Showing representative values at close. Live data during market hours requires Settings configuration." />

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {headers.map(({ label, field }) => (
                <TableHead
                  key={field}
                  className={["text-xs h-8 px-3 cursor-pointer select-none", sortField === field ? "text-primary" : "text-text-muted"].join(" ")}
                  onClick={() => handleSort(field)}
                >
                  {label}
                  {sortField === field && <ArrowUpDown size={9} className="inline ml-1 opacity-80" />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((idx) => (
              <TableRow key={idx.name} className="border-border-default hover:bg-surface-card">
                <TableCell className="px-3 py-2">
                  <div className="text-xs font-semibold text-text-primary">{idx.name}</div>
                </TableCell>
                <TableCell className="px-3 py-2">
                  <Badge className="text-xxs h-4 px-1.5 bg-surface-card text-text-secondary border-border-default">
                    {idx.region}
                  </Badge>
                </TableCell>
                <TableCell className="px-3 py-2 font-mono text-xs text-text-primary">
                  {idx.ltp.toLocaleString("en-US", { maximumFractionDigits: 2 })}
                  <span className="text-xxs text-text-muted ml-1">{idx.currency}</span>
                </TableCell>
                <TableCell className={`px-3 py-2 font-mono text-xs ${idx.change >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  {idx.change >= 0 ? "+" : ""}{idx.change.toFixed(2)}
                </TableCell>
                <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${idx.change_pct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                  <span className="flex items-center gap-1">
                    {idx.change_pct >= 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                    {idx.change_pct >= 0 ? "+" : ""}{idx.change_pct.toFixed(2)}%
                  </span>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 7: Participant OI
// ---------------------------------------------------------------------------

function ParticipantOITab() {
  function formatOI(v: number): string {
    if (v >= 10000000) return `${(v / 10000000).toFixed(2)} Cr`;
    if (v >= 100000) return `${(v / 100000).toFixed(1)} L`;
    if (v >= 1000) return `${(v / 1000).toFixed(0)} K`;
    return v.toString();
  }

  function getInterpretation(net: number): { label: string; color: string } {
    if (net > 50000) return { label: "Long Build Up", color: "text-emerald-400" };
    if (net > 10000) return { label: "Mildly Long", color: "text-emerald-400" };
    if (net > -10000) return { label: "Neutral", color: "text-text-secondary" };
    if (net > -50000) return { label: "Mildly Short", color: "text-red-400" };
    return { label: "Short Build Up", color: "text-red-400" };
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Participant-wise OI from NSE. Available after market hours. Live data during trading requires F&O data subscription." />

        {/* Index Futures OI */}
        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Index Futures" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long", "Short", "Net OI", "Interpretation"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const interp = getInterpretation(row.net_index_fut);
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2">
                        <span className="text-xs font-semibold text-primary">{row.participant}</span>
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-emerald-400">
                        {formatOI(row.long_index_fut)}
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-red-400">
                        {formatOI(row.short_index_fut)}
                      </TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(row.net_index_fut)}`}>
                        {row.net_index_fut >= 0 ? "+" : ""}{formatOI(Math.abs(row.net_index_fut))}
                      </TableCell>
                      <TableCell className="px-3 py-2">
                        <Badge className={`text-xs h-5 px-2 bg-transparent border ${interp.color === "text-emerald-400" ? "border-emerald-800 text-emerald-400" : interp.color === "text-red-400" ? "border-red-800 text-red-400" : "border-border-default text-text-secondary"}`}>
                          {interp.label}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>

        {/* Index Options OI */}
        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Index Options" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long Calls", "Short Calls", "Long Puts", "Short Puts", "Net"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const net = row.long_index_opt - row.short_index_opt;
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2">
                        <span className="text-xs font-semibold text-primary">{row.participant}</span>
                      </TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-emerald-400">{formatOI(row.long_index_opt)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-red-400">{formatOI(row.short_index_opt)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-emerald-400">{formatOI(Math.round(row.long_index_opt * 0.48))}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-red-400">{formatOI(Math.round(row.short_index_opt * 0.52))}</TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(net)}`}>
                        {net >= 0 ? "+" : ""}{formatOI(Math.abs(net))}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>

        {/* Stock Futures */}
        <div>
          <SectionLabel icon={Users} label="Participant-wise OI — Stock Futures" />
          <div className="rounded-md border border-border-default overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  {["Participant", "Long", "Short", "Net OI"].map((h) => (
                    <TableHead key={h} className="text-xs text-text-muted h-8 px-3">{h}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {PARTICIPANT_OI.map((row) => {
                  const net = row.long_stock_fut - row.short_stock_fut;
                  return (
                    <TableRow key={row.participant} className="border-border-default hover:bg-surface-card">
                      <TableCell className="px-3 py-2 text-xs font-semibold text-primary">{row.participant}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-emerald-400">{formatOI(row.long_stock_fut)}</TableCell>
                      <TableCell className="px-3 py-2 font-mono text-xs text-red-400">{formatOI(row.short_stock_fut)}</TableCell>
                      <TableCell className={`px-3 py-2 font-mono text-xs font-semibold ${netColor(net)}`}>
                        {net >= 0 ? "+" : ""}{formatOI(Math.abs(net))}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Tab 8: Delivery Data
// ---------------------------------------------------------------------------

function DeliveryDataTab() {
  const [sortField, setSortField] = useState<keyof DeliveryRow>("delivery_pct");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    return [...DELIVERY_DATA].sort((a, b) => {
      const av = a[sortField];
      const bv = b[sortField];
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "desc" ? bv - av : av - bv;
      }
      return sortDir === "desc"
        ? String(bv).localeCompare(String(av))
        : String(av).localeCompare(String(bv));
    });
  }, [sortField, sortDir]);

  const handleSort = (field: keyof DeliveryRow) => {
    if (sortField === field) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("desc"); }
  };

  const headers: { label: string; field: keyof DeliveryRow }[] = [
    { label: "Symbol", field: "symbol" },
    { label: "Open", field: "open" },
    { label: "High", field: "high" },
    { label: "Low", field: "low" },
    { label: "Close", field: "close" },
    { label: "Volume (L)", field: "volume_lakh" },
    { label: "Delivery %", field: "delivery_pct" },
  ];

  return (
    <div className="p-4">
      <DataNotice text="Delivery data from NSE bhavcopy. Available after 6 PM on trading days. High delivery % indicates institutional interest and conviction." />

      <div className="rounded-md border border-border-default overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow className="border-border-default hover:bg-transparent">
              {headers.map(({ label, field }) => (
                <TableHead
                  key={field}
                  className={["text-xs h-8 px-2 cursor-pointer select-none", sortField === field ? "text-primary" : "text-text-muted"].join(" ")}
                  onClick={() => handleSort(field)}
                >
                  {label}
                  {sortField === field && <ArrowUpDown size={9} className="inline ml-1 opacity-80" />}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((row) => {
              const changeAmt = row.close - row.open;
              const changePct = ((changeAmt / row.open) * 100);
              const deliveryColor = row.delivery_pct >= 60 ? "text-emerald-400" : row.delivery_pct >= 45 ? "text-amber-400" : "text-text-secondary";
              return (
                <TableRow key={row.symbol} className="border-border-default hover:bg-surface-card">
                  <TableCell className="px-2 py-1.5">
                    <div className="text-xs font-semibold font-mono text-primary">{row.symbol}</div>
                    <div className={`text-xs font-mono ${changePct >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                      {changePct >= 0 ? "+" : ""}{changePct.toFixed(2)}%
                    </div>
                  </TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{row.open.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-emerald-400">{row.high.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-red-400">{row.low.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-primary">{row.close.toFixed(1)}</TableCell>
                  <TableCell className="px-2 py-1.5 font-mono text-xs text-text-secondary">{row.volume_lakh.toFixed(1)}L</TableCell>
                  <TableCell className="px-2 py-1.5">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-surface-elevated rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${row.delivery_pct}%`,
                            backgroundColor: row.delivery_pct >= 60 ? "#10b981" : row.delivery_pct >= 45 ? "#f59e0b" : "#6b7280",
                          }}
                        />
                      </div>
                      <span className={`font-mono text-xs font-semibold w-10 text-right ${deliveryColor}`}>
                        {row.delivery_pct.toFixed(1)}%
                      </span>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center gap-4 mt-3 text-xs">
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-emerald-400 inline-block" /><span className="text-text-muted">High delivery ≥60%</span></div>
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-400 inline-block" /><span className="text-text-muted">Medium 45–60%</span></div>
        <div className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-gray-500 inline-block" /><span className="text-text-muted">Low &lt;45%</span></div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab 9: Correlation Matrix
// ---------------------------------------------------------------------------

function CorrelationMatrixTab() {
  function getCorrColor(v: number): { bg: string; text: string } {
    if (v >= 0.7) return { bg: "#064e3b", text: "#a7f3d0" };
    if (v >= 0.4) return { bg: "#065f46", text: "#6ee7b7" };
    if (v >= 0.1) return { bg: "#047857", text: "#d1fae5" };
    if (v >= -0.1) return { bg: "#1e1e2e", text: "#9090b0" };
    if (v >= -0.4) return { bg: "#7f1d1d", text: "#fca5a5" };
    if (v >= -0.7) return { bg: "#991b1b", text: "#f87171" };
    return { bg: "#450a0a", text: "#fca5a5" };
  }

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-4">
        <DataNotice text="Correlation computed from approximate 1-year rolling daily returns. Illustrative values — connect data source for live correlations." />

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className="text-xs text-text-muted font-normal px-2 py-1.5 text-left w-20" />
                {CORR_ASSETS.map((asset) => (
                  <th key={asset} className="text-xs text-text-secondary font-medium px-2 py-1.5 text-center">
                    {asset}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {CORR_MATRIX.map((row, ri) => (
                <tr key={CORR_ASSETS[ri]}>
                  <td className="text-xs text-text-secondary font-medium px-2 py-1 text-right pr-3">
                    {CORR_ASSETS[ri]}
                  </td>
                  {row.map((val, ci) => {
                    const colors = getCorrColor(val);
                    return (
                      <td key={ci} className="px-1 py-1">
                        <div
                          className="w-16 h-10 rounded flex items-center justify-center font-mono text-xs font-semibold transition-all hover:opacity-90 cursor-default"
                          style={{ backgroundColor: colors.bg, color: colors.text }}
                          title={`${CORR_ASSETS[ri]} vs ${CORR_ASSETS[ci]}: ${val.toFixed(2)}`}
                        >
                          {val === 1.0 ? "1.00" : val.toFixed(2)}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Legend */}
        <div className="space-y-2">
          <div className="text-xs text-text-muted font-medium">How to read:</div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            {[
              { range: "0.7 to 1.0", desc: "Strong positive — move together", bg: "#064e3b", text: "#a7f3d0" },
              { range: "0.4 to 0.7", desc: "Moderate positive correlation", bg: "#065f46", text: "#6ee7b7" },
              { range: "0.1 to 0.4", desc: "Weak positive correlation", bg: "#047857", text: "#d1fae5" },
              { range: "-0.1 to 0.1", desc: "Uncorrelated / neutral", bg: "#1e1e2e", text: "#9090b0" },
              { range: "-0.4 to -0.1", desc: "Weak negative correlation", bg: "#7f1d1d", text: "#fca5a5" },
              { range: "-1.0 to -0.4", desc: "Strong negative — move oppositely", bg: "#450a0a", text: "#fca5a5" },
            ].map((l) => (
              <div key={l.range} className="flex items-center gap-2">
                <span
                  className="w-8 h-5 rounded text-center font-mono text-xxs flex items-center justify-center shrink-0"
                  style={{ backgroundColor: l.bg, color: l.text }}
                >
                  {l.range.split(" ")[0]}
                </span>
                <span className="text-xs text-text-muted">{l.desc}</span>
              </div>
            ))}
          </div>
        </div>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-3 pb-3 px-4 space-y-2">
            <div className="text-xs font-semibold text-text-primary">Key Observations</div>
            <ul className="space-y-1.5 text-xs text-text-secondary">
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />VIX and Nifty have a strong negative correlation (-0.72). Rising VIX typically signals falling markets.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Gold and USD-INR are positively correlated (0.48). Rupee depreciation often drives gold prices higher in INR terms.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Nifty and USD-INR are negatively correlated (-0.62). FII outflows weaken the rupee and pressure equities simultaneously.</li>
              <li className="flex items-start gap-2"><ChevronRight size={11} className="text-primary mt-0.5 shrink-0" />Gold and Crude have a weak positive correlation (0.28), driven by common USD and geopolitical factors.</li>
            </ul>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}

// ---------------------------------------------------------------------------
// Tab 10: Announcements
// ---------------------------------------------------------------------------

const CATEGORY_COLORS: Record<string, string> = {
  "Board Meeting": "text-primary border-neutral-border",
  "Dividend": "text-emerald-400 border-emerald-800",
  "Debt": "text-amber-400 border-amber-800",
  "Compliance": "text-text-secondary border-border-default",
  "Appointment": "text-purple-400 border-purple-800",
  "Results": "text-cyan-400 border-cyan-800",
  "Buyback": "text-pink-400 border-pink-800",
  "Rating": "text-teal-400 border-teal-800",
  "Equity": "text-orange-400 border-orange-800",
};

function AnnouncementsTab() {
  const [filterCat, setFilterCat] = useState<string>("All");

  const categories = ["All", ...Array.from(new Set(ANNOUNCEMENTS.map((a) => a.category)))];

  const filtered = useMemo(() => {
    if (filterCat === "All") return ANNOUNCEMENTS;
    return ANNOUNCEMENTS.filter((a) => a.category === filterCat);
  }, [filterCat]);

  return (
    <div className="p-4">
      <DataNotice text="Corporate announcements from NSE/BSE. Live feed via data source. Showing representative structure." />

      {/* Category filter chips */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setFilterCat(cat)}
            className={[
              "text-xs px-2 py-0.5 rounded border transition-colors",
              filterCat === cat
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {cat}
          </button>
        ))}
        <span className="text-xs text-text-muted ml-auto self-center">
          {filtered.length} of {ANNOUNCEMENTS.length}
        </span>
      </div>

      <div className="space-y-2">
        {filtered.map((ann, i) => {
          const catCls = CATEGORY_COLORS[ann.category] ?? "text-text-secondary border-border-default";
          return (
            <Card key={i} className="bg-surface-card border-border-default hover:border-border-default transition-colors">
              <CardContent className="pt-3 pb-3 px-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-semibold font-mono text-primary">{ann.symbol}</span>
                      <Badge className={`text-xxs h-4 px-1.5 bg-transparent border ${catCls}`}>
                        {ann.category}
                      </Badge>
                      <Badge className="text-xxs h-4 px-1.5 bg-surface-elevated text-text-muted border-border-default">
                        {ann.exchange}
                      </Badge>
                    </div>
                    <p className="text-xs text-text-secondary leading-relaxed line-clamp-2">
                      {ann.subject}
                    </p>
                  </div>
                  <div className="text-xs text-text-muted font-mono shrink-0 pt-0.5">
                    {ann.date}
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
        {filtered.length === 0 && (
          <div className="text-center py-8 text-xs text-text-muted">
            No announcements in this category.
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar tab definitions
// ---------------------------------------------------------------------------

type TabId =
  | "breadth"
  | "fiidii"
  | "sectors"
  | "heatmap"
  | "vix"
  | "global"
  | "participantoi"
  | "delivery"
  | "correlation"
  | "announcements";

interface TabDef {
  id: TabId;
  label: string;
  icon: typeof Activity;
}

const TABS: TabDef[] = [
  { id: "breadth", label: "Market Breadth", icon: Activity },
  { id: "fiidii", label: "FII/DII Flows", icon: Globe },
  { id: "sectors", label: "Sector Rotation", icon: ArrowUpDown },
  { id: "heatmap", label: "Sector Heatmap", icon: Map },
  { id: "vix", label: "India VIX", icon: ShieldAlert },
  { id: "global", label: "Global Indices", icon: Zap },
  { id: "participantoi", label: "Participant OI", icon: Users },
  { id: "delivery", label: "Delivery Data", icon: Package },
  { id: "correlation", label: "Correlation Matrix", icon: Grid3X3 },
  { id: "announcements", label: "Announcements", icon: Megaphone },
];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

export default function MarketIntelligenceTool({ onClose }: Props) {
  const [activeTab, setActiveTab] = useState<TabId>("breadth");

  const tabContent: Record<TabId, React.ReactNode> = {
    breadth: <MarketBreadthTab />,
    fiidii: <FiiDiiFlowsTab />,
    sectors: <SectorRotationTab />,
    heatmap: <SectorHeatmapTab />,
    vix: <IndiaVixTab />,
    global: <GlobalIndicesTab />,
    participantoi: <ParticipantOITab />,
    delivery: <DeliveryDataTab />,
    correlation: <CorrelationMatrixTab />,
    announcements: <AnnouncementsTab />,
  };

  // Tabs that manage their own scroll (use ScrollArea internally)
  const selfScrollingTabs: TabId[] = ["breadth", "fiidii", "vix", "participantoi", "correlation"];

  const currentTab = TABS.find((t) => t.id === activeTab);

  return (
    <div className="h-full flex flex-col bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card shrink-0">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-primary" />
          <span className="font-heading font-bold text-lg text-text-primary">Market Intelligence</span>
          {currentTab && (
            <>
              <span className="text-text-disabled">/</span>
              <span className="text-xs text-text-secondary">{currentTab.label}</span>
            </>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text-primary transition-colors"
        >
          <X size={15} />
        </button>
      </div>

      {/* Body: sidebar + content */}
      <div className="flex flex-1 min-h-0">
        {/* Sidebar */}
        <div className="w-44 border-r border-border-default bg-surface-card shrink-0 overflow-y-auto py-1.5">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={[
                  "w-full flex items-center gap-2 px-3 py-2 font-heading font-medium text-xs transition-colors text-left",
                  isActive
                    ? "bg-neutral-bg/60 text-primary border-r-2 border-primary"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-elevated",
                ].join(" ")}
              >
                <Icon size={13} className="shrink-0" />
                <span className="truncate">{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Content area */}
        {selfScrollingTabs.includes(activeTab) ? (
          <div className="flex-1 min-h-0 overflow-hidden">
            {tabContent[activeTab]}
          </div>
        ) : (
          <ScrollArea className="flex-1">
            <div>{tabContent[activeTab]}</div>
          </ScrollArea>
        )}
      </div>
    </div>
  );
}
