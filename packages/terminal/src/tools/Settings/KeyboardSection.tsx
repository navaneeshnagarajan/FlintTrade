/**
 * KeyboardSection — read-only display of keyboard shortcuts.
 */

import { SectionTitle } from "./shared";

interface ShortcutRowProps {
  keys: string[];
  action: string;
}

function ShortcutRow({ keys, action }: ShortcutRowProps) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-border-default last:border-0">
      <span className="text-xs text-text-secondary">{action}</span>
      <div className="flex items-center gap-1">
        {keys.map((k, i) => (
          <span key={i}>
            <kbd className="px-1.5 py-0.5 text-xs font-mono font-medium bg-surface-base border border-border-default rounded text-text-primary">
              {k}
            </kbd>
            {i < keys.length - 1 && (
              <span className="text-xs text-text-muted mx-0.5">+</span>
            )}
          </span>
        ))}
      </div>
    </div>
  );
}

export function KeyboardSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>Keyboard Shortcuts</SectionTitle>

      <div className="p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        Shortcut customisation is coming in a future release. These defaults are active now.
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Order Placement</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Shift", "↑"]} action="Buy CE (call option)" />
          <ShortcutRow keys={["Shift", "↓"]} action="Buy PE (put option)"  />
          <ShortcutRow keys={["Shift", "←"]} action="Sell CE"              />
          <ShortcutRow keys={["Shift", "→"]} action="Sell PE"              />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Position Management</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["F6"]} action="Close All Positions" />
          <ShortcutRow keys={["F7"]} action="Cancel All Orders"   />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Widget Navigation</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Ctrl", "W"]} action="Add widget"       />
          <ShortcutRow keys={["Ctrl", "/"]} action="Open command bar" />
        </div>
      </div>
    </div>
  );
}
