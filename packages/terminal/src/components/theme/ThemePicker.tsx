/**
 * ThemePicker.tsx
 *
 * Theme selection grid and custom theme builder for AppearanceSection.
 * Phase C: migrated from FlintTradeTheme to CinematicTheme.
 * Phase H: enhanced with contrast validation, dark/light split preview,
 *           stricter import validation, and hover-preview on preset cards.
 *
 * Sections:
 *   1. Built-in theme grid — icon + name + description + dark/light accent dots
 *      Hover-preview: temporarily applies hovered theme's CSS vars.
 *   2. Custom builder (collapsible) — dark + light variant color editors
 *      WCAG AA contrast indicators per accent/base pair.
 *      Dark/Light split preview cards shown side by side.
 *   3. Import / Export — JSON clipboard round-trip for CinematicTheme
 *      Import validates that both "dark" and "light" variant fields exist.
 */

import {
  useState,
  useCallback,
  useRef,
  type ChangeEvent,
  type MouseEvent,
} from "react";
import {
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  Upload,
  Palette,
  Leaf,
  Waves,
  Sun,
  Zap,
  Snowflake,
  Moon,
  ShieldCheck,
  ShieldX,
  type LucideProps,
} from "lucide-react";
import type { ForwardRefExoticComponent, RefAttributes } from "react";
import { useThemeStore } from "@/stores/themeStore";
import {
  CINEMATIC_THEMES,
  type CinematicTheme,
  type ThemeVariant,
} from "@/lib/cinematicThemes";
import { evaluateContrast, type ContrastResult } from "@/lib/contrastUtils";

// ---------------------------------------------------------------------------
// Icon resolver — maps theme.icon string to a Lucide component
// ---------------------------------------------------------------------------

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, "ref"> & RefAttributes<SVGSVGElement>>;

const ICON_MAP: Record<string, LucideIcon> = {
  leaf:      Leaf,
  waves:     Waves,
  sun:       Sun,
  zap:       Zap,
  snowflake: Snowflake,
  moon:      Moon,
};

function ThemeIcon({ name, size = 16, className }: { name: string; size?: number; className?: string }) {
  const Icon = (ICON_MAP[name] ?? Palette) as LucideIcon;
  return <Icon size={size} className={className} aria-hidden />;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCustomId(): string {
  return `custom-${Date.now()}`;
}

/** Build a minimal CinematicTheme from partial variant overrides. */
function buildCustomTheme(
  id: string,
  name: string,
  dark: ThemeVariant,
  light: ThemeVariant,
): CinematicTheme {
  return {
    id,
    name,
    description: "Custom theme",
    icon: "palette",
    dark,
    light,
    shared: {
      profit: "#22c55e",
      loss:   "#ef4444",
      shimmer: { speed: "2.4s" },
      particles: {
        quantity:  40,
        sizeRange: [1, 3],
        behavior:  "drift",
      },
    },
  };
}

/**
 * Validate that a parsed JSON value has the minimum shape of a CinematicTheme:
 * an object with id (string), name (string), dark (object), and light (object).
 */
function isCinematicThemeShape(value: unknown): value is CinematicTheme {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v["id"] === "string" &&
    typeof v["name"] === "string" &&
    typeof v["dark"] === "object" && v["dark"] !== null &&
    typeof v["light"] === "object" && v["light"] !== null
  );
}

// ---------------------------------------------------------------------------
// Sub-component: ContrastBadge
// Displays a WCAG AA pass/fail indicator with the numeric ratio.
// ---------------------------------------------------------------------------

interface ContrastBadgeProps {
  fg: string;
  bg: string;
  label: string;
}

