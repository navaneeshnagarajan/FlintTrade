import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: { getState: () => ({ apiKey: "" }) },
}));
vi.mock("@/stores/authStore", () => ({
  useAuthStore: { getState: () => ({ token: "demo-user" }) },
}));

import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";
import { createPreset, deletePreset, forkPreset, listPresets, updatePreset } from "../ftApi.workspace";

const STORAGE_KEY = "flinttrade:public-demo-presets:v1";
const draft = { name: "Synthetic browser preset", description: "Example only", widgets: ["chart", "watchlist"] };

beforeEach(() => {
  vi.stubEnv("BASE_URL", "/demo-app/");
  localStorage.clear();
  // Reproduce the public site's HTML response instead of pretending a preset
  // backend exists. The public-demo adapter must never reach this boundary.
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response("<!DOCTYPE html><title>Site</title>")));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("public-demo workspace presets", () => {
  it("loads the real built-in catalogue without an API request", async () => {
    const result = await listPresets();
    expect(result.presets.map((preset) => preset.id)).toEqual(WORKSPACE_PRESETS.map((preset) => preset.id));
    expect(result.presets.every((preset) => preset.is_builtin && preset.widgets.length > 0)).toBe(true);
    expect(result.presets.find((preset) => preset.id === "multi-chart")?.widgets).toEqual(["chart", "chart", "chart", "chart"]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("persists create, update, fork and delete locally across module reloads", async () => {
    const created = await createPreset(draft);
    expect(created).toMatchObject({ ...draft, is_builtin: false });
    expect(created.id).toMatch(/^demo-preset-/);
    await updatePreset(created.id, { name: "Renamed synthetic preset" });
    vi.resetModules();
    const reloaded = await import("../ftApi.workspace");
    expect((await reloaded.listPresets()).presets.find((preset) => preset.id === created.id))
      .toMatchObject({ ...draft, name: "Renamed synthetic preset" });
    const builtin = (await reloaded.listPresets()).presets.find((preset) => preset.is_builtin)!;
    const forked = await reloaded.forkPreset(builtin.id, "Synthetic fork");
    expect(forked).toMatchObject({ name: "Synthetic fork", widgets: builtin.widgets, is_builtin: false });
    await reloaded.deletePreset(created.id);
    expect((await reloaded.listPresets()).presets.some((preset) => preset.id === created.id)).toBe(false);
    expect((await reloaded.listPresets()).presets.some((preset) => preset.id === forked.id)).toBe(true);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not allow custom writes to mutate the built-in catalogue", async () => {
    await expect(updatePreset(WORKSPACE_PRESETS[0].id, { name: "Changed" })).rejects.toThrow(/built-in/i);
    await expect(deletePreset(WORKSPACE_PRESETS[0].id)).rejects.toThrow(/built-in/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects stale identities without modifying a different preset", async () => {
    const created = await createPreset(draft);
    const original = localStorage.getItem(STORAGE_KEY);
    await expect(updatePreset("missing-preset", { name: "Wrong target" })).rejects.toThrow(/no longer exists/i);
    await expect(deletePreset("missing-preset")).rejects.toThrow(/no longer exists/i);
    await expect(forkPreset("missing-preset", "Wrong fork")).rejects.toThrow(/no longer exists/i);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(original);
    expect((await listPresets()).presets.find((preset) => preset.id === created.id)?.name).toBe(draft.name);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects case-insensitive name collisions across built-ins, custom presets and forks", async () => {
    const created = await createPreset(draft);
    const second = await createPreset({ ...draft, name: "Second synthetic preset" });
    const original = localStorage.getItem(STORAGE_KEY);
    await expect(createPreset({ ...draft, name: ` ${draft.name.toUpperCase()} ` })).rejects.toThrow(/already exists/i);
    await expect(createPreset({ ...draft, name: WORKSPACE_PRESETS[0].name.toLowerCase() })).rejects.toThrow(/already exists/i);
    await expect(updatePreset(second.id, { name: draft.name.toUpperCase() })).rejects.toThrow(/already exists/i);
    await expect(updatePreset(second.id, { name: WORKSPACE_PRESETS[0].name.toUpperCase() })).rejects.toThrow(/already exists/i);
    await expect(forkPreset(WORKSPACE_PRESETS[0].id, draft.name.toUpperCase())).rejects.toThrow(/already exists/i);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(original);
    await expect(updatePreset(created.id, { name: draft.name.toUpperCase() }))
      .resolves.toMatchObject({ id: created.id, name: draft.name.toUpperCase() });
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects malformed records and ambiguous duplicate identities", async () => {
    const created = await createPreset(draft);
    for (const presets of [[{ ...created, widgets: [{}] }], [created, created]]) {
      const raw = JSON.stringify({ version: 1, presets });
      localStorage.setItem(STORAGE_KEY, raw);
      await expect(listPresets()).rejects.toThrow(/corrupt/i);
      expect(localStorage.getItem(STORAGE_KEY)).toBe(raw);
    }
    expect(fetch).not.toHaveBeenCalled();
  });

  it("surfaces corrupt storage without replacing existing bytes", async () => {
    localStorage.setItem(STORAGE_KEY, "broken JSON");
    await expect(listPresets()).rejects.toThrow(/corrupt/i);
    await expect(createPreset(draft)).rejects.toThrow(/corrupt/i);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("broken JSON");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("does not report success when browser persistence fails", async () => {
    const created = await createPreset(draft);
    const original = localStorage.getItem(STORAGE_KEY);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("Synthetic quota failure"); });
    await expect(updatePreset(created.id, { name: "Not saved" })).rejects.toThrow(/browser/i);
    expect(localStorage.getItem(STORAGE_KEY)).toBe(original);
    expect((await listPresets()).presets.find((preset) => preset.id === created.id)?.name).toBe(draft.name);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("surfaces unavailable browser storage without falling back to the backend", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("Synthetic storage denial"); });
    await expect(listPresets()).rejects.toThrow(/read presets saved in this browser/i);
    await expect(createPreset(draft)).rejects.toThrow(/read presets saved in this browser/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("keeps preset mutations separate from existing workspace storage", async () => {
    localStorage.setItem("flinttrade:workspaces", "synthetic workspace metadata");
    localStorage.setItem("flinttrade:layouts", "synthetic workspace layout");
    await createPreset(draft);
    expect(localStorage.getItem("flinttrade:workspaces")).toBe("synthetic workspace metadata");
    expect(localStorage.getItem("flinttrade:layouts")).toBe("synthetic workspace layout");
  });

  it("validates imported payload shapes and supplies the description default", async () => {
    await expect(createPreset({ ...draft, widgets: [42] } as unknown as typeof draft)).rejects.toThrow();
    await expect(createPreset({ ...draft, name: " " })).rejects.toThrow();
    const created = await createPreset({ name: "Minimal import", widgets: ["chart"] } as typeof draft);
    expect(created.description).toBe("");
    expect(created.widgets).toEqual(["chart"]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("preserves normal installed backend requests even for an Example session", async () => {
    vi.stubEnv("BASE_URL", "/");
    vi.stubEnv("DEV", false);
    const backendPreset = { ...draft, id: "server-preset", is_builtin: false };
    vi.mocked(fetch).mockImplementation(async () => new Response(JSON.stringify({ data: backendPreset })));
    await createPreset(draft);
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/presets/", expect.objectContaining({ method: "POST", body: JSON.stringify(draft) }));
    await listPresets();
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/presets/", expect.any(Object));
    await updatePreset("server/id", { name: "Updated" });
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/presets/server%2Fid", expect.objectContaining({ method: "PUT" }));
    await deletePreset("server/id");
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/presets/server%2Fid", expect.objectContaining({ method: "DELETE" }));
    await forkPreset("server/id", "Fork");
    expect(fetch).toHaveBeenLastCalledWith("/api/v1/presets/server%2Fid/fork", expect.objectContaining({ method: "POST" }));
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
