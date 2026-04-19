/**
 * ShortcutConfigPanel — Settings panel for customising keyboard shortcuts.
 *
 * Displays all registered hotkeys grouped by category. Customisable bindings
 * show a "Press key combo to change" button that enters capture mode and
 * records the next key combination pressed. Conflict detection warns when two
 * bindings share the same combo. A "Reset to defaults" button clears all
 * overrides in localStorage.
 *
 * Backend sync: On mount, attempts to fetch overrides from
 * GET /ft-api/v1/shortcuts (user-specific, DuckDB-backed). On every save,
 * POSTs to /ft-api/v1/shortcuts for cross-device persistence.
 */

import {
  useState,
  useEffect,
  useCallback,
  useRef,
} from "react";
import {
  AlertTriangle,
  Check,
  Keyboard,
  RotateCcw,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  DEFAULT_HOTKEYS,
  detectConflicts,
  eventToKeys,
  findConflict,
  formatKeyCombo,
  loadCustomHotkeys,
  normalizeKeyCombo,
  resetAllHotkeys,
  saveHotkeyOverride,
  type HotkeyBinding,
  type HotkeyConflict,
} from "@/lib/hotkeyStore";

// ---------------------------------------------------------------------------
// Backend sync helpers
// ---------------------------------------------------------------------------

