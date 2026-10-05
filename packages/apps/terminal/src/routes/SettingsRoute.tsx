/**
 * SettingsRoute — /settings app route.
 *
 * Accessible from all routes via the sidebar, avatar, or Tools menu.
 * Ctrl+, opens Quick Settings in the shared chrome.
 * Shares section components and Zustand stores with QuickAccessPanel.
 *
 * Layout: shared PageHeader + grouped section nav + scrollable content area
 * inside the shared app chrome.
 */

import { useState, useCallback, useEffect, useMemo, type JSX } from "react";
import { useNavigate } from "react-router";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { CinematicLayout } from "@/components/layout/CinematicLayout";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/layout/Page";
import { SectionNav } from "@/components/layout/SectionNav";
import { InlineToast } from "@/tools/Settings/shared";
import { ProfileSection }    from "@/tools/Settings/ProfileSection";
import { GeneralSection }    from "@/tools/Settings/GeneralSection";
import { AppearanceSection } from "@/tools/Settings/AppearanceSection";
import { ConnectionSection } from "@/tools/Settings/ConnectionSection";
import { BrokerConnect }     from "@/components/account/BrokerConnect";
import { TradingSection }    from "@/tools/Settings/TradingSection";
import { RiskSection }       from "@/tools/Settings/RiskSection";
import { KeyboardSection }   from "@/tools/Settings/KeyboardSection";
import { LLMSection }        from "@/tools/Settings/LLMSection";
import { TelegramSection }   from "@/tools/Settings/TelegramSection";
import { DataSection }       from "@/tools/Settings/DataSection";
import { AboutSection }      from "@/tools/Settings/AboutSection";
import { LeverageSection }   from "@/tools/Settings/LeverageSection";
import { PracticeSection }   from "@/tools/Settings/PracticeSection";
import { SecuritySection }   from "@/tools/Settings/SecuritySection";
import { MonitoringSection } from "@/tools/Settings/MonitoringSection";
import { SkillSection }      from "@/tools/Settings/SkillSection";
import { UpdatesSection }    from "@/tools/Settings/UpdatesSection";
import { SupportSection }    from "@/tools/Settings/SupportSection";
import { TickerSettings }    from "@/routes/settings/TickerSettings";
import { SECTIONS, SECTION_GROUPS, DEMO_HIDDEN_SECTIONS, type SectionId } from "@/tools/Settings/settingsConfig";
import { isPublicDemoBuild } from "@/lib/demoSession";
import { useSettingsState } from "@/hooks/useSettingsState";
import { PracticeLaterSetup } from "@/routes/SetupAccountRoute";


// ---------------------------------------------------------------------------
// Route component
// ---------------------------------------------------------------------------

