import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { getVersionInventory, getOllamaVersionInventory } from "../ftApi.versions";

const valid = { app_version: "v0.0.1", runtimes: [{ name: "Python", version: "3.12.9" }], packages: [], brokers: [] };
beforeEach(() => { useAuthStore.setState({ token: "synthetic-session" }); useConnectionStore.setState({ apiKey: "" }); });
afterEach(() => vi.unstubAllGlobals());
describe("version metadata request", () => {
  it("uses one authenticated bounded read and bypasses caches", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(valid)));
    vi.stubGlobal("fetch", fetcher);
    await expect(getVersionInventory()).resolves.toEqual(valid);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/ft-api/api/v1/versions", {
      headers: { Authorization: "Bearer synthetic-session" }, signal: expect.any(AbortSignal), cache: "no-store",
    });
  });
  it("reads only the observational Ollama endpoint", async () => {
    const payload = { configured: "v0.35.0", reported: "0.32.0", status: "reported" };
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload)));
    vi.stubGlobal("fetch", fetcher);
    await expect(getOllamaVersionInventory()).resolves.toEqual(payload);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/ft-api/api/v1/versions/ollama", {
      headers: { Authorization: "Bearer synthetic-session" }, signal: expect.any(AbortSignal), cache: "no-store",
    });
  });
  it("never requests metadata for demo sessions", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    useAuthStore.setState({ token: "demo-user" });
    await expect(getVersionInventory()).rejects.toThrow("unavailable in Demo");
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("honours caller cancellation", async () => {
    const controller = new AbortController();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(valid))));
    await getVersionInventory(controller.signal);
    const signal = vi.mocked(fetch).mock.calls[0][1]?.signal;
    controller.abort();
    expect(signal?.aborted).toBe(true);
  });
  it.each([
    { ...valid, app_version: "/private/home" },
    { ...valid, brokers: [{ name: "kotakneoapi", installed: "3.0.7", configured: "3.0.7", source_commit: "main", installed_commit: null }] },
    { ...valid, packages: [{ name: "x", installed: 123, configured: null }] },
  ])("rejects malformed or unbounded metadata", async (payload) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(getVersionInventory()).rejects.toThrow();
  });
  it("accepts bounded Python epoch versions and full SHA-256 Git object IDs", async () => {
    const payload = { ...valid, packages: [{ name: "example", installed: "1!2.0.0", configured: null }], brokers: [{ name: "kotakneoapi", installed: "3.0.7", configured: "3.0.7", source_commit: "a".repeat(64), installed_commit: "b".repeat(40) }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))));
    await expect(getVersionInventory()).resolves.toEqual(payload);
  });
  it("does not echo backend error text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private-host", { status: 503 })));
    await expect(getVersionInventory()).rejects.toThrow("Backend version information is unavailable.");
  });
});
