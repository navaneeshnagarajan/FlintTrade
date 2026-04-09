/**
 * CommandPalette.tsx
 *
 * Ctrl+K command palette for the FlintTrade terminal.
 * Adapted from openalgo-chart's CommandPalette (JSX + CSS Modules)
 * into TypeScript + Tailwind CSS v4, using FlintTrade design tokens.
 *
 * Keyboard:
 *   ArrowUp / ArrowDown  — move selection
 *   Enter                — execute selected command
 *   Escape               — close
 *
 * Behaviour:
 *   - No query: shows "Recent" section + all categories grouped
 *   - With query: shows filtered results (case-insensitive substring match)
 *   - Input is auto-focused when modal opens
 *   - Active item is scrolled into view
 */

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
} from "react";
import {
  Search,
  LayoutGrid,
  Wrench,
  Navigation,
  Zap,
  Palette,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  useCommandRegistry,
} from "./useCommandRegistry";
import type { Command, CommandCategory, GroupedCommands } from "./useCommandRegistry";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Category icon map
// ---------------------------------------------------------------------------

const CATEGORY_ICONS: Record<CommandCategory, React.ReactNode> = {
  widget:   <LayoutGrid  size={13} aria-hidden="true" />,
  tool:     <Wrench      size={13} aria-hidden="true" />,
  navigate: <Navigation  size={13} aria-hidden="true" />,
  action:   <Zap         size={13} aria-hidden="true" />,
  theme:    <Palette     size={13} aria-hidden="true" />,
};

// ---------------------------------------------------------------------------
// Highlight matching text
// ---------------------------------------------------------------------------

function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <span className="text-accent font-medium">{text.slice(idx, idx + query.length)}</span>
      {text.slice(idx + query.length)}
    </>
  );
}

// ---------------------------------------------------------------------------
// Single command row
// ---------------------------------------------------------------------------

interface CommandRowProps {
  cmd: Command;
  isActive: boolean;
  query: string;
  flatIndex: number;
  onMouseEnter: () => void;
  onClick: () => void;
  rowRef?: React.RefCallback<HTMLLIElement>;
}

