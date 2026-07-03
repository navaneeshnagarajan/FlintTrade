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

const setLoggedIn = vi.fn();
let currentMode: "explore" | "practice" | "live" = "practice";

vi.mock("@/stores/authStore", () => ({
  useAuthStore: (selector: (s: {
    username: string;
    setLoggedOut: () => void;
    setLoggedIn: () => void;
  }) => unknown) =>
    selector({
      username: "testuser",
      setLoggedOut: vi.fn(),
      setLoggedIn,
    }),
}));

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
});
