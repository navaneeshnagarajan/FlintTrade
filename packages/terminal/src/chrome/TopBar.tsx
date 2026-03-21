import { useState, useEffect, useCallback, useRef, useLayoutEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Wrench, Grid3x3, Plus, LayoutGrid, Copy, Layers, Pencil, Trash2, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { LogoIcon } from "@/components/brand/Logo";
import { useConnectionStore } from "@/stores/connectionStore";
import { useTradingStore } from "@/stores/tradingStore";
import { useLayoutStore } from "@/stores/layoutStore";
import { ping } from "@/services/api";
import { useTimings } from "@/hooks/useMarketStatus";
import type { MarketTiming } from "@/types/api";

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

type MarketStatus = "open" | "pre-market" | "closed" | "weekend";

interface MarketStatusInfo {
  status: MarketStatus;
  label: string;
}

/** Returns market status from NSE timing, falling back to hardcoded 9:15–15:30 IST. */
function getNseStatus(timings: MarketTiming[] | undefined): MarketStatusInfo {
  const now = new Date();
  const istString = now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
  const ist = new Date(istString);
  const day = ist.getDay(); // 0 = Sunday, 6 = Saturday

  if (day === 0 || day === 6) {
    return { status: "weekend", label: "Weekend" };
  }

  const nowMs = now.getTime();

  // Try live timings first (NSE exchange)
  const nseTiming = timings?.find(
    (t) => t.exchange === "NSE" || t.exchange === "NSE_INDEX",
  );

  if (nseTiming) {
    if (nowMs < nseTiming.start_time) {
      return { status: "pre-market", label: "Pre-Market" };
    }
    if (nowMs <= nseTiming.end_time) {
      return { status: "open", label: "Market Open" };
    }
    return { status: "closed", label: "Closed" };
  }

  // Fallback: hardcoded 9:15–15:30 IST
  const hour = ist.getHours();
  const mins = hour * 60 + ist.getMinutes();
  const OPEN_MINS = 9 * 60 + 15; // 555
  const CLOSE_MINS = 15 * 60 + 30; // 930

  if (mins < OPEN_MINS) return { status: "pre-market", label: "Pre-Market" };
  if (mins <= CLOSE_MINS) return { status: "open", label: "Market Open" };
  return { status: "closed", label: "Closed" };
}

function MarketStatusBadge() {
  const { data: timings } = useTimings();
  const [statusInfo, setStatusInfo] = useState<MarketStatusInfo>(() =>
    getNseStatus(timings),
  );

  // Recompute every 30 seconds so the badge flips automatically at open/close
  useEffect(() => {
    const update = () => setStatusInfo(getNseStatus(timings));
    update();
    const id = setInterval(update, 30_000);
    return () => clearInterval(id);
  }, [timings]);

  const dotClass: Record<MarketStatus, string> = {
    open: "bg-profit animate-[pulse-glow_2s_ease-in-out_infinite]",
    "pre-market": "bg-amber-400",
    closed: "bg-loss",
    weekend: "bg-text-muted",
  };

  const textClass: Record<MarketStatus, string> = {
    open: "text-profit",
    "pre-market": "text-amber-400",
    closed: "text-text-muted",
    weekend: "text-text-muted",
  };

  return (
    <div
      className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-hover"
      aria-label={`Market status: ${statusInfo.label}`}
    >
      <div
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotClass[statusInfo.status]}`}
        aria-hidden="true"
      />
      <span className={`text-xs font-medium tabular-nums ${textClass[statusInfo.status]}`}>
        {statusInfo.label}
      </span>
    </div>
  );
}

const ROUTE_TABS = [
  { path: "/learn", label: "Learn" },
  { path: "/invest", label: "Invest" },
  { path: "/trade", label: "Trade" },
  { path: "/lab", label: "Lab" },
  { path: "/automate", label: "Automate" },
  { path: "/ai", label: "AI" },
] as const;

/**
 * TopBar -- always-visible chrome bar at h-10.
 * Renders route tabs (Learn/Invest/Trade) on all app routes.
 * Workspace tabs (Dockview layout management) only appear on /terminal.
 * TOOLS and WIDGETS buttons are visible on all app routes.
 */
export default function TopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentPath = location.pathname;
  const isTerminal = currentPath === "/trade";

  const status = useConnectionStore((s) => s.status);
  const setStatus = useConnectionStore((s) => s.setStatus);
  const [broker, setBroker] = useState("");

  const totalPnl = useTradingStore((s) => s.totalPnl);
  const positionCount = useTradingStore((s) => s.positionCount);

  const tabs = useLayoutStore((s) => s.tabs);
  const activeTabId = useLayoutStore((s) => s.activeTabId);
  const setActiveTab = useLayoutStore((s) => s.setActiveTab);
  const addTab = useLayoutStore((s) => s.addTab);
  const removeTab = useLayoutStore((s) => s.removeTab);
  const renameTab = useLayoutStore((s) => s.renameTab);
  const saveTabLayout = useLayoutStore((s) => s.saveTabLayout);
  const getTabLayout = useLayoutStore((s) => s.getTabLayout);
  const setWidgetPickerOpen = useLayoutStore((s) => s.setWidgetPickerOpen);
  const setToolsMenuOpen = useLayoutStore((s) => s.setToolsMenuOpen);
  const toolsMenuOpen = useLayoutStore((s) => s.toolsMenuOpen);
  const setPresetPickerOpen = useLayoutStore((s) => s.setPresetPickerOpen);

  const [contextMenu, setContextMenu] = useState<{ tabId: string; x: number; y: number } | null>(null);
  /** Id of the workspace tab currently being renamed inline. */
  const [renamingTabId, setRenamingTabId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  /** Id of the workspace tab awaiting inline delete confirmation. */
  const [deletingTabId, setDeletingTabId] = useState<string | null>(null);

  const connected = status === "connected";

  const handleNewBlank = useCallback(() => {
    addTab();
  }, [addTab]);

  const handleCloneCurrent = useCallback(() => {
    const currentTab = tabs.find((t) => t.id === activeTabId);
    if (!currentTab) return;
    const layout = getTabLayout(activeTabId);
    addTab(`${currentTab.name} (Copy)`);
    // After addTab, the new tab becomes active. Save the cloned layout to it.
    const newTabs = useLayoutStore.getState().tabs;
    const newTab = newTabs[newTabs.length - 1];
    if (newTab && layout) {
      saveTabLayout(newTab.id, layout);
    }
  }, [tabs, activeTabId, addTab, getTabLayout, saveTabLayout]);

  const handleTabContextMenu = useCallback(
    (e: React.MouseEvent, tabId: string) => {
      e.preventDefault();
      setContextMenu({ tabId, x: e.clientX, y: e.clientY });
    },
    [],
  );

  const handleRenameTab = useCallback(
    (tabId: string) => {
      const tab = tabs.find((t) => t.id === tabId);
      if (!tab) return;
      setRenamingTabId(tabId);
      setRenameValue(tab.name);
      setContextMenu(null);
    },
    [tabs],
  );

  const commitRename = useCallback(() => {
    if (renamingTabId && renameValue.trim()) {
      renameTab(renamingTabId, renameValue.trim());
    }
    setRenamingTabId(null);
    setRenameValue("");
  }, [renamingTabId, renameValue, renameTab]);

  const cancelRename = useCallback(() => {
    setRenamingTabId(null);
    setRenameValue("");
  }, []);

  const handleDeleteTab = useCallback(
    (tabId: string) => {
      if (tabs.length <= 1) {
        setContextMenu(null);
        return;
      }
      setDeletingTabId(tabId);
      setContextMenu(null);
    },
    [tabs],
  );

  const confirmDelete = useCallback(() => {
    if (deletingTabId) {
      removeTab(deletingTabId);
    }
    setDeletingTabId(null);
  }, [deletingTabId, removeTab]);

  const cancelDelete = useCallback(() => {
    setDeletingTabId(null);
  }, []);

  // Auto-focus the rename input when it appears.
  useLayoutEffect(() => {
    if (renamingTabId && renameInputRef.current) {
      renameInputRef.current.focus();
      renameInputRef.current.select();
    }
  }, [renamingTabId]);

  // Close context menu on click outside
  useEffect(() => {
    if (!contextMenu) return;
    const handler = () => setContextMenu(null);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [contextMenu]);

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
    <div className="h-10 bg-surface-card border-b border-border-default flex items-center justify-between px-3 select-none shrink-0 animate-fade-in">
      {/* Left: Logo + Route Tabs + Separator + Workspace Tabs */}
      <div className="flex items-center gap-3">
        <LogoIcon size={20} />

        {/* Route tabs (always visible) */}
        <nav aria-label="Main navigation" className="flex items-center gap-0.5 ml-3">
          {ROUTE_TABS.map((tab) => (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              aria-current={currentPath === tab.path ? "page" : undefined}
              className={`px-3 py-1 text-xs font-heading font-medium rounded transition-colors ${
                currentPath === tab.path
                  ? "bg-accent/15 text-accent border-b-2 border-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* Separator + Workspace tabs (only on /terminal) */}
        {isTerminal && (
          <>
            <div className="w-px h-4 bg-border-default mx-2" />

            <div className="flex items-center gap-1">
              {tabs.map((tab) => (
                <div key={tab.id} className="relative flex items-center">
                  {renamingTabId === tab.id ? (
                    /* Inline rename input */
                    <div className="flex items-center gap-1 px-1">
                      <Input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitRename();
                          if (e.key === "Escape") cancelRename();
                        }}
                        onBlur={commitRename}
                        className="h-6 w-28 px-1.5 text-xs bg-surface-base border-border-default text-text-primary font-heading"
                        aria-label="Rename workspace"
                      />
                      <button
                        onMouseDown={(e) => { e.preventDefault(); commitRename(); }}
                        className="p-0.5 rounded text-profit hover:bg-surface-hover transition-colors"
                        aria-label="Confirm rename"
                      >
                        <Check size={12} />
                      </button>
                      <button
                        onMouseDown={(e) => { e.preventDefault(); cancelRename(); }}
                        className="p-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
                        aria-label="Cancel rename"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ) : deletingTabId === tab.id ? (
                    /* Inline delete confirmation */
                    <div className="flex items-center gap-1 px-2 py-0.5 rounded bg-surface-hover border border-loss/40 text-xs">
                      <span className="text-text-secondary">Delete?</span>
                      <button
                        onClick={confirmDelete}
                        className="px-1.5 py-0.5 rounded text-loss hover:bg-loss/10 transition-colors font-medium"
                        aria-label="Confirm delete"
                      >
                        Yes
                      </button>
                      <button
                        onClick={cancelDelete}
                        className="px-1.5 py-0.5 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
                        aria-label="Cancel delete"
                      >
                        No
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => setActiveTab(tab.id)}
                      onContextMenu={(e) => handleTabContextMenu(e, tab.id)}
                      className={`px-3 py-1 text-xs font-heading rounded transition-colors ${
                        tab.id === activeTabId
                          ? "bg-surface-hover text-text-primary"
                          : "text-text-secondary hover:text-text-primary hover:bg-surface-hover"
                      }`}
                    >
                      {tab.name}
                    </button>
                  )}
                </div>
              ))}

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    title="New workspace"
                    aria-label="New workspace"
                    className="px-2 py-1 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
                  >
                    <Plus size={14} aria-hidden="true" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-48">
                  <DropdownMenuItem onClick={handleNewBlank}>
                    <LayoutGrid size={14} className="mr-2" />
                    New Blank Workspace
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={handleCloneCurrent}>
                    <Copy size={14} className="mr-2" />
                    Clone Current
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem onClick={() => setPresetPickerOpen(true)}>
                    <Layers size={14} className="mr-2" />
                    New from Template...
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {/* Right-click context menu for workspace tabs */}
            {contextMenu && (
              <div
                className="fixed z-50 min-w-32 bg-popover border border-border rounded-md p-1 shadow-md"
                style={{ top: contextMenu.y, left: contextMenu.x }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  onClick={() => handleRenameTab(contextMenu.tabId)}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-popover-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
                >
                  <Pencil size={14} />
                  Rename
                </button>
                <button
                  onClick={() => handleDeleteTab(contextMenu.tabId)}
                  disabled={tabs.length <= 1}
                  className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50 disabled:pointer-events-none"
                >
                  <Trash2 size={14} />
                  Delete
                </button>
              </div>
            )}
          </>
        )}
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

      {/* Right: TOOLS (all routes) + WIDGETS (/trade only) + Connection status + Clock */}
      <div className="flex items-center gap-3">
        {/* TOOLS: always visible — shows route-relevant tools via ToolsDropdown */}
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setToolsMenuOpen(!toolsMenuOpen)}
          className="h-7 px-2 text-xs text-text-secondary hover:text-text-primary"
        >
          <Wrench size={14} className="mr-1" />
          TOOLS
        </Button>

        {/* WIDGETS: only on /trade (Dockview canvas) */}
        {isTerminal && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setWidgetPickerOpen(true)}
            className="h-7 px-2 text-xs text-text-secondary hover:text-text-primary"
          >
            <Grid3x3 size={14} className="mr-1" />
            WIDGETS
          </Button>
        )}

        <div
          className="flex items-center gap-1.5"
          role="status"
          aria-live="polite"
          aria-label={`OpenAlgo: ${connected && broker ? broker : connected ? "Connected" : "Disconnected"}`}
        >
          <div
            className={`w-2 h-2 rounded-full transition-colors ${
              connected ? "bg-profit ring-2 ring-profit/20 animate-[pulse-glow_2s_ease-in-out_infinite]" : "bg-loss"
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

        <MarketStatusBadge />
        <ISTClock />
      </div>
    </div>
  );
}
