import { useState, useEffect, useCallback, useRef, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Wrench, Grid3x3, Plus, LayoutGrid, Copy, Layers, Pencil, Trash2, Check, X, Sun, Moon, Monitor, Settings } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { useQuery } from "@tanstack/react-query";
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
import { useThemeStore } from "@/stores/themeStore";
import { ping } from "@/services/api";
import { getPendingOrders } from "@/services/ftApi";
import { useTimings } from "@/hooks/useMarketStatus";
import type { MarketTiming } from "@/types/api";
import { useSkillLevel } from "@/hooks/useSkillLevel";
import AccountSwitcher from "./AccountSwitcher";
import SandboxToggle from "./SandboxToggle";
import QuickAccessPanel from "./QuickAccessPanel";
import ToolsDropdown from "./ToolsDropdown";
import type { ToolId } from "@/types/widgets";

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
    <span
      className="font-mono text-xs text-text-secondary tabular-nums"
      aria-label="Current time in IST"
    >
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
  const resolvedMode = useThemeStore((s) => s.getResolvedMode());

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

  // On light backgrounds, text-profit (#22c55e) fails WCAG AA contrast.
  // Use text-green-700 (#15803d) on light mode — passes 4.5:1 on white.
  const textClass: Record<MarketStatus, string> = {
    open: resolvedMode === "light" ? "text-green-700" : "text-profit",
    "pre-market": "text-amber-400",
    closed: "text-text-muted",
    weekend: "text-text-muted",
  };

  return (
    <div
      className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-surface-hover shrink-0"
      aria-label={`Market status: ${statusInfo.label}`}
    >
      <div
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotClass[statusInfo.status]}`}
        aria-hidden="true"
      />
      <span className={`text-xs font-medium tabular-nums whitespace-nowrap ${textClass[statusInfo.status]}`}>
        {statusInfo.label}
      </span>
    </div>
  );
}

const BASE_ROUTE_TABS = [
  { path: "/learn", label: "Learn" },
  { path: "/invest", label: "Invest" },
  { path: "/trade", label: "Trade" },
  { path: "/lab", label: "Lab" },
  { path: "/automate", label: "Automate" },
  { path: "/ai", label: "AI" },
] as const;

/** Advanced-only tabs appended when skill level is "advanced". */
const ADVANCED_ROUTE_TABS = [
  { path: "/ditto", label: "Multi-Account" },
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

  const glass = useThemeStore(useShallow((s) => s.glass));
  const globalSkill = useSkillLevel();
  const routeTabs = globalSkill === "advanced"
    ? [...BASE_ROUTE_TABS, ...ADVANCED_ROUTE_TABS]
    : [...BASE_ROUTE_TABS];

  const status = useConnectionStore((s) => s.status);
  const setStatus = useConnectionStore((s) => s.setStatus);
  const [broker, setBroker] = useState("");

  const totalPnl = useTradingStore((s) => s.totalPnl);
  const positionCount = useTradingStore((s) => s.positionCount);

  // tabs is an array — useShallow prevents re-renders when the reference changes
  // but the contents (ids/names) are the same
  const tabs = useLayoutStore(useShallow((s) => s.tabs));
  const activeTabId = useLayoutStore((s) => s.activeTabId);
  const toolsMenuOpen = useLayoutStore((s) => s.toolsMenuOpen);
  // Group action selectors into a single shallow call — functions are stable
  // references but grouping reduces the number of store subscriptions
  const {
    setActiveTab,
    addTab,
    removeTab,
    renameTab,
    saveTabLayout,
    getTabLayout,
    setWidgetPickerOpen,
    setToolsMenuOpen,
    setPresetPickerOpen,
  } = useLayoutStore(
    useShallow((s) => ({
      setActiveTab: s.setActiveTab,
      addTab: s.addTab,
      removeTab: s.removeTab,
      renameTab: s.renameTab,
      saveTabLayout: s.saveTabLayout,
      getTabLayout: s.getTabLayout,
      setWidgetPickerOpen: s.setWidgetPickerOpen,
      setToolsMenuOpen: s.setToolsMenuOpen,
      setPresetPickerOpen: s.setPresetPickerOpen,
    }))
  );

  const [contextMenu, setContextMenu] = useState<{ tabId: string; x: number; y: number } | null>(null);
  /** Id of the workspace tab currently being renamed inline. */
  const [renamingTabId, setRenamingTabId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  /** Id of the workspace tab awaiting inline delete confirmation. */
  const [deletingTabId, setDeletingTabId] = useState<string | null>(null);
  /** Quick settings panel open state */
  const [quickSettingsOpen, setQuickSettingsOpen] = useState(false);
  const gearRef = useRef<HTMLButtonElement>(null);
  /** TOOLS button ref — used to anchor the ToolsDropdown portal (Issue #39) */
  const toolsButtonRef = useRef<HTMLButtonElement>(null);

  const connected = status === "connected";

  const themeMode = useThemeStore((s) => s.mode);
  const setThemeMode = useThemeStore((s) => s.setMode);

  // Pending action center orders — only poll when connected, every 5s
  const isConnected = useConnectionStore((s) => s.status === "connected");
  const { data: pendingOrders } = useQuery({
    queryKey: ["actionCenterPending"],
    queryFn: getPendingOrders,
    enabled: isConnected,
    refetchInterval: isConnected ? 5_000 : false,
    // Don't throw on error — badge simply won't appear
    throwOnError: false,
  });
  const pendingCount = (pendingOrders ?? []).length;

  /**
   * Handle tool selection from ToolsDropdown (Issue #75).
   * On /trade: dispatch flinttrade:open-tool so TerminalRoute opens the overlay.
   * On other routes: ToolsDropdown handles navigation to /settings itself.
   */
  const handleSelectTool = useCallback((toolId: ToolId) => {
    window.dispatchEvent(
      new CustomEvent("flinttrade:open-tool", { detail: { toolId } }),
    );
    setToolsMenuOpen(false);
  }, [setToolsMenuOpen]);

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

  // Close QuickAccessPanel when clicking outside the panel or its trigger button
  useEffect(() => {
    if (!quickSettingsOpen) return;
    const handler = (e: MouseEvent) => {
      const panel = document.querySelector("[role='dialog'][aria-label='Quick settings']");
      if (
        panel &&
        !panel.contains(e.target as Node) &&
        gearRef.current &&
        !gearRef.current.contains(e.target as Node)
      ) {
        setQuickSettingsOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [quickSettingsOpen]);

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

  // Ctrl+, (or Cmd+,) → navigate to /settings
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ",") {
        e.preventDefault();
        navigate("/settings");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate]);

  const pnlColor = totalPnl >= 0 ? "text-profit" : "text-loss";
  const pnlSign = totalPnl >= 0 ? "+" : "";

  // Glass: apply backdrop-blur + reduced opacity background when enabled.
  // When disabled, fall back to the solid surface-card token via className.
  const glassStyle: React.CSSProperties = glass.enabled
    ? {
        backdropFilter: `blur(${glass.blur}px)`,
        WebkitBackdropFilter: `blur(${glass.blur}px)`,
        // Use CSS variable opacity notation supported in modern browsers
        backgroundColor: `color-mix(in srgb, var(--color-surface-card) ${100 - glass.transparency}%, transparent)`,
      }
    : {};

  return (
    <div
      className={`h-10 border-b border-border-default flex items-center justify-between px-3 select-none shrink-0 animate-fade-in${glass.enabled ? "" : " bg-surface-card"}`}
      style={glass.enabled ? glassStyle : undefined}
    >
      {/* Left: Logo + Route Tabs + Separator + Workspace Tabs */}
      <div className="flex items-center gap-3">
        <Link to="/trade" aria-label="FlintTrade home" className="flex items-center shrink-0">
          <LogoIcon size={20} />
        </Link>

        {/* Route tabs (always visible) */}
        <nav aria-label="Main navigation" className="flex items-center gap-0.5 ml-3">
          {routeTabs.map((tab) => {
            const isActive = currentPath === tab.path;
            return (
              <Link
                key={tab.path}
                to={tab.path}
                aria-current={isActive ? "page" : undefined}
                className={`relative px-3 py-1 text-xs font-heading font-medium rounded transition-colors no-underline ${
                  isActive
                    ? "bg-accent/15 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
                }`}
              >
                {tab.label}
                {isActive && (
                  <motion.div
                    layoutId="route-tab-underline"
                    className="absolute bottom-0 left-0 right-0 h-0.5 bg-accent rounded-full"
                    initial={false}
                    transition={{ duration: 0.2, ease: [0.25, 1, 0.5, 1] }}
                  />
                )}
              </Link>
            );
          })}
        </nav>

        {/* Separator + Workspace tabs (only on /terminal) */}
        {isTerminal && (
          <>
            <div className="w-px h-4 bg-border-default mx-2" />

            <div role="tablist" aria-label="Workspaces" className="flex items-center gap-1">
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
                      role="tab"
                      aria-selected={tab.id === activeTabId}
                      onClick={() => setActiveTab(tab.id)}
                      onContextMenu={(e) => handleTabContextMenu(e, tab.id)}
                      onKeyDown={(e) => {
                        if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
                          e.preventDefault();
                          const rect = e.currentTarget.getBoundingClientRect();
                          setContextMenu({ tabId: tab.id, x: rect.left, y: rect.bottom });
                        }
                        if (e.key === "Escape") {
                          setContextMenu(null);
                        }
                      }}
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
                onKeyDown={(e) => { if (e.key === "Escape") setContextMenu(null); }}
                role="menu"
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

      {/* Center: P&L summary — always visible to prevent layout shift */}
      <div
        className="flex items-center gap-2 w-40 justify-center"
        aria-label={
          positionCount > 0
            ? `Total P&L: ${totalPnl >= 0 ? "+" : ""}${totalPnl.toLocaleString()}, ${positionCount} position${positionCount !== 1 ? "s" : ""}`
            : "No open positions"
        }
      >
        {positionCount > 0 ? (
          <>
            <span className={`font-mono text-xs tabular-nums ${pnlColor}`}>
              {pnlSign}{totalPnl.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <Badge variant="secondary" className="text-xxs px-1.5 py-0">
              {positionCount} pos
            </Badge>
          </>
        ) : (
          <span className="font-mono text-xs tabular-nums text-text-muted">
            0 positions · ₹0.00
          </span>
        )}
      </div>

      {/* Right: TOOLS (all routes) + WIDGETS (/trade only) + AccountSwitcher + SandboxToggle + Connection status + Clock */}
      <div className="flex items-center gap-2">
        {/* TOOLS: always visible — shows route-relevant tools via ToolsDropdown (portal) */}
        <Button
          ref={toolsButtonRef}
          variant="ghost"
          size="sm"
          onClick={() => setToolsMenuOpen(!toolsMenuOpen)}
          aria-expanded={toolsMenuOpen}
          aria-haspopup="menu"
          className="h-7 px-2 text-xs text-text-secondary hover:text-text-primary relative"
        >
          <Wrench size={14} className="mr-1" />
          TOOLS
          {/* Pending action center badge */}
          {pendingCount > 0 && (
            <span
              className="absolute -top-1 -right-1 min-w-[16px] h-4 flex items-center justify-center rounded-full bg-loss text-white text-xxs font-bold px-1 leading-none"
              aria-label={`${pendingCount} pending order approval${pendingCount !== 1 ? "s" : ""}`}
            >
              {pendingCount > 9 ? "9+" : pendingCount}
            </span>
          )}
        </Button>
        {/* ToolsDropdown portal — renders outside TopBar so it is never clipped
            by parent overflow (Issue #39). Visible on all app routes (Issue #75). */}
        <ToolsDropdown
          isOpen={toolsMenuOpen}
          onClose={() => setToolsMenuOpen(false)}
          onSelectTool={handleSelectTool}
          anchorRect={toolsButtonRef.current?.getBoundingClientRect()}
        />

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

        <div className="w-px h-4 bg-border-default" aria-hidden="true" />

        {/* Account switcher — hidden when no accounts connected */}
        <AccountSwitcher />

        {/* Sandbox / Live trading toggle */}
        <SandboxToggle />

        {/* Sun/Moon/Monitor quick mode flip — cycles: dark → light → system → dark */}
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0"
          onClick={() => {
            const nextMode = themeMode === "dark" ? "light" : themeMode === "light" ? "system" : "dark";
            setThemeMode(nextMode);
          }}
          aria-label={
            themeMode === "dark"
              ? "Switch to light mode"
              : themeMode === "light"
                ? "Switch to system mode"
                : "Switch to dark mode"
          }
        >
          {themeMode === "dark" ? (
            <Sun className="h-3.5 w-3.5" aria-hidden="true" />
          ) : themeMode === "light" ? (
            <Moon className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <Monitor className="h-3.5 w-3.5" aria-hidden="true" />
          )}
        </Button>

        {/* Gear icon + QuickAccessPanel (portal-rendered to escape stacking context) */}
        <div>
          <Button
            ref={gearRef}
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0"
            onClick={() => setQuickSettingsOpen(!quickSettingsOpen)}
            aria-label="Quick settings"
            aria-expanded={quickSettingsOpen}
            aria-haspopup="dialog"
          >
            <Settings className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
        {/* Portal — renders outside the TopBar stacking context so z-50 works correctly */}
        <AnimatePresence>
          {quickSettingsOpen && createPortal(
            <QuickAccessPanel
              onClose={() => setQuickSettingsOpen(false)}
              triggerRef={gearRef}
              anchorRect={gearRef.current?.getBoundingClientRect()}
            />,
            document.body,
          )}
        </AnimatePresence>

        <div className="w-px h-4 bg-border-default" aria-hidden="true" />

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
