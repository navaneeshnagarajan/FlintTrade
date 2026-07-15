/**
 * LoginRoute.test.tsx
 *
 * Smoke tests for the login form component.
 * Mocks authStore and brand logo to keep tests lightweight.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const {
  authState,
  modeState,
  mockCaptureAuthSessionFence,
  mockSetLoggedInIfCurrent,
  mockSetMode,
  mockUpdateToken,
} = vi.hoisted(() => {
  type MockAuthStatus =
    | "unknown"
    | "transitioning"
    | "logged-in"
    | "logged-out"
    | "pin-required"
    | "setup-required";
  interface MockFence {
    status: MockAuthStatus;
    principal: string | null;
    generation: number;
  }
  const authState = {
    status: "logged-out" as MockAuthStatus,
    token: null as string | null,
    reauthToken: null as string | null,
    username: null as string | null,
    sessionGeneration: 7,
  };
  const currentFence = (): MockFence => ({
    status: authState.status,
    principal: authState.username?.trim() || null,
    generation: authState.sessionGeneration,
  });
  const fenceIsCurrent = (fence: MockFence): boolean => (
    fence.status === authState.status &&
    fence.principal === (authState.username?.trim() || null) &&
    fence.generation === authState.sessionGeneration
  );
  const mockCaptureAuthSessionFence = vi.fn(currentFence);
  const mockSetLoggedInIfCurrent = vi.fn(
    (token: string, username: string, _expiresAt: string, fence: MockFence) => {
      if (!fenceIsCurrent(fence)) return false;
      Object.assign(authState, {
        status: "logged-in",
        token,
        reauthToken: null,
        username,
        sessionGeneration: authState.sessionGeneration + 1,
      });
      return true;
    },
  );
  const mockUpdateToken = vi.fn((token: string, expectedGeneration: number) => {
    if (authState.status !== "logged-in" || authState.sessionGeneration !== expectedGeneration) {
      return false;
    }
    authState.token = token;
    authState.sessionGeneration += 1;
    return true;
  });
  const modeState = { mode: "explore" as "explore" | "practice" | "live" };
  const mockSetMode = vi.fn((mode: "explore" | "practice" | "live") => {
    modeState.mode = mode;
  });
  return {
    authState,
    modeState,
    mockCaptureAuthSessionFence,
    mockSetLoggedInIfCurrent,
    mockSetMode,
    mockUpdateToken,
    fenceIsCurrent,
  };
});

vi.mock("@/stores/authStore", () => ({
  captureAuthSessionFence: mockCaptureAuthSessionFence,
  isAuthSessionFenceCurrent: (fence: {
    status: string;
    principal: string | null;
    generation: number;
  }) => (
    fence.status === authState.status &&
    fence.principal === (authState.username?.trim() || null) &&
    fence.generation === authState.sessionGeneration
  ),
  useAuthStore: Object.assign(() => ({}), {
    getState: () => ({
      ...authState,
      setLoggedInIfCurrent: mockSetLoggedInIfCurrent,
      updateToken: mockUpdateToken,
      setLoggedOut: vi.fn(),
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
    Object.assign(authState, {
      status: "logged-out",
      token: null,
      reauthToken: null,
      username: null,
      sessionGeneration: 7,
    });
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
    expect(mockSetLoggedInIfCurrent).toHaveBeenCalledWith(
      "explore-session",
      "testuser",
      "2026-07-02T08:00:00+05:30",
      { status: "logged-out", principal: null, generation: 7 },
    );
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
    expect(mockUpdateToken).toHaveBeenCalledWith("practice-session", 8);
    // Mode stays practice — it must NOT have been dropped to explore.
    expect(mockSetMode).not.toHaveBeenCalledWith("explore");
  });

  it("does not install a password response after a different login wins", async () => {
    let finishLogin: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finishLogin = resolve;
      }),
    );
    const onSuccess = vi.fn();
    render(<LoginRoute onSuccess={onSuccess} mode="full" />);

    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    fireEvent.change(screen.getByLabelText("Enter your 2FA code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());
    Object.assign(authState, {
      status: "logged-in",
      token: "newer-token",
      username: "bob",
      sessionGeneration: 8,
    });

    await act(async () => {
      finishLogin?.(new Response(JSON.stringify({
        status: "success",
        data: { token: "late-token", username: "alice", expires_at: "" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
      await Promise.resolve();
    });

    expect(mockSetLoggedInIfCurrent).toHaveReturnedWith(false);
    expect(authState).toMatchObject({ token: "newer-token", username: "bob", sessionGeneration: 8 });
    expect(mockSetMode).not.toHaveBeenCalled();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("does not install a PIN response after the locked session is terminated", async () => {
    Object.assign(authState, {
      status: "pin-required",
      token: null,
      reauthToken: "locked-token",
      username: "testuser",
      sessionGeneration: 11,
    });
    let finishPin: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
      new Promise<Response>((resolve) => {
        finishPin = resolve;
      }),
    );
    const onSuccess = vi.fn();
    render(<LoginRoute onSuccess={onSuccess} mode="pin" />);
    fireEvent.change(screen.getByLabelText("Enter your 6-digit PIN"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: /unlock/i }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledOnce());
    Object.assign(authState, {
      status: "logged-out",
      reauthToken: null,
      username: null,
      sessionGeneration: 12,
    });

    await act(async () => {
      finishPin?.(new Response(JSON.stringify({
        status: "success",
        data: { token: "late-live-token" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }));
      await Promise.resolve();
    });

    expect(mockSetLoggedInIfCurrent).toHaveReturnedWith(false);
    expect(authState).toMatchObject({ status: "logged-out", token: null, username: null });
    expect(mockSetMode).not.toHaveBeenCalledWith("live");
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("does not downgrade or navigate when a stale Practice upgrade fails", async () => {
    modeState.mode = "practice";
    let failPractice: ((error: Error) => void) | undefined;
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: "success",
        data: { token: "explore-session", username: "alice", expires_at: "" },
      }), { status: 200, headers: { "Content-Type": "application/json" } }))
      .mockReturnValueOnce(new Promise<Response>((_resolve, reject) => {
        failPractice = reject;
      }));
    const onSuccess = vi.fn();
    render(<LoginRoute onSuccess={onSuccess} mode="full" />);
    fireEvent.change(screen.getByLabelText("Enter your password"), { target: { value: "password" } });
    fireEvent.change(screen.getByLabelText("Enter your 2FA code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2));
    Object.assign(authState, {
      status: "logged-in",
      token: "newer-token",
      username: "bob",
      sessionGeneration: 9,
    });

    await act(async () => {
      failPractice?.(new Error("late failure"));
      await Promise.resolve();
    });

    expect(mockSetMode).not.toHaveBeenCalledWith("explore");
    expect(onSuccess).not.toHaveBeenCalled();
    expect(authState).toMatchObject({ token: "newer-token", username: "bob" });
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

  it("resets a forgotten password through the email OTP routes", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ status: "success", message: "If registered, a code was sent." }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ status: "success", message: "Password has been reset." }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    fireEvent.click(screen.getByRole("button", { name: /forgot your password/i }));
    fireEvent.change(screen.getByLabelText("Password reset email"), {
      target: { value: " operator@example.com " },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset code/i }));

    await waitFor(() => expect(screen.getByText("Enter reset code")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenNthCalledWith(
      1,
      "/ft-api/v1/auth/forgot-password-otp",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ email: "operator@example.com" }),
      }),
    );

    fireEvent.change(screen.getByLabelText("Password reset code"), { target: { value: "12a3456" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "new-password" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));

    await waitFor(() => expect(screen.getByText("Password reset")).toBeInTheDocument());
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "/ft-api/v1/auth/reset-password-otp",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "operator@example.com",
          otp: "123456",
          new_password: "new-password",
        }),
      }),
    );
  });

  it("does not submit a password reset when confirmations differ", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "success" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    render(<LoginRoute onSuccess={vi.fn()} mode="full" />);

    fireEvent.click(screen.getByRole("button", { name: /forgot your password/i }));
    fireEvent.change(screen.getByLabelText("Password reset email"), {
      target: { value: "operator@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send reset code/i }));
    await waitFor(() => expect(screen.getByText("Enter reset code")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Password reset code"), { target: { value: "123456" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "new-password" } });
    fireEvent.change(screen.getByLabelText("Confirm new password"), { target: { value: "different" } });
    fireEvent.click(screen.getByRole("button", { name: /^reset password$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(fetchSpy).toHaveBeenCalledTimes(1);
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
