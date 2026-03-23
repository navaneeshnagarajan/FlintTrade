/**
 * SetupRoute — multi-step first-time setup wizard.
 * Modes: Quick (2 steps), Guided (7 steps), Advanced (9 steps).
 * Saves to connectionStore + settingsStore, then navigates based on persona.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { motion, AnimatePresence } from "framer-motion";
import {
  Check,
  CheckCircle,
  XCircle,
  Loader2,
  Zap,
  BookOpen,
  Settings2,
  ArrowLeft,
  ArrowRight,
  Wifi,
  CandlestickChart,
  PiggyBank,
  Workflow,
  Bot,
  type LucideIcon,
} from "lucide-react";
import { motionConfig } from "@/lib/motion";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { ping } from "@/services/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SetupMode = "quick" | "guided" | "advanced";
type Persona = "trader" | "investor" | "beginner";
type ExperienceLevel = "new" | "intermediate" | "professional";

// ---------------------------------------------------------------------------
// Zod schemas
// ---------------------------------------------------------------------------

const connectionSchema = z.object({
  host: z.string().min(1, "Host is required").url("Must be a valid URL (include http://)"),
  apiKey: z.string().min(8, "API key must be at least 8 characters"),
  wsPort: z.string().min(1, "WebSocket port is required"),
});

type ConnectionFormValues = z.infer<typeof connectionSchema>;

const tradingDefaultsSchema = z.object({
  defaultExchange: z.string().min(1, "Exchange is required"),
  defaultProduct: z.string().min(1, "Product is required"),
  defaultQty: z.number().int().min(1, "Minimum 1").max(9999, "Maximum 9999"),
});

type TradingDefaultsFormValues = z.infer<typeof tradingDefaultsSchema>;

const riskSchema = z.object({
  maxPositionLots: z.number().int().min(1).max(1000),
  mtmStoploss: z.number().min(0),
  mtmTarget: z.number().min(0),
  maxOrdersPerMin: z.number().int().min(1).max(100),
});

type RiskFormValues = z.infer<typeof riskSchema>;

const llmSchema = z.object({
  provider: z.string().min(1, "Provider is required"),
  model: z.string().min(1, "Model is required"),
  host: z.string().optional(),
});

type LlmFormValues = z.infer<typeof llmSchema>;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function deriveWsUrl(host: string, wsPort: string): string {
  try {
    const url = new URL(host);
    const proto = url.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${url.hostname}:${wsPort}`;
  } catch {
    return `ws://localhost:${wsPort}`;
  }
}

function personaRoute(persona: Persona): string {
  if (persona === "investor") return "/invest";
  if (persona === "beginner") return "/learn";
  return "/trade";
}

// ---------------------------------------------------------------------------
// Step progress indicator — clickable dots
// ---------------------------------------------------------------------------

interface StepIndicatorProps {
  total: number;
  current: number;
  /** Optional: called when user clicks a completed step dot */
  onStepClick?: (index: number) => void;
}

