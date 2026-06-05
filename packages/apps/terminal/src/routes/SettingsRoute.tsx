/**
 * SettingsRoute — /settings app route.
 *
 * Accessible from ALL routes via the TOOLS dropdown, gear icon, or Ctrl+,.
 * Shares section components and Zustand stores with QuickAccessPanel.
 *
 * Layout: slim header + left sidebar nav + scrollable content area inside
 * the shared app chrome.
 */

import { useState, useCallback, useEffect, useRef, type JSX } from "react";
import { useNavigate } from "react-router-dom";
import { RouteBanner } from "@/components/help/RouteBanner";
import { CinematicLayout } from "@/components/layout/CinematicLayout";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { LogoIcon } from "@/components/brand/Logo";
import { InlineToast } from "@/tools/Settings/shared";
import { ProfileSection }    from "@/tools/Settings/ProfileSection";
import { GeneralSection }    from "@/tools/Settings/GeneralSection";
import { AppearanceSection } from "@/tools/Settings/AppearanceSection";
import { ConnectionSection } from "@/tools/Settings/ConnectionSection";
import { TradingSection }    from "@/tools/Settings/TradingSection";
import { RiskSection }       from "@/tools/Settings/RiskSection";
import { KeyboardSection }   from "@/tools/Settings/KeyboardSection";
import { LLMSection }        from "@/tools/Settings/LLMSection";
import { TelegramSection }   from "@/tools/Settings/TelegramSection";
import { WhatsAppSection }   from "@/tools/Settings/WhatsAppSection";
import { DataSection }       from "@/tools/Settings/DataSection";
import { AboutSection }      from "@/tools/Settings/AboutSection";
import { LeverageSection }   from "@/tools/Settings/LeverageSection";
import { PracticeSection }   from "@/tools/Settings/PracticeSection";
import { SecuritySection }   from "@/tools/Settings/SecuritySection";
import { MonitoringSection } from "@/tools/Settings/MonitoringSection";
import { SkillSection }      from "@/tools/Settings/SkillSection";
import { PresetSection }     from "@/tools/Settings/PresetSection";
import { TickerSettings }    from "@/routes/settings/TickerSettings";
import { SECTIONS, type SectionId } from "@/tools/Settings/settingsConfig";
import { useSettingsState } from "@/hooks/useSettingsState";

// ---------------------------------------------------------------------------
// Route component
// ---------------------------------------------------------------------------

