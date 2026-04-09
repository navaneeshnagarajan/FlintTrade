/**
 * IndicatorSettingsModal.tsx
 *
 * Rich indicator configuration modal for the ChartWidget.
 *
 * Features:
 * - All indicators listed with toggle, colour picker, period input(s),
 *   line-style selector, and description
 * - Grouped by category: Overlays, Volume, Oscillators
 * - Two-column layout: category list on left, settings panel on right
 * - "Reset to defaults" and "Apply" actions
 *
 * Usage:
 *   <IndicatorSettingsModal
 *     open={open}
 *     onClose={() => setOpen(false)}
 *     indicators={indicators}
 *     periods={periods}
 *     onApply={(indicators, periods) => { ... }}
 *   />
 */

import { useState, useCallback, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RotateCcw } from "lucide-react";
import type { IndicatorState, IndicatorPeriods } from "./types";

// ---------------------------------------------------------------------------
// Colour palette
// ---------------------------------------------------------------------------

const PALETTE = [
  "#3b82f6", // blue-500
  "#f59e0b", // amber-500
  "#06b6d4", // cyan-500
  "#84cc16", // lime-500
  "#94a3b8", // slate-400
  "#22c55e", // green-500 (profit)
  "#a855f7", // purple-500
  "#f97316", // orange-500
  "#ec4899", // pink-500
  "#ef4444", // red-500
  "#14b8a6", // teal-500
  "#6366f1", // indigo-500
  "#fbbf24", // amber-400
  "#38bdf8", // sky-400
  "#fb923c", // orange-400
  "#e879f9", // fuchsia-400
] as const;

type PaletteColor = (typeof PALETTE)[number];

// ---------------------------------------------------------------------------
// Line style type
// ---------------------------------------------------------------------------

type LineStyleValue = "solid" | "dashed" | "dotted";

// ---------------------------------------------------------------------------
// Indicator descriptor
// ---------------------------------------------------------------------------

type IndicatorKey = keyof IndicatorState;

interface IndicatorMeta {
  key: IndicatorKey;
  name: string;
  description: string;
  category: "Overlays" | "Volume" | "Oscillators";
  defaultColor: PaletteColor;
  periods: Array<{ field: keyof IndicatorPeriods; label: string; min: number; max: number; step: number }>;
  hasLineStyle: boolean;
}

// ---------------------------------------------------------------------------
// Metadata catalogue
// ---------------------------------------------------------------------------

