/**
 * PracticeSection — Settings section for practice mode.
 *
 * Wraps the existing SandboxControls component which provides:
 *   - Virtual capital display and adjustment
 *   - Reset all practice data
 *   - Export/import practice data as JSON
 */

import SandboxControls from "@/components/sandbox/SandboxControls";
import { useModeStore } from "@/stores/modeStore";

export function PracticeSection() {
  const mode = useModeStore((s) => s.mode);
  const isPractice = mode === "practice";

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-heading font-semibold text-base text-text-primary mb-1">
          Practice Mode
        </h2>
        <p className="text-sm text-text-muted">
          Manage your virtual trading capital, export practice data, or reset to start fresh.
        </p>
      </div>

      {!isPractice && (
        <div className="p-4 rounded-lg border border-border-default bg-surface-card">
          <p className="text-sm text-text-secondary">
            Switch to <strong>Practice</strong> mode from the TopBar to access virtual trading controls.
            You are currently in <strong>{mode === "explore" ? "Explore" : "Live"}</strong> mode.
          </p>
        </div>
      )}

      {isPractice && <SandboxControls />}
    </div>
  );
}
