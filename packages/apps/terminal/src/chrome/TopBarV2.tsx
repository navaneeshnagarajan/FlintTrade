/**
 * TopBarV2 — redesigned glass chrome bar (38px, single row).
 *
 * Layout (left → right):
 *   [FlintLogo] | [TickerMarquee (flex:1)] [GearIcon] | [SearchBtn Ctrl+K]
 *   [BellIcon] [FullscreenIcon] [LiveBadge] [ClockIST] [Avatar]
 *
 * Design:
 *   - Background: rgba(12, 12, 20, 0.85) + backdrop-filter: blur(16px)
 *   - Border-bottom: 1px solid rgba(255,255,255,0.05)
 *   - Sticky top, z-index 100
 *   - 1px × 18px rgba dividers between groups
 *
 * NO AI pill — that is a separate persistent overlay at bottom-right.
 * NO route tabs — those move to the sidebar in Phase 2.
 *
 * Click fires flinttrade:open-command-palette; keyboard handling is owned by
 * the active route's global shortcut layer.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { Search, Maximize2, Minimize2, Settings, Wrench } from "lucide-react";
import { LogoIcon } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useSkillContent } from "@/hooks/useSkillContent";
import { useTimings } from "@/hooks/useMarketStatus";
import { ping } from "@/services/api";
import type { MarketTiming } from "@/types/api";
import type { ToolId } from "@/types/widgets";
import NotificationBell from "@/components/NotificationCentre/NotificationCentre";
import AccountSwitcher from "./AccountSwitcher";
import QuickAccessPanel from "./QuickAccessPanel";
import TickerMarquee from "./TickerMarquee";
import type { TickerMode } from "./TickerMarquee";
import ToolsDropdown from "./ToolsDropdown";

// ---------------------------------------------------------------------------
// ISTClock
// ---------------------------------------------------------------------------

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
        }),
      );
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <span
      className="font-mono text-xs text-text-secondary tabular-nums shrink-0"
      aria-label="Current time in IST"
    >
      {time} IST
    </span>
  );
}

// ---------------------------------------------------------------------------
// MarketStatus — "Live" badge (green pulse when open, muted when closed)
// ---------------------------------------------------------------------------

type MarketStatus = "open" | "pre-market" | "closed" | "weekend";

interface MarketStatusInfo {
  status: MarketStatus;
  label: string;
}

function getNseStatus(timings: MarketTiming[] | undefined): MarketStatusInfo {
  const now = new Date();
  const istString = now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" });
  const ist = new Date(istString);
  const day = ist.getDay();

  if (day === 0 || day === 6) return { status: "weekend", label: "Weekend" };

  const nowMs = now.getTime();
  const nseTiming = timings?.find(
    (t) => t.exchange === "NSE" || t.exchange === "NSE_INDEX",
  );

  if (nseTiming) {
    if (nowMs < nseTiming.start_time)
      return { status: "pre-market", label: "Pre-Market" };
    if (nowMs <= nseTiming.end_time)
      return { status: "open", label: "Live" };
    return { status: "closed", label: "Closed" };
  }

  // Fallback: 9:15–15:30 IST
  const hour = ist.getHours();
  const mins = hour * 60 + ist.getMinutes();
  if (mins < 9 * 60 + 15) return { status: "pre-market", label: "Pre-Market" };
  if (mins <= 15 * 60 + 30) return { status: "open", label: "Live" };
  return { status: "closed", label: "Closed" };
}

function LiveBadge() {
  const { data: timings } = useTimings();
  const [statusInfo, setStatusInfo] = useState<MarketStatusInfo>(() =>
    getNseStatus(timings),
  );

  useEffect(() => {
    const update = () => setStatusInfo(getNseStatus(timings));
    update();
    const id = setInterval(update, 30_000);
    return () => clearInterval(id);
  }, [timings]);

  const isOpen = statusInfo.status === "open";

  return (
    <div
      className="flex items-center gap-1 px-1.5 py-0.5 rounded shrink-0"
      style={{
        background: isOpen ? "var(--color-bullish-bg)" : "var(--glass-l2-bg)",
        border: isOpen ? "1px solid var(--color-bullish-border)" : "1px solid var(--glass-l2-border)",
      }}
      aria-label={`Market status: ${statusInfo.label}`}
      data-testid="live-badge"
    >
      <div
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
          isOpen
            ? "bg-profit animate-[pulse-glow_2s_ease-in-out_infinite]"
            : statusInfo.status === "pre-market"
              ? "bg-amber-400"
              : "bg-text-muted/50"
        }`}
        aria-hidden="true"
      />
      <span
        className={`text-xs font-medium tabular-nums whitespace-nowrap ${
          isOpen
            ? "text-profit"
            : statusInfo.status === "pre-market"
              ? "text-amber-400"
              : "text-text-muted"
        }`}
      >
        {statusInfo.label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Divider — 1px × 18px rgba separator
// ---------------------------------------------------------------------------

function Divider() {
  return (
    <div
      className="w-px shrink-0"
      style={{ height: 18, background: "var(--glass-chrome-border, rgba(255,255,255,0.08))" }}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// Fullscreen toggle
// ---------------------------------------------------------------------------

function FullscreenButton() {
  const [isFullscreen, setIsFullscreen] = useState(
    () => !!document.fullscreenElement,
  );

  useEffect(() => {
    const handler = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", handler);
    return () => document.removeEventListener("fullscreenchange", handler);
  }, []);

  const toggle = useCallback(async () => {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen();
      } else {
        await document.exitFullscreen();
      }
    } catch {
      // Ignore — some browsers block fullscreen without user gesture
    }
  }, []);

  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-7 w-7 p-0 text-text-muted hover:text-text-primary"
      onClick={toggle}
      aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen (F11)"}
      data-testid="fullscreen-btn"
    >
      {isFullscreen ? (
        <Minimize2 className="h-3.5 w-3.5" aria-hidden="true" />
      ) : (
        <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Avatar — placeholder until auth/profile is wired
// ---------------------------------------------------------------------------

function Avatar() {
  return (
    <button
      type="button"
      className="w-6 h-6 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center text-accent text-xs font-bold shrink-0 hover:bg-accent/30 transition-colors focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
      aria-label="User profile"
      data-testid="avatar-btn"
    >
      U
    </button>
  );
}

// ---------------------------------------------------------------------------
// SearchButton
// ---------------------------------------------------------------------------

const isMac =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function SearchButton() {
  const handleClick = useCallback(() => {
    window.dispatchEvent(new CustomEvent("flinttrade:open-command-palette"));
  }, []);

  const shortcutHint = isMac ? "⌘K" : "Ctrl+K";

  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-7 px-2 gap-1.5 text-text-muted hover:text-text-primary shrink-0"
      onClick={handleClick}
      aria-label={`Search (${shortcutHint})`}
      data-testid="search-btn"
    >
      <Search className="h-3.5 w-3.5" aria-hidden="true" />
      <span className="text-xs hidden sm:inline">Search</span>
      <kbd
        className="hidden sm:inline-flex items-center rounded border border-border-default px-1 text-xxs text-text-muted/60 font-mono leading-none"
        aria-hidden="true"
      >
        {shortcutHint}
      </kbd>
    </Button>
  );
}

// ---------------------------------------------------------------------------
// TopBarV2
// ---------------------------------------------------------------------------

export interface TopBarV2Props {
  /** Overrides the persisted ticker mode from the settings store. Useful in tests. */
  tickerMode?: TickerMode;
}

