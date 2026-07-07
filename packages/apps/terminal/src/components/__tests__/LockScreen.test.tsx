/**
 * LockScreen.test.tsx — Renders the lock screen UI with PIN input, and
 * verifies the Phase 1 G2 fix: idle PIN unlock is mode-preserving and never
 * silently escalates an Explore/Practice session to a Live-unlocked JWT.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — both stores, so the test can drive the current UI mode
// ---------------------------------------------------------------------------

// vi.hoisted so the mock factory (hoisted above imports) can build its state
// object eagerly — the factory now references setLoggedIn at mock time, not
// lazily inside the selector.
const { setLoggedIn } = vi.hoisted(() => ({ setLoggedIn: vi.fn() }));
let currentMode: "explore" | "practice" | "live" = "practice";

vi.mock("@/stores/authStore", () => {
  const state = {
    username: "testuser",
    token: "current-session-jwt",
    setLoggedOut: vi.fn(),
    setLoggedIn,
  };
  // modeAuth.unlockWithPin reads the session token via getState() — the PIN
  // unlock is session-bound (policy D6), so the mock must expose it.
  const useAuthStore = (selector: (s: typeof state) => unknown) => selector(state);
  useAuthStore.getState = () => state;
  return { useAuthStore };
});

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) =>
    selector({ mode: currentMode }),
}));

import { LockScreen } from "../LockScreen";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LockScreen", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    setLoggedIn.mockClear();
    currentMode = "practice";
  });

  it("renders the lock screen dialog with user name", () => {
    render(<LockScreen />);
    expect(screen.getByRole("dialog", { name: /screen locked/i })).toBeInTheDocument();
    expect(screen.getByText("testuser")).toBeInTheDocument();
  });

  it("has a hidden PIN input field", () => {
    render(<LockScreen />);
    expect(screen.getByLabelText(/enter your 6-digit pin/i)).toBeInTheDocument();
  });

  it("unlocks preserving the current mode — a Practice session does NOT escalate to Live", async () => {
    currentMode = "practice";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { token: "practice-jwt", mode: "practice", live_mode_unlocked: false },
      }),
    );

    render(<LockScreen />);
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin/i), {
      target: { value: "123456" },
    });

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());
    // The PIN request carries the current UI mode so the server mints a
    // matching (non-live-unlocked) token — the G2 divergence fix.
    expect(fetchSpy).toHaveBeenCalledWith(
      "/ft-api/v1/auth/pin",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ pin: "123456", mode: "practice" }),
      }),
    );
    await waitFor(() => expect(setLoggedIn).toHaveBeenCalledWith("practice-jwt", "testuser", ""));
  });

  it("sends the live mode when the session was already Live", async () => {
    currentMode = "live";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { token: "live-jwt", mode: "live", live_mode_unlocked: true },
      }),
    );

    render(<LockScreen />);
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin/i), {
      target: { value: "654321" },
    });

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledOnce());
    expect(fetchSpy).toHaveBeenCalledWith(
      "/ft-api/v1/auth/pin",
      expect.objectContaining({
        body: JSON.stringify({ pin: "654321", mode: "live" }),
      }),
    );
  });

  it("surfaces the server's error message on PIN failure (pin_not_set guidance)", async () => {
    // The backend distinguishes "wrong PIN" from "no PIN set" — pin_not_set
    // tells the operator to create one in Settings → Security. The lock
    // screen must show THAT message, not a hardcoded "Incorrect PIN.".
    const serverMessage =
      "No PIN is set for this account — the optional PIN was skipped at " +
      "setup. Create one in Settings → Security (POST /v1/auth/pin/set), " +
      "then retry.";
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({ status: "error", code: "pin_not_set", message: serverMessage }, 409),
    );

    render(<LockScreen />);
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin/i), {
      target: { value: "123456" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(serverMessage);
    expect(setLoggedIn).not.toHaveBeenCalled();
  });

  it("falls back to the hardcoded PIN error only when no message is available", async () => {
    // A non-Error rejection carries no message — the last-resort fallback.
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce("boom");

    render(<LockScreen />);
    fireEvent.change(screen.getByLabelText(/enter your 6-digit pin/i), {
      target: { value: "123456" },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Incorrect PIN. Try again.",
    );
    expect(setLoggedIn).not.toHaveBeenCalled();
  });
});
