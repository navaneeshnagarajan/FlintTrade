/**
 * LoginRoute.test.tsx
 *
 * Smoke tests for the login form component.
 * Mocks authStore and brand logo to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const { mockSetLoggedIn, mockUpdateToken, mockSetMode, modeState } = vi.hoisted(() => ({
  mockSetLoggedIn: vi.fn(),
  mockUpdateToken: vi.fn(),
  mockSetMode: vi.fn((mode: "explore" | "practice" | "live") => {
    modeState.mode = mode;
  }),
  modeState: { mode: "explore" as "explore" | "practice" | "live" },
}));

vi.mock("@/stores/authStore", () => ({
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({
      setLoggedIn: mockSetLoggedIn,
      updateToken: mockUpdateToken,
      setLoggedOut: vi.fn(),
      username: "testuser",
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: Object.assign(() => ({}), {
    getState: () => ({
      mode: modeState.mode,
      setMode: mockSetMode,
    }),
    setState: vi.fn(),
  }),
}));

vi.mock("@/components/brand/Logo", () => ({
  LogoIcon: ({ size }: { size: number }) => (
    <svg data-testid="logo-icon" width={size} height={size} />
  ),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import LoginRoute from "../LoginRoute";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LoginRoute", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
    modeState.mode = "explore";
  });

  it("renders the login form with heading", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByText("Welcome Back")).toBeInTheDocument();
  });

  it("has password and 2FA code inputs in full mode", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByLabelText("Enter your password")).toBeInTheDocument();
    expect(screen.getByLabelText("Enter your 2FA code")).toBeInTheDocument();
  });

  it("has a Sign In button in full mode", () => {
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("clears a stale Live UI mode after normal password and 2FA login", async () => {
    modeState.mode = "live";
    const onSuccess = vi.fn();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "success",
          data: { token: "explore-session", username: "testuser", expires_at: "2026-07-02T08:00:00+05:30" },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LoginRoute onSuccess={onSuccess} mode="full" />);

    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    fireEvent.change(screen.getByLabelText("Enter your 2FA code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    expect(mockSetLoggedIn).toHaveBeenCalledWith("explore-session", "testuser", "2026-07-02T08:00:00+05:30");
    expect(mockSetMode).toHaveBeenCalledWith("explore");
  });

  it("upgrades the explore login JWT to practice when the UI was in Practice", async () => {
    // Phase 1 G1 (login half): password login always mints an explore JWT.
    // If the persisted UI mode is Practice, LoginRoute must call /auth/mode to
    // sync the token to practice — otherwise sandbox orders 403 mode_blocked.
    modeState.mode = "practice";
    const onSuccess = vi.fn();
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "success",
            data: { token: "explore-session", username: "testuser", expires_at: "" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            status: "success",
            data: { token: "practice-session", mode: "practice", live_mode_unlocked: false },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    render(<LoginRoute onSuccess={onSuccess} mode="full" />);

    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    fireEvent.change(screen.getByLabelText("Enter your 2FA code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
    // Second call is the /auth/mode practice upgrade carrying the login token.
    expect(fetchSpy).toHaveBeenCalledWith(
      "/ft-api/v1/auth/mode",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ mode: "practice" }) }),
    );
    expect(mockUpdateToken).toHaveBeenCalledWith("practice-session");
    // Mode stays practice — it must NOT have been dropped to explore.
    expect(mockSetMode).not.toHaveBeenCalledWith("explore");
  });

  it("accepts an 8-char backup code in the 2FA field and enables Sign In", () => {
    // The field must take a backup code (upper-hex, 8 chars), not only a
    // 6-digit TOTP — the backend accepts either, so the UI must too.
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    const field = screen.getByLabelText("Enter your 2FA code") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "a1b2c3d4" } });

    expect(field.value).toBe("A1B2C3D4"); // upper-cased, all 8 chars kept
    expect(screen.getByRole("button", { name: /sign in/i })).not.toBeDisabled();
  });

  it("recovers a lost authenticator: password mints a fresh QR + backup codes", async () => {
    // The lockout fix — a self-hosted operator who lost their TOTP device AND
    // backup codes can reset 2FA from the login screen with just their password.
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "success",
          data: {
            totp_uri: "otpauth://totp/FlintTrade:testuser?secret=ABCDEF23GHIJKL45&issuer=FlintTrade",
            backup_codes: ["A1B2C3D4", "E5F6A7B8"],
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    fireEvent.click(screen.getByRole("button", { name: /lost your authenticator/i }));
    expect(screen.getByText("Reset your 2FA")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Confirm your password to reset 2FA"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset 2fa$/i }));

    await waitFor(() => expect(screen.getByText("New 2FA ready")).toBeInTheDocument());
    expect(screen.getByText("A1B2C3D4")).toBeInTheDocument();
    expect(screen.getByText("E5F6A7B8")).toBeInTheDocument();
    // The manual-entry secret is surfaced from the otpauth URI.
    expect(screen.getByText("ABCDEF23GHIJKL45")).toBeInTheDocument();
  });

  it("surfaces a wrong-password error in the recovery panel", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({ status: "error", message: "Invalid password." }),
        { status: 401, headers: { "Content-Type": "application/json" } },
      ),
    );
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    fireEvent.click(screen.getByRole("button", { name: /lost your authenticator/i }));
    fireEvent.change(screen.getByLabelText("Confirm your password to reset 2FA"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset 2fa$/i }));

    await waitFor(() => expect(screen.getByText("Invalid password.")).toBeInTheDocument());
    // Stays on the confirm view — no QR minted.
    expect(screen.queryByText("New 2FA ready")).not.toBeInTheDocument();
  });
});
