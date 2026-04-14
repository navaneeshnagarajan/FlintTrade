# Unified Search + Command Palette — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the existing CommandPalette from a single command list to a 4-tab Unified Search (Symbols / Commands / Widgets / Ask AI) with glass styling, prefix-based tab routing, live market prices, and AI chat.

**Architecture:** Extend the existing `CommandPalette.tsx` + `useCommandRegistry.ts` with AnimatedTabs (Aceternity). Symbol search uses `searchSymbol()` API via TanStack Query with 300ms debounce, enriched with live LTP from Jotai `tickAtomFamily`. Commands and Widgets are extracted from existing useCommandRegistry into separate tab panels. AI tab sends messages through `useAIConversationStore`. No new Zustand store — palette state is ephemeral.

**Tech Stack:** React 19, TypeScript strict, AnimatedTabs (Aceternity), TanStack Query v5, Jotai atoms, Zustand (aiConversationStore), shadcn/ui, Tailwind CSS v4 glass utilities, lucide-react icons.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/components/CommandPalette/CommandPalette.tsx` | **Modify** | Add AnimatedTabs, glass styling, prefix routing, delegate to tab components |
| `src/components/CommandPalette/useCommandRegistry.ts` | **Modify** | Export separate `widgetCommands` and `nonWidgetCommands` for tab extraction |
| `src/components/CommandPalette/SymbolSearchTab.tsx` | **Create** | Symbol search with debounced API, live LTP, quick actions |
| `src/components/CommandPalette/CommandsTab.tsx` | **Create** | Extract command list rendering (navigate + tool + action + theme) |
| `src/components/CommandPalette/WidgetsTab.tsx` | **Create** | Extract widget command list rendering |
| `src/components/CommandPalette/AITab.tsx` | **Create** | AI chat input, send to conversation store, show response |
| `src/components/CommandPalette/useSymbolSearch.ts` | **Create** | TanStack Query hook wrapping searchSymbol() with 300ms debounce |
| `src/components/CommandPalette/PaletteShell.tsx` | **Create** | Shared glass overlay + modal chrome (extracted from CommandPalette) |
| `src/components/CommandPalette/__tests__/SymbolSearchTab.test.tsx` | **Create** | Tests for symbol search tab |
| `src/components/CommandPalette/__tests__/CommandsTab.test.tsx` | **Create** | Tests for commands tab |
| `src/components/CommandPalette/__tests__/WidgetsTab.test.tsx` | **Create** | Tests for widgets tab |
| `src/components/CommandPalette/__tests__/AITab.test.tsx` | **Create** | Tests for AI tab |
| `src/components/CommandPalette/__tests__/CommandPalette.test.tsx` | **Create** | Integration tests for full palette with tabs + prefix routing |
| `src/components/CommandPalette/__tests__/useSymbolSearch.test.ts` | **Create** | Tests for debounced symbol search hook |

---

## Task 1: useSymbolSearch hook (TanStack Query + debounce)

**Files:**
- Create: `src/components/CommandPalette/useSymbolSearch.ts`
- Create: `src/components/CommandPalette/__tests__/useSymbolSearch.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// src/components/CommandPalette/__tests__/useSymbolSearch.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { useSymbolSearch } from "../useSymbolSearch";

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn(),
}));

import { searchSymbol } from "@/services/api";

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );

describe("useSymbolSearch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  it("returns empty results for empty query", () => {
    const { result } = renderHook(() => useSymbolSearch(""), { wrapper });
    expect(result.current.results).toEqual([]);
    expect(result.current.isLoading).toBe(false);
  });

  it("debounces the API call by 300ms", async () => {
    const mockResults = [{ symbol: "RELIANCE", exchange: "NSE" }];
    vi.mocked(searchSymbol).mockResolvedValue(mockResults);

    const { result } = renderHook(() => useSymbolSearch("REL"), { wrapper });

    // Before debounce fires
    expect(searchSymbol).not.toHaveBeenCalled();

    // Advance past debounce
    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    await waitFor(() => {
      expect(searchSymbol).toHaveBeenCalledWith("REL");
      expect(result.current.results).toEqual(mockResults);
    });
  });

  it("does not call API for queries shorter than 2 characters", () => {
    renderHook(() => useSymbolSearch("R"), { wrapper });
    vi.advanceTimersByTime(500);
    expect(searchSymbol).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/useSymbolSearch.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Write minimal implementation**

```typescript
// src/components/CommandPalette/useSymbolSearch.ts
import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { searchSymbol } from "@/services/api";

interface SymbolResult {
  symbol: string;
  exchange: string;
}

export function useSymbolSearch(query: string) {
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    if (query.length < 2) {
      setDebouncedQuery("");
      return;
    }
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data, isLoading } = useQuery<SymbolResult[]>({
    queryKey: ["symbolSearch", debouncedQuery],
    queryFn: () => searchSymbol(debouncedQuery),
    enabled: debouncedQuery.length >= 2,
    staleTime: 30_000,
  });

  return {
    results: data ?? [],
    isLoading: isLoading && debouncedQuery.length >= 2,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/useSymbolSearch.test.ts`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/components/CommandPalette/useSymbolSearch.ts src/components/CommandPalette/__tests__/useSymbolSearch.test.ts
git commit -m "feat(terminal): add useSymbolSearch hook with 300ms debounce"
```

---

## Task 2: PaletteShell — glass modal chrome

**Files:**
- Create: `src/components/CommandPalette/PaletteShell.tsx`

- [ ] **Step 1: Write the PaletteShell component**

This extracts the overlay + modal chrome from `CommandPalette.tsx` into a reusable shell with glass styling. No separate test — tested through integration tests in Task 7.

```tsx
// src/components/CommandPalette/PaletteShell.tsx
import { useCallback, type ReactNode } from "react";
import { cn } from "@/lib/utils";

interface PaletteShellProps {
  isOpen: boolean;
  onClose: () => void;
  children: ReactNode;
}

export function PaletteShell({ isOpen, onClose, children }: PaletteShellProps) {
  const handleOverlayClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (e.target === e.currentTarget) onClose();
    },
    [onClose],
  );

  if (!isOpen) return null;

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
          "w-full max-w-xl mx-4 flex flex-col",
          "glass-surface-l1 rounded-glass-card shadow-2xl overflow-hidden",
          "animate-in fade-in slide-in-from-top-4 duration-200",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add src/components/CommandPalette/PaletteShell.tsx
git commit -m "feat(terminal): add PaletteShell with glass modal chrome"
```

---

## Task 3: Extract CommandsTab

**Files:**
- Create: `src/components/CommandPalette/CommandsTab.tsx`
- Create: `src/components/CommandPalette/__tests__/CommandsTab.test.tsx`
- Modify: `src/components/CommandPalette/useCommandRegistry.ts` — export categorised command lists

- [ ] **Step 1: Modify useCommandRegistry to export categorised lists**

Add to end of `useCommandRegistry.ts`, inside the hook return:

```typescript
// In the return statement, add:
return {
  commands,
  recentCommands,
  groupedCommands,
  searchCommands,
  executeCommand,
  // New: categorised for tab extraction
  commandsByCategory: useMemo(() => {
    const widgetCmds = commands.filter((c) => c.category === "widget");
    const nonWidgetCmds = commands.filter((c) => c.category !== "widget");
    return { widgetCmds, nonWidgetCmds };
  }, [commands]),
};
```

- [ ] **Step 2: Write failing test for CommandsTab**

```tsx
// src/components/CommandPalette/__tests__/CommandsTab.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { CommandsTab } from "../CommandsTab";
import type { Command } from "../useCommandRegistry";

const mockCommands: Command[] = [
  { id: "nav:trade", title: "Go to Trade", category: "navigate", action: vi.fn() },
  { id: "action:fullscreen", title: "Toggle Fullscreen", category: "action", shortcut: "F11", action: vi.fn() },
  { id: "theme:graphite", title: "Switch to Graphite", category: "theme", action: vi.fn() },
];

describe("CommandsTab", () => {
  it("renders all commands", () => {
    render(
      <CommandsTab
        commands={mockCommands}
        query=""
        activeIndex={0}
        onSelect={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Go to Trade")).toBeInTheDocument();
    expect(screen.getByText("Toggle Fullscreen")).toBeInTheDocument();
    expect(screen.getByText("Switch to Graphite")).toBeInTheDocument();
  });

  it("filters commands by query", () => {
    render(
      <CommandsTab
        commands={mockCommands}
        query="trade"
        activeIndex={0}
        onSelect={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/Go to Trade/)).toBeInTheDocument();
    expect(screen.queryByText("Toggle Fullscreen")).not.toBeInTheDocument();
  });

  it("calls onSelect when a command is clicked", () => {
    const onSelect = vi.fn();
    render(
      <CommandsTab
        commands={mockCommands}
        query=""
        activeIndex={0}
        onSelect={onSelect}
        onActiveIndexChange={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("Go to Trade"));
    expect(onSelect).toHaveBeenCalledWith(mockCommands[0]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/CommandsTab.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 4: Implement CommandsTab**

```tsx
// src/components/CommandPalette/CommandsTab.tsx
import { useMemo } from "react";
import {
  LayoutGrid,
  Wrench,
  Navigation,
  Zap,
  Palette,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { Command, CommandCategory } from "./useCommandRegistry";

const CATEGORY_ICONS: Record<CommandCategory, React.ReactNode> = {
  widget:   <LayoutGrid  size={13} aria-hidden="true" />,
  tool:     <Wrench      size={13} aria-hidden="true" />,
  navigate: <Navigation  size={13} aria-hidden="true" />,
  action:   <Zap         size={13} aria-hidden="true" />,
  theme:    <Palette     size={13} aria-hidden="true" />,
};

interface CommandsTabProps {
  commands: Command[];
  query: string;
  activeIndex: number;
  onSelect: (cmd: Command) => void;
  onActiveIndexChange: (index: number) => void;
}

export function CommandsTab({ commands, query, activeIndex, onSelect, onActiveIndexChange }: CommandsTabProps) {
  const filtered = useMemo(() => {
    if (!query) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (cmd) =>
        cmd.title.toLowerCase().includes(q) ||
        cmd.description?.toLowerCase().includes(q),
    );
  }, [commands, query]);

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted">
        <p className="text-sm">No commands match &ldquo;{query}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Commands" className="overflow-y-auto max-h-80 py-1">
      {filtered.map((cmd, i) => (
        <li
          key={cmd.id}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          onClick={() => onSelect(cmd)}
          className={cn(
            "flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <span className={cn("shrink-0 flex items-center justify-center w-6 h-6 rounded text-text-muted", i === activeIndex && "text-accent")}>
            {CATEGORY_ICONS[cmd.category]}
          </span>
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
          {cmd.shortcut && (
            <kbd className="shrink-0 font-mono text-[10px] text-text-muted bg-glass-l1 border border-glass-l1 rounded px-1.5 py-0.5 leading-none">
              {cmd.shortcut}
            </kbd>
          )}
        </li>
      ))}
    </ul>
  );
}

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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/CommandsTab.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/components/CommandPalette/CommandsTab.tsx src/components/CommandPalette/__tests__/CommandsTab.test.tsx src/components/CommandPalette/useCommandRegistry.ts
git commit -m "feat(terminal): extract CommandsTab with filtering and glass styling"
```

---

## Task 4: Extract WidgetsTab

**Files:**
- Create: `src/components/CommandPalette/WidgetsTab.tsx`
- Create: `src/components/CommandPalette/__tests__/WidgetsTab.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// src/components/CommandPalette/__tests__/WidgetsTab.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { WidgetsTab } from "../WidgetsTab";
import type { Command } from "../useCommandRegistry";

const mockWidgets: Command[] = [
  { id: "widget:chart", title: "Add Chart", description: "Open Chart widget", category: "widget", action: vi.fn() },
  { id: "widget:positions", title: "Add Positions", description: "Open Positions widget", category: "widget", action: vi.fn() },
];

describe("WidgetsTab", () => {
  it("renders all widget commands", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText("Add Chart")).toBeInTheDocument();
    expect(screen.getByText("Add Positions")).toBeInTheDocument();
  });

  it("filters by query", () => {
    render(
      <WidgetsTab widgets={mockWidgets} query="chart" activeIndex={0} onSelect={vi.fn()} onActiveIndexChange={vi.fn()} />,
    );
    expect(screen.getByText(/Add Chart/)).toBeInTheDocument();
    expect(screen.queryByText("Add Positions")).not.toBeInTheDocument();
  });

  it("calls onSelect on click", () => {
    const onSelect = vi.fn();
    render(
      <WidgetsTab widgets={mockWidgets} query="" activeIndex={0} onSelect={onSelect} onActiveIndexChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByText("Add Chart"));
    expect(onSelect).toHaveBeenCalledWith(mockWidgets[0]);
  });
});
```

- [ ] **Step 2: Implement WidgetsTab**

```tsx
// src/components/CommandPalette/WidgetsTab.tsx
import { useMemo } from "react";
import { LayoutGrid } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Command } from "./useCommandRegistry";

interface WidgetsTabProps {
  widgets: Command[];
  query: string;
  activeIndex: number;
  onSelect: (cmd: Command) => void;
  onActiveIndexChange: (index: number) => void;
}

export function WidgetsTab({ widgets, query, activeIndex, onSelect, onActiveIndexChange }: WidgetsTabProps) {
  const filtered = useMemo(() => {
    if (!query) return widgets;
    const q = query.replace(/^#\s*/, "").toLowerCase();
    if (!q) return widgets;
    return widgets.filter(
      (w) => w.title.toLowerCase().includes(q) || w.description?.toLowerCase().includes(q),
    );
  }, [widgets, query]);

  if (filtered.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted">
        <p className="text-sm">No widgets match &ldquo;{query.replace(/^#\s*/, "")}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Widgets" className="overflow-y-auto max-h-80 py-1">
      {filtered.map((w, i) => (
        <li
          key={w.id}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          onClick={() => onSelect(w)}
          className={cn(
            "flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <LayoutGrid size={13} className={cn("shrink-0 text-text-muted", i === activeIndex && "text-accent")} />
          <span className="flex-1 min-w-0">
            <span className="block text-sm text-text-primary leading-snug truncate">{w.title}</span>
            {w.description && (
              <span className="block text-xs text-text-muted leading-snug truncate mt-0.5">{w.description}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/WidgetsTab.test.tsx`
Expected: PASS (3 tests)

- [ ] **Step 4: Commit**

```bash
git add src/components/CommandPalette/WidgetsTab.tsx src/components/CommandPalette/__tests__/WidgetsTab.test.tsx
git commit -m "feat(terminal): extract WidgetsTab with # prefix filtering"
```

---

## Task 5: SymbolSearchTab with live prices

**Files:**
- Create: `src/components/CommandPalette/SymbolSearchTab.tsx`
- Create: `src/components/CommandPalette/__tests__/SymbolSearchTab.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// src/components/CommandPalette/__tests__/SymbolSearchTab.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { SymbolSearchTab } from "../SymbolSearchTab";

vi.mock("../useSymbolSearch", () => ({
  useSymbolSearch: vi.fn().mockReturnValue({
    results: [
      { symbol: "RELIANCE", exchange: "NSE" },
      { symbol: "RELIANCEPP", exchange: "NSE" },
    ],
    isLoading: false,
  }),
}));

vi.mock("jotai", () => ({
  useAtomValue: vi.fn().mockReturnValue(null),
}));

vi.mock("@/atoms/marketAtoms", () => ({
  tickAtomFamily: vi.fn().mockReturnValue({}),
}));

describe("SymbolSearchTab", () => {
  it("renders search results with symbol and exchange", () => {
    render(
      <SymbolSearchTab
        query="REL"
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(screen.getAllByText("NSE")).toHaveLength(2);
  });

  it("shows empty state for no query", () => {
    vi.mocked(require("../useSymbolSearch").useSymbolSearch).mockReturnValue({
      results: [],
      isLoading: false,
    });
    render(
      <SymbolSearchTab
        query=""
        activeIndex={0}
        onSelectSymbol={vi.fn()}
        onActiveIndexChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/type to search/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement SymbolSearchTab**

```tsx
// src/components/CommandPalette/SymbolSearchTab.tsx
import { useAtomValue } from "jotai";
import { Search, TrendingUp, TrendingDown, BarChart3, ShoppingCart, MessageSquare } from "lucide-react";
import { cn } from "@/lib/utils";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useSymbolSearch } from "./useSymbolSearch";

interface SymbolSearchTabProps {
  query: string;
  activeIndex: number;
  onSelectSymbol: (symbol: string, exchange: string, action: "chart" | "buy" | "sell" | "ai") => void;
  onActiveIndexChange: (index: number) => void;
}

function SymbolPrice({ symbol, exchange }: { symbol: string; exchange: string }) {
  const tick = useAtomValue(tickAtomFamily(`${exchange}:${symbol}`));
  if (!tick) return <span className="text-xs text-text-muted">—</span>;

  const change = tick.change ?? 0;
  const pct = tick.pct ?? 0;
  const isPositive = change >= 0;

  return (
    <span className={cn("text-right font-data text-xs tabular-nums", isPositive ? "text-profit" : "text-loss")}>
      <span className="block">{tick.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2 })}</span>
      <span className="block text-[10px]">
        {isPositive ? "+" : ""}{pct.toFixed(2)}%
      </span>
    </span>
  );
}

export function SymbolSearchTab({ query, activeIndex, onSelectSymbol, onActiveIndexChange }: SymbolSearchTabProps) {
  const { results, isLoading } = useSymbolSearch(query);

  if (!query || query.length < 2) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-2">
        <Search size={24} className="text-text-muted/50" />
        <p className="text-sm">Type to search stocks, ETFs, futures, options&hellip;</p>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-text-muted">
        <p className="text-sm">Searching&hellip;</p>
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-text-muted gap-2">
        <Search size={24} className="text-text-muted/50" />
        <p className="text-sm">No symbols match &ldquo;{query}&rdquo;</p>
      </div>
    );
  }

  return (
    <ul role="listbox" aria-label="Symbol results" className="overflow-y-auto max-h-80 py-1">
      {results.map((r, i) => (
        <li
          key={`${r.exchange}:${r.symbol}`}
          role="option"
          aria-selected={i === activeIndex}
          onMouseEnter={() => onActiveIndexChange(i)}
          className={cn(
            "group flex items-center gap-3 px-4 py-2.5 cursor-pointer select-none transition-colors",
            i === activeIndex ? "bg-glass-l3" : "hover:bg-glass-l2",
          )}
        >
          <span className="flex-1 min-w-0" onClick={() => onSelectSymbol(r.symbol, r.exchange, "chart")}>
            <span className="block text-sm text-text-primary font-medium truncate">{r.symbol}</span>
            <span className="block text-[10px] text-text-muted uppercase">{r.exchange}</span>
          </span>

          <SymbolPrice symbol={r.symbol} exchange={r.exchange} />

          {/* Quick actions — visible on hover / active */}
          <span className={cn(
            "flex items-center gap-1 transition-opacity",
            i === activeIndex ? "opacity-100" : "opacity-0 group-hover:opacity-100",
          )}>
            <button
              type="button"
              aria-label={`Open ${r.symbol} chart`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "chart")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-text-primary"
            >
              <BarChart3 size={14} />
            </button>
            <button
              type="button"
              aria-label={`Buy ${r.symbol}`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "buy")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-profit"
            >
              <ShoppingCart size={14} />
            </button>
            <button
              type="button"
              aria-label={`Ask AI about ${r.symbol}`}
              onClick={() => onSelectSymbol(r.symbol, r.exchange, "ai")}
              className="p-1 rounded hover:bg-glass-l3 text-text-muted hover:text-[#8b5cf6]"
            >
              <MessageSquare size={14} />
            </button>
          </span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/SymbolSearchTab.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add src/components/CommandPalette/SymbolSearchTab.tsx src/components/CommandPalette/__tests__/SymbolSearchTab.test.tsx
git commit -m "feat(terminal): add SymbolSearchTab with live prices and quick actions"
```

---

## Task 6: AITab

**Files:**
- Create: `src/components/CommandPalette/AITab.tsx`
- Create: `src/components/CommandPalette/__tests__/AITab.test.tsx`

- [ ] **Step 1: Write failing test**

```tsx
// src/components/CommandPalette/__tests__/AITab.test.tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { AITab } from "../AITab";

vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: Object.assign(
    vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
      selector({
        messages: [],
        isStreaming: false,
        addMessage: vi.fn(),
      }),
    ),
    { getState: () => ({ addMessage: vi.fn(), messages: [], isStreaming: false }) },
  ),
}));

describe("AITab", () => {
  it("renders the AI input with placeholder", () => {
    render(<AITab query="" onClose={vi.fn()} />);
    expect(screen.getByText(/ask ai anything/i)).toBeInTheDocument();
  });

  it("shows the query as prefilled text when @ai prefix is stripped", () => {
    render(<AITab query="analyse NIFTY" onClose={vi.fn()} />);
    expect(screen.getByText(/analyse NIFTY/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement AITab**

```tsx
// src/components/CommandPalette/AITab.tsx
import { useState } from "react";
import { Sparkles, Send, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAIConversationStore } from "@/stores/aiConversationStore";

interface AITabProps {
  query: string;
  onClose: () => void;
}

const QUICK_PROMPTS = [
  "Analyse NIFTY trend today",
  "What are FII/DII flows?",
  "Summarise my open positions",
  "Best option strategy for sideways market",
];

export function AITab({ query, onClose }: AITabProps) {
  const addMessage = useAIConversationStore((s) => s.addMessage);
  const strippedQuery = query.replace(/^@ai\s*/i, "").trim();
  const [inputValue, setInputValue] = useState(strippedQuery);

  function handleSend(text: string) {
    if (!text.trim()) return;
    addMessage("user", text.trim());
    onClose();
    // Navigate to /ai so the user sees the response
    window.dispatchEvent(
      new CustomEvent("flinttrade:navigate", { detail: { path: "/ai" } }),
    );
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-4">
      {/* Input */}
      <div className="flex items-center gap-2 bg-glass-l2 border border-glass-l2 rounded-glass-control px-3 py-2">
        <Sparkles size={14} className="shrink-0 text-[#8b5cf6]" />
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSend(inputValue);
            }
          }}
          placeholder="Ask AI anything about your portfolio, markets, strategies…"
          className="flex-1 bg-transparent text-sm text-text-primary placeholder:text-text-muted outline-none"
          autoFocus
        />
        <button
          type="button"
          onClick={() => handleSend(inputValue)}
          disabled={!inputValue.trim()}
          className={cn(
            "p-1 rounded transition-colors",
            inputValue.trim() ? "text-[#8b5cf6] hover:bg-glass-l3" : "text-text-muted/30",
          )}
        >
          <Send size={14} />
        </button>
      </div>

      {/* Quick prompts */}
      {!strippedQuery && (
        <div className="flex flex-col gap-1">
          <p className="text-[10px] uppercase tracking-widest text-text-muted font-medium px-1">Quick prompts</p>
          {QUICK_PROMPTS.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => handleSend(prompt)}
              className="flex items-center gap-2 px-3 py-2 rounded-glass-control text-sm text-text-secondary hover:bg-glass-l2 hover:text-text-primary transition-colors text-left"
            >
              <ArrowRight size={12} className="shrink-0 text-text-muted" />
              {prompt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/AITab.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 4: Commit**

```bash
git add src/components/CommandPalette/AITab.tsx src/components/CommandPalette/__tests__/AITab.test.tsx
git commit -m "feat(terminal): add AITab with quick prompts and conversation store integration"
```

---

## Task 7: Rewrite CommandPalette with AnimatedTabs + prefix routing

**Files:**
- Modify: `src/components/CommandPalette/CommandPalette.tsx` — full rewrite using tabs
- Create: `src/components/CommandPalette/__tests__/CommandPalette.test.tsx`

- [ ] **Step 1: Write integration test**

```tsx
// src/components/CommandPalette/__tests__/CommandPalette.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";

// Mock framer-motion
vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: Record<string, unknown>) => {
      const { initial: _i, animate: _a, exit: _e, variants: _v, transition: _t, layoutId: _l, ...rest } = props;
      return <div {...rest}>{children as React.ReactNode}</div>;
    },
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/services/api", () => ({
  searchSymbol: vi.fn().mockResolvedValue([]),
}));

vi.mock("jotai", () => ({
  useAtomValue: vi.fn().mockReturnValue(null),
}));

vi.mock("@/atoms/marketAtoms", () => ({
  tickAtomFamily: vi.fn().mockReturnValue({}),
}));

vi.mock("@/stores/aiConversationStore", () => ({
  useAIConversationStore: Object.assign(
    vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
      sel({ messages: [], isStreaming: false, addMessage: vi.fn() }),
    ),
    { getState: () => ({ addMessage: vi.fn(), messages: [], isStreaming: false }) },
  ),
}));

vi.mock("@/stores/themeStore", () => ({
  useThemeStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ setTheme: vi.fn(), setMode: vi.fn(), mode: "dark" }),
  ),
}));

vi.mock("@/layout/widgetFactory", () => ({
  widgetCatalog: [
    { id: "chart", name: "Chart", category: "analysis" },
    { id: "positions", name: "Positions", category: "trading" },
  ],
}));

import CommandPalette from "../CommandPalette";

const wrapper = ({ children }: { children: React.ReactNode }) =>
  createElement(
    QueryClientProvider,
    { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
    children,
  );

function renderPalette(isOpen = true) {
  return render(
    createElement(wrapper, null,
      createElement(CommandPalette, { isOpen, onClose: vi.fn() }),
    ),
  );
}

describe("CommandPalette — tabbed", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders 4 tabs: Symbols, Commands, Widgets, Ask AI", () => {
    renderPalette();
    expect(screen.getByRole("tab", { name: /symbols/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /commands/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /widgets/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /ask ai/i })).toBeInTheDocument();
  });

  it("defaults to Symbols tab", () => {
    renderPalette();
    expect(screen.getByRole("tab", { name: /symbols/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches to Commands tab when / is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "/" } });
    expect(screen.getByRole("tab", { name: /commands/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches to Widgets tab when # is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "#" } });
    expect(screen.getByRole("tab", { name: /widgets/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches to AI tab when @ai is typed", () => {
    renderPalette();
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "@ai " } });
    expect(screen.getByRole("tab", { name: /ask ai/i })).toHaveAttribute("aria-selected", "true");
  });

  it("returns null when not open", () => {
    const { container } = renderPalette(false);
    expect(container.innerHTML).toBe("");
  });
});
```

- [ ] **Step 2: Rewrite CommandPalette.tsx**

Replace the entire file with the new tabbed version. The new `CommandPalette.tsx` should:

1. Import `AnimatedTabs` from `@/components/aceternity/animated-tabs`
2. Import `PaletteShell`, `CommandsTab`, `WidgetsTab`, `SymbolSearchTab`, `AITab`
3. Import `useCommandRegistry` for command data
4. Manage local state: `query`, `activeTab`, `activeIndex`
5. Implement prefix routing: `/` → commands, `#` → widgets, `@ai` → ai, else → symbols
6. Wire keyboard: ArrowUp/Down, Enter, Escape
7. Use glass design tokens throughout

The full implementation:

```tsx
// src/components/CommandPalette/CommandPalette.tsx
import { useEffect, useRef, useState, useCallback } from "react";
import { Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { AnimatedTabs, type TabItem } from "@/components/aceternity/animated-tabs";
import { PaletteShell } from "./PaletteShell";
import { CommandsTab } from "./CommandsTab";
import { WidgetsTab } from "./WidgetsTab";
import { SymbolSearchTab } from "./SymbolSearchTab";
import { AITab } from "./AITab";
import { useCommandRegistry } from "./useCommandRegistry";
import type { Command } from "./useCommandRegistry";

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
}

type PaletteTab = "symbols" | "commands" | "widgets" | "ai";

function detectTab(query: string): PaletteTab | null {
  if (query.startsWith("/")) return "commands";
  if (query.startsWith("#")) return "widgets";
  if (query.toLowerCase().startsWith("@ai")) return "ai";
  return null;
}

function stripPrefix(query: string, tab: PaletteTab): string {
  if (tab === "commands" && query.startsWith("/")) return query.slice(1).trim();
  if (tab === "widgets" && query.startsWith("#")) return query.slice(1).trim();
  if (tab === "ai" && query.toLowerCase().startsWith("@ai")) return query.slice(3).trim();
  return query;
}

export default function CommandPalette({ isOpen, onClose }: CommandPaletteProps) {
  const { commandsByCategory, executeCommand } = useCommandRegistry();
  const [query, setQuery] = useState("");
  const [activeTab, setActiveTab] = useState<PaletteTab>("symbols");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset on open
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

  // Keyboard
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((p) => p + 1);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((p) => Math.max(0, p - 1));
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        const tabs: PaletteTab[] = ["symbols", "commands", "widgets", "ai"];
        const idx = tabs.indexOf(activeTab);
        setActiveTab(tabs[(idx + (e.shiftKey ? -1 + tabs.length : 1)) % tabs.length]);
        setActiveIndex(0);
      }
    },
    [onClose, activeTab],
  );

  const handleCommandSelect = useCallback(
    (cmd: Command) => {
      executeCommand(cmd);
      onClose();
    },
    [executeCommand, onClose],
  );

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
          new CustomEvent("flinttrade:navigate", { detail: { path: "/ai" } }),
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
          placeholder="Search symbols, / commands, # widgets, @ai ask…"
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
        keepMounted={false}
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

export type { Command, CommandCategory, GroupedCommands } from "./useCommandRegistry";
```

- [ ] **Step 3: Run integration tests**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/__tests__/CommandPalette.test.tsx`
Expected: PASS (6 tests)

- [ ] **Step 4: Run TypeScript check**

Run: `cd packages/terminal && npx tsc --noEmit`
Expected: Clean (0 errors)

- [ ] **Step 5: Run ALL CommandPalette tests together**

Run: `cd packages/terminal && npx vitest run src/components/CommandPalette/`
Expected: All tests pass across all test files

- [ ] **Step 6: Commit**

```bash
git add src/components/CommandPalette/
git commit -m "feat(terminal): rewrite CommandPalette with 4-tab Unified Search

Tabs: Symbols (live prices + quick actions), Commands (/ prefix),
Widgets (# prefix), Ask AI (@ai prefix). Glass Adaptive styling.
AnimatedTabs from Aceternity. Prefix-based auto-tab routing.
Keyboard: arrows navigate, Tab switches tabs, Enter selects, Esc closes."
```

---

## Task 8: Verify existing integration + build

**Files:**
- No new files. Verify existing wiring works.

- [ ] **Step 1: Verify TerminalRoute still imports correctly**

The existing `TerminalRoute.tsx` imports `CommandPalette` as default. Our rewrite preserves the default export and `CommandPaletteProps` interface — no changes needed.

Run: `cd packages/terminal && npx tsc --noEmit`
Expected: Clean

- [ ] **Step 2: Run full test suite**

Run: `cd packages/terminal && npx vitest run`
Expected: All tests pass (2,500+)

- [ ] **Step 3: Build check**

Run: `cd packages/terminal && npm run build`
Expected: Clean build

- [ ] **Step 4: Final commit if any adjustments were needed**

```bash
git add -u
git commit -m "fix(terminal): adjust imports for Unified Search integration"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| 4 tabs: Symbols, Commands, Widgets, Ask AI | Task 7 |
| Symbol search: stocks, ETFs, options, futures | Task 1 (hook) + Task 5 (tab) |
| Live price + change% on symbols | Task 5 (SymbolPrice component) |
| Quick actions: chart, buy/sell, ask AI | Task 5 (onSelectSymbol) |
| Commands: / prefix | Task 7 (detectTab) |
| Widgets: # prefix | Task 7 (detectTab) |
| AI: @ai prefix | Task 7 (detectTab) |
| Keyboard: arrows, Enter, ESC | Task 7 (handleKeyDown) |
| Glass themed overlay | Task 2 (PaletteShell) + Task 7 |
| Tab key switches tabs | Task 7 (handleKeyDown Tab) |