export default function TopBarV2({ tickerMode: tickerModeProp }: TopBarV2Props) {
  const setStatus = useConnectionStore((s) => s.setStatus);
  const storedTickerMode = useSettingsStore((s) => s.tickerMode);
  const tickerMode: TickerMode = tickerModeProp ?? storedTickerMode;
  const { availableTools } = useSkillContent();
  const [quickSettingsOpen, setQuickSettingsOpen] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const gearRef = useRef<HTMLButtonElement>(null);
  const toolsRef = useRef<HTMLButtonElement>(null);

  // Ping OpenAlgo every 10 s to maintain connection status
  useEffect(() => {
    const check = async () => {
      try {
        await ping();
        setStatus("connected");
      } catch {
        setStatus("disconnected");
      }
    };
    check();
    const id = setInterval(check, 10_000);
    return () => clearInterval(id);
  }, [setStatus]);

  // Close QuickAccessPanel on outside click
  useEffect(() => {
    if (!quickSettingsOpen) return;
    const handler = (e: MouseEvent) => {
      const panel = document.querySelector(
        "[role='dialog'][aria-label='Quick settings']",
      );
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

  const barStyle: React.CSSProperties = {
    background: "var(--glass-chrome-bg, rgba(12,12,20,0.85))",
    backdropFilter: "blur(16px)",
    WebkitBackdropFilter: "blur(16px)",
    borderBottom: "1px solid var(--glass-chrome-border, rgba(255,255,255,0.05))",
  };

  const handleSelectTool = useCallback((toolId: ToolId) => {
    window.dispatchEvent(
      new CustomEvent("flinttrade:open-tool", { detail: { toolId } }),
    );
  }, []);

  return (
    <div
      className="sticky top-0 z-100 flex items-center h-9.5 px-3 shrink-0 select-none animate-fade-in"
      style={barStyle}
      data-testid="topbar-v2"
    >
      {/* ── GROUP 1: Logo ─────────────────────────────────────────────────── */}
      <Link
        to="/trade"
        aria-label="Flint home"
        className="flex items-center gap-1.5 shrink-0 mr-2"
        data-testid="logo-link"
      >
        <LogoIcon size={18} aria-hidden />
        <span className="font-heading font-bold text-sm text-text-primary tracking-tight leading-none">
          Flint
        </span>
      </Link>

      <Divider />

      {/* ── GROUP 2: Ticker (flex:1) + Gear ───────────────────────────────── */}
      <div className="flex items-center gap-1 flex-1 min-w-0 mx-2">
        {tickerMode !== "off" && (
          <TickerMarquee
            mode={tickerMode}
            className="flex-1 min-w-0 h-9.5"
          />
        )}

        {/* Gear icon: ticker settings */}
        <Button
          ref={gearRef}
          variant="ghost"
          size="sm"
          className="h-7 w-7 p-0 text-text-muted hover:text-text-primary shrink-0"
          onClick={() => setQuickSettingsOpen(!quickSettingsOpen)}
          aria-label="Quick settings"
          aria-expanded={quickSettingsOpen}
          aria-haspopup="dialog"
          data-testid="gear-btn"
        >
          <Settings className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </div>

      <Divider />

      {/* ── GROUP 3: Right controls ───────────────────────────────────────── */}
      <div className="flex items-center gap-1 ml-2 shrink-0">
        {/* Search / command palette */}
        <SearchButton />

        {/* Route-aware tool menu */}
        <Button
          ref={toolsRef}
          variant="ghost"
          size="sm"
          className="h-7 px-2 gap-1.5 text-text-muted hover:text-text-primary shrink-0"
          onClick={() => {
            setToolsOpen((open) => !open);
            setQuickSettingsOpen(false);
          }}
          aria-label="Tools"
          aria-expanded={toolsOpen}
          aria-haspopup="menu"
          data-testid="tools-btn"
        >
          <Wrench className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="text-xs hidden md:inline">Tools</span>
        </Button>

        {/* Notification bell */}
        <NotificationBell />

        {/* Connected broker account context */}
        <AccountSwitcher />

        {/* Fullscreen toggle */}
        <FullscreenButton />

        <Divider />

        {/* Live badge */}
        <LiveBadge />

        {/* IST clock */}
        <ISTClock />

        {/* Avatar */}
        <Avatar />
      </div>

      {/* QuickAccessPanel portal — renders outside TopBar stacking context */}
      {createPortal(
        <AnimatePresence>
          {quickSettingsOpen && (
            <QuickAccessPanel
              key="quick-settings"
              onClose={() => setQuickSettingsOpen(false)}
              triggerRef={gearRef}
              anchorRect={gearRef.current?.getBoundingClientRect()}
            />
          )}
        </AnimatePresence>,
        document.body,
      )}

      <ToolsDropdown
        isOpen={toolsOpen}
        onClose={() => setToolsOpen(false)}
        onSelectTool={handleSelectTool}
        anchorRect={toolsRef.current?.getBoundingClientRect()}
        allowedToolIds={availableTools}
      />
    </div>
  );
}
