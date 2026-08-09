import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { WorkspaceApi } from "@/layout/flexLayoutAdapter";
import { applyPreset as applyPresetImpl } from "@/layout/workspacePresets";
import { Model } from "flexlayout-react";
import type { IJsonModel } from "flexlayout-react";

export class WorkspaceStorageError extends Error {
  constructor(message = "Workspace storage is corrupted and could not be read.") {
    super(message);
    this.name = "WorkspaceStorageError";
  }
}

interface LayoutTab {
  id: string;
  name: string;
  serializedLayout?: Record<string, unknown>;
}

interface LayoutStore {
  tabs: LayoutTab[];
  activeTabId: string;
  workspaceApi: WorkspaceApi | null;
  widgetPickerOpen: boolean;
  presetPickerOpen: boolean;
  addTab: (name?: string) => void;
  removeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  renameTab: (id: string, name: string) => void;
  saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
  getTabLayout: (id: string) => Record<string, unknown> | undefined;
  setWorkspaceApi: (api: WorkspaceApi | null) => void;
  setWidgetPickerOpen: (open: boolean) => void;
  setPresetPickerOpen: (open: boolean) => void;
  applyPreset: (presetId: string) => void;
}

function generateId(): string {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

const defaultTabId = generateId();

export type SerializedLayoutKind = "empty" | "setup" | "dockview" | "flexlayout" | "corrupt";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasValidOptionalNodeId(node: Record<string, unknown>): boolean {
  return node.id === undefined || (typeof node.id === "string" && node.id.length > 0);
}

function hasOptionalFieldsOfType(
  node: Record<string, unknown>,
  fields: readonly string[],
  expectedType: "string" | "number" | "boolean",
): boolean {
  return fields.every((field) => {
    const value = node[field];
    if (value === undefined) return true;
    if (expectedType === "number") return typeof value === "number" && Number.isFinite(value);
    return typeof value === expectedType;
  });
}

const TAB_BOOLEAN_FIELDS = [
  "enableClose", "enableDrag", "enablePopout", "enablePopoutFloatIcon",
  "enablePopoutIcon", "enablePopoutOverlay", "enableRename", "enableRenderOnDemand",
  "enableScrollbars", "enableWindowReMount", "pinned",
] as const;
const TAB_NUMBER_FIELDS = ["borderHeight", "borderWidth", "closeType", "maxHeight", "maxWidth", "minHeight", "minWidth"] as const;
const TAB_STRING_FIELDS = ["altName", "className", "contentClassName", "helpText", "icon", "subLayoutId", "tabsetClassName"] as const;

const TABSET_BOOLEAN_FIELDS = [
  "active", "maximized", "autoSelectTab", "enableActiveIcon", "enableClose",
  "enableCloseButton", "enableDeleteWhenEmpty", "enableDivide", "enableDrag",
  "enableDrop", "enableMaximize", "enableSingleTabStretch", "enableTabScrollbar",
  "enableTabStrip", "enableTabWrap",
] as const;
const TABSET_NUMBER_FIELDS = ["maxHeight", "maxWidth", "minHeight", "minWidth", "selected", "weight"] as const;
const TABSET_STRING_FIELDS = ["classNameTabStrip", "name"] as const;

function isFlexLayoutTab(node: unknown): boolean {
  return isRecord(node)
    && node.type === "tab"
    && hasValidOptionalNodeId(node)
    && typeof node.component === "string"
    && node.component.length > 0
    && typeof node.name === "string"
    && hasOptionalFieldsOfType(node, TAB_BOOLEAN_FIELDS, "boolean")
    && hasOptionalFieldsOfType(node, TAB_NUMBER_FIELDS, "number")
    && hasOptionalFieldsOfType(node, TAB_STRING_FIELDS, "string");
}

function isFlexLayoutTabset(node: unknown): boolean {
  return isRecord(node)
    && node.type === "tabset"
    && hasValidOptionalNodeId(node)
    && hasOptionalFieldsOfType(node, TABSET_BOOLEAN_FIELDS, "boolean")
    && hasOptionalFieldsOfType(node, TABSET_NUMBER_FIELDS, "number")
    && hasOptionalFieldsOfType(node, TABSET_STRING_FIELDS, "string")
    && (node.tabLocation === undefined || node.tabLocation === "top" || node.tabLocation === "bottom")
    && Array.isArray(node.children)
    && node.children.every(isFlexLayoutTab);
}

function isFlexLayoutRow(node: unknown): boolean {
  return isRecord(node)
    && node.type === "row"
    && hasValidOptionalNodeId(node)
    && hasOptionalFieldsOfType(node, ["weight"], "number")
    && Array.isArray(node.children)
    && node.children.every((child) => isFlexLayoutRow(child) || isFlexLayoutTabset(child));
}

function isFlexLayoutBorder(node: unknown): boolean {
  return isRecord(node)
    && node.type === "border"
    && hasValidOptionalNodeId(node)
    && ["top", "bottom", "left", "right"].includes(String(node.location))
    && hasOptionalFieldsOfType(node, ["autoSelectTabWhenClosed", "autoSelectTabWhenOpen", "enableAutoHide", "enableDrop", "enableTabScrollbar", "show"], "boolean")
    && hasOptionalFieldsOfType(node, ["maxSize", "minSize", "selected", "size"], "number")
    && hasOptionalFieldsOfType(node, ["className"], "string")
    && (node.borderType === undefined || node.borderType === "split" || node.borderType === "overlay")
    && Array.isArray(node.children)
    && node.children.every(isFlexLayoutTab);
}

function isFlexLayoutSubLayout(value: unknown): boolean {
  if (!isRecord(value) || !isFlexLayoutRow(value.layout)) return false;
  if (value.type !== undefined && !["window", "float", "tab"].includes(String(value.type))) return false;
  if (value.rect !== undefined) {
    const rect = value.rect;
    if (!isRecord(rect)) return false;
    if (!hasOptionalFieldsOfType(rect, ["x", "y", "width", "height"], "number")) return false;
    if (!["x", "y", "width", "height"].every((field) => rect[field] !== undefined)) return false;
  }
  return true;
}

function hasValidSubLayouts(value: unknown): boolean {
  return value === undefined
    || (isRecord(value) && Object.values(value).every(isFlexLayoutSubLayout));
}

/**
 * FlexLayout's parser deliberately normalises malformed documents. Define the
 * persisted contract positively before handing data to Model.fromJson so a
 * generated empty model can never autosave over truncated evidence.
 */
function hasValidFlexLayoutSchema(layout: Record<string, unknown>): boolean {
  return (layout.global === undefined || isRecord(layout.global))
    && (layout.borders === undefined
      || (Array.isArray(layout.borders) && layout.borders.every(isFlexLayoutBorder)))
    && hasValidSubLayouts(layout.subLayouts)
    && hasValidSubLayouts(layout.popouts)
    && isFlexLayoutRow(layout.layout);
}

/** Dockview family presence (shape markers only). */
function hasDockviewFamilyMarkers(layout: Record<string, unknown>): boolean {
  return isRecord(layout.grid) && isRecord(layout.panels);
}

/**
 * FlexLayout / current-format family presence markers.
 * Presence ≠ validity. Used for exclusive-family checks.
 * Aliases: subLayouts (current) XOR popouts (deprecated) — coexistence handled separately.
 */
function hasFlexFamilyMarkers(layout: Record<string, unknown>): boolean {
  return (
    layout.layout !== undefined
    || layout.global !== undefined
    || layout.borders !== undefined
    || layout.subLayouts !== undefined
    || layout.popouts !== undefined
  );
}

function hasSetupMarker(layout: Record<string, unknown>): boolean {
  return layout.__pendingPreset !== undefined;
}

export function classifySerializedLayout(
  layout: Record<string, unknown> | undefined,
): SerializedLayoutKind {
  if (layout === undefined || Object.keys(layout).length === 0) return "empty";

  const keys = Object.keys(layout);
  if (
    keys.length === 1
    && keys[0] === "__pendingPreset"
    && typeof layout.__pendingPreset === "string"
    && (layout.__pendingPreset as string).length > 0
  ) {
    return "setup";
  }

  // ALIAS COLLISION (before any family accept)
  if (layout.subLayouts !== undefined && layout.popouts !== undefined) return "corrupt";

  // FAMILY FLAGS (presence)
  const dock = hasDockviewFamilyMarkers(layout);
  const flex = hasFlexFamilyMarkers(layout);
  const setup = hasSetupMarker(layout);

  // MIXED-FAMILY REJECTION (global, not a three-literal denylist)
  const familyCount = [dock, flex, setup].filter(Boolean).length;
  if (familyCount > 1) return "corrupt";

  // PURE DOCKVIEW
  if (dock && !flex && !setup) return "dockview";

  // PURE FLEX / CURRENT
  if (flex && !dock && !setup) {
    if (!hasValidFlexLayoutSchema(layout)) return "corrupt";
    try {
      Model.fromJson(layout as unknown as IJsonModel);
      return "flexlayout";
    } catch {
      return "corrupt";
    }
  }

  // SETUP already handled above; if setup marker but not pure → corrupt (extra keys)
  if (setup) return "corrupt";

  return "corrupt";
}

const storeImpl: StateCreator<LayoutStore, [["zustand/persist", unknown]]> = (set, get) => ({
  tabs: [{ id: defaultTabId, name: "Workspace" }],
  activeTabId: defaultTabId,
  workspaceApi: null,
  widgetPickerOpen: false,
  presetPickerOpen: false,
  addTab: (name) => {
    const id = generateId();
    const tabName = name || `Layout ${get().tabs.length + 1}`;
    set((state) => ({
      tabs: [...state.tabs, { id, name: tabName }],
      activeTabId: id,
    }));
  },
  removeTab: (id) => {
    set((state) => {
      const remaining = state.tabs.filter((t) => t.id !== id);
      if (remaining.length === 0) return state;
      const newActive =
        state.activeTabId === id ? remaining[0].id : state.activeTabId;
      return { tabs: remaining, activeTabId: newActive };
    });
  },
  setActiveTab: (id) => set({ activeTabId: id }),
  renameTab: (id, name) => {
    set((state) => ({
      tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
    }));
  },
  saveTabLayout: (id, layout) => {
    set((state) => ({
      tabs: state.tabs.map((t) =>
        t.id === id ? { ...t, serializedLayout: layout } : t
      ),
    }));
  },
  getTabLayout: (id) => {
    return get().tabs.find((t) => t.id === id)?.serializedLayout;
  },
  setWorkspaceApi: (api) => set({ workspaceApi: api }),
  setWidgetPickerOpen: (open) => set({ widgetPickerOpen: open }),
  setPresetPickerOpen: (open) => set({ presetPickerOpen: open }),
  applyPreset: (presetId) => {
    const api = get().workspaceApi;
    if (!api) return;
    applyPresetImpl(api, presetId);
  },
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:layouts",
  partialize: (state) => ({
    tabs: state.tabs,
    activeTabId: state.activeTabId,
  }) as LayoutStore,
});

export const useLayoutStore = import.meta.env.DEV
  ? create<LayoutStore>()(devtools(persistedStore, { name: "layout" }))
  : create<LayoutStore>()(persistedStore);
