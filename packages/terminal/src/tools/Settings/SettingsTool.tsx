/**
 * SettingsTool — Full settings panel for FlintTrade terminal.
 *
 * Layout: left sidebar with section names, right panel with active section form.
 * Persistence: localStorage key "flinttrade:settings"
 * Sections (all functional): General, API Connection, Trading Defaults, Risk Limits,
 *   Keyboard Shortcuts, LLM Config, Telegram, Data Paths, About
 */

import { useState, useEffect, useCallback, useRef, type JSX } from "react";
import {
  X,
  Settings,
  Monitor,
  Wifi,
  TrendingUp,
  ShieldAlert,
  Keyboard,
  Brain,
  Send,
  HardDrive,
  Info,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Github,
  ExternalLink,
  type LucideIcon,
} from "lucide-react";
import { ping } from "@/services/api";
import { resetWsService } from "@/services/websocket";
import { useSettingsStore } from "@/stores/settingsStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GeneralSettings {
  fontSize: "small" | "normal" | "large";
  density: "compact" | "comfortable";
}

interface ApiSettings {
  host: string;
  apiKey: string;
  wsPort: string;
}

interface TradingSettings {
  exchange: string;
  product: "MIS" | "NRML" | "CNC";
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  quantity: string;
}

interface RiskSettings {
  maxPositionLots: string;
  mtmStoploss: string;
  mtmTarget: string;
  maxOrdersPerMinute: string;
}

type LlmProvider =
  | "lmstudio"
  | "ollama"
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "groq"
  | "grok"
  | "mistral"
  | "together"
  | "openrouter"
  | "custom";

interface LlmSettings {
  provider: LlmProvider;
  host: string;
  model: string;
  apiKey: string;
}

interface TelegramSettings {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

interface DataPathSettings {
  fastStoragePath: string;
  archiveStoragePath: string;
}

interface AllSettings {
  general: GeneralSettings;
  api: ApiSettings;
  trading: TradingSettings;
  risk: RiskSettings;
  llm: LlmSettings;
  telegram: TelegramSettings;
  dataPaths: DataPathSettings;
}

type SectionId =
  | "general"
  | "api"
  | "trading"
  | "risk"
  | "keyboard"
  | "llm"
  | "telegram"
  | "dataPaths"
  | "about";

interface SectionDef {
  id: SectionId;
  label: string;
  icon: LucideIcon;
}

interface SelectOption {
  value: string;
  label: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:settings";

const DEFAULT_SETTINGS: AllSettings = {
  general: {
    fontSize: "normal",
    density: "comfortable",
  },
  api: {
    host: "",
    apiKey: "",
    wsPort: "8765",
  },
  trading: {
    exchange: "NSE",
    product: "MIS",
    orderType: "MARKET",
    quantity: "1",
  },
  risk: {
    maxPositionLots: "",
    mtmStoploss: "",
    mtmTarget: "",
    maxOrdersPerMinute: "",
  },
  llm: {
    provider: "lmstudio",
    host: "http://127.0.0.1:1234",
    model: "",
    apiKey: "",
  },
  telegram: {
    enabled: false,
    botToken: "",
    chatId: "",
  },
  dataPaths: {
    fastStoragePath: "",
    archiveStoragePath: "",
  },
};

const SECTIONS: SectionDef[] = [
  { id: "general",    label: "General",           icon: Monitor    },
  { id: "api",        label: "API Connection",     icon: Wifi       },
  { id: "trading",    label: "Trading Defaults",   icon: TrendingUp },
  { id: "risk",       label: "Risk Limits",        icon: ShieldAlert },
  { id: "keyboard",   label: "Keyboard Shortcuts", icon: Keyboard   },
  { id: "llm",        label: "LLM Config",         icon: Brain      },
  { id: "telegram",   label: "Telegram",           icon: Send       },
  { id: "dataPaths",  label: "Data Paths",         icon: HardDrive  },
  { id: "about",      label: "About",              icon: Info       },
];

const LOCAL_PROVIDERS = new Set<LlmProvider>(["lmstudio", "ollama", "custom"]);

const LLM_PROVIDER_OPTIONS: SelectOption[] = [
  { value: "lmstudio",   label: "LM Studio (local)"  },
  { value: "ollama",     label: "Ollama (local)"      },
  { value: "openai",     label: "OpenAI"              },
  { value: "anthropic",  label: "Anthropic"           },
  { value: "gemini",     label: "Google Gemini"       },
  { value: "deepseek",   label: "DeepSeek"            },
  { value: "groq",       label: "Groq"                },
  { value: "grok",       label: "Grok (xAI)"         },
  { value: "mistral",    label: "Mistral"             },
  { value: "together",   label: "Together AI"         },
  { value: "openrouter", label: "OpenRouter"          },
  { value: "custom",     label: "Custom endpoint"     },
];

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

function loadSettings(): AllSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<AllSettings>;
    return {
      general:   { ...DEFAULT_SETTINGS.general,   ...(parsed.general   ?? {}) },
      api:       { ...DEFAULT_SETTINGS.api,        ...(parsed.api       ?? {}) },
      trading:   { ...DEFAULT_SETTINGS.trading,    ...(parsed.trading   ?? {}) },
      risk:      { ...DEFAULT_SETTINGS.risk,       ...(parsed.risk      ?? {}) },
      llm:       { ...DEFAULT_SETTINGS.llm,        ...(parsed.llm       ?? {}) },
      telegram:  { ...DEFAULT_SETTINGS.telegram,   ...(parsed.telegram  ?? {}) },
      dataPaths: { ...DEFAULT_SETTINGS.dataPaths,  ...(parsed.dataPaths ?? {}) },
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings: AllSettings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable (private browsing, etc.)
  }
}

// ---------------------------------------------------------------------------
// Reusable form primitives (plain HTML — matches project theme)
// ---------------------------------------------------------------------------

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-xs text-text-secondary mb-1">{children}</label>
  );
}

