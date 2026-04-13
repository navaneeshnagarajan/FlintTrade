import type React from "react";

export interface SectorReturn {
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

export interface MarketBreadth {
  advances: number;
  declines: number;
  unchanged: number;
  total: number;
  newHighs: number;
  newLows: number;
  label: string;
}

export interface FiiDiiRow {
  date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
}

export interface GlobalIndex {
  name: string;
  region: string;
  ltp: number;
  change: number;
  change_pct: number;
  currency: string;
}

export interface ParticipantOI {
  participant: string;
  long_index_fut: number;
  short_index_fut: number;
  long_index_opt: number;
  short_index_opt: number;
  long_stock_fut: number;
  short_stock_fut: number;
  net_index_fut: number;
}

export interface DeliveryRow {
  symbol: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume_lakh: number;
  delivery_pct: number;
  series: string;
}

export interface Announcement {
  symbol: string;
  exchange: string;
  subject: string;
  date: string;
  category: string;
}

export const TIMEFRAMES = ["1D", "1W", "1M", "3M", "6M", "1Y"] as const;
export type TF = (typeof TIMEFRAMES)[number];

export const TF_KEY: Record<TF, keyof SectorReturn> = {
  "1D": "returns_1d",
  "1W": "returns_1w",
  "1M": "returns_1m",
  "3M": "returns_3m",
  "6M": "returns_6m",
  "1Y": "returns_1y",
};

export const LIVE_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"] as const;
export type LiveSymbol = (typeof LIVE_SYMBOLS)[number];

export interface LiveSelectorState {
  symbol: LiveSymbol;
  exchange: string;
  expiry: string | null;
  expiries: string[];
  expiryLoading: boolean;
}

export type OIBuildUp = "Long Build Up" | "Short Build Up" | "Long Unwinding" | "Short Covering" | "Neutral";

import type { OIProfileEntry } from "@/types/api";
export type StrikeEntry = { ce: OIProfileEntry | null; pe: OIProfileEntry | null };

export type TabId =
  | "breadth"
  | "fiidii"
  | "sectors"
  | "heatmap"
  | "vix"
  | "global"
  | "participantoi"
  | "delivery"
  | "correlation"
  | "announcements"
  | "gex"
  | "ivsmile"
  | "maxpain"
  | "oiprofile";

export interface TabDef {
  id: TabId;
  label: string;
  icon: React.ElementType;
}

