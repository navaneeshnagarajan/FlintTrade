/**
 * useCommandRegistry.ts
 *
 * Provides the full command catalogue for the FlintTrade command palette.
 * Commands are grouped by category and support fuzzy (substring) search.
 * Recent commands are persisted to localStorage (max 5 entries).
 *
 * Data flow:
 *   Widget commands  → dispatch `flinttrade:addWidget`  (picked up by WidgetPicker listener)
 *   Navigate/Tool    → dispatch `flinttrade:navigate`   (picked up by TopBar router listener)
 *   Action commands  → dispatch custom action events
 *   Theme commands   → call useThemeStore directly
 */

import { useMemo, useCallback, useState } from "react";
import { widgetCatalog } from "@/layout/widgetFactory";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";
import { useThemeStore } from "@/stores/themeStore";
import { useSkillLevel } from "@/hooks/useSkillLevel";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CommandCategory = "widget" | "tool" | "navigate" | "action" | "theme";

export interface Command {
  id: string;
  title: string;
  description?: string;
  category: CommandCategory;
  shortcut?: string;
  action: () => void;
}

export interface GroupedCommands {
  category: CommandCategory;
  label: string;
  commands: Command[];
}

// ---------------------------------------------------------------------------
// localStorage key + helpers
// ---------------------------------------------------------------------------

const RECENT_KEY = "flinttrade:recentCommands";
const MAX_RECENT = 5;
/**
 * Skill-tier gates for the widget commands. Both are keyed by catalogue id, so
 * a retired or invented id does not degrade gracefully — it silently removes a
 * widget from that tier. `useCommandRegistry.test.ts` pins every id against
 * `widgetCatalog`; exported for that guard.
 */
export const BEGINNER_WIDGET_IDS = new Set([
  "indexstrip",
  "chart",
  "watchlist",
  "orderpad",
  "positions",
]);
export const INTERMEDIATE_WIDGET_IDS = new Set([
  ...BEGINNER_WIDGET_IDS,
  "orders",
  "ticker",
  // `depth` was retired into `orderladder` by the widget merge. Because this
  // gate is by id, leaving the retired id here removed the DOM / Ladder from
  // the intermediate tier entirely — the retired id matches no catalogue entry
  // and the canonical was never added. Same failure `useSkillContent.ts` fixed
  // for its own list.
  "orderladder",
  "optionchain",
  "greeks",
  // `pnl` was never a catalogue id — the P&L surface is `pnlmonitor`,
  // so this tier silently shipped one widget short of its intent.
  "pnlmonitor",
  "riskdashboard",
  "alerts",
]);

function loadRecentIds(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string");
  } catch {
    return [];
  }
}

function saveRecentIds(ids: string[]): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(ids));
  } catch {
    // storage unavailable — fail silently
  }
}

