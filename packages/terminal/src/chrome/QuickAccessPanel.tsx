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
  Info,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ShimmerButton } from "@/components/magicui/shimmer-button";
import { useConnectionStore } from "@/stores/connectionStore";
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

const THEME_DOTS = [
  { id: "emerald", label: "Emerald", color: "#22c55e" },
  { id: "sky", label: "Sky", color: "#38bdf8" },
  { id: "orange", label: "Orange", color: "#fb923c" },
  { id: "violet", label: "Violet", color: "#a855f7" },
  { id: "slate", label: "Slate", color: "#94a3b8" },
  { id: "red", label: "Red", color: "#dc2626" },
] as const;

// ---------------------------------------------------------------------------
// Section shortcuts config
// ---------------------------------------------------------------------------

const DENSITY_OPTIONS = ["compact", "comfortable"] as const;

const SECTION_SHORTCUTS = [
  { id: "api", label: "API", icon: Wifi },
  { id: "risk", label: "Risk", icon: ShieldAlert },
  { id: "llm", label: "LLM", icon: Brain },
  { id: "telegram", label: "Telegram", icon: Send },
  { id: "trading", label: "Trading", icon: TrendingUp },
  { id: "about", label: "About", icon: Info },
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
  sandboxMode: boolean;
}

function ConnectionCard({ connected, sandboxMode }: ConnectionCardProps) {
  return (
    <div
      className="flex items-center justify-between p-2.5 rounded-lg border border-border-default"
      style={{ backgroundColor: "rgba(255,255,255,0.03)" }}
    >
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
          {connected ? "Connected" : "Disconnected"}
        </span>
      </div>
      {sandboxMode && (
        <Badge
          variant="outline"
          className="text-[10px] px-1.5 py-0 border-amber-500/50 text-amber-400 bg-amber-500/10"
        >
          SANDBOX
        </Badge>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sandbox toggle switch
// ---------------------------------------------------------------------------

interface SandboxSwitchProps {
  enabled: boolean;
  onToggle: () => void;
}

function SandboxSwitch({ enabled, onToggle }: SandboxSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label="Toggle sandbox mode"
      onClick={onToggle}
      className={cn(
        "relative inline-flex h-5 w-9 cursor-pointer items-center rounded-full",
        "transition-colors duration-200 focus:outline-none",
        "focus-visible:ring-2 focus-visible:ring-accent/50",
        enabled ? "bg-accent" : "bg-surface-hover border border-border-default",
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform duration-200",
          enabled ? "translate-x-4" : "translate-x-0.5",
        )}
        aria-hidden="true"
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function QuickAccessPanel({ onClose, triggerRef, anchorRect }: QuickAccessPanelProps) {
  const navigate = useNavigate();
  const panelRef = useRef<HTMLDivElement>(null);
  const firstModeButtonRef = useRef<HTMLButtonElement>(null);

  // Connection state
  const status = useConnectionStore((s) => s.status);
  const connected = status === "connected";

  // Settings store
  const density = useSettingsStore((s) => s.density);
  const setDensity = useSettingsStore((s) => s.setDensity);
  const sandboxMode = useSettingsStore((s) => s.sandboxMode);
  const setSandboxMode = useSettingsStore((s) => s.setSandboxMode);

  // Theme store — active theme for dot selection
  const activeThemeId = useThemeStore((s) => s.activeThemeId);
  const setTheme = useThemeStore((s) => s.setTheme);

  // Phase B: mode/setMode do not exist in ThemeState yet.
  // Using type-cast fallback. Phase C will add these to the store.
  const mode = useThemeStore(
    (s) => (s as unknown as { mode?: ColorMode }).mode ?? "dark",
  );
  const setMode = useThemeStore(
    (s) =>
      (s as unknown as { setMode?: (m: ColorMode) => void }).setMode ??
      (() => { /* noop until Phase C */ }),
  );

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
      className="z-50 w-80 rounded-xl shadow-2xl overflow-hidden"
      style={{
        ...positionStyle,
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        backgroundColor: "rgba(22,22,31,0.85)",
        border: "1px solid rgba(255,255,255,0.08)",
      }}
      variants={motionConfig.variants.scaleIn}
      initial="initial"
      animate="animate"
      exit="exit"
      onKeyDown={handleKeyDown}
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
        <ConnectionCard connected={connected} sandboxMode={sandboxMode} />

        {/* ------------------------------------------------------------------ */}
        {/* Dark / Light / System mode segment                                   */}
        {/* ------------------------------------------------------------------ */}
        <div className="space-y-1.5">
          <span className="text-xs text-text-muted font-medium uppercase tracking-wider">
            Mode
          </span>
          <div className="flex gap-1.5" role="group" aria-label="Color mode">
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
                  "relative h-6 w-6 rounded-full transition-all duration-150",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1",
                  "focus-visible:ring-white/40",
                  activeThemeId === dot.id
                    ? "ring-2 ring-offset-1 ring-white/50 scale-110"
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
        {/* Sandbox toggle                                                        */}
        {/* ------------------------------------------------------------------ */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <span className="text-xs font-medium text-text-primary">Sandbox Mode</span>
            <p className="text-[10px] text-text-muted leading-snug">
              Paper trading, no real orders
            </p>
          </div>
          <SandboxSwitch
            enabled={sandboxMode}
            onToggle={() => setSandboxMode(!sandboxMode)}
          />
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
