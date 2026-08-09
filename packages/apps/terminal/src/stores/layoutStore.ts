import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { PersistStorage, StorageValue } from "zustand/middleware";
import type { StateCreator } from "zustand";
import { Model } from "flexlayout-react";
import type { IJsonModel } from "flexlayout-react";
import type { WorkspaceApi } from "@/layout/flexLayoutAdapter";
import { applyPreset as applyPresetImpl } from "@/layout/workspacePresets";

export class WorkspaceStorageError extends Error {
  constructor(message = "Workspace storage is corrupted and could not be read.") {
    super(message);
    this.name = "WorkspaceStorageError";
  }
}

export interface WorkspaceCreationTransaction {
  id: string;
  state: "pending" | "committed";
}

interface LayoutTab {
  id: string;
  name: string;
  serializedLayout?: Record<string, unknown>;
  creationTransaction?: WorkspaceCreationTransaction;
}

interface LayoutStore {
  tabs: LayoutTab[];
  activeTabId: string;
  layoutStorageError: WorkspaceStorageError | null;
  layoutStorageQuarantined: boolean;
  workspaceApi: WorkspaceApi | null;
  workspaceApiTabId: string | null;
  widgetPickerOpen: boolean;
  presetPickerOpen: boolean;
  addTab: (
    name?: string,
    initialLayout?: Record<string, unknown>,
    providedId?: string,
    creationTransaction?: WorkspaceCreationTransaction,
  ) => void;
  commitTabCreation: (id: string, transactionId: string) => void;
  removeTab: (id: string) => void;
  setActiveTab: (id: string) => void;
  renameTab: (id: string, name: string) => void;
  saveTabLayout: (id: string, layout: Record<string, unknown>) => void;
  getTabLayout: (id: string) => Record<string, unknown> | undefined;
  setWorkspaceApi: (api: WorkspaceApi | null, tabId?: string) => void;
  setWidgetPickerOpen: (open: boolean) => void;
  setPresetPickerOpen: (open: boolean) => void;
  applyPreset: (presetId: string) => void;
}

type PersistedLayoutState = Pick<LayoutStore, "tabs" | "activeTabId">;

const LAYOUT_STORAGE_KEY = "flinttrade:layouts";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export type SerializedLayoutKind = "empty" | "setup" | "dockview" | "flexlayout" | "corrupt";

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

export function classifySerializedLayout(
  layout: Record<string, unknown> | undefined,
): SerializedLayoutKind {
  if (layout === undefined || Object.keys(layout).length === 0) return "empty";

  const keys = Object.keys(layout);
  if (
    keys.length === 1
    && keys[0] === "__pendingPreset"
    && typeof layout.__pendingPreset === "string"
  ) {
    return "setup";
  }

  // FlexLayout parses `subLayouts || popouts`; reject their coexistence before
  // any legacy-format early return can hide semantically ignored node IDs.
  if (layout.subLayouts !== undefined && layout.popouts !== undefined) return "corrupt";

  if (isRecord(layout.grid) && isRecord(layout.panels)) return "dockview";

  if (!hasValidFlexLayoutSchema(layout)) return "corrupt";
  try {
    Model.fromJson(layout as unknown as IJsonModel);
    return "flexlayout";
  } catch {
    return "corrupt";
  }
}

function corruptLayoutStorageError(): WorkspaceStorageError {
  return new WorkspaceStorageError(
    "Workspace layout storage is corrupted and could not be read.",
  );
}

function parsePersistedLayoutValue(raw: string): StorageValue<PersistedLayoutState> {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw corruptLayoutStorageError();
  }

  if (!isRecord(parsed) || !isRecord(parsed.state)) {
    throw corruptLayoutStorageError();
  }
  const { tabs, activeTabId } = parsed.state;
  if (!Array.isArray(tabs) || typeof activeTabId !== "string") {
    throw corruptLayoutStorageError();
  }
  const validTabs = tabs.every((tab) =>
    isRecord(tab)
    && typeof tab.id === "string"
    && typeof tab.name === "string"
    && (tab.serializedLayout === undefined || isRecord(tab.serializedLayout))
    && (
      tab.creationTransaction === undefined
      || (
        isRecord(tab.creationTransaction)
        && typeof tab.creationTransaction.id === "string"
        && (
          tab.creationTransaction.state === "pending"
          || tab.creationTransaction.state === "committed"
        )
      )
    )
  );
  if (!validTabs || !tabs.some((tab) => (tab as Record<string, unknown>).id === activeTabId)) {
    throw corruptLayoutStorageError();
  }
  if (parsed.version !== undefined && typeof parsed.version !== "number") {
    throw corruptLayoutStorageError();
  }
  return parsed as StorageValue<PersistedLayoutState>;
}

interface InitialLayoutStorageInspection {
  error: WorkspaceStorageError | null;
  quarantined: boolean;
}

