/**
 * TaxTab.tsx — Tax-ready P&L report for Indian traders
 *
 * Summary cards: LTCG, STCG, Intraday P&L, F&O P&L, Commodity P&L,
 * Total STT, Estimated Tax Liability, Audit Required indicator.
 * Segment breakdown table with per-trade details.
 * Turnover calculation and FY selector.
 *
 * Data source: GET /ft-api/v1/tax/summary, /ft-api/v1/tax/report
 */

import { useState, useMemo } from "react";
import {
  Receipt,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  ShieldCheck,
  RefreshCw,
  Calendar,
  FileText,
  Landmark,
  BarChart3,
  ArrowUpRight,
  ArrowDownRight,
  ChevronDown,
  ChevronUp,
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
import { cn } from "@/lib/utils";
import { useTaxSummary, useTaxReport, type TaxSegment } from "@/hooks/useTaxReport";
import { formatINR, formatINRCompact } from "../formatters";

// ─── Constants ───────────────────────────────────────────────────────────────

/** Available financial years for the selector. */
const FY_OPTIONS = [
  { value: "2025-26", label: "FY 2025-26" },
  { value: "2024-25", label: "FY 2024-25" },
  { value: "2023-24", label: "FY 2023-24" },
];

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
  label: string;
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
  const [selectedFy, setSelectedFy] = useState("2025-26");
  const { data: summary, isLoading: summaryLoading } = useTaxSummary(selectedFy);
  const { data: report, isLoading: reportLoading } = useTaxReport(selectedFy);

  const isLoading = summaryLoading || reportLoading;

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
      {/* Header with FY selector */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Receipt className="size-5 text-accent" />
          <div>
            <h2 className="font-heading font-semibold text-sm text-text-primary">
              Tax Report
            </h2>
            <p className="text-xxs text-text-muted">
              {summary.trade_count} trades &middot; Budget 2024 rates
            </p>
          </div>
        </div>
        <Select value={selectedFy} onValueChange={setSelectedFy}>
          <SelectTrigger className="w-36 h-8 text-xs">
            <Calendar className="size-3 mr-1.5 text-text-muted" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FY_OPTIONS.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Hero: Total P&L + Estimated Tax */}
      <GlassCard className="p-5 gap-0">
        <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
          <div className="space-y-1">
            <p className="text-xxs text-text-muted uppercase tracking-wider font-medium">
              Total Realized P&L ({selectedFy})
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
            {summary.needs_audit ? (
              <Badge variant="destructive" className="text-xxs gap-1">
                <AlertTriangle className="size-3" />
                Tax Audit Required
              </Badge>
            ) : (
              <Badge variant="outline" className="text-xxs gap-1 border-profit/30 text-profit">
                <ShieldCheck className="size-3" />
                No Audit Required
              </Badge>
            )}
          </div>
        </div>
      </GlassCard>

      {/* Summary cards grid */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <SummaryCard
          label="Equity LTCG"
          value={summary.equity_ltcg}
          icon={TrendingUp}
          subtitle={`Exemption used: ${formatINR(summary.ltcg_exemption_used)} of 1.25L`}
          variant={summary.equity_ltcg >= 0 ? "profit" : "loss"}
        />
        <SummaryCard
          label="Equity STCG"
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
          label="STT Paid"
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
              Mandatory if turnover &gt; 10Cr, or &gt; 2Cr with profit &lt; 6% of turnover.
              Your turnover: {formatINRCompact(summary.turnover)}.
            </p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Audit Status</p>
            <div className="mt-1">
              {summary.needs_audit ? (
                <div className="flex items-center gap-1.5 text-loss text-sm font-medium">
                  <AlertTriangle className="size-4" />
                  Audit required — consult a CA
                </div>
              ) : (
                <div className="flex items-center gap-1.5 text-profit text-sm font-medium">
                  <ShieldCheck className="size-4" />
                  Below audit threshold
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
        Tax calculations are estimates based on Budget 2024 rates. LTCG: 12.5% above
        1.25L exemption. STCG: 20%. Business income (intraday, F&O, commodity) taxed at
        slab rate (estimated 30%). Consult a Chartered Accountant for filing. STT is
        deductible as business expense for F&O/intraday traders.
      </p>
    </div>
  );
}
