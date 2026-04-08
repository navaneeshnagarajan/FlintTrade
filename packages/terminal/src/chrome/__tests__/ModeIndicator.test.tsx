/**
 * ModeIndicator.test.tsx
 *
 * Tests for the TopBar mode pill/toggle component.
 * Verifies rendering per mode, toggle behaviour, and PIN dialog flow.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useModeStore } from "@/stores/modeStore";
import ModeIndicator from "../ModeIndicator";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStore(mode: "explore" | "practice" | "live" = "explore") {
  useModeStore.setState({ mode });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ModeIndicator", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  // --- Explore mode ---------------------------------------------------------

  describe("explore mode", () => {
    it("renders an EXPLORE pill", () => {
      resetStore("explore");
      render(<ModeIndicator />);

      expect(screen.getByText("EXPLORE")).toBeInTheDocument();
    });

    it("is a static div, not a button (no toggle)", () => {
      resetStore("explore");
      render(<ModeIndicator />);

      const pill = screen.getByText("EXPLORE").closest("div");
      expect(pill).toBeInTheDocument();
      expect(screen.queryByRole("button")).not.toBeInTheDocument();
    });

    it("has the correct aria-label", () => {
      resetStore("explore");
      render(<ModeIndicator />);

      expect(
        screen.getByLabelText("Explore mode — sample data only"),
      ).toBeInTheDocument();
    });
  });

  // --- Practice mode --------------------------------------------------------

  describe("practice mode", () => {
    it("renders a PRACTICE button", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      const button = screen.getByRole("button", { name: /practice mode/i });
      expect(button).toBeInTheDocument();
      expect(screen.getByText("PRACTICE")).toBeInTheDocument();
    });

    it("opens PIN dialog when clicked (practice -> live requires PIN)", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      expect(
        screen.getByText("Switch to Live Trading?"),
      ).toBeInTheDocument();
    });

    it("shows PIN input field in the dialog", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const pinInput = screen.getByPlaceholderText("6-digit PIN");
      expect(pinInput).toBeInTheDocument();
    });

    it("disables confirm button when PIN is not 6 digits", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const confirmBtn = screen.getByRole("button", {
        name: /switch to live/i,
      });
      expect(confirmBtn).toBeDisabled();
    });

    it("validates PIN must be exactly 6 digits", async () => {
      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const pinInput = screen.getByPlaceholderText("6-digit PIN");
      fireEvent.change(pinInput, { target: { value: "123" } });

      const confirmBtn = screen.getByRole("button", {
        name: /switch to live/i,
      });
      expect(confirmBtn).toBeDisabled();
    });

    it("switches to live after successful PIN verification", async () => {
      // Mock successful PIN fetch
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status: 200 }),
      );

      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const pinInput = screen.getByPlaceholderText("6-digit PIN");
      fireEvent.change(pinInput, { target: { value: "123456" } });

      const confirmBtn = screen.getByRole("button", {
        name: /switch to live/i,
      });
      fireEvent.click(confirmBtn);

      await waitFor(() => {
        expect(useModeStore.getState().mode).toBe("live");
      });
    });

    it("does not switch to live on incorrect PIN", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response(null, { status: 401 }),
      );

      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const pinInput = screen.getByPlaceholderText("6-digit PIN");
      fireEvent.change(pinInput, { target: { value: "000000" } });

      const confirmBtn = screen.getByRole("button", {
        name: /switch to live/i,
      });
      fireEvent.click(confirmBtn);

      // Wait for the async fetch to settle
      await waitFor(() => {
        expect(globalThis.fetch).toHaveBeenCalledOnce();
      });

      // Mode must remain practice — incorrect PIN must not switch to live
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("does not switch to live on network error", async () => {
      vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
        new Error("Network error"),
      );

      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));

      const pinInput = screen.getByPlaceholderText("6-digit PIN");
      fireEvent.change(pinInput, { target: { value: "123456" } });

      const confirmBtn = screen.getByRole("button", {
        name: /switch to live/i,
      });
      fireEvent.click(confirmBtn);

      // Wait for the async fetch to settle
      await waitFor(() => {
        expect(globalThis.fetch).toHaveBeenCalledOnce();
      });

      // Mode must remain practice — network failure must not switch to live
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("closes dialog on cancel without changing mode", () => {
      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));
      expect(screen.getByText("Switch to Live Trading?")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("button", { name: /cancel/i }));

      expect(useModeStore.getState().mode).toBe("practice");
    });
  });

  // --- Live mode ------------------------------------------------------------

  describe("live mode", () => {
    it("renders a LIVE button", () => {
      resetStore("live");
      render(<ModeIndicator />);

      const button = screen.getByRole("button", { name: /live trading/i });
      expect(button).toBeInTheDocument();
      expect(screen.getByText("LIVE")).toBeInTheDocument();
    });

    it("switches to practice instantly on click (no PIN needed)", () => {
      resetStore("live");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));

      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("does not open a PIN dialog when switching to practice", () => {
      resetStore("live");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));

      expect(
        screen.queryByText("Switch to Live Trading?"),
      ).not.toBeInTheDocument();
    });
  });
});
