/**
 * SettingsRoute — standalone /settings full-page.
 *
 * Accessible from ALL routes via the TOOLS dropdown.
 * Uses the same section components as SettingsTool so settings
 * are shared (both read/write the same localStorage key).
 *
 * Layout: slim header + left sidebar nav + scrollable content area.
 */

import { useState, useEffect, useCallback, useRef, type JSX } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, Monitor, Palette, Wifi, TrendingUp, ShieldAlert,
  Keyboard, Brain, Send, HardDrive, Info, RefreshCw,
  type LucideIcon,
} from "lucide-react";
import { resetWsService } from "@/services/websocket";
import { LogoIcon } from "@/components/brand/Logo";
import { InlineToast } from "@/tools/Settings/shared";
import { GeneralSection }    from "@/tools/Settings/GeneralSection";
import { AppearanceSection } from "@/tools/Settings/AppearanceSection";
import { ConnectionSection } from "@/tools/Settings/ConnectionSection";
import { TradingSection }    from "@/tools/Settings/TradingSection";
import { RiskSection }       from "@/tools/Settings/RiskSection";
import { KeyboardSection }   from "@/tools/Settings/KeyboardSection";
import { LLMSection }        from "@/tools/Settings/LLMSection";
import { TelegramSection }   from "@/tools/Settings/TelegramSection";
import { DataSection }       from "@/tools/Settings/DataSection";
import { AboutSection }      from "@/tools/Settings/AboutSection";

// ---------------------------------------------------------------------------
// Types (mirror SettingsTool so same localStorage key is compatible)
// ---------------------------------------------------------------------------

type LlmProvider =
  | "lmstudio" | "ollama" | "openai" | "anthropic" | "gemini"
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

type SectionId =
  | "general" | "appearance" | "api" | "trading" | "risk"
  | "keyboard" | "llm" | "telegram" | "dataPaths" | "about";

interface SectionDef { id: SectionId; label: string; icon: LucideIcon }

// ---------------------------------------------------------------------------
// Constants — same storage key as SettingsTool so changes are shared
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
// Persistence helpers
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
// Route component
// ---------------------------------------------------------------------------

export default function SettingsRoute() {
  const navigate = useNavigate();

  // Read hash fragment to allow deep-linking: /settings#api
  const initialSection = (): SectionId => {
    const hash = window.location.hash.replace("#", "") as SectionId;
    return SECTIONS.some((s) => s.id === hash) ? hash : "general";
  };

  const [activeSection, setActiveSection] = useState<SectionId>(initialSection);
  const [settings, setSettings]           = useState<AllSettings>(loadSettings);
  const [restarting, setRestarting]       = useState(false);
  const [toastMsg, setToastMsg]           = useState<string | null>(null);
  const dismissToast                      = useCallback(() => setToastMsg(null), []);
  const restartRef                        = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Persist on every change (same behaviour as SettingsTool)
  useEffect(() => { saveSettings(settings); }, [settings]);
  useEffect(() => () => { if (restartRef.current) clearTimeout(restartRef.current); }, []);

  // Update hash when section changes for deep-link support
  useEffect(() => {
    window.history.replaceState(null, "", `#${activeSection}`);
  }, [activeSection]);

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
    restartRef.current = setTimeout(() => {
      setRestarting(false);
      setToastMsg("Services restarted");
    }, 800);
  }

  function renderContent(): JSX.Element {
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
    <main
      aria-label="Settings"
      className="fixed inset-0 bg-surface-base flex flex-col overflow-hidden animate-fade-in"
    >
      {/* Slim header */}
      <div className="flex items-center gap-3 px-4 h-10 border-b border-border-default bg-surface-card shrink-0">
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="flex items-center gap-1.5 text-text-muted hover:text-text-primary text-xs transition-colors"
          aria-label="Go back"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="w-px h-4 bg-border-default" />
        <div className="flex items-center gap-1.5">
          <LogoIcon size={16} />
          <span className="font-heading font-semibold text-xs text-text-secondary">Settings</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {toastMsg && <InlineToast message={toastMsg} onDismiss={dismissToast} />}
          <button
            type="button"
            onClick={handleRestart}
            disabled={restarting}
            className="flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded bg-surface-base border border-border-default text-text-secondary hover:text-text-primary hover:border-accent/40 hover:bg-accent/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={11} className={restarting ? "animate-spin" : ""} />
            {restarting ? "Restarting..." : "Restart Services"}
          </button>
        </div>
      </div>

      {/* Body: sidebar + content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar nav */}
        <nav
          className="w-52 flex-none bg-surface-card border-r border-border-default overflow-y-auto py-2 shrink-0"
          aria-label="Settings sections"
        >
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveSection(id)}
              aria-current={id === activeSection ? "page" : undefined}
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

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          <div className="max-w-2xl px-8 py-6">
            {renderContent()}
          </div>
        </div>
      </div>

      {/* Footer status bar */}
      <div className="flex-none px-4 py-2 bg-surface-card border-t border-border-default flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-profit" />
        <span className="text-xs text-text-muted">Changes saved automatically</span>
      </div>
    </main>
  );
}
