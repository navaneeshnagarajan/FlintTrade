/**
 * CalculatorWidget — the terminal's one trade calculator.
 *
 * Four tabs over a single shared trade description:
 *
 *   Sizing       how many lots to take — Fixed %, Kelly or ATR
 *   Target / R:R what those lots pay, and how often the setup must win
 *   Brokerage    what the round trip costs
 *   Margin       what the broker will block
 *
 * Merged on 2026-07-25 from three widgets that each sized the same position:
 * Calculator (risk/reward, brokerage, margin), Position Sizing (Fixed %/Kelly/
 * ATR plus the capital-at-risk donut) and Profit Target (R:R, breakeven win
 * rate, the R:R bar). The arithmetic was already shared through `lib/sizing.ts`;
 * this merges the surfaces, so entry, stop, lot size, capital and risk % are
 * typed once and every tab reads the same trade instead of three panels
 * disagreeing about one position.
 *
 * What each contributed:
 *   Calculator      react-hook-form + zod validation (the only one of the three
 *                   that validated anything), side auto-detection, directional
 *                   rejection, the Conservative/Balanced/Aggressive templates,
 *                   the charges engine and the live margin tab.
 *   Position Sizing Kelly (half-Kelly) and ATR-derived stops; the donut.
 *   Profit Target   breakeven win rate with its prose insight; the R:R bar.
 *
 * `params.tab` selects the opening tab and is persisted through
 * `api.updateParameters`, which is also how the retired `positionsizing`
 * (tab `"sizing"`) and `profittarget` (tab `"target"`) ids keep resolving into
 * the view their operators saved.
 *
 * Adapted from:
 *   openalgo-chart/src/components/RiskCalculatorPanel/RiskCalculatorPanel.tsx
 *   openalgo-chart/src/utils/indicators/riskCalculator.ts
 */

import { useCallback, useEffect, useMemo, useRef, useState, memo } from "react";
import {
  useForm,
  Controller,
  type FieldErrors,
  type Resolver,
  type UseFormRegisterReturn,
  type UseFormReturn,
} from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AlertTriangle, Calculator, Layers, Receipt, Ruler, Target } from "lucide-react";
import { FlintDonutBreakdown } from "@flinttrade/design-system";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { WidgetProps } from "@/types/widgets";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import type { AccountAuthorityIdentity } from "@/hooks/useDataScope";
import {
  accountAuthorityMatches,
  captureAccountAuthority,
} from "@/lib/accountQueryState";
import { getMargin, getFunds } from "@/services/api";
import type { MarginData, Funds } from "@/types/api";
import {
  breakevenWinRate,
  deriveTarget,
  formatRR,
  kellyFraction,
  riskBudget,
  rrRatio as computeRR,
  sizeFixedFractional,
  type FixedFractionalResult,
  type TradeSide,
} from "@/lib/sizing";

// ---------------------------------------------------------------------------
// Tab identity
// ---------------------------------------------------------------------------

/** The four calculator surfaces. */
export type CalculatorTab = "sizing" | "target" | "brokerage" | "margin";

const CALCULATOR_TABS: readonly CalculatorTab[] = ["sizing", "target", "brokerage", "margin"];

/** Panel params this widget understands. */
export interface CalculatorPanelParams {
  /** Which tab to open on. Retired ids arrive here — see RETIRED_WIDGET_IDS. */
  tab?: string;
}

/**
 * Resolve a panel-supplied tab id to a tab this widget actually has.
 *
 * @param raw - The `tab` param from a saved layout, which may be anything.
 * @returns The matching tab, or `"sizing"` for unknown or absent values.
 */
export function resolveCalculatorTab(raw: unknown): CalculatorTab {
  return typeof raw === "string" && (CALCULATOR_TABS as readonly string[]).includes(raw)
    ? (raw as CalculatorTab)
    : "sizing";
}

// ---------------------------------------------------------------------------
// Formatters — one rupee formatter for the whole widget (there were three)
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** Format a rupee amount in Indian digit grouping, paise only when present. */
function formatINR(n: number): string {
  return `₹${INR.format(n)}`;
}

// ---------------------------------------------------------------------------
// Shared presentational pieces
// ---------------------------------------------------------------------------

type Highlight = "profit" | "loss" | "neutral" | "warning";

const HIGHLIGHT_CLASS: Record<Highlight, string> = {
  profit: "text-profit",
  loss: "text-loss",
  warning: "text-warning",
  neutral: "text-text-primary",
};

function ResultRow({
  label,
  value,
  highlight = "neutral",
}: {
  label: string;
  value: string;
  highlight?: Highlight;
}) {
  return (
    <div className="flex items-center justify-between py-0.5">
      <span className="text-text-muted text-xs">{label}</span>
      <span
        className={`font-mono tabular-nums text-xs font-medium ${HIGHLIGHT_CLASS[highlight]}`}
      >
        {value}
      </span>
    </div>
  );
}

interface NumFieldProps {
  id: string;
  label: string;
  register: UseFormRegisterReturn;
  error?: string;
  step?: string;
  min?: string;
  placeholder?: string;
}

/** A labelled numeric input wired to react-hook-form, with its zod error. */
function NumField({ id, label, register, error, step = "1", min, placeholder }: NumFieldProps) {
  return (
    <div className="flex items-center gap-2">
      <Label htmlFor={id} className="text-xs text-text-muted w-32 shrink-0">
        {label}
      </Label>
      <div className="flex-1 min-w-0">
        <Input
          id={id}
          type="number"
          step={step}
          min={min}
          placeholder={placeholder}
          className={`h-7 text-xs font-mono text-right bg-surface-card border-border-default text-text-primary ${
            error ? "border-loss" : ""
          }`}
          {...register}
        />
        {error && <p className="text-loss text-xxs mt-0.5">{error}</p>}
      </div>
    </div>
  );
}

const selectCls =
  "h-7 text-xs bg-surface-card border-border-default text-text-primary font-mono px-1.5";

// ---------------------------------------------------------------------------
// The shared trade description (Sizing + Target tabs)
// ---------------------------------------------------------------------------

/** How the Sizing tab arrives at the percentage of capital to stake. */
export type SizingMethod = "fixedFractional" | "kelly" | "atr";

