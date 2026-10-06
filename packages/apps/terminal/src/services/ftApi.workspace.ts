import { get, post, put, del } from "./ftApi.helpers";
import { isPublicDemoBuild } from "@/lib/demoSession";

export interface PresetWidgetEntry {
  id: string;
  component: string;
  title: string;
  position?: {
    direction?: "left" | "right" | "above" | "below" | "within";
    referenceComponent?: string;
  };
  initialWidth?: number;
  initialHeight?: number;
}

// The backend preset model stores `widgets` as an ordered list of widget IDs
// (strings), and does not return `icon`/`widget_count` — keep the client types in
// lock-step so create/update don't 400 and cards don't show "undefined widgets".
export interface WorkspacePresetRecord {
  id: string;
  name: string;
  description: string;
  icon?: string;
  is_builtin: boolean;
  widget_count?: number;
  widgets: string[];
  created_at?: string;
  updated_at?: string;
}

export interface CreatePresetPayload {
  name: string;
  description: string;
  icon?: string;
  widgets: string[];
}

export interface UpdatePresetPayload {
  name?: string;
  description?: string;
  icon?: string;
  widgets?: string[];
}

export const listPresets = async () => {
  if (isPublicDemoBuild()) return (await import("./publicDemoPresets")).listPublicDemoPresets();
  return get<{ presets: WorkspacePresetRecord[] }>("presets/");
};

export const createPreset = async (payload: CreatePresetPayload) => {
  if (isPublicDemoBuild()) return (await import("./publicDemoPresets")).createPublicDemoPreset(payload);
  return post<WorkspacePresetRecord>("presets/", payload);
};

export const updatePreset = async (id: string, payload: UpdatePresetPayload) => {
  if (isPublicDemoBuild()) return (await import("./publicDemoPresets")).updatePublicDemoPreset(id, payload);
  return put<WorkspacePresetRecord>(`presets/${encodeURIComponent(id)}`, payload);
};

export const deletePreset = async (id: string) => {
  if (isPublicDemoBuild()) return (await import("./publicDemoPresets")).deletePublicDemoPreset(id);
  return del<{ success: boolean }>(`presets/${encodeURIComponent(id)}`);
};

export const forkPreset = async (id: string, name: string) => {
  if (isPublicDemoBuild()) return (await import("./publicDemoPresets")).forkPublicDemoPreset(id, name);
  return post<WorkspacePresetRecord>(`presets/${encodeURIComponent(id)}/fork`, { name });
};
