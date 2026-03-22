/**
 * ThemePicker.tsx
 *
 * Theme selection grid and custom theme builder for the Appearance settings section.
 *
 * Sections:
 *   1. Built-in theme grid — 4-column cards with color swatches, click to apply
 *   2. Custom builder (collapsible) — color pickers, glass sliders, border radius
 *   3. Import / Export — JSON clipboard round-trip
 */

import { useState, useCallback, type ChangeEvent } from "react";
import { ChevronDown, ChevronUp, Copy, Check, Upload, Palette } from "lucide-react";
import { useThemeStore } from "@/stores/themeStore";
import { BUILTIN_THEMES } from "@/components/theme/themePresets";
import type { FlintTradeTheme } from "@/components/theme/themePresets";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Generate a stable custom-theme id from the current timestamp. */
function makeCustomId(): string {
  return `custom-${Date.now()}`;
}

/** Build a minimal valid FlintTradeTheme from partial color overrides. */
function buildCustomTheme(
  id: string,
  name: string,
  colors: FlintTradeTheme["colors"],
  effects: FlintTradeTheme["effects"],
): FlintTradeTheme {
  return {
    id,
    name,
    mode: "dark",
    colors,
    effects,
    background: {
      type: "solid",
      value: colors.background,
    },
  };
}

// ---------------------------------------------------------------------------
// Sub-component: ThemeCard
// ---------------------------------------------------------------------------

interface ThemeCardProps {
  theme: FlintTradeTheme;
  isActive: boolean;
  onSelect: () => void;
}

