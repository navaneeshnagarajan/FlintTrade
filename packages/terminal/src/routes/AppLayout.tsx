import { useState, useEffect, useCallback } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import TopBarV2 from "@/chrome/TopBarV2";
import DockSidebar from "@/chrome/DockSidebar";
import PageTransition from "@/components/motion/PageTransition";
import TickerBar from "@/chrome/TickerBar";
import { useWsBridge } from "@/hooks/useWsBridge";
import { useTickerFallback } from "@/hooks/useTickerFallback";
import { usePrevClose } from "@/hooks/usePrevClose";
import DailyWelcome from "@/components/welcome/DailyWelcome";
import InteractiveTour from "@/components/tour/InteractiveTour";
import { NoConnectionOverlay } from "@/components/NoConnectionOverlay";
import { LockScreen } from "@/components/LockScreen";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import KeyboardShortcutsDialog from "@/components/KeyboardShortcuts/KeyboardShortcutsDialog";
import { Button } from "@/components/ui/button";

const TOUR_COMPLETE_KEY = "flinttrade:tourComplete";

const SMALL_SCREEN_DISMISSED_KEY = "flinttrade:smallScreenDismissed";
const SMALL_SCREEN_BREAKPOINT = 768;

const ROUTE_TITLES: Record<string, string> = {
  "/home": "Home",
  "/trade": "Trading Workspace",
  "/invest": "Investment Dashboard",
  "/learn": "Learning Centre",
  "/lab": "Strategy Lab",
  "/automate": "Automation Hub",
  "/ai": "AI Centre",
  "/settings": "Settings",
  "/ditto": "Multi-Account Manager",
  "/admin": "Admin Panel",
};

function SmallScreenOverlay({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="small-screen-title"
      className="fixed inset-0 z-200 flex flex-col items-center justify-center bg-surface-base px-6 text-center"
    >
      <div className="flex flex-col items-center gap-5 max-w-xs">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" aria-hidden="true">
          <rect width="40" height="40" rx="8" fill="var(--color-accent, #6366f1)" fillOpacity="0.15" />
          <path d="M12 20h16M20 12l8 8-8 8" stroke="var(--color-accent, #6366f1)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="space-y-2">
          <h1 id="small-screen-title" className="font-heading font-bold text-lg text-text-primary">
            FlintTrade is designed for desktop
          </h1>
          <p className="text-sm text-text-secondary leading-relaxed">
            For the best experience, use a screen wider than 768px. The workspace, charts, and data grids require more horizontal space.
          </p>
        </div>
        <Button
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          variant="outline"
          onClick={onDismiss}
          className="mt-2 border-accent/30 text-accent hover:bg-accent/20 hover:text-accent"
        >
          Continue anyway
        </Button>
      </div>
    </div>
  );
}

/**
 * AppLayout -- shared chrome for all app routes (/terminal, /invest, /learn).
 * Renders TopBar (with route tabs) + TickerBar + DockSidebar + nested route content.
 * Flow routes (/welcome, /explore, /setup) render outside this layout.
 */
