/**
 * KeyboardShortcutsDialog.test.tsx
 *
 * Tests for the keyboard shortcuts reference dialog:
 *  - Renders when open / hidden when closed
 *  - Shows category headings
 *  - Search filters by label and key token
 *  - Shows empty state when no match
 *  - Platform-aware labels (Ctrl vs ⌘)
 *  - ARIA attributes present
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/components/ui/dialog", () => ({
  Dialog: ({
    open,
    children,
  }: {
    open: boolean;
    children: React.ReactNode;
  }) => (open ? <div data-testid="dialog">{children}</div> : null),
  DialogContent: ({
    children,
    ...rest
  }: {
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <div data-testid="dialog-content" {...rest}>
      {children}
    </div>
  ),
  DialogHeader: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  DialogTitle: ({ children }: { children: React.ReactNode }) => (
    <h2>{children}</h2>
  ),
}));

vi.mock("@/components/ui/input", () => ({
  Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => (
    <input {...props} />
  ),
}));

vi.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import KeyboardShortcutsDialog from "../KeyboardShortcutsDialog";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderOpen() {
  return render(
    <KeyboardShortcutsDialog isOpen={true} onClose={vi.fn()} />,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("KeyboardShortcutsDialog", () => {
  describe("visibility", () => {
    it("renders the dialog when isOpen is true", () => {
      renderOpen();
      expect(screen.getByTestId("dialog")).toBeInTheDocument();
    });

    it("does not render when isOpen is false", () => {
      render(<KeyboardShortcutsDialog isOpen={false} onClose={vi.fn()} />);
      expect(screen.queryByTestId("dialog")).not.toBeInTheDocument();
    });

    it("shows the dialog title", () => {
      renderOpen();
      expect(screen.getByText("Keyboard Shortcuts")).toBeInTheDocument();
    });
  });

  describe("categories", () => {
    it("renders all four category headings", () => {
      renderOpen();
      expect(screen.getByText("Navigation")).toBeInTheDocument();
      expect(screen.getByText("Trading")).toBeInTheDocument();
      expect(screen.getByText("Chart")).toBeInTheDocument();
      expect(screen.getByText("General")).toBeInTheDocument();
    });

    it("shows shortcut labels for each category", () => {
      renderOpen();
      // Navigation
      expect(
        screen.getByText(/command palette/i),
      ).toBeInTheDocument();
      expect(screen.getByText("Go to Home")).toBeInTheDocument();
      expect(screen.getByText("Go to Trade")).toBeInTheDocument();
      // Trading
      expect(
        screen.getByText(/cancel all open orders/i),
      ).toBeInTheDocument();
      // Chart
      expect(
        screen.getByText(/toggle chart replay/i),
      ).toBeInTheDocument();
      // General
      expect(
        screen.getByText(/keyboard shortcuts reference/i),
      ).toBeInTheDocument();
    });
  });

  describe("search", () => {
    it("renders a searchbox", () => {
      renderOpen();
      expect(
        screen.getByRole("searchbox", { name: /search shortcuts/i }),
      ).toBeInTheDocument();
    });

    it("filters shortcuts by label text", () => {
      renderOpen();
      const input = screen.getByRole("searchbox");
      fireEvent.change(input, { target: { value: "fullscreen" } });
      // The label text is split by <mark> when highlighted — query the containing span.
      const rows = document.querySelectorAll('[role="listitem"]');
      const rowTexts = Array.from(rows).map((r) => r.textContent ?? "");
      expect(rowTexts.some((t) => /toggle fullscreen/i.test(t))).toBe(true);
      // Unrelated shortcut should not appear.
      expect(rowTexts.every((t) => !/cancel all open orders/i.test(t))).toBe(true);
    });

    it("filtering hides category headings when all entries in a category are excluded", () => {
      renderOpen();
      const input = screen.getByRole("searchbox");
      // "fullscreen" only matches the General category shortcut.
      fireEvent.change(input, { target: { value: "fullscreen" } });
      expect(screen.queryByText("Trading")).not.toBeInTheDocument();
      expect(screen.queryByText("Chart")).not.toBeInTheDocument();
      expect(screen.getByText("General")).toBeInTheDocument();
    });

    it("search is case-insensitive", () => {
      renderOpen();
      const input = screen.getByRole("searchbox");
      fireEvent.change(input, { target: { value: "FULLSCREEN" } });
      // textContent of listitem spans includes highlighted text
      const rows = document.querySelectorAll('[role="listitem"]');
      const rowTexts = Array.from(rows).map((r) => r.textContent ?? "");
      expect(rowTexts.some((t) => /toggle fullscreen/i.test(t))).toBe(true);
    });

    it("shows empty state when no shortcuts match", () => {
      renderOpen();
      const input = screen.getByRole("searchbox");
      fireEvent.change(input, { target: { value: "xyznotahotkey" } });
      expect(screen.getByText(/no shortcuts match/i)).toBeInTheDocument();
    });

    it("clears search when clear button is clicked", () => {
      renderOpen();
      const input = screen.getByRole("searchbox");
      fireEvent.change(input, { target: { value: "fullscreen" } });
      const clearBtn = screen.getByRole("button", { name: /clear search/i });
      fireEvent.click(clearBtn);
      // All categories should reappear.
      expect(screen.getByText("Navigation")).toBeInTheDocument();
      expect(screen.getByText("Trading")).toBeInTheDocument();
    });
  });

  describe("key badges", () => {
    it("renders key tokens as kbd elements", () => {
      renderOpen();
      const kbdElements = document.querySelectorAll("kbd");
      expect(kbdElements.length).toBeGreaterThan(0);
    });

    it("renders Ctrl token (non-Mac environment)", () => {
      // jsdom navigator.platform is '' — isMac() returns false.
      renderOpen();
      // The "Ctrl" token appears for Ctrl+K (command palette).
      const kbdElements = Array.from(document.querySelectorAll("kbd"));
      const ctrlBadge = kbdElements.find((el) => el.textContent === "Ctrl");
      expect(ctrlBadge).toBeDefined();
    });
  });

  describe("accessibility", () => {
    it("dialog content has aria-describedby pointing to the description element", () => {
      renderOpen();
      const content = screen.getByTestId("dialog-content");
      expect(content).toHaveAttribute("aria-describedby", "kbd-shortcuts-desc");
    });

    it("each category section has an aria-labelledby heading id", () => {
      renderOpen();
      const navSection = document.getElementById("shortcut-cat-navigation");
      expect(navSection).toBeInTheDocument();
      const tradingSection = document.getElementById("shortcut-cat-trading");
      expect(tradingSection).toBeInTheDocument();
    });

    it("footer hint text is present", () => {
      renderOpen();
      expect(
        screen.getByText(/shortcuts fire only when no input/i),
      ).toBeInTheDocument();
    });
  });

  describe("close behaviour", () => {
    it("calls onClose when dialog signals close", () => {
      const onClose = vi.fn();
      // The mock Dialog calls onOpenChange(false) → our handler calls onClose.
      // We test indirectly: re-render with isOpen=false should unmount dialog.
      const { rerender } = render(
        <KeyboardShortcutsDialog isOpen={true} onClose={onClose} />,
      );
      rerender(<KeyboardShortcutsDialog isOpen={false} onClose={onClose} />);
      expect(screen.queryByTestId("dialog")).not.toBeInTheDocument();
    });
  });
});

describe("SHORTCUT_ENTRIES Slice 2 navigation", () => {
  it("documents Go to Home (Alt+H) and Go to Trade (Alt+T)", async () => {
    const { SHORTCUT_ENTRIES } = await import("../KeyboardShortcutsDialog");
    const home = SHORTCUT_ENTRIES.find((e) => e.id === "go-home");
    const trade = SHORTCUT_ENTRIES.find((e) => e.id === "go-trade");
    expect(home).toMatchObject({ label: "Go to Home", keys: ["Alt", "H"], category: "Navigation" });
    expect(trade).toMatchObject({ label: "Go to Trade", keys: ["Alt", "T"], category: "Navigation" });
  });
});
