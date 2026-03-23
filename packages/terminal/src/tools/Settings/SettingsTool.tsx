/**
 * SettingsTool — Settings panel orchestrator for FlintTrade terminal.
 *
 * Layout: left sidebar (section nav) + right panel (active section).
 * Persistence: localStorage key "flinttrade:settings"
 * All section components live in separate files in this directory.
 */

import { useState, useEffect, useCallback, useRef, type JSX } from "react";
import {
  X, Settings, Monitor, Wifi, TrendingUp, ShieldAlert,
  Keyboard, Brain, Send, HardDrive, Info, Palette, RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { resetWsService } from "@/services/websocket";
import { InlineToast } from "./shared";
import { GeneralSection } from "./GeneralSection";
import { AppearanceSection } from "./AppearanceSection";
import { ConnectionSection } from "./ConnectionSection";
import { TradingSection } from "./TradingSection";
import { RiskSection } from "./RiskSection";
import { KeyboardSection } from "./KeyboardSection";
import { LLMSection } from "./LLMSection";
import { TelegramSection } from "./TelegramSection";
import { DataSection } from "./DataSection";
import { AboutSection } from "./AboutSection";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LlmProvider = "lmstudio" | "ollama" | "openai" | "anthropic" | "gemini"
  | "deepseek" | "groq" | "grok" | "mistral" | "together" | "openrouter" | "custom";

interface AllSettings {
  general:   { fontSize: "small" | "normal" | "large"; density: "compact" | "comfortable" };
  api:       { host: string; apiKey: string; wsPort: string };
  trading:   { exchange: string; product: "MIS" | "NRML" | "CNC"; orderType: "MARKET" | "LIMIT" | "SL" | "SL-M"; quantity: string };
  risk:      { maxPositionLots: string; mtmStoploss: string; mtmTarget: string; maxOrdersPerMinute: string };
  llm:       { provider: LlmProvider; host: string; model: string; apiKey: string };
  telegram:  { enabled: boolean; botToken: string; chatId: string };
  dataPaths: { fastStoragePath: string; archiveStoragePath: string };
}

type SectionId = "general" | "appearance" | "api" | "trading" | "risk" | "keyboard" | "llm" | "telegram" | "dataPaths" | "about";

interface SectionDef { id: SectionId; label: string; icon: LucideIcon }

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STORAGE_KEY = "flinttrade:settings";

const DEFAULT_SETTINGS: AllSettings = {
  general:   { fontSize: "normal", density: "comfortable" },
  api:       { host: "", apiKey: "", wsPort: "8765" },
  trading:   { exchange: "NSE", product: "MIS", orderType: "MARKET", quantity: "1" },
  risk:      { maxPositionLots: "", mtmStoploss: "", mtmTarget: "", maxOrdersPerMinute: "" },
  llm:       { provider: "lmstudio", host: "http://127.0.0.1:1234", model: "", apiKey: "" },
  telegram:  { enabled: false, botToken: "", chatId: "" },
  dataPaths: { fastStoragePath: "", archiveStoragePath: "" },
};

const SECTIONS: SectionDef[] = [
  { id: "general",    label: "General",           icon: Monitor     },
  { id: "appearance", label: "Appearance",         icon: Palette     },
  { id: "api",        label: "API Connection",     icon: Wifi        },
  { id: "trading",    label: "Trading Defaults",   icon: TrendingUp  },
  { id: "risk",       label: "Risk Limits",        icon: ShieldAlert },
  { id: "keyboard",   label: "Keyboard Shortcuts", icon: Keyboard    },
  { id: "llm",        label: "LLM Config",         icon: Brain       },
  { id: "telegram",   label: "Telegram",           icon: Send        },
  { id: "dataPaths",  label: "Data Paths",         icon: HardDrive   },
  { id: "about",      label: "About",              icon: Info        },
];

// ---------------------------------------------------------------------------
// Persistence
// ---------------------------------------------------------------------------

function loadSettings(): AllSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const p = JSON.parse(raw) as Partial<AllSettings>;
    return {
      general:   { ...DEFAULT_SETTINGS.general,   ...(p.general   ?? {}) },
      api:       { ...DEFAULT_SETTINGS.api,        ...(p.api       ?? {}) },
      trading:   { ...DEFAULT_SETTINGS.trading,    ...(p.trading   ?? {}) },
      risk:      { ...DEFAULT_SETTINGS.risk,       ...(p.risk      ?? {}) },
      llm:       { ...DEFAULT_SETTINGS.llm,        ...(p.llm       ?? {}) },
      telegram:  { ...DEFAULT_SETTINGS.telegram,   ...(p.telegram  ?? {}) },
      dataPaths: { ...DEFAULT_SETTINGS.dataPaths,  ...(p.dataPaths ?? {}) },
    };
  } catch { return DEFAULT_SETTINGS; }
}

