/**
 * QuickAccessPanel — Glass morphism settings dropdown from TopBar gear icon.
 *
 * Design: 320px wide, backdrop-blur 24px, green top-edge glow.
 * Animation: motionConfig.variants.scaleIn (scale 0.96→1, opacity 0→1).
 * Accessibility: role="dialog", arrow key navigation for theme dots,
 * focus management on open, Escape to close.
 *
 * NOTE: themeStore.mode / themeStore.setMode do not exist in Phase B.
 * They are read with a type-cast fallback and will be wired
 * in Phase C when the mode field is added to the store.
 */

import { useEffect, useRef, useCallback, forwardRef, type KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { layerClassNames } from "@flinttrade/design-system";
import { useModeStore } from "@/stores/modeStore";
import {
  Settings,
  X,
  Sun,
  Moon,
  Monitor,
  Check,
  Wifi,
  ShieldAlert,
  Brain,
  Send,
  TrendingUp,
  UserCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ShimmerButton } from "@/components/magicui/shimmer-button";
import { useConnectionStore } from "@/stores/connectionStore";
import type { WsFailure } from "@/services/websocket";
import { useSettingsStore } from "@/stores/settingsStore";
import { useThemeStore } from "@/stores/themeStore";
import { motionConfig } from "@/lib/motion";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface QuickAccessPanelProps {
  onClose: () => void;
  triggerRef?: React.RefObject<HTMLButtonElement | null>;
  /** Bounding rect of the trigger button — used for fixed positioning when rendered via portal. */
  anchorRect?: DOMRect;
}

type ColorMode = "dark" | "light" | "system";

// ---------------------------------------------------------------------------
// Theme dots config
// Phase B: hardcoded accent colors. Phase C: driven by themeStore presets.
// ---------------------------------------------------------------------------

// v4 themes — Graphite (emerald), Midnight (sky-blue), Ember (amber)
const THEME_DOTS = [
  { id: "graphite", label: "Graphite", color: "#22c55e" },
  { id: "midnight", label: "Midnight", color: "#38bdf8" },
  { id: "ember",    label: "Ember",    color: "#f59e0b" },
] as const;

// ---------------------------------------------------------------------------
// Section shortcuts config
// ---------------------------------------------------------------------------

const DENSITY_OPTIONS = ["compact", "comfortable"] as const;

const SECTION_SHORTCUTS = [
  { id: "profile", label: "Profile", icon: UserCircle },
  { id: "api", label: "API", icon: Wifi },
  { id: "risk", label: "Risk", icon: ShieldAlert },
  { id: "llm", label: "LLM", icon: Brain },
  { id: "telegram", label: "Telegram", icon: Send },
  { id: "trading", label: "Trading", icon: TrendingUp },
] as const;

// ---------------------------------------------------------------------------
// Mode segment button (forwardRef for first-focus management)
// ---------------------------------------------------------------------------

interface ModeButtonProps {
  mode: ColorMode;
  active: boolean;
  onClick: () => void;
}

const ModeButton = forwardRef<HTMLButtonElement, ModeButtonProps>(
  function ModeButton({ mode, active, onClick }, ref) {
    const icons: Record<ColorMode, React.ReactNode> = {
      dark: <Moon className="h-3.5 w-3.5" aria-hidden="true" />,
      light: <Sun className="h-3.5 w-3.5" aria-hidden="true" />,
      system: <Monitor className="h-3.5 w-3.5" aria-hidden="true" />,
    };
    const labels: Record<ColorMode, string> = {
      dark: "Dark",
      light: "Light",
      system: "System",
    };

    return (
      <button
        ref={ref}
        type="button"
        onClick={onClick}
        className={cn(
          "flex-1 flex flex-col items-center justify-center gap-1 py-2 rounded text-xs font-medium transition-colors",
          active
            ? "bg-accent/20 text-accent border border-accent/40"
            : "text-text-muted hover:text-text-primary hover:bg-surface-hover border border-transparent",
        )}
        aria-pressed={active}
        aria-label={`${labels[mode]} mode`}
      >
        {icons[mode]}
        <span className="text-[10px] leading-none">{labels[mode]}</span>
      </button>
    );
  },
);

// ---------------------------------------------------------------------------
// Connection status sub-card
// ---------------------------------------------------------------------------

interface ConnectionCardProps {
  connected: boolean;
  practiceMode: boolean;
  /** Latest WebSocket failure from the connection store — null when healthy. */
  wsFailure: WsFailure | null;
}

function ConnectionCard({ connected, practiceMode, wsFailure }: ConnectionCardProps) {
  // An auth rejection is more actionable than a bare "Disconnected" — name it,
  // and show the server's reason so the operator knows which key to fix.
  const authFailed = !connected && wsFailure?.kind === "auth";
  const label = connected
    ? "Connected"
    : authFailed
      ? "Authentication failed"
      : "Disconnected";
  return (
    <div
      className="p-2.5 rounded-lg border border-border-default"
      style={{ backgroundColor: "var(--glass-l2-bg, var(--color-surface-elevated))" }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "w-2 h-2 rounded-full shrink-0 transition-colors",
              connected
                ? "bg-profit ring-2 ring-profit/20 animate-[pulse-glow_2s_ease-in-out_infinite]"
                : "bg-loss",
            )}
            aria-hidden="true"
          />
          <span className={cn("text-xs font-medium", connected ? "text-profit" : "text-loss")}>
            {label}
          </span>
        </div>
        {practiceMode && (
          <Badge
            variant="outline"
            className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-400 bg-amber-500/10"
          >
            PRACTICE
          </Badge>
        )}
      </div>
      {authFailed && wsFailure && (
        <p className="mt-1 pl-4 text-xxs text-text-muted" role="status">
          {wsFailure.reason}
          {wsFailure.fatal ? " — update the API key in Settings to retry" : ""}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trading-mode label (read-only; the switch lives in the TopBar ModeIndicator)
// ---------------------------------------------------------------------------

const MODE_LABEL: Record<"explore" | "practice" | "live", { text: string; className: string }> = {
  explore: { text: "Explore", className: "text-text-secondary" },
  practice: { text: "Practice", className: "text-amber-400" },
  live: { text: "Live", className: "text-profit" },
};

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function QuickAccessPanel({ onClose, triggerRef, anchorRect }: QuickAccessPanelProps) {
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);
  const firstModeButtonRef = useRef<HTMLButtonElement>(null);

  // Connection state
  const status = useConnectionStore((s) => s.status);
  const wsFailure = useConnectionStore((s) => s.wsFailure);
  const connected = status === "connected";

  // Settings store — density only; mode is owned by modeStore
  const density = useSettingsStore((s) => s.density);
  const setDensity = useSettingsStore((s) => s.setDensity);

  // Mode store — current trading mode (switched from the TopBar ModeIndicator)
  const appMode = useModeStore((s) => s.mode);
  const isPractice = appMode === "practice";

  // Theme store — active theme for dot selection
  const activeThemeId = useThemeStore((s) => s.activeThemeId);
  const setTheme = useThemeStore((s) => s.setTheme);

  const mode = useThemeStore((s) => s.mode);
  const setMode = useThemeStore((s) => s.setMode);

  // Move focus to the first interactive element on mount
  useEffect(() => {
    const timer = setTimeout(() => {
      firstModeButtonRef.current?.focus();
    }, 50);
    return () => clearTimeout(timer);
  }, []);

  // Escape key: close panel and return focus to trigger button
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLDivElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        triggerRef?.current?.focus();
      }
    },
    [onClose, triggerRef],
  );

  // Theme dots: left/right arrow key navigation
  const handleThemeDotKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next =
        e.key === "ArrowRight"
          ? (index + 1) % THEME_DOTS.length
          : (index - 1 + THEME_DOTS.length) % THEME_DOTS.length;
      const container = panelRef.current?.querySelector(
        "[role='radiogroup'][aria-label='Theme']",
      );
      const dots = container?.querySelectorAll<HTMLButtonElement>("[role='radio']");
      dots?.[next]?.focus();
    },
    [],
  );

  // Density segment: left/right arrow key navigation (roving tabindex)
  const handleDensityKeyDown = useCallback(
    (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      e.preventDefault();
      const next =
        e.key === "ArrowRight"
          ? (index + 1) % DENSITY_OPTIONS.length
          : (index - 1 + DENSITY_OPTIONS.length) % DENSITY_OPTIONS.length;
      const container = panelRef.current?.querySelector(
        "[role='radiogroup'][aria-label='Density']",
      );
      const buttons = container?.querySelectorAll<HTMLButtonElement>("[role='radio']");
      buttons?.[next]?.focus();
    },
    [],
  );

  const handleNavigateToSection = useCallback(
    (sectionId: string) => {
      onClose();
      navigate(`/settings#${sectionId}`);
    },
    [navigate, onClose],
  );

  const handleOpenFullSettings = useCallback(() => {
    onClose();
    navigate("/settings");
  }, [navigate, onClose]);

  // When anchorRect is provided (portal mode) use fixed positioning so the panel
  // escapes any parent stacking context. Otherwise fall back to absolute (legacy).
  const positionStyle: React.CSSProperties = anchorRect
    ? {
        position: "fixed",
        top: anchorRect.bottom + 4,
        right: window.innerWidth - anchorRect.right,
      }
    : {
        position: "absolute",
        right: 0,
        top: "2.25rem", // 36px — same as the original top-9
      };

  return (
    <motion.div
      ref={panelRef}
      role="dialog"
      aria-label="Quick settings"
      aria-modal="false"
      className={cn(
        layerClassNames.floatingPanel,
        "w-80 rounded-xl shadow-2xl overflow-hidden",
      )}
      style={{
        ...positionStyle,
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        backgroundColor: "color-mix(in srgb, var(--color-card) 85%, transparent)",
        border: "1px solid var(--glass-l2-border, var(--color-border-default))",
      }}
      variants={motionConfig.variants.scaleIn}
      initial="initial"
      animate="animate"
      exit="exit"
      onKeyDown={handleKeyDown}
      onBlur={(e) => {
        // Close when focus moves entirely outside the panel
        if (!e.currentTarget.contains(e.relatedTarget as Node)) {
          onClose();
        }
      }}
    >
      {/* Screen reader announcement on open */}
      <span className="sr-only" aria-live="polite" role="status">
        Quick settings panel opened
      </span>

      {/* Green top-edge glow */}
      <div
        className="h-px w-full"
        style={{
          background:
            "linear-gradient(90deg, transparent, rgba(34,197,94,0.4), transparent)",
        }}
        aria-hidden="true"
      />

      <div className="p-4 space-y-4 max-h-[calc(100vh-60px)] overflow-y-auto">

        {/* ------------------------------------------------------------------ */}
        {/* Header                                                               */}
        {/* ------------------------------------------------------------------ */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Settings className="h-3.5 w-3.5 text-text-secondary" aria-hidden="true" />
            <span className="text-sm font-heading font-semibold text-text-primary">
              Settings
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 w-6 p-0 text-text-muted hover:text-text-primary"
            onClick={onClose}
            aria-label="Close quick settings"
          >
            <X className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Connection status card                                               */}
        {/* ------------------------------------------------------------------ */}
        <ConnectionCard connected={connected} practiceMode={isPractice} wsFailure={wsFailure ?? null} />

        {/* ------------------------------------------------------------------ */}
        {/* Dark / Light / System mode segment                                   */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-1.5">
          <span className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Mode
          </span>
          <div className="flex gap-1.5" role="group" aria-label="Colour mode">
            {(["dark", "light", "system"] as ColorMode[]).map((m, i) => (
              <ModeButton
                key={m}
                ref={i === 0 ? firstModeButtonRef : undefined}
                mode={m}
                active={mode === m}
                onClick={() => setMode(m)}
              />
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Theme dots — radiogroup with arrow key navigation                    */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-1.5">
          <span className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Theme
          </span>
          <div
            role="radiogroup"
            aria-label="Theme"
            className="flex items-center gap-2"
          >
            {THEME_DOTS.map((dot, index) => (
              <button
                key={dot.id}
                type="button"
                role="radio"
                aria-checked={activeThemeId === dot.id}
                aria-label={dot.label}
                onClick={() => setTheme(dot.id)}
                onKeyDown={(e) => handleThemeDotKeyDown(e, index)}
                tabIndex={
                  activeThemeId === dot.id ||
                  (index === 0 &&
                    !THEME_DOTS.some((d) => d.id === activeThemeId))
                    ? 0
                    : -1
                }
                className={cn(
                  "relative h-6 w-6 rounded-full transition-[transform,colors] duration-150",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1",
                  "focus-visible:ring-accent/50",
                  activeThemeId === dot.id
                    ? "ring-2 ring-offset-1 ring-accent/50 scale-110"
                    : "opacity-70 hover:opacity-100 hover:scale-105",
                )}
                style={{ backgroundColor: dot.color }}
              >
                {activeThemeId === dot.id && (
                  <Check
                    className="absolute inset-0 m-auto h-3 w-3 text-white drop-shadow"
                    aria-hidden="true"
                  />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Density segment — radiogroup                                         */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-1.5">
          <span className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Density
          </span>
          <div
            role="radiogroup"
            aria-label="Density"
            className="flex rounded-md overflow-hidden border border-border-default"
          >
            {DENSITY_OPTIONS.map((d, index) => (
              <button
                key={d}
                type="button"
                role="radio"
                aria-checked={density === d}
                tabIndex={density === d ? 0 : -1}
                onClick={() => setDensity(d)}
                onKeyDown={(e) => handleDensityKeyDown(e, index)}
                className={cn(
                  "flex-1 py-1.5 text-xs font-medium transition-colors capitalize",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/50",
                  density === d
                    ? "bg-accent/20 text-accent"
                    : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
                )}
              >
                {d}
              </button>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Trading mode (read-only — switch from the TopBar mode pill)          */}
        {/* ------------------------------------------------------------------ */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <span className="text-xs font-medium text-text-primary">Trading Mode</span>
            <p className="text-[10px] text-text-muted leading-snug">
              Switch from the mode pill in the top bar
            </p>
          </div>
          <span
            className={cn("text-xs font-semibold font-heading", MODE_LABEL[appMode].className)}
            aria-label={`Current trading mode: ${MODE_LABEL[appMode].text}`}
          >
            {MODE_LABEL[appMode].text}
          </span>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Section shortcuts — 3x2 grid                                         */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-1.5">
          <span className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Jump to
          </span>
          <div className="grid grid-cols-3 gap-1.5">
            {SECTION_SHORTCUTS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => handleNavigateToSection(id)}
                className={cn(
                  "flex flex-col items-center gap-1 py-2 px-1 rounded-md text-xs",
                  "text-text-secondary hover:text-text-primary hover:bg-surface-hover",
                  "transition-colors border border-transparent hover:border-border-default",
                )}
                aria-label={`Go to ${label} settings`}
              >
                <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                <span className="text-[10px]">{label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* ------------------------------------------------------------------ */}
        {/* Shimmer CTA                                                           */}
        {/* ------------------------------------------------------------------ */}
        <ShimmerButton
          className="w-full text-xs py-2"
          onClick={handleOpenFullSettings}
        >
          <Settings className="h-3.5 w-3.5" aria-hidden="true" />
          Open Full Settings
        </ShimmerButton>
      </div>
    </motion.div>
  );
}
