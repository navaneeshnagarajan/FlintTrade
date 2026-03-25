/**
 * SipTab.tsx
 *
 * SIP calculator + active SIPs tracker placeholder.
 * Calculator: pure client-side compound interest (no API needed).
 * Tracker: empty table awaiting NAV feed connection.
 */

import { useState, useMemo } from "react";
import { Info, Plus } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { GlassCard } from "@/components/ui/GlassCard";
import { StaggeredList } from "@/components/motion/StaggeredList";
import { DisabledActionButton } from "../DisabledActionButton";
import { formatINR, formatINRCompact } from "../formatters";

// ─── Constants ────────────────────────────────────────────────────────────────

const SIP_TABLE_COLUMNS = [
  "Fund Name",
  "Monthly (₹)",
  "Start Date",
  "Duration",
  "Expected Return",
  "Maturity",
  "Status",
];

// ─── Calculator result type ───────────────────────────────────────────────────

interface SipResult {
  invested: number;
  maturity: number;
  returns: number;
  /** Returns as % of maturity (0–100), for the stacked bar. */
  progress: number;
  wealthRatio: number;
}

function calculateSip(monthly: number, annualRate: number, years: number): SipResult | null {
  if (monthly <= 0 || years <= 0) return null;
  const r = annualRate / 100 / 12;
  const n = years * 12;
  const invested = monthly * n;
  const maturity =
    r > 0 ? monthly * ((Math.pow(1 + r, n) - 1) / r) * (1 + r) : invested;
  const returns = maturity - invested;
  const progress = invested > 0 ? Math.min((returns / maturity) * 100, 100) : 0;
  const wealthRatio = invested > 0 ? maturity / invested : 0;
  return { invested, maturity, returns, progress, wealthRatio };
}

// ─── Component ────────────────────────────────────────────────────────────────

export function SipTab() {
  const [monthly, setMonthly] = useState<string>("5000");
  const [rate, setRate] = useState<string>("12");
  const [years, setYears] = useState<string>("10");

  const result = useMemo<SipResult | null>(
    () =>
      calculateSip(
        parseFloat(monthly) || 0,
        parseFloat(rate) || 0,
        parseFloat(years) || 0,
      ),
    [monthly, rate, years],
  );

  return (
    <div className="max-w-xl space-y-6">
      {/* Header */}
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">SIP Calculator</h3>
        <p className="text-xs text-text-muted">
          Estimate future corpus from regular monthly investments using compound interest (CAGR).
        </p>
      </div>

      {/* Inputs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            Monthly SIP (INR)
          </Label>
          <Input
            type="number"
            value={monthly}
            onChange={(e) => setMonthly(e.target.value)}
            min="100"
            step="500"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            Expected Return (%/yr)
          </Label>
          <Input
            type="number"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            min="1"
            max="30"
            step="0.5"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            Duration (years)
          </Label>
          <Input
            type="number"
            value={years}
            onChange={(e) => setYears(e.target.value)}
            min="1"
            max="40"
            step="1"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
      </div>

      {/* Results */}
      {result ? (
        <div className="space-y-4">
          <StaggeredList
            className="grid grid-cols-3 gap-px bg-border-default rounded-lg overflow-hidden"
            staggerDelay={60}
          >
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Total Invested
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.invested)}
              </div>
            </GlassCard>
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Est. Returns
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-profit">
                {formatINRCompact(result.returns)}
              </div>
            </GlassCard>
            <GlassCard className="rounded-none p-4 gap-1">
              <span className="text-xxs text-text-muted uppercase tracking-wider">
                Maturity Value
              </span>
              <div className="text-xl font-mono font-bold tabular-nums text-text-primary">
                {formatINRCompact(result.maturity)}
              </div>
            </GlassCard>
          </StaggeredList>

          {/* Wealth ratio */}
          <div className="flex items-center gap-3 text-xs">
            <span className="text-text-muted">Wealth ratio:</span>
            <span className="font-mono font-semibold text-profit">
              {result.wealthRatio.toFixed(2)}x
            </span>
            <span className="text-text-muted">
              — your money multiplies {result.wealthRatio.toFixed(2)} times over {years} years
            </span>
          </div>

          {/* Stacked bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-text-muted">
              <span>Principal</span>
              <span>Estimated returns</span>
            </div>
            <div className="h-2.5 w-full bg-border-default rounded-full overflow-hidden flex">
              <div
                className="h-full bg-blue-600 transition-all duration-500"
                style={{ width: `${100 - result.progress}%` }}
              />
              <div
                className="h-full bg-profit transition-all duration-500"
                style={{ width: `${result.progress}%` }}
              />
            </div>
            <div className="flex justify-between text-xs">
              <span className="text-neutral-text font-mono tabular-nums">
                {(100 - result.progress).toFixed(1)}% principal
              </span>
              <span className="text-profit font-mono tabular-nums">
                {result.progress.toFixed(1)}% gains
              </span>
            </div>
          </div>

          <p className="text-xs text-text-muted leading-relaxed">
            Investing {formatINR(parseFloat(monthly) || 0)}/month for {years} years at {rate}%
            p.a. compounds to {formatINRCompact(result.maturity)}. Actual MF returns vary; this is
            an illustrative projection only.
          </p>
        </div>
      ) : (
        <div className="text-center py-8 text-text-muted text-xs">
          Enter values above to calculate.
        </div>
      )}

      {/* Active SIPs tracker */}
      <div className="pt-4 border-t border-border-default space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h4 className="font-heading font-semibold text-sm text-text-primary">Active SIPs</h4>
            <p className="text-xs text-text-muted mt-0.5">
              Track your running SIP mandates. Requires NAV feed connection to sync auto.
            </p>
          </div>
          <DisabledActionButton
            label="Add SIP"
            tooltip="Connect a NAV data source (Settings → Data Sources) to add and track SIP mandates."
            icon={Plus}
          />
        </div>

        <div className="border border-border-default rounded-lg overflow-hidden">
          <Table aria-label="Active SIPs">
            <TableHeader>
              <TableRow className="border-border-default hover:bg-transparent">
                {SIP_TABLE_COLUMNS.map((col) => (
                  <TableHead
                    key={col}
                    className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider"
                  >
                    {col}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow className="border-none hover:bg-transparent">
                <TableCell
                  colSpan={SIP_TABLE_COLUMNS.length}
                  className="h-20 text-center text-xs text-text-muted"
                >
                  <div className="flex flex-col items-center gap-2">
                    <Info className="size-4 text-text-disabled" />
                    No SIPs tracked yet. Connect NAV provider to add SIP mandates.
                  </div>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>

        <p className="text-xs text-text-muted leading-relaxed">
          After connecting a NAV feed, FlintTrade will sync your SIP dates, invested amounts, and
          current NAV to show running XIRR alongside this calculator.
        </p>
      </div>
    </div>
  );
}
