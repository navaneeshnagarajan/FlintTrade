import { useState, useEffect, useCallback, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import TopBarV2 from "@/chrome/TopBarV2";
import DockSidebar from "@/chrome/DockSidebar";
import PageTransition from "@/components/motion/PageTransition";
import TickerBar from "@/chrome/TickerBar";
import { useWsBridge } from "@/hooks/useWsBridge";
import { useTickerFallback } from "@/hooks/useTickerFallback";
import { usePrevClose } from "@/hooks/usePrevClose";
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";
import DailyWelcome from "@/components/welcome/DailyWelcome";
import { useNotificationFeed } from "@/components/NotificationCentre/useNotificationFeed";
import { NoConnectionOverlay } from "@/components/NoConnectionOverlay";
import { LockScreen } from "@/components/LockScreen";
import CommandPalette from "@/components/CommandPalette/CommandPalette";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import useGlobalKeys from "@/hooks/useGlobalKeys";
import KeyboardShortcutsDialog from "@/components/KeyboardShortcuts/KeyboardShortcutsDialog";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

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
  "/ditto": "Account Manager",
  "/admin": "Admin Panel",
};

type NavigationEventDetail = string | { path?: unknown };

function getNavigationPath(detail: NavigationEventDetail): string | null {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof detail.path === "string") {
    return detail.path;
  }
  return null;
}

function SmallScreenOverlay({ onDismiss }: { onDismiss: () => void }) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="small-screen-title"
      className="fixed inset-0 z-200 flex flex-col items-center justify-center bg-surface-base px-6 text-center"
    >
      <div className="flex flex-col items-center gap-5 max-w-xs">
        <div
          className="grid size-10 place-items-center rounded-lg bg-accent/15 text-accent"
          aria-hidden="true"
        >
          <ArrowRight className="size-5" strokeWidth={2} />
        </div>
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
  useTradingStoreSync(); // Mirror funds/positions REST cache → tradingStore scalars (single write point)
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
  // Practice mode drives the persistent amber indicator bar.
  // Mode is now owned exclusively by modeStore — settingsStore no longer has sandboxMode.
  const mode = useModeStore((s) => s.mode);
  const authStatus = useAuthStore((s) => s.status);

  const routeTitle = ROUTE_TITLES[location.pathname] ?? "FlintTrade";

  // Global navigation event listener — widgets (e.g. AIAdvisor) dispatch this
  // because they can't use useNavigate() inside Dockview panels
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

  const [showWelcome, setShowWelcome] = useState(() => {
    return sessionStorage.getItem("flinttrade:dailyWelcomeDismissed") !== "true";
  });

  const [showSmallScreenWarning, setShowSmallScreenWarning] = useState(() => {
    if (typeof window === "undefined") return false;
    if (sessionStorage.getItem(SMALL_SCREEN_DISMISSED_KEY) === "true") return false;
    return window.innerWidth < SMALL_SCREEN_BREAKPOINT;
  });

  // Keyboard shortcuts dialog — opened by `?` key or programmatically.
  const [showShortcuts, setShowShortcuts] = useState(false);
  const handleShowShortcuts = useCallback(() => setShowShortcuts(true), []);
  const handleCloseShortcuts = useCallback(() => setShowShortcuts(false), []);

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

  // Global keyboard shortcuts listener.
  useGlobalKeys({
    onCommandPalette: handleToggleCommandPalette,
    onShowShortcuts: handleShowShortcuts,
  });

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
    <div className="relative h-screen flex flex-col bg-surface-base overflow-hidden">
      <style>{`
        @keyframes appStarDrift {
          from { transform: translate3d(0, 0, 0); }
          to { transform: translate3d(-42px, 24px, 0); }
        }
        .app-cinematic-stars {
          background-image:
            radial-gradient(circle, rgba(255,255,255,0.22) 0 1px, transparent 1.35px),
            radial-gradient(circle, rgba(34,197,94,0.26) 0 1px, transparent 1.45px);
          background-size: 116px 116px, 168px 168px;
          background-position: 0 0, 58px 72px;
          animation: appStarDrift 28s linear infinite alternate;
        }
        @media (prefers-reduced-motion: reduce) {
          .app-cinematic-stars { animation: none; }
        }
      `}</style>
      <div className="pointer-events-none absolute inset-0 z-0" aria-hidden="true">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_46%,rgba(34,197,94,0.10),transparent_32rem),radial-gradient(circle_at_55%_18%,rgba(56,189,248,0.06),transparent_28rem),linear-gradient(180deg,rgba(0,0,0,0.05),transparent_45%,rgba(0,0,0,0.16))]" />
        <div className="app-cinematic-stars absolute inset-0 opacity-[0.16]" />
      </div>
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
      {/* Mode disclaimer banners — aria-live so screen readers announce mode changes.
          Note: a bare wrapper with className="contents" strips role="status" from the
          AX tree in some browsers, so the live region lives on each banner instead. */}
      {mode === "practice" && (
        <div
          role="status"
          aria-live="polite"
          className="bg-amber-500/10 border-b border-amber-500/20 px-4 py-1 text-center"
        >
          <p className="text-xs text-amber-400">
            PRACTICE MODE — Virtual trading results are simulated and do not represent actual trading outcomes
          </p>
        </div>
      )}
      {mode === "explore" && (
        <div
          role="status"
          aria-live="polite"
          className="bg-text-muted/10 border-b border-text-muted/20 px-4 py-1 text-center"
        >
          <p className="text-xs text-text-muted">
            EXPLORE MODE — All data shown is sample only
          </p>
        </div>
      )}
      {/* Skip link — visible on focus with AA-compliant contrast (Issue #61).
          bg-accent is a high-saturation colour; text-white guarantees 4.5:1+. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-100 focus:top-2 focus:left-2 focus:bg-accent focus:text-white focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm focus:font-medium focus:shadow-lg"
      >
        Skip to main content
      </a>
      <header className="relative z-20">
        <TopBarV2 />
        <TickerBar />
      </header>
      {/* Content area: DockSidebar + main panel side by side */}
      {/* Issue #47: visually-hidden H1 for screen readers reflecting the current route */}
      {/* Issue #54: aria-label on main landmark mirrors the route title */}
      <div className="relative z-10 flex flex-1 overflow-hidden">
        <DockSidebar />
        <main
          id="main-content"
          ref={mainRef}
          tabIndex={-1}
          aria-label={routeTitle}
          className="flex-1 overflow-hidden outline-none"
        >
          <h1 className="sr-only">{routeTitle}</h1>
          <PageTransition locationKey={location.pathname}>
            <Outlet />
          </PageTransition>
        </main>
      </div>
      {showWelcome && mode !== "explore" && (
        <DailyWelcome onDismiss={handleDismissWelcome} />
      )}
      <NoConnectionOverlay />
      {authStatus === "pin-required" && <LockScreen />}
      <KeyboardShortcutsDialog
        isOpen={showShortcuts}
        onClose={handleCloseShortcuts}
      />
      <CommandPalette
        isOpen={cmdPaletteOpen}
        onClose={handleCloseCommandPalette}
      />
    </div>
  );
}
