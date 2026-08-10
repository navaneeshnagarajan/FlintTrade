/**
 * ModeIndicator.test.tsx
 *
 * Tests for the TopBar mode pill/toggle component.
 * Verifies rendering per mode, toggle behaviour, and PIN dialog flow.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useModeStore } from "@/stores/modeStore";
import { useAuthStore } from "@/stores/authStore";
import ModeIndicator from "../ModeIndicator";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStore(mode: "explore" | "practice" | "live" = "explore") {
  useModeStore.setState({ mode });
  // Reset auth state to a known starting token so the mode-switch
  // requests carry an Authorization header.
  useAuthStore.setState({
    status: "logged-in",
    token: "initial-jwt-token",
    reauthToken: null,
    username: "testuser",
    sessionGeneration: 0,
  });
}

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

    it("switches to Practice when clicked, syncing the JWT server-side", async () => {
      // Phase 1 G1 regression: Explore→Practice must call /auth/mode so the
      // backend upgrades the explore JWT to practice. Without the server round
      // trip the UI showed Practice while the JWT stayed explore and every
      // sandbox order was rejected 403 mode_blocked.
      resetStore("explore");
      const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({ status: "success", data: { token: "practice-jwt", mode: "practice" } }),
      );

      render(<ModeIndicator />);
      fireEvent.click(screen.getByRole("button", { name: /explore mode active/i }));

      await waitFor(() => expect(useModeStore.getState().mode).toBe("practice"));
      expect(fetchSpy).toHaveBeenCalledWith(
        "/ft-api/v1/auth/mode",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ mode: "practice" }) }),
      );
      // The explore JWT is replaced with the practice JWT the server minted.
      expect(useAuthStore.getState().token).toBe("practice-jwt");
    });

    it("stays in Explore if the Practice JWT sync fails", async () => {
      resetStore("explore");
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(jsonResponse({}, 503));

      render(<ModeIndicator />);
      fireEvent.click(screen.getByRole("button", { name: /explore mode active/i }));

      await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
      expect(useModeStore.getState().mode).toBe("explore");
    });

    it("routes demo users to account setup instead of switching to API-backed Practice", () => {
      resetStore("explore");
      useAuthStore.setState({ token: "demo-user" });
      const listener = vi.fn();
      window.addEventListener("flinttrade:navigate", listener);
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /explore mode active/i }));

      expect(useModeStore.getState().mode).toBe("explore");
      expect(listener).toHaveBeenCalledTimes(1);
      const event = listener.mock.calls[0]?.[0] as CustomEvent<{ path?: string }>;
      expect(event.detail.path).toBe("/setup");
      window.removeEventListener("flinttrade:navigate", listener);
    });

    it("has the correct aria-label", () => {
      resetStore("explore");
      render(<ModeIndicator />);

      expect(
        screen.getByLabelText(/explore mode active/i),
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

    it("switches to live after successful PIN verification + stores the live JWT", async () => {
      // PIN response now must include a token — frontend uses it to
      // replace authStore.token so future order calls send the
      // live-unlocked JWT (closes the 2026-05-19 Codex CRITICAL finding).
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: { token: "live-unlocked-jwt", live_mode_unlocked: true },
        }),
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
      // The authStore token must now be the live-unlocked JWT, NOT the
      // initial Practice JWT that was in place before.
      expect(useAuthStore.getState().token).toBe("live-unlocked-jwt");
    });

    it("ignores a PIN response that arrives after the session locks", async () => {
      let finishRequest: ((response: Response) => void) | undefined;
      vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          finishRequest = resolve;
        }),
      );

      resetStore("practice");
      render(<ModeIndicator />);
      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());

      act(() => useAuthStore.getState().setPinRequired());
      await act(async () => {
        finishRequest?.(jsonResponse({
          status: "success",
          data: { token: "late-live-token", mode: "live", live_mode_unlocked: true },
        }));
        await Promise.resolve();
      });

      expect(useAuthStore.getState()).toMatchObject({
        status: "pin-required",
        token: null,
        username: "testuser",
      });
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("rejects PIN flow if server returned no token", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({ status: "success", data: {} }),
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
        expect(globalThis.fetch).toHaveBeenCalledOnce();
      });
      // Mode stays practice and the in-memory token doesn't change.
      expect(useModeStore.getState().mode).toBe("practice");
      expect(useAuthStore.getState().token).toBe("initial-jwt-token");
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

    it("surfaces the server's error message on PIN failure (pin_not_set guidance)", async () => {
      // The backend distinguishes "wrong PIN" from "no PIN set" — the
      // pin_not_set message points the operator at Settings → Security. The
      // dialog must show THAT message, not a hardcoded "Incorrect PIN.".
      const serverMessage =
        "No PIN is set for this account — the optional PIN was skipped at " +
        "setup. Create one in Settings → Security (POST /v1/auth/pin/set), " +
        "then retry.";
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({ status: "error", code: "pin_not_set", message: serverMessage }, 409),
      );

      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      expect(await screen.findByText(serverMessage)).toBeInTheDocument();
      expect(useModeStore.getState().mode).toBe("practice");
    });

    it("falls back to the hardcoded PIN error only when no message is available", async () => {
      // A non-Error rejection carries no message — the last-resort fallback.
      vi.spyOn(globalThis, "fetch").mockRejectedValueOnce("boom");

      resetStore("practice");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /practice mode/i }));
      fireEvent.change(screen.getByPlaceholderText("6-digit PIN"), {
        target: { value: "123456" },
      });
      fireEvent.click(screen.getByRole("button", { name: /switch to live/i }));

      expect(await screen.findByText("Incorrect PIN. Try again.")).toBeInTheDocument();
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

    it("calls /v1/auth/mode + stores new practice JWT + flips UI", async () => {
      // Mode-switch response carries the new Practice JWT. The frontend
      // MUST swap it in via authStore.updateToken so a stale
      // live-unlocked token doesn't outlive the UI toggle (closes
      // 2026-05-19 Codex CRITICAL finding).
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            token: "fresh-practice-jwt",
            mode: "practice",
            live_mode_unlocked: false,
          },
        }),
      );

      resetStore("live");
      useAuthStore.setState({ token: "stale-live-jwt" });
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));

      await waitFor(() => {
        expect(useModeStore.getState().mode).toBe("practice");
      });
      expect(useAuthStore.getState().token).toBe("fresh-practice-jwt");

      // Confirm the call shape — Bearer auth + practice body.
      const fetchCall = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
      const [url, init] = fetchCall as [string, RequestInit];
      expect(url).toBe("/ft-api/v1/auth/mode");
      expect(init.method).toBe("POST");
      const headers = init.headers as Record<string, string>;
      expect(headers["Authorization"]).toBe("Bearer stale-live-jwt");
      expect(JSON.parse(init.body as string)).toEqual({ mode: "practice" });
    });

    it("ignores a mode response that arrives after logout", async () => {
      let finishRequest: ((response: Response) => void) | undefined;
      vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          finishRequest = resolve;
        }),
      );

      resetStore("live");
      useAuthStore.setState({ token: "stale-live-jwt" });
      render(<ModeIndicator />);
      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));
      await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());

      act(() => useAuthStore.getState().setLoggedOut());
      await act(async () => {
        finishRequest?.(jsonResponse({
          status: "success",
          data: { token: "late-practice-token", mode: "practice" },
        }));
        await Promise.resolve();
      });

      expect(useAuthStore.getState()).toMatchObject({
        status: "logged-out",
        token: null,
        username: null,
      });
      expect(useModeStore.getState().mode).toBe("live");
    });

    it("does NOT flip to practice if mode-switch endpoint fails", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("", { status: 500 }),
      );

      resetStore("live");
      useAuthStore.setState({ token: "stale-live-jwt" });
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));

      // The error message is surfaced to the user once the failed request
      // settles — await it so the async rejection has fully propagated
      // before asserting the state stayed put.
      expect(await screen.findByRole("alert")).toBeInTheDocument();
      expect(globalThis.fetch).toHaveBeenCalledOnce();
      // Stayed in live — the UI must never claim Practice while the
      // backend still has a live-unlocked JWT in its blocklist's good
      // standing.
      expect(useModeStore.getState().mode).toBe("live");
      expect(useAuthStore.getState().token).toBe("stale-live-jwt");
    });

    it("does not open a PIN dialog when switching to practice", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: { token: "p", mode: "practice", live_mode_unlocked: false },
        }),
      );

      resetStore("live");
      render(<ModeIndicator />);

      fireEvent.click(screen.getByRole("button", { name: /live trading/i }));

      await waitFor(() => {
        expect(useModeStore.getState().mode).toBe("practice");
      });
      expect(
        screen.queryByText("Switch to Live Trading?"),
      ).not.toBeInTheDocument();
    });
  });
});
