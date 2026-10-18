import { useState, useEffect, useCallback, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";
import { UnifiedAppsHost } from "./UnifiedAppsHost";
import { OperatorIncidentProbes } from "@/chrome/OperatorIncidentProbes";
import { OperatorStatusStrip } from "@/chrome/OperatorStatusStrip";
import TopBarV2 from "@/chrome/TopBarV2";
import ModeHonestyBar from "@/chrome/ModeHonestyBar";
import { AppNavigation, SystemStatusBar } from "@/chrome/AppNavigation";
import { APPS, appForPath, appPath, homeForWidget } from "@/layout/appCatalog";
import TickerBar from "@/chrome/TickerBar";
import { useWsBridge } from "@/hooks/useWsBridge";
import { useDirectBrokerConnected } from "@/hooks/useBrokerConnected";
import { useDemoFeed } from "@/hooks/useDemoFeed";
import { useTickerFallback } from "@/hooks/useTickerFallback";
import { usePrevClose } from "@/hooks/usePrevClose";
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";
import { useBrokerAccounts } from "@/hooks/useBrokerAccounts";
import { useNotificationFeed } from "@/components/NotificationCentre/useNotificationFeed";
import { NoConnectionOverlay } from "@/components/NoConnectionOverlay";
import { LockScreen } from "@/components/LockScreen";
import CommandPalette from "@/components/CommandPalette/CommandPalette";
import DocsSearch, { type DocSearchResult } from "@/components/DocsSearch/DocsSearch";
import ChangelogViewer from "@/components/Changelog/ChangelogViewer";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import KeyboardShortcutsDialog from "@/components/KeyboardShortcuts/KeyboardShortcutsDialog";
import { appendAISymbolContext } from "@/lib/aiSymbolContext";
import { operatorProbesEnabled } from "@/lib/operatorProbes";
import { useDeskDensityChrome } from "@/hooks/useDeskDensityChrome";
import { usePrimaryBanner } from "@/hooks/usePrimaryBannerKind";
import { useChromeCollapse } from "@/chrome/useChromeCollapse";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { isPublicDemoBuild } from "@/lib/demoSession";
import { PublicPreviewHeader } from "@/chrome/PublicPreviewHeader";
import { loadInstrumentLotRows } from "@/lib/instrumentLots";


/** Landmark names match the sidebar label and each page's H1. */
const ROUTE_TITLES: Record<string, string> = {
  "/home": "Home",
  "/trade": "Trade",
  "/invest": "Invest",
  "/learn": "Learn",
  "/lab": "Strategy Lab",
  "/automate": "Automate",
  "/ai": "AI Centre",
  "/settings": "Settings",
  "/ditto": "Accounts",
  "/admin": "Admin",
};

type NavigationEventDetail = string | { path?: unknown; context?: unknown };
function getNavigationPath(detail: NavigationEventDetail): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.path === "string") {
    return appendAISymbolContext(detail.path, detail.context);
  }
  return null;
}

function getCustomEventDetail(event: Event): unknown {
  return (event as CustomEvent<unknown>).detail;
}

function getToolId(detail: unknown): string | null {
  if (detail && typeof detail === "object" && typeof (detail as { toolId?: unknown }).toolId === "string") {
    return (detail as { toolId: string }).toolId;
  }
  return null;
}

/**
 * AppLayout -- shared chrome for all app routes (/terminal, /invest, /learn).
 * Renders TopBar → incident slot → Mode honesty → TickerStrip → route body.
 * Flow routes (/welcome, /explore, /setup) render outside this layout.
 */
