/**
 * TopBarV2 — the app bar (44px, single row), in three zones:
 *
 *   [Menu*] [F FlintTrade] | [Search symbols, pages, commands…  Ctrl K]
 *                                  [Account*] [Mode] [Market · IST] [Status]
 *                                  | [Ask AI] [Tools] [Fullscreen] [Bell] [Avatar]
 *
 *   * Menu appears below 768px and opens the navigation drawer; Account
 *     appears once a broker account exists.
 *
 * Each status has one home. Broker, Laya and LLM live in the Status menu:
 * one worst-first dot on the bar, plain words in its popover. Feed
 * provenance lives once, at the start of the ticker. The market session has
 * one label from one source (useOperatorMarketSession). The Workspace
 * switcher lives on the Trade desk toolbar, where workspaces apply.
 *
 * FT-UX-002: TopBar is not a quote rail. The dedicated scrolling ticker
 * lives under this bar (TickerBar / TickerStrip). There is no Settings gear.
 * Tools → Quick Settings opens density, theme, and similar controls in
 * place. Tools → Settings opens the full Settings route. Compact Trade
 * hides the tool ribbon but keeps Quick Settings on this bar.
 *
 * Click on Search fires flinttrade:open-command-palette; keyboard handling is
 * owned by the active route's global shortcut layer.
 *
 * Skinny windows (FT-MOBILE-002): ticker hides under ~480px; at ~390px
 * Workspace and secondary chrome move into a More sheet so Mode stays
 * reachable and the bar does not scroll sideways.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router";
import {
  Menu,
  Search,
  Maximize2,
  Minimize2,
  MoreHorizontal,
  SlidersHorizontal,
  Sparkles,
  Wrench,
} from "lucide-react";
import { AnimatePresence } from "framer-motion";
import { LogoIcon } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { useModeStore } from "@/stores/modeStore";
import { useSidebarStore } from "@/stores/sidebarStore";
import { useSkillStore } from "@/stores/skillStore";
import { DeskStatusCluster } from "@/chrome/DeskStatusCluster";
import WorkspaceSwitcher from "@/chrome/WorkspaceSwitcher";
import { useDirectBrokerConnected } from "@/hooks/useBrokerConnected";
import { useOperatorIncident } from "@/hooks/useOperatorIncident";
import { brokerSessionDarkened } from "@/lib/operatorIncident";
import { useSkillContent } from "@/hooks/useSkillContent";
import { useOperatorMarketSession } from "@/hooks/useOperatorMarketSession";
import { ping } from "@/services/api";
import {
  operatorMarketLabel,
  type MarketSessionInfo,
} from "@/lib/market";
import { cn } from "@/lib/utils";
import type { ToolId } from "@/types/widgets";
import NotificationBell from "@/components/NotificationCentre/NotificationCentre";
import AccountSwitcher from "./AccountSwitcher";
import ModeIndicator from "./ModeIndicator";
import type { TickerMode } from "./TickerMarquee";
import ToolsDropdown from "./ToolsDropdown";
import QuickAccessPanel from "./QuickAccessPanel";
import SystemStatusMenu from "./SystemStatusMenu";
import TopBarMoreSheet, { MoreRow } from "./TopBarMoreSheet";
import { useChromeCollapse } from "./useChromeCollapse";
import { useDeskDensityChrome } from "@/hooks/useDeskDensityChrome";
import { useDeskChromeStore } from "@/stores/deskChromeStore";
import { TOGGLE_AI_TUTOR_EVENT } from "@/lib/aiTutorEvents";

const NAV_DRAWER_MAX_WIDTH = 767;

function useNavDrawerViewport(): boolean {
  const query = `(max-width: ${NAV_DRAWER_MAX_WIDTH}px)`;
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : false,
  );
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** Shared look for every icon-and-label control on the bar. */
const barButton =
  "h-8 shrink-0 gap-1.5 px-2.5 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary";

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
// MarketStatus — explicit NSE session state, separate from Live execution mode
// ---------------------------------------------------------------------------

