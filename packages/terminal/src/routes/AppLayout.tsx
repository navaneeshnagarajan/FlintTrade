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
      <TopBar />
      <TickerBar />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
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
