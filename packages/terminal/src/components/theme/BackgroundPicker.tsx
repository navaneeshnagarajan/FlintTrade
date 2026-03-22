/**
 * BackgroundPicker.tsx
 *
 * Background type selector for the Appearance settings section.
 * Supports: Solid Color | Gradient | Image URL | Pattern
 * All changes apply immediately via themeStore.setBackground().
 */

import { type ChangeEvent } from "react";
import { useThemeStore } from "@/stores/themeStore";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BgType = "solid" | "gradient" | "image" | "pattern";

type GradientType = "linear" | "radial";

const PATTERN_OPTIONS = [
  { value: "none",  label: "None"  },
  { value: "grid",  label: "Grid"  },
  { value: "dots",  label: "Dots"  },
  { value: "noise", label: "Noise" },
] as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a CSS gradient string from two colors, angle, and type. */
function buildGradientValue(
  colorA: string,
  colorB: string,
  angle: number,
  type: GradientType,
): string {
  if (type === "radial") {
    return `radial-gradient(circle, ${colorA}, ${colorB})`;
  }
  return `linear-gradient(${angle}deg, ${colorA}, ${colorB})`;
}

/** Parse gradient components out of a stored CSS gradient string. Returns defaults on failure. */
function parseGradient(value: string): {
  colorA: string;
  colorB: string;
  angle: number;
  type: GradientType;
} {
  const defaults = { colorA: "#0a0a0f", colorB: "#1e1e3f", angle: 135, type: "linear" as GradientType };
  if (!value) return defaults;

  if (value.startsWith("radial")) {
    const match = value.match(/#[0-9a-fA-F]{6}/g);
    if (match && match.length >= 2) return { ...defaults, colorA: match[0], colorB: match[1], type: "radial" };
  }

  if (value.startsWith("linear")) {
    const angleMatch = value.match(/(\d+)deg/);
    const colorMatch = value.match(/#[0-9a-fA-F]{6}/g);
    if (colorMatch && colorMatch.length >= 2) {
      return {
        colorA: colorMatch[0],
        colorB: colorMatch[1],
        angle: angleMatch ? parseInt(angleMatch[1], 10) : 135,
        type: "linear",
      };
    }
  }

  return defaults;
}

// ---------------------------------------------------------------------------
// Sub-component: SectionLabel
// ---------------------------------------------------------------------------

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[10px] uppercase tracking-wide text-text-muted">{children}</span>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: ColorInput
// ---------------------------------------------------------------------------

interface ColorInputProps {
  label: string;
  value: string;
  onChange: (val: string) => void;
}

function ColorInput({ label, value, onChange }: ColorInputProps) {
  const safeHex = value.startsWith("#") && value.length === 7 ? value : "#000000";

  return (
    <div className="flex flex-col gap-1">
      <SectionLabel>{label}</SectionLabel>
      <div className="flex items-center gap-1.5">
        <input
          type="color"
          value={safeHex}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
          className="h-7 w-7 rounded border border-border-default cursor-pointer bg-transparent p-0.5 shrink-0"
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
// Background type: Solid
// ---------------------------------------------------------------------------

interface SolidConfigProps {
  value: string;
  onChange: (val: string) => void;
}

function SolidConfig({ value, onChange }: SolidConfigProps) {
  return (
    <div className="pt-1">
      <ColorInput label="Color" value={value || "#0a0a0f"} onChange={onChange} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background type: Gradient
// ---------------------------------------------------------------------------

interface GradientConfigProps {
  value: string;
  onChange: (val: string) => void;
}

function GradientConfig({ value, onChange }: GradientConfigProps) {
  const parsed = parseGradient(value);

  function update(patch: Partial<typeof parsed>) {
    const merged = { ...parsed, ...patch };
    onChange(buildGradientValue(merged.colorA, merged.colorB, merged.angle, merged.type));
  }

  return (
    <div className="space-y-3 pt-1">
      <div className="grid grid-cols-2 gap-3">
        <ColorInput
          label="Color A"
          value={parsed.colorA}
          onChange={(c) => update({ colorA: c })}
        />
        <ColorInput
          label="Color B"
          value={parsed.colorB}
          onChange={(c) => update({ colorB: c })}
        />
      </div>

      {/* Type */}
      <div className="flex flex-col gap-1">
        <SectionLabel>Type</SectionLabel>
        <div className="flex items-center gap-1.5">
          {(["linear", "radial"] as GradientType[]).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => update({ type: t })}
              className={`px-3 py-1 text-xs rounded border transition-colors ${
                parsed.type === t
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Angle — only for linear */}
      {parsed.type === "linear" && (
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <SectionLabel>Angle</SectionLabel>
            <span className="text-[10px] font-mono text-text-secondary">{parsed.angle}°</span>
          </div>
          <input
            type="range"
            min={0}
            max={360}
            step={5}
            value={parsed.angle}
            onChange={(e: ChangeEvent<HTMLInputElement>) =>
              update({ angle: Number(e.target.value) })
            }
            className="w-full h-1 accent-accent cursor-pointer"
          />
        </div>
      )}

      {/* Gradient preview strip */}
      <div
        className="h-5 rounded border border-border-default"
        style={{
          background: buildGradientValue(parsed.colorA, parsed.colorB, parsed.angle, parsed.type),
        }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background type: Image
// ---------------------------------------------------------------------------

interface ImageConfigProps {
  value: string;
  onChange: (val: string) => void;
}

function ImageConfig({ value, onChange }: ImageConfigProps) {
  return (
    <div className="pt-1 space-y-1">
      <SectionLabel>Image URL</SectionLabel>
      <input
        type="url"
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(`url("${e.target.value}")`)}
        placeholder="https://example.com/background.jpg"
        className="w-full px-3 py-1.5 text-xs bg-surface-base border border-border-default rounded text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent/60"
      />
      <p className="text-[11px] text-text-muted">
        Use a dark, low-contrast image for best readability.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Background type: Pattern
// ---------------------------------------------------------------------------

interface PatternConfigProps {
  value: string;
  onChange: (val: string) => void;
}

function PatternConfig({ value, onChange }: PatternConfigProps) {
  return (
    <div className="pt-1 space-y-1">
      <SectionLabel>Pattern</SectionLabel>
      <div className="flex flex-wrap gap-1.5">
        {PATTERN_OPTIONS.map(({ value: v, label }) => (
          <button
            key={v}
            type="button"
            onClick={() => onChange(v)}
            className={`px-3 py-1 text-xs rounded border transition-colors ${
              value === v
                ? "border-accent bg-accent/10 text-accent"
                : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component: BackgroundPicker
// ---------------------------------------------------------------------------

const BG_TYPE_OPTIONS: Array<{ value: BgType; label: string }> = [
  { value: "solid",    label: "Solid Color" },
  { value: "gradient", label: "Gradient"    },
  { value: "image",    label: "Image URL"   },
  { value: "pattern",  label: "Pattern"     },
];

export function BackgroundPicker() {
  const { background, setBackground } = useThemeStore();

  const activeType = (background.type as BgType) || "solid";
  const activeValue = background.value || "";

  function handleTypeChange(type: BgType) {
    // Reset value to a sensible default per type
    const defaultValue: Record<BgType, string> = {
      solid:    "#0a0a0f",
      gradient: "linear-gradient(135deg, #0a0a0f, #1e1e3f)",
      image:    "",
      pattern:  "none",
    };
    setBackground({ type, value: defaultValue[type] });
  }

  function handleValueChange(val: string) {
    setBackground({ value: val });
  }

  return (
    <div className="space-y-3">

      {/* Type selector */}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-text-muted mb-2">Type</p>
        <div className="flex flex-wrap items-center gap-1.5">
          {BG_TYPE_OPTIONS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => handleTypeChange(value)}
              className={`px-3 py-1.5 text-xs rounded border transition-colors ${
                activeType === value
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border-default bg-surface-card text-text-secondary hover:bg-surface-hover"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Type-specific config */}
      <div>
        {activeType === "solid" && (
          <SolidConfig value={activeValue} onChange={handleValueChange} />
        )}
        {activeType === "gradient" && (
          <GradientConfig value={activeValue} onChange={handleValueChange} />
        )}
        {activeType === "image" && (
          <ImageConfig value={activeValue} onChange={handleValueChange} />
        )}
        {activeType === "pattern" && (
          <PatternConfig value={activeValue} onChange={handleValueChange} />
        )}
      </div>
    </div>
  );
}