function sessionChipTone(info: MarketSessionInfo): "green" | "amber" | "muted" {
  if (info.isGreenOpen) return "green";
  if (info.status === "unavailable" || info.status === "closed") return "muted";
  return "amber";
}

function MarketSessionStatus() {
  const statusInfo = useOperatorMarketSession();
  const label = operatorMarketLabel(statusInfo);
  const tone = sessionChipTone(statusInfo);

  return (
    <div className="flex items-center gap-1 shrink-0">
      <div
        className="flex items-center gap-1.5 rounded-md px-1.5 py-0.5"
        aria-label={`Market status: ${label}`}
        title={
          statusInfo.status === "closed" || statusInfo.status === "unavailable"
            ? label
            : statusInfo.title
        }
        data-testid="market-session-status"
      >
        <div
          className={cn(
            "size-1.5 shrink-0 rounded-full",
            tone === "green"
              ? "bg-profit animate-[pulse-glow_2s_ease-in-out_infinite]"
              : tone === "amber"
                ? "bg-amber-400"
                : "bg-text-muted",
          )}
          aria-hidden="true"
        />
        <span
          className={cn(
            "whitespace-nowrap text-xs font-medium tabular-nums",
            tone === "green"
              ? "text-profit"
              : tone === "amber"
                ? "text-[var(--color-warning-text,var(--color-warning))]"
                : "text-text-secondary",
          )}
        >
          {label}
        </span>
      </div>
      {statusInfo.foSecondary ? (
        <div
          className="flex items-center rounded-md border border-border-default px-1.5 py-0.5"
          aria-label={statusInfo.foSecondary}
          title={statusInfo.foSecondary}
          data-testid="fo-session-status"
        >
          <span className="whitespace-nowrap text-xs font-medium tabular-nums text-text-secondary">
            {statusInfo.foSecondary}
          </span>
        </div>
      ) : null}
    </div>
  );
}

