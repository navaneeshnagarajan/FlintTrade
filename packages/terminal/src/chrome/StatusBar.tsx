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
      style={{
        height: "24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 12px",
        background: "var(--glass-chrome-bg, rgba(12,12,20,0.85))",
        borderTop: "1px solid var(--glass-chrome-border, rgba(255,255,255,0.05))",
        backdropFilter: "var(--glass-blur, blur(16px))",
        flexShrink: 0,
      }}
    >
      {/* Left */}
      <p
        style={{
          fontSize: "10px",
          color: "var(--color-text-muted, #505068)",
          letterSpacing: "0.02em",
        }}
      >
        <span data-testid="status-bar-card-count">{displayCount}</span>
        {" cards · Drag to rearrange"}
      </p>

      {/* Right */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "12px",
          fontSize: "10px",
          color: "var(--color-text-muted, #505068)",
        }}
      >
        <span>
          Layout:{" "}
          <span style={{ color: "#9090b0" }} data-testid="status-bar-layout-name">
            {displayLayout}
          </span>
        </span>

        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          style={{
            fontSize: "10px",
            color: isSaving ? "#22c55e" : "#6b6b8a",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
            transition: "color 150ms ease",
          }}
          aria-label="Save current layout"
        >
          {isSaving ? "Saved" : "Save"}
        </button>

        <button
          type="button"
          style={{
            fontSize: "10px",
            color: "#6b6b8a",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
          }}
          aria-label="View presets"
        >
          Presets
        </button>

        <button
          type="button"
          onClick={resetToDefault}
          style={{
            fontSize: "10px",
            color: "#6b6b8a",
            background: "none",
            border: "none",
            cursor: "pointer",
            padding: 0,
          }}
          aria-label="Reset layout to default"
        >
          Reset
        </button>
      </div>
    </div>
  );
}