function StepIndicator({ total, current, onStepClick }: StepIndicatorProps) {
  const reduced = motionConfig.prefersReducedMotion();

  return (
    <div
      className="flex items-center gap-3 justify-center"
      aria-label={`Setup progress: step ${current + 1} of ${total}`}
    >
      {Array.from({ length: total }, (_, i) => {
        const isCompleted = i < current;
        const isActive = i === current;
        const isClickable = isCompleted && onStepClick !== undefined;

        return (
          <button
            key={i}
            type="button"
            aria-label={`Step ${i + 1}${isCompleted ? " (completed)" : isActive ? " (current)" : ""}`}
            disabled={!isClickable}
            onClick={isClickable ? () => onStepClick(i) : undefined}
            className={[
              "relative flex items-center justify-center rounded-full transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
              isActive ? "size-5 bg-primary" : isCompleted ? "size-4 bg-profit cursor-pointer hover:ring-2 hover:ring-profit/40" : "size-3 bg-border-default",
              !isClickable && "cursor-default",
            ].join(" ")}
          >
            {isActive && !reduced && (
              <motion.span
                layoutId="step-active-ring"
                className="absolute inset-0 rounded-full ring-2 ring-primary/40"
                transition={motionConfig.transitions.tab}
              />
            )}
            {isCompleted && (
              <Check className="size-2.5 text-surface-base" strokeWidth={3} />
            )}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mode selection screen
// ---------------------------------------------------------------------------

interface ModeCardProps {
  title: string;
  subtitle: string;
  description: string;
  badge: string;
  icon: React.ReactNode;
  onClick: () => void;
}

function ModeCard({ title, subtitle, description, badge, icon, onClick }: ModeCardProps) {
  return (
    <Card
      className="bg-surface-card border border-border-default rounded-lg p-6 shadow-sm cursor-pointer hover:border-accent/40 hover:bg-surface-hover transition-all duration-200 group"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between mb-2">
          <div className="p-2 rounded-lg bg-accent/15 text-accent group-hover:bg-accent/20 transition-colors">
            {icon}
          </div>
          <Badge variant="outline" className="text-xxs text-text-muted bg-surface-elevated px-2 py-0.5 rounded border-border-default">
            {badge}
          </Badge>
        </div>
        <CardTitle className="font-heading font-bold text-lg text-text-primary">{title}</CardTitle>
        <CardDescription className="text-sm text-text-muted">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-text-muted leading-relaxed">{description}</p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Connection step (shared by Quick, Guided, Advanced)
// ---------------------------------------------------------------------------

interface ConnectionStepProps {
  onComplete: (values: ConnectionFormValues) => void;
  defaultValues?: Partial<ConnectionFormValues>;
}

function ConnectionStep({ onComplete, defaultValues }: ConnectionStepProps) {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: {
      host: defaultValues?.host ?? "http://localhost:5000",
      apiKey: defaultValues?.apiKey ?? "",
      wsPort: defaultValues?.wsPort ?? "8765",
    },
  });

  const [testState, setTestState] = useState<"idle" | "testing" | "ok" | "fail">("idle");
  const [testError, setTestError] = useState("");

  async function handleTest() {
    // Temporarily apply values so ping() can read from store
    const vals = getValues();
    const wsUrl = deriveWsUrl(vals.host, vals.wsPort);
    useConnectionStore.getState().setConfig({ host: vals.host, apiKey: vals.apiKey, wsUrl });

    setTestState("testing");
    setTestError("");
    try {
      await ping();
      setTestState("ok");
    } catch (err) {
      setTestState("fail");
      setTestError(err instanceof Error ? err.message : "Connection failed");
    }
  }

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label htmlFor="host" className="text-text-secondary text-xs uppercase tracking-wider">
          OpenAlgo URL
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="host"
            placeholder="http://localhost:5000"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("host")}
          />
        </div>
        {errors.host && (
          <p className="text-red-400 text-xs">{errors.host.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="apiKey" className="text-text-secondary text-xs uppercase tracking-wider">
          API Key
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="apiKey"
            type="password"
            placeholder="Your OpenAlgo API key"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("apiKey")}
          />
        </div>
        {errors.apiKey && (
          <p className="text-red-400 text-xs">{errors.apiKey.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="wsPort" className="text-text-secondary text-xs uppercase tracking-wider">
          WebSocket Port
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="wsPort"
            placeholder="8765"
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("wsPort")}
          />
        </div>
        {errors.wsPort && (
          <p className="text-red-400 text-xs">{errors.wsPort.message}</p>
        )}
      </div>

      <div className="flex items-center gap-3 pt-1">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleTest}
          disabled={testState === "testing"}
          className="border-border-default text-text-secondary hover:text-text-primary"
        >
          {testState === "testing" ? (
            <Loader2 className="size-3.5 mr-1.5 animate-spin" />
          ) : (
            <Wifi className="size-3.5 mr-1.5" />
          )}
          Test Connection
        </Button>

        {testState === "ok" && (
          <span className="flex items-center gap-1.5 text-green-400 text-sm">
            <CheckCircle className="size-4" /> Connected
          </span>
        )}
        {testState === "fail" && (
          <span className="flex items-center gap-1.5 text-red-400 text-sm">
            <XCircle className="size-4" />
            <span className="truncate max-w-50">{testError || "Failed"}</span>
          </span>
        )}
      </div>

      <Button
        type="submit"
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
      >
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Persona picker (shared by Quick step-2, Guided step-1)
// ---------------------------------------------------------------------------

interface PersonaPickerProps {
  selected: Persona | null;
  onSelect: (p: Persona) => void;
}

function PersonaPicker({ selected, onSelect }: PersonaPickerProps) {
  const options: Array<{ value: Persona; label: string; description: string; hint: string }> = [
    {
      value: "trader",
      label: "Active Trader",
      description: "F&O, intraday, scalping",
      hint: "Full terminal with order pad, depth, Greeks",
    },
    {
      value: "investor",
      label: "Investor",
      description: "Equity, long-term, SIP",
      hint: "Portfolio overview with holdings dashboard",
    },
    {
      value: "beginner",
      label: "Learner",
      description: "Learning markets, paper trading",
      hint: "Guided workspace with explanations",
    },
  ];

  return (
    <div className="space-y-3">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onSelect(opt.value)}
          className={[
            "w-full text-left rounded-lg border p-4 transition-all duration-150",
            selected === opt.value
              ? "border-accent/40 bg-accent/15"
              : "border-border-default bg-surface-base hover:border-accent/40",
          ].join(" ")}
        >
          <div className="flex items-center justify-between">
            <span className="text-text-primary font-medium text-sm">{opt.label}</span>
            <Badge
              variant="outline"
              className={[
                "text-xs border-border-default",
                selected === opt.value ? "border-accent/40 text-accent" : "text-text-muted",
              ].join(" ")}
            >
              {opt.description}
            </Badge>
          </div>
          <p className="text-text-muted text-xs mt-1">{opt.hint}</p>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Experience level picker
// ---------------------------------------------------------------------------

interface ExperiencePickerProps {
  selected: ExperienceLevel | null;
  onSelect: (e: ExperienceLevel) => void;
}

function ExperiencePicker({ selected, onSelect }: ExperiencePickerProps) {
  const options: Array<{ value: ExperienceLevel; label: string; description: string }> = [
    { value: "new", label: "New to markets", description: "Less than 1 year" },
    { value: "intermediate", label: "Intermediate", description: "1-3 years of trading" },
    { value: "professional", label: "Professional", description: "3+ years, active strategies" },
  ];

  return (
    <div className="space-y-3">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onSelect(opt.value)}
          className={[
            "w-full text-left rounded-lg border p-4 transition-all duration-150",
            selected === opt.value
              ? "border-accent/40 bg-accent/15"
              : "border-border-default bg-surface-base hover:border-accent/40",
          ].join(" ")}
        >
          <span className="text-text-primary font-medium text-sm block">{opt.label}</span>
          <span className="text-text-muted text-xs">{opt.description}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Interest definitions
// ---------------------------------------------------------------------------

const INTERESTS = [
  { id: "learning", label: "Learning & Education", icon: BookOpen, desc: "Market basics, strategies, paper trading" },
  { id: "investing", label: "Investing", icon: PiggyBank, desc: "Mutual funds, SIPs, portfolio, net worth" },
  { id: "trading", label: "Trading", icon: CandlestickChart, desc: "F&O scalping, options, intraday" },
  { id: "backtesting", label: "Backtesting", icon: Zap, desc: "Strategy testing, walk-forward, optimization" },
  { id: "automation", label: "Automation", icon: Workflow, desc: "Flow builder, cron jobs, alerts" },
  { id: "ai", label: "AI & Analysis", icon: Bot, desc: "LLM advisor, sentiment, signals" },
] as const;

// ---------------------------------------------------------------------------
// Interest picker (multi-select)
// ---------------------------------------------------------------------------

interface InterestPickerProps {
  selected: string[];
  onToggle: (id: string) => void;
}

function InterestPicker({ selected, onToggle }: InterestPickerProps) {
  return (
    <div className="grid grid-cols-2 gap-3">
      {INTERESTS.map((interest) => {
        const Icon: LucideIcon = interest.icon;
        const isSelected = selected.includes(interest.id);
        return (
          <button
            key={interest.id}
            type="button"
            onClick={() => onToggle(interest.id)}
            className={[
              "text-left rounded-lg border p-4 transition-all duration-150",
              isSelected
                ? "bg-accent/10 border-accent/40 ring-1 ring-accent/20"
                : "bg-surface-card border-border-default hover:border-accent/30 hover:bg-surface-hover",
            ].join(" ")}
          >
            <div className="flex items-center gap-2.5 mb-1.5">
              <Icon className={[
                "size-4",
                isSelected ? "text-accent" : "text-text-muted",
              ].join(" ")} />
              <span className={[
                "text-sm font-medium",
                isSelected ? "text-accent" : "text-text-primary",
              ].join(" ")}>
                {interest.label}
              </span>
            </div>
            <p className={[
              "text-xs leading-relaxed",
              isSelected ? "text-accent/70" : "text-text-muted",
            ].join(" ")}>
              {interest.desc}
            </p>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Name input
// ---------------------------------------------------------------------------

interface NameInputProps {
  value: string;
  onChange: (name: string) => void;
}

function NameInput({ value, onChange }: NameInputProps) {
  return (
    <div className="space-y-1.5">
      <Label className="text-text-secondary text-xs uppercase tracking-wider">
        What should we call you?
      </Label>
      <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Trader"
          className="h-9 text-sm border-border-default rounded-md font-sans bg-surface-base text-text-primary"
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layout preset logic
// ---------------------------------------------------------------------------

function getPresetName(experience: string, interests: string[]): string {
  if (experience === "new") {
    if (interests.includes("trading")) return "learn-then-trade";
    if (interests.includes("investing")) return "invest-lite";
    return "learn-first";
  }
  if (experience === "professional") {
    if (interests.includes("trading")) return "scalper-zone";
    return "power-user";
  }
  // intermediate or fallback
  if (interests.length >= 3) return "full";
  if (interests.includes("investing")) return "invest-diversified";
  return "minimal";
}

/**
 * Maps wizard-internal preset names (which may not match real preset IDs) to
 * the actual preset IDs registered in workspacePresets.ts.
 */
function mapWizardPreset(wizardPreset: string): string {
  const MAP: Record<string, string> = {
    "learn-first": "market-watch",
    "learn-then-trade": "market-watch",
    "invest-lite": "investor-view",
    "invest-diversified": "investor-view",
    "power-user": "scalper-zone",
    "full": "analysis",
    "minimal": "market-watch",
    "scalper-zone": "scalper-zone",
    "options-desk": "options-desk",
  };
  return MAP[wizardPreset] ?? "market-watch";
}

const PRESET_DESCRIPTIONS: Record<string, string> = {
  "learn-first": "Market Watch workspace — Watchlist, Chart, and Dashboard to get started",
  "learn-then-trade": "Market Watch workspace — overview layout ideal for learning while watching markets",
  "invest-lite": "Investor View — Chart, Watchlist, Holdings, and Dashboard for portfolio tracking",
  "invest-diversified": "Investor View — portfolio overview with holdings, watchlist, and chart",
  "scalper-zone": "Scalper Zone — Chart, Order Pad, Depth, Positions, and Scalper for rapid execution",
  "power-user": "Scalper Zone — full-featured layout with all execution and analysis panels",
  "full": "Analysis workspace — Chart, OI Chart, Depth, Positions, and News feed",
  "minimal": "Market Watch workspace — clean layout with essential widgets to get started",
  "options-desk": "Options Desk — Option Chain, Chart, Greeks, Positions, and Straddle",
};

interface LayoutPreviewProps {
  experience: string;
  interests: string[];
}

function LayoutPreview({ experience, interests }: LayoutPreviewProps) {
  const wizardPreset = getPresetName(experience, interests);
  const actualPresetId = mapWizardPreset(wizardPreset);
  const description = PRESET_DESCRIPTIONS[wizardPreset] ?? "Custom workspace layout";
  const displayName = actualPresetId
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");

  return (
    <div className="bg-surface-card border border-border-default rounded-lg p-4 shadow-sm space-y-2">
      <p className="text-xxs uppercase tracking-wider text-text-muted">Your workspace</p>
      <p className="text-text-primary font-heading font-bold text-lg">{displayName}</p>
      <p className="text-sm text-text-secondary leading-relaxed">{description}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trading defaults step
// ---------------------------------------------------------------------------

interface TradingDefaultsStepProps {
  onComplete: (values: TradingDefaultsFormValues) => void;
  defaultValues?: Partial<TradingDefaultsFormValues>;
}

function TradingDefaultsStep({ onComplete, defaultValues }: TradingDefaultsStepProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<TradingDefaultsFormValues>({
    resolver: zodResolver(tradingDefaultsSchema),
    defaultValues: {
      defaultExchange: defaultValues?.defaultExchange ?? "NFO",
      defaultProduct: defaultValues?.defaultProduct ?? "MIS",
      defaultQty: defaultValues?.defaultQty ?? 1,
    },
  });

  const watchedExchange = watch("defaultExchange");
  const watchedProduct = watch("defaultProduct");

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">
          Default Exchange
        </Label>
        <Select
          value={watchedExchange}
          onValueChange={(v) => setValue("defaultExchange", v)}
        >
          <SelectTrigger className="w-full bg-surface-base border-border-default text-text-primary">
            <SelectValue placeholder="Select exchange" />
          </SelectTrigger>
          <SelectContent>
            {["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NSE_INDEX"].map((ex) => (
              <SelectItem key={ex} value={ex}>
                {ex}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {errors.defaultExchange && (
          <p className="text-red-400 text-xs">{errors.defaultExchange.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">
          Default Product
        </Label>
        <Select
          value={watchedProduct}
          onValueChange={(v) => setValue("defaultProduct", v)}
        >
          <SelectTrigger className="w-full bg-surface-base border-border-default text-text-primary">
            <SelectValue placeholder="Select product" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="MIS">MIS — Intraday</SelectItem>
            <SelectItem value="CNC">CNC — Delivery</SelectItem>
            <SelectItem value="NRML">NRML — Normal (F&O)</SelectItem>
            <SelectItem value="BO">BO — Bracket Order</SelectItem>
            <SelectItem value="CO">CO — Cover Order</SelectItem>
          </SelectContent>
        </Select>
        {errors.defaultProduct && (
          <p className="text-red-400 text-xs">{errors.defaultProduct.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="defaultQty" className="text-text-secondary text-xs uppercase tracking-wider">
          Default Quantity / Lots
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="defaultQty"
            type="number"
            min={1}
            max={9999}
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("defaultQty", { valueAsNumber: true })}
          />
        </div>
        {errors.defaultQty && (
          <p className="text-red-400 text-xs">{errors.defaultQty.message}</p>
        )}
      </div>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Risk limits step (Advanced only)
// ---------------------------------------------------------------------------

interface RiskStepProps {
  onComplete: (values: RiskFormValues) => void;
  defaultValues?: Partial<RiskFormValues>;
}

function RiskStep({ onComplete, defaultValues }: RiskStepProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<RiskFormValues>({
    resolver: zodResolver(riskSchema),
    defaultValues: {
      maxPositionLots: defaultValues?.maxPositionLots ?? 10,
      mtmStoploss: defaultValues?.mtmStoploss ?? 5000,
      mtmTarget: defaultValues?.mtmTarget ?? 10000,
      maxOrdersPerMin: defaultValues?.maxOrdersPerMin ?? 30,
    },
  });

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <Label htmlFor="maxPositionLots" className="text-text-secondary text-xs uppercase tracking-wider">
            Max Position Lots
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="maxPositionLots"
              type="number"
              min={1}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("maxPositionLots", { valueAsNumber: true })}
            />
          </div>
          {errors.maxPositionLots && (
            <p className="text-red-400 text-xs">{errors.maxPositionLots.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="maxOrdersPerMin" className="text-text-secondary text-xs uppercase tracking-wider">
            Max Orders / Min
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="maxOrdersPerMin"
              type="number"
              min={1}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("maxOrdersPerMin", { valueAsNumber: true })}
            />
          </div>
          {errors.maxOrdersPerMin && (
            <p className="text-red-400 text-xs">{errors.maxOrdersPerMin.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmStoploss" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Stop-loss (INR)
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="mtmStoploss"
              type="number"
              min={0}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("mtmStoploss", { valueAsNumber: true })}
            />
          </div>
          {errors.mtmStoploss && (
            <p className="text-red-400 text-xs">{errors.mtmStoploss.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmTarget" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Target (INR)
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="mtmTarget"
              type="number"
              min={0}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("mtmTarget", { valueAsNumber: true })}
            />
          </div>
          {errors.mtmTarget && (
            <p className="text-red-400 text-xs">{errors.mtmTarget.message}</p>
          )}
        </div>
      </div>

      <p className="text-text-muted text-xs">
        Risk limits are enforced by the safety engine. You can change them later in Settings.
      </p>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// LLM config step (Advanced only)
// ---------------------------------------------------------------------------

interface LlmStepProps {
  onComplete: (values: LlmFormValues) => void;
}

function LlmStep({ onComplete }: LlmStepProps) {
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors },
  } = useForm<LlmFormValues>({
    resolver: zodResolver(llmSchema),
    defaultValues: { provider: "openai", model: "gpt-4o-mini", host: "" },
  });

  const provider = watch("provider");

  return (
    <form onSubmit={handleSubmit(onComplete)} className="space-y-5">
      <div className="space-y-1.5">
        <Label className="text-text-secondary text-xs uppercase tracking-wider">LLM Provider</Label>
        <Select value={provider} onValueChange={(v) => setValue("provider", v)}>
          <SelectTrigger className="w-full bg-surface-base border-border-default text-text-primary">
            <SelectValue placeholder="Select provider" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="openai">OpenAI</SelectItem>
            <SelectItem value="anthropic">Anthropic</SelectItem>
            <SelectItem value="google">Google Gemini</SelectItem>
            <SelectItem value="lmstudio">LM Studio (local)</SelectItem>
            <SelectItem value="ollama">Ollama (local)</SelectItem>
          </SelectContent>
        </Select>
        {errors.provider && <p className="text-red-400 text-xs">{errors.provider.message}</p>}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="model" className="text-text-secondary text-xs uppercase tracking-wider">
          Model
        </Label>
        <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
          <Input
            id="model"
            placeholder={
              provider === "lmstudio" || provider === "ollama"
                ? "qwen3-9b"
                : provider === "anthropic"
                  ? "claude-3-5-haiku-20241022"
                  : "gpt-4o-mini"
            }
            className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
            {...register("model")}
          />
        </div>
        {errors.model && <p className="text-red-400 text-xs">{errors.model.message}</p>}
      </div>

      {(provider === "lmstudio" || provider === "ollama") && (
        <div className="space-y-1.5">
          <Label htmlFor="llmHost" className="text-text-secondary text-xs uppercase tracking-wider">
            Local Host URL
          </Label>
          <div className="rounded-md focus-within:ring-2 focus-within:ring-accent/30">
            <Input
              id="llmHost"
              placeholder={provider === "lmstudio" ? "http://localhost:1234" : "http://localhost:11434"}
              className="h-9 text-sm bg-surface-base border-border-default text-text-primary font-mono"
              {...register("host")}
            />
          </div>
        </div>
      )}

      <p className="text-text-muted text-xs">
        API keys are stored in your workspace config (~/.flinttrade/workspace.json), never in this app.
      </p>

      <Button type="submit" className="w-full bg-primary hover:bg-primary/90 text-primary-foreground">
        Continue
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Done screen
// ---------------------------------------------------------------------------

interface DoneScreenProps {
  persona: Persona;
  name: string;
  onGo: () => void;
}

function DoneScreen({ persona, name, onGo }: DoneScreenProps) {
  const personaLabel =
    persona === "investor" ? "Investor" : persona === "beginner" ? "Learner" : "Trader";

  const destination =
    persona === "investor"
      ? "Investment Dashboard"
      : persona === "beginner"
        ? "Learning Workspace"
        : "Trading Terminal";

  const greeting = name && name !== "Trader" ? `${name}, your` : "Your";

  return (
    <div className="text-center space-y-6 py-4">
      <div className="inline-flex items-center justify-center size-16 rounded-full bg-profit/15 border border-profit/30">
        <CheckCircle className="size-8 text-profit" />
      </div>
      <div className="space-y-2">
        <h3 className="font-heading font-bold text-lg text-text-primary">Setup Complete</h3>
        <p className="text-sm text-text-secondary">
          {greeting} workspace is configured for{" "}
          <span className="text-accent font-medium">{personaLabel}</span>.
        </p>
        <p className="text-text-muted text-xxs">Opening {destination}</p>
      </div>
      <Button
        onClick={onGo}
        className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
        size="lg"
      >
        Launch FlintTrade
        <ArrowRight className="size-4 ml-2" />
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard state
// ---------------------------------------------------------------------------

interface WizardState {
  persona: Persona | null;
  experience: ExperienceLevel | null;
  connection: ConnectionFormValues | null;
  tradingDefaults: TradingDefaultsFormValues | null;
  riskLimits: RiskFormValues | null;
  name: string;
  interests: string[];
}

const INITIAL_WIZARD: WizardState = {
  persona: null,
  experience: null,
  connection: null,
  tradingDefaults: null,
  riskLimits: null,
  name: "Trader",
  interests: [],
};

// ---------------------------------------------------------------------------
// Step labels per mode
// ---------------------------------------------------------------------------

const QUICK_STEPS = ["Connection", "Persona"];
const GUIDED_STEPS = ["Persona", "Connection", "Experience", "Interests", "Trading Defaults", "Preview", "Done"];
const ADVANCED_STEPS = [
  "Persona",
  "Connection",
  "Experience",
  "Interests",
  "Trading Defaults",
  "Risk Limits",
  "AI Config",
  "Preview",
  "Done",
];

function stepsForMode(mode: SetupMode): string[] {
  if (mode === "quick") return QUICK_STEPS;
  if (mode === "guided") return GUIDED_STEPS;
  return ADVANCED_STEPS;
}

// ---------------------------------------------------------------------------
// Main SetupRoute
// ---------------------------------------------------------------------------

export default function SetupRoute() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<SetupMode | null>(null);
  const [step, setStep] = useState(0);
  const [wizard, setWizard] = useState<WizardState>(INITIAL_WIZARD);

  function mapExperience(level: ExperienceLevel | null): "beginner" | "intermediate" | "pro" | "custom" {
    if (level === "new") return "beginner";
    if (level === "professional") return "pro";
    if (level === "intermediate") return "intermediate";
    return "intermediate";
  }

  function applyAndNavigate(w: WizardState) {
    const persona = w.persona ?? "trader";
    const connection = w.connection;
    const tradingDefaults = w.tradingDefaults;
    const riskLimits = w.riskLimits;

    if (connection) {
      const wsUrl = deriveWsUrl(connection.host, connection.wsPort);
      useConnectionStore.getState().setConfig({
        host: connection.host,
        apiKey: connection.apiKey,
        wsUrl,
      });
    }

    useSettingsStore.getState().setPersona(persona);
    useSettingsStore.getState().setName(w.name || "Trader");
    useSettingsStore.getState().setInterests(w.interests);
    useSettingsStore.getState().setExperience(mapExperience(w.experience));

    if (tradingDefaults) {
      useSettingsStore.getState().setTradingDefaults({
        defaultExchange: tradingDefaults.defaultExchange,
        defaultProduct: tradingDefaults.defaultProduct,
        defaultQty: tradingDefaults.defaultQty,
      });
    }

    if (riskLimits) {
      useSettingsStore.getState().setRiskLimits(riskLimits);
    }

    // Derive and apply the actual workspace preset before navigating.
    // The Dockview API may not be mounted yet (user is still on /setup), so we
    // store the intent and TerminalRoute will pick it up on mount. If the API is
    // already mounted (e.g., navigating back to /trade), apply immediately.
    const wizardPreset = getPresetName(w.experience ?? "intermediate", w.interests);
    const actualPresetId = mapWizardPreset(wizardPreset);
    const api = useLayoutStore.getState().dockviewApi;
    if (api) {
      useLayoutStore.getState().applyPreset(actualPresetId);
    } else {
      // Store the desired preset so TerminalRoute can apply it on first mount.
      // We reuse the active tab's layout slot — clear any stale saved layout so
      // TerminalRoute falls through to applyPreset with our chosen preset.
      const activeTabId = useLayoutStore.getState().activeTabId;
      useLayoutStore.getState().saveTabLayout(activeTabId, {
        __pendingPreset: actualPresetId,
      } as unknown as Record<string, unknown>);
    }

    navigate(personaRoute(persona));
  }

  function toggleInterest(id: string) {
    setWizard((w) => ({
      ...w,
      interests: w.interests.includes(id)
        ? w.interests.filter((i) => i !== id)
        : [...w.interests, id],
    }));
  }

  function next() {
    setStep((s) => s + 1);
  }

  function back() {
    if (step === 0) {
      setMode(null);
    } else {
      setStep((s) => s - 1);
    }
  }

  // ---------- Mode selection ----------
  if (!mode) {
    return (
      <main aria-label="Setup wizard" className="min-h-screen bg-surface-base flex items-center justify-center p-4">
        <div className="max-w-3xl w-full space-y-8">
          <div className="text-center space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-accent/40 bg-accent/15 text-accent text-xxs font-medium mb-2">
              First Time Setup
            </div>
            <h1 className="font-heading font-bold text-2xl text-text-primary tracking-tight">
              Welcome to FlintTrade
            </h1>
            <p className="text-sm text-text-secondary max-w-md mx-auto">
              Connect to OpenAlgo and configure your workspace. Takes under two minutes.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ModeCard
              title="Quick Setup"
              subtitle="2 steps — connect and go"
              description="Enter your OpenAlgo URL and API key, pick your persona, start trading immediately."
              badge="~1 min"
              icon={<Zap className="size-5" />}
              onClick={() => { setMode("quick"); setStep(0); }}
            />
            <ModeCard
              title="Guided Setup"
              subtitle="7 steps — personalized"
              description="Persona, connection, experience, interests, and trading defaults for a tailored workspace."
              badge="~2 min"
              icon={<BookOpen className="size-5" />}
              onClick={() => { setMode("guided"); setStep(0); }}
            />
            <ModeCard
              title="Advanced Setup"
              subtitle="9 steps — full control"
              description="Everything in Guided plus LLM provider, risk limits, and workspace preview."
              badge="~4 min"
              icon={<Settings2 className="size-5" />}
              onClick={() => { setMode("advanced"); setStep(0); }}
            />
          </div>

          <div className="text-center">
            <Button
              variant="ghost"
              className="text-sm text-text-muted hover:text-text-primary"
              onClick={() => navigate("/trade")}
            >
              Skip setup — use defaults
            </Button>
          </div>
        </div>
      </main>
    );
  }

  // ---------- Wizard shell ----------
  const steps = stepsForMode(mode);
  const totalSteps = steps.length;
  const stepLabel = steps[step] ?? "";

  function renderStep() {
    // QUICK: 0=Connection, 1=Persona
    if (mode === "quick") {
      if (step === 0) {
        return (
          <ConnectionStep
            defaultValues={wizard.connection ?? undefined}
            onComplete={(vals) => {
              const updated = { ...wizard, connection: vals };
              setWizard(updated);
              next();
            }}
          />
        );
      }
      if (step === 1) {
        return (
          <div className="space-y-5">
            <NameInput
              value={wizard.name}
              onChange={(name) => setWizard((w) => ({ ...w, name }))}
            />
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={!wizard.persona}
              onClick={() => applyAndNavigate(wizard)}
            >
              Launch FlintTrade
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
    }

    // GUIDED: 0=Persona, 1=Connection, 2=Experience, 3=Interests,
    //         4=TradingDefaults, 5=Preview, 6=Done
    if (mode === "guided") {
      if (step === 0) {
        return (
          <div className="space-y-5">
            <NameInput
              value={wizard.name}
              onChange={(name) => setWizard((w) => ({ ...w, name }))}
            />
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={!wizard.persona}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 1) {
        return (
          <ConnectionStep
            defaultValues={wizard.connection ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, connection: vals }));
              next();
            }}
          />
        );
      }
      if (step === 2) {
        return (
          <div className="space-y-5">
            <ExperiencePicker
              selected={wizard.experience}
              onSelect={(e) => setWizard((w) => ({ ...w, experience: e }))}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={!wizard.experience}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 3) {
        return (
          <div className="space-y-5">
            <p className="text-sm text-text-secondary">Select one or more areas you are interested in.</p>
            <InterestPicker
              selected={wizard.interests}
              onToggle={toggleInterest}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={wizard.interests.length === 0}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 4) {
        return (
          <TradingDefaultsStep
            defaultValues={wizard.tradingDefaults ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, tradingDefaults: vals }));
              next();
            }}
          />
        );
      }
      if (step === 5) {
        return (
          <div className="space-y-5">
            <LayoutPreview
              experience={wizard.experience ?? "intermediate"}
              interests={wizard.interests}
            />
            <p className="text-text-muted text-xs">
              You can change your layout anytime from the workspace menu.
            </p>
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 6) {
        return (
          <DoneScreen
            persona={wizard.persona ?? "trader"}
            name={wizard.name}
            onGo={() => applyAndNavigate(wizard)}
          />
        );
      }
    }

    // ADVANCED: 0=Persona, 1=Connection, 2=Experience, 3=Interests,
    //           4=TradingDefaults, 5=RiskLimits, 6=LLM, 7=Preview, 8=Done
    if (mode === "advanced") {
      if (step === 0) {
        return (
          <div className="space-y-5">
            <NameInput
              value={wizard.name}
              onChange={(name) => setWizard((w) => ({ ...w, name }))}
            />
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={!wizard.persona}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 1) {
        return (
          <ConnectionStep
            defaultValues={wizard.connection ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, connection: vals }));
              next();
            }}
          />
        );
      }
      if (step === 2) {
        return (
          <div className="space-y-5">
            <ExperiencePicker
              selected={wizard.experience}
              onSelect={(e) => setWizard((w) => ({ ...w, experience: e }))}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={!wizard.experience}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 3) {
        return (
          <div className="space-y-5">
            <p className="text-sm text-text-secondary">Select one or more areas you are interested in.</p>
            <InterestPicker
              selected={wizard.interests}
              onToggle={toggleInterest}
            />
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              disabled={wizard.interests.length === 0}
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 4) {
        return (
          <TradingDefaultsStep
            defaultValues={wizard.tradingDefaults ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, tradingDefaults: vals }));
              next();
            }}
          />
        );
      }
      if (step === 5) {
        return (
          <RiskStep
            defaultValues={wizard.riskLimits ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, riskLimits: vals }));
              next();
            }}
          />
        );
      }
      if (step === 6) {
        return (
          <LlmStep
            onComplete={() => {
              // LLM config goes to workspace.json (backend), not stored in-app.
              // We acknowledge and advance.
              next();
            }}
          />
        );
      }
      if (step === 7) {
        return (
          <div className="space-y-5">
            <LayoutPreview
              experience={wizard.experience ?? "intermediate"}
              interests={wizard.interests}
            />
            <p className="text-text-muted text-xs">
              You can change your layout anytime from the workspace menu.
            </p>
            <Button
              className="w-full bg-primary hover:bg-primary/90 text-primary-foreground"
              onClick={next}
            >
              Continue
              <ArrowRight className="size-4 ml-2" />
            </Button>
          </div>
        );
      }
      if (step === 8) {
        return (
          <DoneScreen
            persona={wizard.persona ?? "trader"}
            name={wizard.name}
            onGo={() => applyAndNavigate(wizard)}
          />
        );
      }
    }

    return null;
  }

  const isDoneStep =
    (mode === "guided" && step === 6) || (mode === "advanced" && step === 8);

  const reduced = motionConfig.prefersReducedMotion();

  // Slide variants: enter from right, exit to left
  const stepVariants = {
    initial: { opacity: 0, x: reduced ? 0 : 20 },
    animate: {
      opacity: 1,
      x: 0,
      transition: { duration: motionConfig.duration.slow, ease: motionConfig.ease.enter },
    },
    exit: {
      opacity: 0,
      x: reduced ? 0 : -20,
      transition: { duration: motionConfig.duration.fast, ease: motionConfig.ease.exit },
    },
  };

  return (
    <main aria-label="Setup wizard" className="min-h-screen bg-surface-base flex items-center justify-center p-4">
      <div className="max-w-lg w-full space-y-6">
        {/* Header */}
        <div className="text-center space-y-1">
          <p className="text-text-muted text-xxs uppercase tracking-widest">FlintTrade Setup</p>
          <AnimatePresence mode="wait">
            <motion.h2
              key={`label-${step}`}
              initial={{ opacity: 0, y: reduced ? 0 : -4 }}
              animate={{ opacity: 1, y: 0, transition: { duration: motionConfig.duration.normal, ease: motionConfig.ease.enter } }}
              exit={{ opacity: 0, y: reduced ? 0 : 4, transition: { duration: motionConfig.duration.fast, ease: motionConfig.ease.exit } }}
              className="font-heading font-bold text-lg text-text-primary"
            >
              {stepLabel}
            </motion.h2>
          </AnimatePresence>
        </div>

        {/* Progress dots */}
        <StepIndicator
          total={totalSteps}
          current={step}
          onStepClick={(i) => setStep(i)}
        />

        {/* Card with slide transitions */}
        <Card className="bg-surface-card border-border-default overflow-hidden">
          <CardContent className="pt-6 pb-6 px-6">
            <AnimatePresence mode="wait">
              <motion.div
                key={step}
                variants={stepVariants}
                initial="initial"
                animate="animate"
                exit="exit"
              >
                {renderStep()}
              </motion.div>
            </AnimatePresence>
          </CardContent>
        </Card>

        {/* Navigation */}
        {!isDoneStep && (
          <div className="flex justify-between items-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={back}
              className="text-sm text-text-muted hover:text-text-primary"
            >
              <ArrowLeft className="size-3.5 mr-1.5" />
              {step === 0 ? "Change mode" : "Back"}
            </Button>

            <span className="font-mono text-xs text-text-muted">
              {step + 1} / {totalSteps}
            </span>
          </div>
        )}
      </div>
    </main>
  );
}
