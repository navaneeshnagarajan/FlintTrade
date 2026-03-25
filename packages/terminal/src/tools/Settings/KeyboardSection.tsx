/**
 * KeyboardSection — read-only display of keyboard shortcuts.
 *
 * Implemented shortcuts are sourced from useGlobalKeys.ts.
 * Planned shortcuts are shown in muted style with a "(Planned)" tag.
 */

import { SectionTitle } from "./shared";

interface ShortcutRowProps {
  keys: string[];
  action: string;
  description?: string;
  planned?: boolean;
}

function ShortcutRow({ keys, action, description, planned = false }: ShortcutRowProps) {
  return (
    <div
      className={`flex items-start justify-between py-2 border-b border-border-default last:border-0 gap-4 ${
        planned ? "opacity-50" : ""
      }`}
    >
      <div className="flex flex-col gap-0.5 min-w-0">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className={`text-xs ${planned ? "text-text-muted" : "text-text-secondary"}`}>
            {action}
          </span>
          {planned && (
            <span className="text-[10px] font-medium text-text-muted bg-surface-base border border-border-default rounded px-1 py-px leading-none">
              Planned
            </span>
          )}
        </div>
        {description && (
          <span className="text-xxs text-text-muted">{description}</span>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        {keys.map((k, i) => (
          <span key={i}>
            <kbd
              className={`px-1.5 py-0.5 text-xs font-mono font-medium border rounded ${
                planned
                  ? "bg-surface-base border-border-default text-text-muted"
                  : "bg-surface-base border-border-default text-text-primary"
              }`}
            >
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
        Shortcut customisation is coming in a future release. Active shortcuts are live now.
        Planned shortcuts are shown dimmed.
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Global</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Escape"]}            action="Close overlay / dismiss panel"  description="Closes any open tool overlay, basket, or dropdown" />
          <ShortcutRow keys={["Ctrl", "K"]}         action="Command palette / symbol search" description="Open the global symbol and action search bar" />
          <ShortcutRow keys={["Ctrl", ","]}         action="Open settings"                  description="Open the Settings tool overlay" />
          <ShortcutRow keys={["Ctrl", "Shift", "P"]} action="Widget picker"                 description="Open the widget picker to add a new panel" planned />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Order Placement</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Shift", "↑"]} action="Buy CE (call option)"  description="Market buy the near-ATM call at current lot size" />
          <ShortcutRow keys={["Shift", "↓"]} action="Buy PE (put option)"   description="Market buy the near-ATM put at current lot size" />
          <ShortcutRow keys={["Shift", "←"]} action="Sell CE"               description="Market sell the near-ATM call" />
          <ShortcutRow keys={["Shift", "→"]} action="Sell PE"               description="Market sell the near-ATM put" />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Scalper — Position Management</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["X"]}           action="Exit all positions (with confirmation)" description="Prompts confirmation before squaring off all open positions" />
          <ShortcutRow keys={["Shift", "X"]}  action="Exit all positions immediately"         description="Square off all open positions without confirmation (MIS only, market order)" />
          <ShortcutRow keys={["C"]}           action="Cancel all orders"                      description="Cancel all pending/open orders in the current strategy" />
          <ShortcutRow keys={["F6"]}          action="Close all positions"                    description="Alias for exit all — useful with foot pedal setups" />
          <ShortcutRow keys={["F7"]}          action="Cancel all orders"                      description="Alias for cancel all orders" />
        </div>
      </div>

      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">Chart</p>
        <div className="rounded border border-border-default overflow-hidden px-3">
          <ShortcutRow keys={["Alt", "1"]} action="1-minute interval"     />
          <ShortcutRow keys={["Alt", "5"]} action="5-minute interval"     />
          <ShortcutRow keys={["Alt", "D"]} action="Daily interval"        />
          <ShortcutRow keys={["D"]}        action="Toggle drawing mode"   description="Cycle through drawing tools while chart is focused" />
        </div>
      </div>
    </div>
  );
}
