/**
 * SetupRoute — multi-step first-time setup wizard.
 * Modes: Quick (2 steps), Guided (5 steps), Advanced (7 steps).
 * Saves to connectionStore + settingsStore, then navigates based on persona.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  CheckCircle,
  XCircle,
  Loader2,
  Zap,
  BookOpen,
  Settings2,
  ArrowLeft,
  ArrowRight,
  Wifi,
} from "lucide-react";

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
  return "/terminal";
}

// ---------------------------------------------------------------------------
// Step progress indicator
// ---------------------------------------------------------------------------

interface StepIndicatorProps {
  total: number;
  current: number;
}

function StepIndicator({ total, current }: StepIndicatorProps) {
  return (
    <div className="flex items-center gap-2 justify-center">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={[
            "h-1.5 rounded-full transition-all duration-300",
            i < current
              ? "w-6 bg-green-500"
              : i === current
                ? "w-6 bg-blue-500"
                : "w-4 bg-border-default",
          ].join(" ")}
        />
      ))}
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
      className="bg-surface-card border-border-default cursor-pointer hover:border-blue-500/60 hover:bg-surface-card/80 transition-all duration-200 group"
      onClick={onClick}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between mb-2">
          <div className="p-2 rounded-lg bg-blue-500/10 text-blue-400 group-hover:bg-blue-500/20 transition-colors">
            {icon}
          </div>
          <Badge variant="outline" className="text-xs text-text-muted border-border-default">
            {badge}
          </Badge>
        </div>
        <CardTitle className="text-text-primary text-lg">{title}</CardTitle>
        <CardDescription className="text-text-secondary text-xs">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-text-muted text-sm leading-relaxed">{description}</p>
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
        <Input
          id="host"
          placeholder="http://localhost:5000"
          className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
          {...register("host")}
        />
        {errors.host && (
          <p className="text-red-400 text-xs">{errors.host.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="apiKey" className="text-text-secondary text-xs uppercase tracking-wider">
          API Key
        </Label>
        <Input
          id="apiKey"
          type="password"
          placeholder="Your OpenAlgo API key"
          className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
          {...register("apiKey")}
        />
        {errors.apiKey && (
          <p className="text-red-400 text-xs">{errors.apiKey.message}</p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="wsPort" className="text-text-secondary text-xs uppercase tracking-wider">
          WebSocket Port
        </Label>
        <Input
          id="wsPort"
          placeholder="8765"
          className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
          {...register("wsPort")}
        />
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
        className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
              ? "border-blue-500 bg-blue-500/10"
              : "border-border-default bg-surface-base hover:border-blue-500/40",
          ].join(" ")}
        >
          <div className="flex items-center justify-between">
            <span className="text-text-primary font-medium text-sm">{opt.label}</span>
            <Badge
              variant="outline"
              className={[
                "text-xs border-border-default",
                selected === opt.value ? "border-blue-500/60 text-blue-400" : "text-text-muted",
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
              ? "border-blue-500 bg-blue-500/10"
              : "border-border-default bg-surface-base hover:border-blue-500/40",
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
        <Input
          id="defaultQty"
          type="number"
          min={1}
          max={9999}
          className="bg-surface-base border-border-default text-text-primary font-mono"
          {...register("defaultQty", { valueAsNumber: true })}
        />
        {errors.defaultQty && (
          <p className="text-red-400 text-xs">{errors.defaultQty.message}</p>
        )}
      </div>

      <Button type="submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white">
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
          <Input
            id="maxPositionLots"
            type="number"
            min={1}
            className="bg-surface-base border-border-default text-text-primary font-mono"
            {...register("maxPositionLots", { valueAsNumber: true })}
          />
          {errors.maxPositionLots && (
            <p className="text-red-400 text-xs">{errors.maxPositionLots.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="maxOrdersPerMin" className="text-text-secondary text-xs uppercase tracking-wider">
            Max Orders / Min
          </Label>
          <Input
            id="maxOrdersPerMin"
            type="number"
            min={1}
            className="bg-surface-base border-border-default text-text-primary font-mono"
            {...register("maxOrdersPerMin", { valueAsNumber: true })}
          />
          {errors.maxOrdersPerMin && (
            <p className="text-red-400 text-xs">{errors.maxOrdersPerMin.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmStoploss" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Stop-loss (INR)
          </Label>
          <Input
            id="mtmStoploss"
            type="number"
            min={0}
            className="bg-surface-base border-border-default text-text-primary font-mono"
            {...register("mtmStoploss", { valueAsNumber: true })}
          />
          {errors.mtmStoploss && (
            <p className="text-red-400 text-xs">{errors.mtmStoploss.message}</p>
          )}
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="mtmTarget" className="text-text-secondary text-xs uppercase tracking-wider">
            MTM Target (INR)
          </Label>
          <Input
            id="mtmTarget"
            type="number"
            min={0}
            className="bg-surface-base border-border-default text-text-primary font-mono"
            {...register("mtmTarget", { valueAsNumber: true })}
          />
          {errors.mtmTarget && (
            <p className="text-red-400 text-xs">{errors.mtmTarget.message}</p>
          )}
        </div>
      </div>

      <p className="text-text-muted text-xs">
        Risk limits are enforced by the safety engine. You can change them later in Settings.
      </p>

      <Button type="submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white">
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
        <Input
          id="model"
          placeholder={
            provider === "lmstudio" || provider === "ollama"
              ? "qwen3-9b"
              : provider === "anthropic"
                ? "claude-3-5-haiku-20241022"
                : "gpt-4o-mini"
          }
          className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
          {...register("model")}
        />
        {errors.model && <p className="text-red-400 text-xs">{errors.model.message}</p>}
      </div>

      {(provider === "lmstudio" || provider === "ollama") && (
        <div className="space-y-1.5">
          <Label htmlFor="llmHost" className="text-text-secondary text-xs uppercase tracking-wider">
            Local Host URL
          </Label>
          <Input
            id="llmHost"
            placeholder={provider === "lmstudio" ? "http://localhost:1234" : "http://localhost:11434"}
            className="bg-surface-base border-border-default text-text-primary font-mono text-sm"
            {...register("host")}
          />
        </div>
      )}

      <p className="text-text-muted text-xs">
        API keys are stored in your workspace config (~/.flinttrade/workspace.json), never in this app.
      </p>

      <Button type="submit" className="w-full bg-blue-600 hover:bg-blue-500 text-white">
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
  onGo: () => void;
}

function DoneScreen({ persona, onGo }: DoneScreenProps) {
  const personaLabel =
    persona === "investor" ? "Investor" : persona === "beginner" ? "Learner" : "Trader";

  const destination =
    persona === "investor"
      ? "Investment Dashboard"
      : persona === "beginner"
        ? "Learning Workspace"
        : "Trading Terminal";

  return (
    <div className="text-center space-y-6 py-4">
      <div className="inline-flex items-center justify-center size-16 rounded-full bg-green-500/15 border border-green-500/30">
        <CheckCircle className="size-8 text-green-400" />
      </div>
      <div className="space-y-2">
        <h3 className="text-text-primary text-xl font-semibold">Setup Complete</h3>
        <p className="text-text-secondary text-sm">
          Your workspace is configured for{" "}
          <span className="text-blue-400 font-medium">{personaLabel}</span>.
        </p>
        <p className="text-text-muted text-xs">Opening {destination}</p>
      </div>
      <Button
        onClick={onGo}
        className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
}

const INITIAL_WIZARD: WizardState = {
  persona: null,
  experience: null,
  connection: null,
  tradingDefaults: null,
  riskLimits: null,
};

// ---------------------------------------------------------------------------
// Step labels per mode
// ---------------------------------------------------------------------------

const QUICK_STEPS = ["Connection", "Persona"];
const GUIDED_STEPS = ["Persona", "Connection", "Experience", "Trading Defaults", "Done"];
const ADVANCED_STEPS = [
  "Persona",
  "Connection",
  "Experience",
  "Trading Defaults",
  "Risk Limits",
  "AI Config",
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

    navigate(personaRoute(persona));
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
      <div className="min-h-screen bg-surface-base flex items-center justify-center p-4">
        <div className="max-w-3xl w-full space-y-8">
          <div className="text-center space-y-3">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-blue-500/30 bg-blue-500/10 text-blue-400 text-xs font-medium mb-2">
              First Time Setup
            </div>
            <h1 className="text-3xl font-bold text-text-primary tracking-tight">
              Welcome to FlintTrade
            </h1>
            <p className="text-text-secondary text-sm max-w-md mx-auto">
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
              subtitle="5 steps — personalized"
              description="Persona, connection, experience level, and trading defaults for a tailored workspace."
              badge="~2 min"
              icon={<BookOpen className="size-5" />}
              onClick={() => { setMode("guided"); setStep(0); }}
            />
            <ModeCard
              title="Advanced Setup"
              subtitle="7 steps — full control"
              description="Everything in Guided plus LLM provider, Telegram notifications, and risk limits."
              badge="~4 min"
              icon={<Settings2 className="size-5" />}
              onClick={() => { setMode("advanced"); setStep(0); }}
            />
          </div>

          <div className="text-center">
            <Button
              variant="ghost"
              className="text-text-muted hover:text-text-secondary"
              onClick={() => navigate("/terminal")}
            >
              Skip setup — use defaults
            </Button>
          </div>
        </div>
      </div>
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
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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

    // GUIDED: 0=Persona, 1=Connection, 2=Experience, 3=TradingDefaults, 4=Done
    if (mode === "guided") {
      if (step === 0) {
        return (
          <div className="space-y-5">
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
              className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
          <TradingDefaultsStep
            defaultValues={wizard.tradingDefaults ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, tradingDefaults: vals }));
              next();
            }}
          />
        );
      }
      if (step === 4) {
        return (
          <DoneScreen
            persona={wizard.persona ?? "trader"}
            onGo={() => applyAndNavigate(wizard)}
          />
        );
      }
    }

    // ADVANCED: 0=Persona, 1=Connection, 2=Experience, 3=TradingDefaults,
    //           4=RiskLimits, 5=LLM, 6=Done
    if (mode === "advanced") {
      if (step === 0) {
        return (
          <div className="space-y-5">
            <PersonaPicker
              selected={wizard.persona}
              onSelect={(p) => setWizard((w) => ({ ...w, persona: p }))}
            />
            <Button
              className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
              className="w-full bg-blue-600 hover:bg-blue-500 text-white"
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
          <TradingDefaultsStep
            defaultValues={wizard.tradingDefaults ?? undefined}
            onComplete={(vals) => {
              setWizard((w) => ({ ...w, tradingDefaults: vals }));
              next();
            }}
          />
        );
      }
      if (step === 4) {
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
      if (step === 5) {
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
      if (step === 6) {
        return (
          <DoneScreen
            persona={wizard.persona ?? "trader"}
            onGo={() => applyAndNavigate(wizard)}
          />
        );
      }
    }

    return null;
  }

  const isDoneStep =
    (mode === "guided" && step === 4) || (mode === "advanced" && step === 6);

  return (
    <div className="min-h-screen bg-surface-base flex items-center justify-center p-4">
      <div className="max-w-lg w-full space-y-6">
        {/* Header */}
        <div className="text-center space-y-1">
          <p className="text-text-muted text-xs uppercase tracking-widest">FlintTrade Setup</p>
          <h2 className="text-text-primary text-xl font-semibold">{stepLabel}</h2>
        </div>

        {/* Progress */}
        <StepIndicator total={totalSteps} current={step} />

        {/* Card */}
        <Card className="bg-surface-card border-border-default">
          <CardContent className="pt-6 pb-6 px-6">
            {renderStep()}
          </CardContent>
        </Card>

        {/* Navigation */}
        {!isDoneStep && (
          <div className="flex justify-between items-center">
            <Button
              variant="ghost"
              size="sm"
              onClick={back}
              className="text-text-muted hover:text-text-secondary"
            >
              <ArrowLeft className="size-3.5 mr-1.5" />
              {step === 0 ? "Change mode" : "Back"}
            </Button>

            <span className="text-text-muted text-xs">
              {step + 1} / {totalSteps}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
