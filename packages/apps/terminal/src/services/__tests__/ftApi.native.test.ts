/**
 * ftApi.native.test.ts — exercises the REAL get/post envelope unwrapping.
 *
 * Audit regression: `get`/`post` (ftApi.helpers) already unwrap the backend
 * `{status, data}` envelope, so ftApi.native must NOT read a second `.data`
 * level — otherwise every list is silently empty and the whole Brokers connect
 * UI (accounts, G7 amber state, Re-authenticate) can never render. These tests
 * drive the actual fetch → parseResponse → ftApi.native chain (not a mock of
 * ftApi.native itself) so the double-unwrap can never come back.
 */

import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";

import {
  listNativeBrokers,
  listNativeAccounts,
  connectNativeAccount,
  oauthStartNativeAccount,
  reloginNativeAccount,
} from "../ftApi.native";

function envelope(data: unknown, status = 200): Response {
  return new Response(JSON.stringify({ status: "success", data }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

let fetchSpy: MockInstance<typeof globalThis.fetch>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch");
});
afterEach(() => {
  fetchSpy.mockRestore();
});

describe("ftApi.native envelope unwrapping", () => {
  it("listNativeBrokers returns the brokers array from {status,data:{brokers}}", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({ brokers: [{ adapter_id: "dhan", display_name: "Dhan", auth_methods: [] }] }),
    );
    const brokers = await listNativeBrokers();
    expect(brokers).toHaveLength(1);
    expect(brokers[0].adapter_id).toBe("dhan");
  });

  it("listNativeAccounts returns the accounts array (not an empty list)", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({ accounts: [{ adapter_id: "dhan", account_id: "A1", needs_relogin: true }] }),
    );
    const accounts = await listNativeAccounts();
    expect(accounts).toHaveLength(1);
    expect(accounts[0].needs_relogin).toBe(true);
  });

  it("connectNativeAccount reads connected/login from the unwrapped data", async () => {
    fetchSpy.mockResolvedValueOnce(envelope({ connected: true, login: "ok" }));
    const r = await connectNativeAccount({
      adapter_id: "dhan",
      account_id: "A1",
      credentials: { access_token: "t" },
    });
    expect(r.connected).toBe(true);
    expect(r.login).toBe("ok");
  });

  it("oauthStartNativeAccount returns the unwrapped auth_url payload", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({ auth_url: "https://api.upstox.com/x", state: "S", redirect_uri: "http://cb" }),
    );
    const r = await oauthStartNativeAccount({
      adapter_id: "upstox",
      account_id: "U1",
      api_key: "K",
      api_secret: "S",
    });
    expect(r.auth_url).toContain("upstox.com");
  });

  it("reloginNativeAccount resolves a live session from {data:{session}}", async () => {
    fetchSpy.mockResolvedValueOnce(envelope({ login: "ok", session: { has_session: true, expires_at: 1 } }));
    const s = await reloginNativeAccount("dhan", "A1");
    expect(s.has_session).toBe(true);
  });

  it("reloginNativeAccount throws when the session did not establish", async () => {
    fetchSpy.mockResolvedValueOnce(envelope({ login: "login-failed", session: { has_session: false } }));
    await expect(reloginNativeAccount("dhan", "A1")).rejects.toThrow(/fresh credentials/i);
  });
});
