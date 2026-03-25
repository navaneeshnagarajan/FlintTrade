/**
 * SettingsRoute — standalone /settings full-page.
 *
 * Accessible from ALL routes via the TOOLS dropdown, gear icon, or Ctrl+,.
 * Shares section components and Zustand stores with QuickAccessPanel.
 *
 * Layout: slim header + left sidebar nav + scrollable content area.
 */

import { useState, useCallback, useEffect, type JSX } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, RefreshCw } from "lucide-react";
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
import { SecuritySection }   from "@/tools/Settings/SecuritySection";
import { MonitoringSection } from "@/tools/Settings/MonitoringSection";
import { SkillSection }      from "@/tools/Settings/SkillSection";
import { SECTIONS, type SectionId } from "@/tools/Settings/settingsConfig";
import { useSettingsState } from "@/hooks/useSettingsState";

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
  const [toastMsg, setToastMsg]           = useState<string | null>(null);
  const dismissToast                      = useCallback(() => setToastMsg(null), []);

  // Update hash when section changes for deep-link support
  useEffect(() => {
    window.history.replaceState(null, "", `#${activeSection}`);
  }, [activeSection]);

  // All state and actions from Zustand stores
  const {
    general,
    trading,
    risk,
    llm,
    telegram,
    dataPaths,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateTelegram,
    updateDataPaths,
    updateConnection,
    handleRestart,
  } = useSettingsState();

  function renderContent(): JSX.Element {
    switch (activeSection) {
      case "general":    return <GeneralSection    settings={general}    onChange={updateGeneral} />;
      case "appearance": return <AppearanceSection />;
      case "api":        return <ConnectionSection settings={connection} onChange={updateConnection} />;
      case "trading":    return <TradingSection    settings={trading}    onChange={updateTradingDefaults} />;
      case "risk":       return <RiskSection       settings={risk}       onChange={updateRiskLimits} />;
      case "keyboard":   return <KeyboardSection />;
      case "llm":        return <LLMSection        settings={llm}        onChange={updateLLM} />;
      case "telegram":   return <TelegramSection   settings={telegram}   onChangeField={updateTelegram} />;
      case "dataPaths":  return <DataSection       settings={dataPaths}  onChange={updateDataPaths} />;
      case "security":   return <SecuritySection />;
      case "monitoring": return <MonitoringSection />;
      case "skill":      return <SkillSection />;
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
            onClick={() => handleRestart((msg) => setToastMsg(msg))}
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
