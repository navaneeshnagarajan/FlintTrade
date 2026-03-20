/**
 * CalculatorWidget
 *
 * Absorbed from:
 *   openalgo-chart/src/components/RiskCalculatorPanel/RiskCalculatorPanel.tsx
 *   openalgo-chart/src/utils/indicators/riskCalculator.ts
 *
 * Adaptations:
 * - CSS Modules → Tailwind CSS v4
 * - shadcn: Input, Select, Card, Tabs, Button, Label
 * - react-hook-form + zod for form validation
 * - Added Brokerage Calculator tab with April 2026 STT rates
 *   (Futures STT 0.05%, Options STT 0.15%)
 * - Templates: conservative (1%), balanced (2%), aggressive (3%)
 * - Removed draggable/overlay shell; inline widget
 */

import { useMemo } from "react";
import { useForm, Controller } from "react-hook-form";
import type { Resolver } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Calculator, TrendingUp } from "lucide-react";
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

// ---------------------------------------------------------------------------
// Risk calculation engine (absorbed from riskCalculator.ts)
// ---------------------------------------------------------------------------
type TradeSide = "BUY" | "SELL";

interface RiskCalcParams {
  capital: number;
  riskPercent: number;
  entryPrice: number;
  stopLossPrice: number;
  targetPrice?: number;
  riskRewardRatio: number;
  side: TradeSide;
}

interface RiskCalcResult {
  riskAmount: number;
  slPoints: number;
  quantity: number;
  positionValue: number;
  targetPrice: number;
  rewardPoints: number;
  rewardAmount: number;
  rrRatio: number;
}

function calculateRiskPosition(params: RiskCalcParams): RiskCalcResult | null {
  const { capital, riskPercent, entryPrice, stopLossPrice, targetPrice, riskRewardRatio, side } =
    params;

  if (capital <= 0 || riskPercent <= 0 || entryPrice <= 0 || stopLossPrice <= 0) return null;

  const riskAmount = capital * (riskPercent / 100);
  const slPoints = Math.abs(entryPrice - stopLossPrice);
  if (slPoints <= 0) return null;

  if (side === "BUY" && entryPrice <= stopLossPrice) return null;
  if (side === "SELL" && entryPrice >= stopLossPrice) return null;

  const quantity = Math.floor(riskAmount / slPoints);
  if (quantity <= 0) return null;

  const positionValue = quantity * entryPrice;
  let finalTarget: number;
  let finalRR: number;

  if (targetPrice && targetPrice > 0) {
    if (side === "BUY" && targetPrice <= entryPrice) return null;
    if (side === "SELL" && targetPrice >= entryPrice) return null;
    finalTarget = targetPrice;
    finalRR = Math.abs(targetPrice - entryPrice) / slPoints;
  } else {
    finalRR = riskRewardRatio;
    finalTarget =
      side === "BUY"
        ? entryPrice + slPoints * finalRR
        : entryPrice - slPoints * finalRR;
  }

  const rewardPoints = Math.abs(finalTarget - entryPrice);
  const rewardAmount = rewardPoints * quantity;

  return { riskAmount, slPoints, quantity, positionValue, targetPrice: finalTarget, rewardPoints, rewardAmount, rrRatio: finalRR };
}

// Auto-detect side from entry vs SL (absorbed from riskCalculator.ts)
function autoDetectSide(entry: number, sl: number): TradeSide | null {
  if (entry <= 0 || sl <= 0 || entry === sl) return null;
  return sl > entry ? "SELL" : "BUY";
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

// ---------------------------------------------------------------------------
// Templates (absorbed from TemplateSelector concept)
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
// Zod schemas
// ---------------------------------------------------------------------------
const riskSchema = z.object({
  capital: z.coerce.number().min(1000, "Min ₹1,000"),
  riskPercent: z.coerce.number().min(0.1, "Min 0.1%").max(10, "Max 10%"),
  side: z.enum(["BUY", "SELL"]),
  entryPrice: z.coerce.number().min(0.01, "Required"),
  stopLossPrice: z.coerce.number().min(0.01, "Required"),
  targetPrice: z.coerce.number().optional(),
  riskRewardRatio: z.coerce.number().min(0.5).max(10),
});

type RiskFormValues = z.infer<typeof riskSchema>;

const brokerageSchema = z.object({
  lotSize: z.coerce.number().min(1, "Min 1"),
  lots: z.coerce.number().min(1, "Min 1"),
  price: z.coerce.number().min(0.05, "Required"),
  type: z.enum(["futures", "options"]),
  side: z.enum(["BUY", "SELL", "BOTH"]),
  flatBrokerage: z.coerce.number().min(0),
});

type BrokerageFormValues = z.infer<typeof brokerageSchema>;

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------
const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });
const formatINR = (n: number) => `\u20B9${INR.format(n)}`;

