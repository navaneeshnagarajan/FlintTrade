/**
 * AppearanceSection — theme picker, background, glass morphism, and layout density.
 */

import { useState, useEffect } from "react";
import { useThemeStore } from "@/stores/themeStore";
import { ThemePicker } from "@/components/theme/ThemePicker";
import { BackgroundPicker } from "@/components/theme/BackgroundPicker";
import { FieldRow, SegmentControl, Toggle, SectionTitle } from "./shared";

export function AppearanceSection() {
  const { glass, setGlass } = useThemeStore();
  const [density, setDensity]           = useState<"compact" | "comfortable">("comfortable");
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("flinttrade:appearance");
      if (raw) {
        const parsed = JSON.parse(raw) as { density?: string; reduceMotion?: boolean };
        if (parsed.density === "compact" || parsed.density === "comfortable") {
          setDensity(parsed.density);
        }
        if (typeof parsed.reduceMotion === "boolean") {
          setReduceMotion(parsed.reduceMotion);
        }
      }
    } catch {
      // Ignore parse errors
    }
  }, []);

  function saveMeta(newDensity: "compact" | "comfortable", newReduceMotion: boolean) {
    try {
      localStorage.setItem(
        "flinttrade:appearance",
        JSON.stringify({ density: newDensity, reduceMotion: newReduceMotion }),
      );
    } catch {
      // Ignore storage errors
    }
  }

  function handleDensity(v: string) {
    const val = v as "compact" | "comfortable";
    setDensity(val);
    saveMeta(val, reduceMotion);
    document.documentElement.setAttribute("data-density", val);
  }

  function handleReduceMotion(v: boolean) {
    setReduceMotion(v);
    saveMeta(density, v);
    if (v) {
      document.documentElement.classList.add("reduce-motion");
    } else {
      document.documentElement.classList.remove("reduce-motion");
    }
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

      {/* Glass morphism */}
      <div className="space-y-3">
        <p className="text-xs font-semibold text-text-secondary">Glass Effect</p>
        <div className="p-4 rounded-lg border border-border-default bg-surface-card space-y-4">
          <Toggle
            checked={glass.enabled}
            onChange={(v) => setGlass({ enabled: v })}
            label="Enable glass morphism on cards and panels"
          />

          <div className={glass.enabled ? "" : "opacity-40 pointer-events-none"}>
            <div className="space-y-3">
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-wide text-text-muted">Transparency</span>
                  <span className="text-[10px] font-mono text-text-secondary">{glass.transparency}%</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={5}
                  value={glass.transparency}
                  onChange={(e) => setGlass({ transparency: Number(e.target.value) })}
                  aria-label="Glass transparency"
                  className="w-full h-1 accent-accent cursor-pointer"
                />
              </div>

              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] uppercase tracking-wide text-text-muted">Backdrop blur</span>
                  <span className="text-[10px] font-mono text-text-secondary">{glass.blur}px</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={24}
                  step={1}
                  value={glass.blur}
                  onChange={(e) => setGlass({ blur: Number(e.target.value) })}
                  aria-label="Glass backdrop blur"
                  className="w-full h-1 accent-accent cursor-pointer"
                />
              </div>
            </div>
          </div>
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
