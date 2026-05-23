/**
 * ftApi.ts — Runtime Zod schemas for /ft-api/v1/* responses.
 *
 * Every schema models the actual JSON the Python backend emits, verified
 * against the route handlers in packages/PKGNAME/src/PKGNAME_routes.py.
 *
 * Consumers: use Schema.safeParse(json) instead of `as Foo` casts.
 * The inferred TS types are exported alongside each schema so call sites
 * need not maintain a separate hand-written interface.
 *
 * ".passthrough()" is applied where the backend may include extra fields
 * (e.g. from model_dump()) that the frontend does not consume.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Shared envelope
// ---------------------------------------------------------------------------

/** Error envelope returned by every backend endpoint on failure. */
export const ErrorEnvelopeSchema = z.object({
  status: z.literal("error"),
  message: z.string(),
  code: z.string().optional(),
});
export type ErrorEnvelope = z.infer<typeof ErrorEnvelopeSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/auth/status
// packages/core/core/src/auth_routes.py → auth_status()
// { status: "success", data: { is_setup: bool, is_locked: bool } }
// ---------------------------------------------------------------------------

export const AuthStatusSchema = z.object({
  status: z.string(),
  data: z
    .object({
      is_setup: z.boolean(),
      is_locked: z.boolean(),
    })
    .passthrough()
    .optional(),
});
export type AuthStatus = z.infer<typeof AuthStatusSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/tax/summary — packages/core/data/src/tax_routes.py → tax_summary()
// { status: "success", data: { fy, equity_ltcg, ..., needs_audit, trade_count } }
//
// GET /ft-api/v1/tax/report  — tax_report()
// { status: "success", data: <report dict> }
// ---------------------------------------------------------------------------

const TaxSummaryDataSchema = z
  .object({
    fy: z.string(),
    equity_ltcg: z.number(),
    equity_stcg: z.number(),
    intraday_pnl: z.number(),
    fno_pnl: z.number(),
    commodity_pnl: z.number(),
    stt_paid: z.number(),
    turnover: z.number(),
    tax_liability_estimated: z.number(),
    ltcg_exemption_used: z.number(),
    needs_audit: z.boolean(),
    trade_count: z.number(),
  })
  .passthrough();

export const TaxSummarySchema = z.object({
  status: z.string(),
  data: TaxSummaryDataSchema,
});
export type TaxSummary = z.infer<typeof TaxSummaryDataSchema>;

const TaxSegmentTradeSchema = z
  .object({
    date: z.string(),
    symbol: z.string(),
    exchange: z.string(),
    action: z.string(),
    quantity: z.number(),
    price: z.number(),
    buy_price: z.number(),
    pnl: z.number(),
    holding_period_days: z.number(),
  })
  .passthrough();

const TaxSegmentSchema = z
  .object({
    trade_count: z.number(),
    pnl: z.number(),
    trades: z.array(TaxSegmentTradeSchema),
  })
  .passthrough();

export const TaxReportSchema = z.object({
  status: z.string(),
  data: z
    .object({
      summary: TaxSummaryDataSchema,
      segments: z.record(z.string(), TaxSegmentSchema),
    })
    .passthrough(),
});
export type TaxReport = z.infer<typeof TaxReportSchema>["data"];
export type TaxSegment = z.infer<typeof TaxSegmentSchema>;
export type TaxSegmentTrade = z.infer<typeof TaxSegmentTradeSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/stocks/scan
// packages/services/screener/src/stock_routes.py → stock_scan()
// { status: "success", data: { stocks: [...], sectors: [...], count: N } }
// ---------------------------------------------------------------------------

const StockFundamentalsSchema = z
  .object({
    symbol: z.string(),
    name: z.string(),
    exchange: z.string(),
    market_cap: z.number(),
    pe_ratio: z.number(),
    pb_ratio: z.number(),
    roe: z.number(),
    roce: z.number(),
    dividend_yield: z.number(),
    sector: z.string(),
  })
  .passthrough();

export const StockScanResponseSchema = z.object({
  status: z.string(),
  data: z
    .object({
      stocks: z.array(StockFundamentalsSchema),
      sectors: z.array(z.string()),
      count: z.number(),
    })
    .passthrough(),
});
export type StockScanResponse = z.infer<typeof StockScanResponseSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/sandbox/status (proxied via /ft-api/v1/sandbox/capital)
// packages/core/data/src/sandbox_routes.py → get_capital()
// { status: "success", data: { capital: number | object } }
//
// SandboxControls uses /ft-api/v1/sandbox/status (different route definition
// in engine/src/sandbox_routes.py).  The shape expected by the UI is:
// { capital, initial_capital, pnl, trades_count }
// ---------------------------------------------------------------------------