// ---------------------------------------------------------------------------
// Row component for results
// ---------------------------------------------------------------------------
function ResultRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "profit" | "loss" | "neutral";
}) {
  const color =
    highlight === "profit"
      ? "text-profit"
      : highlight === "loss"
      ? "text-loss"
      : "text-text-primary";
  return (
    <div className="flex justify-between items-center py-0.5">
      <span className="text-text-muted text-xs">{label}</span>
      <span className={`font-mono tabular-nums text-xs font-medium ${color}`}>{value}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Risk Calculator tab
// ---------------------------------------------------------------------------
function RiskCalcTab() {
  const {
    register,
    control,
    watch,
    setValue,
    formState: { errors },
  } = useForm<RiskFormValues>({
    resolver: zodResolver(riskSchema) as Resolver<RiskFormValues>,
    defaultValues: {
      capital: 200_000,
      riskPercent: 2,
      side: "BUY",
      entryPrice: 0,
      stopLossPrice: 0,
      targetPrice: undefined,
      riskRewardRatio: 2,
    },
    mode: "onChange",
  });

  const values = watch();

  // Auto-detect side
  const entry = Number(values.entryPrice);
  const sl = Number(values.stopLossPrice);
  const autoSide = entry > 0 && sl > 0 ? autoDetectSide(entry, sl) : null;
  const effectiveSide: TradeSide = (autoSide ?? values.side ?? "BUY") as TradeSide;

  const result = useMemo<RiskCalcResult | null>(() => {
    return calculateRiskPosition({
      capital: Number(values.capital),
      riskPercent: Number(values.riskPercent),
      entryPrice: entry,
      stopLossPrice: sl,
      targetPrice: values.targetPrice ? Number(values.targetPrice) : undefined,
      riskRewardRatio: Number(values.riskRewardRatio),
      side: effectiveSide,
    });
  }, [values, entry, sl, effectiveSide]);

  const applyTemplate = (t: Template) => {
    setValue("capital", t.capital);
    setValue("riskPercent", t.riskPercent);
    setValue("riskRewardRatio", t.riskRewardRatio);
  };

  const fieldCls = (err?: { message?: string }) =>
    `h-6 text-xs bg-surface-card border-border-default text-text-primary font-mono px-1.5 ${
      err ? "border-loss" : ""
    }`;

  return (
    <div className="flex flex-col gap-2 overflow-auto h-full p-3">
      {/* Templates */}
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

      {/* Form grid */}
      <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Capital (₹)</Label>
          <Input {...register("capital")} className={fieldCls(errors.capital)} placeholder="200000" />
          {errors.capital && <p className="text-loss text-xxs mt-0.5">{errors.capital.message}</p>}
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Risk %</Label>
          <Input {...register("riskPercent")} className={fieldCls(errors.riskPercent)} placeholder="2" step="0.1" type="number" />
          {errors.riskPercent && <p className="text-loss text-xxs mt-0.5">{errors.riskPercent.message}</p>}
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Side</Label>
          <Controller
            name="side"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger className={fieldCls()}>
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

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">R:R Ratio</Label>
          <Controller
            name="riskRewardRatio"
            control={control}
            render={({ field }) => (
              <Select value={String(field.value)} onValueChange={(v) => field.onChange(Number(v))}>
                <SelectTrigger className={fieldCls()}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent className="bg-surface-card border-border-default text-xs">
                  {[1, 1.5, 2, 2.5, 3, 4, 5].map((v) => (
                    <SelectItem key={v} value={String(v)}>1:{v}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Entry Price</Label>
          <Input {...register("entryPrice")} className={fieldCls(errors.entryPrice)} placeholder="0.00" step="0.05" type="number" />
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Stop Loss</Label>
          <Input {...register("stopLossPrice")} className={fieldCls(errors.stopLossPrice)} placeholder="0.00" step="0.05" type="number" />
        </div>

        <div className="col-span-2">
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Target Price (optional)</Label>
          <Input {...register("targetPrice")} className={fieldCls()} placeholder="Leave empty for auto" step="0.05" type="number" />
        </div>
      </div>

      {/* Results */}
      {result ? (
        <div className="border border-border-default rounded p-2 bg-surface-card space-y-0.5">
          <p className="text-xxs text-text-muted uppercase tracking-wider mb-1">Results</p>
          <ResultRow label="Quantity" value={`${result.quantity.toLocaleString("en-IN")} shares`} highlight="neutral" />
          <ResultRow label="Position Value" value={formatINR(result.positionValue)} />
          <ResultRow label="Risk Amount" value={formatINR(result.riskAmount)} highlight="loss" />
          <ResultRow label="SL Points" value={result.slPoints.toFixed(2)} />
          <div className="border-t border-border-default my-1" />
          <ResultRow label="Target" value={formatINR(result.targetPrice)} highlight="profit" />
          <ResultRow label="Reward Points" value={result.rewardPoints.toFixed(2)} />
          <ResultRow label="Reward Amount" value={formatINR(result.rewardAmount)} highlight="profit" />
          <div className="border-t border-border-default my-1" />
          <ResultRow
            label="Risk : Reward"
            value={`1 : ${Number.isInteger(result.rrRatio) ? result.rrRatio : result.rrRatio.toFixed(2)}`}
            highlight={result.rrRatio >= 2 ? "profit" : result.rrRatio >= 1 ? "neutral" : "loss"}
          />
        </div>
      ) : (
        <div className="text-xs text-text-disabled text-center py-2">
          Enter entry and stop loss prices to calculate
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Brokerage Calculator tab
// ---------------------------------------------------------------------------
function BrokerageCalcTab() {
  const {
    register,
    control,
    watch,
    formState: { errors },
  } = useForm<BrokerageFormValues>({
    resolver: zodResolver(brokerageSchema) as Resolver<BrokerageFormValues>,
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
      Number(values.lotSize),
      Number(values.lots),
      Number(values.price),
      values.type,
      Number(values.flatBrokerage),
      values.side,
    );
  }, [values]);

  const fieldCls = (err?: { message?: string }) =>
    `h-6 text-xs bg-surface-card border-border-default text-text-primary font-mono px-1.5 ${
      err ? "border-loss" : ""
    }`;

  return (
    <div className="flex flex-col gap-2 overflow-auto h-full p-3">
      {/* Note about new STT rates */}
      <div className="text-xs text-warning/70 bg-warning/10 border border-warning/30 rounded px-2 py-1 leading-tight">
        STT rates from Apr 1 2026 — Futures: 0.05%, Options: 0.15% (on premium)
      </div>

      <div className="grid grid-cols-2 gap-x-2 gap-y-1.5">
        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Instrument</Label>
          <Controller
            name="type"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger className={fieldCls()}>
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

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Side</Label>
          <Controller
            name="side"
            control={control}
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange}>
                <SelectTrigger className={fieldCls()}>
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

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Lot Size</Label>
          <Input {...register("lotSize")} className={fieldCls(errors.lotSize)} type="number" placeholder="25" />
          {errors.lotSize && <p className="text-loss text-xxs">{errors.lotSize.message}</p>}
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Lots</Label>
          <Input {...register("lots")} className={fieldCls(errors.lots)} type="number" placeholder="1" />
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Price (₹)</Label>
          <Input {...register("price")} className={fieldCls(errors.price)} type="number" step="0.05" placeholder="100" />
        </div>

        <div>
          <Label className="text-xxs uppercase tracking-wider text-text-muted">Flat Brokerage (₹)</Label>
          <Input {...register("flatBrokerage")} className={fieldCls()} type="number" step="1" placeholder="20" />
        </div>
      </div>

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
        <ResultRow
          label="Breakeven/Unit"
          value={`\u20B9${result.breakeven.toFixed(3)}`}
          highlight="neutral"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Widget entry point
// ---------------------------------------------------------------------------
export default function CalculatorWidget(_props: WidgetProps) {
  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2 py-1 border-b border-border-default shrink-0">
        <Calculator size={11} className="text-text-muted" />
        <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">Calculator</span>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="risk" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="shrink-0 h-7 bg-surface-card rounded-none border-b border-border-default px-2 gap-1 justify-start">
          <TabsTrigger
            value="risk"
            className="text-xs h-5 px-2 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted rounded"
          >
            <TrendingUp size={9} className="mr-1" />
            Risk / Reward
          </TabsTrigger>
          <TabsTrigger
            value="brokerage"
            className="text-xs h-5 px-2 data-[state=active]:bg-surface-elevated data-[state=active]:text-text-primary text-text-muted rounded"
          >
            Brokerage
          </TabsTrigger>
        </TabsList>

        <TabsContent value="risk" className="flex-1 overflow-auto m-0 p-0">
          <RiskCalcTab />
        </TabsContent>
        <TabsContent value="brokerage" className="flex-1 overflow-auto m-0 p-0">
          <BrokerageCalcTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
