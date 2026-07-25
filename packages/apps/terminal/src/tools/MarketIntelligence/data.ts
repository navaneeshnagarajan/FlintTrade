import {
  Activity,
  ArrowUpDown,
  Flame,
  Globe,
  Grid3X3,
  Layers,
  LineChart,
  Map as MapIcon,
  Megaphone,
  Package,
  ShieldAlert,
  Target,
  Users,
  Zap,
} from "lucide-react";
import type {
  Announcement,
  DeliveryRow,
  FiiDiiRow,
  GlobalIndex,
  MarketBreadth,
  OIBuildUp,
  ParticipantOI,
  SectorReturn,
  TabDef,
  TabId,
} from "./types";

export const INDIA_SECTORS: SectorReturn[] = [
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

export const BREADTH_DATA: MarketBreadth[] = [
  { label: "NSE 500", advances: 312, declines: 164, unchanged: 24, total: 500, newHighs: 42, newLows: 8 },
  { label: "BSE 500", advances: 298, declines: 178, unchanged: 24, total: 500, newHighs: 38, newLows: 12 },
  { label: "Nifty 50", advances: 32, declines: 17, unchanged: 1, total: 50, newHighs: 6, newLows: 2 },
];

export const FII_DII_DATA: FiiDiiRow[] = [
  { date: "2024-12-27", fii_buy: 12450, fii_sell: 9820, fii_net: 2630, dii_buy: 8940, dii_sell: 7120, dii_net: 1820 },
  { date: "2024-12-26", fii_buy: 9840, fii_sell: 11250, fii_net: -1410, dii_buy: 9820, dii_sell: 7840, dii_net: 1980 },
  { date: "2024-12-24", fii_buy: 14820, fii_sell: 10490, fii_net: 4330, dii_buy: 7640, dii_sell: 8120, dii_net: -480 },
  { date: "2024-12-23", fii_buy: 8920, fii_sell: 13450, fii_net: -4530, dii_buy: 10240, dii_sell: 7840, dii_net: 2400 },
  { date: "2024-12-20", fii_buy: 11240, fii_sell: 9870, fii_net: 1370, dii_buy: 8490, dii_sell: 9120, dii_net: -630 },
  { date: "2024-12-19", fii_buy: 7840, fii_sell: 14280, fii_net: -6440, dii_buy: 11240, dii_sell: 6480, dii_net: 4760 },
  { date: "2024-12-18", fii_buy: 15640, fii_sell: 8920, fii_net: 6720, dii_buy: 7840, dii_sell: 9120, dii_net: -1280 },
];

export const GLOBAL_INDICES: GlobalIndex[] = [
  { name: "S&P 500", region: "USA", ltp: 4782.82, change: 24.18, change_pct: 0.51, currency: "USD" },
  { name: "NASDAQ 100", region: "USA", ltp: 16832.92, change: -42.14, change_pct: -0.25, currency: "USD" },
  { name: "Dow Jones", region: "USA", ltp: 37440.67, change: 158.11, change_pct: 0.42, currency: "USD" },
  { name: "FTSE 100", region: "UK", ltp: 7648.30, change: -18.20, change_pct: -0.24, currency: "GBP" },
  { name: "Nikkei 225", region: "Japan", ltp: 33431.51, change: 442.80, change_pct: 1.34, currency: "JPY" },
  { name: "Hang Seng", region: "Hong Kong", ltp: 16524.33, change: -132.60, change_pct: -0.80, currency: "HKD" },
  { name: "DAX", region: "Germany", ltp: 16751.48, change: 84.20, change_pct: 0.50, currency: "EUR" },
  { name: "Shanghai Comp.", region: "China", ltp: 2962.28, change: -8.44, change_pct: -0.28, currency: "CNY" },
  { name: "GIFT Nifty", region: "India (NSE IX)", ltp: 21842.0, change: 108.5, change_pct: 0.50, currency: "USD" },
];

export const PARTICIPANT_OI: ParticipantOI[] = [
  { participant: "FII", long_index_fut: 284120, short_index_fut: 312480, long_index_opt: 8420180, short_index_opt: 6284200, long_stock_fut: 142840, short_stock_fut: 128640, net_index_fut: -28360 },
  { participant: "Pro", long_index_fut: 198420, short_index_fut: 184200, long_index_opt: 4284200, short_index_opt: 6420480, long_stock_fut: 84200, short_stock_fut: 92840, net_index_fut: 14220 },
  { participant: "DII", long_index_fut: 48200, short_index_fut: 24800, long_index_opt: 248200, short_index_opt: 184200, long_stock_fut: 42840, short_stock_fut: 28400, net_index_fut: 23400 },
  { participant: "Client", long_index_fut: 420840, short_index_fut: 428480, long_index_opt: 2148200, short_index_opt: 2212200, long_stock_fut: 284200, short_stock_fut: 302200, net_index_fut: -7640 },
];

export const DELIVERY_DATA: DeliveryRow[] = [
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

export const ANNOUNCEMENTS: Announcement[] = [
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

export const CORR_ASSETS = ["VIX", "Nifty", "Gold", "Crude", "USD-INR"];
export const CORR_MATRIX: number[][] = [
  [ 1.00, -0.72,  0.18,  0.12,  0.34],
  [-0.72,  1.00, -0.08,  0.42, -0.62],
  [ 0.18, -0.08,  1.00,  0.28,  0.48],
  [ 0.12,  0.42,  0.28,  1.00, -0.18],
  [ 0.34, -0.62,  0.48, -0.18,  1.00],
];

export const CATEGORY_COLORS: Record<string, string> = {
  "Board Meeting": "text-primary border-neutral-border",
  "Dividend": "text-profit border-bullish-border",
  "Debt": "text-warning border-atm-border",
  "Compliance": "text-text-secondary border-border-default",
  "Appointment": "text-purple-400 border-purple-800",
  "Results": "text-cyan-400 border-cyan-800",
  "Buyback": "text-pink-400 border-pink-800",
  "Rating": "text-teal-400 border-teal-800",
  "Equity": "text-orange-400 border-orange-800",
};

export const OI_BUILDUP_COLORS: Record<OIBuildUp, string> = {
  "Long Build Up": "text-emerald-400 border-emerald-800",
  "Short Build Up": "text-red-400 border-red-800",
  "Long Unwinding": "text-orange-400 border-orange-800",
  "Short Covering": "text-sky-400 border-sky-800",
  "Neutral": "text-text-muted border-border-default",
};

/**
 * Tabs whose content is static illustrative data.
 *
 * `fiidii` is deliberately NOT here: it fetches `getFiiDiiData(10)` and renders
 * real rows, hiding its own DataNotice when the payload is live. Listing it
 * made the tool header stamp a "Sample Data" badge over genuinely live
 * figures — a badge that lies in the safe direction is still a badge that
 * lies, and it trains the operator to ignore the one that matters.
 */
export const SAMPLE_DATA_TABS: TabId[] = [
  "breadth",
  "sectors",
  "heatmap",
  "vix",
  "global",
  "participantoi",
  "delivery",
  "correlation",
  "announcements",
];

export const TABS: TabDef[] = [
  { id: "breadth", label: "Market Breadth", icon: Activity },
  { id: "fiidii", label: "FII/DII Flows", icon: Globe },
  { id: "sectors", label: "Sector Rotation", icon: ArrowUpDown },
  { id: "heatmap", label: "Sector Heatmap", icon: MapIcon },
  { id: "vix", label: "India VIX", icon: ShieldAlert },
  { id: "global", label: "Global Indices", icon: Zap },
  { id: "participantoi", label: "Participant OI", icon: Users },
  { id: "delivery", label: "Delivery Data", icon: Package },
  { id: "correlation", label: "Correlation Matrix", icon: Grid3X3 },
  { id: "announcements", label: "Announcements", icon: Megaphone },
  { id: "gex", label: "GEX", icon: Flame },
  { id: "ivsmile", label: "IV Smile", icon: LineChart },
  { id: "maxpain", label: "Max Pain", icon: Target },
  { id: "oiprofile", label: "OI Profile", icon: Layers },
];