export default function AppLayout() {
  useWsBridge();         // WebSocket connection (no-ops if no apiKey)
  useTickerFallback();   // REST polling fallback when WS is disconnected
  usePrevClose();        // Fetch prev close via REST for change% calculation (LTP mode has no close)
  const location = useLocation();
  const navigate = useNavigate();
  // Practice mode drives the persistent amber indicator bar.
  // Mode is now owned exclusively by modeStore — settingsStore no longer has sandboxMode.
  const mode = useModeStore((s) => s.mode);
  const authStatus = useAuthStore((s) => s.status);

  const routeTitle = ROUTE_TITLES[location.pathname] ?? "FlintTrade";

  // Global navigation event listener — widgets (e.g. AIAdvisor) dispatch this
  // because they can't use useNavigate() inside Dockview panels
  useEffect(() => {
    const handler = (e: Event) => {
      const path = (e as CustomEvent<string>).detail;
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

  const [showWelcome, setShowWelcome] = useState(() => {
    return sessionStorage.getItem("flinttrade:dailyWelcomeDismissed") !== "true";
  });

  const [showSmallScreenWarning, setShowSmallScreenWarning] = useState(() => {
    if (typeof window === "undefined") return false;
    if (sessionStorage.getItem(SMALL_SCREEN_DISMISSED_KEY) === "true") return false;
    return window.innerWidth < SMALL_SCREEN_BREAKPOINT;
  });

  // Show the interactive tour on /trade for first-time users who haven't seen it.
  // The tour itself writes TOUR_COMPLETE_KEY to localStorage on skip or completion.
  const [showTour, setShowTour] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(TOUR_COMPLETE_KEY) !== "true";
  });

  // Gate the tour to the /trade route — it introduces the trading workspace.
  const isTradeRoute = location.pathname === "/trade";
  const tourVisible = showTour && isTradeRoute;

  // Keyboard shortcuts dialog — opened by `?` key or programmatically.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const handleShowShortcuts = useCallback(() => setShowShortcuts(true), []);
  const handleCloseShortcuts = useCallback(() => setShowShortcuts(false), []);

  // Global keyboard shortcuts listener.
  useGlobalKeys({ onShowShortcuts: handleShowShortcuts });

  useEffect(() => {
    function handleResize() {
      if (window.innerWidth >= SMALL_SCREEN_BREAKPOINT) {
        setShowSmallScreenWarning(false);
      }
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  function handleDismissSmallScreen() {
    sessionStorage.setItem(SMALL_SCREEN_DISMISSED_KEY, "true");
    setShowSmallScreenWarning(false);
  }

  const handleDismissWelcome = useCallback(() => {
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    setShowWelcome(false);
  }, []);

  return (
    <div className="h-screen flex flex-col bg-surface-base overflow-hidden">
      {showSmallScreenWarning && (
        <SmallScreenOverlay onDismiss={handleDismissSmallScreen} />
      )}
      {/* Mode indicator — coloured top border per mode (Thinkorswim-inspired) */}
      {mode === "explore" && (
        <div className="h-0.75 bg-text-muted/40 shrink-0" aria-hidden="true" />
      )}
      {mode === "practice" && (
        <div className="h-0.75 bg-amber-500 shrink-0" aria-hidden="true" />
      )}
      {mode === "live" && (
        <div className="h-px bg-profit/60 shrink-0" aria-hidden="true" />
      )}
      {/* Mode disclaimer banners — aria-live so screen readers announce mode changes */}
      <div aria-live="polite" role="status" className="contents">
        {mode === "practice" && (
          <div className="bg-amber-500/10 border-b border-amber-500/20 px-4 py-1 text-center">
            <p className="text-xs text-amber-400">
              PRACTICE MODE — Virtual trading results are simulated and do not represent actual trading outcomes
            </p>
          </div>
        )}
        {mode === "explore" && (
          <div className="bg-text-muted/10 border-b border-text-muted/20 px-4 py-1 text-center">
            <p className="text-xs text-text-muted">
              EXPLORE MODE — All data shown is sample only
            </p>
          </div>
        )}
      </div>
      {/* Skip link — visible on focus with AA-compliant contrast (Issue #61).
          bg-accent is a high-saturation colour; text-white guarantees 4.5:1+. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-100 focus:top-2 focus:left-2 focus:bg-accent focus:text-white focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to main content
      </a>
      <header>
        <TopBarV2 />
        <TickerBar />
      </header>
      {/* Content area: DockSidebar + main panel side by side */}
      {/* Issue #47: visually-hidden H1 for screen readers reflecting the current route */}
      {/* Issue #54: aria-label on main landmark mirrors the route title */}
      <div className="flex flex-1 overflow-hidden">
        <DockSidebar />
        <main id="main-content" aria-label={routeTitle} className="flex-1 overflow-hidden">
          <h1 className="sr-only">{routeTitle}</h1>
          <PageTransition locationKey={location.pathname}>
            <Outlet />
          </PageTransition>
        </main>
      </div>
      {showWelcome && (
        <DailyWelcome onDismiss={handleDismissWelcome} />
      )}
      <NoConnectionOverlay />
      {authStatus === "pin-required" && <LockScreen />}
      {tourVisible && (
        <InteractiveTour onComplete={() => setShowTour(false)} />
      )}
      <KeyboardShortcutsDialog
        isOpen={showShortcuts}
        onClose={handleCloseShortcuts}
      />
    </div>
  );
}