function CommandRow({ cmd, isActive, query, onMouseEnter, onClick, rowRef, flatIndex }: CommandRowProps) {
  return (
    <li
      ref={rowRef}
      id={`cmd-item-${flatIndex}`}
      role="option"
      aria-selected={isActive}
      onMouseEnter={onMouseEnter}
      onClick={onClick}
      className={cn(
        "flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
        isActive ? "bg-surface-hover" : "hover:bg-surface-hover/60",
      )}
    >
      {/* Category icon */}
      <span
        className={cn(
          "shrink-0 flex items-center justify-center w-6 h-6 rounded text-text-muted",
          isActive && "text-accent",
        )}
        aria-hidden="true"
      >
        {CATEGORY_ICONS[cmd.category]}
      </span>

      {/* Title + description */}
      <span className="flex-1 min-w-0">
        <span className="block text-sm text-text-primary leading-snug truncate">
          <HighlightMatch text={cmd.title} query={query} />
        </span>
        {cmd.description && (
          <span className="block text-xs text-text-muted leading-snug truncate mt-0.5">
            {cmd.description}
          </span>
        )}
      </span>

      {/* Shortcut badge */}
      {cmd.shortcut && (
        <kbd
          aria-label={`Shortcut: ${cmd.shortcut}`}
          className="shrink-0 font-mono text-[10px] text-text-muted bg-surface-base border border-border-default rounded px-1.5 py-0.5 leading-none whitespace-nowrap"
        >
          {cmd.shortcut}
        </kbd>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Section header within the results list
// ---------------------------------------------------------------------------

function SectionLabel({ label }: { label: React.ReactNode }) {
  return (
    <li
      role="presentation"
      className="px-4 py-1.5 text-[10px] font-medium text-text-muted uppercase tracking-widest font-heading border-b border-border-subtle/50 bg-surface-base/30"
      aria-hidden="true"
    >
      {label}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Flat item type for keyboard navigation list
// ---------------------------------------------------------------------------

type FlatItem =
  | { type: "section"; label: string }
  | { type: "command"; cmd: Command; flatIndex: number };

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CommandPalette({ isOpen, onClose }: CommandPaletteProps) {
  const { recentCommands, groupedCommands, searchCommands, executeCommand } =
    useCommandRegistry();

  const [query, setQuery]               = useState("");
  const [activeIndex, setActiveIndex]   = useState(0);

  const inputRef        = useRef<HTMLInputElement>(null);
  const listRef         = useRef<HTMLUListElement>(null);
  // Maps flat item index → li element for scrollIntoView
  const itemRefs        = useRef<Map<number, HTMLLIElement>>(new Map());

  // ---- Build flat item list for keyboard navigation -------------------------
  // Section entries are non-selectable separators; only "command" entries
  // count toward the navigable index.

  const { flatItems, selectableCount } = useMemo<{
    flatItems: FlatItem[];
    selectableCount: number;
  }>(() => {
    const items: FlatItem[] = [];
    let selectableIdx = 0;

    if (!query) {
      // No query: show recents + full grouped catalogue
      if (recentCommands.length > 0) {
        items.push({ type: "section", label: "Recent" });
        for (const cmd of recentCommands) {
          items.push({ type: "command", cmd, flatIndex: selectableIdx++ });
        }
      }
      for (const group of groupedCommands) {
        items.push({ type: "section", label: group.label });
        for (const cmd of group.commands) {
          items.push({ type: "command", cmd, flatIndex: selectableIdx++ });
        }
      }
    } else {
      // Query: show filtered results in a single flat list
      const results = searchCommands(query);
      if (results.length === 0) {
        // Empty state — handled in render below
      } else {
        items.push({ type: "section", label: "Results" });
        for (const cmd of results) {
          items.push({ type: "command", cmd, flatIndex: selectableIdx++ });
        }
      }
    }

    return { flatItems: items, selectableCount: selectableIdx };
  }, [query, recentCommands, groupedCommands, searchCommands]);

  // ---- Clamp activeIndex when list changes ----------------------------------
  useEffect(() => {
    setActiveIndex(0);
  }, [query, selectableCount]);

  // ---- Scroll active row into view -----------------------------------------
  useEffect(() => {
    const el = itemRefs.current.get(activeIndex);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  // ---- Focus input when opened ---------------------------------------------
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setActiveIndex(0);
      // Defer to next frame so the modal has rendered
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // ---- Keyboard navigation -------------------------------------------------
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((prev) => (prev + 1) % Math.max(1, selectableCount));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((prev) =>
          (prev - 1 + Math.max(1, selectableCount)) % Math.max(1, selectableCount),
        );
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        // Find the command at activeIndex
        const target = flatItems.find(
          (item): item is Extract<FlatItem, { type: "command" }> =>
            item.type === "command" && item.flatIndex === activeIndex,
        );
        if (target) {
          executeCommand(target.cmd);
          onClose();
        }
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    },
    [activeIndex, selectableCount, flatItems, executeCommand, onClose],
  );

  // ---- Close on overlay click ----------------------------------------------
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  // ---- Reset itemRefs on every render so stale entries don't linger --------
  itemRefs.current.clear();

  if (!isOpen) return null;

  const isEmpty = query !== "" && selectableCount === 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] bg-black/50 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div
        className={cn(
          "w-full max-w-lg mx-4 flex flex-col",
          "bg-surface-card border border-border-default rounded-xl shadow-2xl overflow-hidden",
          "animate-in fade-in slide-in-from-top-4 duration-200",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* ---- Search input ---- */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border-default">
          <Search size={16} className="shrink-0 text-text-muted" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            role="combobox"
            aria-expanded="true"
            aria-autocomplete="list"
            aria-controls="cmd-palette-list"
            aria-activedescendant={
              selectableCount > 0 ? `cmd-item-${activeIndex}` : undefined
            }
            placeholder="Search commands..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className={cn(
              "flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted",
              "outline-none border-none ring-0 focus:outline-none",
            )}
            spellCheck={false}
            autoComplete="off"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => { setQuery(""); inputRef.current?.focus(); }}
              className="shrink-0 text-text-muted hover:text-text-primary transition-colors"
            >
              <span aria-hidden="true" className="text-xs">✕</span>
            </button>
          )}
        </div>

        {/* ---- Results list ---- */}
        <ul
          id="cmd-palette-list"
          ref={listRef}
          role="listbox"
          aria-label="Commands"
          className="overflow-y-auto max-h-105 py-1"
        >
          {isEmpty ? (
            <li
              role="presentation"
              className="flex flex-col items-center justify-center gap-2 py-12 text-center"
            >
              <Search size={24} className="text-text-muted/50" aria-hidden="true" />
              <p className="text-sm text-text-muted">
                No commands match <span className="text-text-secondary">&ldquo;{query}&rdquo;</span>
              </p>
            </li>
          ) : (
            flatItems.map((item, i) => {
              if (item.type === "section") {
                return (
                  <SectionLabel
                    key={`section-${item.label}-${i}`}
                    label={
                      item.label === "Recent" ? (
                        <span className="flex items-center gap-1.5">
                          <Clock size={9} aria-hidden="true" />
                          {item.label}
                        </span>
                      ) : item.label
                    }
                  />
                );
              }

              const { cmd, flatIndex } = item;
              return (
                <CommandRow
                  key={cmd.id}
                  cmd={cmd}
                  flatIndex={flatIndex}
                  isActive={flatIndex === activeIndex}
                  query={query}
                  onMouseEnter={() => setActiveIndex(flatIndex)}
                  onClick={() => {
                    executeCommand(cmd);
                    onClose();
                  }}
                  rowRef={(el) => {
                    if (el) itemRefs.current.set(flatIndex, el);
                  }}
                />
              );
            })
          )}
        </ul>

        {/* ---- Footer ---- */}
        <div
          aria-hidden="true"
          className="flex items-center gap-4 px-4 py-2 border-t border-border-default bg-surface-base/50"
        >
          <FooterHint keys="↑↓" label="Navigate" />
          <FooterHint keys="↵" label="Execute" />
          <FooterHint keys="Esc" label="Close" />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Footer hint pill
// ---------------------------------------------------------------------------

function FooterHint({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-text-muted">
      <kbd className="font-mono text-[10px] bg-surface-elevated border border-border-default rounded px-1 py-0.5 leading-none">
        {keys}
      </kbd>
      <span>{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Re-export types so callers can import from the barrel without going deeper
// ---------------------------------------------------------------------------
export type { Command, CommandCategory, GroupedCommands };
