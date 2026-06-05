import { get, post, put, del } from "./ftApi.helpers";

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

export const listPresets = () =>
  get<{ presets: WorkspacePresetRecord[] }>("presets/");

export const getPreset = (id: string) =>
  get<WorkspacePresetRecord>(`presets/${encodeURIComponent(id)}`);

export const createPreset = (payload: CreatePresetPayload) =>
  post<WorkspacePresetRecord>("presets/", payload);

export const updatePreset = (id: string, payload: UpdatePresetPayload) =>
  put<WorkspacePresetRecord>(`presets/${encodeURIComponent(id)}`, payload);

export const deletePreset = (id: string) =>
  del<{ success: boolean }>(`presets/${encodeURIComponent(id)}`);

export const forkPreset = (id: string, name: string) =>
  post<WorkspacePresetRecord>(`presets/${encodeURIComponent(id)}/fork`, { name });
