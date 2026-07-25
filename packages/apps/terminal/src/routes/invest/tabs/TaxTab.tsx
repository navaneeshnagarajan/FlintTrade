/**
 * TaxTab.tsx — Indicative tax P&L report for Indian traders
 *
 * Summary cards: LTCG, STCG, Intraday P&L, F&O P&L, Commodity P&L,
 * Total STT, Estimated Tax Liability, and audit assessment indicator.
 * Segment breakdown table with per-trade details.
 * Turnover calculation and FY selector.
 *
 * Data source: GET /ft-api/v1/tax/summary, /ft-api/v1/tax/report
 */

import type { ReactNode } from "react";
import { useState, useMemo } from "react";
import {
  Receipt,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  RefreshCw,
  Calendar,
  FileText,
  Landmark,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  ChevronDown,
  ChevronUp,
  Download,
  Printer,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { GlossaryTooltip } from "@/components/ui/GlossaryTooltip";
import { DemoBanner } from "@/components/ui/DemoBanner";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useTaxSummary, useTaxReport, type TaxSummary, type TaxSegment } from "@/hooks/useTaxReport";
import { exportToCSV, printCurrentView } from "@/lib/exportUtils";
import { formatINR, formatINRCompact } from "../formatters";

type AuditAssessment = "incomplete" | "required";

type TaxSummaryWithMethodology = TaxSummary & {
  audit_assessment: AuditAssessment;
  audit_assessment_reason: string;
  tax_estimate_methodology: string;
  stt_methodology: string;
  stt_rate_provenance: string;
};

export function getFinancialYearOptions(asOf = new Date()) {
  const currentStartYear = asOf.getMonth() < 3 ? asOf.getFullYear() - 1 : asOf.getFullYear();
  return [currentStartYear, currentStartYear - 1].map((startYear) => {
    const value = `${startYear}-${String(startYear + 1).slice(-2)}`;
    return { value, label: `FY ${value}` };
  });
}

// ─── Demo data ────────────────────────────────────────────────────────────────

function getDemoTaxSummary(fy: string): TaxSummaryWithMethodology {
  return {
    fy,
    equity_ltcg: 45000,
    equity_stcg: 28000,
    intraday_pnl: -12000,
    fno_pnl: 185000,
    commodity_pnl: 8500,
    stt_paid: 4200,
    turnover: 8500000,
    tax_liability_estimated: 62000,
    ltcg_exemption_used: 45000,
    needs_audit: false,
    audit_assessment: "incomplete",
    audit_assessment_reason: "Complete taxpayer-specific records are not available.",
    tax_estimate_methodology:
      "Indicative estimate from realised P&L only: equity LTCG and STCG use the modelled capital-gains rates, while net positive business income uses an illustrative 30% slab-rate assumption.",
    stt_methodology:
      "STT is calculated per transaction date on the applicable taxable value; the existing equity treatment is unchanged.",
    stt_rate_provenance:
      "Derivative sell-side option/futures rates are 0.0625%/0.0125% before 1 October 2024, 0.1%/0.02% from 1 October 2024 through 31 March 2026, and 0.15%/0.05% from 1 April 2026; the effective-date changes follow the Finance (No. 2) Act, 2024 and Finance Act, 2026 schedules.",
    trade_count: 342,
    is_sample_data: true,
    data_source: "sample",
  };
}

// ─── Constants ───────────────────────────────────────────────────────────────