export default function AppLayout() {
  const mode = useModeStore((s) => s.mode);
  const { showTicker: showDeskTicker } = useDeskDensityChrome();
  const tickerMode = useSettingsStore((s) => s.tickerMode);
  const { hideTickerByDefault } = useChromeCollapse();
  const tickerForcedOnNarrow = useDeskChromeStore((s) => s.tickerForcedOnNarrow);
  const showTickerStrip =
    tickerMode !== "off"
    && showDeskTicker
    && (!hideTickerByDefault || tickerForcedOnNarrow);
  const authStatus = useAuthStore((s) => s.status);
  const authenticated = authStatus === "logged-in";
  const brokerConfigEnabled = authenticated && mode !== "explore";
  const nativeBrokerConnected = useDirectBrokerConnected();
  const liveMarketDataEnabled = brokerConfigEnabled && nativeBrokerConnected;

  useWsBridge(liveMarketDataEnabled);
  useDemoFeed();         // Simulated-live market feed in Explore mode (no broker)
  useTickerFallback(liveMarketDataEnabled); // REST fallback belongs to the same authenticated feed.
  usePrevClose(liveMarketDataEnabled);        // Fetch prev close via REST for change% calculation (LTP mode has no close)
  useTradingStoreSync(authenticated); // Mirror only the current authenticated session's account state.
  useBrokerAccounts(brokerConfigEnabled); // Never fetch account metadata while locked, logged out, or exploring.
  useNotificationFeed(); // Feed real connection/mode/order events into the Notification Centre
  const location = useLocation();
  const navigate = useNavigate();

  // Route focus management — move keyboard focus to <main> on every route change.
  // This ensures screen-reader users and keyboard-only users land at the new
  // content boundary rather than remaining wherever focus was before navigation.
  // preventScroll avoids a visual jump when the main area is already in view.
  const mainRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  useEffect(() => {
    if (!isPublicDemoBuild()) void loadInstrumentLotRows();
  }, []);
  // Practice mode drives the persistent amber indicator bar.
  // Mode is now owned exclusively by modeStore — settingsStore no longer has sandboxMode.

  const routeTitle = APPS.find(app => app.id === appForPath(location.pathname))?.name ?? ROUTE_TITLES[location.pathname] ?? "FlintTrade";

  // Global navigation event listener — widgets (e.g. AIAdvisor) dispatch this
  // because they can't use useNavigate() inside workspace panels
  useEffect(() => {
    const handler = (e: Event) => {
      const path = getNavigationPath(
        (e as CustomEvent<NavigationEventDetail>).detail,
      );
      if (path) navigate(path);
    };
    window.addEventListener("flinttrade:navigate", handler);
    return () => window.removeEventListener("flinttrade:navigate", handler);
  }, [navigate]);

  // Idle detection — check every 60 s; reset timer on any user activity
  useEffect(() => {
    const interval = setInterval(() => {
      useAuthStore.getState().checkIdle();
    }, 60_000);

    function onActivity() { useAuthStore.getState().touchActivity(); }
    window.addEventListener("mousemove", onActivity, { passive: true });
    window.addEventListener("keydown", onActivity, { passive: true });

    return () => {
      clearInterval(interval);
      window.removeEventListener("mousemove", onActivity);
      window.removeEventListener("keydown", onActivity);
    };
  }, []);

  // Keyboard shortcuts dialog — opened by `?` key or programmatically.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showDocsSearch, setShowDocsSearch] = useState(false);
  const [docsInitialQuery, setDocsInitialQuery] = useState("");
  const [showChangelog, setShowChangelog] = useState(false);
  const handleShowShortcuts = useCallback(() => setShowShortcuts(true), []);
  const handleCloseShortcuts = useCallback(() => setShowShortcuts(false), []);
  const handleCloseDocsSearch = useCallback(() => setShowDocsSearch(false), []);
  const handleCloseChangelog = useCallback(() => setShowChangelog(false), []);

  // Command palette — owned by shared chrome so search works on every app route.
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);
  const handleOpenCommandPalette = useCallback(() => setCmdPaletteOpen(true), []);
  const handleToggleCommandPalette = useCallback(() => {
    setCmdPaletteOpen((open) => !open);
  }, []);
  const handleCloseCommandPalette = useCallback(() => setCmdPaletteOpen(false), []);

  useEffect(() => {
    window.addEventListener("flinttrade:open-command-palette", handleOpenCommandPalette);
    return () => {
      window.removeEventListener("flinttrade:open-command-palette", handleOpenCommandPalette);
    };
  }, [handleOpenCommandPalette]);

  useEffect(() => {
    function onWidget(event: Event) {
      const detail = getCustomEventDetail(event) as { widgetId?: string; props?: Record<string, unknown> } | undefined;
      const current = appForPath(location.pathname);
      const target = detail?.widgetId ? homeForWidget(detail.widgetId, current) : undefined;
      if (!target) return;
      if (target === current) window.dispatchEvent(new CustomEvent("flinttrade:app-widget", { detail }));
      else navigate(appPath(target), { state: { openWidget: detail } });
    }
    function onTool(event: Event) {
      const id = getToolId(getCustomEventDetail(event));
      if (id === "settings") navigate("/settings");
      if (id === "trade-journal") navigate("/reports");
    }
    function onDocs() { setDocsInitialQuery(""); setShowDocsSearch(true); }
    function onChangelog() { setShowChangelog(true); }
    function onDoc(event: Event) {
      const detail = getCustomEventDetail(event) as { path?: string; anchor?: string } | undefined;
      if (detail?.path) navigate("/learn", { state: { selectedDocPath: detail.path, docAnchor: detail.anchor } });
    }
    async function onFullscreen() {
      try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); } catch { /* Browser refusal is not an application mutation. */ }
    }
    const handlers: Record<string, EventListener> = {
      "flinttrade:addWidget": onWidget, "flinttrade:open-tool": onTool,
      "flinttrade:search-docs": onDocs, "flinttrade:show-changelog": onChangelog,
      "flinttrade:openDoc": onDoc, "flinttrade:toggle-fullscreen": onFullscreen,
    };
    Object.entries(handlers).forEach(([name, handler]) => window.addEventListener(name, handler));
    return () => Object.entries(handlers).forEach(([name, handler]) => window.removeEventListener(name, handler));
  }, [location.pathname, navigate]);

  const handleSelectDoc = useCallback(
    (result: DocSearchResult) => {
      navigate("/learn", { state: { selectedDoc: result } });
    },
    [navigate],
  );

  // Global keyboard shortcuts listener — the SINGLE useGlobalKeys mount for
  // the whole app (destructive trading hotkeys must never register twice).
  // Escape is forwarded on the event bus so route-local overlays (e.g. the
  // /trade tool/picker overlays in TerminalRoute) can close themselves
  // without mounting the hook a second time.
  // Alt+T opens Terminal. Alt+H is the same destination, kept as a hidden alias.
  // Wired here only — do not add a second mount.
  const handleGoTerminal = useCallback(() => {
    navigate("/terminal");
  }, [navigate]);

  useGlobalKeys({
    onEscape: useCallback(() => {
      window.dispatchEvent(new CustomEvent("flinttrade:escape"));
    }, []),
    onCommandPalette: handleToggleCommandPalette,
    tradingHotkeysEnabled: appForPath(location.pathname) === "terminal",
    onShowShortcuts: handleShowShortcuts,
    onGoHome: handleGoTerminal,
    onGoTrade: handleGoTerminal,
  });

  const { kind: primaryBannerKind, incident: operatorIncident } = usePrimaryBanner();

  // The locked session leaves the desk. Panels and their data are not kept
  // rendered behind the lock.
  if (authStatus === "pin-required") {
    return <LockScreen />;
  }

  return (
    <div className="relative h-screen flex flex-col bg-surface-base overflow-hidden">
      {/* Skip link — visible on focus with AA-compliant contrast (Issue #61).
          bg-accent is a high-saturation colour; text-white guarantees 4.5:1+. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-100 focus:top-2 focus:left-2 focus:bg-accent focus:text-white focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to main content
      </a>
      {operatorProbesEnabled() ? <OperatorIncidentProbes /> : null}
      <header className="relative z-20 flex flex-col shrink-0">
        {isPublicDemoBuild() ? <PublicPreviewHeader /> : <TopBarV2 />}
        <AppNavigation />
        {primaryBannerKind ? (
          <OperatorStatusStrip kind={primaryBannerKind} incident={operatorIncident} />
        ) : null}
        {!isPublicDemoBuild() && <ModeHonestyBar mode={mode} />}
        {showTickerStrip && <TickerBar mode={tickerMode} />}
      </header>
      {/* Content area: DockSidebar + main panel side by side */}
      {/* Issue #54: aria-label on main landmark mirrors the route title. Each
          route renders its own single H1 (PageHeader, or Trade's sr-only H1). */}
      <div className="relative z-10 flex min-h-0 flex-1 overflow-hidden">

        <main
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
          aria-label={routeTitle}
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden outline-none"
        >
          <div
            data-testid="route-body"
            className="flex min-h-0 flex-1 flex-col overflow-hidden"
          >
            <UnifiedAppsHost />
            <Outlet />
          </div>
        </main>
      </div>
      <SystemStatusBar />
      {!isPublicDemoBuild() && <NoConnectionOverlay suppress={primaryBannerKind === "live_risk"} />}
      <KeyboardShortcutsDialog
        isOpen={showShortcuts}
        onClose={handleCloseShortcuts}
      />
      <DocsSearch
        isOpen={showDocsSearch}
        onClose={handleCloseDocsSearch}
        initialQuery={docsInitialQuery}
        onSelectDoc={handleSelectDoc}
      />
      <ChangelogViewer
        isOpen={showChangelog}
        onClose={handleCloseChangelog}
      />
      <CommandPalette
        isOpen={cmdPaletteOpen}
        onClose={handleCloseCommandPalette}
      />
    </div>
  );
}