/** Market session and IST clock share one chip: both answer "can I trade now?". */
function MarketChip({ showClock }: { showClock: boolean }) {
  return (
    <div
      className="flex h-8 shrink-0 items-center gap-1 rounded-md border border-border-default bg-surface-base/60 pl-1 pr-2"
      data-testid="market-chip"
    >
      <MarketSessionStatus />
      {showClock ? (
        <>
          <span aria-hidden="true" className="h-3.5 w-px bg-border-default" />
          <span className="pl-1">
            <ISTClock />
          </span>
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Divider
// ---------------------------------------------------------------------------

function Divider() {
  return <div className="mx-1 h-5 w-px shrink-0 bg-border-default" aria-hidden="true" />;
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
      className="h-8 w-8 p-0 text-text-secondary hover:text-text-primary"
      onClick={toggle}
      aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen (F11)"}
      title={isFullscreen ? "Exit fullscreen" : "Enter fullscreen (F11)"}
      data-testid="fullscreen-btn"
    >
      {isFullscreen ? (
        <Minimize2 className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Maximize2 className="h-4 w-4" aria-hidden="true" />
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Avatar — opens the Profile Manager (Settings → Profile)
// ---------------------------------------------------------------------------

function Avatar() {
  const navigate = useNavigate();
  const name = useSettingsStore((s) => s.name);
  const initial = (name.trim()[0] ?? "T").toUpperCase();

  return (
    <button
      type="button"
      className="ml-1 flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/30 bg-accent/15 text-xs font-bold text-accent transition-colors hover:bg-accent/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      aria-label="Open profile and settings"
      title="Profile and settings"
      data-testid="avatar-btn"
      onClick={() => navigate("/settings#profile")}
    >
      {initial}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Search — looks and reads like a search field; opens the command palette
// ---------------------------------------------------------------------------

const isMac =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function SearchButton({ variant = "field" }: { variant?: "field" | "row" }) {
  const handleClick = useCallback(() => {
    window.dispatchEvent(new CustomEvent("flinttrade:open-command-palette"));
  }, []);

  const shortcutHint = isMac ? "⌘K" : "Ctrl+K";

  if (variant === "row") {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="h-8 gap-1.5 px-2 text-text-secondary hover:text-text-primary"
        onClick={handleClick}
        aria-label={`Search (${shortcutHint})`}
        data-testid="search-btn"
      >
        <Search className="h-4 w-4" aria-hidden="true" />
        <span className="text-xs">Search</span>
      </Button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-label={`Search (${shortcutHint})`}
      data-testid="search-btn"
      className={cn(
        "group flex h-8 w-full min-w-0 max-w-md items-center gap-2 rounded-md border border-border-default bg-surface-base/70 px-2.5 text-left transition-colors",
        "hover:border-border-strong hover:bg-surface-hover",
      )}
    >
      <Search className="h-4 w-4 shrink-0 text-text-muted" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate text-xs text-text-muted group-hover:text-text-secondary">
        Search symbols, pages, commands…
      </span>
      <kbd
        className="hidden shrink-0 items-center rounded border border-border-default px-1.5 py-px font-mono text-xxs text-text-muted sm:inline-flex"
        aria-hidden="true"
      >
        {shortcutHint}
      </kbd>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Ask AI — launches the shared AI tutor panel
// ---------------------------------------------------------------------------

function AskAIButton() {
  const aiTutorEnabled = useSkillStore((s) => s.helpPrefs.aiTutor);
  if (!aiTutorEnabled) return null;
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={barButton}
      onClick={() => window.dispatchEvent(new CustomEvent(TOGGLE_AI_TUTOR_EVENT))}
      aria-label="Ask AI"
      data-testid="ask-ai-btn"
    >
      <Sparkles className="h-4 w-4 text-accent" aria-hidden="true" />
      <span className="hidden lg:inline">Ask AI</span>
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
  const mode = useModeStore((s) => s.mode);
  const directBrokerConnected = useDirectBrokerConnected();
  const operatorIncident = useOperatorIncident();
  const moneyPathClosed = brokerSessionDarkened(operatorIncident);
  const hasBrokerAccounts = useBrokerStore((s) => s.accounts.length > 0);
  const storedTickerMode = useSettingsStore((s) => s.tickerMode);
  const setTickerMode = useSettingsStore((s) => s.setTickerMode);
  const tickerMode: TickerMode = tickerModeProp ?? storedTickerMode;
  const { availableTools } = useSkillContent();
  const { collapseOverflow } = useChromeCollapse();
  const navDrawer = useNavDrawerViewport();
  const mobileNavOpen = useSidebarStore((s) => s.mobileOpen);
  const setMobileNavOpen = useSidebarStore((s) => s.setMobileOpen);
  const {
    showToolRibbon,
    setToolsExpanded,
  } = useDeskDensityChrome();
  const tickerForcedOnNarrow = useDeskChromeStore((s) => s.tickerForcedOnNarrow);
  const setTickerForcedOnNarrow = useDeskChromeStore((s) => s.setTickerForcedOnNarrow);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [quickSettingsOpen, setQuickSettingsOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const toolsRef = useRef<HTMLButtonElement>(null);
  const compactQuickRef = useRef<HTMLButtonElement>(null);
  const panelTriggerRef = useRef<HTMLButtonElement | null>(null);
  const hideDeskRibbon = !showToolRibbon && !collapseOverflow;

  const openQuickSettings = useCallback((trigger: HTMLButtonElement | null) => {
    panelTriggerRef.current = trigger;
    setQuickSettingsOpen(true);
    setToolsOpen(false);
  }, []);

  useEffect(() => {
    const handleQuickSettings = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key !== "," || event.altKey) return;
      event.preventDefault();
      if (event.repeat) return;
      setMoreOpen(false);
      openQuickSettings(hideDeskRibbon ? compactQuickRef.current : toolsRef.current);
    };
    window.addEventListener("keydown", handleQuickSettings);
    return () => window.removeEventListener("keydown", handleQuickSettings);
  }, [hideDeskRibbon, openQuickSettings]);

  // Maintain broker connection status from either OpenAlgo bridge ping or a
  // live native/gateway broker session. This store still drives older widgets.
  //
  // Explore mode has NO broker: ping() there returns a demo mock that always
  // resolves, so treating a resolved ping as "connected" reported the gateway
  // as connected and fired a repeating "Broker gateway connected — live market
  // data and order routing are available" notification every poll. In Explore
  // the status is purely whatever real broker is connected (none), never the
  // demo ping.
  useEffect(() => {
    if (mode === "explore" || moneyPathClosed) {
      // Explore is broker-free. A leftover native session must not paint
      // Connected/green — same honesty as FT-AI-002 / FT-AUTO-002.
      // A money-path incident stays dark even when a broker session remains.
      setStatus("disconnected");
      return;
    }
    const check = async () => {
      try {
        await ping();
        setStatus("connected");
      } catch {
        setStatus(directBrokerConnected ? "connected" : "disconnected");
      }
    };
    check();
    const id = setInterval(check, 10_000);
    return () => clearInterval(id);
  }, [mode, directBrokerConnected, moneyPathClosed, setStatus]);

  const barStyle: React.CSSProperties = {
    background: "var(--glass-chrome-bg, rgba(12,12,20,0.85))",
    borderBottom: "1px solid var(--glass-chrome-border, rgba(255,255,255,0.05))",
  };

  const handleSelectTool = useCallback((toolId: ToolId) => {
    setQuickSettingsOpen(false);
    window.dispatchEvent(
      new CustomEvent("flinttrade:open-tool", { detail: { toolId } }),
    );
  }, []);

  return (
    <div
      className="sticky top-0 z-100 flex h-11 shrink-0 select-none items-center gap-2 overflow-x-hidden px-3"
      style={barStyle}
      data-testid="topbar-v2"
    >
      {/* ── Brand (and the navigation drawer toggle on narrow screens) ─────── */}
      {navDrawer ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 shrink-0 p-0 text-text-secondary hover:text-text-primary"
          onClick={() => setMobileNavOpen(!mobileNavOpen)}
          aria-label="Open navigation"
          aria-expanded={mobileNavOpen}
          data-testid="nav-drawer-btn"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
        </Button>
      ) : null}
      <Link
        to="/home"
        aria-label="FlintTrade home"
        className="flex shrink-0 items-center gap-2 rounded-md pr-1"
        data-testid="logo-link"
      >
        <LogoIcon size={20} aria-hidden />
        {!collapseOverflow && (
          <span className="font-heading text-sm font-bold leading-none tracking-tight text-text-primary">
            FlintTrade
          </span>
        )}
      </Link>

      {/* ── Search ─────────────────────────────────────────────────────────── */}
      <div className="flex min-w-0 flex-1 items-center px-1 md:px-3">
        {!collapseOverflow && !hideDeskRibbon ? <SearchButton /> : null}
      </div>

      {/* ── Context and actions ───────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center gap-1">
        {collapseOverflow ? (
          <>
            <ModeIndicator />
            <MarketSessionStatus />
            <Button
              variant="ghost"
              size="sm"
              className="h-8 px-2 text-text-secondary hover:text-text-primary shrink-0"
              onClick={() => {
                setMoreOpen((open) => !open);
                setToolsOpen(false);
              }}
              aria-label="More"
              aria-expanded={moreOpen}
              aria-haspopup="dialog"
              data-testid="topbar-more-btn"
            >
              <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
            </Button>
          </>
        ) : (
          <>
            {hasBrokerAccounts ? <AccountSwitcher /> : null}
            <ModeIndicator />
            <div className="hidden md:block">
              <MarketChip showClock={!hideDeskRibbon} />
            </div>
            <SystemStatusMenu />
            <Divider />
            <AskAIButton />
            {!hideDeskRibbon && (
              <Button
                ref={toolsRef}
                variant="ghost"
                size="sm"
                className={barButton}
                onClick={() => {
                  setQuickSettingsOpen(false);
                  setToolsOpen((open) => !open);
                }}
                aria-label="Tools"
                aria-expanded={toolsOpen}
                aria-haspopup="menu"
                data-testid="tools-btn"
              >
                <Wrench className="h-4 w-4" aria-hidden="true" />
                <span className="hidden lg:inline">Tools</span>
              </Button>
            )}
            {hideDeskRibbon && (
              <Button
                ref={compactQuickRef}
                type="button"
                variant="ghost"
                size="sm"
                className={barButton}
                onClick={() => {
                  if (quickSettingsOpen) {
                    setQuickSettingsOpen(false);
                    return;
                  }
                  openQuickSettings(compactQuickRef.current);
                }}
                aria-label="Quick Settings"
                aria-expanded={quickSettingsOpen}
                aria-haspopup="dialog"
                data-testid="quick-settings-btn"
              >
                <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
                <span>Quick Settings</span>
              </Button>
            )}
            {hideDeskRibbon && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className={barButton}
                onClick={() => setToolsExpanded(true)}
                aria-label="Watchlist and desk tools"
                data-testid="topbar-desk-tools-btn"
              >
                <Wrench className="h-4 w-4" aria-hidden="true" />
                <span>Desk tools</span>
              </Button>
            )}
            {!hideDeskRibbon && <FullscreenButton />}
            <NotificationBell />
            <Avatar />
          </>
        )}
      </div>

      <TopBarMoreSheet open={moreOpen && collapseOverflow} onClose={() => setMoreOpen(false)}>
        <MoreRow>
          <span className="w-20 shrink-0 text-xs text-text-muted">Workspace</span>
          <WorkspaceSwitcher />
        </MoreRow>
        {hasBrokerAccounts ? (
          <MoreRow>
            <span className="w-20 shrink-0 text-xs text-text-muted">Account</span>
            <AccountSwitcher />
          </MoreRow>
        ) : null}
        <MoreRow className="flex-col items-stretch py-1">
          <DeskStatusCluster variant="stacked" />
        </MoreRow>
        <MoreRow>
          <SearchButton variant="row" />
        </MoreRow>
        <MoreRow>
          <Button
            ref={toolsRef}
            variant="ghost"
            size="sm"
            className="min-h-11 px-2 gap-1.5 text-text-secondary hover:text-text-primary"
            onClick={() => {
              setQuickSettingsOpen(false);
              setToolsOpen((open) => !open);
            }}
            aria-label="Tools"
            aria-expanded={toolsOpen}
            aria-haspopup="menu"
            data-testid="tools-btn"
          >
            <Wrench className="h-4 w-4" aria-hidden="true" />
            <span className="text-xs">Tools</span>
          </Button>
        </MoreRow>
        <MoreRow>
          <FullscreenButton />
          <span className="text-xs text-text-secondary">Fullscreen</span>
        </MoreRow>
        <MoreRow>
          <ISTClock />
        </MoreRow>
        <MoreRow>
          <NotificationBell />
          <Avatar />
        </MoreRow>
        <MoreRow>
          <Button
            variant="ghost"
            size="sm"
            className="min-h-11 px-2 text-text-secondary hover:text-text-primary"
            onClick={() => {
              if (tickerForcedOnNarrow) {
                setTickerForcedOnNarrow(false);
              } else {
                if (tickerMode === "off") setTickerMode("marquee");
                setTickerForcedOnNarrow(true);
              }
              setMoreOpen(false);
            }}
            aria-label={tickerForcedOnNarrow ? "Hide ticker" : "Show ticker"}
          >
            {tickerForcedOnNarrow ? "Hide ticker" : "Show ticker"}
          </Button>
        </MoreRow>
      </TopBarMoreSheet>

      {createPortal(
        <AnimatePresence>
          {quickSettingsOpen ? (
            <QuickAccessPanel
              key="quick-settings"
              onClose={() => setQuickSettingsOpen(false)}
              triggerRef={panelTriggerRef}
              anchorRect={panelTriggerRef.current?.getBoundingClientRect()}
            />
          ) : null}
        </AnimatePresence>,
        document.body,
      )}

      <ToolsDropdown
        isOpen={toolsOpen}
        onClose={() => setToolsOpen(false)}
        onSelectTool={handleSelectTool}
        onOpenQuickSettings={() => openQuickSettings(toolsRef.current)}
        anchorRect={toolsRef.current?.getBoundingClientRect()}
        allowedToolIds={availableTools}
      />
    </div>
  );
}