export default function SettingsRoute() {
  const navigate = useNavigate();

  // Read hash fragment to allow deep-linking: /settings#api
  const sectionFromHash = (): SectionId => {
    const hash = window.location.hash.replace("#", "") as SectionId;
    return SECTIONS.some((s) => s.id === hash) ? hash : "general";
  };

  const [activeSection, setActiveSection] = useState<SectionId>(sectionFromHash);
  const [toastMsg, setToastMsg]           = useState<string | null>(null);
  const dismissToast                      = useCallback(() => setToastMsg(null), []);

  const tablistRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const syncSectionFromHash = () => setActiveSection(sectionFromHash());
    window.addEventListener("hashchange", syncSectionFromHash);
    return () => window.removeEventListener("hashchange", syncSectionFromHash);
  }, []);

  const handleSidebarKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLElement>) => {
      const keys = ["ArrowUp", "ArrowDown", "Home", "End"];
      if (!keys.includes(e.key)) return;
      e.preventDefault();
      const tabs = tablistRef.current?.querySelectorAll<HTMLButtonElement>("[role='tab']");
      if (!tabs || tabs.length === 0) return;
      const idx = Array.from(tabs).indexOf(document.activeElement as HTMLButtonElement);
      let next: number;
      if (e.key === "ArrowDown") next = (idx + 1) % tabs.length;
      else if (e.key === "ArrowUp") next = (idx - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") next = 0;
      else next = tabs.length - 1;
      const nextTab = tabs[next];
      nextTab?.focus();
      const sectionId = SECTIONS[next]?.id;
      if (sectionId) setActiveSection(sectionId);
    },
    [],
  );

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
    whatsapp,
    dataPaths,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateTelegram,
    updateWhatsApp,
    updateDataPaths,
    updateConnection,
    handleRestart,
  } = useSettingsState();

  function renderContent(): JSX.Element {
    switch (activeSection) {
      case "profile":    return <ProfileSection />;
      case "general":    return <GeneralSection    settings={general}    onChange={updateGeneral} />;
      case "appearance": return <AppearanceSection />;
      case "ticker":     return <TickerSettings />;
      case "api":        return <ConnectionSection settings={connection} onChange={updateConnection} />;
      case "trading":    return <TradingSection    settings={trading}    onChange={updateTradingDefaults} />;
      case "risk":       return <RiskSection       settings={risk}       onChange={updateRiskLimits} />;
      case "leverage":   return <LeverageSection />;
      case "practice":   return <PracticeSection />;
      case "keyboard":   return <KeyboardSection />;
      case "llm":        return <LLMSection        settings={llm}        onChange={updateLLM} />;
      case "telegram":   return <TelegramSection   settings={telegram}   onChangeField={updateTelegram} />;
      case "whatsapp":   return <WhatsAppSection   settings={whatsapp}   onChangeField={updateWhatsApp} />;
      case "dataPaths":  return <DataSection       settings={dataPaths}  onChange={updateDataPaths} />;
      case "security":   return <SecuritySection />;
      case "monitoring": return <MonitoringSection />;
      case "skill":      return <SkillSection />;
      case "presets":    return <PresetSection />;
      case "about":      return <AboutSection />;
    }
  }

  return (
    <CinematicLayout mode="focused" className="h-full">
    <section
      aria-label="Settings"
      className="h-full flex flex-col overflow-hidden animate-fade-in"
    >
      {/* Route-level hint banner — dismissible, respects helpPrefs.inlineHints */}
      <RouteBanner
        hintId="settings-broker-gateway-connect"
        text="Go to Broker Gateway to connect FlintTrade's direct broker support or an OpenAlgo-compatible bridge."
      />
      {/* Slim header */}
      <div className="flex items-center gap-3 px-4 h-10 border-b border-glass-chrome bg-glass-chrome backdrop-blur-md shrink-0">
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
      <div className="flex-1 flex min-h-0 flex-col overflow-hidden md:flex-row">
        {/* Sidebar nav */}
        <nav
          ref={tablistRef}
          role="tablist"
          aria-orientation="vertical"
          aria-label="Settings sections"
          className="flex w-full flex-none gap-1 overflow-x-auto border-b border-glass-l1 bg-glass-l1 px-2 py-2 md:w-52 md:flex-col md:gap-0 md:overflow-x-hidden md:overflow-y-auto md:border-b-0 md:border-r md:px-0"
          onKeyDown={handleSidebarKeyDown}
        >
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              role="tab"
              id={`settings-tab-${id}`}
              aria-selected={id === activeSection}
              aria-controls={`settings-tabpanel-${id}`}
              tabIndex={id === activeSection ? 0 : -1}
              onClick={() => setActiveSection(id)}
              className={`flex flex-none items-center gap-2.5 px-3 py-2 font-sans text-sm transition-colors text-left md:w-full ${
                id === activeSection
                  ? "bg-accent/10 text-accent md:border-r-2 md:border-accent"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              <Icon size={13} className="flex-none" />
              <span className="truncate">{label}</span>
            </button>
          ))}
        </nav>

        {/* Content area */}
        <div
          role="tabpanel"
          id={`settings-tabpanel-${activeSection}`}
          aria-labelledby={`settings-tab-${activeSection}`}
          className="min-w-0 flex-1 overflow-y-auto"
        >
          <div className="w-full max-w-3xl px-4 py-5 pb-16 sm:px-6 lg:px-8">
            {renderContent()}
          </div>
        </div>
      </div>

      {/* Footer status bar */}
      <div className="flex-none px-4 py-2 bg-glass-l1 border-t border-glass-l1 flex items-center gap-2">
        <div className="w-1.5 h-1.5 rounded-full bg-profit" />
        <span className="text-xs text-text-muted">Changes saved automatically</span>
      </div>
    </section>
    </CinematicLayout>
  );
}