/** Human-readable segment labels and descriptions. */
const SEGMENT_META: Record<string, { label: string; description: string; taxRule: string }> = {
  equity_ltcg: {
    label: "Equity LTCG",
    description: "Held > 12 months",
    taxRule: "12.5% above 1.25L exemption",
  },
  equity_stcg: {
    label: "Equity STCG",
    description: "Held < 12 months",
    taxRule: "20% flat",
  },
  equity_intraday: {
    label: "Intraday",
    description: "Squared off same day",
    taxRule: "Slab rate (business income)",
  },
  futures: {
    label: "Futures",
    description: "Index & stock futures",
    taxRule: "Slab rate (business income)",
  },
  options: {
    label: "Options",
    description: "Index & stock options",
    taxRule: "Slab rate (business income)",
  },
  commodity: {
    label: "Commodity",
    description: "MCX trades",
    taxRule: "Slab rate (business income)",
  },
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function PnLValue({ value, compact = false }: { value: number; compact?: boolean }) {
  const positive = value >= 0;
  const formatter = compact ? formatINRCompact : formatINR;
  return (
    <span
      className={cn(
        "font-mono tabular-nums font-semibold",
        positive ? "text-profit" : "text-loss",
      )}
    >
      {positive ? "+" : ""}
      {formatter(value)}
    </span>
  );
}

function SummaryCard({
  label,
  value,
  icon: Icon,
  subtitle,
  variant = "default",
}: {
  label: ReactNode;
  value: number;
  icon: typeof TrendingUp;
  subtitle?: string;
  variant?: "default" | "profit" | "loss" | "warning" | "info";
}) {
  const bgClass = {
    default: "bg-surface-elevated",
    profit: "bg-bullish-bg",
    loss: "bg-bearish-bg",
    warning: "bg-yellow-500/10",
    info: "bg-blue-500/10",
  }[variant];

  const iconClass = {
    default: "text-text-secondary",
    profit: "text-profit",
    loss: "text-loss",
    warning: "text-yellow-500",
    info: "text-blue-500",
  }[variant];

  return (
    <GlassCard className="p-4 gap-2">
      <div className="flex items-center gap-2">
        <div className={cn("size-7 rounded-lg flex items-center justify-center", bgClass)}>
          <Icon className={cn("size-3.5", iconClass)} />
        </div>
        <span className="text-xxs text-text-muted uppercase tracking-wider">{label}</span>
      </div>
      <div className="text-xl font-mono font-bold tabular-nums">
        <PnLValue value={value} compact />
      </div>
      {subtitle && <p className="text-xs text-text-muted">{subtitle}</p>}
    </GlassCard>
  );
}

function SegmentBreakdownRow({
  segmentKey,
  segment,
}: {
  segmentKey: string;
  segment: TaxSegment;
}) {
  const [expanded, setExpanded] = useState(false);
  const meta = SEGMENT_META[segmentKey];
  if (!meta || segment.trade_count === 0) return null;

  return (
    <>
      <TableRow
        className="cursor-pointer hover:bg-surface-elevated/50"
        onClick={() => setExpanded(!expanded)}
      >
        <TableCell className="font-medium text-text-primary">
          <div className="flex items-center gap-2">
            {expanded ? (
              <ChevronUp className="size-3.5 text-text-muted" />
            ) : (
              <ChevronDown className="size-3.5 text-text-muted" />
            )}
            {meta.label}
          </div>
        </TableCell>
        <TableCell className="text-text-muted text-xs">{meta.description}</TableCell>
        <TableCell className="text-right font-mono tabular-nums">{segment.trade_count}</TableCell>
        <TableCell className="text-right">
          <PnLValue value={segment.pnl} />
        </TableCell>
        <TableCell className="text-xs text-text-muted">{meta.taxRule}</TableCell>
      </TableRow>
      {expanded &&
        segment.trades
          .filter((t) => t.action === "SELL")
          .map((t, i) => (
            <TableRow key={`${segmentKey}-${i}`} className="bg-surface-card/50">
              <TableCell className="pl-10 text-xs text-text-secondary">{t.symbol}</TableCell>
              <TableCell className="text-xs text-text-muted">{t.date}</TableCell>
              <TableCell className="text-right font-mono tabular-nums text-xs">
                {t.quantity}
              </TableCell>
              <TableCell className="text-right">
                <span
                  className={cn(
                    "font-mono tabular-nums text-xs",
                    t.pnl >= 0 ? "text-profit" : "text-loss",
                  )}
                >
                  {formatINR(t.pnl)}
                </span>
              </TableCell>
              <TableCell className="text-xs text-text-muted font-mono tabular-nums">
                {t.buy_price > 0 ? `${formatINR(t.buy_price)} → ${formatINR(t.price)}` : "—"}
              </TableCell>
            </TableRow>
          ))}
    </>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────

export function TaxTab() {
  const fyOptions = useMemo(() => getFinancialYearOptions(), []);
  const [selectedFy, setSelectedFy] = useState(fyOptions[0].value);
  const { data: liveSummary, isLoading: summaryLoading, isError: summaryError } = useTaxSummary(selectedFy);
  const { data: report, isLoading: reportLoading } = useTaxReport(selectedFy);

  const isLoading = summaryLoading || reportLoading;

  // Fall back to demo data when API fails or returns empty. A successful
  // sample response still uses the server payload, but keeps the demo banner.
  const shouldUseDemoFallback = summaryError || (!isLoading && !liveSummary);
  const summary = (
    shouldUseDemoFallback ? getDemoTaxSummary(selectedFy) : liveSummary
  ) as TaxSummaryWithMethodology | undefined;
  // Provenance fails closed: only an explicit `is_sample_data: false` clears the demo banner.
  const isDemo = shouldUseDemoFallback || summary?.is_sample_data !== false;
  const auditAssessment: AuditAssessment = !isDemo && summary?.audit_assessment === "required"
    ? "required"
    : "incomplete";

  // Compute total P&L for display
  const totalPnl = useMemo(() => {
    if (!summary) return 0;
    return (
      summary.equity_ltcg +
      summary.equity_stcg +
      summary.intraday_pnl +
      summary.fno_pnl +
      summary.commodity_pnl
    );
  }, [summary]);

  // Segments ordered for display
  const segmentOrder = [
    "equity_ltcg",
    "equity_stcg",
    "equity_intraday",
    "futures",
    "options",
    "commodity",
  ];

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <RefreshCw className="size-5 animate-spin" />
        <span className="text-sm">Loading tax report...</span>
      </div>
    );
  }

  if (!summary) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3 text-text-muted">
        <FileText className="size-8 opacity-50" />
        <span className="text-sm">No tax data available. Connect to FlintTrade backend.</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Demo banner */}
      {isDemo && (
        <DemoBanner message="The built-in tax ledger is illustrative; live tax-history ingestion is not wired." />
      )}

      {/* Header with FY selector */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Receipt className="size-5 text-accent" />
          <div>
            <h2 className="font-heading font-semibold text-sm text-text-primary">
              Tax Report
            </h2>
            <p className="text-xxs text-text-muted">
              {summary.trade_count} trades &middot; Trade-date STT rates
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={isDemo}
            title={isDemo ? "CSV export is unavailable for illustrative tax data" : undefined}
            onClick={() => {
              if (!summary || isDemo) return;
              const csvData = [
                { Segment: "Equity LTCG", "P&L": summary.equity_ltcg },
                { Segment: "Equity STCG", "P&L": summary.equity_stcg },
                { Segment: "Intraday", "P&L": summary.intraday_pnl },
                { Segment: "F&O", "P&L": summary.fno_pnl },
                { Segment: "Commodity", "P&L": summary.commodity_pnl },
                {
                  Segment: "Overall estimate",
                  "P&L": totalPnl,
                  "Estimated Tax": summary.tax_liability_estimated,
                  STT: summary.stt_paid,
                  Methodology: summary.tax_estimate_methodology,
                  Provenance: summary.stt_rate_provenance,
                },
              ];
              exportToCSV(csvData, `tax-summary-${selectedFy}`);
            }}
            className="text-xs text-text-muted h-6 px-2 gap-1"
          >
            <Download className="size-3" />
            Export CSV
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={printCurrentView}
            className="text-xs text-text-muted h-6 px-2 gap-1"
          >
            <Printer className="size-3" />
            Print
          </Button>
          <Select value={selectedFy} onValueChange={setSelectedFy}>
            <SelectTrigger className="w-36 h-8 text-xs">
              <Calendar className="size-3 mr-1.5 text-text-muted" />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {fyOptions.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Hero: Total P&L + Estimated Tax */}
      <GlassCard className="p-5 gap-0">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="space-y-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
              Total Realised P&L ({selectedFy})
            </p>
            <div className="flex items-baseline gap-3">
              <span className="text-3xl font-mono font-bold tabular-nums">
                <PnLValue value={totalPnl} compact />
              </span>
            </div>
            <p className="text-xs text-text-muted">
              Across {summary.trade_count} trades &middot; STT paid: {formatINR(summary.stt_paid)}
            </p>
          </div>

          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-mono font-semibold tabular-nums",
                  "bg-yellow-500/10 text-yellow-500 border border-yellow-500/20",
                )}
              >
                <Landmark className="size-4" />
                Est. Tax: {formatINRCompact(summary.tax_liability_estimated)}
              </div>
            </div>
            {auditAssessment === "required" ? (
              <Badge variant="destructive" className="text-xxs gap-1">
                <AlertTriangle className="size-3" />
                Tax Audit Required
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xxs gap-1 border-yellow-500/30 text-yellow-500">
                <AlertTriangle className="size-3" />
                Audit assessment incomplete
              </Badge>
            )}
          </div>
        </div>
      </GlassCard>

      {/* Summary cards grid */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <SummaryCard
          label={<>Equity <GlossaryTooltip term="LTCG">LTCG</GlossaryTooltip></>}
          value={summary.equity_ltcg}
          icon={TrendingUp}
          subtitle={`Exemption used: ${formatINR(summary.ltcg_exemption_used)} of 1.25L`}
          variant={summary.equity_ltcg >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label={<>Equity <GlossaryTooltip term="STCG">STCG</GlossaryTooltip></>}
          value={summary.equity_stcg}
          icon={summary.equity_stcg >= 0 ? ArrowUpRight : ArrowDownRight}
          subtitle="Tax: 20% flat"
          variant={summary.equity_stcg >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label="Intraday P&L"
          value={summary.intraday_pnl}
          icon={BarChart3}
          subtitle="Business income — slab rate"
          variant={summary.intraday_pnl >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label="F&O P&L"
          value={summary.fno_pnl}
          icon={summary.fno_pnl >= 0 ? TrendingUp : TrendingDown}
          subtitle="Futures + Options — slab rate"
          variant={summary.fno_pnl >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label="Commodity P&L"
          value={summary.commodity_pnl}
          icon={summary.commodity_pnl >= 0 ? TrendingUp : TrendingDown}
          subtitle="MCX — slab rate"
          variant={summary.commodity_pnl >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label={<><GlossaryTooltip term="STT">STT</GlossaryTooltip> Paid</>}
          value={-summary.stt_paid}
          icon={Receipt}
          subtitle="Securities Transaction Tax"
          variant="info"
        />
      </div>

      {/* Turnover & Audit info */}
      <GlassCard className="p-4 gap-2">
        <div className="flex items-center gap-2">
          <Landmark className="size-4 text-text-muted" />
          <span className="text-xxs text-text-muted uppercase tracking-wider font-medium">
            Turnover & Audit
          </span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-1">
          <div>
            <p className="text-xs text-text-muted">Total Turnover</p>
            <p className="text-lg font-mono font-bold tabular-nums text-text-primary">
              {formatINRCompact(summary.turnover)}
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Audit Threshold</p>
            <p className="text-xs text-text-secondary mt-1 leading-relaxed">
              Simplified threshold check: turnover &gt; 10Cr, or &gt; 2Cr with profit &lt; 6% of turnover.
              Your turnover: {formatINRCompact(summary.turnover)}.
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Audit Status</p>
            <div className="mt-1">
              {auditAssessment === "required" ? (
                <div className="flex items-center gap-1.5 text-loss text-sm font-medium">
                  <AlertTriangle className="size-4" />
                  Audit required — consult a CA
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="flex items-center gap-1.5 text-yellow-500 text-sm font-medium">
                    <AlertTriangle className="size-4" />
                    Audit assessment incomplete
                  </div>
                  <p className="text-xxs text-text-muted leading-relaxed">
                    {summary.audit_assessment_reason}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </GlassCard>

      {/* Segment breakdown table */}
      {report && (
        <GlassCard className="p-4 gap-3">
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Segment Breakdown
          </h3>
          <p className="text-xxs text-text-muted">
            Click a segment to expand individual trades.
          </p>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-40">Segment</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="text-right w-20">Trades</TableHead>
                  <TableHead className="text-right w-32">P&L</TableHead>
                  <TableHead className="w-48">Tax Treatment</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {segmentOrder.map((key) => {
                  const segment = report.segments[key];
                  if (!segment) return null;
                  return (
                    <SegmentBreakdownRow
                      key={key}
                      segmentKey={key}
                      segment={segment}
                    />
                  );
                })}
              </TableBody>
            </Table>
          </div>
        </GlassCard>
      )}

      {/* Disclaimer */}
      <p className="text-xxs text-text-muted leading-relaxed">
        Tax calculations are estimates. {summary.tax_estimate_methodology} {summary.stt_methodology} Provenance:{" "}
        {summary.stt_rate_provenance} Consult a Chartered Accountant for filing.
      </p>
    </div>
  );
}
