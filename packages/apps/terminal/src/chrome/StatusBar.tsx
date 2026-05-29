/**
 * StatusBar — 24px bottom chrome bar for the Home bento dashboard.
 *
 * Left:  "{N} cards · Drag to rearrange"
 * Right: "Layout: {name} · Save · Presets · Reset"
 */

import { useBentoStore } from "@/stores/bentoStore";
import { useState } from "react";
import { createPortal } from "react-dom";
import { Trash2, X } from "lucide-react";

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
  const loadPreset = useBentoStore((s) => s.loadPreset);
  const deletePreset = useBentoStore((s) => s.deletePreset);
  const resetToDefault = useBentoStore((s) => s.resetToDefault);

  const [isSaving, setIsSaving] = useState(false);
  const [isPresetsOpen, setIsPresetsOpen] = useState(false);

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

  function handleLoadPreset(presetId: string) {
    loadPreset(presetId);
    setIsPresetsOpen(false);
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
          onClick={() => setIsPresetsOpen((open) => !open)}
          aria-expanded={isPresetsOpen}
          aria-haspopup="dialog"
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

      {isPresetsOpen &&
        createPortal(
          <div
            role="dialog"
            aria-label="Dashboard layout presets"
            className="fixed bottom-7 right-3 z-200 w-72 rounded-lg border border-border-default bg-surface-card p-3 text-xs shadow-xl backdrop-blur-md"
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="font-medium text-text-primary">Layout Presets</p>
                <p className="text-[10px] text-text-muted">Load or remove saved dashboard layouts.</p>
              </div>
              <button
                type="button"
                aria-label="Close layout presets"
                className="flex size-7 items-center justify-center rounded text-text-muted hover:bg-surface-hover hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                onClick={() => setIsPresetsOpen(false)}
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>

            {presets.length === 0 ? (
              <p className="rounded border border-dashed border-border-default px-3 py-4 text-center text-text-muted">
                No saved layouts yet.
              </p>
            ) : (
              <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
                {presets.map((preset) => (
                  <div
                    key={preset.id}
                    className="flex items-center justify-between gap-2 rounded border border-border-default bg-surface-base/70 px-2 py-2"
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left text-text-secondary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                      aria-label={`Load layout ${preset.name}`}
                      onClick={() => handleLoadPreset(preset.id)}
                    >
                      <span className="block truncate font-medium">{preset.name}</span>
                      <span className="text-[10px] text-text-muted">
                        {preset.cards.length} widgets
                        {activePresetId === preset.id ? " · Active" : ""}
                      </span>
                    </button>
                    <button
                      type="button"
                      aria-label={`Delete layout ${preset.name}`}
                      className="flex size-7 items-center justify-center rounded text-text-muted hover:bg-loss/10 hover:text-loss focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-loss/40"
                      onClick={() => deletePreset(preset.id)}
                    >
                      <Trash2 size={13} aria-hidden="true" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
