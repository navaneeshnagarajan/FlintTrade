import { useState } from "react";
import { Outlet } from "react-router-dom";
import TopBar from "@/chrome/TopBar";
import TickerBar from "@/chrome/TickerBar";
import InteractiveTour from "@/components/tour/InteractiveTour";
import { useWsBridge } from "@/hooks/useWsBridge";
import { useTickerFallback } from "@/hooks/useTickerFallback";
import DailyWelcome from "@/components/welcome/DailyWelcome";

const TOUR_STORAGE_KEY = "flinttrade:tourComplete";

/**
 * AppLayout -- shared chrome for all app routes (/terminal, /invest, /learn).
 * Renders TopBar (with route tabs) + TickerBar + nested route content.
 * Flow routes (/welcome, /explore, /setup) render outside this layout.
 */
export default function AppLayout() {
  useWsBridge();         // WebSocket connection (no-ops if no apiKey)
  useTickerFallback();   // REST polling fallback when WS is disconnected
  const [showWelcome, setShowWelcome] = useState(true);
  const [tourComplete, setTourComplete] = useState(
    () => localStorage.getItem(TOUR_STORAGE_KEY) === "true",
  );

  return (
    <div className="h-screen flex flex-col bg-surface-base overflow-hidden">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-[100] focus:top-2 focus:left-2 focus:bg-primary focus:text-primary-foreground focus:px-4 focus:py-2 focus:rounded-lg focus:text-sm"
      >
        Skip to main content
      </a>
      <header>
        <TopBar />
        <TickerBar />
      </header>
      <main id="main-content" className="flex-1 overflow-hidden">
        <Outlet />
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
    </div>
  );
}
