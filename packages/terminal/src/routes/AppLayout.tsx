import { useState, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import TopBar from "@/chrome/TopBar";
import PageTransition from "@/components/motion/PageTransition";
import TickerBar from "@/chrome/TickerBar";
import InteractiveTour from "@/components/tour/InteractiveTour";
import { useWsBridge } from "@/hooks/useWsBridge";
import { useTickerFallback } from "@/hooks/useTickerFallback";
import DailyWelcome from "@/components/welcome/DailyWelcome";
import { NoConnectionOverlay } from "@/components/NoConnectionOverlay";

const TOUR_STORAGE_KEY = "flinttrade:tourComplete";
const SMALL_SCREEN_DISMISSED_KEY = "flinttrade:smallScreenDismissed";
const SMALL_SCREEN_BREAKPOINT = 768;

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
        <button
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          onClick={onDismiss}
          className="mt-2 px-5 py-2 rounded-lg bg-accent/10 border border-accent/30 text-accent text-sm font-medium hover:bg-accent/20 transition-colors"
        >
          Continue anyway
        </button>
      </div>
    </div>
  );
}

/**
 * AppLayout -- shared chrome for all app routes (/terminal, /invest, /learn).
 * Renders TopBar (with route tabs) + TickerBar + nested route content.
 * Flow routes (/welcome, /explore, /setup) render outside this layout.
 */
export default function AppLayout() {
  useWsBridge();         // WebSocket connection (no-ops if no apiKey)
  useTickerFallback();   // REST polling fallback when WS is disconnected
  const location = useLocation();
  const [showWelcome, setShowWelcome] = useState(true);
  const [tourComplete, setTourComplete] = useState(
    () => localStorage.getItem(TOUR_STORAGE_KEY) === "true",
  );

  const [showSmallScreenWarning, setShowSmallScreenWarning] = useState(() => {
    if (typeof window === "undefined") return false;
    if (sessionStorage.getItem(SMALL_SCREEN_DISMISSED_KEY) === "true") return false;
    return window.innerWidth < SMALL_SCREEN_BREAKPOINT;
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

  return (
    <div className="h-screen flex flex-col bg-surface-base overflow-hidden">
      {showSmallScreenWarning && (
        <SmallScreenOverlay onDismiss={handleDismissSmallScreen} />
      )}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-100 focus:top-2 focus:left-2 focus:bg-primary focus:text-primary-foreground focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm"
      >
        Skip to main content
      </a>
      <header>
        <TopBar />
        <TickerBar />
      </header>
      <main id="main-content" className="flex-1 overflow-hidden">
        <PageTransition locationKey={location.pathname}>
          <Outlet />
        </PageTransition>
      </main>
      {showWelcome && (
        <DailyWelcome onDismiss={() => setShowWelcome(false)} />
      )}
      {!tourComplete && (
        <InteractiveTour
          onComplete={() => {
            localStorage.setItem(TOUR_STORAGE_KEY, "true");
            setTourComplete(true);
          }}
        />
      )}
      <NoConnectionOverlay />
    </div>
  );
}