const tradeSchema = z.object({
  capital: z.coerce.number().min(1000, "Min ₹1,000"),
  riskPercent: z.coerce.number().min(0.1, "Min 0.1%").max(10, "Max 10%"),
  side: z.enum(["BUY", "SELL"]),
  lotSize: z.coerce.number().min(1, "Min 1"),
  entryPrice: z.coerce.number().min(0.01, "Required"),
  stopLossPrice: z.coerce.number().min(0.01, "Required"),
  targetPrice: z.coerce.number().optional(),
  riskRewardRatio: z.coerce.number().min(0.5).max(10),
  quantity: z.coerce.number().min(1, "Min 1"),
  // Kelly
  winRate: z.coerce.number().min(1, "Min 1%").max(100, "Max 100%"),
  rewardRisk: z.coerce.number().min(0.1, "Min 0.1"),
  // ATR
  atr: z.coerce.number().min(0.01, "Required"),
  atrMultiplier: z.coerce.number().min(0.1, "Min 0.1"),
});

type TradeFormValues = z.infer<typeof tradeSchema>;

const TRADE_DEFAULTS: TradeFormValues = {
  capital: 500_000,
  riskPercent: 1,
  side: "BUY",
  lotSize: 50,
  entryPrice: 22_000,
  stopLossPrice: 21_800,
  targetPrice: 22_500,
  riskRewardRatio: 2,
  quantity: 1,
  winRate: 55,
  rewardRisk: 2,
  atr: 180,
  atrMultiplier: 1.5,
};

/**
 * Number inputs hand back strings; zod coerces at validation time but
 * `watch()` returns the raw field value, so the maths coerces explicitly.
 */
function num(value: unknown): number {
  return Number(value);
}

/** Auto-detect the side from entry vs stop (adapted from riskCalculator.ts). */
function autoDetectSide(entry: number, stop: number): TradeSide | null {
  if (entry <= 0 || stop <= 0 || entry === stop) return null;
  return stop > entry ? "SELL" : "BUY";
}

/**
 * The side the maths should use: the stop's position relative to entry wins
 * over the operator's selection, because a stop above entry is a short
 * whatever the dropdown says. Falls back to the selection when the two prices
 * cannot decide (equal, blank, or a method that derives its own stop).
 */
function effectiveSide(entry: number, stop: number, selected: TradeSide): TradeSide {
  return autoDetectSide(entry, stop) ?? selected;
}

// ---------------------------------------------------------------------------
// Sizing maths — all three methods reduce to the shared fixed-fractional
// kernel in lib/sizing.ts; only the staked percentage and the stop differ.
// ---------------------------------------------------------------------------

interface SizingComputation {
  /** Lot count, units and the rupees genuinely at risk at that size. */
  sized: FixedFractionalResult;
  /** Rupee budget the operator asked for — the yardstick for `exceedsRisk`. */
  budget: number;
  /** Percentage of capital staked. Kelly derives this; the others state it. */
  stakePct: number;
  /** Distance from entry to stop, in points. */
  stopDistance: number;
  /** The stop price — typed by the operator, or derived from the ATR. */
  stopPrice: number;
  /** `units × entry`. */
  positionValue: number;
  side: TradeSide;
}

interface SizingInput {
  capital: number;
  riskPercent: number;
  lotSize: number;
  entryPrice: number;
  stopLossPrice: number;
  side: TradeSide;
  method: SizingMethod;
  winRate: number;
  rewardRisk: number;
  atr: number;
  atrMultiplier: number;
}

/**
 * Size the trade under the selected method.
 *
 * @param input - The shared trade description plus the method's own inputs.
 * @returns The sizing result, or `null` when the inputs cannot describe a
 *   trade — including a direction the prices contradict.
 */
function computeSizing(input: SizingInput): SizingComputation | null {
  const { capital, riskPercent, lotSize, entryPrice, stopLossPrice, side, method } = input;

  if (!(entryPrice > 0)) return null;

  let stopDistance: number;
  let stopPrice: number;

  if (method === "atr") {
    // The stop comes from volatility, so it is always on the correct side.
    stopDistance = input.atr * input.atrMultiplier;
    if (!(stopDistance > 0)) return null;
    stopPrice = side === "SELL" ? entryPrice + stopDistance : entryPrice - stopDistance;
  } else {
    if (!(stopLossPrice > 0)) return null;
    // Directional validation: a BUY whose stop sits at or above entry is not a
    // trade, and neither is a SELL whose stop sits at or below it.
    if (side === "BUY" && entryPrice <= stopLossPrice) return null;
    if (side === "SELL" && entryPrice >= stopLossPrice) return null;
    stopDistance = Math.abs(entryPrice - stopLossPrice);
    stopPrice = stopLossPrice;
  }

  const stakePct =
    method === "kelly"
      ? kellyFraction({ winRate: input.winRate, rewardRisk: input.rewardRisk }) * 100
      : riskPercent;

  const sized = sizeFixedFractional({ capital, riskPct: stakePct, stopDistance, lotSize });
  if (!sized) return null;

  return {
    sized,
    budget: riskBudget(capital, stakePct),
    stakePct,
    stopDistance,
    stopPrice,
    positionValue: sized.units * entryPrice,
    side,
  };
}

// ---------------------------------------------------------------------------
// Target / R:R maths
// ---------------------------------------------------------------------------

interface TargetComputation {
  side: TradeSide;
  /** The target used — the operator's, or one derived from the R:R selector. */
  targetPrice: number;
  /** True when the target came from the R:R selector rather than the operator. */
  derived: boolean;
  stopDistance: number;
  rewardPoints: number;
  /** `quantity × lotSize`. */
  units: number;
  riskPerTrade: number;
  potentialProfit: number;
  rrRatio: number;
  /** Win rate needed to break even at this R:R, as a percentage. */
  breakEvenWinRate: number;
}

interface TargetInput {
  entryPrice: number;
  stopLossPrice: number;
  targetPrice: number;
  riskRewardRatio: number;
  quantity: number;
  lotSize: number;
  side: TradeSide;
}

/**
 * Work out what the trade pays and how often it must win.
 *
 * @param input - Entry, stop, an optional target, the fallback R:R and the size.
 * @returns The reward picture, or `null` when the prices contradict the
 *   direction or the trade is not yet described.
 */
