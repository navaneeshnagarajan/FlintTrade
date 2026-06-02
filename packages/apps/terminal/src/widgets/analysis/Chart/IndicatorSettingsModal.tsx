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
import {
  FLINT_CHART_INDICATOR_CATEGORIES as CATEGORIES,
  FLINT_CHART_INDICATOR_DEFAULT_COLORS as DEFAULT_COLORS,
  FLINT_CHART_INDICATOR_DEFAULT_LINE_STYLES as DEFAULT_LINE_STYLES,
  FLINT_CHART_INDICATOR_DEFINITIONS as INDICATOR_META,
  FLINT_CHART_INDICATOR_PALETTE as PALETTE,
  getFlintChartActiveIndicatorCountByCategory,
} from "@flinttrade/design-system";
import type {
  FlintChartIndicatorCategory as Category,
  FlintChartIndicatorColor as PaletteColor,
  FlintChartIndicatorKey as IndicatorKey,
  FlintChartIndicatorLineStyle as LineStyleValue,
} from "@flinttrade/design-system";
import { RotateCcw } from "lucide-react";
import type { IndicatorState, IndicatorPeriods } from "./types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface IndicatorSettingsModalProps {
  open: boolean;
  onClose: () => void;
  indicators: IndicatorState;
  periods: IndicatorPeriods;
  colors: Record<IndicatorKey, PaletteColor>;
  lineStyles: Record<IndicatorKey, LineStyleValue>;
  onApply: (
    indicators: IndicatorState,
    periods: IndicatorPeriods,
    colors: Record<IndicatorKey, PaletteColor>,
    lineStyles: Record<IndicatorKey, LineStyleValue>,
  ) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function IndicatorSettingsModal({
  open,
  onClose,
  indicators,
  periods,
  colors: currentColors,
  lineStyles: currentLineStyles,
  onApply,
}: IndicatorSettingsModalProps) {
  // Local draft state — only committed when Apply is clicked
  const [draftIndicators, setDraftIndicators] = useState<IndicatorState>(() => ({ ...indicators }));
  const [draftPeriods, setDraftPeriods] = useState<IndicatorPeriods>(() => ({ ...periods }));
  const [colors, setColors] = useState<Record<IndicatorKey, PaletteColor>>(() => ({ ...currentColors }));
  const [lineStyles, setLineStyles] = useState<Record<IndicatorKey, LineStyleValue>>(() => ({ ...currentLineStyles }));

  const [selectedCategory, setSelectedCategory] = useState<Category>("Overlays");
  const [selectedKey, setSelectedKey] = useState<IndicatorKey>("showEMA20");

  // Sync draft state when the modal opens with fresh external values
  const [lastOpen, setLastOpen] = useState(false);
  if (open && !lastOpen) {
    setLastOpen(true);
    setDraftIndicators({ ...indicators });
    setDraftPeriods({ ...periods });
    setColors({ ...currentColors });
    setLineStyles({ ...currentLineStyles });
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
    () => getFlintChartActiveIndicatorCountByCategory(draftIndicators),
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
    onApply(draftIndicators, draftPeriods, colors, lineStyles);
    onClose();
  }, [colors, draftIndicators, draftPeriods, lineStyles, onApply, onClose]);

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
