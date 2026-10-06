import { z } from "zod";
import { WORKSPACE_PRESETS } from "@/layout/workspacePresets";
import type { CreatePresetPayload, UpdatePresetPayload, WorkspacePresetRecord } from "./ftApi.workspace";

// This collection belongs only to the static public demo. Installed workspace
// metadata and backend presets use different stores and are never migrated here.
const STORAGE_KEY = "flinttrade:public-demo-presets:v1";
const payloadSchema = z.object({
  name: z.string().trim().min(1),
  description: z.string().default(""),
  icon: z.string().optional(),
  widgets: z.array(z.string()),
});
const storedPresetSchema = payloadSchema.extend({
  id: z.string().startsWith("demo-preset-"),
  is_builtin: z.literal(false),
  created_at: z.string(),
  updated_at: z.string(),
});
const storageSchema = z.object({
  version: z.literal(1),
  presets: z.array(storedPresetSchema),
}).refine(({ presets }) => new Set(presets.map(({ id }) => id)).size === presets.length);

type StoredPreset = z.infer<typeof storedPresetSchema>;

function readCustomPresets(): StoredPreset[] {
  let raw: string | null;
  try {
    raw = localStorage.getItem(STORAGE_KEY);
  } catch {
    throw new Error("Could not read presets saved in this browser.");
  }
  if (raw === null) return [];
  try {
    return storageSchema.parse(JSON.parse(raw)).presets;
  } catch {
    // Never replace malformed records with an empty collection: subsequent
    // writes would silently destroy a draft saved by this browser.
    throw new Error("Saved presets in this browser are corrupted and could not be read.");
  }
}

function writeCustomPresets(presets: StoredPreset[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, presets }));
  } catch {
    throw new Error("Could not save presets in this browser. Check browser storage availability.");
  }
}

function widgetIds(node: unknown): string[] {
  if (!node || typeof node !== "object") return [];
  const entry = node as { type?: unknown; component?: unknown; children?: unknown };
  if (entry.type === "tab" && typeof entry.component === "string") return [entry.component];
  return Array.isArray(entry.children) ? entry.children.flatMap(widgetIds) : [];
}

function builtInPresets(): WorkspacePresetRecord[] {
  return WORKSPACE_PRESETS.map((preset) => ({
    id: preset.id,
    name: preset.name,
    description: preset.description,
    icon: preset.icon,
    is_builtin: true,
    widgets: widgetIds(preset.build().layout),
  }));
}

export function listPublicDemoPresets(): { presets: WorkspacePresetRecord[] } {
  return { presets: [...builtInPresets(), ...readCustomPresets()] };
}

function assertUniqueName(name: string, presets: StoredPreset[], currentId?: string): void {
  const normalised = name.toLowerCase();
  const collision = WORKSPACE_PRESETS.some((preset) => preset.name.toLowerCase() === normalised)
    || presets.some((preset) => preset.id !== currentId && preset.name.toLowerCase() === normalised);
  if (collision) throw new Error(`A preset named '${name}' already exists`);
}

export function createPublicDemoPreset(payload: CreatePresetPayload): WorkspacePresetRecord {
  const parsed = payloadSchema.parse(payload);
  const presets = readCustomPresets();
  assertUniqueName(parsed.name, presets);
  const now = new Date().toISOString();
  const preset: StoredPreset = {
    ...parsed,
    id: `demo-preset-${crypto.randomUUID()}`,
    is_builtin: false,
    created_at: now,
    updated_at: now,
  };
  writeCustomPresets([...presets, preset]);
  return preset;
}

function customPresetIndex(presets: StoredPreset[], id: string): number {
  if (WORKSPACE_PRESETS.some((preset) => preset.id === id)) {
    throw new Error("Built-in presets cannot be changed. Fork one to create a custom preset.");
  }
  const index = presets.findIndex((preset) => preset.id === id);
  if (index < 0) throw new Error("This browser preset no longer exists. Refresh the preset list.");
  return index;
}

export function updatePublicDemoPreset(id: string, payload: UpdatePresetPayload): WorkspacePresetRecord {
  const presets = readCustomPresets();
  const index = customPresetIndex(presets, id);
  // Ignore omitted fields, matching the backend's partial-update contract.
  const fields = Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined));
  const parsed = payloadSchema.parse({ ...presets[index], ...fields });
  if ("name" in fields) assertUniqueName(parsed.name, presets, id);
  const updated: StoredPreset = { ...presets[index], ...parsed, updated_at: new Date().toISOString() };
  presets[index] = updated;
  writeCustomPresets(presets);
  return updated;
}

export function deletePublicDemoPreset(id: string): { success: boolean } {
  const presets = readCustomPresets();
  const index = customPresetIndex(presets, id);
  writeCustomPresets(presets.filter((_, candidate) => candidate !== index));
  return { success: true };
}

export function forkPublicDemoPreset(id: string, name: string): WorkspacePresetRecord {
  const source = listPublicDemoPresets().presets.find((preset) => preset.id === id);
  if (!source) throw new Error("This preset no longer exists. Refresh the preset list.");
  return createPublicDemoPreset({ name, description: source.description, icon: source.icon, widgets: source.widgets });
}
