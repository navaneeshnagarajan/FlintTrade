/**
 * useTaxReport.ts
 *
 * TanStack Query hooks for the tax report API endpoints.
 * Fetches from GET /ft-api/v1/tax/summary and /ft-api/v1/tax/report.
 */

import { useQuery } from "@tanstack/react-query";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface TaxSummary {
  fy: string;
  equity_ltcg: number;
  equity_stcg: number;
  intraday_pnl: number;
  fno_pnl: number;
  commodity_pnl: number;
  stt_paid: number;
  turnover: number;
  tax_liability_estimated: number;
  ltcg_exemption_used: number;
  needs_audit: boolean;
  trade_count: number;
}

export interface TaxSegmentTrade {
  date: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: number;
  price: number;
  buy_price: number;
  pnl: number;
  holding_period_days: number;
}

export interface TaxSegment {
  trade_count: number;
  pnl: number;
  trades: TaxSegmentTrade[];
}

export interface TaxReport {
  summary: TaxSummary;
  segments: Record<string, TaxSegment>;
}

// ─── Fetchers ────────────────────────────────────────────────────────────────

async function fetchTaxSummary(fy: string): Promise<TaxSummary> {
  const res = await fetch(`/ft-api/v1/tax/summary?fy=${encodeURIComponent(fy)}`);
  if (!res.ok) throw new Error(`Tax summary request failed: ${res.status}`);
  const json = (await res.json()) as { status: string; data: TaxSummary };
  return json.data;
}

async function fetchTaxReport(fy: string): Promise<TaxReport> {
  const res = await fetch(`/ft-api/v1/tax/report?fy=${encodeURIComponent(fy)}`);
  if (!res.ok) throw new Error(`Tax report request failed: ${res.status}`);
  const json = (await res.json()) as { status: string; data: TaxReport };
  return json.data;
}

// ─── Hooks ───────────────────────────────────────────────────────────────────

export function useTaxSummary(fy: string) {
  return useQuery<TaxSummary>({
    queryKey: ["tax-summary", fy],
    queryFn: () => fetchTaxSummary(fy),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useTaxReport(fy: string) {
  return useQuery<TaxReport>({
    queryKey: ["tax-report", fy],
    queryFn: () => fetchTaxReport(fy),
    staleTime: 5 * 60 * 1000,
  });
}