function ContrastBadge({ fg, bg, label }: ContrastBadgeProps) {
  const result: ContrastResult = evaluateContrast(fg, bg);

  return (
    <div
      className="flex items-center gap-1"
      title={`${label}: ${result.ratio}:1 — ${result.label}`}
    >
      <span className="text-[9px] text-text-muted">{label}</span>
      {result.passes ? (
        <ShieldCheck
          size={10}
          className="text-profit shrink-0"
          aria-label={`${label} passes WCAG AA (${result.ratio}:1)`}
        />
      ) : (
        <ShieldX
          size={10}
          className="text-loss shrink-0"
          aria-label={`${label} fails WCAG AA (${result.ratio}:1)`}
        />
      )}
      <span
        className={`text-[9px] font-mono ${result.passes ? "text-profit" : "text-loss"}`}
      >
        {result.ratio}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: VariantPreviewCard
// Shows a compact visual preview for one ThemeVariant (dark OR light).
// ---------------------------------------------------------------------------

interface VariantPreviewCardProps {
  variant: ThemeVariant;
  mode: "dark" | "light";
}

function VariantPreviewCard({ variant, mode }: VariantPreviewCardProps) {
  const { colors } = variant;
  const glassStyle: React.CSSProperties = {
    backgroundColor: variant.glass.tint,
    border: `1px solid ${colors.accent}${Math.round(variant.glass.borderAlpha * 255).toString(16).padStart(2, "0")}`,
  };

  return (
    <div
      className="rounded-lg border p-3 space-y-2 flex-1 min-w-0"
      style={{ backgroundColor: colors.base, borderColor: colors.border }}
      aria-label={`${mode} variant preview`}
    >
      {/* Mode label */}
      <div className="flex items-center justify-between">
        <span
          className="text-[9px] uppercase tracking-widest font-medium"
          style={{ color: colors.textMuted }}
        >
          {mode}
        </span>
        <div
          className="h-1.5 w-1.5 rounded-full"
          style={{ backgroundColor: colors.accent }}
        />
      </div>

      {/* Sample card */}
      <div
        className="rounded p-2 space-y-1.5"
        style={{ backgroundColor: colors.card, borderColor: colors.border, border: `1px solid ${colors.border}` }}
      >
        {/* Primary + muted text */}
        <div
          className="text-[10px] font-semibold leading-none"
          style={{ color: colors.text }}
        >
          NIFTY 25,150.00
        </div>
        <div
          className="text-[9px] leading-none"
          style={{ color: colors.textMuted }}
        >
          Last updated 09:30 IST
        </div>

        {/* Accent-colored element */}
        <div
          className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono"
          style={{
            backgroundColor: `${colors.accent}22`,
            color:            colors.accent,
            border:           `1px solid ${colors.accent}44`,
          }}
        >
          +1.42%
        </div>
      </div>

      {/* Glass morphism strip */}
      <div
        className="rounded px-2 py-1 text-[9px]"
        style={{ ...glassStyle, color: colors.textSecondary }}
      >
        Glass surface
      </div>

      {/* Color swatch strip */}
      <div className="flex items-center gap-1">
        {[
          colors.base,
          colors.card,
          colors.accent,
          colors.text,
          colors.border,
        ].map((c, i) => (
          <div
            key={i}
            className="h-2 flex-1 rounded-sm"
            style={{ backgroundColor: c }}
          />
        ))}
      </div>

      {/* Contrast indicator for the key pair: accent on base */}
      <ContrastBadge fg={colors.accent} bg={colors.base} label="accent/base" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: ThemeCard
// Supports hover-preview: temporarily apply the hovered theme's CSS vars.
// ---------------------------------------------------------------------------

interface ThemeCardProps {
  theme: CinematicTheme;
  isActive: boolean;
  onSelect: () => void;
}

function ThemeCard({ theme, isActive, onSelect }: ThemeCardProps) {
  const previewActive = useRef(false);

  function handleMouseEnter(_e: MouseEvent<HTMLButtonElement>) {
    previewActive.current = true;
    // Temporarily apply this theme's CSS vars without persisting to store state.
    // We do this by grabbing the store's applyTheme mechanism but swapping the
    // active theme id for the preview id only in the DOM, then restoring it.
    const store = useThemeStore.getState();
    const previousId = store.activeThemeId;

    // Only preview if this isn't already the active theme
    if (theme.id === previousId) return;

    // Temporarily write the preview theme's vars to document
    store.setTheme(theme.id);

    // Stash the previous id so we can restore on leave
    (handleMouseEnter as { _prevId?: string })._prevId = previousId;
  }

  function handleMouseLeave(_e: MouseEvent<HTMLButtonElement>) {
    if (!previewActive.current) return;
    previewActive.current = false;

    const prevId = (handleMouseEnter as { _prevId?: string })._prevId;
    if (prevId) {
      // Restore the previously active theme
      useThemeStore.getState().setTheme(prevId);
      (handleMouseEnter as { _prevId?: string })._prevId = undefined;
    }
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      aria-label={theme.name}
      aria-pressed={isActive}
      className={`group relative flex flex-col gap-2 p-3 rounded-lg border transition-colors text-left ${
        isActive
          ? "border-accent bg-accent/10 ring-1 ring-accent/20"
          : "border-border-default bg-surface-card hover:bg-surface-hover hover:border-border-strong"
      }`}
    >
      {/* Icon + accent dots row */}
      <div className="flex items-center justify-between">
        <ThemeIcon
          name={theme.icon}
          size={14}
          className={isActive ? "text-accent" : "text-text-muted"}
        />
        {/* Dark + Light accent dots */}
        <div className="flex items-center gap-1">
          <div
            title={`Dark accent: ${theme.dark.colors.accent}`}
            className="h-2.5 w-2.5 rounded-full border border-black/10 shrink-0"
            style={{ backgroundColor: theme.dark.colors.accent }}
          />
          <div
            title={`Light accent: ${theme.light.colors.accent}`}
            className="h-2.5 w-2.5 rounded-full border border-black/10 shrink-0"
            style={{ backgroundColor: theme.light.colors.accent }}
          />
        </div>
      </div>

      {/* Name + description */}
      <div>
        <div className="text-xs font-heading font-semibold text-text-primary leading-tight">
          {theme.name}
        </div>
        <div className="text-[10px] text-text-muted mt-0.5 leading-snug line-clamp-2">
          {theme.description}
        </div>
      </div>

      {isActive && (
        <div className="absolute top-1.5 right-1.5">
          <Check size={10} className="text-accent" />
        </div>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: ColorField
// ---------------------------------------------------------------------------

interface ColorFieldProps {
  label: string;
  value: string;
  onChange: (val: string) => void;
}

function ColorField({ label, value, onChange }: ColorFieldProps) {
  const safeHex = value.startsWith("#") && value.length === 7 ? value : "#000000";

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] text-text-muted uppercase tracking-wide">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          type="color"
          value={safeHex}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          className="h-7 w-7 rounded border border-border-default cursor-pointer bg-transparent p-0.5"
          title={label}
          aria-label={`${label} color picker`}
        />
        <input
          type="text"
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          className="flex-1 min-w-0 px-2 py-1 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60"
          spellCheck={false}
          aria-label={`${label} hex value`}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default custom-builder variant state (based on emerald-night)
// ---------------------------------------------------------------------------

const DEFAULT_DARK_VARIANT: ThemeVariant = {
  colors: {
    base:          "#0a0a0f",
    card:          "#13151a",
    cardHover:     "#1c1f27",
    border:        "#1e2430",
    text:          "#e2ffe8",
    textMuted:     "#5a7a66",
    textSecondary: "#8ab89a",
    accent:        "#22c55e",
    accentText:    "#0a0a0f",
  },
  particles: { colors: ["#22c55e", "#16a34a", "#4ade80"], opacity: 0.55 },
  glass: { tint: "rgba(10,10,15,0.75)", blur: 12, borderAlpha: 0.18, minOpacity: 0.60 },
  glow:  { color: "rgba(34,197,94,0.15)", opacity: 0.15, radius: 24 },
  shimmerColor: "rgba(34,197,94,0.08)",
};

const DEFAULT_LIGHT_VARIANT: ThemeVariant = {
  colors: {
    base:          "#f8faf9",
    card:          "#ffffff",
    cardHover:     "#edf7f1",
    border:        "#cce8d6",
    text:          "#0f2318",
    textMuted:     "#6a907a",
    textSecondary: "#3d6b52",
    accent:        "#15803d",
    accentText:    "#ffffff",
  },
  particles: { colors: ["#15803d", "#16a34a", "#4ade80"], opacity: 0.35 },
  glass: { tint: "rgba(248,250,249,0.80)", blur: 10, borderAlpha: 0.20, minOpacity: 0.70 },
  glow:  { color: "rgba(21,128,61,0.10)", opacity: 0.10, radius: 20 },
  shimmerColor: "rgba(21,128,61,0.06)",
};

// ---------------------------------------------------------------------------
// Main component: ThemePicker
// ---------------------------------------------------------------------------

export function ThemePicker() {
  const { activeThemeId, customThemes, setTheme, addCustomTheme } = useThemeStore();

  // --- Custom builder state ---
  const [builderOpen, setBuilderOpen] = useState(false);
  const [customName,  setCustomName]  = useState("My Theme");
  const [darkVariant,  setDarkVariant]  = useState<ThemeVariant>(() => ({
    ...DEFAULT_DARK_VARIANT,
    colors: { ...DEFAULT_DARK_VARIANT.colors },
  }));
  const [lightVariant, setLightVariant] = useState<ThemeVariant>(() => ({
    ...DEFAULT_LIGHT_VARIANT,
    colors: { ...DEFAULT_LIGHT_VARIANT.colors },
  }));

  // --- Import/Export state ---
  const [importText,  setImportText]  = useState("");
  const [importError, setImportError] = useState("");
  const [copied,      setCopied]      = useState(false);

  // All themes (built-in + custom)
  const allThemes: CinematicTheme[] = [...CINEMATIC_THEMES, ...customThemes];

  // --- Color updater for dark variant ---
  const updateDarkColor = useCallback(
    (key: keyof ThemeVariant["colors"], val: string) => {
      setDarkVariant((prev) => ({
        ...prev,
        colors: { ...prev.colors, [key]: val },
      }));
    },
    [],
  );

  // --- Color updater for light variant ---
  const updateLightColor = useCallback(
    (key: keyof ThemeVariant["colors"], val: string) => {
      setLightVariant((prev) => ({
        ...prev,
        colors: { ...prev.colors, [key]: val },
      }));
    },
    [],
  );

  // --- Apply custom theme ---
  function handleApplyCustom() {
    const id = makeCustomId();
    const theme = buildCustomTheme(id, customName || "Custom", darkVariant, lightVariant);
    addCustomTheme(theme);
    setTheme(id);
  }

  // --- Export ---
  async function handleExport() {
    const store = useThemeStore.getState();
    const theme = store.getActiveTheme();
    const json = JSON.stringify(theme, null, 2);
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — silent fail
    }
  }

  // --- Import (validates CinematicTheme shape: must have dark + light) ---
  function handleImport() {
    setImportError("");
    try {
      const parsed = JSON.parse(importText) as unknown;
      if (!isCinematicThemeShape(parsed)) {
        setImportError(
          "Invalid CinematicTheme JSON — must have id (string), name (string), dark (object), and light (object) fields.",
        );
        return;
      }
      const importedTheme: CinematicTheme = {
        ...parsed,
        id: parsed.id.startsWith("custom-") ? parsed.id : `custom-${parsed.id}`,
      };
      addCustomTheme(importedTheme);
      setTheme(importedTheme.id);
      setImportText("");
    } catch {
      setImportError("Could not parse JSON. Check formatting and try again.");
    }
  }

  // --- Contrast summary for the builder ---
  // Show a compact panel with accent-on-base and text-on-base checks for
  // both dark and light variants simultaneously.
  const contrastPairs: Array<{ fg: string; bg: string; label: string; variant: "dark" | "light" }> = [
    { fg: darkVariant.colors.accent,  bg: darkVariant.colors.base, label: "accent/base", variant: "dark" },
    { fg: darkVariant.colors.text,    bg: darkVariant.colors.base, label: "text/base",   variant: "dark" },
    { fg: lightVariant.colors.accent, bg: lightVariant.colors.base, label: "accent/base", variant: "light" },
    { fg: lightVariant.colors.text,   bg: lightVariant.colors.base, label: "text/base",   variant: "light" },
  ];

  return (
    <div className="space-y-5">

      {/* ---- Theme grid ---- */}
      <div className="grid grid-cols-3 gap-2">
        {allThemes.map((theme) => (
          <ThemeCard
            key={theme.id}
            theme={theme}
            isActive={theme.id === activeThemeId}
            onSelect={() => setTheme(theme.id)}
          />
        ))}
      </div>

      {/* ---- Custom builder ---- */}
      <div className="rounded-lg border border-border-default overflow-hidden">
        <button
          type="button"
          onClick={() => setBuilderOpen((p) => !p)}
          className="w-full flex items-center justify-between px-4 py-2.5 bg-surface-card hover:bg-surface-hover transition-colors text-left"
        >
          <div className="flex items-center gap-2">
            <Palette size={13} className="text-accent" />
            <span className="text-xs font-medium text-text-primary">Custom Theme Builder</span>
          </div>
          {builderOpen ? (
            <ChevronUp size={13} className="text-text-muted" />
          ) : (
            <ChevronDown size={13} className="text-text-muted" />
          )}
        </button>

        {builderOpen && (
          <div className="p-4 space-y-5 border-t border-border-default">

            {/* Theme name */}
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-text-muted uppercase tracking-wide">Theme name</span>
              <input
                type="text"
                value={customName}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setCustomName(e.target.value)}
                placeholder="My Theme"
                className="w-full max-w-48 px-3 py-1.5 text-xs bg-surface-base border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60"
              />
            </div>

            {/* --- Dark variant color editor --- */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">
                Dark variant colors
              </p>
              <div className="grid grid-cols-2 gap-3">
                <ColorField label="Base"           value={darkVariant.colors.base}          onChange={(v) => updateDarkColor("base",          v)} />
                <ColorField label="Card"           value={darkVariant.colors.card}          onChange={(v) => updateDarkColor("card",          v)} />
                <ColorField label="Accent"         value={darkVariant.colors.accent}        onChange={(v) => updateDarkColor("accent",        v)} />
                <ColorField label="Accent text"    value={darkVariant.colors.accentText}    onChange={(v) => updateDarkColor("accentText",    v)} />
                <ColorField label="Border"         value={darkVariant.colors.border}        onChange={(v) => updateDarkColor("border",        v)} />
                <ColorField label="Text"           value={darkVariant.colors.text}          onChange={(v) => updateDarkColor("text",          v)} />
                <ColorField label="Text muted"     value={darkVariant.colors.textMuted}     onChange={(v) => updateDarkColor("textMuted",     v)} />
                <ColorField label="Text secondary" value={darkVariant.colors.textSecondary} onChange={(v) => updateDarkColor("textSecondary", v)} />
              </div>
            </div>

            {/* --- Light variant color editor --- */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">
                Light variant colors
              </p>
              <div className="grid grid-cols-2 gap-3">
                <ColorField label="Base"           value={lightVariant.colors.base}          onChange={(v) => updateLightColor("base",          v)} />
                <ColorField label="Card"           value={lightVariant.colors.card}          onChange={(v) => updateLightColor("card",          v)} />
                <ColorField label="Accent"         value={lightVariant.colors.accent}        onChange={(v) => updateLightColor("accent",        v)} />
                <ColorField label="Accent text"    value={lightVariant.colors.accentText}    onChange={(v) => updateLightColor("accentText",    v)} />
                <ColorField label="Border"         value={lightVariant.colors.border}        onChange={(v) => updateLightColor("border",        v)} />
                <ColorField label="Text"           value={lightVariant.colors.text}          onChange={(v) => updateLightColor("text",          v)} />
                <ColorField label="Text muted"     value={lightVariant.colors.textMuted}     onChange={(v) => updateLightColor("textMuted",     v)} />
                <ColorField label="Text secondary" value={lightVariant.colors.textSecondary} onChange={(v) => updateLightColor("textSecondary", v)} />
              </div>
            </div>

            {/* --- WCAG AA contrast checker --- */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">
                WCAG AA contrast check
              </p>
              <div className="rounded-lg border border-border-default bg-surface-base p-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
                {contrastPairs.map((pair) => {
                  const result = evaluateContrast(pair.fg, pair.bg);
                  return (
                    <div
                      key={`${pair.variant}-${pair.label}`}
                      className="flex items-center justify-between gap-2"
                    >
                      <span className="text-[9px] text-text-muted capitalize">
                        {pair.variant} {pair.label}
                      </span>
                      <div className="flex items-center gap-1">
                        {result.passes ? (
                          <ShieldCheck size={10} className="text-profit shrink-0" aria-label="passes AA" />
                        ) : (
                          <ShieldX size={10} className="text-loss shrink-0" aria-label="fails AA" />
                        )}
                        <span
                          className={`text-[9px] font-mono ${result.passes ? "text-profit" : "text-loss"}`}
                        >
                          {result.ratio}:1
                        </span>
                        <span
                          className={`text-[9px] ${result.passes ? "text-profit" : "text-loss"}`}
                        >
                          {result.label}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* --- Dark / Light split preview --- */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">
                Preview — dark / light
              </p>
              <div className="flex gap-2">
                <VariantPreviewCard variant={darkVariant}  mode="dark"  />
                <VariantPreviewCard variant={lightVariant} mode="light" />
              </div>
            </div>

            {/* Apply button */}
            <button
              type="button"
              onClick={handleApplyCustom}
              className="flex items-center gap-2 px-4 py-1.5 text-xs font-medium rounded bg-accent/10 border border-accent/30 text-accent hover:bg-accent/20 hover:border-accent/50 transition-colors"
            >
              <Palette size={12} />
              Apply Custom Theme
            </button>
          </div>
        )}
      </div>

      {/* ---- Import / Export ---- */}
      <div className="rounded-lg border border-border-default overflow-hidden">
        <div className="px-4 py-2.5 bg-surface-card border-b border-border-default">
          <span className="text-xs font-medium text-text-primary">Import / Export</span>
        </div>
        <div className="p-4 space-y-3">

          {/* Export */}
          <button
            type="button"
            onClick={() => void handleExport()}
            className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors"
          >
            {copied ? (
              <Check size={12} className="text-profit" />
            ) : (
              <Copy size={12} />
            )}
            {copied ? "Copied to clipboard" : "Export Active Theme as JSON"}
          </button>

          {/* Import */}
          <div className="space-y-1.5">
            <textarea
              value={importText}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => {
                setImportText(e.target.value);
                setImportError("");
              }}
              placeholder="Paste CinematicTheme JSON here — must have id, name, dark, and light fields."
              rows={4}
              spellCheck={false}
              className="w-full px-3 py-2 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60 resize-none"
            />
            {importError && (
              <p className="text-[11px] text-loss">{importError}</p>
            )}
            <button
              type="button"
              onClick={handleImport}
              disabled={!importText.trim()}
              className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Upload size={12} />
              Import &amp; Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
