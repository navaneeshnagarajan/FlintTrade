/**
 * One static Mode line under the TopBar.
 *
 * Desk-first: a single line, with horizontal scroll only when the copy
 * cannot fit. It is Mode chrome, never an outage banner.
 */

import { modeHonestyCopy } from "@/lib/modeHonesty";
import type { AppMode } from "@/stores/modeStore";

export default function ModeHonestyBar({ mode }: { mode: AppMode }) {
  const line = modeHonestyCopy(mode);
  return (
    <div
      data-testid="mode-honesty-bar"
      data-mode={mode}
      className="shrink-0 border-b border-border-subtle bg-surface-base px-3 py-1"
    >
      <p className="overflow-x-auto whitespace-nowrap text-xs text-text-secondary [scrollbar-width:none]">
        {line}
      </p>
    </div>
  );
}
