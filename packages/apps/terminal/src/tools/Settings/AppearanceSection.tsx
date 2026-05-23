/**
 * AppearanceSection — color mode toggle, theme picker, background,
 * glass morphism, and layout density.
 *
 * Phase C: dark/light/system mode control added at top.
 * density and reduceMotion now read from stores (not localStorage).
 * flinttrade:appearance localStorage key fully eliminated.
 */

import { Sun, Moon, Monitor } from "lucide-react";
import { useThemeStore } from "@/stores/themeStore";
import { useSettingsStore } from "@/stores/settingsStore";
import { ThemePicker } from "@/components/theme/ThemePicker";
import { BackgroundPicker } from "@/components/theme/BackgroundPicker";
import { FieldRow, SegmentControl, Toggle, SectionTitle } from "./shared";

export function AppearanceSection() {
  const { glass, setGlass } = useThemeStore();

  // Color mode — from themeStore
  const mode         = useThemeStore((s) => s.mode);
  const reduceMotion = useThemeStore((s) => s.reduceMotion);

  // Density — from settingsStore
  const density = useSettingsStore((s) => s.density);

  function handleMode(v: string) {
    if (v === "dark" || v === "light" || v === "system") {
      useThemeStore.getState().setMode(v);
    }
  }

  function handleDensity(v: string) {
    const val = v as "compact" | "comfortable";
    useSettingsStore.getState().setDensity(val);
    document.documentElement.setAttribute("data-density", val);
  }

  function handleReduceMotion(v: boolean) {
    useThemeStore.getState().setReduceMotion(v);
  }

  return (
    <div className="space-y-6">
      <SectionTitle>Appearance</SectionTitle>

      {/* Dark / Light / System mode toggle */}
      <div className="space-y-2">
        <p className="text-xs font-semibold text-text-secondary">Color Mode</p>
        <div className="flex items-center gap-1 p-1 rounded-lg border border-border-default bg-surface-card w-fit">
          <button
            type="button"
            aria-label="Light mode"
            aria-pressed={mode === "light"}
            onClick={() => handleMode("light")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              mode === "light"
                ? "bg-accent/20 text-text-primary border border-accent/40"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            <Sun size={13} aria-hidden="true" />
            Light
          </button>
          <button
            type="button"
            aria-label="Dark mode"
            aria-pressed={mode === "dark"}
            onClick={() => handleMode("dark")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              mode === "dark"
                ? "bg-accent/20 text-text-primary border border-accent/40"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            <Moon size={13} aria-hidden="true" />
            Dark
          </button>
          <button
            type="button"
            aria-label="System mode"
            aria-pressed={mode === "system"}
            onClick={() => handleMode("system")}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              mode === "system"
                ? "bg-accent/20 text-text-primary border border-accent/40"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            <Monitor size={13} aria-hidden="true" />
            System
          </button>
        </div>
      </div>

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

      {/* Glass morphism */}
      <div className="space-y-3">
        <p className="text-xs font-semibold text-text-secondary">Glass Effect</p>
        <div className="p-4 rounded-lg border border-border-default bg-surface-card space-y-4">
          <Toggle
            checked={glass}
            onChange={(v) => setGlass(v)}
            label="Enable glass morphism on cards and panels"
          />
          <p className="text-[10px] text-text-muted">
            Backdrop blur and transparent surfaces. Disable for better performance on lower-end hardware.
          </p>
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
