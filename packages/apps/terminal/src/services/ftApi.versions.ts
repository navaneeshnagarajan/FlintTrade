import { z } from "zod";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";

const version = z.string().regex(/^[v0-9][0-9A-Za-z.!+_-]{0,127}$/).nullable();
const name = z.string().regex(/^[A-Za-z][A-Za-z0-9 ._-]{0,79}$/);
const commit = z.string().regex(/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i).nullable();
const inventorySchema = z.object({
  app_version: version,
  runtimes: z.array(z.object({ name, version })).max(10),
  packages: z.array(z.object({ name, installed: version, configured: version })).max(30),
  brokers: z.array(z.object({ name, installed: version, configured: version, source_commit: commit, installed_commit: commit, release_version: version.optional() })).max(20),
});
export type BackendVersionInventory = z.infer<typeof inventorySchema>;

const ollamaSchema = z.object({
  configured: version,
  reported: version,
  status: z.enum(["reported", "not_responding", "unavailable"]),
});
export type OllamaVersionInventory = z.infer<typeof ollamaSchema>;

async function readInventory<T>(path: string, parse: (value: unknown) => T, signal?: AbortSignal): Promise<T> {
  if (isDemoAuthSession()) throw new Error("Backend versions are unavailable in Demo.");
  const response = await fetch(`${getBase()}/api/v1/versions${path}`, {
    headers: buildHeaders(false),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(5000)]) : AbortSignal.timeout(5000),
    cache: "no-store",
  });
  if (!response.ok) throw new Error("Backend version information is unavailable.");
  return parse(await response.json());
}

export function getVersionInventory(signal?: AbortSignal): Promise<BackendVersionInventory> {
  return readInventory("", (value) => inventorySchema.parse(value), signal);
}

export function getOllamaVersionInventory(signal?: AbortSignal): Promise<OllamaVersionInventory> {
  return readInventory("/ollama", (value) => ollamaSchema.parse(value), signal);
}
