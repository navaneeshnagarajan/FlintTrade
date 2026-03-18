/**
 * SettingsTool — Full settings panel for FlintTrade terminal.
 *
 * Layout: left sidebar with section names, right panel with active section form.
 * Persistence: localStorage key "flinttrade:settings"
 * Functional sections: General, API Connection, Trading Defaults, Risk
 * Stub sections: Keyboard, LLM, Telegram, Ditto, Automation, Layouts, About
 */

import { useState, useEffect, useCallback } from "react";
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
  Copy,
  Bot,
  Layout,
  Info,
  CheckCircle2,
  XCircle,
  Loader2,
} from "lucide-react";
import { ping } from "../../services/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:settings";

const DEFAULT_SETTINGS = {
  general: {
    theme: "dark",
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
};

const SECTIONS = [
  { id: "general",   label: "General",          icon: Monitor,    functional: true  },
  { id: "api",       label: "API Connection",    icon: Wifi,       functional: true  },
  { id: "trading",   label: "Trading Defaults",  icon: TrendingUp, functional: true  },
  { id: "risk",      label: "Risk",              icon: ShieldAlert,functional: true  },
  { id: "keyboard",  label: "Keyboard",          icon: Keyboard,   functional: false },
  { id: "llm",       label: "LLM",               icon: Brain,      functional: false },
  { id: "telegram",  label: "Telegram",          icon: Send,       functional: false },
  { id: "ditto",     label: "Ditto",             icon: Copy,       functional: false },
  { id: "automation",label: "Automation",        icon: Bot,        functional: false },
  { id: "layouts",   label: "Layouts",           icon: Layout,     functional: false },
  { id: "about",     label: "About",             icon: Info,       functional: false },
];

// ---------------------------------------------------------------------------
// Persistence helpers
// ---------------------------------------------------------------------------

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw);
    // Deep merge with defaults to handle new keys added after first save
    return {
      general:  { ...DEFAULT_SETTINGS.general,  ...(parsed.general  ?? {}) },
      api:      { ...DEFAULT_SETTINGS.api,       ...(parsed.api      ?? {}) },
      trading:  { ...DEFAULT_SETTINGS.trading,   ...(parsed.trading  ?? {}) },
      risk:     { ...DEFAULT_SETTINGS.risk,      ...(parsed.risk     ?? {}) },
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable (private browsing, etc.)
  }
}

// ---------------------------------------------------------------------------
// Reusable form primitives
// ---------------------------------------------------------------------------

function Label({ children }) {
  return (
    <label className="block text-xs text-text-secondary mb-1">{children}</label>
  );
}