interface TextInputProps {
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
}

function TextInput({ value, onChange, placeholder, type = "text", disabled = false }: TextInputProps) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="w-full px-3 py-1.5 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
    />
  );
}

interface SelectInputProps {
  value: string;
  onChange: (val: string) => void;
  options: SelectOption[];
}

function SelectInput({ value, onChange, options }: SelectInputProps) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full px-3 py-1.5 text-xs bg-surface-base border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/20 transition-colors appearance-none cursor-pointer"
    >
      {options.map(({ value: v, label }) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  );
}

interface SegmentControlProps {
  value: string;
  onChange: (val: string) => void;
  options: SelectOption[];
  disabled?: boolean;
}

function SegmentControl({ value, onChange, options, disabled = false }: SegmentControlProps) {
  return (
    <div className={`flex items-center bg-surface-base border border-border-default rounded overflow-hidden w-fit ${disabled ? "opacity-50 pointer-events-none" : ""}`}>
      {options.map(({ value: v, label }) => (
        <button
          key={v}
          type="button"
          onClick={() => onChange(v)}
          disabled={disabled}
          className={`px-3 py-1 text-xs transition-colors ${
            v === value
              ? "bg-accent/15 text-accent font-medium"
              : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

function Toggle({ checked, onChange, label }: SwitchProps) {
  return (
    <label className="flex items-center gap-2.5 cursor-pointer w-fit">
      <div
        role="switch"
        aria-checked={checked}
        aria-label={label}
        tabIndex={0}
        onClick={() => onChange(!checked)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onChange(!checked);
          }
        }}
        className={`relative inline-flex h-4 w-7 shrink-0 cursor-pointer rounded-full border border-transparent transition-colors focus:outline-none focus:ring-1 focus:ring-accent/30 ${
          checked ? "bg-accent" : "bg-surface-hover border-border-default"
        }`}
      >
        <span
          className={`pointer-events-none inline-block h-3 w-3 rounded-full bg-white shadow transform transition-transform mt-0.5 ${
            checked ? "translate-x-3" : "translate-x-0.5"
          }`}
        />
      </div>
      <span className="text-xs text-text-secondary">{label}</span>
    </label>
  );
}

function FieldRow({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <FieldLabel>{label}</FieldLabel>
      {children}
      {hint && <p className="text-xs text-text-muted mt-0.5">{hint}</p>}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-heading font-semibold text-sm text-text-primary mb-4 pb-2 border-b border-border-default">
      {children}
    </h2>
  );
}

// ---------------------------------------------------------------------------
// Section: General
// ---------------------------------------------------------------------------

interface GeneralSectionProps {
  settings: GeneralSettings;
  onChange: (field: keyof GeneralSettings, value: string) => void;
}

function GeneralSection({ settings, onChange }: GeneralSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>General</SectionTitle>

      <FieldRow
        label="Theme"
        hint="Light theme coming in a future release. Dark mode only for now."
      >
        <SegmentControl
          value={settings.theme}
          onChange={() => {}} // dark-only for now
          disabled={true}
          options={[
            { value: "dark",  label: "Dark"  },
            { value: "light", label: "Light" },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Font Size"
        hint="Affects data tables and number displays across the terminal."
      >
        <SegmentControl
          value={settings.fontSize}
          onChange={(v) => onChange("fontSize", v)}
          options={[
            { value: "small",  label: "Small (12px)"  },
            { value: "normal", label: "Normal (13px)" },
            { value: "large",  label: "Large (14px)"  },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Density"
        hint="Compact reduces row padding for more data on screen."
      >
        <SegmentControl
          value={settings.density}
          onChange={(v) => onChange("density", v)}
          options={[
            { value: "compact",     label: "Compact"     },
            { value: "comfortable", label: "Comfortable" },
          ]}
        />
      </FieldRow>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: API Connection
// ---------------------------------------------------------------------------

interface ApiSectionProps {
  settings: ApiSettings;
  onChange: (field: keyof ApiSettings, value: string) => void;
}

function ApiSection({ settings, onChange }: ApiSectionProps) {
  const [testing, setTesting]         = useState(false);
  const [connStatus, setConnStatus]   = useState<"connected" | "failed" | null>(null);
  const [connMessage, setConnMessage] = useState("");

  async function handleTestConnection() {
    setTesting(true);
    setConnStatus(null);
    setConnMessage("");
    try {
      await ping();
      setConnStatus("connected");
      setConnMessage("OpenAlgo is reachable and responding.");
    } catch (e) {
      setConnStatus("failed");
      setConnMessage(e instanceof Error ? e.message : "Connection failed. Check host and API key.");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle>API Connection</SectionTitle>

      <FieldRow
        label="OpenAlgo Host"
        hint="Base URL of your OpenAlgo instance. Set VITE_OPENALGO_HOST in .env to override at build time."
      >
        <TextInput
          value={settings.host}
          onChange={(v) => onChange("host", v)}
          placeholder="http://127.0.0.1:5000"
        />
      </FieldRow>

      <FieldRow
        label="API Key"
        hint="Your OpenAlgo API key. Stored in localStorage — do not use on shared machines."
      >
        <TextInput
          value={settings.apiKey}
          onChange={(v) => onChange("apiKey", v)}
          type="password"
          placeholder="••••••••••••••••"
        />
      </FieldRow>

      <FieldRow
        label="WebSocket Port"
        hint="OpenAlgo WebSocket port (default 8765). Used for live tick data."
      >
        <TextInput
          value={settings.wsPort}
          onChange={(v) => onChange("wsPort", v)}
          placeholder="8765"
        />
      </FieldRow>

      <div className="space-y-2">
        <button
          type="button"
          onClick={() => void handleTestConnection()}
          disabled={testing}
          className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium rounded bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 hover:border-accent/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {testing ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Wifi size={12} />
          )}
          {testing ? "Testing…" : "Test Connection"}
        </button>

        {connStatus && (
          <div className={`flex items-center gap-2 px-3 py-2 rounded text-xs border ${
            connStatus === "connected"
              ? "bg-profit/10 border-profit/20 text-profit"
              : "bg-loss/10 border-loss/20 text-loss"
          }`}>
            {connStatus === "connected" ? (
              <CheckCircle2 size={13} />
            ) : (
              <XCircle size={13} />
            )}
            <span>{connMessage}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Trading Defaults
// ---------------------------------------------------------------------------

interface TradingDefaultsSectionProps {
  settings: TradingSettings;
  onChange: (field: keyof TradingSettings, value: string) => void;
}

function TradingDefaultsSection({ settings, onChange }: TradingDefaultsSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Trading Defaults</SectionTitle>

      <FieldRow label="Default Exchange">
        <SelectInput
          value={settings.exchange}
          onChange={(v) => onChange("exchange", v)}
          options={[
            { value: "NSE", label: "NSE — National Stock Exchange" },
            { value: "NFO", label: "NFO — NSE F&O"                },
            { value: "BSE", label: "BSE — Bombay Stock Exchange"   },
            { value: "BFO", label: "BFO — BSE F&O"                },
            { value: "MCX", label: "MCX — Multi Commodity Exchange"},
            { value: "CDS", label: "CDS — Currency Derivatives"   },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Default Product"
        hint="MIS = intraday, NRML = overnight F&O, CNC = delivery equity."
      >
        <SegmentControl
          value={settings.product}
          onChange={(v) => onChange("product", v)}
          options={[
            { value: "MIS",  label: "MIS"  },
            { value: "NRML", label: "NRML" },
            { value: "CNC",  label: "CNC"  },
          ]}
        />
      </FieldRow>

      <FieldRow label="Default Order Type">
        <SegmentControl
          value={settings.orderType}
          onChange={(v) => onChange("orderType", v)}
          options={[
            { value: "MARKET", label: "Market" },
            { value: "LIMIT",  label: "Limit"  },
            { value: "SL",     label: "SL"     },
            { value: "SL-M",   label: "SL-M"   },
          ]}
        />
      </FieldRow>

      <FieldRow
        label="Default Quantity"
        hint="Pre-filled quantity in order forms. Can be overridden per order."
      >
        <TextInput
          value={settings.quantity}
          onChange={(v) => onChange("quantity", v)}
          placeholder="1"
          type="number"
        />
      </FieldRow>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Risk Limits
// ---------------------------------------------------------------------------

interface RiskSectionProps {
  settings: RiskSettings;
  onChange: (field: keyof RiskSettings, value: string) => void;
}

function RiskSection({ settings, onChange }: RiskSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Risk Limits</SectionTitle>

      <div className="p-3 rounded bg-warning/5 border border-warning/20 text-xs text-warning/80">
        Risk limits are enforced client-side only. They do NOT replace broker-level risk controls.
        Always configure limits at the broker or OpenAlgo level as your primary protection.
      </div>

      <FieldRow
        label="Max Position Size (lots)"
        hint="Maximum number of lots per position. Leave blank to disable."
      >
        <TextInput
          value={settings.maxPositionLots}
          onChange={(v) => onChange("maxPositionLots", v)}
          placeholder="e.g. 10"
          type="number"
        />
      </FieldRow>

      <FieldRow
        label="MTM Stoploss (₹)"
        hint="Mark-to-market loss limit. Enter as negative number (e.g. -5000). Leave blank to disable."
      >
        <TextInput
          value={settings.mtmStoploss}
          onChange={(v) => onChange("mtmStoploss", v)}
          placeholder="e.g. -5000"
          type="number"
        />
      </FieldRow>

      <FieldRow
        label="MTM Target (₹)"
        hint="Mark-to-market profit target. Leave blank to disable."
      >
        <TextInput
          value={settings.mtmTarget}
          onChange={(v) => onChange("mtmTarget", v)}
          placeholder="e.g. 10000"
          type="number"
        />
      </FieldRow>

      <FieldRow
        label="Max Orders per Minute"
        hint="Rate limit for order placement. Leave blank to use OpenAlgo default (10/sec)."
      >
        <TextInput
          value={settings.maxOrdersPerMinute}
          onChange={(v) => onChange("maxOrdersPerMinute", v)}
          placeholder="e.g. 20"
          type="number"
        />
      </FieldRow>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Keyboard Shortcuts (read-only display)
// ---------------------------------------------------------------------------

interface ShortcutRowProps {
  keys: string[];
  action: string;
}

function ShortcutRow({ keys, action }: ShortcutRowProps) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border-default last:border-0">
      <span className="text-xs text-text-secondary">{action}</span>
      <div className="flex items-center gap-1">
        {keys.map((k, i) => (
          <span key={i}>
            <kbd className="px-1.5 py-0.5 text-xs font-mono font-medium bg-surface-base border border-border-default rounded text-text-primary">
              {k}
            </kbd>
            {i < keys.length - 1 && (
              <span className="text-xs text-text-muted mx-0.5">+</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

function KeyboardSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>Keyboard Shortcuts</SectionTitle>

      <div className="p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        Shortcut customisation is coming in a future release. These defaults are active now.
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Order Placement</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Shift", "↑"]} action="Buy CE (call option)" />
          <ShortcutRow keys={["Shift", "↓"]} action="Buy PE (put option)"  />
          <ShortcutRow keys={["Shift", "←"]} action="Sell CE"              />
          <ShortcutRow keys={["Shift", "→"]} action="Sell PE"              />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Position Management</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["F6"]} action="Close All Positions"  />
          <ShortcutRow keys={["F7"]} action="Cancel All Orders"    />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Widget Navigation</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Ctrl", "W"]} action="Add widget"       />
          <ShortcutRow keys={["Ctrl", "/"]} action="Open command bar" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: LLM Config
// ---------------------------------------------------------------------------

interface LlmSectionProps {
  settings: LlmSettings;
  onChange: (field: keyof LlmSettings, value: string) => void;
}

function LlmSection({ settings, onChange }: LlmSectionProps) {
  const isLocal = LOCAL_PROVIDERS.has(settings.provider);

  return (
    <div className="space-y-5">
      <SectionTitle>LLM Config</SectionTitle>

      <FieldRow
        label="Provider"
        hint="Local providers (LM Studio, Ollama) run on your machine — no API key needed."
      >
        <SelectInput
          value={settings.provider}
          onChange={(v) => onChange("provider", v)}
          options={LLM_PROVIDER_OPTIONS}
        />
      </FieldRow>

      {isLocal && (
        <FieldRow
          label="Host URL"
          hint="Base URL of the local inference server."
        >
          <TextInput
            value={settings.host}
            onChange={(v) => onChange("host", v)}
            placeholder={settings.provider === "ollama" ? "http://127.0.0.1:11434" : "http://127.0.0.1:1234"}
          />
        </FieldRow>
      )}

      <FieldRow
        label="Model Name"
        hint={isLocal ? "Model identifier as listed in your local server (e.g. qwen3:9b)." : "Model identifier from the provider (e.g. gpt-4o)."}
      >
        <TextInput
          value={settings.model}
          onChange={(v) => onChange("model", v)}
          placeholder={isLocal ? "e.g. qwen3:9b" : "e.g. gpt-4o"}
        />
      </FieldRow>

      {!isLocal && (
        <FieldRow
          label="API Key"
          hint="Provider API key. Stored in localStorage — do not use on shared machines."
        >
          <TextInput
            value={settings.apiKey}
            onChange={(v) => onChange("apiKey", v)}
            type="password"
            placeholder="sk-••••••••••••••••"
          />
        </FieldRow>
      )}

      {settings.provider === "custom" && (
        <FieldRow
          label="Custom Endpoint Base URL"
          hint="Full base URL of an OpenAI-compatible custom endpoint."
        >
          <TextInput
            value={settings.host}
            onChange={(v) => onChange("host", v)}
            placeholder="https://your-custom-endpoint.example.com"
          />
        </FieldRow>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Telegram
// ---------------------------------------------------------------------------

interface TelegramSectionProps {
  settings: TelegramSettings;
  onChangeField: (field: keyof TelegramSettings, value: string | boolean) => void;
}

function TelegramSection({ settings, onChangeField }: TelegramSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Telegram</SectionTitle>

      <FieldRow label="Enable Telegram notifications">
        <Toggle
          checked={settings.enabled}
          onChange={(v) => onChangeField("enabled", v)}
          label={settings.enabled ? "Enabled" : "Disabled"}
        />
      </FieldRow>

      <FieldRow
        label="Bot Token"
        hint="Create a bot via @BotFather on Telegram. Stored in localStorage."
      >
        <TextInput
          value={settings.botToken}
          onChange={(v) => onChangeField("botToken", v)}
          type="password"
          placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
          disabled={!settings.enabled}
        />
      </FieldRow>

      <FieldRow
        label="Chat ID"
        hint="Your personal or group chat ID. Use @userinfobot to find it."
      >
        <TextInput
          value={settings.chatId}
          onChange={(v) => onChangeField("chatId", v)}
          placeholder="-100123456789"
          disabled={!settings.enabled}
        />
      </FieldRow>

      {settings.enabled && (
        <div className="p-3 rounded bg-accent/5 border border-accent/20 text-xs text-text-secondary space-y-1">
          <p className="font-medium text-text-primary">Telegram alerts include:</p>
          <ul className="list-disc list-inside space-y-0.5 text-text-muted">
            <li>Order placed / modified / cancelled</li>
            <li>MTM stoploss triggered</li>
            <li>MTM target reached</li>
            <li>Position closed</li>
            <li>Kill switch (send /killswitch to the bot)</li>
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: Data Paths
// ---------------------------------------------------------------------------

interface DataPathsSectionProps {
  settings: DataPathSettings;
  onChange: (field: keyof DataPathSettings, value: string) => void;
}

function DataPathsSection({ settings, onChange }: DataPathsSectionProps) {
  return (
    <div className="space-y-5">
      <SectionTitle>Data Paths</SectionTitle>

      <div className="p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        Storage paths are read by the Python backend on startup. Changes take effect after restarting services.
        Leave blank to use the default path (<code className="font-mono text-text-secondary">~/.flinttrade/</code>).
      </div>

      <FieldRow
        label="Fast Storage Path"
        hint="DuckDB database and intraday tick cache. Use an SSD path for best performance."
      >
        <TextInput
          value={settings.fastStoragePath}
          onChange={(v) => onChange("fastStoragePath", v)}
          placeholder="~/.flinttrade/data/fast"
        />
      </FieldRow>

      <FieldRow
        label="Archive Storage Path"
        hint="Long-term OHLCV history and SEBI audit logs (5-year retention required). Can be a slower disk."
      >
        <TextInput
          value={settings.archiveStoragePath}
          onChange={(v) => onChange("archiveStoragePath", v)}
          placeholder="~/.flinttrade/data/archive"
        />
      </FieldRow>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section: About
// ---------------------------------------------------------------------------

function AboutSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>About</SectionTitle>

      <div className="flex items-center gap-3 p-4 rounded-lg bg-surface-card border border-border-default">
        <div className="flex-none w-10 h-10 rounded-lg bg-accent/10 border border-accent/20 flex items-center justify-center">
          <Settings size={18} className="text-accent" />
        </div>
        <div>
          <div className="text-sm font-semibold text-text-primary">FlintTrade</div>
          <div className="text-xs text-text-muted">Version 0.1.0-alpha</div>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Description</p>
        <p className="text-xs text-text-secondary leading-relaxed">
          Open-source modular trading and investment platform for Indian F&amp;O, commodities, and crypto.
          Built on OpenAlgo (30+ broker gateway). Monorepo with 12 packages (11 Python + 1 React).
        </p>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Links</p>
        <div className="space-y-1.5">
          <a
            href="https://github.com/navaneeshnagarajan/FlintTrade"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <Github size={12} className="flex-none text-text-muted" />
            <span>GitHub — navaneeshnagarajan/FlintTrade</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
          <a
            href="https://github.com/navaneeshnagarajan/openalgo"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <ExternalLink size={12} className="flex-none text-text-muted" />
            <span>OpenAlgo — Broker Gateway</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
          <a
            href="https://www.gnu.org/licenses/agpl-3.0.html"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 px-3 py-2 rounded border border-border-default bg-surface-card hover:bg-surface-hover text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <ExternalLink size={12} className="flex-none text-text-muted" />
            <span>License — GNU AGPL-3.0</span>
            <ExternalLink size={10} className="ml-auto text-text-muted flex-none" />
          </a>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted">Build Info</p>
        <div className="rounded border border-border-default overflow-hidden">
          <table className="w-full text-xs">
            <tbody>
              {[
                ["Version",   "0.1.0-alpha"],
                ["React",     "19"],
                ["Dockview",  "5.1"],
                ["License",   "AGPL-3.0"],
              ].map(([key, val]) => (
                <tr key={key} className="border-b border-border-default last:border-0">
                  <td className="px-3 py-1.5 text-text-muted w-32">{key}</td>
                  <td className="px-3 py-1.5 text-text-primary font-mono">{val}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline toast (no external toast library available)
// ---------------------------------------------------------------------------

interface ToastProps {
  message: string;
  onDismiss: () => void;
}

function InlineToast({ message, onDismiss }: ToastProps) {
  useEffect(() => {
    const id = setTimeout(onDismiss, 3000);
    return () => clearTimeout(id);
  }, [onDismiss]);

  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded text-xs border bg-profit/10 border-profit/20 text-profit">
      <CheckCircle2 size={13} className="flex-none" />
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props {
  onClose?: () => void;
}

export default function SettingsTool({ onClose }: Props) {
  const [activeSection, setActiveSection] = useState<SectionId>("general");
  const [settings, setSettings]           = useState<AllSettings>(loadSettings);
  const [restarting, setRestarting]       = useState(false);
  const [toastMsg, setToastMsg]           = useState<string | null>(null);
  const dismissToast                      = useCallback(() => setToastMsg(null), []);

  // Persist on every settings change
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  // Typed updater for simple string fields
  const updateSection = useCallback(<K extends keyof AllSettings>(
    sectionId: K,
    field: keyof AllSettings[K],
    value: string,
  ) => {
    setSettings((prev) => ({
      ...prev,
      [sectionId]: {
        ...prev[sectionId],
        [field]: value,
      },
    }));
  }, []);

  // Updater for Telegram (mixed string | boolean)
  const updateTelegram = useCallback((field: keyof TelegramSettings, value: string | boolean) => {
    setSettings((prev) => ({
      ...prev,
      telegram: {
        ...prev.telegram,
        [field]: value,
      },
    }));
  }, []);

  // Restart Services
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleRestart() {
    if (restarting) return;
    saveSettings(settings);
    setRestarting(true);
    resetWsService();
    restartRef.current = setTimeout(() => {
      setRestarting(false);
      setToastMsg("Services restarted");
    }, 800);
  }

  useEffect(() => {
    return () => {
      if (restartRef.current) clearTimeout(restartRef.current);
    };
  }, []);

  function renderPanel(): JSX.Element {
    switch (activeSection) {
      case "general":
        return (
          <GeneralSection
            settings={settings.general}
            onChange={(field, value) => updateSection("general", field, value)}
          />
        );
      case "api":
        return (
          <ApiSection
            settings={settings.api}
            onChange={(field, value) => updateSection("api", field, value)}
          />
        );
      case "trading":
        return (
          <TradingDefaultsSection
            settings={settings.trading}
            onChange={(field, value) => updateSection("trading", field, value)}
          />
        );
      case "risk":
        return (
          <RiskSection
            settings={settings.risk}
            onChange={(field, value) => updateSection("risk", field, value)}
          />
        );
      case "keyboard":
        return <KeyboardSection />;
      case "llm":
        return (
          <LlmSection
            settings={settings.llm}
            onChange={(field, value) => updateSection("llm", field, value)}
          />
        );
      case "telegram":
        return (
          <TelegramSection
            settings={settings.telegram}
            onChangeField={updateTelegram}
          />
        );
      case "dataPaths":
        return (
          <DataPathsSection
            settings={settings.dataPaths}
            onChange={(field, value) => updateSection("dataPaths", field, value)}
          />
        );
      case "about":
        return <AboutSection />;
    }
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Title bar */}
      <div className="flex-none flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2">
          <Settings size={14} className="text-accent" />
          <span className="font-heading font-bold text-lg text-text-primary">Settings</span>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
            aria-label="Close settings"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* Body: sidebar + panel */}
      <div className="flex-1 flex overflow-hidden">

        {/* Sidebar */}
        <nav className="w-44 flex-none bg-surface-card border-r border-border-default overflow-y-auto py-2" aria-label="Settings sections">
          {SECTIONS.map((section) => {
            const Icon     = section.icon;
            const isActive = section.id === activeSection;
            return (
              <button
                key={section.id}
                type="button"
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 font-sans text-sm transition-colors text-left ${
                  isActive
                    ? "bg-accent/10 text-accent border-r-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                <Icon size={13} className="flex-none" />
                <span className="truncate">{section.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Right panel */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {renderPanel()}
        </div>
      </div>

      {/* Footer */}
      <div className="flex-none px-4 py-2 bg-surface-card border-t border-border-default space-y-2">

        {/* Toast */}
        {toastMsg && (
          <InlineToast message={toastMsg} onDismiss={dismissToast} />
        )}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-profit" />
            <span className="text-xs text-text-muted">Changes saved automatically</span>
          </div>

          <button
            type="button"
            onClick={handleRestart}
            disabled={restarting}
            className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded bg-surface-base border border-border-default text-text-secondary hover:text-text-primary hover:border-accent/40 hover:bg-accent/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={11} className={restarting ? "animate-spin" : ""} />
            {restarting ? "Restarting…" : "Restart Services"}
          </button>
        </div>
      </div>
    </div>
  );
}
