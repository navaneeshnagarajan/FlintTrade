import { useState, useEffect } from "react";
import { Wrench, Grid3x3, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LogoIcon } from "@/components/brand/Logo";
import { useConnectionStore } from "@/stores/connectionStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { ping } from "@/services/api";

function ISTClock() {
  const [time, setTime] = useState("");

  useEffect(() => {
    const tick = () =>
      setTime(
        new Date().toLocaleTimeString("en-IN", {
          timeZone: "Asia/Kolkata",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        })
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span className="font-mono text-xs text-text-secondary tabular-nums">
      {time} IST
    </span>
  );
}

interface TopBarProps {
  onWidgetPicker: () => void;
  onToolsMenu: () => void;
}

/**
 * TopBar -- always-visible chrome bar at h-10.
 * Uses Zustand stores for connection, trading, and layout state.
 */
export default function TopBar({ onWidgetPicker, onToolsMenu }: TopBarProps) {
  const status = useConnectionStore((s) => s.status);
  const setStatus = useConnectionStore((s) => s.setStatus);
  const [broker, setBroker] = useState("");

  const totalPnl = useTradingStore((s) => s.totalPnl);
  const positionCount = useTradingStore((s) => s.positionCount);

  const tabs = useLayoutStore((s) => s.tabs);
  const activeTabId = useLayoutStore((s) => s.activeTabId);
  const setActiveTab = useLayoutStore((s) => s.setActiveTab);
  const addTab = useLayoutStore((s) => s.addTab);

  const connected = status === "connected";

  // Ping OpenAlgo every 10s to check connection
  useEffect(() => {
    const check = async () => {
      try {
        const res = await ping();
        setStatus("connected");
        setBroker((res as Record<string, string>)?.broker || "");
      } catch {
        setStatus("disconnected");
        setBroker("");
      }
    };
    check();
    const id = setInterval(check, 10_000);
    return () => clearInterval(id);
  }, [setStatus]);

  const pnlColor = totalPnl >= 0 ? "text-profit" : "text-loss";
  const pnlSign = totalPnl >= 0 ? "+" : "";

  return (
    <div className="h-10 bg-surface-card border-b border-border-default flex items-center justify-between px-3 select-none shrink-0">
      {/* Left: Logo + Layout Tabs */}
      <div className="flex items-center gap-3">
        <LogoIcon size={20} />

        <div className="flex items-center gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-3 py-1 text-xs font-heading rounded transition-colors ${
                tab.id === activeTabId
                  ? "bg-surface-hover text-text-primary"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {tab.name}
            </button>
          ))}

          <button
            onClick={() => addTab()}
            title="New layout"
            className="px-2 py-1 text-xs text-text-muted hover:text-text-primary transition-colors"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      {/* Center: P&L summary (shown when positions exist) */}
      {positionCount > 0 && (
        <div className="flex items-center gap-2">
          <span className={`font-mono text-xs tabular-nums ${pnlColor}`}>
            {pnlSign}{totalPnl.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
          <Badge variant="secondary" className="text-xxs px-1.5 py-0">
            {positionCount} pos
          </Badge>
        </div>
      )}

      {/* Right: TOOLS + WIDGETS + Connection status + Clock */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={onToolsMenu}
          className="h-7 px-2 text-xs text-text-secondary hover:text-text-primary"
        >
          <Wrench size={14} className="mr-1" />
          TOOLS
        </Button>

        <Button
          variant="ghost"
          size="sm"
          onClick={onWidgetPicker}
          className="h-7 px-2 text-xs text-text-secondary hover:text-text-primary"
        >
          <Grid3x3 size={14} className="mr-1" />
          WIDGETS
        </Button>

        <div className="flex items-center gap-1.5">
          <div
            className={`w-2 h-2 rounded-full transition-colors ${
              connected ? "bg-profit ring-2 ring-profit/20" : "bg-loss"
            }`}
          />
          <span className="text-xs text-text-secondary">
            {connected && broker
              ? broker
              : connected
                ? "Connected"
                : "Disconnected"}
          </span>
        </div>

        <ISTClock />
      </div>
    </div>
  );
}