function TextInput({ value, onChange, placeholder, type = "text", disabled = false }) {
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

function SelectInput({ value, onChange, options }) {
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

function SegmentControl({ value, onChange, options }) {
  return (
    <div className="flex items-center bg-surface-base border border-border-default rounded overflow-hidden w-fit">
      {options.map(({ value: v, label }) => (
        <button
          key={v}
          onClick={() => onChange(v)}
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

function FieldRow({ label, children }) {
  return (
    <div className="space-y-1">
      <Label>{label}</Label>
      {children}
    </div>
  );
}

function SectionTitle({ children }) {
  return (
    <h2 className="text-sm font-semibold text-text-primary mb-4 pb-2 border-b border-border-default">
      {children}
    </h2>
  );
}

function HintText({ children }) {
  return <p className="text-[10px] text-text-muted mt-0.5">{children}</p>;
}

// ---------------------------------------------------------------------------
// Section panels
// ---------------------------------------------------------------------------

function GeneralSection({ settings, onChange }) {
  return (
    <div className="space-y-5">
      <SectionTitle>General</SectionTitle>

      <FieldRow label="Theme">
        <SegmentControl
          value={settings.theme}
          onChange={() => {}} // dark-only for now
          options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]}
        />
        <HintText>Light theme coming in a future release. Dark mode only for now.</HintText>
      </FieldRow>

      <FieldRow label="Font Size">
        <SegmentControl
          value={settings.fontSize}
          onChange={(v) => onChange("fontSize", v)}
          options={[
            { value: "small",  label: "Small"  },
            { value: "normal", label: "Normal" },
            { value: "large",  label: "Large"  },
          ]}
        />
        <HintText>Affects data tables and number displays across the terminal.</HintText>
      </FieldRow>

      <FieldRow label="Density">
        <SegmentControl
          value={settings.density}
          onChange={(v) => onChange("density", v)}
          options={[
            { value: "compact",     label: "Compact"     },
            { value: "comfortable", label: "Comfortable" },
          ]}
        />
        <HintText>Compact reduces row padding for more data on screen.</HintText>
      </FieldRow>
    </div>
  );
}

function ApiSection({ settings, onChange }) {
  const [testing, setTesting] = useState(false);
  const [connStatus, setConnStatus] = useState(null); // null | "connected" | "failed"
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
      setConnMessage(e.message || "Connection failed. Check host and API key.");
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle>API Connection</SectionTitle>

      <FieldRow label="OpenAlgo Host">
        <TextInput
          value={settings.host}
          onChange={(v) => onChange("host", v)}
          placeholder="http://127.0.0.1:5000"
        />
        <HintText>Base URL of your OpenAlgo instance. Set VITE_OPENALGO_HOST in .env to override at build time.</HintText>
      </FieldRow>

      <FieldRow label="API Key">
        <TextInput
          value={settings.apiKey}
          onChange={(v) => onChange("apiKey", v)}
          type="password"
          placeholder="••••••••••••••••"
        />
        <HintText>Your OpenAlgo API key. Stored in localStorage — do not use on shared machines.</HintText>
      </FieldRow>

      <FieldRow label="WebSocket Port">
        <TextInput
          value={settings.wsPort}
          onChange={(v) => onChange("wsPort", v)}
          placeholder="8765"
        />
        <HintText>OpenAlgo WebSocket port (default 8765). Used for live tick data.</HintText>
      </FieldRow>

      {/* Test connection button + status */}
      <div className="space-y-2">
        <button
          onClick={handleTestConnection}
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

function TradingDefaultsSection({ settings, onChange }) {
  return (
    <div className="space-y-5">
      <SectionTitle>Trading Defaults</SectionTitle>

      <FieldRow label="Default Exchange">
        <SelectInput
          value={settings.exchange}
          onChange={(v) => onChange("exchange", v)}
          options={[
            { value: "NSE", label: "NSE — National Stock Exchange" },
            { value: "NFO", label: "NFO — NSE F&O" },
            { value: "BSE", label: "BSE — Bombay Stock Exchange" },
            { value: "BFO", label: "BFO — BSE F&O" },
            { value: "MCX", label: "MCX — Multi Commodity Exchange" },
            { value: "CDS", label: "CDS — Currency Derivatives" },
          ]}
        />
      </FieldRow>

      <FieldRow label="Default Product">
        <SegmentControl
          value={settings.product}
          onChange={(v) => onChange("product", v)}
          options={[
            { value: "MIS",  label: "MIS"  },
            { value: "NRML", label: "NRML" },
            { value: "CNC",  label: "CNC"  },
          ]}
        />
        <HintText>MIS = intraday, NRML = overnight F&O, CNC = delivery equity.</HintText>
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

      <FieldRow label="Default Quantity">
        <TextInput
          value={settings.quantity}
          onChange={(v) => onChange("quantity", v)}
          placeholder="1"
          type="number"
        />
        <HintText>Pre-filled quantity in order forms. Can be overridden per order.</HintText>
      </FieldRow>
    </div>
  );
}

function RiskSection({ settings, onChange }) {
  return (
    <div className="space-y-5">
      <SectionTitle>Risk Management</SectionTitle>

      <div className="p-3 rounded bg-warning/5 border border-warning/20 text-[11px] text-warning/80">
        Risk limits are enforced client-side. They do NOT replace broker-level risk controls. Always configure risk at the broker/OpenAlgo level as primary protection.
      </div>

      <FieldRow label="Max Position Size (lots)">
        <TextInput
          value={settings.maxPositionLots}
          onChange={(v) => onChange("maxPositionLots", v)}
          placeholder="e.g. 10"
          type="number"
        />
        <HintText>Maximum number of lots per position. Leave blank to disable.</HintText>
      </FieldRow>

      <FieldRow label="MTM Stoploss (INR)">
        <TextInput
          value={settings.mtmStoploss}
          onChange={(v) => onChange("mtmStoploss", v)}
          placeholder="e.g. -5000"
          type="number"
        />
        <HintText>Mark-to-market loss limit. Enter as negative number (e.g. -5000). Leave blank to disable.</HintText>
      </FieldRow>

      <FieldRow label="MTM Target (INR)">
        <TextInput
          value={settings.mtmTarget}
          onChange={(v) => onChange("mtmTarget", v)}
          placeholder="e.g. 10000"
          type="number"
        />
        <HintText>Mark-to-market profit target. Leave blank to disable.</HintText>
      </FieldRow>

      <FieldRow label="Max Orders per Minute">
        <TextInput
          value={settings.maxOrdersPerMinute}
          onChange={(v) => onChange("maxOrdersPerMinute", v)}
          placeholder="e.g. 20"
          type="number"
        />
        <HintText>Rate limit for order placement. Leave blank to use OpenAlgo default (10/sec).</HintText>
      </FieldRow>
    </div>
  );
}

function StubSection({ section }) {
  const Icon = section.icon;
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-text-muted py-16">
      <Icon size={36} className="opacity-30" />
      <div className="text-center">
        <div className="text-sm font-medium text-text-secondary">{section.label}</div>
        <div className="text-xs text-text-muted mt-1 max-w-xs text-center leading-relaxed">
          {stubDescription(section.id)}
        </div>
      </div>
      <div className="mt-2 px-3 py-1 rounded-full text-[10px] text-text-muted border border-border-default">
        Coming soon
      </div>
    </div>
  );
}

function stubDescription(id) {
  const descriptions = {
    keyboard:   "Customise keyboard shortcuts for order placement, widget navigation, and terminal actions.",
    llm:        "Configure local or cloud LLM providers (Ollama, OpenAI, Anthropic) for AI signals and market analysis.",
    telegram:   "Set up a Telegram bot for trade alerts, MTM notifications, and remote kill-switch commands.",
    ditto:      "Mirror trades across multiple accounts with configurable lot ratios and margin controls.",
    automation: "Schedule strategies, configure cron jobs, and set up post-market analysis pipelines.",
    layouts:    "Save, load, and manage FlexLayout workspace configurations. Export and share layouts.",
    about:      "FlintTrade version, build info, OpenAlgo connection details, and open-source license.",
  };
  return descriptions[id] || "This section is under development.";
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function SettingsTool({ onClose }) {
  const [activeSection, setActiveSection] = useState("general");
  const [settings, setSettings] = useState(loadSettings);

  // Persist on every change
  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  // Generic updater for a top-level section key
  const updateSection = useCallback((sectionId, field, value) => {
    setSettings((prev) => ({
      ...prev,
      [sectionId]: {
        ...prev[sectionId],
        [field]: value,
      },
    }));
  }, []);

  const currentSection = SECTIONS.find((s) => s.id === activeSection);

  function renderPanel() {
    if (!currentSection?.functional) {
      return <StubSection section={currentSection} />;
    }

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
      default:
        return <StubSection section={currentSection} />;
    }
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* ── Title bar ── */}
      <div className="flex-none flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2">
          <Settings size={14} className="text-accent" />
          <span className="text-sm font-semibold text-text-primary">Settings</span>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          title="Close settings"
        >
          <X size={14} />
        </button>
      </div>

      {/* ── Body: sidebar + panel ── */}
      <div className="flex-1 flex overflow-hidden">

        {/* Sidebar */}
        <div className="w-44 flex-none bg-surface-card border-r border-border-default overflow-y-auto py-2">
          {SECTIONS.map((section) => {
            const Icon = section.icon;
            const isActive = section.id === activeSection;

            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-2.5 px-3 py-2 text-xs transition-colors text-left ${
                  isActive
                    ? "bg-accent/10 text-accent border-r-2 border-accent"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                <Icon size={13} className="flex-none" />
                <span className="truncate">{section.label}</span>
                {!section.functional && (
                  <span className="ml-auto text-[8px] text-text-muted bg-surface-hover px-1 py-0.5 rounded flex-none">
                    soon
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Right panel */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {renderPanel()}
        </div>
      </div>

      {/* ── Footer: autosave indicator ── */}
      <div className="flex-none px-4 py-1.5 bg-surface-card border-t border-border-default flex items-center gap-1.5">
        <div className="w-1.5 h-1.5 rounded-full bg-profit" />
        <span className="text-[10px] text-text-muted">Changes saved automatically to local storage</span>
      </div>
    </div>
  );
}
