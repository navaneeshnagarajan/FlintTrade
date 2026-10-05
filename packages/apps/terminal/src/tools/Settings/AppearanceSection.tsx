/**
 * AppearanceSection — color mode toggle, theme picker, background,
 * glass morphism, and layout density.
 *
 * Phase C: dark/light/system mode control added at top.
 * density and reduceMotion now read from stores (not localStorage).
 * flinttrade:appearance localStorage key fully eliminated.
 */

import { useThemeStore } from "@/stores/themeStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { ThemePicker } from "@/components/theme/ThemePicker";
import { BackgroundPicker } from "@/components/theme/BackgroundPicker";
import { selectDeskDensity } from "@/hooks/useDeskDensityChrome";
import { FieldRow, SegmentControl, Toggle, SectionTitle } from "./shared";

export function AppearanceSection() {
  const reduceMotion = useThemeStore((s) => s.reduceMotion);

  // Density — from settingsStore
  const density = useSettingsStore((s) => s.density);

  function handleDensity(v: string) {
    const val = v as "compact" | "comfortable";
    selectDeskDensity(val);
  }

  function handleReduceMotion(v: boolean) {
    useThemeStore.getState().setReduceMotion(v);
  }

  return (
    <div className="space-y-6">
      <SectionTitle>Appearance</SectionTitle>

      {/* Theme */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-text-secondary">Theme</p>
        <ThemePicker />
      </div>

      {/* Background */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-text-secondary">Background</p>
        <div className="p-4 rounded-lg border border-border-default bg-surface-card">
          <BackgroundPicker />
        </div>
      </div>

      {/* Layout */}
      <div className="space-y-3">
        <p className="text-xs font-semibold text-text-secondary">Layout</p>
        <div className="p-4 rounded-lg border border-border-default bg-surface-card space-y-4">
          <FieldRow
            label="Density"
            hint="Compact reduces row padding for more data on screen."
          >
            <SegmentControl
              value={density}
              onChange={handleDensity}
              options={[
                { value: "compact",     label: "Compact"     },
                { value: "comfortable", label: "Comfortable" },
              ]}
              aria-label="Layout density"
            />
          </FieldRow>

          <div className="space-y-1">
            <Toggle
              checked={reduceMotion}
              onChange={handleReduceMotion}
              label="Reduce motion (override system preference)"
            />
            <p className="text-xs text-text-muted pl-9">
              Disables animations and transitions across the terminal.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