export const SandboxStatusSchema = z.object({
  status: z.string(),
  data: z
    .object({
      capital: z.number(),
      initial_capital: z.number().optional().default(0),
      pnl: z.number().optional().default(0),
      trades_count: z.number().optional().default(0),
    })
    .passthrough(),
});
export type SandboxStatus = z.infer<typeof SandboxStatusSchema>["data"];

// ---------------------------------------------------------------------------
// GET /ft-api/v1/docs/search?q=…
// packages/core/core/src/docs_search_routes.py → search_docs()
// { query: str, results: [...], total: N }
// ---------------------------------------------------------------------------

const DocSearchResultSchema = z
  .object({
    path: z.string(),
    title: z.string(),
    snippet: z.string(),
    score: z.number(),
  })
  .passthrough();

export const DocsSearchResponseSchema = z.object({
  query: z.string(),
  results: z.array(DocSearchResultSchema),
  total: z.number(),
});
export type DocsSearchResponse = z.infer<typeof DocsSearchResponseSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/breadth/current
// packages/services/screener/src/breadth_routes.py → breadth_current()
// { status: "success", is_sample_data: bool, data: BreadthData (snake_case) }
//
// The frontend MarketBreadthWidget fetches /ft-api/v1/breadth (no /current)
// and expects camelCase shape — the widget treats the whole response as
// BreadthData directly.  We validate the actual backend shape here.
// ---------------------------------------------------------------------------

export const BreadthDataSchema = z
  .object({
    date: z.string(),
    advances: z.number(),
    declines: z.number(),
    unchanged: z.number(),
    new_highs: z.number().optional().default(0),
    new_lows: z.number().optional().default(0),
    ad_ratio: z.number().optional().default(1),
    ad_line: z.number().optional().default(0),
    mcclellan_oscillator: z.number().optional().default(0),
    breadth_thrust: z.number().optional().default(0),
  })
  .passthrough();

export const BreadthResponseSchema = z.object({
  status: z.string(),
  is_sample_data: z.boolean().optional(),
  data: BreadthDataSchema,
});
export type BreadthData = z.infer<typeof BreadthDataSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/v1/admin/system
// packages/core/core/src/admin_routes.py → admin_system()
// packages/core/core/src/system_metrics.py → SystemMetrics.to_dict() (model_dump)
// Fields are FLAT (no nested network_io — backend uses network_bytes_sent/recv).
// ---------------------------------------------------------------------------

export const SystemMetricsResponseSchema = z.object({
  status: z.string(),
  data: z
    .object({
      cpu_percent: z.number(),
      memory_percent: z.number(),
      memory_used_gb: z.number(),
      memory_total_gb: z.number(),
      disk_percent: z.number(),
      disk_used_gb: z.number(),
      disk_total_gb: z.number(),
      uptime_seconds: z.number(),
      process_count: z.number(),
      network_bytes_sent: z.number().optional().default(0),
      network_bytes_recv: z.number().optional().default(0),
      psutil_available: z.boolean().optional(),
      // Allow extra fields the frontend NetworkIO-nested version expects
    })
    .passthrough(),
});
export type SystemMetricsResponse = z.infer<typeof SystemMetricsResponseSchema>;

// ---------------------------------------------------------------------------
// GET /ft-api/api/v1/advisor/status
// packages/services/ai/src/advisor_routes.py → advisor_status()
// { status: "success", data: { configured: bool, provider: str, model: str } }
// ---------------------------------------------------------------------------

export const AdvisorStatusDataSchema = z.object({
  configured: z.boolean(),
  provider: z.string(),
  model: z.string(),
});

export const AdvisorStatusResponseSchema = z.object({
  status: z.string(),
  data: AdvisorStatusDataSchema.optional(),
});
export type AdvisorStatusData = z.infer<typeof AdvisorStatusDataSchema>;
export type AdvisorStatusResponse = z.infer<typeof AdvisorStatusResponseSchema>;

// ---------------------------------------------------------------------------
// POST /ft-api/api/v1/advisor
// packages/services/ai/src/advisor_routes.py → advisor_chat()
// { status: "success" | "error", data?: { response: str }, message?: str }
// ---------------------------------------------------------------------------

export const AdvisorResponseSchema = z.object({
  status: z.union([z.literal("success"), z.literal("error")]),
  data: z
    .object({
      response: z.string(),
    })
    .optional(),
  message: z.string().optional(),
});
export type AdvisorResponse = z.infer<typeof AdvisorResponseSchema>;