async function fetchServerShortcuts(): Promise<Record<string, string[]> | null> {
  try {
    const res = await fetch("/ft-api/v1/shortcuts", {
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { overrides?: Record<string, string[]> };
    return data.overrides ?? null;
  } catch {
    return null;
  }
}

async function pushServerShortcuts(
  overrides: Record<string, string[]>,
): Promise<void> {
  try {
    await fetch("/ft-api/v1/shortcuts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides }),
    });
  } catch {
    // Network unavailable — localStorage copy is authoritative
  }
}

async function resetServerShortcuts(): Promise<void> {
  try {
    await fetch("/ft-api/v1/shortcuts/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch {
    // noop
  }
}

// ---------------------------------------------------------------------------
// Category label map
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<HotkeyBinding["category"], string> = {
  global: "Global",
  scalper: "Scalper",
  chart: "Chart",
  trading: "Trading",
};

const CATEGORY_ORDER: Array<HotkeyBinding["category"]> = [
  "global",
  "scalper",
  "trading",
  "chart",
];

// ---------------------------------------------------------------------------
// Key badge
// ---------------------------------------------------------------------------

function KeyBadge({ token }: { token: string }) {
  return (
    <kbd className="inline-flex items-center justify-center rounded border border-border-default bg-glass-l1 text-text-secondary font-mono text-[11px] leading-none select-none shrink-0 h-5 px-1.5 min-w-5">
      {token}
    </kbd>
  );
}

function KeyComboDisplay({ keys }: { keys: string[] }) {
  if (keys.length === 0)
    return <span className="text-text-muted text-xs italic">unbound</span>;
  return (
    <span className="flex items-center gap-1" aria-label={keys.join(" + ")}>
      {keys.map((k, i) => (
        <KeyBadge key={i} token={k} />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Capture button
// ---------------------------------------------------------------------------

interface CaptureButtonProps {
  binding: HotkeyBinding;
  isCapturing: boolean;
  conflictId: string | null;
  onStartCapture: () => void;
  onCaptured: (keys: string[]) => void;
  onCancelCapture: () => void;
}

function CaptureButton({
  binding,
  isCapturing,
  conflictId,
  onStartCapture,
  onCaptured,
  onCancelCapture,
}: CaptureButtonProps) {
  const ref = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isCapturing) return;
    ref.current?.focus();

    function handleKeyDown(e: KeyboardEvent) {
      e.preventDefault();
      e.stopPropagation();
      const keys = eventToKeys(e);
      if (keys.length === 0) return;
      // Escape cancels
      if (keys.length === 1 && keys[0] === "Escape") {
        onCancelCapture();
        return;
      }
      onCaptured(keys);
    }

    window.addEventListener("keydown", handleKeyDown, { capture: true });
    return () => window.removeEventListener("keydown", handleKeyDown, { capture: true });
  }, [isCapturing, onCaptured, onCancelCapture]);

  if (!binding.customizable) {
    return (
      <span className="text-xs text-text-muted italic">
        System — not customisable
      </span>
    );
  }

  if (isCapturing) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-xs text-accent animate-pulse font-medium">
          Press key combo…
        </span>
        <button
          ref={ref}
          type="button"
          aria-label="Cancel key capture"
          onClick={onCancelCapture}
          className="p-1 rounded text-text-muted hover:text-text-primary transition-colors focus-visible:outline focus-visible:outline-accent"
        >
          <X size={12} />
        </button>
        {conflictId && (
          <span className="flex items-center gap-1 text-xs text-amber-400">
            <AlertTriangle size={11} />
            Conflict
          </span>
        )}
      </div>
    );
  }

  return (
    <Button
      size="sm"
      variant="outline"
      onClick={onStartCapture}
      className="h-6 px-2 text-xs border-border-default text-text-secondary hover:text-text-primary hover:bg-glass-l2"
    >
      Change
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Shortcut row
// ---------------------------------------------------------------------------

interface ShortcutRowProps {
  binding: HotkeyBinding;
  allBindings: HotkeyBinding[];
  conflict: HotkeyConflict | undefined;
  onUpdate: (id: string, keys: string[]) => void;
}

function ShortcutRow({ binding, allBindings, conflict, onUpdate }: ShortcutRowProps) {
  const [isCapturing, setIsCapturing] = useState(false);
  const [captureConflict, setCaptureConflict] = useState<string | null>(null);

  const handleCaptured = useCallback(
    (keys: string[]) => {
      const conflictId = findConflict(keys, binding.id, allBindings);
      if (conflictId) {
        setCaptureConflict(conflictId);
        // Still apply — let user decide; conflict warning shown in panel
      }
      onUpdate(binding.id, keys);
      setIsCapturing(false);
      setCaptureConflict(null);
    },
    [binding.id, allBindings, onUpdate],
  );

  const isDefault =
    normalizeKeyCombo(binding.keys) ===
    normalizeKeyCombo(
      DEFAULT_HOTKEYS.find((d) => d.id === binding.id)?.keys ?? [],
    );

  return (
    <div
      className={cn(
        "group flex items-center justify-between gap-4 py-2.5 px-3 rounded-glass-inner transition-colors",
        "border border-transparent",
        conflict ? "border-amber-500/30 bg-amber-500/5" : "hover:bg-glass-l1",
      )}
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm text-text-primary leading-snug truncate">
          {binding.action}
        </p>
        <p className="text-xs text-text-muted mt-0.5 truncate">
          {binding.description}
        </p>
        {conflict && (
          <p className="text-xs text-amber-400 mt-1 flex items-center gap-1">
            <AlertTriangle size={10} />
            Conflicts with another binding
          </p>
        )}
      </div>

      <div className="flex items-center gap-3 shrink-0">
        <KeyComboDisplay keys={binding.keys} />

        {!isDefault && binding.customizable && (
          <Badge
            variant="outline"
            className="text-[10px] h-4 px-1.5 border-accent/40 text-accent"
          >
            Custom
          </Badge>
        )}

        <CaptureButton
          binding={binding}
          isCapturing={isCapturing}
          conflictId={captureConflict}
          onStartCapture={() => setIsCapturing(true)}
          onCaptured={handleCaptured}
          onCancelCapture={() => {
            setIsCapturing(false);
            setCaptureConflict(null);
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export interface ShortcutConfigPanelProps {
  /** If true, shows a compact inline panel; if false shows full-width */
  compact?: boolean;
}

export default function ShortcutConfigPanel({
  compact = false,
}: ShortcutConfigPanelProps) {
  const [bindings, setBindings] = useState<HotkeyBinding[]>(() =>
    loadCustomHotkeys(),
  );
  const [saved, setSaved] = useState(false);
  const [syncing, setSyncing] = useState(false);

  // Load server overrides on mount and merge with defaults
  useEffect(() => {
    async function syncFromServer() {
      setSyncing(true);
      const serverOverrides = await fetchServerShortcuts();
      if (serverOverrides) {
        setBindings(
          DEFAULT_HOTKEYS.map((def) => {
            const custom = serverOverrides[def.id];
            if (custom && def.customizable) {
              // Apply server override to localStorage too
              saveHotkeyOverride(def.id, custom);
              return { ...def, keys: custom };
            }
            return { ...def };
          }),
        );
      }
      setSyncing(false);
    }
    void syncFromServer();
  }, []);

  const conflicts = detectConflicts(bindings);

  const handleUpdate = useCallback(
    async (id: string, keys: string[]) => {
      // Update local state
      setBindings((prev) =>
        prev.map((b) => (b.id === id ? { ...b, keys } : b)),
      );
      // Persist to localStorage
      saveHotkeyOverride(id, keys);
      // Build current overrides for server sync
      const updated = bindings.map((b) => (b.id === id ? { ...b, keys } : b));
      const overrides: Record<string, string[]> = {};
      for (const b of updated) {
        const def = DEFAULT_HOTKEYS.find((d) => d.id === b.id);
        if (
          b.customizable &&
          def &&
          normalizeKeyCombo(b.keys) !== normalizeKeyCombo(def.keys)
        ) {
          overrides[b.id] = keys;
        }
      }
      await pushServerShortcuts(overrides);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
    [bindings],
  );

  const handleResetAll = useCallback(async () => {
    resetAllHotkeys();
    await resetServerShortcuts();
    setBindings(loadCustomHotkeys());
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }, []);

  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat],
    entries: bindings.filter((b) => b.category === cat),
  }));

  const conflictIds = new Set(conflicts.flatMap((c) => c.bindingIds));

  return (
    <div
      className={cn(
        "flex flex-col gap-0",
        compact ? "" : "max-w-2xl",
      )}
      aria-label="Keyboard shortcut configuration"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Keyboard size={16} className="text-text-muted" aria-hidden="true" />
          <h2 className="text-sm font-semibold text-text-primary font-heading">
            Keyboard Shortcuts
          </h2>
          {syncing && (
            <span className="text-xs text-text-muted animate-pulse">
              Syncing…
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {saved && (
            <span
              className="flex items-center gap-1 text-xs text-green-400"
              aria-live="polite"
            >
              <Check size={12} />
              Saved
            </span>
          )}
          {conflicts.length > 0 && (
            <span className="flex items-center gap-1 text-xs text-amber-400">
              <AlertTriangle size={12} />
              {conflicts.length} conflict{conflicts.length > 1 ? "s" : ""}
            </span>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={handleResetAll}
            className="h-7 px-2 text-xs text-text-muted hover:text-text-primary gap-1.5"
            aria-label="Reset all shortcuts to defaults"
          >
            <RotateCcw size={12} />
            Reset to defaults
          </Button>
        </div>
      </div>

      {/* Grouped sections */}
      <div className="space-y-6">
        {grouped.map(({ category, label, entries }) => (
          <section key={category} aria-labelledby={`shortcut-group-${category}`}>
            <h3
              id={`shortcut-group-${category}`}
              className="text-xs font-medium text-text-muted uppercase tracking-widest mb-2"
            >
              {label}
            </h3>
            <div className="space-y-1">
              {entries.map((binding) => {
                const conflict = conflicts.find((c) =>
                  c.bindingIds.includes(binding.id),
                );
                return (
                  <ShortcutRow
                    key={binding.id}
                    binding={binding}
                    allBindings={bindings}
                    conflict={conflict}
                    onUpdate={handleUpdate}
                  />
                );
              })}
            </div>
          </section>
        ))}
      </div>

      {/* Conflict summary */}
      {conflicts.length > 0 && (
        <div
          className="mt-4 p-3 rounded-glass-inner border border-amber-500/30 bg-amber-500/5"
          role="alert"
          aria-label="Shortcut conflicts detected"
        >
          <p className="text-xs font-medium text-amber-400 mb-1.5 flex items-center gap-1.5">
            <AlertTriangle size={12} />
            Shortcut conflicts detected
          </p>
          <ul className="space-y-1">
            {conflicts.map((c) => (
              <li key={c.combo} className="text-xs text-text-muted">
                <span className="font-mono text-text-secondary">{c.combo}</span>
                {" "}— assigned to:{" "}
                {c.bindingIds
                  .map(
                    (id) =>
                      bindings.find((b) => b.id === id)?.action ?? id,
                  )
                  .join(", ")}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-4 text-xs text-text-muted">
        Shortcuts marked &ldquo;System&rdquo; cannot be customised. All others
        fire only when no input field is focused.{" "}
        {conflictIds.size > 0
          ? "Conflicting shortcuts may behave unpredictably."
          : ""}
      </p>
    </div>
  );
}

// Re-export for convenience
export { formatKeyCombo };
