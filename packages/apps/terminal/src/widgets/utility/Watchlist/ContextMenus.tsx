/**
 * ContextMenus — symbol context menu, tab context menu, and rename input
 * for WatchlistWidget.
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { Trash2, Pencil, Copy } from "lucide-react";

// ---------------------------------------------------------------------------
// SymbolContextMenu
// ---------------------------------------------------------------------------

export interface SymbolContextMenuProps {
  x:        number;
  y:        number;
  symbol:   string;
  onRemove: () => void;
  onClose:  () => void;
}

export function SymbolContextMenu({ x, y, symbol, onRemove, onClose }: SymbolContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handle);
    document.addEventListener("contextmenu", handle);
    return () => {
      document.removeEventListener("mousedown", handle);
      document.removeEventListener("contextmenu", handle);
    };
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`Actions for ${symbol}`}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-36"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-xs text-text-muted font-mono">{symbol}</span>
      </div>
      <button
        role="menuitem"
        onClick={onRemove}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
      >
        <Trash2 size={10} />
        Remove
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TabContextMenu
// ---------------------------------------------------------------------------

export interface TabContextMenuProps {
  x:           number;
  y:           number;
  tabName:     string;
  canDelete:   boolean;
  onRename:    () => void;
  onDuplicate: () => void;
  onDelete:    () => void;
  onClose:     () => void;
}

export function TabContextMenu({
  x, y, tabName, canDelete, onRename, onDuplicate, onDelete, onClose,
}: TabContextMenuProps) {
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  return (
    <div
      ref={menuRef}
      role="menu"
      aria-label={`Tab actions for ${tabName}`}
      className="fixed z-50 bg-surface-card border border-border-default rounded shadow-2xl py-1 min-w-40"
      style={{ top: y, left: x }}
    >
      <div className="px-3 py-1 border-b border-border-subtle mb-1">
        <span className="text-xs text-text-muted truncate">{tabName}</span>
      </div>
      <button
        role="menuitem"
        onClick={onRename}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <Pencil size={10} />
        Rename
      </button>
      <button
        role="menuitem"
        onClick={onDuplicate}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <Copy size={10} />
        Duplicate
      </button>
      {canDelete && (
        <>
          <div className="border-t border-border-subtle my-1" />
          <button
            role="menuitem"
            onClick={onDelete}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-loss hover:bg-loss/10 transition-colors"
          >
            <Trash2 size={10} />
            Delete
          </button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// RenameInput
// ---------------------------------------------------------------------------

export interface RenameInputProps {
  initialValue: string;
  onConfirm:    (name: string) => void;
  onCancel:     () => void;
}

export function RenameInput({ initialValue, onConfirm, onCancel }: RenameInputProps) {
  const [value, setValue] = useState(initialValue);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const commit = useCallback(() => {
    const trimmed = value.trim();
    if (trimmed) onConfirm(trimmed);
    else onCancel();
  }, [value, onConfirm, onCancel]);

  const handleKey = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter")  commit();
    if (e.key === "Escape") onCancel();
  }, [commit, onCancel]);

  return (
    <input
      ref={inputRef}
      type="text"
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={commit}
      onKeyDown={handleKey}
      className="w-24 h-4 bg-surface-elevated border border-accent/50 text-text-primary text-xs rounded px-1 focus:outline-none"
      maxLength={20}
    />
  );
}
