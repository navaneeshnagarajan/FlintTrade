/**
 * ThemePicker.tsx
 *
 * v4 theme selection UI for AppearanceSection.
 *
 * Sections:
 *   1. Built-in theme cards (Graphite / Midnight / Ember) with colour swatches.
 *      Hover-preview: temporarily applies the hovered theme's CSS vars.
 *   2. Dark / Light / System mode toggle — 3 buttons.
 *   3. Glass effects toggle — shadcn/ui Switch.
 *   4. Custom theme builder (collapsible):
 *      - Pick a base theme
 *      - Override any colour with a colour picker
 *      - Dark + Light split preview cards side-by-side
 *      - WCAG AA contrast validation per pair
 *      - Export active theme as JSON / Import from JSON
 */

import {
  useState,
  useCallback,
  useEffect,
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
  Moon,
  Sun,
  Monitor,
  Layers,
  Flame,
  ShieldCheck,
  ShieldX,
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { useThemeStore } from "@/stores/themeStore";
import {
  CINEMATIC_THEMES,
  type CinematicTheme,
  type ThemeDefinition,
  type ThemeVariant,
  type ColorMode,
} from "@/lib/cinematicThemes";
import { evaluateContrast, type ContrastResult } from "@/lib/contrastUtils";

// ---------------------------------------------------------------------------
// Icon resolver — maps theme.icon string to a Lucide component
// ---------------------------------------------------------------------------

type IconComponent = React.FC<{ size?: number; className?: string; "aria-hidden"?: boolean | "true" | "false" }>;

function ThemeIcon({ name, size = 16, className }: { name: string; size?: number; className?: string }) {
  const icons: Record<string, IconComponent> = {
    layers: Layers,
    moon:   Moon,
    flame:  Flame,
    sun:    Sun,
  };
  const Icon = (icons[name] ?? Palette) as IconComponent;
  return <Icon size={size} className={className} aria-hidden />;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCustomId(): string {
  return `custom-${Date.now()}`;
}

function buildCustomTheme(
  id: string,
  name: string,
  dark: ThemeVariant,
  light: ThemeVariant,
): ThemeDefinition {
  return {
    id,
    name,
    description: "Custom theme",
    icon:        "palette",
    dark,
    light,
    shared: {
      shimmer:   { speed: "2.4s" },
      particles: { quantity: 40, sizeRange: [1, 3], behavior: "drift" },
    },
  };
}

function isCinematicThemeShape(value: unknown): value is ThemeDefinition {
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
// ---------------------------------------------------------------------------

interface ContrastBadgeProps {
  fg: string;
  bg: string;
  label: string;
}

function ContrastBadge({ fg, bg, label }: ContrastBadgeProps) {
  const result: ContrastResult = evaluateContrast(fg, bg);

  return (
    <div className="flex items-center gap-1" title={`${label}: ${result.ratio}:1 — ${result.label}`}>
      <span className="text-[9px] text-text-muted">{label}</span>
      {result.passes ? (
        <ShieldCheck size={10} className="text-profit shrink-0" aria-label={`${label} passes WCAG AA`} />
      ) : (
        <ShieldX size={10} className="text-loss shrink-0" aria-label={`${label} fails WCAG AA`} />
      )}
      <span className={`text-[9px] font-mono ${result.passes ? "text-profit" : "text-loss"}`}>
        {result.ratio}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: VariantPreviewCard
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
      <div className="flex items-center justify-between">
        <span className="text-[9px] uppercase tracking-widest font-medium" style={{ color: colors.textMuted }}>
          {mode}
        </span>
        <div className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: colors.accent }} />
      </div>

      <div
        className="rounded p-2 space-y-1.5"
        style={{ backgroundColor: colors.card, border: `1px solid ${colors.border}` }}
      >
        <div className="text-[10px] font-semibold leading-none" style={{ color: colors.text }}>
          NIFTY 25,150.00
        </div>
        <div className="text-[9px] leading-none" style={{ color: colors.textMuted }}>
          09:30 IST
        </div>
        <div
          className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-mono"
          style={{ backgroundColor: `${colors.accent}22`, color: colors.accent, border: `1px solid ${colors.accent}44` }}
        >
          +1.42%
        </div>
      </div>

      <div className="rounded px-2 py-1 text-[9px]" style={{ ...glassStyle, color: colors.textSecondary }}>
        Glass surface
      </div>

      {/* Colour swatch strip: base / card / accent / profit / loss */}
      <div className="flex items-center gap-1">
        {[colors.base, colors.card, colors.accent, "#22c55e", "#ef4444"].map((c, i) => (
          <div key={i} className="h-2 flex-1 rounded-sm" style={{ backgroundColor: c }} />
        ))}
      </div>

      <ContrastBadge fg={colors.accent} bg={colors.base} label="accent/base" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: ThemeCard
// Hover-preview: temporarily applies hovered theme's CSS vars.
// ---------------------------------------------------------------------------

interface ThemeCardProps {
  theme: CinematicTheme;
  isActive: boolean;
  onSelect: () => void;
}

function ThemeCard({ theme, isActive, onSelect }: ThemeCardProps) {
  const previewActive = useRef(false);
  const prevId = useRef<string | null>(null);

  function handleMouseEnter(_e: MouseEvent<HTMLButtonElement>) {
    const store = useThemeStore.getState();
    if (theme.id === store.activeThemeId) return;
    previewActive.current = true;
    prevId.current = store.activeThemeId;
    store.setTheme(theme.id);
  }

  function handleMouseLeave(_e: MouseEvent<HTMLButtonElement>) {
    if (!previewActive.current || !prevId.current) return;
    previewActive.current = false;
    useThemeStore.getState().setTheme(prevId.current);
    prevId.current = null;
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
      {/* Icon + accent dots */}
      <div className="flex items-center justify-between">
        <ThemeIcon name={theme.icon} size={14} className={isActive ? "text-accent" : "text-text-muted"} />
        <div className="flex items-center gap-1">
          <div
            title={`Dark: ${theme.dark.colors.accent}`}
            className="h-2.5 w-2.5 rounded-full border border-black/10 shrink-0"
            style={{ backgroundColor: theme.dark.colors.accent }}
          />
          <div
            title={`Light: ${theme.light.colors.accent}`}
            className="h-2.5 w-2.5 rounded-full border border-black/10 shrink-0"
            style={{ backgroundColor: theme.light.colors.accent }}
          />
        </div>
      </div>

      {/* Name + description */}
      <div>
        <div className="text-xs font-heading font-semibold text-text-primary leading-tight">{theme.name}</div>
        <div className="text-[10px] text-text-muted mt-0.5 leading-snug line-clamp-2">{theme.description}</div>
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
// Sub-component: ModeToggle — Dark / Light / System
// ---------------------------------------------------------------------------

interface ModeToggleProps {
  mode: ColorMode;
  onChange: (mode: ColorMode) => void;
}

function ModeToggle({ mode, onChange }: ModeToggleProps) {
  const options: Array<{ value: ColorMode; icon: React.ReactNode; label: string }> = [
    { value: "dark",   icon: <Moon size={13} aria-hidden />,    label: "Dark" },
    { value: "light",  icon: <Sun size={13} aria-hidden />,     label: "Light" },
    { value: "system", icon: <Monitor size={13} aria-hidden />, label: "System" },
  ];

  return (
    <div className="flex items-center gap-1 rounded-lg border border-border-default bg-surface-base p-0.5" role="group" aria-label="Colour mode">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          aria-pressed={mode === opt.value}
          aria-label={opt.label}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
            mode === opt.value
              ? "bg-accent/15 text-accent border border-accent/30"
              : "text-text-muted hover:text-text-primary hover:bg-surface-hover border border-transparent"
          }`}
        >
          {opt.icon}
          {opt.label}
        </button>
      ))}
    </div>
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
// Default custom-builder variant — based on Graphite dark/light
// ---------------------------------------------------------------------------

const BASE_VARIANTS: Record<string, { dark: ThemeVariant; light: ThemeVariant }> = {
  graphite: {
    dark:  CINEMATIC_THEMES[0].dark,
    light: CINEMATIC_THEMES[0].light,
  },
  midnight: {
    dark:  CINEMATIC_THEMES[1].dark,
    light: CINEMATIC_THEMES[1].light,
  },
  ember: {
    dark:  CINEMATIC_THEMES[2].dark,
    light: CINEMATIC_THEMES[2].light,
  },
};

// ---------------------------------------------------------------------------
// Main component: ThemePicker
// ---------------------------------------------------------------------------

export function ThemePicker() {
  const { activeThemeId, mode, glass, customThemes, setTheme, setMode, setGlass, addCustomTheme } = useThemeStore();

  // --- Custom builder state ---
  const [builderOpen,   setBuilderOpen]  = useState(false);
  const [customName,    setCustomName]   = useState("My Theme");
  const [baseThemeId,   setBaseThemeId]  = useState<string>("graphite");
  const [darkVariant,   setDarkVariant]  = useState<ThemeVariant>(() => ({ ...BASE_VARIANTS["graphite"].dark,  colors: { ...BASE_VARIANTS["graphite"].dark.colors }  }));
  const [lightVariant,  setLightVariant] = useState<ThemeVariant>(() => ({ ...BASE_VARIANTS["graphite"].light, colors: { ...BASE_VARIANTS["graphite"].light.colors } }));

  // --- Import/Export state ---
  const [importText,  setImportText]  = useState("");
  const [importError, setImportError] = useState("");
  const [copied,      setCopied]      = useState(false);
  const copiedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copiedTimerRef.current !== null) {
        clearTimeout(copiedTimerRef.current);
      }
    };
  }, []);

  // All themes (built-in + custom)
  const allBuiltIn = [...CINEMATIC_THEMES];
  const allThemes: CinematicTheme[] = [...allBuiltIn, ...customThemes];

  // When the base theme selector changes, reset variant editors to that base
  function handleBaseThemeChange(id: string) {
    setBaseThemeId(id);
    const base = BASE_VARIANTS[id] ?? BASE_VARIANTS["graphite"];
    setDarkVariant({ ...base.dark,  colors: { ...base.dark.colors  } });
    setLightVariant({ ...base.light, colors: { ...base.light.colors } });
  }

  // --- Color updater for dark variant ---
  const updateDarkColor = useCallback(
    (key: keyof ThemeVariant["colors"], val: string) => {
      setDarkVariant((prev) => ({ ...prev, colors: { ...prev.colors, [key]: val } }));
    },
    [],
  );

  // --- Color updater for light variant ---
  const updateLightColor = useCallback(
    (key: keyof ThemeVariant["colors"], val: string) => {
      setLightVariant((prev) => ({ ...prev, colors: { ...prev.colors, [key]: val } }));
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

  // --- Export active theme as JSON ---
  async function handleExport() {
    const theme = useThemeStore.getState().getActiveTheme();
    const json = JSON.stringify(theme, null, 2);
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      copiedTimerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access denied — silent fail
    }
  }

  // --- Import ---
  function handleImport() {
    setImportError("");
    try {
      const parsed = JSON.parse(importText) as unknown;
      if (!isCinematicThemeShape(parsed)) {
        setImportError("Invalid theme JSON — must have id, name, dark, and light fields.");
        return;
      }
      const imported: ThemeDefinition = {
        ...parsed,
        id: parsed.id.startsWith("custom-") ? parsed.id : `custom-${parsed.id}`,
      };
      addCustomTheme(imported);
      setTheme(imported.id);
      setImportText("");
    } catch {
      setImportError("Could not parse JSON. Check formatting and try again.");
    }
  }

  // Contrast pairs for the WCAG checker
  const contrastPairs: Array<{ fg: string; bg: string; label: string; variant: "dark" | "light" }> = [
    { fg: darkVariant.colors.accent,  bg: darkVariant.colors.base,  label: "accent/base", variant: "dark" },
    { fg: darkVariant.colors.text,    bg: darkVariant.colors.base,  label: "text/base",   variant: "dark" },
    { fg: lightVariant.colors.accent, bg: lightVariant.colors.base, label: "accent/base", variant: "light" },
    { fg: lightVariant.colors.text,   bg: lightVariant.colors.base, label: "text/base",   variant: "light" },
  ];

  return (
    <div className="space-y-5">

      {/* ---- Theme cards (3 built-in + any custom) ---- */}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Theme</p>
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
      </div>

      {/* ---- Dark / Light / System toggle ---- */}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Colour mode</p>
        <ModeToggle mode={mode} onChange={setMode} />
        {mode === "system" && (
          <p className="text-[10px] text-text-muted mt-1.5">
            Automatically follows your OS dark/light preference in real time.
          </p>
        )}
      </div>

      {/* ---- Glass effects toggle ---- */}
      <div className="flex items-center gap-3">
        <Switch
          id="glass-toggle"
          checked={glass}
          onCheckedChange={setGlass}
          aria-label="Toggle glass effects"
        />
        <Label htmlFor="glass-toggle" className="text-xs text-text-primary cursor-pointer select-none">
          Glass effects
          <span className="block text-[10px] text-text-muted font-normal">
            Backdrop blur on cards, panels, and overlays. Disable for better performance.
          </span>
        </Label>
      </div>

      {/* ---- Custom theme builder ---- */}
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

            {/* Base theme selector */}
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-text-muted uppercase tracking-wide">Start from</span>
              <div className="flex items-center gap-2">
                {(["graphite", "midnight", "ember"] as const).map((id) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => handleBaseThemeChange(id)}
                    className={`px-3 py-1 text-xs rounded border transition-colors capitalize ${
                      baseThemeId === id
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border-default text-text-muted hover:text-text-primary hover:bg-surface-hover"
                    }`}
                  >
                    {id}
                  </button>
                ))}
              </div>
            </div>

            {/* Dark variant color editor */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Dark variant colours</p>
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

            {/* Light variant color editor */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Light variant colours</p>
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

            {/* WCAG AA contrast checker */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">WCAG AA contrast</p>
              <div className="rounded-lg border border-border-default bg-surface-base p-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
                {contrastPairs.map((pair) => {
                  const result = evaluateContrast(pair.fg, pair.bg);
                  return (
                    <div key={`${pair.variant}-${pair.label}`} className="flex items-center justify-between gap-2">
                      <span className="text-[9px] text-text-muted capitalize">{pair.variant} {pair.label}</span>
                      <div className="flex items-center gap-1">
                        {result.passes ? (
                          <ShieldCheck size={10} className="text-profit shrink-0" aria-label="passes AA" />
                        ) : (
                          <ShieldX size={10} className="text-loss shrink-0" aria-label="fails AA" />
                        )}
                        <span className={`text-[9px] font-mono ${result.passes ? "text-profit" : "text-loss"}`}>
                          {result.ratio}:1
                        </span>
                        <span className={`text-[9px] ${result.passes ? "text-profit" : "text-loss"}`}>
                          {result.label}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Dark / Light split preview */}
            <div>
              <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Live preview</p>
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
          <button
            type="button"
            onClick={() => void handleExport()}
            className="flex items-center gap-2 px-3 py-1.5 text-xs rounded border border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover hover:text-text-primary transition-colors"
          >
            {copied ? <Check size={12} className="text-profit" /> : <Copy size={12} />}
            {copied ? "Copied to clipboard" : "Export active theme as JSON"}
          </button>

          <div className="space-y-1.5">
            <textarea
              value={importText}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => { setImportText(e.target.value); setImportError(""); }}
              placeholder="Paste theme JSON here — must have id, name, dark, and light fields."
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
