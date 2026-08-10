/**
 * KeyboardShortcutsDialog — Modal reference card for all keyboard shortcuts.
 *
 * Triggered by pressing `?` (when no input is focused) or from Settings.
 * Groups shortcuts by category, supports search filtering, and renders
 * platform-aware key labels (⌘ on macOS, Ctrl on Windows/Linux).
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Search, X, Keyboard } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------

function isMac(): boolean {
  if (typeof navigator === "undefined") return false;
  return /mac/i.test(navigator.platform) || /mac/i.test(navigator.userAgent);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ShortcutEntry {
  /** Unique identifier */
  id: string;
  /** Human-readable label */
  label: string;
  /** Key tokens to display, e.g. ["Ctrl", "K"] or ["?"] */
  keys: string[];
  /** Category this shortcut belongs to */
  category: ShortcutCategory;
}

export type ShortcutCategory = "Navigation" | "Trading" | "Chart" | "General";

// ---------------------------------------------------------------------------
// Shortcut definitions
// ---------------------------------------------------------------------------

export const SHORTCUT_ENTRIES: ShortcutEntry[] = [
  // Navigation
  {
    id: "command-palette",
    label: "Command palette / symbol search",
    keys: ["Ctrl", "K"],
    category: "Navigation",
  },
  {
    id: "open-settings",
    label: "Open settings",
    keys: ["Ctrl", ","],
    category: "Navigation",
  },
  {
    id: "escape",
    label: "Close modal or tool overlay",
    keys: ["Esc"],
    category: "Navigation",
  },
  {
    id: "go-home",
    label: "Go to Home",
    keys: ["Alt", "H"],
    category: "Navigation",
  },
  {
    id: "go-trade",
    label: "Go to Trade",
    keys: ["Alt", "T"],
    category: "Navigation",
  },

  // Trading
  {
    id: "exit-confirm",
    label: "Exit all positions (with confirmation)",
    keys: ["X"],
    category: "Trading",
  },
  {
    id: "exit-immediate",
    label: "Force exit all positions (no confirmation)",
    keys: ["Shift", "X"],
    category: "Trading",
  },
  {
    id: "cancel-orders",
    label: "Cancel all open orders",
    keys: ["C"],
    category: "Trading",
  },
  {
    id: "quick-buy",
    label: "Quick buy at market price",
    keys: ["B"],
    category: "Trading",
  },
  {
    id: "quick-sell",
    label: "Quick sell at market price",
    keys: ["S"],
    category: "Trading",
  },
  {
    id: "flatten-all",
    label: "Flatten — close positions and cancel orders",
    keys: ["F"],
    category: "Trading",
  },

  // Chart
  {
    id: "chart-interval-1",
    label: "Switch chart interval (1 = 1m, 2 = 5m … 9 = 1D)",
    keys: ["1–9"],
    category: "Chart",
  },
  {
    id: "chart-replay",
    label: "Toggle chart replay mode",
    keys: ["R"],
    category: "Chart",
  },
  {
    id: "chart-drawing",
    label: "Toggle drawing tools",
    keys: ["D"],
    category: "Chart",
  },
  {
    id: "toggle-timeframe",
    label: "Cycle chart timeframes",
    keys: ["T"],
    category: "Chart",
  },

  // General
  {
    id: "show-shortcuts",
    label: "Show this keyboard shortcuts reference",
    keys: ["?"],
    category: "General",
  },
  {
    id: "fullscreen",
    label: "Toggle fullscreen",
    keys: ["F11"],
    category: "General",
  },
  {
    id: "save-layout",
    label: "Save current workspace layout",
    keys: ["Ctrl", "S"],
    category: "General",
  },
];

const CATEGORY_ORDER: ShortcutCategory[] = [
  "Navigation",
  "Trading",
  "Chart",
  "General",
];

// ---------------------------------------------------------------------------
// Key badge helpers
// ---------------------------------------------------------------------------

/** Translates "Ctrl" to "⌘" on macOS. */
function resolveKeyLabel(token: string, mac: boolean): string {
  if (mac && token === "Ctrl") return "⌘";
  if (mac && token === "Alt") return "⌥";
  if (mac && token === "Shift") return "⇧";
  return token;
}

interface KeyBadgeProps {
  token: string;
  mac: boolean;
}

function KeyBadge({ token, mac }: KeyBadgeProps) {
  const label = resolveKeyLabel(token, mac);
  // Single-char tokens (letter, digit, symbol) get slightly wider padding.
  const isSingleChar = label.length === 1;
  return (
    <kbd
      className={cn(
        "inline-flex items-center justify-center rounded border border-border-default",
        "bg-surface-base text-text-secondary font-mono text-[11px] leading-none",
        "select-none shrink-0",
        isSingleChar ? "h-5 min-w-5 px-1.5" : "h-5 px-2",
      )}
    >
      {label}
    </kbd>
  );
}

interface KeyComboProps {
  keys: string[];
  mac: boolean;
}

