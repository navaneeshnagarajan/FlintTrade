/**
 * useTaxReport.ts
 *
 * TanStack Query hooks for the tax report API endpoints.
 * Fetches from GET /ft-api/v1/tax/summary and /ft-api/v1/tax/report.
 */

import { useQuery } from "@tanstack/react-query";
import { TaxSummarySchema, TaxReportSchema } from "@/lib/schemas/ftApi";
import type { TaxSummary, TaxReport, TaxSegment, TaxSegmentTrade } from "@/lib/schemas/ftApi";

// Re-export inferred types for consumers that previously imported from this file.
export type { TaxSummary, TaxReport, TaxSegment, TaxSegmentTrade };

// ─── Fetchers ────────────────────────────────────────────────────────────────

async function fetchTaxSummary(fy: string): Promise<TaxSummary> {
  const res = await fetch(`/ft-api/v1/tax/summary?fy=${encodeURIComponent(fy)}`);
  if (!res.ok) throw new Error(`Tax summary request failed: ${res.status}`);
  const raw: unknown = await res.json();
  const result = TaxSummarySchema.safeParse(raw);
  if (!result.success) {
    console.error("[useTaxReport] /tax/summary shape mismatch:", result.error.issues);
    throw new Error("Tax summary response did not match expected shape");
  }
  return result.data.data;
}

async function fetchTaxReport(fy: string): Promise<TaxReport> {
  const res = await fetch(`/ft-api/v1/tax/report?fy=${encodeURIComponent(fy)}`);
  if (!res.ok) throw new Error(`Tax report request failed: ${res.status}`);
  const raw: unknown = await res.json();
  const result = TaxReportSchema.safeParse(raw);
  if (!result.success) {
    console.error("[useTaxReport] /tax/report shape mismatch:", result.error.issues);
    throw new Error("Tax report response did not match expected shape");
  }
  return result.data.data;
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
