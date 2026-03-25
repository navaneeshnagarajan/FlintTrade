/**
 * ThemePicker.tsx
 *
 * Theme selection grid and custom theme builder for AppearanceSection.
 * Phase C: migrated from FlintTradeTheme to CinematicTheme.
 *
 * Sections:
 *   1. Built-in theme grid — icon + name + description + dark/light accent dots
 *   2. Custom builder (collapsible) — dark + light variant color editors
 *   3. Import / Export — JSON clipboard round-trip for CinematicTheme
 */

import { useState, useCallback, type ChangeEvent } from "react";
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
  type LucideProps,
} from "lucide-react";
import type { ForwardRefExoticComponent, RefAttributes } from "react";
import { useThemeStore } from "@/stores/themeStore";
import {
  CINEMATIC_THEMES,
  type CinematicTheme,
  type ThemeVariant,
} from "@/lib/cinematicThemes";

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

// ---------------------------------------------------------------------------
// Sub-component: ThemeCard
// ---------------------------------------------------------------------------

interface ThemeCardProps {
  theme: CinematicTheme;
  isActive: boolean;
  onSelect: () => void;
}

function ThemeCard({ theme, isActive, onSelect }: ThemeCardProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={theme.name}
      aria-pressed={isActive}
      className={`group relative flex flex-col gap-2 p-3 rounded-lg border transition-all text-left ${
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
  const [darkVariant,  setDarkVariant]  = useState<ThemeVariant>(() => ({ ...DEFAULT_DARK_VARIANT, colors: { ...DEFAULT_DARK_VARIANT.colors } }));
  const [lightVariant, setLightVariant] = useState<ThemeVariant>(() => ({ ...DEFAULT_LIGHT_VARIANT, colors: { ...DEFAULT_LIGHT_VARIANT.colors } }));
  const [editingVariant, setEditingVariant] = useState<"dark" | "light">("dark");

  // --- Import/Export state ---
  const [importText,  setImportText]  = useState("");
  const [importError, setImportError] = useState("");
  const [copied,      setCopied]      = useState(false);

  // All themes (built-in + custom)
  const allThemes: CinematicTheme[] = [...CINEMATIC_THEMES, ...customThemes];

  // The currently-edited variant object
  const currentVariant = editingVariant === "dark" ? darkVariant : lightVariant;
  const setCurrentVariant = editingVariant === "dark" ? setDarkVariant : setLightVariant;

  // --- Color updater for current variant ---
  const updateColor = useCallback(
    (key: keyof ThemeVariant["colors"], val: string) => {
      setCurrentVariant((prev) => ({
        ...prev,
        colors: { ...prev.colors, [key]: val },
      }));
    },
    [setCurrentVariant],
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

  // --- Import ---
  function handleImport() {
    setImportError("");
    try {
      const parsed = JSON.parse(importText) as unknown;
      if (
        typeof parsed !== "object" ||
        parsed === null ||
        !("id" in parsed) ||
        !("name" in parsed) ||
        !("dark" in parsed) ||
        !("light" in parsed)
      ) {
        setImportError("Invalid CinematicTheme JSON — must have id, name, dark, and light fields.");
        return;
      }
      const theme = parsed as CinematicTheme;
      const importedTheme: CinematicTheme = {
        ...theme,
        id: theme.id.startsWith("custom-") ? theme.id : `custom-${theme.id}`,
      };
      addCustomTheme(importedTheme);
      setTheme(importedTheme.id);
      setImportText("");
    } catch {
      setImportError("Could not parse JSON. Check formatting and try again.");
    }
  }

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

            {/* Variant selector (dark / light) */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Editing variant</p>
              <div className="flex items-center gap-1 p-0.5 rounded-md border border-border-default bg-surface-base w-fit">
                {(["dark", "light"] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => setEditingVariant(v)}
                    className={`px-3 py-1 text-xs rounded transition-colors ${
                      editingVariant === v
                        ? "bg-accent/15 text-accent border border-accent/20"
                        : "text-text-muted hover:text-text-primary"
                    }`}
                  >
                    {v === "dark" ? "Dark" : "Light"}
                  </button>
                ))}
              </div>
            </div>

            {/* Colors grid for current variant */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">
                {editingVariant === "dark" ? "Dark" : "Light"} variant colors
              </p>
              <div className="grid grid-cols-2 gap-3">
                <ColorField label="Base"           value={currentVariant.colors.base}          onChange={(v) => updateColor("base",          v)} />
                <ColorField label="Card"           value={currentVariant.colors.card}          onChange={(v) => updateColor("card",          v)} />
                <ColorField label="Accent"         value={currentVariant.colors.accent}        onChange={(v) => updateColor("accent",        v)} />
                <ColorField label="Accent text"    value={currentVariant.colors.accentText}    onChange={(v) => updateColor("accentText",    v)} />
                <ColorField label="Border"         value={currentVariant.colors.border}        onChange={(v) => updateColor("border",        v)} />
                <ColorField label="Text"           value={currentVariant.colors.text}          onChange={(v) => updateColor("text",          v)} />
                <ColorField label="Text muted"     value={currentVariant.colors.textMuted}     onChange={(v) => updateColor("textMuted",     v)} />
                <ColorField label="Text secondary" value={currentVariant.colors.textSecondary} onChange={(v) => updateColor("textSecondary", v)} />
              </div>
            </div>

            {/* Live preview */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Preview ({editingVariant})</p>
              <div
                className="rounded-lg border p-3 space-y-2"
                style={{ backgroundColor: currentVariant.colors.card, borderColor: currentVariant.colors.border }}
              >
                <div className="flex items-center justify-between">
                  <span style={{ color: currentVariant.colors.text, fontSize: "11px", fontWeight: 600 }}>
                    Preview
                  </span>
                  <span style={{ color: currentVariant.colors.accent, fontSize: "10px" }}>Active</span>
                </div>
                <div className="flex items-center gap-2">
                  <div
                    className="rounded px-2 py-0.5 text-[10px] font-mono"
                    style={{
                      backgroundColor: `${currentVariant.colors.accent}22`,
                      color:            currentVariant.colors.accent,
                      border:          `1px solid ${currentVariant.colors.accent}44`,
                    }}
                  >
                    +1.42%
                  </div>
                  <div
                    className="rounded px-2 py-0.5 text-[10px] font-mono"
                    style={{
                      backgroundColor: "rgba(239,68,68,0.13)",
                      color:           "#ef4444",
                      border:          "1px solid rgba(239,68,68,0.27)",
                    }}
                  >
                    -0.68%
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  {[
                    currentVariant.colors.base,
                    currentVariant.colors.card,
                    currentVariant.colors.accent,
                    "#22c55e",
                    "#ef4444",
                    currentVariant.colors.border,
                  ].map((c, i) => (
                    <div
                      key={i}
                      className="h-3 w-3 rounded-sm border border-black/10"
                      style={{ backgroundColor: c }}
                    />
                  ))}
                </div>
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
              placeholder="Paste CinematicTheme JSON here…"
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