function KeyCombo({ keys, mac }: KeyComboProps) {
  return (
    <span className="flex items-center gap-1" aria-label={keys.join(" + ")}>
      {keys.map((k, i) => (
        <KeyBadge key={i} token={k} mac={mac} />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Shortcut row
// ---------------------------------------------------------------------------

interface ShortcutRowProps {
  entry: ShortcutEntry;
  mac: boolean;
  query: string;
}

function highlightMatch(text: string, query: string) {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="bg-accent/25 text-accent rounded-sm not-italic">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

function ShortcutRow({ entry, mac, query }: ShortcutRowProps) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 border-b border-border-default/50 last:border-0">
      <span className="text-sm text-text-secondary leading-snug flex-1 min-w-0">
        {highlightMatch(entry.label, query)}
      </span>
      <KeyCombo keys={entry.keys} mac={mac} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Category section
// ---------------------------------------------------------------------------

interface CategorySectionProps {
  category: ShortcutCategory;
  entries: ShortcutEntry[];
  mac: boolean;
  query: string;
}

function CategorySection({ category, entries, mac, query }: CategorySectionProps) {
  return (
    <section aria-labelledby={`shortcut-cat-${category.toLowerCase()}`}>
      <h3
        id={`shortcut-cat-${category.toLowerCase()}`}
        className="text-xs font-heading font-medium text-text-muted uppercase tracking-widest mb-2 mt-1"
      >
        {category}
      </h3>
      <div role="list" aria-label={`${category} shortcuts`}>
        {entries.map((entry) => (
          <div key={entry.id} role="listitem">
            <ShortcutRow entry={entry} mac={mac} query={query} />
          </div>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Main dialog
// ---------------------------------------------------------------------------

export interface KeyboardShortcutsDialogProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function KeyboardShortcutsDialog({
  isOpen,
  onClose,
}: KeyboardShortcutsDialogProps) {
  const [query, setQuery] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const mac = isMac();

  // Auto-focus search and reset on open/close.
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => searchRef.current?.focus(), 50);
      return () => clearTimeout(timer);
    } else {
      setQuery("");
    }
  }, [isOpen]);

  const handleClose = useCallback(() => {
    setQuery("");
    onClose();
  }, [onClose]);

  const trimmed = query.trim();
  const isSearching = trimmed.length > 0;

  // Filter entries by label.
  const filtered = isSearching
    ? SHORTCUT_ENTRIES.filter((e) =>
        e.label.toLowerCase().includes(trimmed.toLowerCase()) ||
        e.keys.some((k) => k.toLowerCase().includes(trimmed.toLowerCase())),
      )
    : SHORTCUT_ENTRIES;

  // Group by category in the defined order.
  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    entries: filtered.filter((e) => e.category === cat),
  })).filter((g) => g.entries.length > 0);

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent
        className="sm:max-w-lg max-h-[80vh] flex flex-col bg-surface-card border-border-default p-0 animate-fade-in-scale"
        aria-describedby="kbd-shortcuts-desc"
      >
        <DialogHeader className="px-6 pt-5 pb-3 border-b border-border-default">
          <div className="flex items-center gap-2">
            <Keyboard
              className="w-4 h-4 text-text-muted shrink-0"
              aria-hidden="true"
            />
            <DialogTitle className="text-sm font-semibold text-text-primary tracking-wide">
              Keyboard Shortcuts
            </DialogTitle>
          </div>
          <p
            id="kbd-shortcuts-desc"
            className="text-xs text-text-muted mt-0.5"
          >
            {mac ? "⌘ = Command key on macOS" : "Ctrl key shortcuts"}
          </p>

          {/* Search */}
          <div className="relative mt-3">
            <Search
              className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-text-muted pointer-events-none"
              aria-hidden="true"
            />
            <Input
              ref={searchRef}
              type="search"
              role="searchbox"
              aria-label="Search shortcuts"
              placeholder="Search shortcuts…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-8 h-8 text-sm bg-surface-base border-border-default placeholder:text-text-muted focus-visible:ring-accent/40"
            />
            {isSearching && (
              <button
                type="button"
                aria-label="Clear search"
                onClick={() => {
                  setQuery("");
                  searchRef.current?.focus();
                }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-text-muted hover:text-text-primary transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </DialogHeader>

        {/* Shortcut list */}
        <div className="overflow-y-auto flex-1 min-h-0 px-6 py-4">
          {grouped.length > 0 ? (
            <div className="space-y-5">
              {grouped.map(({ category, entries }) => (
                <CategorySection
                  key={category}
                  category={category}
                  entries={entries}
                  mac={mac}
                  query={trimmed}
                />
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 gap-2">
              <Search
                className="w-8 h-8 text-text-muted/40"
                aria-hidden="true"
              />
              <p className="text-sm text-text-muted">
                No shortcuts match &ldquo;{trimmed}&rdquo;
              </p>
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="px-6 py-3 border-t border-border-default">
          <p className="text-xs text-text-muted">
            Shortcuts fire only when no input field is focused.
          </p>
        </div>
      </DialogContent>
    </Dialog>
  );
}
