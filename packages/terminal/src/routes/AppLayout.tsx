import { Outlet } from "react-router-dom";
import TopBar from "@/chrome/TopBar";
import TickerBar from "@/chrome/TickerBar";
import { useWsBridge } from "@/hooks/useWsBridge";

/**
 * AppLayout -- shared chrome for all app routes (/terminal, /invest, /learn).
 * Renders TopBar (with route tabs) + TickerBar + nested route content.
 * Flow routes (/welcome, /explore, /setup) render outside this layout.
 */
export default function AppLayout() {
  useWsBridge(); // WebSocket connection (no-ops if no apiKey)
  return (
    <div className="h-screen flex flex-col bg-surface-base overflow-hidden">
      <TopBar />
      <TickerBar />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}
