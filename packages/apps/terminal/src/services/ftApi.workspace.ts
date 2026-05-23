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

export interface WorkspacePresetRecord {
  id: string;
  name: string;
  description: string;
  icon: string;
  source: "builtin" | "custom";
  widget_count: number;
  widgets: PresetWidgetEntry[];
  created_at?: string;
  updated_at?: string;
}

export interface CreatePresetPayload {
  name: string;
  description: string;
  icon?: string;
  widgets: PresetWidgetEntry[];
}

export interface UpdatePresetPayload {
  name?: string;
  description?: string;
  icon?: string;
  widgets?: PresetWidgetEntry[];
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
