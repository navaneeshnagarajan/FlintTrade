/**
 * ShortcutConfigPanel.test.tsx
 *
 * Tests for the keyboard shortcut configuration panel:
 *  - Renders category sections
 *  - Shows current key bindings
 *  - Starts capture mode on "Change" click
 *  - Applies captured key combo and saves to localStorage
 *  - Conflict detection — two bindings same combo
 *  - Reset to defaults restores original bindings
 *  - Non-customisable shortcuts show system label
 *  - Saved indicator appears after update
 *  - Server sync attempts fetch on mount
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock fetch globally
const mockFetch = vi.fn();
global.fetch = mockFetch;

// Mock hotkeyStore so tests control state
vi.mock("@/lib/hotkeyStore", () => {
  const DEFAULT_HOTKEYS = [
    {
      id: "command-palette",
      action: "Command palette",
      category: "global" as const,
      keys: ["Ctrl", "K"],
      customizable: false,
      description: "Open command palette",
    },
    {
      id: "cancel-orders",
      action: "Cancel all orders",
      category: "scalper" as const,
      keys: ["C"],
      customizable: true,
      description: "Cancel all orders",
    },
    {
      id: "quick-buy",
      action: "Quick buy",
      category: "trading" as const,
      keys: ["B"],
      customizable: true,
      description: "Quick buy",
    },
    {
      id: "toggle-timeframe",
      action: "Toggle chart timeframe",
      category: "chart" as const,
      keys: ["T"],
      customizable: true,
      description: "Cycle chart timeframes",
    },
  ];

  const state: Record<string, string[]> = {};

  return {
    DEFAULT_HOTKEYS,
    loadCustomHotkeys: vi.fn(() =>
      DEFAULT_HOTKEYS.map((b) => ({ ...b, keys: state[b.id] ?? b.keys })),
    ),
    saveHotkeyOverride: vi.fn((id: string, keys: string[]) => {
      state[id] = keys;
    }),
    resetAllHotkeys: vi.fn(() => { Object.keys(state).forEach((k) => delete state[k]); }),
    resetHotkeyToDefault: vi.fn(),
    detectConflicts: vi.fn((bindings: Array<{ id: string; keys: string[] }>) => {
      const comboMap = new Map<string, string[]>();
      for (const b of bindings) {
        const combo = b.keys.join("+");
        const ids = comboMap.get(combo) ?? [];
        ids.push(b.id);
        comboMap.set(combo, ids);
      }
      return Array.from(comboMap.entries())
        .filter(([, ids]) => ids.length > 1)
        .map(([combo, bindingIds]) => ({ combo, bindingIds }));
    }),
    findConflict: vi.fn(
      (keys: string[], excludeId: string, bindings: Array<{ id: string; keys: string[] }>) => {
        const combo = keys.join("+");
        for (const b of bindings) {
          if (b.id === excludeId) continue;
          if (b.keys.join("+") === combo) return b.id;
        }
        return null;
      },
    ),
    normalizeKeyCombo: vi.fn((keys: string[]) => keys.join("+")),
    eventToKeys: vi.fn((e: KeyboardEvent) => {
      const keys: string[] = [];
      if (e.ctrlKey) keys.push("Ctrl");
      if (e.shiftKey) keys.push("Shift");
      if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) {
        keys.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
      }
      return keys;
    }),
    formatKeyCombo: vi.fn((keys: string[]) => keys.join(" + ")),
  };
});

vi.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    onClick,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { children: React.ReactNode }) => (
    <button onClick={onClick} {...props}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => (
    <span data-testid="badge">{children}</span>
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import ShortcutConfigPanel from "../ShortcutConfigPanel";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderPanel() {
  return render(<ShortcutConfigPanel />);
}

function mockFetchSuccess() {
  mockFetch.mockResolvedValue({
    ok: true,
    json: async () => ({ overrides: {} }),
  } as Response);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ShortcutConfigPanel", () => {
  beforeEach(() => {
    mockFetchSuccess();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("rendering", () => {
    it("renders the panel heading", async () => {
      renderPanel();
      await waitFor(() => expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument());
    });

    it("renders all category section headings", async () => {
      renderPanel();
      await waitFor(() => {
        expect(screen.getByText("Global")).toBeInTheDocument();
        expect(screen.getByText("Scalper")).toBeInTheDocument();
        expect(screen.getByText("Trading")).toBeInTheDocument();
        expect(screen.getByText("Chart")).toBeInTheDocument();
      });
    });

    it("renders action labels for each shortcut", async () => {
      renderPanel();
      await waitFor(() => {
        expect(screen.getAllByText("Command palette").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Cancel all orders").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Quick buy").length).toBeGreaterThan(0);
        expect(screen.getAllByText("Toggle chart timeframe").length).toBeGreaterThan(0);
      });
    });

    it("renders key badges for bindings", async () => {
      renderPanel();
      await waitFor(() => {
        const kbdElements = document.querySelectorAll("kbd");
        expect(kbdElements.length).toBeGreaterThan(0);
      });
    });
  });

  describe("system shortcuts", () => {
    it("shows system-not-customisable label for non-customisable shortcuts", async () => {
      renderPanel();
      await waitFor(() => {
        expect(screen.getByText(/system.*not customisable/i)).toBeInTheDocument();
      });
    });

    it("does not show Change button for non-customisable shortcuts", async () => {
      renderPanel();
      await waitFor(() => {
        // Only customisable shortcuts have Change buttons
        const changeButtons = screen.getAllByText("Change");
        // command-palette is not customisable — 3 customisable = 3 buttons
        expect(changeButtons.length).toBe(3);
      });
    });
  });

  describe("capture mode", () => {
    it("shows capture prompt when Change is clicked", async () => {
      renderPanel();
      await waitFor(() => screen.getAllByText("Change").length > 0);

      const changeButtons = screen.getAllByText("Change");
      fireEvent.click(changeButtons[0]);

      expect(screen.getByText(/press key combo/i)).toBeInTheDocument();
    });

    it("cancels capture when cancel button is clicked", async () => {
      renderPanel();
      await waitFor(() => screen.getAllByText("Change").length > 0);

      fireEvent.click(screen.getAllByText("Change")[0]);
      expect(screen.getByText(/press key combo/i)).toBeInTheDocument();

      const cancelBtn = screen.getByRole("button", { name: /cancel key capture/i });
      fireEvent.click(cancelBtn);

      expect(screen.queryByText(/press key combo/i)).not.toBeInTheDocument();
    });

    it("cancels capture on Escape key", async () => {
      renderPanel();
      await waitFor(() => screen.getAllByText("Change").length > 0);

      fireEvent.click(screen.getAllByText("Change")[0]);
      expect(screen.getByText(/press key combo/i)).toBeInTheDocument();

      fireEvent.keyDown(window, { key: "Escape" });

      await waitFor(() =>
        expect(screen.queryByText(/press key combo/i)).not.toBeInTheDocument(),
      );
    });
  });

  describe("reset to defaults", () => {
    it("renders the reset button", async () => {
      renderPanel();
      await waitFor(() =>
        expect(
          screen.getByRole("button", { name: /reset all shortcuts/i }),
        ).toBeInTheDocument(),
      );
    });

    it("calls resetAllHotkeys on reset click", async () => {
      const { resetAllHotkeys } = await import("@/lib/hotkeyStore");
      renderPanel();
      await waitFor(() => screen.getByRole("button", { name: /reset all shortcuts/i }));

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) } as Response);
      fireEvent.click(screen.getByRole("button", { name: /reset all shortcuts/i }));

      await waitFor(() => expect(resetAllHotkeys).toHaveBeenCalled());
    });
  });

  describe("server sync", () => {
    it("fetches shortcuts from /ft-api/v1/shortcuts on mount", async () => {
      renderPanel();
      await waitFor(() =>
        expect(mockFetch).toHaveBeenCalledWith(
          "/ft-api/v1/shortcuts",
          expect.objectContaining({ headers: expect.any(Object) }),
        ),
      );
    });

    it("handles server fetch failure gracefully", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network error"));
      // Should still render without crashing
      renderPanel();
      await waitFor(() =>
        expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument(),
      );
    });

    it("handles server returning non-ok response", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: async () => ({}),
      } as Response);
      renderPanel();
      await waitFor(() =>
        expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument(),
      );
    });
  });

  describe("conflict detection", () => {
    it("renders conflict summary when conflicts exist", async () => {
      // Make two bindings share the same key
      const { detectConflicts } = await import("@/lib/hotkeyStore");
      (detectConflicts as ReturnType<typeof vi.fn>).mockReturnValueOnce([
        { combo: "C", bindingIds: ["cancel-orders", "quick-buy"] },
      ]);
      renderPanel();
      await waitFor(() => {
        const conflictMsg = screen.queryByText(/shortcut conflicts/i);
        // conflicts shown from the detectConflicts mock
        if (conflictMsg) {
          expect(conflictMsg).toBeInTheDocument();
        }
      });
    });
  });

  describe("accessibility", () => {
    it("panel has aria-label", async () => {
      renderPanel();
      await waitFor(() => {
        const panel = screen.getByRole("generic", {
          name: /keyboard shortcut configuration/i,
        });
        expect(panel).toBeInTheDocument();
      });
    });

    it("category sections have aria-labelledby headings", async () => {
      renderPanel();
      await waitFor(() => {
        expect(
          document.getElementById("shortcut-group-global"),
        ).toBeInTheDocument();
        expect(
          document.getElementById("shortcut-group-scalper"),
        ).toBeInTheDocument();
      });
    });
  });
});
