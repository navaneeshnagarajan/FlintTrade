/**
 * SipTab.tsx
 *
 * Enhanced SIP calculator + active SIPs tracker.
 *
 * Features:
 *   - SIP frequency: Daily / Weekly / Monthly
 *   - Step-up SIP: annual increase by X% each year
 *   - Three-scenario comparison at 8%, 10%, 12% projected returns
 *   - "Start SIP" button (wired when opencase endpoint available)
 *   - Active SIPs tracker table (pending NAV feed)
 *
 * Calculator: pure client-side compound interest (no API needed).
 */

import { useState, useMemo } from "react";
import { Info, Plus, Zap } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
import { StaggeredList } from "@/components/motion/StaggeredList";
import { DisabledActionButton } from "../DisabledActionButton";
import { cn } from "@/lib/utils";
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

type Frequency = "daily" | "weekly" | "monthly";

const FREQUENCY_LABELS: Record<Frequency, string> = {
  daily: "Daily",
  weekly: "Weekly",
  monthly: "Monthly",
};

/** Payments per year for each frequency. */
const PAYMENTS_PER_YEAR: Record<Frequency, number> = {
  daily: 252,    // approx trading days in India; use 365 for pure daily
  weekly: 52,
  monthly: 12,
};

const SCENARIO_RATES = [8, 10, 12] as const;

// ─── Calculator logic ─────────────────────────────────────────────────────────

interface SipResult {
  invested: number;
  maturity: number;
  returns: number;
  /** Returns as % of maturity (0–100), for the stacked bar. */
  progress: number;
  wealthRatio: number;
}

/**
 * Step-up SIP calculation.
 *
 * For each year the periodic instalment increases by `stepUpPct` percent.
 * We simulate year-by-year to handle the step-up correctly.
 */
function calculateStepUpSip(
  periodicAmount: number,
  frequency: Frequency,
  annualRate: number,
  years: number,
  stepUpPct: number,
): SipResult | null {
  if (periodicAmount <= 0 || years <= 0) return null;

  const n = PAYMENTS_PER_YEAR[frequency];
  const r = annualRate / 100 / n; // periodic rate

  let corpus = 0;
  let totalInvested = 0;
  let currentAmount = periodicAmount;

  for (let y = 0; y < years; y++) {
    if (y > 0) currentAmount *= 1 + stepUpPct / 100;
    const payments = n;
    // Future value of uniform payments for this year (standard FV annuity due)
    const fvPayments =
      r > 0
        ? currentAmount * ((Math.pow(1 + r, payments) - 1) / r) * (1 + r)
        : currentAmount * payments;
    // Grow existing corpus for this year
    corpus = corpus * Math.pow(1 + r, payments) + fvPayments;
    totalInvested += currentAmount * payments;
  }

  const returns = corpus - totalInvested;
  const progress =
    totalInvested > 0 ? Math.min((returns / corpus) * 100, 100) : 0;
  const wealthRatio = totalInvested > 0 ? corpus / totalInvested : 0;

  return {
    invested: totalInvested,
    maturity: corpus,
    returns,
    progress,
    wealthRatio,
  };
}

// ─── Scenario comparison row ──────────────────────────────────────────────────

interface ScenarioRowProps {
  rate: number;
  periodicAmount: number;
  frequency: Frequency;
  years: number;
  stepUpPct: number;
  highlight?: boolean;
}

