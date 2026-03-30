/**
 * MfOptimizerTab.tsx
 *
 * Mutual Fund Expense Ratio Optimizer for SIP investors.
 * Shows potential savings by switching from regular to direct plans.
 *
 * Features:
 *   - Input: comma-separated mutual fund names
 *   - For each fund: expense ratio (regular vs direct), category, AUM
 *   - Annual savings by switching to direct plans
 *   - Total potential savings over 5/10/20 years with compounding
 *   - Hardcoded data for 20 popular Indian mutual funds
 *
 * Pure calculation logic exported for unit testing.
 */

import { useState, useMemo } from "react";
import {
  Calculator,
  Search,
  TrendingUp,
  IndianRupee,
  ArrowRight,
  Sparkles,
  AlertCircle,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MutualFundData {
  name: string;
  /** Shorthand for matching user input */
  aliases: string[];
  category: string;
  aum: number; // in INR crore
  expenseRegular: number; // percentage
  expenseDirect: number; // percentage
}

export interface MatchedFund extends MutualFundData {
  /** Annual savings per lakh invested */
  annualSavingsPerLakh: number;
  /** Expense ratio difference */
  expenseDiff: number;
}

export interface SavingsProjection {
  years: number;
  totalSavings: number;
}

// ---------------------------------------------------------------------------
// Hardcoded fund database (20 popular Indian MFs)
// ---------------------------------------------------------------------------

export const FUND_DATABASE: MutualFundData[] = [
  { name: "HDFC Flexi Cap Fund", aliases: ["hdfc flexi", "hdfc flexicap"], category: "Flexi Cap", aum: 55000, expenseRegular: 1.74, expenseDirect: 0.77 },
  { name: "SBI Bluechip Fund", aliases: ["sbi bluechip", "sbi blue chip"], category: "Large Cap", aum: 48000, expenseRegular: 1.63, expenseDirect: 0.82 },
  { name: "Axis Long Term Equity Fund", aliases: ["axis long term", "axis elss", "axis ltef"], category: "ELSS", aum: 33000, expenseRegular: 1.69, expenseDirect: 0.63 },
  { name: "Parag Parikh Flexi Cap Fund", aliases: ["parag parikh", "ppfas", "ppfcf"], category: "Flexi Cap", aum: 62000, expenseRegular: 1.63, expenseDirect: 0.63 },
  { name: "Mirae Asset Large Cap Fund", aliases: ["mirae large cap", "mirae asset"], category: "Large Cap", aum: 38000, expenseRegular: 1.62, expenseDirect: 0.53 },
  { name: "ICICI Pru Bluechip Fund", aliases: ["icici bluechip", "icici pru blue"], category: "Large Cap", aum: 51000, expenseRegular: 1.69, expenseDirect: 0.87 },
  { name: "Kotak Emerging Equity Fund", aliases: ["kotak emerging", "kotak midcap"], category: "Mid Cap", aum: 42000, expenseRegular: 1.78, expenseDirect: 0.46 },
  { name: "Nippon India Small Cap Fund", aliases: ["nippon small cap", "nippon smallcap"], category: "Small Cap", aum: 46000, expenseRegular: 1.82, expenseDirect: 0.68 },
  { name: "HDFC Mid-Cap Opportunities Fund", aliases: ["hdfc midcap", "hdfc mid cap"], category: "Mid Cap", aum: 60000, expenseRegular: 1.79, expenseDirect: 0.75 },
  { name: "SBI Small Cap Fund", aliases: ["sbi small cap", "sbi smallcap"], category: "Small Cap", aum: 28000, expenseRegular: 1.73, expenseDirect: 0.66 },
  { name: "Axis Midcap Fund", aliases: ["axis midcap", "axis mid cap"], category: "Mid Cap", aum: 25000, expenseRegular: 1.72, expenseDirect: 0.52 },
  { name: "UTI Nifty 50 Index Fund", aliases: ["uti nifty", "uti index", "uti nifty 50"], category: "Index", aum: 18000, expenseRegular: 0.30, expenseDirect: 0.18 },
  { name: "HDFC Index Fund - Nifty 50", aliases: ["hdfc index", "hdfc nifty"], category: "Index", aum: 14000, expenseRegular: 0.30, expenseDirect: 0.20 },
  { name: "Motilal Oswal Nasdaq 100 FoF", aliases: ["motilal nasdaq", "nasdaq 100"], category: "International", aum: 8000, expenseRegular: 1.09, expenseDirect: 0.48 },
  { name: "DSP Tax Saver Fund", aliases: ["dsp tax saver", "dsp elss"], category: "ELSS", aum: 13000, expenseRegular: 1.85, expenseDirect: 0.70 },
  { name: "Quant Small Cap Fund", aliases: ["quant small cap", "quant smallcap"], category: "Small Cap", aum: 24000, expenseRegular: 1.81, expenseDirect: 0.64 },
  { name: "Canara Robeco Bluechip Equity Fund", aliases: ["canara bluechip", "canara robeco"], category: "Large Cap", aum: 11000, expenseRegular: 1.80, expenseDirect: 0.43 },
  { name: "Tata Digital India Fund", aliases: ["tata digital", "tata digital india"], category: "Sectoral", aum: 9000, expenseRegular: 1.87, expenseDirect: 0.39 },
  { name: "SBI Focused Equity Fund", aliases: ["sbi focused", "sbi focused equity"], category: "Focused", aum: 30000, expenseRegular: 1.71, expenseDirect: 0.78 },
  { name: "ICICI Pru Value Discovery Fund", aliases: ["icici value", "icici value discovery"], category: "Value", aum: 42000, expenseRegular: 1.68, expenseDirect: 0.99 },
];

// ---------------------------------------------------------------------------
// Pure logic — exported for testing
// ---------------------------------------------------------------------------

/** Match user input against fund database. Case-insensitive, partial match. */
export function matchFunds(input: string): MatchedFund[] {
  const queries = input
    .split(",")
    .map((q) => q.trim().toLowerCase())
    .filter((q) => q.length > 0);

  if (queries.length === 0) return [];

  const matched: MatchedFund[] = [];
  const seen = new Set<string>();

  for (const query of queries) {
    for (const fund of FUND_DATABASE) {
      if (seen.has(fund.name)) continue;

      const nameMatch = fund.name.toLowerCase().includes(query);
      const aliasMatch = fund.aliases.some((a) => a.includes(query));

      if (nameMatch || aliasMatch) {
        const expenseDiff = fund.expenseRegular - fund.expenseDirect;
        matched.push({
          ...fund,
          expenseDiff,
          annualSavingsPerLakh: expenseDiff * 1000, // diff% of 1L = diff * 1000
        });
        seen.add(fund.name);
      }
    }
  }

  return matched;
}

/**
 * Calculate compounded savings over N years.
 * investmentPerFund: assumed investment per fund (INR).
 * expenseDiff: difference in expense ratio (percentage points).
 * assumedReturn: annual return rate (percentage).
 * years: projection period.
 *
 * The savings compound because on a growing corpus, the expense difference
 * saves more each year.
 */
export function calculateCompoundedSavings(
  investmentPerFund: number,
  expenseDiff: number,
  assumedReturn: number,
  years: number,
): number {
  if (years <= 0 || expenseDiff <= 0 || investmentPerFund <= 0) return 0;

  const monthlyRate = assumedReturn / 100 / 12;
  const diffRate = expenseDiff / 100;

  // With regular plan: grows at (return - expenseRegular)
  // With direct plan: grows at (return - expenseDirect)
  // Difference in growth rate = expenseDiff
  // We model as SIP of investmentPerFund/12 per month

  const monthlySip = investmentPerFund / 12;
  const months = years * 12;

  // Corpus with higher expense (regular)
  const regularRate = monthlyRate - (diffRate / 12);
  // Corpus with lower expense (direct)
  const directRate = monthlyRate;

  let corpusRegular = 0;
  let corpusDirect = 0;

  for (let m = 0; m < months; m++) {
    corpusRegular = (corpusRegular + monthlySip) * (1 + regularRate);
    corpusDirect = (corpusDirect + monthlySip) * (1 + directRate);
  }

  return Math.max(0, corpusDirect - corpusRegular);
}

/**
 * Calculate total savings across all matched funds for given projection years.
 * Returns savings for 5, 10, and 20 year horizons.
 */
export function calculateProjections(
  funds: MatchedFund[],
  investmentPerFund: number,
  assumedReturn: number,
): SavingsProjection[] {
  const horizons = [5, 10, 20];

  return horizons.map((years) => {
    const totalSavings = funds.reduce(
      (acc, fund) =>
        acc + calculateCompoundedSavings(investmentPerFund, fund.expenseDiff, assumedReturn, years),
      0,
    );
    return { years, totalSavings };
  });
}

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------

function formatINR(value: number): string {
  if (value >= 1_00_00_000) {
    return `₹${(value / 1_00_00_000).toFixed(2)} Cr`;
  }
  if (value >= 1_00_000) {
    return `₹${(value / 1_00_000).toFixed(2)} L`;
  }
  return `₹${value.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

function formatAUM(crore: number): string {
  if (crore >= 1_00_000) {
    return `${(crore / 1_00_000).toFixed(1)}L Cr`;
  }
  return `${crore.toLocaleString("en-IN")} Cr`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MfOptimizerTab() {
  const [input, setInput] = useState("");
  const [investmentPerFund, setInvestmentPerFund] = useState(100_000); // 1L default
  const [assumedReturn, setAssumedReturn] = useState(12); // 12% default

  const matched = useMemo(() => matchFunds(input), [input]);
  const projections = useMemo(
    () => calculateProjections(matched, investmentPerFund, assumedReturn),
    [matched, investmentPerFund, assumedReturn],
  );

  const totalAnnualSavings = useMemo(
    () =>
      matched.reduce(
        (acc, f) => acc + (f.expenseDiff / 100) * investmentPerFund,
        0,
      ),
    [matched, investmentPerFund],
  );

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-accent" aria-hidden="true" />
          <h3 className="font-heading font-semibold text-sm text-text-primary">
            Expense Ratio Optimizer
          </h3>
        </div>
        <p className="text-xs text-text-muted mt-1">
          Compare regular vs direct mutual fund plans. See how much you could save by switching.
        </p>
      </div>

      {/* Input section */}
      <GlassCard className="p-4 gap-3">
        <div className="space-y-3">
          {/* Fund names input */}
          <div className="space-y-1.5">
            <label htmlFor="fund-input" className="text-xs font-medium text-text-secondary">
              Your Mutual Funds
            </label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-text-muted" aria-hidden="true" />
              <Input
                id="fund-input"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. HDFC Flexi, SBI Bluechip, Parag Parikh"
                className="pl-8 h-8 text-xs bg-surface-card border-border-default"
              />
              {input.length > 0 && (
                <button
                  onClick={() => setInput("")}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary"
                  aria-label="Clear input"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </div>
            <p className="text-xxs text-text-muted">
              Enter fund names separated by commas. Matches from {FUND_DATABASE.length} popular funds.
            </p>
          </div>

          {/* Investment + Return assumptions */}
          <div className="flex items-end gap-4 flex-wrap">
            <div className="space-y-1.5">
              <label htmlFor="investment-input" className="text-xxs text-text-muted">
                Annual investment per fund (INR)
              </label>
              <Input
                id="investment-input"
                type="number"
                value={investmentPerFund}
                onChange={(e) => setInvestmentPerFund(Math.max(0, Number(e.target.value)))}
                className="h-7 w-32 text-xs font-mono bg-surface-card border-border-default"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="return-input" className="text-xxs text-text-muted">
                Assumed annual return (%)
              </label>
              <Input
                id="return-input"
                type="number"
                value={assumedReturn}
                onChange={(e) => setAssumedReturn(Math.max(0, Math.min(30, Number(e.target.value))))}
                className="h-7 w-20 text-xs font-mono bg-surface-card border-border-default"
              />
            </div>
          </div>
        </div>

        {/* Quick-add suggestions */}
        {input.length === 0 && (
          <div className="flex flex-wrap gap-1.5 pt-1">
            <span className="text-xxs text-text-muted mr-1">Try:</span>
            {["HDFC Flexi, SBI Bluechip", "Parag Parikh, Mirae", "Kotak Emerging, Nippon Small Cap"].map((suggestion) => (
              <button
                key={suggestion}
                onClick={() => setInput(suggestion)}
                className="text-xxs text-accent hover:text-accent/80 underline-offset-2 hover:underline transition-colors"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}
      </GlassCard>

      {/* Results */}
      {matched.length > 0 && (
        <>
          {/* Fund comparison table */}
          <GlassCard className="p-0 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2 border-b border-border-default">
              <div className="flex items-center gap-2">
                <Calculator className="size-3 text-text-muted" aria-hidden="true" />
                <span className="text-xs font-medium text-text-secondary">
                  Fund Comparison
                </span>
              </div>
              <Badge
                variant="outline"
                className="text-xxs border-border-default text-text-muted h-4 px-1.5"
              >
                {matched.length} fund{matched.length !== 1 ? "s" : ""}
              </Badge>
            </div>

            <Table aria-label="Mutual fund expense ratio comparison">
              <TableHeader>
                <TableRow className="border-border-default hover:bg-transparent">
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider">
                    Fund
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-center">
                    Category
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    AUM
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Regular
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-center">
                    &nbsp;
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Direct
                  </TableHead>
                  <TableHead className="h-8 text-xxs font-medium text-text-muted uppercase tracking-wider text-right">
                    Savings/yr
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {matched.map((fund) => (
                  <TableRow
                    key={fund.name}
                    className="border-border-default hover:bg-surface-card transition-colors"
                  >
                    <TableCell className="py-2 text-xs">
                      <div className="font-medium text-text-primary text-xs max-w-48 truncate">
                        {fund.name}
                      </div>
                    </TableCell>
                    <TableCell className="py-2 text-center">
                      <Badge
                        variant="outline"
                        className="text-xxs border-border-default text-text-muted font-normal h-4 px-1.5"
                      >
                        {fund.category}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-text-muted">
                      {formatAUM(fund.aum)}
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-loss font-semibold">
                      {fund.expenseRegular.toFixed(2)}%
                    </TableCell>
                    <TableCell className="py-2 text-center">
                      <ArrowRight className="size-3 text-text-muted mx-auto" aria-hidden="true" />
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-profit font-semibold">
                      {fund.expenseDirect.toFixed(2)}%
                    </TableCell>
                    <TableCell className="py-2 text-right font-mono tabular-nums text-xs text-profit font-semibold">
                      {formatINR((fund.expenseDiff / 100) * investmentPerFund)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </GlassCard>

          {/* Savings projections */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            {projections.map((proj) => (
              <GlassCard key={proj.years} className="p-4 gap-2">
                <div className="flex items-center gap-2">
                  <div className={cn(
                    "size-7 rounded-lg flex items-center justify-center",
                    proj.years === 5
                      ? "bg-surface-elevated"
                      : proj.years === 10
                        ? "bg-bullish-bg"
                        : "bg-accent/10",
                  )}>
                    <TrendingUp
                      className={cn(
                        "size-3.5",
                        proj.years === 5
                          ? "text-text-secondary"
                          : proj.years === 10
                            ? "text-profit"
                            : "text-accent",
                      )}
                    />
                  </div>
                  <span className="text-xxs text-text-muted uppercase tracking-wider">
                    {proj.years} Year Savings
                  </span>
                </div>
                <div className={cn(
                  "text-2xl font-mono font-bold tabular-nums",
                  proj.totalSavings > 0 ? "text-profit" : "text-text-muted",
                )}>
                  {formatINR(proj.totalSavings)}
                </div>
                <p className="text-xxs text-text-muted">
                  Compounded at {assumedReturn}% p.a. across {matched.length} fund{matched.length !== 1 ? "s" : ""}
                </p>
              </GlassCard>
            ))}
          </div>

          {/* Annual summary */}
          <GlassCard className="p-4 gap-2">
            <div className="flex items-center gap-2">
              <IndianRupee className="size-4 text-profit" aria-hidden="true" />
              <span className="text-xs font-medium text-text-secondary">
                Annual Savings Summary
              </span>
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-mono font-bold tabular-nums text-profit">
                {formatINR(totalAnnualSavings)}
              </span>
              <span className="text-xs text-text-muted">per year</span>
            </div>
            <p className="text-xs text-text-muted">
              By switching {matched.length} fund{matched.length !== 1 ? "s" : ""} from regular to direct plans,
              you save on average{" "}
              <span className="font-mono text-text-primary font-semibold">
                {(matched.reduce((a, f) => a + f.expenseDiff, 0) / matched.length).toFixed(2)}%
              </span>{" "}
              in expense ratios annually.
            </p>
          </GlassCard>
        </>
      )}

      {/* Empty state */}
      {input.length > 0 && matched.length === 0 && (
        <div className="flex flex-col items-center justify-center h-32 gap-3 text-text-muted">
          <AlertCircle className="size-5" aria-hidden="true" />
          <span className="text-sm">No matching funds found.</span>
          <span className="text-xs text-center max-w-xs">
            Try partial names like &quot;HDFC&quot;, &quot;SBI&quot;, &quot;Parag&quot;, or &quot;Mirae&quot;.
            We have {FUND_DATABASE.length} popular Indian mutual funds in our database.
          </span>
        </div>
      )}

      {/* Disclaimer */}
      <p className="text-xxs text-text-muted">
        Expense ratios are indicative and may vary. Actual savings depend on market conditions,
        fund performance, and investment timing. Switch to direct plans via your AMC website or
        MF Central. Consult a SEBI-registered advisor for personalised advice.
      </p>
    </div>
  );
}
