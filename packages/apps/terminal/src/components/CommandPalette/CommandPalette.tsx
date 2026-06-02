/**
 * CommandPalette.tsx
 *
 * Unified Search — Ctrl+K command palette with 4 tabs:
 *   Symbols (default) | Commands (/ prefix) | Widgets (# prefix) | Ask AI (@ai prefix)
 *
 * Glass Adaptive design. AnimatedTabs from Aceternity.
 * Keyboard: ArrowUp/Down navigate, Enter selects, Tab switches tab, Escape closes.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { Search } from "lucide-react";
import { AnimatedTabs, type TabItem } from "@/components/aceternity/animated-tabs";
import { PaletteShell } from "./PaletteShell";
import { CommandsTab } from "./CommandsTab";
import { WidgetsTab } from "./WidgetsTab";
import { SymbolSearchTab } from "./SymbolSearchTab";
import { AITab } from "./AITab";
import { DocsTab } from "./DocsTab";
import { useCommandRegistry } from "./useCommandRegistry";
import type { Command } from "./useCommandRegistry";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Tab type + prefix detection
// ---------------------------------------------------------------------------

type PaletteTab = "symbols" | "commands" | "widgets" | "ai" | "docs";

function detectTab(query: string): PaletteTab | null {
  if (query.startsWith("/")) return "commands";
  if (query.startsWith("#")) return "widgets";
  if (query.toLowerCase().startsWith("@ai")) return "ai";
  if (query.startsWith("?")) return "docs";
  return null;
}

function stripPrefix(query: string, tab: PaletteTab): string {
  if (tab === "commands" && query.startsWith("/")) return query.slice(1).trim();
  if (tab === "widgets" && query.startsWith("#")) return query.slice(1).trim();
  if (tab === "ai" && query.toLowerCase().startsWith("@ai")) return query.slice(3).trim();
  if (tab === "docs" && query.startsWith("?")) return query.slice(1).trim();
  return query;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function CommandPalette({ isOpen, onClose }: CommandPaletteProps) {
  const { commandsByCategory, executeCommand } = useCommandRegistry();
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<PaletteTab>("symbols");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset state on open
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setActiveTab("symbols");
      setActiveIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // Prefix-based tab routing
  const handleQueryChange = useCallback((value: string) => {
    setQuery(value);
    const detected = detectTab(value);
    if (detected) {
      setActiveTab(detected);
      setActiveIndex(0);
    }
  }, []);

  // Keyboard navigation
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((p) => p + 1); // tabs clamp via onActiveIndexChange
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((p) => Math.max(0, p - 1));
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        const tabs: PaletteTab[] = ["symbols", "commands", "widgets", "ai", "docs"];
        const idx = tabs.indexOf(activeTab);
        setActiveTab(tabs[(idx + (e.shiftKey ? -1 + tabs.length : 1)) % tabs.length]);
        setActiveIndex(0);
      }
    },
    [onClose, activeTab],
  );

  // Execute command + close
  const handleCommandSelect = useCallback(
    (cmd: Command) => {
      executeCommand(cmd);
      onClose();
    },
    [executeCommand, onClose],
  );

  // Symbol quick actions
  const handleSymbolSelect = useCallback(
    (symbol: string, exchange: string, action: "chart" | "buy" | "sell" | "ai") => {
      onClose();
      if (action === "chart") {
        window.dispatchEvent(
          new CustomEvent("flinttrade:addWidget", { detail: { widgetId: "chart", props: { symbol, exchange } } }),
        );
      } else if (action === "buy" || action === "sell") {
        window.dispatchEvent(
          new CustomEvent("flinttrade:addWidget", {
            detail: { widgetId: "orderpad", props: { symbol, exchange, side: action.toUpperCase() } },
          }),
        );
      } else if (action === "ai") {
        window.dispatchEvent(
          new CustomEvent("flinttrade:navigate", { detail: { path: "/ai", context: { symbol, exchange } } }),
        );
      }
    },
    [onClose],
  );

  const tabQuery = stripPrefix(query, activeTab);

  const tabs: TabItem[] = [
    {
      id: "symbols",
      label: "Symbols",
      content: (
        <SymbolSearchTab
          query={activeTab === "symbols" ? tabQuery : ""}
          activeIndex={activeIndex}
          onSelectSymbol={handleSymbolSelect}
          onActiveIndexChange={setActiveIndex}
        />
      ),
    },
    {
      id: "commands",
      label: "Commands",
      content: (
        <CommandsTab
          commands={commandsByCategory.nonWidgetCmds}
          query={activeTab === "commands" ? tabQuery : ""}
          activeIndex={activeIndex}
          onSelect={handleCommandSelect}
          onActiveIndexChange={setActiveIndex}
        />
      ),
    },
    {
      id: "widgets",
      label: "Widgets",
      content: (
        <WidgetsTab
          widgets={commandsByCategory.widgetCmds}
          query={activeTab === "widgets" ? tabQuery : ""}
          activeIndex={activeIndex}
          onSelect={handleCommandSelect}
          onActiveIndexChange={setActiveIndex}
        />
      ),
    },
    {
      id: "ai",
      label: "Ask AI",
      content: (
        <AITab
          query={activeTab === "ai" ? tabQuery : ""}
          onClose={onClose}
        />
      ),
    },
    {
      id: "docs",
      label: "Docs",
      content: (
        <DocsTab
          query={activeTab === "docs" ? tabQuery : ""}
          activeIndex={activeIndex}
          onClose={onClose}
          onActiveIndexChange={setActiveIndex}
        />
      ),
    },
  ];

  return (
    <PaletteShell isOpen={isOpen} onClose={onClose}>
      {/* Search input */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-glass-l1">
        <Search size={16} className="shrink-0 text-text-muted" aria-hidden="true" />
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-label="Search symbols, commands, widgets, or ask AI"
          placeholder="Search symbols, / commands, # widgets, @ai ask, ? docs…"
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          onKeyDown={handleKeyDown}
          className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
          spellCheck={false}
          autoComplete="off"
        />
        {query && (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => { setQuery(""); setActiveTab("symbols"); inputRef.current?.focus(); }}
            className="shrink-0 text-text-muted hover:text-text-primary transition-colors text-xs"
          >
            ✕
          </button>
        )}
      </div>

      {/* Tabs */}
      <AnimatedTabs
        tabs={tabs}
        activeTabId={activeTab}
        onTabChange={(id) => { setActiveTab(id as PaletteTab); setActiveIndex(0); }}
        className="gap-0"
        tabListClassName="mx-4 mt-2"
        tabPanelClassName=""
        keepMounted
      />

      {/* Footer */}
      <div className="flex items-center gap-4 px-4 py-2 border-t border-glass-l1 bg-glass-l1">
        <FooterHint keys="↑↓" label="Navigate" />
        <FooterHint keys="↵" label="Select" />
        <FooterHint keys="Tab" label="Switch tab" />
        <FooterHint keys="Esc" label="Close" />
      </div>
    </PaletteShell>
  );
}

// ---------------------------------------------------------------------------
// Footer hint pill
// ---------------------------------------------------------------------------

function FooterHint({ keys, label }: { keys: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs text-text-muted">
      <kbd className="font-mono text-[10px] bg-glass-l2 border border-glass-l1 rounded px-1 py-0.5 leading-none">
        {keys}
      </kbd>
      <span>{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Re-export types for consumers
// ---------------------------------------------------------------------------
export type { Command, CommandCategory, GroupedCommands } from "./useCommandRegistry";