function saveSettings(s: AllSettings): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch { /* private browsing */ }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface Props { onClose?: () => void }

export default function SettingsTool({ onClose }: Props) {
  const [activeSection, setActiveSection] = useState<SectionId>("general");
  const [settings, setSettings]           = useState<AllSettings>(loadSettings);
  const [restarting, setRestarting]       = useState(false);
  const [toastMsg, setToastMsg]           = useState<string | null>(null);
  const dismissToast                      = useCallback(() => setToastMsg(null), []);
  const restartRef                        = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { saveSettings(settings); }, [settings]);
  useEffect(() => () => { if (restartRef.current) clearTimeout(restartRef.current); }, []);

  const updateSection = useCallback(<K extends keyof AllSettings>(
    sectionId: K, field: keyof AllSettings[K], value: string,
  ) => {
    setSettings((prev) => ({ ...prev, [sectionId]: { ...prev[sectionId], [field]: value } }));
  }, []);

  const updateTelegram = useCallback((field: keyof AllSettings["telegram"], value: string | boolean) => {
    setSettings((prev) => ({ ...prev, telegram: { ...prev.telegram, [field]: value } }));
  }, []);

  function handleRestart() {
    if (restarting) return;
    saveSettings(settings);
    setRestarting(true);
    resetWsService();
    restartRef.current = setTimeout(() => { setRestarting(false); setToastMsg("Services restarted"); }, 800);
  }

  function renderPanel(): JSX.Element {
    switch (activeSection) {
      case "general":    return <GeneralSection    settings={settings.general}   onChange={(f, v) => updateSection("general", f, v)} />;
      case "appearance": return <AppearanceSection />;
      case "api":        return <ConnectionSection settings={settings.api}       onChange={(f, v) => updateSection("api", f, v)} />;
      case "trading":    return <TradingSection    settings={settings.trading}   onChange={(f, v) => updateSection("trading", f, v)} />;
      case "risk":       return <RiskSection       settings={settings.risk}      onChange={(f, v) => updateSection("risk", f, v)} />;
      case "keyboard":   return <KeyboardSection />;
      case "llm":        return <LLMSection        settings={settings.llm}       onChange={(f, v) => updateSection("llm", f, v)} />;
      case "telegram":   return <TelegramSection   settings={settings.telegram}  onChangeField={updateTelegram} />;
      case "dataPaths":  return <DataSection       settings={settings.dataPaths} onChange={(f, v) => updateSection("dataPaths", f, v)} />;
      case "about":      return <AboutSection />;
    }
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden animate-fade-in">

      {/* Title bar */}
      <div className="flex-none flex items-center justify-between px-4 py-2.5 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2">
          <Settings size={14} className="text-accent" />
          <span className="font-heading font-bold text-lg text-text-primary">Settings</span>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors" aria-label="Close settings">
            <X size={14} />
          </button>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">
        <nav className="w-44 flex-none bg-surface-card border-r border-border-default overflow-y-auto py-2" aria-label="Settings sections">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveSection(id)}
              className={`w-full flex items-center gap-2.5 px-3 py-2 font-sans text-sm transition-colors text-left ${
                id === activeSection
                  ? "bg-accent/10 text-accent border-r-2 border-accent"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              <Icon size={13} className="flex-none" />
              <span className="truncate">{label}</span>
            </button>
          ))}
        </nav>
        <div className="flex-1 overflow-y-auto px-6 py-5">{renderPanel()}</div>
      </div>

      {/* Footer */}
      <div className="flex-none px-4 py-2 bg-surface-card border-t border-border-default space-y-2">
        {toastMsg && <InlineToast message={toastMsg} onDismiss={dismissToast} />}
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