function ThemeCard({ theme, isActive, onSelect }: ThemeCardProps) {
  const swatches: Array<{ color: string; title: string }> = [
    { color: theme.colors.background, title: "Background" },
    { color: theme.colors.card,       title: "Card"       },
    { color: theme.colors.accent,     title: "Accent"     },
    { color: theme.colors.profit,     title: "Profit"     },
  ];

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`group relative flex flex-col gap-2 p-3 rounded-lg border transition-all text-left ${
        isActive
          ? "border-accent bg-accent/10 ring-1 ring-accent/20"
          : "border-border-default bg-surface-card hover:bg-surface-hover hover:border-border-strong"
      }`}
    >
      {/* Swatch row */}
      <div className="flex items-center gap-1">
        {swatches.map(({ color, title }) => (
          <div
            key={title}
            title={title}
            className="h-3.5 w-3.5 rounded-full border border-black/10 shrink-0"
            style={{ backgroundColor: color }}
          />
        ))}
      </div>

      {/* Name + mode */}
      <div>
        <div className="text-xs font-heading font-semibold text-text-primary leading-tight">
          {theme.name}
        </div>
        <div className="text-[10px] text-text-muted mt-0.5 flex items-center gap-1">
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              theme.mode === "dark" ? "bg-accent/60" : "bg-warning/60"
            }`}
          />
          {theme.mode}
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
  // Coerce rgba/non-hex to a fallback hex so the native picker never crashes.
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
        />
        <input
          type="text"
          value={value}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          className="flex-1 min-w-0 px-2 py-1 text-xs font-mono bg-surface-base border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/60"
          spellCheck={false}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: RangeField
// ---------------------------------------------------------------------------

interface RangeFieldProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (val: number) => void;
}

function RangeField({ label, value, min, max, step = 1, unit = "", onChange }: RangeFieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-text-muted uppercase tracking-wide">{label}</span>
        <span className="text-[10px] font-mono text-text-secondary">
          {value}{unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(Number(e.target.value))}
        className="w-full h-1 accent-accent cursor-pointer"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: LivePreviewCard
// ---------------------------------------------------------------------------

interface LivePreviewProps {
  colors: FlintTradeTheme["colors"];
}

function LivePreviewCard({ colors }: LivePreviewProps) {
  return (
    <div
      className="rounded-lg border p-3 space-y-2"
      style={{ backgroundColor: colors.card, borderColor: colors.border }}
    >
      <div className="flex items-center justify-between">
        <span style={{ color: colors.textPrimary, fontSize: "11px", fontWeight: 600 }}>
          Preview
        </span>
        <span style={{ color: colors.accent, fontSize: "10px" }}>Active</span>
      </div>
      <div className="flex items-center gap-2">
        <div
          className="rounded px-2 py-0.5 text-[10px] font-mono"
          style={{
            backgroundColor: `${colors.profit}22`,
            color: colors.profit,
            border: `1px solid ${colors.profit}44`,
          }}
        >
          +1.42%
        </div>
        <div
          className="rounded px-2 py-0.5 text-[10px] font-mono"
          style={{
            backgroundColor: `${colors.loss}22`,
            color: colors.loss,
            border: `1px solid ${colors.loss}44`,
          }}
        >
          -0.68%
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        {[colors.background, colors.card, colors.accent, colors.profit, colors.loss, colors.warning].map((c, i) => (
          <div
            key={i}
            className="h-3 w-3 rounded-sm border border-black/10"
            style={{ backgroundColor: c }}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Default custom-builder state (clone of midnight colors)
// ---------------------------------------------------------------------------

const DEFAULT_CUSTOM_COLORS: FlintTradeTheme["colors"] = {
  background: "#0a0a0f",
  backgroundSecondary: "#0e0e16",
  card: "#16161f",
  cardHover: "#24242e",
  border: "#2a2a3a",
  borderHover: "#3a3a4a",
  textPrimary: "#e4e4e7",
  textSecondary: "#8b8b95",
  textMuted: "#7e7e8a",
  accent: "#3b82f6",
  accentHover: "#2563eb",
  accentMuted: "rgba(59,130,246,0.15)",
  profit: "#22c55e",
  loss: "#ef4444",
  warning: "#eab308",
};

const DEFAULT_CUSTOM_EFFECTS: FlintTradeTheme["effects"] = {
  transparency: 0,
  blur: 0,
  borderRadius: "md",
};

const BORDER_RADIUS_OPTIONS: Array<FlintTradeTheme["effects"]["borderRadius"]> = [
  "none",
  "sm",
  "md",
  "lg",
  "xl",
];

// ---------------------------------------------------------------------------
// Main component: ThemePicker
// ---------------------------------------------------------------------------

export function ThemePicker() {
  const { activeThemeId, customThemes, setTheme, addCustomTheme } = useThemeStore();

  // --- Custom builder state ---
  const [builderOpen, setBuilderOpen] = useState(false);
  const [customName, setCustomName] = useState("My Theme");
  const [customColors, setCustomColors] = useState<FlintTradeTheme["colors"]>(
    () => ({ ...DEFAULT_CUSTOM_COLORS }),
  );
  const [customEffects, setCustomEffects] = useState<FlintTradeTheme["effects"]>(
    () => ({ ...DEFAULT_CUSTOM_EFFECTS }),
  );

  // --- Import/Export state ---
  const [importText, setImportText] = useState("");
  const [importError, setImportError] = useState("");
  const [copied, setCopied] = useState(false);

  // All themes (built-in + custom)
  const allThemes: FlintTradeTheme[] = [...BUILTIN_THEMES, ...customThemes];

  // --- Color updater ---
  const updateColor = useCallback(
    (key: keyof FlintTradeTheme["colors"], val: string) => {
      setCustomColors((prev) => ({ ...prev, [key]: val }));
    },
    [],
  );

  // --- Effects updater ---
  const updateEffects = useCallback(
    (key: keyof FlintTradeTheme["effects"], val: number | string) => {
      setCustomEffects((prev) => ({ ...prev, [key]: val }));
    },
    [],
  );

  // --- Apply custom theme ---
  function handleApplyCustom() {
    const id = makeCustomId();
    const theme = buildCustomTheme(id, customName || "Custom", customColors, customEffects);
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
        !("colors" in parsed)
      ) {
        setImportError("Invalid theme JSON — must have id, name, and colors fields.");
        return;
      }
      const theme = parsed as FlintTradeTheme;
      const importedTheme: FlintTradeTheme = {
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
      <div className="grid grid-cols-4 gap-2">
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

            {/* Colors grid */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Colors</p>
              <div className="grid grid-cols-2 gap-3">
                <ColorField label="Background"   value={customColors.background}   onChange={(v) => updateColor("background",   v)} />
                <ColorField label="Card"         value={customColors.card}         onChange={(v) => updateColor("card",         v)} />
                <ColorField label="Accent"       value={customColors.accent}       onChange={(v) => updateColor("accent",       v)} />
                <ColorField label="Profit"       value={customColors.profit}       onChange={(v) => updateColor("profit",       v)} />
                <ColorField label="Loss"         value={customColors.loss}         onChange={(v) => updateColor("loss",         v)} />
                <ColorField label="Warning"      value={customColors.warning}      onChange={(v) => updateColor("warning",      v)} />
                <ColorField label="Border"       value={customColors.border}       onChange={(v) => updateColor("border",       v)} />
                <ColorField label="Text Primary" value={customColors.textPrimary}  onChange={(v) => updateColor("textPrimary",  v)} />
              </div>
            </div>

            {/* Effects */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Effects</p>
              <div className="space-y-3">
                <RangeField
                  label="Transparency"
                  value={customEffects.transparency}
                  min={0}
                  max={100}
                  unit="%"
                  onChange={(v) => updateEffects("transparency", v)}
                />
                <RangeField
                  label="Backdrop blur"
                  value={customEffects.blur}
                  min={0}
                  max={24}
                  unit="px"
                  onChange={(v) => updateEffects("blur", v)}
                />
              </div>
            </div>

            {/* Border radius */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Border radius</p>
              <div className="flex items-center gap-1.5 flex-wrap">
                {BORDER_RADIUS_OPTIONS.map((r) => (
                  <button
                    key={r}
                    type="button"
                    onClick={() => updateEffects("borderRadius", r)}
                    className={`px-3 py-1 text-xs rounded border transition-colors ${
                      customEffects.borderRadius === r
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover"
                    }`}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>

            {/* Live preview */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Preview</p>
              <LivePreviewCard colors={customColors} />
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
              placeholder="Paste theme JSON here…"
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