export default function SettingsRoute() {
  const navigate = useNavigate();
  const mode = useModeStore((state) => state.mode);
  const hasConnectedAccount = useBrokerStore((state) =>
    state.accounts.some((account) => account.status === "connected"),
  );
  const hasConnectedBridge = useConnectionStore((state) =>
    state.openAlgoHydrated && Boolean(state.apiKey.trim()) && state.status === "connected",
  );
  // Visibility only; execution keeps its existing independent readiness gates.
  const showLeverage = mode !== "explore" && (hasConnectedAccount || hasConnectedBridge);
  const [requestedSection, setRequestedSection] = useState(() => window.location.hash.slice(1));
  const [advancedOpen, setAdvancedOpen] = useState(requestedSection === "api");
  const canonicalSection = requestedSection === "api" ? "brokers" : requestedSection;
  const activeSection: SectionId = canonicalSection === "leverage" && !showLeverage
    ? (SECTIONS.some((section) => section.id === "brokers") ? "brokers" : "general")
    : SECTIONS.some((section) => section.id === canonicalSection)
      ? canonicalSection as SectionId
      : "general";
  const [llmWasOpened, setLlmWasOpened] = useState(activeSection === "llm");
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const [llmProviderDraftPending, setLlmProviderDraftPending] = useState(false);
  const dismissToast = useCallback(() => setToastMsg(null), []);

  useEffect(() => {
    const syncSectionFromHash = () => {
      const hash = window.location.hash.slice(1);
      setRequestedSection(hash);
      if (hash === "api") setAdvancedOpen(true);
    };
    window.addEventListener("hashchange", syncSectionFromHash);
    return () => window.removeEventListener("hashchange", syncSectionFromHash);
  }, []);

  useEffect(() => {
    if (requestedSection === "presets") {
      useLayoutStore.getState().setPresetPickerOpen(true);
      navigate("/trade", { replace: true });
    }
  }, [navigate, requestedSection]);

  const selectSection = (section: SectionId) => {
    // Write even when the fallback tab is already selected, cancelling pending
    // deep links while asynchronous broker discovery is still in flight.
    window.history.replaceState(null, "", `#${section}`);
    setRequestedSection(section);
  };

  useEffect(() => {
    if (activeSection === "llm") setLlmWasOpened(true);
  }, [activeSection]);

  // All state and actions from Zustand stores
  const {
    general,
    trading,
    risk,
    llm,
    llmSetupPending,
    llmSaveState,
    llmHydrationState,
    llmCredentialConfigured,
    llmCredentialLast4,
    telegram,
    dataPaths,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateLLMProvider,
    removeLLMCredential,
    updateTelegram,
    updateDataPaths,
    acceptConnection,
    handleRestart,
    retryLlmHydration,
  } = useSettingsState();

  function renderLlmContent(): JSX.Element {
    return (
      <LLMSection
        settings={llm}
        onChange={updateLLM}
        onProviderChange={updateLLMProvider}
        hydrationState={llmHydrationState}
        credentialConfigured={llmCredentialConfigured}
        credentialLast4={llmCredentialLast4}
        onCredentialRemove={removeLLMCredential}
        providerActivationRequired={llmSetupPending}
        onDraftStateChange={setLlmProviderDraftPending}
        onRetry={retryLlmHydration}
      />
    );
  }

  function renderContent(): JSX.Element {
    // Hiding these from the nav is not enough on its own: activeSection can be
    // restored from a deep link or persisted state, so the render path has to
    // refuse them too.
    if (isPublicDemoBuild() && DEMO_HIDDEN_SECTIONS.includes(activeSection)) {
      return (
        <div className="p-6 text-sm text-muted-foreground">
          This section is unavailable in the hosted demo because it collects real
          credentials. Install FlintTrade to connect a broker — your keys then stay
          on your own machine and are never typed into a public website.
        </div>
      );
    }
    switch (activeSection) {
      case "profile":    return <ProfileSection />;
      case "general":    return <GeneralSection    settings={general}    onChange={updateGeneral} />;
      case "appearance": return <AppearanceSection />;
      case "ticker":     return <TickerSettings />;
      case "api":
      case "brokers":    return (
        <div className="space-y-6">
          <BrokerConnect pollAccounts={false} />
          <details open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
            <summary className="cursor-pointer text-sm font-medium text-text-secondary">Advanced · OpenAlgo bridge</summary>
            <div className="pt-4">
              <ConnectionSection settings={connection} onSaved={acceptConnection} />
            </div>
          </details>
        </div>
      );
      case "trading":    return <TradingSection    settings={trading}    onChange={updateTradingDefaults} />;
      case "risk":       return <RiskSection       settings={risk}       onChange={updateRiskLimits} />;
      case "leverage":   return <LeverageSection />;
      case "practice":   return <PracticeSection />;
      case "keyboard":   return <KeyboardSection />;
      case "llm":        return <></>;
      case "telegram":   return <TelegramSection   settings={telegram}   onChangeField={updateTelegram} />;
      case "dataPaths":  return <DataSection       settings={dataPaths}  onChange={updateDataPaths} />;
      case "security":   return <SecuritySection />;
      case "monitoring": return <MonitoringSection />;
      case "skill":      return <SkillSection />;
      case "presets":    return <></>;
      case "updates":    return <UpdatesSection />;
      case "support":    return <SupportSection />;
      case "about":      return <AboutSection />;
    }
  }

  const saveStatus = llmHydrationState === "loading"
    ? { copy: "Loading LLM settings", dot: "bg-accent animate-pulse" }
    : llmHydrationState === "error"
      ? { copy: "LLM settings unavailable", dot: "bg-loss" }
      : llmHydrationState === "empty"
        ? { copy: "LLM is not configured", dot: "bg-warning" }
        : (llmProviderDraftPending || llmSetupPending)
          ? { copy: "LLM provider changes not applied", dot: "bg-warning" }
          : llmSaveState === "pending"
            ? { copy: "LLM changes pending", dot: "bg-warning" }
            : llmSaveState === "saving"
              ? { copy: "Saving LLM changes", dot: "bg-accent animate-pulse" }
              : llmSaveState === "error"
                ? { copy: "LLM changes not saved", dot: "bg-loss" }
                : { copy: "No pending LLM changes", dot: "bg-profit" };

  const navGroups = useMemo(
    () =>
      SECTION_GROUPS.map((group) => ({
        id: group.id,
        label: group.label,
        items: SECTIONS.filter((section) => section.group === group.id && (section.id !== "leverage" || showLeverage)).map(({ id, label, icon }) => ({
          id,
          label,
          icon,
        })),
      })).filter((group) => group.items.length > 0),
    [showLeverage],
  );

  return (
    <CinematicLayout mode="focused" className="h-full">
    <section
      aria-label="Settings"
      className="h-full flex flex-col overflow-hidden"
    >
      <PageHeader
        title="Settings"
        description="Your account, preferences, brokers, risk limits, AI and system options."
        actions={
          <>
            {toastMsg && <InlineToast message={toastMsg} onDismiss={dismissToast} />}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleRestart((msg) => setToastMsg(msg))}
              disabled={restarting}
            >
              <RefreshCw className={restarting ? "animate-spin" : ""} aria-hidden="true" />
              {restarting ? "Restarting..." : "Restart Services"}
            </Button>
          </>
        }
      />

      {/* Body: grouped section nav + content */}
      <div className="flex-1 flex min-h-0 flex-col overflow-hidden md:flex-row">
        <SectionNav<SectionId>
          groups={navGroups}
          value={activeSection}
          onChange={selectSection}
          label="Settings sections"
          idPrefix="settings"
        />

        {/* Content area */}
        <div
          role="tabpanel"
          id={`settings-tabpanel-${activeSection}`}
          aria-labelledby={`settings-tab-${activeSection}`}
          className="min-w-0 flex-1 overflow-y-auto"
        >
          <div className="w-full max-w-3xl px-[var(--ft-page-gutter)] pb-16 pt-6">
            <PracticeLaterSetup surface="settings" />
            {activeSection !== "llm" && renderContent()}
            {(llmWasOpened || activeSection === "llm") && (
              <div hidden={activeSection !== "llm"}>
                {renderLlmContent()}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Model persistence belongs only to its settings page. */}
      {activeSection === "llm" && <div
        className="flex-none px-4 py-2 bg-glass-l1 border-t border-glass-l1 flex items-center gap-2"
        role="status"
        aria-label="Settings save status"
        aria-live="polite"
        aria-atomic="true"
      >
        <div className={`size-1.5 rounded-full ${saveStatus.dot}`} />
        <span className="text-xs text-text-muted">{saveStatus.copy}</span>
      </div>}
    </section>
    </CinematicLayout>
  );
}
