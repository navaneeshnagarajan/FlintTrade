/**
 * NoConnectionOverlay — global overlay shown after 5s of OpenAlgo disconnection.
 *
 * Avoids flashing on startup by waiting 5 seconds before becoming visible.
 * Clears immediately when connection is restored.
 * Rendered inside AppLayout so it covers all app routes.
 */

import { useState, useEffect } from "react";
import { WifiOff, Settings, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useConnectionStore } from "@/stores/connectionStore";

const DELAY_MS = 5000;

export function NoConnectionOverlay() {
  const status = useConnectionStore((s) => s.status);
  const [showOverlay, setShowOverlay] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (status === "disconnected") {
      const timer = setTimeout(() => setShowOverlay(true), DELAY_MS);
      return () => clearTimeout(timer);
    }
    // Connected — hide immediately
    setShowOverlay(false);
  }, [status]);

  if (!showOverlay) return null;

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="no-connection-title"
      aria-describedby="no-connection-desc"
      className="fixed inset-0 z-50 bg-surface-base/80 backdrop-blur-sm flex items-center justify-center"
    >
      <div className="bg-surface-card border border-border-default rounded-xl p-8 max-w-md w-full mx-4 text-center space-y-4 shadow-2xl">
        <div className="flex justify-center">
          <div className="w-14 h-14 rounded-full bg-loss/10 border border-loss/20 flex items-center justify-center">
            <WifiOff className="w-6 h-6 text-loss" aria-hidden="true" />
          </div>
        </div>

        <div className="space-y-1.5">
          <h2
            id="no-connection-title"
            className="text-lg font-heading font-semibold text-text-primary"
          >
            OpenAlgo Disconnected
          </h2>
          <p
            id="no-connection-desc"
            className="text-sm text-text-secondary leading-relaxed"
          >
            Cannot reach the OpenAlgo server. Check your connection settings or
            start OpenAlgo, then retry.
          </p>
        </div>

        <div className="flex gap-3 justify-center pt-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => { setShowOverlay(false); navigate("/settings#api"); }}
          >
            <Settings className="w-3.5 h-3.5 mr-1.5" />
            Settings
          </Button>
          <Button
            size="sm"
            onClick={() => window.location.reload()}
          >
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" />
            Retry
          </Button>
        </div>

        <button
          type="button"
          onClick={() => setShowOverlay(false)}
          className="text-xs text-text-muted hover:text-text-secondary transition-colors mt-1"
        >
          Dismiss — continue without live data
        </button>
      </div>
    </div>
  );
}
