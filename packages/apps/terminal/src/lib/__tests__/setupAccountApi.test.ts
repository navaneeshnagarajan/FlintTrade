import { describe, it, expect, vi, beforeEach } from "vitest";
import { setupFlintTradeAccount } from "../setupAccountApi";

describe("setupAccountApi", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns TOTP URI and backup codes on successful account setup", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "success",
          data: {
            totp_uri: "otpauth://totp/FlintTrade:alice",
            backup_codes: ["ABCD-1234"],
            token: "setup-session-jwt",
          },
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(
      setupFlintTradeAccount({
        username: "alice",
        email: "alice@example.com",
        password: "Secret123!",
        pin: "",
      }),
    ).resolves.toEqual({
      totpUri: "otpauth://totp/FlintTrade:alice",
      backupCodes: ["ABCD-1234"],
      // The setup response now mints an explore session so the rest of the
      // wizard (broker connect, mode select) is authenticated (audit fix).
      token: "setup-session-jwt",
    });

    expect(fetch).toHaveBeenCalledWith("/ft-api/v1/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: "alice",
        email: "alice@example.com",
        password: "Secret123!",
        pin: "",
      }),
    });
  });

  it("keeps account-exists errors distinct from backend connectivity errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "error",
          message: "An account already exists on this machine.",
        }),
        { status: 409, headers: { "Content-Type": "application/json" } },
      ),
    );

    await expect(
      setupFlintTradeAccount({
        username: "alice",
        email: "alice@example.com",
        password: "Secret123!",
      }),
    ).rejects.toMatchObject({
      name: "AccountSetupError",
      kind: "account-exists",
      status: 409,
      message: "An account already exists on this machine.",
    });
  });

  it("does not report non-JSON backend responses as an unreachable server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>proxy error</html>", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(
      setupFlintTradeAccount({
        username: "alice",
        email: "alice@example.com",
        password: "Secret123!",
      }),
    ).rejects.toMatchObject({
      kind: "server",
      status: 502,
      message: "FlintTrade backend responded with HTTP 502 Bad Gateway.",
    });
  });

  it("reports real fetch failures as backend connectivity problems", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(
      setupFlintTradeAccount({
        username: "alice",
        email: "alice@example.com",
        password: "Secret123!",
      }),
    ).rejects.toMatchObject({
      kind: "network",
      message: "Cannot reach server. Is the FlintTrade backend running?",
    });
  });
});