const INDICATOR_META: IndicatorMeta[] = [
  // --- Overlays ---
  {
    key: "showEMA20",
    name: "EMA",
    description: "Exponential Moving Average — weights recent prices more heavily.",
    category: "Overlays",
    defaultColor: "#3b82f6",
    periods: [{ field: "ema1", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showEMA50",
    name: "EMA (2)",
    description: "Second EMA line with an independent period.",
    category: "Overlays",
    defaultColor: "#f59e0b",
    periods: [{ field: "ema2", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showSMA",
    name: "SMA",
    description: "Simple Moving Average — equal weight on all periods.",
    category: "Overlays",
    defaultColor: "#06b6d4",
    periods: [{ field: "sma", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showWMA",
    name: "WMA",
    description: "Weighted Moving Average — linear weight increase.",
    category: "Overlays",
    defaultColor: "#84cc16",
    periods: [{ field: "wma", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showDEMA",
    name: "DEMA",
    description: "Double Exponential Moving Average — reduces lag further than EMA.",
    category: "Overlays",
    defaultColor: "#f97316",
    periods: [{ field: "dema", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showHullMA",
    name: "Hull MA",
    description: "Hull Moving Average — fast, smooth, and responsive.",
    category: "Overlays",
    defaultColor: "#a855f7",
    periods: [{ field: "hull", label: "Period", min: 2, max: 500, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showVWMA",
    name: "VWMA",
    description: "Volume-Weighted Moving Average.",
    category: "Overlays",
    defaultColor: "#14b8a6",
    periods: [{ field: "vwma", label: "Period", min: 2, max: 200, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showBB",
    name: "Bollinger Bands",
    description: "Volatility envelope: SMA ± N standard deviations.",
    category: "Overlays",
    defaultColor: "#94a3b8",
    periods: [
      { field: "bbPeriod", label: "Period", min: 2, max: 200, step: 1 },
      { field: "bbMult", label: "Mult", min: 0.5, max: 5, step: 0.1 },
    ],
    hasLineStyle: true,
  },
  {
    key: "showKeltner",
    name: "Keltner Channel",
    description: "ATR-based channel around an EMA.",
    category: "Overlays",
    defaultColor: "#f97316",
    periods: [
      { field: "keltner", label: "Period", min: 2, max: 200, step: 1 },
      { field: "keltnerMult", label: "Mult", min: 0.5, max: 5, step: 0.1 },
    ],
    hasLineStyle: true,
  },
  {
    key: "showSupertrend",
    name: "Supertrend",
    description: "ATR-based trailing stop/trend direction indicator.",
    category: "Overlays",
    defaultColor: "#22c55e",
    periods: [
      { field: "stPeriod", label: "Period", min: 2, max: 100, step: 1 },
      { field: "stFactor", label: "Factor", min: 1, max: 10, step: 0.5 },
    ],
    hasLineStyle: false,
  },
  {
    key: "showVWAP",
    name: "VWAP",
    description: "Volume-Weighted Average Price — intraday benchmark.",
    category: "Overlays",
    defaultColor: "#e879f9",
    periods: [],
    hasLineStyle: true,
  },
  {
    key: "showIchimoku",
    name: "Ichimoku Cloud",
    description: "Multi-line Japanese trend and support/resistance system.",
    category: "Overlays",
    defaultColor: "#22c55e",
    periods: [],
    hasLineStyle: false,
  },
  {
    key: "showPivot",
    name: "Pivot Points",
    description: "Daily pivot, R1–R3, S1–S3 price levels.",
    category: "Overlays",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: true,
  },
  {
    key: "showParabolicSAR",
    name: "Parabolic SAR",
    description: "Stop-and-reverse trend-following dots.",
    category: "Overlays",
    defaultColor: "#fbbf24",
    periods: [],
    hasLineStyle: false,
  },

  // --- Volume ---
  {
    key: "showVolume",
    name: "Volume",
    description: "Bar volume histogram on a separate price scale.",
    category: "Volume",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: false,
  },
  {
    key: "showOBV",
    name: "OBV",
    description: "On-Balance Volume — cumulative volume flow indicator.",
    category: "Volume",
    defaultColor: "#94a3b8",
    periods: [],
    hasLineStyle: true,
  },
  {
    key: "showOI",
    name: "OI Overlay",
    description: "Open Interest histogram overlay — fetched from OpenAlgo.",
    category: "Volume",
    defaultColor: "#6366f1",
    periods: [],
    hasLineStyle: false,
  },

  // --- Oscillators ---
  {
    key: "showRSI",
    name: "RSI",
    description: "Relative Strength Index — overbought/oversold momentum (0–100).",
    category: "Oscillators",
    defaultColor: "#a855f7",
    periods: [{ field: "rsi", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showMACD",
    name: "MACD",
    description: "Moving Average Convergence Divergence (12, 26, 9).",
    category: "Oscillators",
    defaultColor: "#3b82f6",
    periods: [],
    hasLineStyle: false,
  },
  {
    key: "showStoch",
    name: "Stochastic",
    description: "Stochastic oscillator K & D lines (14, 3, 3).",
    category: "Oscillators",
    defaultColor: "#f97316",
    periods: [],
    hasLineStyle: true,
  },
  {
    key: "showATR",
    name: "ATR",
    description: "Average True Range — measures market volatility.",
    category: "Oscillators",
    defaultColor: "#fb923c",
    periods: [{ field: "atr", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showADX",
    name: "ADX",
    description: "Average Directional Index — trend strength (0–100).",
    category: "Oscillators",
    defaultColor: "#fbbf24",
    periods: [{ field: "adx", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showWilliamsR",
    name: "Williams %R",
    description: "Williams %R — momentum oscillator (-100 to 0).",
    category: "Oscillators",
    defaultColor: "#ec4899",
    periods: [{ field: "wr", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
  },
  {
    key: "showCCI",
    name: "CCI",
    description: "Commodity Channel Index — deviation from average price.",
    category: "Oscillators",
    defaultColor: "#38bdf8",
    periods: [{ field: "cci", label: "Period", min: 2, max: 100, step: 1 }],
    hasLineStyle: true,
  },
];

const CATEGORIES = ["Overlays", "Volume", "Oscillators"] as const;
type Category = (typeof CATEGORIES)[number];

// ---------------------------------------------------------------------------
// Default colours map
// ---------------------------------------------------------------------------

const DEFAULT_COLORS: Record<IndicatorKey, PaletteColor> = Object.fromEntries(
  INDICATOR_META.map((m) => [m.key, m.defaultColor]),
) as Record<IndicatorKey, PaletteColor>;

const DEFAULT_LINE_STYLES: Record<IndicatorKey, LineStyleValue> = Object.fromEntries(
  INDICATOR_META.map((m) => [m.key, "solid" as LineStyleValue]),
) as Record<IndicatorKey, LineStyleValue>;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface IndicatorSettingsModalProps {
  open: boolean;
  onClose: () => void;
  indicators: IndicatorState;
  periods: IndicatorPeriods;
  onApply: (indicators: IndicatorState, periods: IndicatorPeriods) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function IndicatorSettingsModal({
  open,
  onClose,
  indicators,
  periods,
  onApply,
}: IndicatorSettingsModalProps) {
  // Local draft state — only committed when Apply is clicked
  const [draftIndicators, setDraftIndicators] = useState<IndicatorState>(() => ({ ...indicators }));
  const [draftPeriods, setDraftPeriods] = useState<IndicatorPeriods>(() => ({ ...periods }));
  const [colors, setColors] = useState<Record<IndicatorKey, PaletteColor>>(() => ({ ...DEFAULT_COLORS }));
  const [lineStyles, setLineStyles] = useState<Record<IndicatorKey, LineStyleValue>>(() => ({ ...DEFAULT_LINE_STYLES }));

  const [selectedCategory, setSelectedCategory] = useState<Category>("Overlays");
  const [selectedKey, setSelectedKey] = useState<IndicatorKey>("showEMA20");

  // Sync draft state when the modal opens with fresh external values
  const [lastOpen, setLastOpen] = useState(false);
  if (open && !lastOpen) {
    setLastOpen(true);
    setDraftIndicators({ ...indicators });
    setDraftPeriods({ ...periods });
  }
  if (!open && lastOpen) {
    setLastOpen(false);
  }

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const filteredIndicators = useMemo(
    () => INDICATOR_META.filter((m) => m.category === selectedCategory),
    [selectedCategory],
  );

  const selectedMeta = useMemo(
    () => INDICATOR_META.find((m) => m.key === selectedKey) ?? INDICATOR_META[0],
    [selectedKey],
  );

  const activeCountByCategory = useMemo(
    () =>
      Object.fromEntries(
        CATEGORIES.map((cat) => [
          cat,
          INDICATOR_META.filter((m) => m.category === cat && draftIndicators[m.key]).length,
        ]),
      ) as Record<Category, number>,
    [draftIndicators],
  );

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleToggle = useCallback((key: IndicatorKey, value: boolean) => {
    setDraftIndicators((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handlePeriodChange = useCallback((field: keyof IndicatorPeriods, raw: string) => {
    const v = parseFloat(raw);
    if (isNaN(v)) return;
    setDraftPeriods((prev) => ({ ...prev, [field]: v }));
  }, []);

  const handleColorChange = useCallback((key: IndicatorKey, color: PaletteColor) => {
    setColors((prev) => ({ ...prev, [key]: color }));
  }, []);

  const handleLineStyleChange = useCallback((key: IndicatorKey, style: LineStyleValue) => {
    setLineStyles((prev) => ({ ...prev, [key]: style }));
  }, []);

  const handleReset = useCallback(() => {
    setDraftIndicators({ ...indicators });
    setDraftPeriods({ ...periods });
    setColors({ ...DEFAULT_COLORS });
    setLineStyles({ ...DEFAULT_LINE_STYLES });
  }, [indicators, periods]);

  const handleApply = useCallback(() => {
    onApply(draftIndicators, draftPeriods);
    onClose();
  }, [draftIndicators, draftPeriods, onApply, onClose]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent
        className="max-w-2xl w-full bg-surface-card border-border-default text-text-primary p-0 gap-0 overflow-hidden"
        aria-label="Indicator settings"
      >
        <DialogHeader className="px-4 pt-4 pb-2 border-b border-border-default">
          <DialogTitle className="text-sm font-heading font-semibold text-text-primary">
            Indicator Settings
          </DialogTitle>
        </DialogHeader>

        {/* Body — two columns */}
        <div className="flex min-h-0" style={{ height: "440px" }}>

          {/* Left: category tabs + indicator list */}
          <div className="w-52 shrink-0 border-r border-border-default flex flex-col overflow-hidden">

            {/* Category tabs */}
            <div className="flex border-b border-border-default">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => {
                    setSelectedCategory(cat);
                    const first = INDICATOR_META.find((m) => m.category === cat);
                    if (first) setSelectedKey(first.key);
                  }}
                  className={`flex-1 py-1.5 text-xxs font-sans transition-colors relative ${
                    selectedCategory === cat
                      ? "text-accent border-b-2 border-accent -mb-px"
                      : "text-text-muted hover:text-text-primary"
                  }`}
                >
                  {cat}
                  {activeCountByCategory[cat] > 0 && (
                    <span className="absolute top-1 right-1 w-3.5 h-3.5 rounded-full bg-accent text-white text-xxs flex items-center justify-center leading-none">
                      {activeCountByCategory[cat]}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Indicator list */}
            <div className="flex-1 overflow-y-auto py-1">
              {filteredIndicators.map((meta) => (
                <button
                  key={meta.key}
                  onClick={() => setSelectedKey(meta.key)}
                  className={`w-full flex items-center gap-2 px-3 py-1.5 text-left transition-colors ${
                    selectedKey === meta.key
                      ? "bg-accent/10 text-text-primary"
                      : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                  }`}
                >
                  {/* Active indicator colour dot */}
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{
                      backgroundColor: draftIndicators[meta.key] ? colors[meta.key] : "transparent",
                      border: draftIndicators[meta.key] ? "none" : "1px solid #4b5563",
                    }}
                  />
                  <span className="text-xs font-sans truncate flex-1">{meta.name}</span>
                  {draftIndicators[meta.key] && (
                    <Badge
                      variant="secondary"
                      className="text-xxs h-4 px-1 bg-accent/15 text-accent border-0"
                    >
                      ON
                    </Badge>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Right: settings panel */}
          <div className="flex-1 flex flex-col overflow-y-auto px-4 py-3 gap-4">

            {/* Toggle + name */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-heading font-semibold text-text-primary">
                  {selectedMeta.name}
                </span>
                <p className="text-xs text-text-muted leading-relaxed max-w-xs">
                  {selectedMeta.description}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0 pt-0.5">
                <span className="text-xs text-text-muted">{draftIndicators[selectedMeta.key] ? "On" : "Off"}</span>
                <Switch
                  checked={draftIndicators[selectedMeta.key]}
                  onCheckedChange={(v) => handleToggle(selectedMeta.key, v)}
                  aria-label={`Toggle ${selectedMeta.name}`}
                />
              </div>
            </div>

            {/* Period inputs */}
            {selectedMeta.periods.length > 0 && (
              <div className="flex flex-col gap-2">
                <span className="text-xxs font-sans text-text-muted uppercase tracking-wider">
                  Parameters
                </span>
                <div className="flex flex-wrap gap-3">
                  {selectedMeta.periods.map((p) => (
                    <div key={p.field} className="flex flex-col gap-1">
                      <label className="text-xxs text-text-muted">{p.label}</label>
                      <Input
                        type="number"
                        min={p.min}
                        max={p.max}
                        step={p.step}
                        value={draftPeriods[p.field]}
                        onChange={(e) => handlePeriodChange(p.field, e.target.value)}
                        className="h-7 w-20 text-xs font-mono text-center px-1 bg-surface-base border-border-default"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Colour picker */}
            <div className="flex flex-col gap-2">
              <span className="text-xxs font-sans text-text-muted uppercase tracking-wider">
                Colour
              </span>
              <div className="flex flex-wrap gap-1.5">
                {PALETTE.map((c) => (
                  <button
                    key={c}
                    title={c}
                    onClick={() => handleColorChange(selectedMeta.key, c)}
                    className={`w-5 h-5 rounded-full transition-all ${
                      colors[selectedMeta.key] === c
                        ? "ring-2 ring-offset-1 ring-offset-surface-card ring-white scale-110"
                        : "hover:scale-110"
                    }`}
                    style={{ backgroundColor: c }}
                    aria-label={`Select colour ${c}`}
                    aria-pressed={colors[selectedMeta.key] === c}
                  />
                ))}
              </div>
            </div>

            {/* Line style selector — only for line-based indicators */}
            {selectedMeta.hasLineStyle && (
              <div className="flex flex-col gap-2">
                <span className="text-xxs font-sans text-text-muted uppercase tracking-wider">
                  Line Style
                </span>
                <Select
                  value={lineStyles[selectedMeta.key]}
                  onValueChange={(v) => handleLineStyleChange(selectedMeta.key, v as LineStyleValue)}
                >
                  <SelectTrigger
                    className="h-7 w-32 text-xs bg-surface-base border-border-default"
                    aria-label="Line style"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-surface-card border-border-default text-text-primary">
                    <SelectItem value="solid" className="text-xs">
                      <span className="flex items-center gap-2">
                        <span className="w-8 h-px border-t-2 border-text-primary inline-block" />
                        Solid
                      </span>
                    </SelectItem>
                    <SelectItem value="dashed" className="text-xs">
                      <span className="flex items-center gap-2">
                        <span className="w-8 h-px border-t-2 border-dashed border-text-primary inline-block" />
                        Dashed
                      </span>
                    </SelectItem>
                    <SelectItem value="dotted" className="text-xs">
                      <span className="flex items-center gap-2">
                        <span className="w-8 h-px border-t-2 border-dotted border-text-primary inline-block" />
                        Dotted
                      </span>
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <DialogFooter className="px-4 py-2 border-t border-border-default flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-text-muted hover:text-text-primary gap-1"
            onClick={handleReset}
          >
            <RotateCcw size={12} />
            Reset to defaults
          </Button>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs border-border-default"
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-7 text-xs bg-accent hover:bg-accent/90 text-white"
              onClick={handleApply}
            >
              Apply
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
