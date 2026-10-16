import { beforeEach, describe, expect, it, vi } from "vitest";

const account = "live:native:dhan:SYNTHETIC-A";
const valid = { version: 1, kind: "captured", account } as const;
describe("notification disclosure persistence", () => {
  beforeEach(() => { localStorage.clear(); vi.resetModules(); });
  it("restores explicit acknowledgement and generic decisions without losing either account", async () => {
    const store = await import("../notificationStore");
    const ack = store.addNotification({ category: "order", title: "Acknowledged A", body: "Not a fill.", accountScopeKey: account, originDisclosure: valid });
    const generic = store.addNotification({ category: "order", title: "Unknown", body: "Reconcile.", accountScopeKey: account, originDisclosure: { version: 1, kind: "none" } });
    vi.resetModules();
    const reloaded = await import("../notificationStore");
    expect(reloaded.getSnapshot()).toEqual([generic, ack]);
    expect(reloaded.notificationAccountOrigin(reloaded.getSnapshot()[0])).toBeNull();
    expect(reloaded.notificationAccountOrigin(reloaded.getSnapshot()[1])).toBe(account);
  });
  it.each([
    { name: "null", metadata: null },
    { name: "array", metadata: [valid] },
    { name: "string", metadata: account },
    { name: "unknown version", metadata: { ...valid, version: 9 } },
    { name: "oversized", metadata: { ...valid, account: "A".repeat(1025) } },
    { name: "unknown key", metadata: { ...valid, current: true } },
    { name: "missing kind", metadata: { version: 1, account } },
  ])("$name fails closed on reload without dropping legitimate neighbouring acknowledgements", async ({ metadata }) => {
    const original = { id: "ack", timestamp: "2026-01-01T00:00:00Z", read: false, category: "order", title: "Ack", body: "Not a fill.", accountScopeKey: account };
    localStorage.setItem("flinttrade:notifications", JSON.stringify([{ ...original, id: "bad", originDisclosure: metadata }, { ...original, originDisclosure: valid }, { ...original, id: "legacy" }]));
    const store = await import("../notificationStore");
    expect(store.getSnapshot()).toHaveLength(3);
    expect(store.getSnapshot()[0]).toMatchObject({ accountScopeKey: account, originDisclosure: { version: 1, kind: "none" } });
    expect(store.getSnapshot().map(store.notificationAccountOrigin)).toEqual([null, account, account]);
  });
  it("display provenance is not reconstructed from routing when metadata is present", async () => {
    const store = await import("../notificationStore");
    const notice = store.addNotification({ category: "order", title: "Ack", body: "Not a fill.", accountScopeKey: "live:native:dhan:SYNTHETIC-B", originDisclosure: valid });
    expect(notice.accountScopeKey).toBe("live:native:dhan:SYNTHETIC-B");
    expect(store.notificationAccountOrigin(notice)).toBe(account);
  });
});