function computeTarget(input: TargetInput): TargetComputation | null {
  const { entryPrice, stopLossPrice, riskRewardRatio, quantity, lotSize, side } = input;

  if (!(entryPrice > 0) || !(stopLossPrice > 0)) return null;
  if (!(quantity > 0) || !(lotSize > 0)) return null;
  if (side === "BUY" && entryPrice <= stopLossPrice) return null;
  if (side === "SELL" && entryPrice >= stopLossPrice) return null;

  const stopDistance = Math.abs(entryPrice - stopLossPrice);

  let targetPrice: number;
  let derived: boolean;
  if (input.targetPrice > 0) {
    // A target on the wrong side of entry is a typo, not a trade.
    if (side === "BUY" && input.targetPrice <= entryPrice) return null;
    if (side === "SELL" && input.targetPrice >= entryPrice) return null;
    targetPrice = input.targetPrice;
    derived = false;
  } else {
    if (!(riskRewardRatio > 0)) return null;
    targetPrice = deriveTarget(entryPrice, stopDistance, riskRewardRatio, side);
    derived = true;
  }

  const rr = computeRR(entryPrice, stopLossPrice, targetPrice);
  if (rr === null) return null;

  const units = quantity * lotSize;
  const rewardPoints = Math.abs(targetPrice - entryPrice);

  return {
    side,
    targetPrice,
    derived,
    stopDistance,
    rewardPoints,
    units,
    riskPerTrade: stopDistance * units,
    potentialProfit: rewardPoints * units,
    rrRatio: rr,
    breakEvenWinRate: breakevenWinRate(rr),
  };
}

// ---------------------------------------------------------------------------
// Risk templates — set the whole risk posture in one click
// ---------------------------------------------------------------------------

interface Template {
  label: string;
  capital: number;
  riskPercent: number;
  riskRewardRatio: number;
}

const TEMPLATES: Template[] = [
  { label: "Conservative", capital: 500_000, riskPercent: 1, riskRewardRatio: 3 },
  { label: "Balanced", capital: 200_000, riskPercent: 2, riskRewardRatio: 2 },
  { label: "Aggressive", capital: 100_000, riskPercent: 3, riskRewardRatio: 1.5 },
];

// ---------------------------------------------------------------------------
// Capital-at-risk donut
// ---------------------------------------------------------------------------

function PieChart({ atRiskFraction }: { atRiskFraction: number }) {
  const clampedFraction = Math.min(1, Math.max(0, atRiskFraction));
  const atRiskPct = (clampedFraction * 100).toFixed(1);
  const availablePct = ((1 - clampedFraction) * 100).toFixed(1);

  return (
    <FlintDonutBreakdown
      ariaLabel={`Capital allocation: ${atRiskPct}% at risk, ${availablePct}% available`}
      slices={[
        { label: "Available", value: 1 - clampedFraction, color: "#34d399" },
        { label: "At Risk", value: clampedFraction, color: "#f87171" },
      ]}
      className="size-20"
    />
  );
}

// ---------------------------------------------------------------------------
// R:R visual bar
// ---------------------------------------------------------------------------

