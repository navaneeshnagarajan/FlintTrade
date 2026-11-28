import { describe, it, expect, vi, beforeEach } from "vitest";
import { confirmLiveMode, downgradeMode, unlockWithPin } from "../modeAuth";
import { useAuthStore } from "@/stores/authStore";

function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("modeAuth session reissue", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useAuthStore.setState({
      status: "logged-in",
      token: "session-tok",
      reauthToken: null,
      username: "user",
      expiresAt: "2026-11-29T02:30:00+00:00",
    });
  });

  it("returns the unchanged expires_at from a PIN unlock", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "success",
        data: {
          token: "pin-tok",
          mode: "practice",
          live_mode_unlocked: false,
          expires_at: "2026-11-29T02:30:00+00:00",
        },
      }),
    );
    await expect(unlockWithPin("123456")).resolves.toEqual({
      token: "pin-tok",
      expiresAt: "2026-11-29T02:30:00+00:00",
    });
  });

  it("returns the unchanged expires_at from a Live switch", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "success",
        data: {
          token: "live-tok",
          mode: "live",
          live_mode_unlocked: true,
          expires_at: "2026-11-29T02:30:00+00:00",
        },
      }),
    );
    await expect(confirmLiveMode("123456")).resolves.toEqual({
      token: "live-tok",
      expiresAt: "2026-11-29T02:30:00+00:00",
    });
  });

  it("returns the unchanged expires_at from a Mode downgrade", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        status: "success",
        data: {
          token: "practice-tok",
          mode: "practice",
          live_mode_unlocked: false,
          expires_at: "2026-11-29T02:30:00+00:00",
        },
      }),
    );
    await expect(downgradeMode("practice", "session-tok")).resolves.toEqual({
      token: "practice-tok",
      expiresAt: "2026-11-29T02:30:00+00:00",
    });
  });
});