function hasQuarantinedTab(value: StorageValue<PersistedLayoutState>): boolean {
  return value.state.tabs.some((tab) =>
    classifySerializedLayout(tab.serializedLayout) === "corrupt"
  );
}

function tabsContainQuarantinedLayout(tabs: LayoutTab[]): boolean {
  return tabs.some((tab) => classifySerializedLayout(tab.serializedLayout) === "corrupt");
}

function inspectInitialLayoutStorage(): InitialLayoutStorageInspection {
  if (typeof window === "undefined") return { error: null, quarantined: false };
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "unknown storage error";
    return {
      error: new WorkspaceStorageError(`Workspace layout storage could not be read: ${detail}`),
      quarantined: false,
    };
  }
  if (raw === null) return { error: null, quarantined: false };
  try {
    const value = parsePersistedLayoutValue(raw);
    return { error: null, quarantined: hasQuarantinedTab(value) };
  } catch (error) {
    return {
      error: error instanceof WorkspaceStorageError ? error : corruptLayoutStorageError(),
      quarantined: false,
    };
  }
}

const initialLayoutStorage = inspectInitialLayoutStorage();
let layoutStorageError = initialLayoutStorage.error;
let layoutStorageQuarantined = initialLayoutStorage.quarantined;
let lastPersistedLayoutCanonical: string | null = null;
let quarantinedLayoutEvidenceRaw: string | null = null;

function canonicalizePersistedLayoutValue(value: StorageValue<PersistedLayoutState>): string {
  return JSON.stringify({
    state: {
      tabs: value.state.tabs,
      activeTabId: value.state.activeTabId,
    },
    ...(value.version === undefined ? {} : { version: value.version }),
  });
}

