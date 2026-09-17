import { afterEach, describe, expect, it, vi } from "vitest";
import { AccountMutationActions, runAccountAction } from "../accountMutationActions";
import { useAuthStore } from "@/stores/authStore";
import { accountMutation, FtApiError } from "../ftApi.helpers";

afterEach(() => vi.restoreAllMocks());

describe("caller-owned account action identity", () => {
  it("retains a key after a lost response and retires it only after success", async () => {
    const actions = new AccountMutationActions();
    const keys: string[] = [];
    await expect(actions.run("native:dhan:fixture:connect", async (key) => {
      keys.push(key);
      throw new TypeError("lost response");
    })).rejects.toThrow("lost response");
    await actions.run("native:dhan:fixture:connect", async (key) => keys.push(key));
    await actions.run("native:dhan:fixture:connect", async (key) => keys.push(key));
    expect(keys[0]).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("refuses overlapping sends without confusing different form submissions", async () => {
    const actions = new AccountMutationActions();
    let finish!: (value: string) => void;
    const send = vi.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
    const first = actions.run("native:dhan:fixture:reconnect", send);
    await expect(actions.run("native:dhan:fixture:reconnect", send)).rejects.toThrow("in progress");
    await Promise.resolve();
    expect(send).toHaveBeenCalledTimes(1);
    finish("done");
    expect(await first).toBe("done");
  });

  it("does not reuse another scope's key and cancellation permits a new action", async () => {
    const actions = new AccountMutationActions();
    const keys: string[] = [];
    const lost = async (key: string) => { keys.push(key); throw new Error("lost"); };
    await expect(actions.run("native:dhan:fixture:connect", lost)).rejects.toThrow();
    await expect(actions.run("native:upstox:fixture:connect", lost)).rejects.toThrow();
    actions.cancel("native:dhan:fixture:connect");
    await expect(actions.run("native:dhan:fixture:connect", lost)).rejects.toThrow();
    expect(new Set(keys).size).toBe(3);
  });

  it("retires a definitively rejected request but retains ambiguous HTTP outcomes", async () => {
    const actions = new AccountMutationActions();
    const keys: string[] = [];
    for (const status of [400, 503, 408, 429]) {
      await expect(actions.run("http-errors", async (key) => {
        keys.push(key);
        throw new FtApiError("synthetic failure", status);
      })).rejects.toThrow("synthetic failure");
    }
    expect(keys[1]).not.toBe(keys[0]);
    expect(new Set(keys.slice(1)).size).toBe(1);
  });

  it("refuses cancellation while an attempt is still awaiting its outcome", async () => {
    const actions = new AccountMutationActions();
    let finish!: () => void;
    const attempt = actions.run("scope", () => new Promise<void>((resolve) => { finish = resolve; }));
    await Promise.resolve();
    expect(() => actions.cancel("scope")).toThrow("in progress");
    finish();
    await attempt;
  });

  it("validates scope before invoking the transport", async () => {
    const actions = new AccountMutationActions();
    const send = vi.fn();
    await expect(actions.run("", send)).rejects.toThrow("scope");
    expect(send).not.toHaveBeenCalled();
  });

  it("refuses a session change before transport dispatch", async () => {
    const send = vi.fn();
    const attempt = runAccountAction("session-change", send);
    useAuthStore.setState({ sessionGeneration: useAuthStore.getState().sessionGeneration + 1 });
    await expect(attempt).rejects.toThrow("session has changed");
    expect(send).not.toHaveBeenCalled();
  });

  it("passes one caller key unchanged through a lost HTTP response", async () => {
    const actions = new AccountMutationActions();
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("lost response"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "success", data: { connected: true } })));
    const send = (key: string) => accountMutation("api/v1", "POST", "native/accounts", key, { fixture: true });
    await expect(actions.run("http-fixture", send)).rejects.toThrow("lost response");
    await actions.run("http-fixture", send);
    const keys = fetchSpy.mock.calls.map((call) => (call[1]?.headers as Record<string, string>)["Idempotency-Key"]);
    expect(keys[0]).toBe(keys[1]);
    expect(keys[0]).toMatch(/^[a-f0-9-]{36}$/);
  });

  it("does not allocate a key at the low-level fetch boundary", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const mint = vi.spyOn(crypto, "randomUUID");
    await expect(accountMutation("v1", "DELETE", "accounts/fixture", "invalid")).rejects.toThrow("Idempotency-Key");
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(mint).not.toHaveBeenCalled();
  });
});
