/**
 * useGlobalKeys tests
 *
 * Tests keyboard shortcut handling. Mocks api calls and verifies
 * that handlers fire correctly based on active element and key combos.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock api service
// ---------------------------------------------------------------------------

const mockCancelAllOrders = vi.fn(() => Promise.resolve());
const mockExitAllPositions = vi.fn(() => Promise.resolve());
const mockEmitNotification = vi.hoisted(() => vi.fn());

vi.mock("@/services/api", () => ({
  cancelAllOrders: () => mockCancelAllOrders(),
  exitAllPositions: () => mockExitAllPositions(),
}));

vi.mock("@/components/NotificationCentre/useNotificationFeed", () => ({
  emitNotification: mockEmitNotification,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import useGlobalKeys from "../useGlobalKeys";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fireKey(key: string, opts: Partial<KeyboardEventInit> = {}): void {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...opts,
  });
  window.dispatchEvent(event);
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  // Ensure activeElement is body (not an input)
  Object.defineProperty(document, "activeElement", {
    value: document.body,
    writable: true,
    configurable: true,
  });
  // Mock window.confirm to auto-accept (tests verify the API call, not the dialog)
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useGlobalKeys", () => {
  it("calls onEscape when Escape is pressed", () => {
    const onEscape = vi.fn();
    renderHook(() => useGlobalKeys({ onEscape }));

    fireKey("Escape");

    expect(onEscape).toHaveBeenCalledOnce();
  });

  it("calls onCommandPalette when Ctrl+K is pressed", () => {
    const onCommandPalette = vi.fn();
    renderHook(() => useGlobalKeys({ onCommandPalette }));

    fireKey("k", { ctrlKey: true });

    expect(onCommandPalette).toHaveBeenCalledOnce();
  });

  it("handles uppercase Ctrl+K keyboard events", () => {
    const onCommandPalette = vi.fn();
    renderHook(() => useGlobalKeys({ onCommandPalette }));

    fireKey("K", { ctrlKey: true });

    expect(onCommandPalette).toHaveBeenCalledOnce();
  });

  it("calls cancelAllOrders when C is pressed", () => {
    renderHook(() => useGlobalKeys({}));

    fireKey("c");

    expect(mockCancelAllOrders).toHaveBeenCalled();
  });

  it("calls exitAllPositions with Shift+X", () => {
    renderHook(() => useGlobalKeys({}));

    fireKey("X", { shiftKey: true });

    expect(mockExitAllPositions).toHaveBeenCalledTimes(1);
  });

  it("plain X (advertised in the /trade banner) confirms and calls exitAllPositions", () => {
    renderHook(() => useGlobalKeys({}));

    fireKey("x");

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(mockExitAllPositions).toHaveBeenCalledTimes(1);
  });

  it("does not call exitAllPositions when the confirmation is declined", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    renderHook(() => useGlobalKeys({}));

    fireKey("x");

    expect(mockExitAllPositions).not.toHaveBeenCalled();
  });

  it("surfaces a synchronous exit-all admission failure", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockExitAllPositions.mockImplementationOnce(() => {
      throw new Error("Exit all positions is available only in Live mode.");
    });
    renderHook(() => useGlobalKeys({}));

    fireKey("x");

    await waitFor(() => {
      expect(mockEmitNotification).toHaveBeenCalledWith({
        category: "order",
        title: "Exit all positions failed",
        body: "Exit all positions is available only in Live mode.",
      });
    });
  });

  // Regression: the hook is mounted by BOTH AppLayout and TerminalRoute on
  // /trade. A single keypress must show ONE confirm dialog and execute the
  // destructive action ONCE — never twice.
  it("double-mounted hook fires exactly one confirm + one cancelAllOrders for C", () => {
    renderHook(() => useGlobalKeys({}));
    renderHook(() => useGlobalKeys({ onEscape: vi.fn() }));

    fireKey("c");

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(mockCancelAllOrders).toHaveBeenCalledTimes(1);
  });

  it("double-mounted hook fires exactly one confirm + one exitAllPositions for Shift+X", () => {
    renderHook(() => useGlobalKeys({}));
    renderHook(() => useGlobalKeys({}));

    fireKey("X", { shiftKey: true });

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(mockExitAllPositions).toHaveBeenCalledTimes(1);
  });

  it("does not fire shortcuts when INPUT is focused", () => {
    const onEscape = vi.fn();
    Object.defineProperty(document, "activeElement", {
      value: { tagName: "INPUT" },
      writable: true,
      configurable: true,
    });

    renderHook(() => useGlobalKeys({ onEscape }));
    fireKey("Escape");

    expect(onEscape).not.toHaveBeenCalled();
  });

  it("does not fire shortcuts when TEXTAREA is focused", () => {
    Object.defineProperty(document, "activeElement", {
      value: { tagName: "TEXTAREA" },
      writable: true,
      configurable: true,
    });

    renderHook(() => useGlobalKeys({}));
    fireKey("c");

    expect(mockCancelAllOrders).not.toHaveBeenCalled();
  });

  it("does not fire shortcuts when contentEditable element is focused", () => {
    Object.defineProperty(document, "activeElement", {
      value: { tagName: "DIV", isContentEditable: true },
      writable: true,
      configurable: true,
    });

    renderHook(() => useGlobalKeys({}));
    fireKey("c");

    expect(mockCancelAllOrders).not.toHaveBeenCalled();
  });

  it("does not call cancelAllOrders on Ctrl+C (copy)", () => {
    renderHook(() => useGlobalKeys({}));

    fireKey("c", { ctrlKey: true });

    expect(mockCancelAllOrders).not.toHaveBeenCalled();
  });

  it("cleans up event listener on unmount", () => {
    const onEscape = vi.fn();
    const { unmount } = renderHook(() => useGlobalKeys({ onEscape }));

    unmount();
    fireKey("Escape");

    expect(onEscape).not.toHaveBeenCalled();
  });
});