function quarantineEvidenceKey(raw: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < raw.length; index += 1) {
    hash ^= raw.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${LAYOUT_STORAGE_KEY}:quarantine:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function preserveQuarantineEvidence(): void {
  if (!quarantinedLayoutEvidenceRaw) return;
  const key = quarantineEvidenceKey(quarantinedLayoutEvidenceRaw);
  try {
    const existing = window.localStorage.getItem(key);
    if (existing === quarantinedLayoutEvidenceRaw) return;
    if (existing !== null) {
      throw new WorkspaceStorageError("Workspace quarantine evidence key collision detected.");
    }
    window.localStorage.setItem(key, quarantinedLayoutEvidenceRaw);
  } catch (error) {
    if (error instanceof WorkspaceStorageError) throw error;
    const detail = error instanceof Error ? error.message : "unknown storage error";
    throw new WorkspaceStorageError(`Workspace quarantine evidence could not be saved: ${detail}`);
  }
}

const layoutStorage: PersistStorage<PersistedLayoutState> = {
  getItem: (name) => {
    if (layoutStorageError) return null;
    const raw = window.localStorage.getItem(name);
    if (raw === null) {
      lastPersistedLayoutCanonical = null;
      quarantinedLayoutEvidenceRaw = null;
      return null;
    }
    try {
      const value = parsePersistedLayoutValue(raw);
      layoutStorageQuarantined = hasQuarantinedTab(value);
      quarantinedLayoutEvidenceRaw = layoutStorageQuarantined ? raw : null;
      lastPersistedLayoutCanonical = canonicalizePersistedLayoutValue(value);
      return value;
    } catch (error) {
      layoutStorageError = error instanceof WorkspaceStorageError
        ? error
        : corruptLayoutStorageError();
      return null;
    }
  },
  setItem: (name, value) => {
    // A malformed top-level envelope is opaque evidence and must remain byte-for-byte.
    // Per-tab quarantine is different: healthy siblings may persist while the corrupt
    // serializedLayout value is carried through unchanged.
    if (layoutStorageError) return;
    const canonical = canonicalizePersistedLayoutValue(value);
    if (canonical === lastPersistedLayoutCanonical) return;
    if (layoutStorageQuarantined) preserveQuarantineEvidence();
    window.localStorage.setItem(name, canonical);
    lastPersistedLayoutCanonical = canonical;
    layoutStorageQuarantined = hasQuarantinedTab(value);
  },
  removeItem: (name) => {
    if (layoutStorageError) return;
    window.localStorage.removeItem(name);
    lastPersistedLayoutCanonical = null;
    layoutStorageQuarantined = false;
    quarantinedLayoutEvidenceRaw = null;
  },
};

function assertLayoutStorageHealthy(state: LayoutStore): void {
  if (state.layoutStorageError) throw state.layoutStorageError;
  if (state.layoutStorageQuarantined) preserveQuarantineEvidence();
}

function getCorruptTabLayoutError(tab: LayoutTab): WorkspaceStorageError | null {
  if (classifySerializedLayout(tab.serializedLayout) !== "corrupt") return null;
  return new WorkspaceStorageError(
    `Workspace "${tab.name}" layout is corrupted and has been quarantined.`,
  );
}

function assertTabLayoutReadable(tab: LayoutTab): void {
  const error = getCorruptTabLayoutError(tab);
  if (error) throw error;
}

function generateId(): string {
  return `LAY-${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
}

const defaultTabId = generateId();

const storeImpl: StateCreator<LayoutStore, [["zustand/persist", unknown]]> = (set, get) => ({
  tabs: [{ id: defaultTabId, name: "Workspace" }],
  activeTabId: defaultTabId,
  layoutStorageError,
  layoutStorageQuarantined,
  workspaceApi: null,
  workspaceApiTabId: null,
  widgetPickerOpen: false,
  presetPickerOpen: false,
  addTab: (name, initialLayout, providedId, creationTransaction) => {
    assertLayoutStorageHealthy(get());
    const id = providedId || generateId();
    const tabName = name || `Layout ${get().tabs.length + 1}`;
    const newTab: LayoutTab = {
      id,
      name: tabName,
      ...(creationTransaction ? { creationTransaction: { ...creationTransaction } } : {}),
    };
    if (initialLayout) {
      newTab.serializedLayout = initialLayout;
    }
    assertTabLayoutReadable(newTab);
    set((state) => ({
      tabs: [...state.tabs, newTab],
      activeTabId: id,
    }));
  },
  commitTabCreation: (id, transactionId) => {
    assertLayoutStorageHealthy(get());
    const tab = get().tabs.find((candidate) => candidate.id === id);
    if (!tab || tab.creationTransaction?.id !== transactionId) {
      throw new WorkspaceStorageError(
        `Workspace creation transaction "${transactionId}" could not be committed.`,
      );
    }
    set((state) => ({
      tabs: state.tabs.map((candidate) =>
        candidate.id === id
          ? {
              ...candidate,
              creationTransaction: { id: transactionId, state: "committed" },
            }
          : candidate
      ),
    }));
  },
  removeTab: (id) => {
    assertLayoutStorageHealthy(get());
    set((state) => {
      const remaining = state.tabs.filter((t) => t.id !== id);
      if (remaining.length === 0) return state;
      const newActive =
        state.activeTabId === id ? remaining[0].id : state.activeTabId;
      return {
        tabs: remaining,
        activeTabId: newActive,
        layoutStorageQuarantined: tabsContainQuarantinedLayout(remaining),
      };
    });
  },
  setActiveTab: (id) => {
    assertLayoutStorageHealthy(get());
    const tab = get().tabs.find((candidate) => candidate.id === id);
    if (tab) {
      assertTabLayoutReadable(tab);
      set({ activeTabId: id });
    }
  },
  renameTab: (id, name) => {
    assertLayoutStorageHealthy(get());
    const existing = get().tabs.find((tab) => tab.id === id);
    if (existing) assertTabLayoutReadable(existing);
    set((state) => ({
      tabs: state.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
    }));
  },
  saveTabLayout: (id, layout) => {
    assertLayoutStorageHealthy(get());
    const existing = get().tabs.find((tab) => tab.id === id);
    if (existing) assertTabLayoutReadable(existing);
    if (classifySerializedLayout(layout) === "corrupt") {
      throw new WorkspaceStorageError(
        `Workspace "${existing?.name ?? id}" rejected a corrupted layout update.`,
      );
    }
    set((state) => ({
      tabs: state.tabs.map((t) =>
        t.id === id ? { ...t, serializedLayout: layout } : t
      ),
    }));
  },
  getTabLayout: (id) => {
    return get().tabs.find((t) => t.id === id)?.serializedLayout;
  },
  setWorkspaceApi: (api, tabId) => set({
    workspaceApi: api,
    workspaceApiTabId: api ? (tabId ?? get().activeTabId) : null,
  }),
  setWidgetPickerOpen: (open) => set({ widgetPickerOpen: open }),
  setPresetPickerOpen: (open) => set({ presetPickerOpen: open }),
  applyPreset: (presetId) => {
    assertLayoutStorageHealthy(get());
    const activeTab = get().tabs.find((tab) => tab.id === get().activeTabId);
    if (activeTab) assertTabLayoutReadable(activeTab);
    const api = get().workspaceApi;
    if (!api) return;
    applyPresetImpl(api, presetId);
    // After applying, the model-level change listener TerminalRoute
    // registers in loadModel auto-saves the new layout to the tab that
    // owns the model — no manual save needed, mounted view or not.
  },
});

const persistedStore = persist(storeImpl, {
  name: LAYOUT_STORAGE_KEY,
  storage: layoutStorage,
  partialize: (state): PersistedLayoutState => ({
    tabs: state.tabs,
    activeTabId: state.activeTabId,
  }),
});

export const useLayoutStore = import.meta.env.DEV
  ? create<LayoutStore>()(devtools(persistedStore, { name: "layout" }))
  : create<LayoutStore>()(persistedStore);
