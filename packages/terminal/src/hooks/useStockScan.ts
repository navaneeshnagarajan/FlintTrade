/**
 * useStockScan.ts
 *
 * TanStack Query hook for the stock screener endpoint.
 * Fetches fundamental data from GET /ft-api/v1/stocks/scan.
 * 5-minute stale time — fundamentals don't change frequently.
 */

import { useQuery } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StockFundamentals {
  symbol: string;
  name: string;
  exchange: string;
  market_cap: number;
  pe_ratio: number;
  pb_ratio: number;
  roe: number;
  roce: number;
  dividend_yield: number;
  sector: string;
}

export interface StockScanParams {
  sector?: string;
  min_market_cap?: number;
  max_pe?: number;
  sort_by?: string;
  limit?: number;
}

interface StockScanResponse {
  status: string;
  data: {
    stocks: StockFundamentals[];
    sectors: string[];
    count: number;
  };
}

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

function getBase(): string {
  // In dev mode, Vite proxy routes /ft-api/* → http://127.0.0.1:5100/*
  return import.meta.env.DEV ? "/ft-api" : "";
}

async function fetchStockScan(
  params: StockScanParams,
): Promise<{ stocks: StockFundamentals[]; sectors: string[] }> {
  const searchParams = new URLSearchParams();

  if (params.sector) searchParams.set("sector", params.sector);
  if (params.min_market_cap !== undefined)
    searchParams.set("min_market_cap", String(params.min_market_cap));
  if (params.max_pe !== undefined)
    searchParams.set("max_pe", String(params.max_pe));
  if (params.sort_by) searchParams.set("sort_by", params.sort_by);
  if (params.limit !== undefined)
    searchParams.set("limit", String(params.limit));

  const qs = searchParams.toString();
  const url = `${getBase()}/v1/stocks/scan${qs ? `?${qs}` : ""}`;

  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Stock scan failed: HTTP ${resp.status}`);
  }

  const json = (await resp.json()) as StockScanResponse;
  if (json.status === "error") {
    throw new Error("Stock scan returned an error");
  }

  return { stocks: json.data.stocks, sectors: json.data.sectors };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useStockScan(params: StockScanParams = {}) {
  return useQuery({
    queryKey: ["stocks", "scan", params],
    queryFn: () => fetchStockScan(params),
    staleTime: 5 * 60 * 1000, // 5 minutes
    retry: 1,
  });
}