// ---------------------------------------------------------------------------
// Category display labels
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<CommandCategory, string> = {
  widget:   "Widgets",
  tool:     "Tools",
  navigate: "Navigate",
  action:   "Actions",
  theme:    "Theme",
};

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useCommandRegistry() {
  const setTheme = useThemeStore((s) => s.setTheme);
  const setMode  = useThemeStore((s) => s.setMode);
  const mode     = useThemeStore((s) => s.mode);
  const tradeLevel = useSkillLevel("trade");

  const [recentIds, setRecentIds] = useState<string[]>(loadRecentIds);

  // Build the full static command list. Memoised so it is only rebuilt when
  // the theme store actions change identity (effectively: once per mount).
  const commands: Command[] = useMemo(() => {
    // ----- Widget commands (one per entry in widgetCatalog) -----
    const visibleWidgets = widgetCatalog.filter((widget) => {
      if (tradeLevel === "advanced") return true;
      if (tradeLevel === "intermediate") return INTERMEDIATE_WIDGET_IDS.has(widget.id);
      return BEGINNER_WIDGET_IDS.has(widget.id);
    });

    const widgetCommands: Command[] = visibleWidgets.map((w) => ({
      id:          `widget:${w.id}`,
      title:       `Add ${w.name}`,
      description: `Open ${w.name} widget in the workspace`,
      category:    "widget" as CommandCategory,
      action:      () => {
        window.dispatchEvent(
          new CustomEvent("flinttrade:addWidget", { detail: { widgetId: w.id } }),
        );
      },
    }));

    // ----- Tool commands -----
    const toolCommands: Command[] = [
      {
        id:          "tool:backtest-lab",
        title:       "Open Backtest Lab",
        description: "Strategy backtesting and optimisation",
        category:    "tool",
        action:      () => {
          window.dispatchEvent(
            new CustomEvent("flinttrade:navigate", { detail: { path: "/lab" } }),
          );
        },
      },
      {
        id:          "tool:flow-builder",
        title:       "Open Flow Builder",
        description: "Design and save local flow drafts",
        category:    "tool",
        action:      () => {
          window.dispatchEvent(
            new CustomEvent("flinttrade:navigate", { detail: { path: "/automate" } }),
          );
        },
      },
      {
        id:          "tool:strategy-builder",
        title:       "Open Strategy Builder",
        description: "Create and manage trading strategies",
        category:    "tool",
        action:      () => {
          window.dispatchEvent(
            new CustomEvent("flinttrade:navigate", { detail: { path: "/lab" } }),
          );
        },
      },
      {
        id:          "tool:trade-journal",
        title:       "Open Trade Review",
        description: "Review and annotate your trades",
        category:    "tool",
        action:      () => {
          window.dispatchEvent(
            new CustomEvent("flinttrade:open-tool", { detail: { toolId: "trade-journal" } }),
          );
        },
      },
      {
        id:          "tool:market-intelligence",
        title:       "Open Market Intelligence",
        description: "AI-powered market insights",
        category:    "tool",
        action:      () => {
          window.dispatchEvent(
            new CustomEvent("flinttrade:open-tool", {
              detail: { toolId: "market-intelligence" },
            }),
          );
        },
      },
    ];

    // ----- Navigate commands -----
    const navEntries: Array<{ id: string; label: string; path: string; shortcut?: string }> = [
      { id: "nav:trade",    label: "Go to Trade",    path: "/trade",    shortcut: "Alt+T" },
      { id: "nav:invest",   label: "Go to Invest",   path: "/invest",   shortcut: "Alt+I" },
      { id: "nav:learn",    label: "Go to Learn",    path: "/learn",    shortcut: "Alt+L" },
      { id: "nav:lab",      label: "Go to Lab",      path: "/lab" },
      { id: "nav:automate", label: "Go to Automate", path: "/automate" },
      { id: "nav:ai",       label: "Go to AI",       path: "/ai" },
      { id: "nav:settings", label: "Go to Settings", path: "/settings" },
    ];
    if (import.meta.env.DEV) {
      navEntries.push({ id: "nav:admin", label: "Go to Admin", path: "/admin" });
    }

    const navigateCommands: Command[] = navEntries.map((entry) => ({
      id:       entry.id,
      title:    entry.label,
      category: "navigate" as CommandCategory,
      shortcut: entry.shortcut,
      action:   () => {
        window.dispatchEvent(
          new CustomEvent("flinttrade:navigate", { detail: { path: entry.path } }),
        );
      },
    }));

    // ----- Action commands -----
    const actionCommands: Command[] = [
      {
        id:       "action:fullscreen",
        title:    "Toggle Fullscreen",
        category: "action",
        shortcut: "F11",
        action:   () => {
          window.dispatchEvent(new CustomEvent("flinttrade:toggle-fullscreen"));
        },
      },
      {
        id:          "action:export-layout",
        title:       "Export Layout",
        description: "Download current workspace layout as JSON",
        category:    "action",
        action:      () => {
          window.dispatchEvent(new CustomEvent("flinttrade:export-layout"));
        },
      },
      {
        id:          "action:reset-layout",
        title:       "Reset Layout",
        description: "Restore workspace to the default preset",
        category:    "action",
        action:      () => {
          window.dispatchEvent(new CustomEvent("flinttrade:reset-layout"));
        },
      },
      {
        id:          "action:show-changelog",
        title:       "Show Changelog",
        description: "View what's new in this version of FlintTrade",
        category:    "action",
        action:      () => {
          window.dispatchEvent(new CustomEvent("flinttrade:show-changelog"));
        },
      },
      {
        id:          "action:search-docs",
        title:       "Search Docs",
        description: "Search FlintTrade documentation (or use ? prefix)",
        category:    "action",
        action:      () => {
          window.dispatchEvent(new CustomEvent("flinttrade:search-docs"));
        },
      },
    ];

    // ----- Theme commands -----
    const themeCommands: Command[] = [
      {
        id:       "theme:graphite",
        title:    "Switch to Graphite",
        category: "theme",
        action:   () => setTheme("graphite"),
      },
      {
        id:       "theme:midnight",
        title:    "Switch to Midnight",
        category: "theme",
        action:   () => setTheme("midnight"),
      },
      {
        id:       "theme:ember",
        title:    "Switch to Ember",
        category: "theme",
        action:   () => setTheme("ember"),
      },
      {
        id:       "theme:toggle-mode",
        title:    "Toggle Dark/Light",
        description: "Switch between dark and light colour mode",
        category: "theme",
        shortcut: "Ctrl+Shift+L",
        action:   () => {
          // "system" → resolve first, then flip
          const next = mode === "light" ? "dark" : "light";
          setMode(next);
        },
      },
    ];

    // ----- Layout preset commands (one per built-in workspace preset) -----
    // Makes every layout — including the four-chart Options Scalper desk —
    // applicable from Ctrl+K, instead of only via the preset-picker dialog.
    // layoutStore.applyPreset is a no-op when no workspace is mounted, so this
    // is safe to invoke from any route.
    const layoutPresetCommands: Command[] = WORKSPACE_PRESETS.map((preset) => ({
      id:          `layout:${preset.id}`,
      title:       `Apply layout: ${preset.name}`,
      description: preset.description,
      category:    "action" as CommandCategory,
      action:      () => {
        window.dispatchEvent(
          new CustomEvent("flinttrade:apply-layout", { detail: { presetId: preset.id } }),
        );
      },
    }));

    return [
      ...widgetCommands,
      ...toolCommands,
      ...navigateCommands,
      ...actionCommands,
      ...layoutPresetCommands,
      ...themeCommands,
    ];
  }, [setTheme, setMode, mode, tradeLevel]);

  // ----- Derived: commands indexed by id -----
  const commandById = useMemo(() => {
    const map = new Map<string, Command>();
    for (const cmd of commands) {
      map.set(cmd.id, cmd);
    }
    return map;
  }, [commands]);

  // ----- Derived: recent commands (hydrated from id list) -----
  const recentCommands = useMemo<Command[]>(
    () => recentIds.flatMap((id) => {
      const cmd = commandById.get(id);
      return cmd ? [cmd] : [];
    }),
    [recentIds, commandById],
  );

  // ----- Derived: commands grouped by category -----
  const groupedCommands = useMemo<GroupedCommands[]>(() => {
    const order: CommandCategory[] = ["widget", "tool", "navigate", "action", "theme"];
    return order.flatMap((cat) => {
      const cmds = commands.filter((c) => c.category === cat);
      if (cmds.length === 0) return [];
      return [{ category: cat, label: CATEGORY_LABELS[cat], commands: cmds }];
    });
  }, [commands]);

  // ----- searchCommands: case-insensitive substring match -----
  const searchCommands = useCallback(
    (query: string): Command[] => {
      const q = query.trim().toLowerCase();
      if (!q) return [];
      return commands.filter(
        (cmd) =>
          cmd.title.toLowerCase().includes(q) ||
          cmd.description?.toLowerCase().includes(q) ||
          cmd.category.toLowerCase().includes(q),
      );
    },
    [commands],
  );

  // ----- executeCommand: run action + update recents -----
  const executeCommand = useCallback(
    (cmd: Command) => {
      // Prepend to recents, deduplicate, cap at MAX_RECENT
      const updated = [cmd.id, ...recentIds.filter((id) => id !== cmd.id)].slice(
        0,
        MAX_RECENT,
      );
      setRecentIds(updated);
      saveRecentIds(updated);
      cmd.action();
    },
    [recentIds],
  );

  const commandsByCategory = useMemo(() => {
    const widgetCmds = commands.filter((c) => c.category === "widget");
    const nonWidgetCmds = commands.filter((c) => c.category !== "widget");
    return { widgetCmds, nonWidgetCmds };
  }, [commands]);

  return {
    commands,
    recentCommands,
    groupedCommands,
    searchCommands,
    executeCommand,
    commandsByCategory,
  };
}
