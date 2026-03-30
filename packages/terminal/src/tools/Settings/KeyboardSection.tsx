/**
 * KeyboardSection — customizable keyboard shortcuts display.
 *
 * Shows current hotkey assignments with ability to remap customizable keys.
 * Stores customizations in localStorage via hotkeyStore.
 * Includes conflict detection and reset-to-default functionality.
 */

import { useState, useCallback, useEffect, useRef } from "react";
import { RotateCcw, AlertTriangle, Pencil, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SectionTitle } from "./shared";
import {
  loadCustomHotkeys,
  saveHotkeyOverride,
  resetHotkeyToDefault,
  resetAllHotkeys,
  detectConflicts,
  findConflict,
  normalizeKeyCombo,
  eventToKeys,
  formatKeyCombo,
  DEFAULT_HOTKEYS,
  type HotkeyBinding,
} from "@/lib/hotkeyStore";

// ---------------------------------------------------------------------------
// Key capture hook
// ---------------------------------------------------------------------------

function useKeyCapture(
  active: boolean,
  onCapture: (keys: string[]) => void,
  onCancel: () => void,
) {
  useEffect(() => {
    if (!active) return;

    function handler(e: KeyboardEvent) {
      e.preventDefault();
      e.stopPropagation();

      // Escape cancels capture
      if (e.key === "Escape") {
        onCancel();
        return;
      }

      // Ignore bare modifier presses
      const ignoreKeys = new Set(["Control", "Shift", "Alt", "Meta"]);
      if (ignoreKeys.has(e.key)) return;

      const keys = eventToKeys(e);
      if (keys.length > 0) {
        onCapture(keys);
      }
    }

    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [active, onCapture, onCancel]);
}

// ---------------------------------------------------------------------------
// Kbd display component
// ---------------------------------------------------------------------------

function KbdDisplay({ keys, muted = false }: { keys: string[]; muted?: boolean }) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      {keys.map((k, i) => (
        <span key={i}>
          <kbd
            className={`px-1.5 py-0.5 text-xs font-mono font-medium border rounded ${
              muted
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
  );
}

// ---------------------------------------------------------------------------
// Shortcut row — editable
// ---------------------------------------------------------------------------

interface EditableShortcutRowProps {
  binding: HotkeyBinding;
  isDefault: boolean;
  conflictWith: string | null;
  onRemap: (id: string, keys: string[]) => void;
  onReset: (id: string) => void;
}

function EditableShortcutRow({
  binding,
  isDefault,
  conflictWith,
  onRemap,
  onReset,
}: EditableShortcutRowProps) {
  const [editing, setEditing] = useState(false);
  const [capturedKeys, setCapturedKeys] = useState<string[] | null>(null);
  const rowRef = useRef<HTMLDivElement>(null);

  const handleCapture = useCallback(
    (keys: string[]) => {
      setCapturedKeys(keys);
    },
    [],
  );

  const handleCancel = useCallback(() => {
    setEditing(false);
    setCapturedKeys(null);
  }, []);

  useKeyCapture(editing && capturedKeys === null, handleCapture, handleCancel);

  function handleConfirm() {
    if (capturedKeys) {
      onRemap(binding.id, capturedKeys);
    }
    setEditing(false);
    setCapturedKeys(null);
  }

  function handleReject() {
    setCapturedKeys(null);
    // Stay in editing mode to capture again
  }

  function handleStartEdit() {
    setEditing(true);
    setCapturedKeys(null);
  }

  return (
    <div
      ref={rowRef}
      className={`flex items-start justify-between py-2 border-b border-border-default last:border-0 gap-4 ${
        conflictWith ? "bg-yellow-900/10" : ""
      }`}
    >
      <div className="flex flex-col gap-0.5 min-w-0 flex-1">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xs text-text-secondary">{binding.action}</span>
          {!binding.customizable && (
            <span className="text-[10px] font-medium text-text-muted bg-surface-base border border-border-default rounded px-1 py-px leading-none">
              System
            </span>
          )}
          {!isDefault && binding.customizable && (
            <span className="text-[10px] font-medium text-accent bg-accent/10 border border-accent/20 rounded px-1 py-px leading-none">
              Custom
            </span>
          )}
          {conflictWith && (
            <span className="text-[10px] font-medium text-yellow-400 flex items-center gap-0.5">
              <AlertTriangle size={9} />
              Conflicts with: {conflictWith}
            </span>
          )}
        </div>
        {binding.description && (
          <span className="text-xxs text-text-muted">{binding.description}</span>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {editing ? (
          capturedKeys ? (
            // Show captured key with confirm/reject
            <div className="flex items-center gap-1">
              <KbdDisplay keys={capturedKeys} />
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 text-profit hover:text-profit"
                onClick={handleConfirm}
                aria-label="Confirm new shortcut"
              >
                <Check size={11} />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 text-loss hover:text-loss"
                onClick={handleReject}
                aria-label="Reject and try again"
              >
                <X size={11} />
              </Button>
            </div>
          ) : (
            // Waiting for keypress
            <div className="flex items-center gap-1">
              <Badge className="bg-accent/15 text-accent border-accent/20 text-xxs animate-pulse">
                Press key combo...
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                className="h-5 w-5 p-0 text-text-muted hover:text-loss"
                onClick={handleCancel}
                aria-label="Cancel editing"
              >
                <X size={11} />
              </Button>
            </div>
          )
        ) : (
          // Normal display
          <>
            <KbdDisplay keys={binding.keys} />
            {binding.customizable && (
              <div className="flex items-center gap-0.5">
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0 text-text-muted hover:text-text-primary"
                  onClick={handleStartEdit}
                  aria-label={`Remap ${binding.action}`}
                >
                  <Pencil size={10} />
                </Button>
                {!isDefault && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 w-5 p-0 text-text-muted hover:text-accent"
                    onClick={() => onReset(binding.id)}
                    aria-label={`Reset ${binding.action} to default`}
                  >
                    <RotateCcw size={10} />
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Category group
// ---------------------------------------------------------------------------

function CategoryGroup({
  label,
  bindings,
  defaultBindings,
  conflicts,
  onRemap,
  onReset,
}: {
  label: string;
  bindings: HotkeyBinding[];
  defaultBindings: HotkeyBinding[];
  conflicts: Map<string, string>;
  onRemap: (id: string, keys: string[]) => void;
  onReset: (id: string) => void;
}) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
        {label}
      </p>
      <div className="rounded border border-border-default overflow-hidden px-3">
        {bindings.map((b) => {
          const def = defaultBindings.find((d) => d.id === b.id);
          const isDefault = def
            ? normalizeKeyCombo(b.keys) === normalizeKeyCombo(def.keys)
            : true;
          return (
            <EditableShortcutRow
              key={b.id}
              binding={b}
              isDefault={isDefault}
              conflictWith={conflicts.get(b.id) ?? null}
              onRemap={onRemap}
              onReset={onReset}
            />
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main section
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  global: "Global",
  scalper: "Scalper — Position Management",
  trading: "Quick Trading",
  chart: "Chart",
};

const CATEGORY_ORDER: string[] = ["global", "scalper", "trading", "chart"];

export function KeyboardSection() {
  const [bindings, setBindings] = useState<HotkeyBinding[]>(() =>
    loadCustomHotkeys(),
  );

  // Conflict detection
  const conflictMap = new Map<string, string>();
  const detected = detectConflicts(bindings);
  for (const c of detected) {
    for (const id of c.bindingIds) {
      const others = c.bindingIds.filter((oid) => oid !== id);
      const otherNames = others
        .map((oid) => bindings.find((b) => b.id === oid)?.action ?? oid)
        .join(", ");
      conflictMap.set(id, otherNames);
    }
  }

  function handleRemap(id: string, keys: string[]) {
    // Check conflict before saving
    const conflictId = findConflict(keys, id, bindings);
    if (conflictId) {
      const conflictBinding = bindings.find((b) => b.id === conflictId);
      const proceed = window.confirm(
        `"${formatKeyCombo(keys)}" is already assigned to "${conflictBinding?.action ?? conflictId}". Assign anyway?`,
      );
      if (!proceed) return;
    }

    saveHotkeyOverride(id, keys);
    setBindings(loadCustomHotkeys());
  }

  function handleReset(id: string) {
    resetHotkeyToDefault(id);
    setBindings(loadCustomHotkeys());
  }

  function handleResetAll() {
    const proceed = window.confirm(
      "Reset all keyboard shortcuts to defaults? This cannot be undone.",
    );
    if (!proceed) return;
    resetAllHotkeys();
    setBindings(loadCustomHotkeys());
  }

  // Group by category
  const grouped = new Map<string, HotkeyBinding[]>();
  for (const b of bindings) {
    const list = grouped.get(b.category) ?? [];
    list.push(b);
    grouped.set(b.category, list);
  }

  const hasCustomizations = bindings.some((b) => {
    const def = DEFAULT_HOTKEYS.find((d) => d.id === b.id);
    return def && normalizeKeyCombo(b.keys) !== normalizeKeyCombo(def.keys);
  });

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <SectionTitle>Keyboard Shortcuts</SectionTitle>
        {hasCustomizations && (
          <Button
            variant="ghost"
            size="sm"
            className="h-6 px-2 text-xs text-text-muted hover:text-loss gap-1"
            onClick={handleResetAll}
          >
            <RotateCcw size={11} />
            Reset All
          </Button>
        )}
      </div>

      <div className="p-3 rounded bg-surface-card border border-border-default text-xs text-text-muted">
        Click the pencil icon to remap a shortcut. Press your desired key combination, then confirm.
        System shortcuts cannot be changed. Conflicts are highlighted in yellow.
      </div>

      {detected.length > 0 && (
        <div className="p-3 rounded bg-yellow-900/15 border border-yellow-700/30 text-xs text-yellow-400 flex items-center gap-2">
          <AlertTriangle size={13} className="shrink-0" />
          <span>
            {detected.length} conflict{detected.length > 1 ? "s" : ""} detected.
            Some shortcuts share the same key combination.
          </span>
        </div>
      )}

      {CATEGORY_ORDER.map((cat) => {
        const catBindings = grouped.get(cat);
        if (!catBindings || catBindings.length === 0) return null;
        return (
          <CategoryGroup
            key={cat}
            label={CATEGORY_LABELS[cat] ?? cat}
            bindings={catBindings}
            defaultBindings={DEFAULT_HOTKEYS}
            conflicts={conflictMap}
            onRemap={handleRemap}
            onReset={handleReset}
          />
        );
      })}
    </div>
  );
}
