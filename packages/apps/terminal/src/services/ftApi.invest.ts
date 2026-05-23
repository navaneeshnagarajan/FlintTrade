import { get } from "./ftApi.helpers";

export interface MutualFundEntry {
  scheme_code: number;
  scheme_name: string;
  amc: string;
  category: string;
  nav: number;
  nav_date: string;
  scheme_type: string;
}

export interface MFSearchResponse {
  query: string;
  count: number;
  funds: MutualFundEntry[];
}

export interface MFNAVResponse {
  fund: MutualFundEntry;
}

export interface MFCategoriesResponse {
  count: number;
  categories: string[];
}

export interface IpoEntry {
  name: string;
  symbol: string;
  issue_size: string;
  price_band: string;
  lot_size: number;
  open_date: string;
  close_date: string;
  listing_date: string;
  status: string;
  listing_gain?: number;
}

export interface IpoResponse {
  ipos: IpoEntry[];
  last_updated: string;
}

export const searchMutualFunds = (query: string, category?: string, limit?: number) => {
  const params = new URLSearchParams({ q: query });
  if (category) params.set("category", category);
  if (limit !== undefined) params.set("limit", String(limit));
  return get<MFSearchResponse>("mf/search?" + params.toString());
};

export const getMutualFundNAV = (schemeCode: number) =>
  get<MFNAVResponse>("mf/nav/" + String(schemeCode));

export const getMFCategories = () =>
  get<MFCategoriesResponse>("mf/categories");

export const getUpcomingIPOs = () => get<IpoResponse>("ipo/upcoming");
export const getRecentIPOs = () => get<IpoResponse>("ipo/recent");
