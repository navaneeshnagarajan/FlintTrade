/**
 * StatusBar — 24px bottom chrome bar for the Home bento dashboard.
 *
 * Left:  "{N} cards · Drag to rearrange"
 * Right: "Layout: {name} · Save · Presets · Reset"
 */

import { useBentoStore } from "@/stores/bentoStore";
import { useState } from "react";

interface StatusBarProps {
  /** Number of visible cards (passed from HomeRoute) */
  cardCount?: number;
  /** Active layout name */
  layoutName?: string;
}

export default function StatusBar({ cardCount, layoutName }: StatusBarProps) {
  const cards = useBentoStore((s) => s.cards);
  const activePresetId = useBentoStore((s) => s.activePresetId);
  const presets = useBentoStore((s) => s.presets);
  const savePreset = useBentoStore((s) => s.savePreset);
  const resetToDefault = useBentoStore((s) => s.resetToDefault);

  const [isSaving, setIsSaving] = useState(false);

  const displayCount = cardCount ?? cards.length;
  const activePreset = presets.find((p) => p.id === activePresetId);
  const displayLayout = activePreset?.name ?? layoutName ?? "Default";

  function handleSave() {
    setIsSaving(true);
    const name = `Layout ${new Date().toLocaleTimeString("en-IN", {
      hour: "2-digit",
      minute: "2-digit",
    })}`;
    savePreset(name);
    setTimeout(() => setIsSaving(false), 1200);
  }

  return (
    <div
      data-testid="status-bar"
      role="status"
      aria-label="Dashboard status bar"
      className="flex items-center justify-between shrink-0 px-3 text-[10px] tracking-[0.02em]"
      style={{
        height: "24px",
        background: "var(--glass-chrome-bg, rgba(12,12,20,0.85))",
        borderTop: "1px solid var(--glass-chrome-border, rgba(255,255,255,0.05))",
        backdropFilter: "var(--glass-blur, blur(16px))",
      }}
    >
      {/* Left */}
      <p className="text-text-muted">
        <span data-testid="status-bar-card-count">{displayCount}</span>
        {" cards · Drag to rearrange"}
      </p>

      {/* Right */}
      <div className="flex items-center gap-3 text-text-muted">
        <span>
          Layout:{" "}
          <span className="text-text-secondary" data-testid="status-bar-layout-name">
            {displayLayout}
          </span>
        </span>

        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          className={[
            "min-h-6 px-2 py-1 rounded text-[10px] bg-transparent border-0 cursor-pointer",
            "transition-colors duration-150 outline-none",
            "focus-visible:ring-1 focus-visible:ring-(--color-accent,#6366f1)",
            isSaving ? "text-profit" : "text-text-muted hover:text-text-primary",
          ].join(" ")}
          aria-label="Save current layout"
        >
          {isSaving ? "Saved" : "Save"}
        </button>

        <button
          type="button"
          className={[
            "min-h-6 px-2 py-1 rounded text-[10px] bg-transparent border-0 cursor-pointer",
            "text-text-muted hover:text-text-primary transition-colors duration-150 outline-none",
            "focus-visible:ring-1 focus-visible:ring-(--color-accent,#6366f1)",
          ].join(" ")}
          aria-label="View presets"
        >
          Presets
        </button>

        <button
          type="button"
          onClick={resetToDefault}
          className={[
            "min-h-6 px-2 py-1 rounded text-[10px] bg-transparent border-0 cursor-pointer",
            "text-text-muted hover:text-text-primary transition-colors duration-150 outline-none",
            "focus-visible:ring-1 focus-visible:ring-(--color-accent,#6366f1)",
          ].join(" ")}
          aria-label="Reset layout to default"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
