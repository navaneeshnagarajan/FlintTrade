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
  listBrokerMcpCatalogue,
  listNativeAccounts,
  connectNativeAccount,
  oauthStartNativeAccount,
  readNativeAccount,
  reloginNativeAccount,
  setPrimaryNativeAccount,
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

  it("listBrokerMcpCatalogue returns broker-hosted MCP metadata", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({
        brokers: [
          {
            adapter_id: "upstox",
            display_name: "Upstox",
            native: true,
            connectable: true,
            mcp: { remote_url: "https://mcp.upstox.com/mcp", read_only: true, trading_supported: false },
          },
        ],
      }),
    );
    const brokers = await listBrokerMcpCatalogue();
    expect(brokers).toHaveLength(1);
    expect(brokers[0].adapter_id).toBe("upstox");
    expect(brokers[0].mcp.read_only).toBe(true);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/broker/mcp"),
      expect.anything(),
    );
  });

  it("listNativeAccounts returns the accounts array (not an empty list)", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({
        accounts: [
          { adapter_id: "dhan", account_id: "A1", needs_relogin: true },
          { adapter_id: "upstox", account_id: "U1", login_retryable: true },
        ],
      }),
    );
    const accounts = await listNativeAccounts();
    expect(accounts).toHaveLength(2);
    expect(accounts[0].needs_relogin).toBe(true);
    expect(accounts[1].login_retryable).toBe(true);
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

  it("readNativeAccount reads a specific live native account book", async () => {
    fetchSpy.mockResolvedValueOnce(envelope([{ symbol: "INFY", order_id: "O1" }]));
    const rows = await readNativeAccount<Array<{ symbol: string }>>("dhan", "A1", "orders");
    expect(rows).toEqual([{ symbol: "INFY", order_id: "O1" }]);
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/native/accounts/dhan/A1/orders"),
      expect.anything(),
    );
  });

  it("setPrimaryNativeAccount posts to the selector-scoped primary route", async () => {
    fetchSpy.mockResolvedValueOnce(envelope({ account: { adapter_id: "upstox", account_id: "U1" } }));
    await setPrimaryNativeAccount("upstox", "U1");
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/native/accounts/upstox/U1/set-primary"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("oauthStartNativeAccount returns the unwrapped auth_url payload", async () => {
    fetchSpy.mockResolvedValueOnce(
      envelope({
        auth_url: "https://api.upstox.com/x",
        state: "S",
        redirect_uri: "http://cb",
        postback_uri: "http://postback",
      }),
    );
    const r = await oauthStartNativeAccount({
      adapter_id: "upstox",
      account_id: "U1",
      api_key: "K",
      api_secret: "S",
    });
    expect(r.auth_url).toContain("upstox.com");
    expect(r.postback_uri).toBe("http://postback");
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