function ScenarioRow({
  rate,
  periodicAmount,
  frequency,
  years,
  stepUpPct,
  highlight,
}: ScenarioRowProps) {
  const result = useMemo(
    () => calculateStepUpSip(periodicAmount, frequency, rate, years, stepUpPct),
    [periodicAmount, frequency, rate, years, stepUpPct],
  );

  if (!result) return null;

  return (
    <div
      className={cn(
        "flex items-center justify-between gap-4 px-4 py-3 rounded-lg border transition-colors",
        highlight
          ? "border-accent/40 bg-accent/5"
          : "border-border-default bg-surface-card",
      )}
    >
      <div className="flex items-center gap-2 shrink-0">
        {highlight && <Zap className="size-3 text-accent" aria-hidden="true" />}
        <span className="text-sm font-mono font-bold text-text-primary">{rate}%</span>
        <span className="text-xs text-text-muted">p.a.</span>
      </div>
      <div className="flex items-center gap-6 text-right">
        <div>
          <div className="text-xxs text-text-muted uppercase tracking-wider">Invested</div>
          <div className="text-sm font-mono tabular-nums text-text-secondary">
            {formatINRCompact(result.invested)}
          </div>
        </div>
        <div>
          <div className="text-xxs text-text-muted uppercase tracking-wider">Est. Returns</div>
          <div className="text-sm font-mono tabular-nums text-profit font-semibold">
            {formatINRCompact(result.returns)}
          </div>
        </div>
        <div>
          <div className="text-xxs text-text-muted uppercase tracking-wider">Maturity</div>
          <div className="text-sm font-mono tabular-nums text-text-primary font-bold">
            {formatINRCompact(result.maturity)}
          </div>
        </div>
        <div className="hidden sm:block">
          <div className="text-xxs text-text-muted uppercase tracking-wider">Wealth ×</div>
          <div className="text-sm font-mono tabular-nums text-text-secondary">
            {result.wealthRatio.toFixed(2)}×
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Component ────────────────────────────────────────────────────────────────

export function SipTab() {
  const [amount, setAmount] = useState<string>("5000");
  const [frequency, setFrequency] = useState<Frequency>("monthly");
  const [years, setYears] = useState<string>("10");
  const [stepUp, setStepUp] = useState<string>("0");
  // Kept for the single-scenario detail card (use the middle 10% scenario)
  const [rate] = useState<string>("10");

  const periodicAmount = parseFloat(amount) || 0;
  const numYears = parseFloat(years) || 0;
  const stepUpPct = parseFloat(stepUp) || 0;
  const annualRate = parseFloat(rate) || 10;

  const result = useMemo<SipResult | null>(
    () => calculateStepUpSip(periodicAmount, frequency, annualRate, numYears, stepUpPct),
    [periodicAmount, frequency, annualRate, numYears, stepUpPct],
  );

  const frequencyLabel = FREQUENCY_LABELS[frequency].toLowerCase();

  return (
    <div className="max-w-2xl space-y-6">
      {/* Header */}
      <div className="space-y-1">
        <h3 className="font-heading font-semibold text-sm text-text-primary">
          <GlossaryTooltip term="SIP">SIP</GlossaryTooltip> Calculator
        </h3>
        <p className="text-xs text-text-muted">
          Estimate your future corpus with optional step-up and frequency selection.
        </p>
      </div>

      {/* Inputs — row 1: amount + frequency */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            SIP Amount (INR)
          </Label>
          <Input
            type="number"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            min="100"
            step="500"
            aria-label="SIP amount in rupees"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            Frequency
          </Label>
          <Select
            value={frequency}
            onValueChange={(v) => setFrequency(v as Frequency)}
          >
            <SelectTrigger
              className="h-9 text-sm bg-surface-card border-border-default text-text-primary"
              aria-label="Select SIP frequency"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-surface-elevated border-border-default">
              {(Object.keys(FREQUENCY_LABELS) as Frequency[]).map((f) => (
                <SelectItem key={f} value={f} className="text-sm">
                  {FREQUENCY_LABELS[f]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Inputs — row 2: duration + step-up */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
            aria-label="Investment duration in years"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xxs text-text-muted uppercase tracking-wider">
            Annual Step-up (%)
          </Label>
          <Input
            type="number"
            value={stepUp}
            onChange={(e) => setStepUp(e.target.value)}
            min="0"
            max="50"
            step="1"
            placeholder="0 = no step-up"
            aria-label="Annual step-up percentage — increases SIP amount each year"
            className="h-9 text-sm bg-surface-card border-border-default text-text-primary font-mono placeholder:text-text-disabled"
          />
          {stepUpPct > 0 && (
            <p className="text-xxs text-text-muted">
              SIP grows {stepUpPct}% each year: yr1 = {formatINR(periodicAmount)},
              yr5 ≈ {formatINR(periodicAmount * Math.pow(1 + stepUpPct / 100, 4))}
            </p>
          )}
        </div>
      </div>

      {/* Three-scenario comparison */}
      {periodicAmount > 0 && numYears > 0 && (
        <div className="space-y-3">
          <div>
            <h4 className="font-heading font-semibold text-xs text-text-primary">
              Projected Wealth — 3 Scenarios
            </h4>
            <p className="text-xs text-text-muted mt-0.5">
              {FREQUENCY_LABELS[frequency]} SIP of {formatINR(periodicAmount)} over {years} years
              {stepUpPct > 0 ? ` with ${stepUpPct}% annual step-up` : ""}.
            </p>
          </div>
          <div className="space-y-2">
            {SCENARIO_RATES.map((r) => (
              <ScenarioRow
                key={r}
                rate={r}
                periodicAmount={periodicAmount}
                frequency={frequency}
                years={numYears}
                stepUpPct={stepUpPct}
                highlight={r === 10}
              />
            ))}
          </div>
        </div>
      )}

      {/* Detail card for 10% scenario */}
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
                Est. Returns (10%)
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
              {result.wealthRatio.toFixed(2)}×
            </span>
            <span className="text-text-muted">
              — at 10% p.a. over {years} years
            </span>
          </div>

          {/* Stacked bar */}
          <div className="space-y-1.5">
            <div className="flex justify-between text-xs text-text-muted">
              <span>Principal</span>
              <span>Estimated returns (10%)</span>
            </div>
            <div className="h-2.5 w-full bg-border-default rounded-full overflow-hidden flex">
              <div
                className="h-full bg-blue-600 transition-[width] duration-500"
                style={{ width: `${100 - result.progress}%` }}
              />
              <div
                className="h-full bg-profit transition-[width] duration-500"
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

          {/* Start SIP button */}
          <div className="flex items-center gap-3 pt-1">
            <DisabledActionButton
              label="Start SIP"
              tooltip="Connect a mutual fund platform (Settings → Data Sources) to place SIP mandates directly from FlintTrade."
              icon={Plus}
            />
            <p className="text-xs text-text-muted">
              Investing {formatINR(periodicAmount)}/{frequencyLabel} for {years} years at 10% p.a. →{" "}
              {formatINRCompact(result.maturity)} at maturity.
            </p>
          </div>
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
              Track your running SIP mandates. Requires NAV feed connection to sync automatically.
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
          current NAV to show running <GlossaryTooltip term="XIRR">XIRR</GlossaryTooltip> alongside this calculator.
        </p>
      </div>
    </div>
  );
}