function RRBar({ rrRatio }: { rrRatio: number }) {
  // Cap visual at 5:1 for display purposes
  const capped = Math.min(rrRatio, 5);
  const riskWidth = (1 / (1 + capped)) * 100;
  const rewardWidth = 100 - riskWidth;
  return (
    <div
      className="flex h-5 rounded overflow-hidden border border-border-default"
      aria-label={`Risk reward ratio ${rrRatio.toFixed(2)} to 1`}
    >
      <div
        className="bg-loss/60 flex items-center justify-center text-xxs text-white font-medium transition-all"
        style={{ width: `${riskWidth.toFixed(1)}%` }}
      >
        {riskWidth > 14 ? "Risk" : ""}
      </div>
      <div
        className="bg-profit/60 flex items-center justify-center text-xxs text-white font-medium transition-all"
        style={{ width: `${rewardWidth.toFixed(1)}%` }}
      >
        {rewardWidth > 14 ? `Reward (${rrRatio.toFixed(1)}R)` : ""}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sizing tab
// ---------------------------------------------------------------------------

const METHODS: { id: SizingMethod; label: string }[] = [
  { id: "fixedFractional", label: "Fixed %" },
  { id: "kelly", label: "Kelly" },
  { id: "atr", label: "ATR" },
];

interface TabProps {
  form: UseFormReturn<TradeFormValues>;
  values: TradeFormValues;
  errors: FieldErrors<TradeFormValues>;
}

interface SizingTabProps extends TabProps {
  method: SizingMethod;
  onMethodChange: (method: SizingMethod) => void;
}

function SizingTab({ form, values, errors, method, onMethodChange }: SizingTabProps) {
  const { register, control, setValue } = form;

  const entry = num(values.entryPrice);
  const stop = num(values.stopLossPrice);
  // ATR derives its own stop and hides the stop-price field, so there the
  // dropdown has to govern — reading the direction off a stop the operator
  // cannot see would make the control look broken.
  const selected = (values.side ?? "BUY") as TradeSide;
  const side = method === "atr" ? selected : effectiveSide(entry, stop, selected);

  const result = useMemo(
    () =>
      computeSizing({
        capital: num(values.capital),
        riskPercent: num(values.riskPercent),
        lotSize: num(values.lotSize),
        entryPrice: entry,
        stopLossPrice: stop,
        side,
        method,
        winRate: num(values.winRate),
        rewardRisk: num(values.rewardRisk),
        atr: num(values.atr),
        atrMultiplier: num(values.atrMultiplier),
      }),
    [values, entry, stop, side, method],
  );

  const applyTemplate = (t: Template) => {
    setValue("capital", t.capital);
    setValue("riskPercent", t.riskPercent);
    setValue("riskRewardRatio", t.riskRewardRatio);
  };

  const unitNoun = num(values.lotSize) === 1 ? "share" : "lot";

  return (
    <div className="flex flex-col gap-3 overflow-auto h-full p-3">
      {/* Templates — the whole risk posture in one click */}
      <div className="flex gap-1">
        {TEMPLATES.map((t) => (
          <button
            key={t.label}
            className="text-xs px-2 py-0.5 rounded border border-border-default text-text-muted hover:text-text-primary hover:border-border-strong transition-colors flex-1"
            onClick={() => applyTemplate(t)}
            type="button"
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Method selector */}
      <div
        className="flex rounded border border-border-default overflow-hidden"
        role="tablist"
        aria-label="Position sizing method"
      >
        {METHODS.map((m) => (
          <button
            key={m.id}
            type="button"
            role="tab"
            aria-selected={method === m.id}
            onClick={() => onMethodChange(m.id)}
            className={`flex-1 py-1 text-xs font-medium transition-colors ${
              method === m.id
                ? "bg-accent text-white"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {/* Account parameters */}
      <fieldset className="space-y-2">
        <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
          Account Parameters
        </legend>
        <NumField
          id="calc-capital"
          label="Account Capital"
          register={register("capital")}
          error={errors.capital?.message}
        />
        {method !== "kelly" && (
          <NumField
            id="calc-risk"
            label="Risk per Trade %"
            register={register("riskPercent")}
            error={errors.riskPercent?.message}
            step="0.1"
            min="0.1"
          />
        )}
        <NumField
          id="calc-lotsize"
          label="Lot Size"
          register={register("lotSize")}
          error={errors.lotSize?.message}
          min="1"
        />
        <div className="flex items-center gap-2">
          <Label htmlFor="calc-side" className="text-xs text-text-muted w-32 shrink-0">
            Side
          </Label>
          <div className="flex-1 min-w-0">
            <Controller
              name="side"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="calc-side" className={selectCls}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default text-xs">
                    <SelectItem value="BUY">BUY</SelectItem>
                    <SelectItem value="SELL">SELL</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>
      </fieldset>

      {/* Trade prices */}
      <fieldset className="space-y-2">
        <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
          {method === "kelly" ? "Kelly Criterion (Half-Kelly)" : method === "atr" ? "ATR-Based" : "Fixed Fractional"}
        </legend>
        <NumField
          id="calc-entry"
          label="Entry Price"
          register={register("entryPrice")}
          error={errors.entryPrice?.message}
          step="0.05"
        />
        {method !== "atr" && (
          <NumField
            id="calc-stop"
            label="Stop Loss"
            register={register("stopLossPrice")}
            error={errors.stopLossPrice?.message}
            step="0.05"
          />
        )}
        {method === "kelly" && (
          <>
            <NumField
              id="calc-winrate"
              label="Win Rate %"
              register={register("winRate")}
              error={errors.winRate?.message}
              step="1"
              min="1"
            />
            <NumField
              id="calc-rewardrisk"
              label="Reward : Risk"
              register={register("rewardRisk")}
              error={errors.rewardRisk?.message}
              step="0.1"
              min="0.1"
            />
          </>
        )}
        {method === "atr" && (
          <>
            <NumField
              id="calc-atr"
              label="ATR Value"
              register={register("atr")}
              error={errors.atr?.message}
              step="0.5"
              min="0.5"
            />
            <NumField
              id="calc-atrmult"
              label="ATR Multiplier"
              register={register("atrMultiplier")}
              error={errors.atrMultiplier?.message}
              step="0.1"
              min="0.1"
            />
          </>
        )}
      </fieldset>

      {/* Results */}
      {result ? (
        <div className="space-y-3">
          {/* Over-budget warning — one lot already breaches the stated risk */}
          {result.sized.exceedsRisk && (
            <div
              role="status"
              className="flex items-start gap-1.5 text-xxs text-warning bg-warning/10 border border-warning/30 rounded px-2 py-1.5 leading-snug"
            >
              <AlertTriangle size={11} className="mt-px shrink-0" aria-hidden="true" />
              <span>
                A single {unitNoun} risks {formatINR(result.sized.rupeeRisk)} — more than the{" "}
                {formatINR(result.budget)} you allowed. One {unitNoun} is shown because it is
                the smallest tradeable size; tighten the stop, reduce the lot size or raise
                your capital to stay within budget.
              </span>
            </div>
          )}

          {/* Capital at risk */}
          <div className="flex items-center gap-4 bg-surface-card border border-border-default rounded p-3">
            <PieChart atRiskFraction={result.sized.capitalAtRiskPct / 100} />
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1.5 text-xxs">
                <span className="w-2.5 h-2.5 rounded-sm bg-loss/60 inline-block shrink-0" />
                <span className="text-text-muted">At Risk</span>
                <span className="ml-auto font-mono font-semibold text-loss">
                  {result.sized.capitalAtRiskPct.toFixed(2)}%
                </span>
              </div>
              <div className="flex items-center gap-1.5 text-xxs">
                <span className="w-2.5 h-2.5 rounded-sm bg-profit/50 inline-block shrink-0" />
                <span className="text-text-muted">Available</span>
                <span className="ml-auto font-mono font-semibold text-profit">
                  {(100 - result.sized.capitalAtRiskPct).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>

          <div className="border border-border-default rounded p-2 bg-surface-card space-y-0.5">
            <p className="text-xxs text-text-muted uppercase tracking-wider mb-1">Results</p>
            <ResultRow label="Position Size (lots)" value={String(result.sized.lots)} />
            <ResultRow label="Units (shares)" value={String(result.sized.units)} />
            <ResultRow label="Position Value" value={formatINR(result.positionValue)} />
            <ResultRow label="SL Points" value={result.stopDistance.toFixed(2)} />
            {method === "atr" && (
              <ResultRow label="Stop Loss (from ATR)" value={formatINR(result.stopPrice)} />
            )}
            {method === "kelly" && (
              <ResultRow label="Kelly Stake" value={`${result.stakePct.toFixed(2)}%`} />
            )}
            <div className="border-t border-border-default my-1" />
            {/*
              Budget and actual are BOTH shown, always. They are not the same
              number: sizing floors to whole lots, so a ₹4,000 budget against a
              13-point stop buys 307 shares risking ₹3,991 — under budget by ₹9.
              The old surfaces printed the budget under the label "Risk Amount"
              and only revealed the real figure when it went OVER, which read as
              if the position risked exactly the budget every other time.
            */}
            <ResultRow label="Risk Budget" value={formatINR(result.budget)} />
            <ResultRow
              label="Actual Risk"
              value={formatINR(result.sized.rupeeRisk)}
              highlight={result.sized.exceedsRisk ? "warning" : "loss"}
            />
          </div>
        </div>
      ) : (
        <div className="text-xs text-text-muted text-center py-4">
          Fill in all fields to see position size
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Target / R:R tab
// ---------------------------------------------------------------------------

function TargetTab({ form, values, errors }: TabProps) {
  const { register, control } = form;

  const entry = num(values.entryPrice);
  const stop = num(values.stopLossPrice);
  const side = effectiveSide(entry, stop, (values.side ?? "BUY") as TradeSide);

  const result = useMemo(
    () =>
      computeTarget({
        entryPrice: entry,
        stopLossPrice: stop,
        targetPrice: num(values.targetPrice),
        riskRewardRatio: num(values.riskRewardRatio),
        quantity: num(values.quantity),
        lotSize: num(values.lotSize),
        side,
      }),
    [values, entry, stop, side],
  );

  return (
    <div className="flex flex-col gap-3 overflow-auto h-full p-3">
      <fieldset className="space-y-2">
        <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
          Trade Parameters
        </legend>
        <NumField
          id="target-entry"
          label="Entry Price"
          register={register("entryPrice")}
          error={errors.entryPrice?.message}
          step="0.05"
        />
        <NumField
          id="target-stop"
          label="Stop Loss"
          register={register("stopLossPrice")}
          error={errors.stopLossPrice?.message}
          step="0.05"
        />
        <NumField
          id="target-price"
          label="Target Price"
          register={register("targetPrice")}
          step="0.05"
          placeholder="Leave empty for auto"
        />
        <div className="flex items-center gap-2">
          <Label htmlFor="target-rr" className="text-xs text-text-muted w-32 shrink-0">
            Target R:R
          </Label>
          <div className="flex-1 min-w-0">
            <Controller
              name="riskRewardRatio"
              control={control}
              render={({ field }) => (
                <Select
                  value={String(field.value)}
                  onValueChange={(v) => field.onChange(Number(v))}
                >
                  <SelectTrigger id="target-rr" className={selectCls}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default text-xs">
                    {[1, 1.5, 2, 2.5, 3, 4, 5].map((v) => (
                      <SelectItem key={v} value={String(v)}>
                        {formatRR(v)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>
        <NumField
          id="target-qty"
          label="Quantity (lots)"
          register={register("quantity")}
          error={errors.quantity?.message}
          min="1"
        />
        <NumField
          id="target-lotsize"
          label="Lot Size"
          register={register("lotSize")}
          error={errors.lotSize?.message}
          min="1"
        />
      </fieldset>

      {result ? (
        <div className="space-y-2">
          <div className="space-y-1">
            <div className="text-xxs text-text-muted uppercase tracking-wide">
              Risk / Reward Ratio
            </div>
            <RRBar rrRatio={result.rrRatio} />
          </div>

          <div className="bg-surface-card border border-border-default rounded p-2 space-y-0.5">
            <ResultRow
              label="Target"
              value={formatINR(result.targetPrice)}
              highlight="profit"
            />
            <ResultRow label="Reward Points" value={result.rewardPoints.toFixed(2)} />
            <ResultRow
              label="Risk per Trade"
              value={formatINR(result.riskPerTrade)}
              highlight="loss"
            />
            <ResultRow
              label="Potential Profit"
              value={formatINR(result.potentialProfit)}
              highlight="profit"
            />
            <ResultRow
              label="R:R Ratio"
              value={formatRR(result.rrRatio)}
              highlight={result.rrRatio >= 2 ? "profit" : result.rrRatio >= 1 ? "neutral" : "loss"}
            />
            <ResultRow
              label="Breakeven Win Rate"
              value={`${result.breakEvenWinRate.toFixed(1)}%`}
            />
          </div>

          {result.derived && (
            <p className="text-xxs text-text-muted leading-snug">
              Target derived from the stop distance at {formatRR(result.rrRatio)}. Type a
              target price to override it.
            </p>
          )}

          {/* Breakeven insight — the reason Profit Target existed */}
          <div className="bg-surface-card border border-border-default rounded px-2 py-1.5 text-xs text-text-secondary">
            Win at least{" "}
            <span className="font-semibold text-text-primary">
              {result.breakEvenWinRate.toFixed(0)}%
            </span>{" "}
            of your trades to break even at this R:R.
          </div>
        </div>
      ) : (
        <div className="text-xs text-text-muted text-center py-4">
          Enter entry, stop loss and target to see results
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Brokerage calculator (April 1 2026 STT rates)
// ---------------------------------------------------------------------------
const STT_RATE_FUTURES = 0.0005;   // 0.05%
const STT_RATE_OPTIONS = 0.0015;   // 0.15% (on premium)
const SEBI_CHARGE = 0.000001;      // ₹10 per crore
const EXCHANGE_TXN = 0.0000325;    // NSE 0.00325%
const STAMP_DUTY = 0.00003;        // 0.003% (buy side only)
const GST_RATE = 0.18;

interface BrokerageResult {
  stt: number;
  exchangeTxn: number;
  sebi: number;
  stampDuty: number;
  brokerage: number;
  gst: number;
  total: number;
  breakeven: number;
}

function calculateBrokerage(
  lotSize: number,
  lots: number,
  price: number,
  type: "futures" | "options",
  flatBrokerage: number,
  side: "BUY" | "SELL" | "BOTH",
): BrokerageResult {
  const qty = lotSize * lots;
  const turnover = qty * price;
  const sides = side === "BOTH" ? 2 : 1;

  const sttRate = type === "futures" ? STT_RATE_FUTURES : STT_RATE_OPTIONS;
  const stt = turnover * sttRate * (type === "futures" ? sides : 1); // options: sell side only

  const exchangeTxn = turnover * EXCHANGE_TXN * sides;
  const sebi = turnover * SEBI_CHARGE * sides;
  const stampDuty = turnover * STAMP_DUTY * (side === "SELL" ? 0 : 1);
  const brokerage = flatBrokerage * sides;
  const subTotal = stt + exchangeTxn + sebi + stampDuty + brokerage;
  const gst = (brokerage + exchangeTxn + sebi) * GST_RATE;
  const total = subTotal + gst;
  const breakeven = qty > 0 ? total / qty : 0;

  return { stt, exchangeTxn, sebi, stampDuty, brokerage, gst, total, breakeven };
}

const brokerageSchema = z.object({
  lotSize: z.coerce.number().min(1, "Min 1"),
  lots: z.coerce.number().min(1, "Min 1"),
  price: z.coerce.number().min(0.05, "Required"),
  type: z.enum(["futures", "options"]),
  side: z.enum(["BUY", "SELL", "BOTH"]),
  flatBrokerage: z.coerce.number().min(0),
});

type BrokerageFormValues = z.infer<typeof brokerageSchema>;

function BrokerageCalcTab() {
  const {
    register,
    control,
    watch,
    formState: { errors },
  } = useForm<BrokerageFormValues>({
    // zod v4 + @hookform/resolvers v5 type mismatch with z.coerce — safe at runtime
    resolver: zodResolver(brokerageSchema) as unknown as Resolver<BrokerageFormValues>,
    defaultValues: {
      lotSize: 25,
      lots: 1,
      price: 100,
      type: "options",
      side: "BOTH",
      flatBrokerage: 20,
    },
    mode: "onChange",
  });

  const values = watch();

  const result = useMemo<BrokerageResult>(() => {
    return calculateBrokerage(
      num(values.lotSize),
      num(values.lots),
      num(values.price),
      values.type,
      num(values.flatBrokerage),
      values.side,
    );
  }, [values]);

  return (
    <div className="flex flex-col gap-3 overflow-auto h-full p-3">
      {/* Note about new STT rates */}
      <div className="text-xs text-warning/70 bg-warning/10 border border-warning/30 rounded px-2 py-1 leading-tight">
        STT rates from Apr 1 2026 — Futures: 0.05%, Options: 0.15% (on premium)
      </div>

      <fieldset className="space-y-2">
        <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
          Contract
        </legend>

        <div className="flex items-center gap-2">
          <Label htmlFor="brk-type" className="text-xs text-text-muted w-32 shrink-0">
            Instrument
          </Label>
          <div className="flex-1 min-w-0">
            <Controller
              name="type"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="brk-type" className={selectCls}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default text-xs">
                    <SelectItem value="futures">Futures</SelectItem>
                    <SelectItem value="options">Options</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Label htmlFor="brk-side" className="text-xs text-text-muted w-32 shrink-0">
            Side
          </Label>
          <div className="flex-1 min-w-0">
            <Controller
              name="side"
              control={control}
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger id="brk-side" className={selectCls}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default text-xs">
                    <SelectItem value="BUY">Buy Only</SelectItem>
                    <SelectItem value="SELL">Sell Only</SelectItem>
                    <SelectItem value="BOTH">Round Trip</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </div>
        </div>

        <NumField
          id="brk-lotsize"
          label="Lot Size"
          register={register("lotSize")}
          error={errors.lotSize?.message}
          min="1"
        />
        <NumField
          id="brk-lots"
          label="Lots"
          register={register("lots")}
          error={errors.lots?.message}
          min="1"
        />
        <NumField
          id="brk-price"
          label="Price (₹)"
          register={register("price")}
          error={errors.price?.message}
          step="0.05"
        />
        <NumField
          id="brk-flat"
          label="Flat Brokerage (₹)"
          register={register("flatBrokerage")}
          error={errors.flatBrokerage?.message}
          step="1"
        />
      </fieldset>

      {/* Results */}
      <div className="border border-border-default rounded p-2 bg-surface-card space-y-0.5">
        <p className="text-xxs text-text-muted uppercase tracking-wider mb-1">Charges Breakdown</p>
        <ResultRow label="Brokerage" value={formatINR(result.brokerage)} />
        <ResultRow label="STT" value={formatINR(result.stt)} />
        <ResultRow label="Exchange Txn" value={formatINR(result.exchangeTxn)} />
        <ResultRow label="SEBI" value={formatINR(result.sebi)} />
        <ResultRow label="Stamp Duty" value={formatINR(result.stampDuty)} />
        <ResultRow label="GST (18%)" value={formatINR(result.gst)} />
        <div className="border-t border-border-default my-1" />
        <ResultRow label="Total Cost" value={formatINR(result.total)} highlight="loss" />
        <ResultRow label="Breakeven/Unit" value={`₹${result.breakeven.toFixed(3)}`} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Margin calculator — SPAN-like SEBI formulas + live API
// ---------------------------------------------------------------------------

/** SEBI-mandated minimum margin rates (approximate SPAN + exposure) */
const SPAN_RATES: Record<string, number> = {
  NRML: 0.15,  // 15% of notional for NRML F&O positions
  MIS:  0.075, // 7.5% for intraday (50% haircut)
  CNC:  0.20,  // 20% for delivery equity
  BO:   0.075,
  CO:   0.075,
};

/** SPAN component is ~60%, exposure ~40% of total SEBI margin */
const SPAN_FRACTION     = 0.60;
const EXPOSURE_FRACTION = 0.40;

interface MarginFormValues {
  symbol:      string;
  exchange:    string;
  action:      "BUY" | "SELL";
  quantity:    number;
  product:     "NRML" | "MIS" | "CNC" | "BO" | "CO";
  price:       number;
  // multi-leg
  legs:        number;
}

const marginSchema = z.object({
  symbol:   z.string().min(1, "Required"),
  exchange: z.string().min(1, "Required"),
  action:   z.enum(["BUY", "SELL"]),
  quantity: z.coerce.number().min(1, "Min 1"),
  product:  z.enum(["NRML", "MIS", "CNC", "BO", "CO"]),
  price:    z.coerce.number().min(0.01, "Required"),
  legs:     z.coerce.number().min(1).max(10),
});

interface MarginCalcState {
  authority:      AccountAuthorityIdentity | null;
  spanMargin:     number;
  exposureMargin: number;
  totalMargin:    number;
  availableCash:  number | null;
  source:         "api" | "estimate";
  loading:        boolean;
  error:          string | null;
}

function initialMarginCalcState(): MarginCalcState {
  return {
    authority: null,
    spanMargin: 0,
    exposureMargin: 0,
    totalMargin: 0,
    availableCash: null,
    source: "estimate",
    loading: false,
    error: null,
  };
}

function MarginCalcTab() {
  const accountReadContext = useAccountReadContext();
  const currentContextRef = useRef(accountReadContext);
  const fundsControllerRef = useRef<AbortController | null>(null);
  const requestIdRef = useRef(0);
  currentContextRef.current = accountReadContext;
  const {
    register,
    control,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<MarginFormValues>({
    // zod v4 + @hookform/resolvers v5 type mismatch with z.coerce — safe at runtime
    resolver: zodResolver(marginSchema) as unknown as Resolver<MarginFormValues>,
    defaultValues: {
      symbol:   "NIFTY",
      exchange: "NFO",
      action:   "BUY",
      quantity: 25,
      product:  "NRML",
      price:    100,
      legs:     1,
    },
    mode: "onChange",
  });

  const [calcState, setCalcState] = useState<MarginCalcState>(initialMarginCalcState);

  useEffect(() => {
    requestIdRef.current += 1;
    fundsControllerRef.current?.abort();
    fundsControllerRef.current = null;
    setCalcState(initialMarginCalcState());
    return () => {
      requestIdRef.current += 1;
      fundsControllerRef.current?.abort();
      fundsControllerRef.current = null;
    };
  }, [
    accountReadContext.enabled,
    accountReadContext.identity.accountId,
    accountReadContext.identity.brokerType,
    accountReadContext.identity.mode,
    accountReadContext.identity.scopeKey,
  ]);

  const values = watch();

  /** Estimate margin using SEBI SPAN-like formula when API is unavailable */
  const estimateMargin = useCallback(
    (vals: MarginFormValues): Pick<MarginCalcState, "spanMargin" | "exposureMargin" | "totalMargin" | "source"> => {
      const notional = num(vals.price) * num(vals.quantity) * num(vals.legs);
      const rate     = SPAN_RATES[vals.product] ?? 0.15;
      const total    = notional * rate;
      return {
        spanMargin:     total * SPAN_FRACTION,
        exposureMargin: total * EXPOSURE_FRACTION,
        totalMargin:    total,
        source:         "estimate",
      };
    },
    [],
  );

  const onCalculate = useCallback(
    async (vals: MarginFormValues) => {
      const context = accountReadContext;
      const identity = captureAccountAuthority(context.identity);
      if (!context.enabled) {
        requestIdRef.current += 1;
        fundsControllerRef.current?.abort();
        fundsControllerRef.current = null;
        setCalcState({ ...initialMarginCalcState(), authority: identity, error: "Broker required" });
        return;
      }

      const requestId = ++requestIdRef.current;
      fundsControllerRef.current?.abort();
      const controller = new AbortController();
      fundsControllerRef.current = controller;
      const isCurrent = () => (
        requestId === requestIdRef.current
        && !controller.signal.aborted
        && currentContextRef.current.enabled
        && accountAuthorityMatches(identity, currentContextRef.current.identity)
      );
      setCalcState((state) => ({
        ...(state.authority != null && accountAuthorityMatches(state.authority, identity)
          ? state
          : initialMarginCalcState()),
        authority: identity,
        loading: true,
        error: null,
      }));

      let funds: Funds | null = null;
      try {
        funds = await getFunds(context, controller.signal);
      } catch {
        if (!isCurrent()) return;
        // non-fatal — we just won't show comparison
      }
      if (!isCurrent()) return;

      try {
        const marginData: MarginData = await getMargin(
          context,
          vals.symbol,
          vals.exchange,
          num(vals.quantity) * num(vals.legs),
          vals.product,
          vals.action,
          controller.signal,
        );
        if (!isCurrent()) return;
        setCalcState({
          authority:      identity,
          spanMargin:     marginData.span_margin,
          exposureMargin: marginData.exposure_margin,
          totalMargin:    marginData.total_margin_required,
          availableCash:  funds?.availableCash ?? null,
          source:         "api",
          loading:        false,
          error:          null,
        });
      } catch {
        if (!isCurrent()) return;
        // Fall back to estimate
        const estimate = estimateMargin(vals);
        setCalcState({
          ...estimate,
          authority:     identity,
          availableCash: funds?.availableCash ?? null,
          loading:       false,
          error:         "API unavailable — showing estimate",
        });
      } finally {
        if (fundsControllerRef.current === controller) {
          fundsControllerRef.current = null;
        }
      }
    },
    [accountReadContext, estimateMargin],
  );

  // Live estimate on form change (no API call)
  const liveEstimate = useMemo(() => estimateMargin(values), [values, estimateMargin]);
  const visibleCalcState = calcState.authority == null
    || accountAuthorityMatches(calcState.authority, accountReadContext.identity)
    ? calcState
    : initialMarginCalcState();

  const hasSufficient =
    visibleCalcState.availableCash != null
      ? visibleCalcState.availableCash >= visibleCalcState.totalMargin
      : null;

  const displayTotal = visibleCalcState.totalMargin > 0
    ? visibleCalcState.totalMargin
    : liveEstimate.totalMargin;
  const displaySpan = visibleCalcState.totalMargin > 0
    ? visibleCalcState.spanMargin
    : liveEstimate.spanMargin;
  const displayExposure = visibleCalcState.totalMargin > 0
    ? visibleCalcState.exposureMargin
    : liveEstimate.exposureMargin;

  return (
    <div className="flex flex-col gap-3 overflow-auto h-full p-3">
      <div className="text-xs text-text-muted/70 bg-surface-card border border-border-default rounded px-2 py-1 leading-tight">
        Live margin via OpenAlgo API. Estimates use SEBI SPAN-like rates (NRML 15%, MIS 7.5%).
      </div>

      <form onSubmit={handleSubmit(onCalculate)} className="flex flex-col gap-2">
        <fieldset className="space-y-2">
          <legend className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">
            Contract
          </legend>

          <div className="flex items-center gap-2">
            <Label htmlFor="mgn-symbol" className="text-xs text-text-muted w-32 shrink-0">
              Symbol
            </Label>
            <div className="flex-1 min-w-0">
              <Input
                id="mgn-symbol"
                {...register("symbol")}
                className={`h-7 text-xs font-mono bg-surface-card border-border-default text-text-primary ${
                  errors.symbol ? "border-loss" : ""
                }`}
                placeholder="NIFTY"
              />
              {errors.symbol && <p className="text-loss text-xxs mt-0.5">{errors.symbol.message}</p>}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Label htmlFor="mgn-exchange" className="text-xs text-text-muted w-32 shrink-0">
              Exchange
            </Label>
            <div className="flex-1 min-w-0">
              <Controller
                name="exchange"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="mgn-exchange" className={selectCls}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-surface-card border-border-default text-xs">
                      <SelectItem value="NFO">NFO</SelectItem>
                      <SelectItem value="NSE">NSE</SelectItem>
                      <SelectItem value="BSE">BSE</SelectItem>
                      <SelectItem value="BFO">BFO</SelectItem>
                      <SelectItem value="MCX">MCX</SelectItem>
                      <SelectItem value="CDS">CDS</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Label htmlFor="mgn-action" className="text-xs text-text-muted w-32 shrink-0">
              Action
            </Label>
            <div className="flex-1 min-w-0">
              <Controller
                name="action"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="mgn-action" className={selectCls}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-surface-card border-border-default text-xs">
                      <SelectItem value="BUY">BUY</SelectItem>
                      <SelectItem value="SELL">SELL</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>

          <NumField
            id="mgn-qty"
            label="Quantity"
            register={register("quantity")}
            error={errors.quantity?.message}
            min="1"
          />
          <NumField
            id="mgn-legs"
            label="Legs (multi-leg)"
            register={register("legs")}
            error={errors.legs?.message}
            min="1"
          />
          <NumField
            id="mgn-price"
            label="Price (₹)"
            register={register("price")}
            error={errors.price?.message}
            step="0.05"
          />

          <div className="flex items-center gap-2">
            <Label htmlFor="mgn-product" className="text-xs text-text-muted w-32 shrink-0">
              Product
            </Label>
            <div className="flex-1 min-w-0">
              <Controller
                name="product"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger id="mgn-product" className={selectCls}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-surface-card border-border-default text-xs">
                      <SelectItem value="NRML">NRML</SelectItem>
                      <SelectItem value="MIS">MIS</SelectItem>
                      <SelectItem value="CNC">CNC</SelectItem>
                      <SelectItem value="BO">BO</SelectItem>
                      <SelectItem value="CO">CO</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </div>
          </div>
        </fieldset>

        <button
          type="submit"
          disabled={visibleCalcState.loading}
          className="h-6 text-xs bg-accent/20 hover:bg-accent/30 text-accent border border-accent/40 rounded font-medium transition-colors disabled:opacity-50"
        >
          {visibleCalcState.loading ? "Fetching…" : "Get Live Margin"}
        </button>
      </form>

      {/* Results */}
      <div className="border border-border-default rounded p-2 bg-surface-card space-y-0.5">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xxs text-text-muted uppercase tracking-wider">Margin Required</p>
          <span className="text-xxs font-mono bg-surface-hover text-text-muted border border-border-default rounded px-1">
            {visibleCalcState.source === "api" ? "LIVE" : "ESTIMATE"}
          </span>
        </div>

        {visibleCalcState.error && (
          <p className="text-xxs text-warning mb-1">{visibleCalcState.error}</p>
        )}

        <ResultRow label="SPAN Margin"     value={formatINR(displaySpan)} />
        <ResultRow label="Exposure Margin" value={formatINR(displayExposure)} />
        <div className="border-t border-border-default my-1" />
        <ResultRow label="Total Required"  value={formatINR(displayTotal)} highlight="loss" />

        {visibleCalcState.availableCash != null && (
          <>
            <div className="border-t border-border-default my-1" />
            <ResultRow
              label="Available Funds"
              value={formatINR(visibleCalcState.availableCash)}
              highlight={hasSufficient === true ? "profit" : hasSufficient === false ? "loss" : "neutral"}
            />
            <ResultRow
              label="After Margin"
              value={formatINR(visibleCalcState.availableCash - displayTotal)}
              highlight={(visibleCalcState.availableCash - displayTotal) >= 0 ? "profit" : "loss"}
            />
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget entry point
// ---------------------------------------------------------------------------

const TRIGGER_CLS =
  "text-xs h-5 px-2 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted rounded";

function CalculatorWidget(props: WidgetProps) {
  const panelParams = props.params as CalculatorPanelParams | undefined;
  const track = useTrackBehavior();
  const [tab, setTab] = useState<CalculatorTab>(() => resolveCalculatorTab(panelParams?.tab));
  const [method, setMethod] = useState<SizingMethod>("fixedFractional");

  const form = useForm<TradeFormValues>({
    // zod v4 + @hookform/resolvers v5 type mismatch with z.coerce — safe at runtime
    resolver: zodResolver(tradeSchema) as unknown as Resolver<TradeFormValues>,
    defaultValues: TRADE_DEFAULTS,
    mode: "onChange",
  });

  // Watched here rather than in the tabs: `watch()` re-renders the component
  // that owns the form, so the subscription has to live at this level for the
  // tab bodies to see every keystroke.
  const values = form.watch();
  const errors = form.formState.errors;

  // Persist the chosen tab into the panel params so a saved layout reopens on
  // it — this is also how the retired positionsizing/profittarget ids land on
  // the surface their operators used.
  const handleTabChange = useCallback(
    (next: string) => {
      const resolved = resolveCalculatorTab(next);
      if (resolved === tab) return;
      setTab(resolved);
      props.api?.updateParameters({ tab: resolved });
    },
    [props.api, tab],
  );

  // Behaviour tracking is a side effect, so it belongs in an effect rather than
  // in a memo — inside one it fired on every keystroke and ran twice under
  // StrictMode.
  useEffect(() => {
    track("trade", `calculator_tab_${tab}`);
  }, [tab, track]);

  const handleMethodChange = useCallback(
    (next: SizingMethod) => {
      setMethod(next);
      track("trade", `calculator_sizing_${next}`);
    },
    [track],
  );

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default shrink-0">
        <Calculator size={11} className="text-text-muted" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
          Calculator
        </span>
      </div>

      {/* Tabs */}
      <Tabs
        value={tab}
        onValueChange={handleTabChange}
        className="flex-1 flex flex-col overflow-hidden"
      >
        <TabsList
          aria-label="Calculator sections"
          className="shrink-0 h-7 bg-surface-card rounded-none border-b border-border-default px-2 gap-1 justify-start"
        >
          <TabsTrigger value="sizing" className={TRIGGER_CLS}>
            <Ruler size={9} className="mr-1" />
            Sizing
          </TabsTrigger>
          <TabsTrigger value="target" className={TRIGGER_CLS}>
            <Target size={9} className="mr-1" />
            Target / R:R
          </TabsTrigger>
          <TabsTrigger value="brokerage" className={TRIGGER_CLS}>
            <Receipt size={9} className="mr-1" />
            Brokerage
          </TabsTrigger>
          <TabsTrigger value="margin" className={TRIGGER_CLS}>
            <Layers size={9} className="mr-1" />
            Margin
          </TabsTrigger>
        </TabsList>

        <TabsContent value="sizing" className="flex-1 overflow-auto m-0 p-0">
          <SizingTab
            form={form}
            values={values}
            errors={errors}
            method={method}
            onMethodChange={handleMethodChange}
          />
        </TabsContent>
        <TabsContent value="target" className="flex-1 overflow-auto m-0 p-0">
          <TargetTab form={form} values={values} errors={errors} />
        </TabsContent>
        <TabsContent value="brokerage" className="flex-1 overflow-auto m-0 p-0">
          <BrokerageCalcTab />
        </TabsContent>
        <TabsContent value="margin" className="flex-1 overflow-auto m-0 p-0">
          <MarginCalcTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default memo(CalculatorWidget);
