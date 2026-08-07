/**
 * useWorkspaceLifecycle.ts
 *
 * Hook that provides workspace CRUD operations backed by localStorage.
 *
 * Storage key: `flinttrade:workspaces`
 *
 * Schema:
 * {
 *   [tabId: string]: {
 *     id: string;         // matches layoutStore tab id  (UNIFIED canonical ID)
 *     name: string;
 *     createdAt: string;  // ISO 8601
 *     updatedAt: string;  // ISO 8601
 *     sourcePresetId?: string;  // set when created from a preset template
 *   }
 * }
 *
 * The layoutStore `tabs` array is the canonical source for what workspaces
 * exist and their names. This store holds supplementary metadata (timestamps,
 * source preset) and provides the CRUD convenience operations.
 */

import { useCallback } from "react";
import { z } from "zod";
import type { WorkspacePreset } from "@/layout/workspacePresets";

// ---------------------------------------------------------------------------
// Storage schema
// ---------------------------------------------------------------------------

export interface WorkspaceMeta {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  sourcePresetId?: string;
}

type WorkspaceStore = Record<string, WorkspaceMeta>;

const workspaceMetaSchema = z.object({
  id: z.string(),
  name: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  sourcePresetId: z.string().optional(),
}) satisfies z.ZodType<WorkspaceMeta>;

const workspaceStoreSchema = z.record(z.string(), workspaceMetaSchema) satisfies z.ZodType<WorkspaceStore>;

const STORAGE_KEY = "flinttrade:workspaces";

export class WorkspaceStorageError extends Error {
  constructor(message = "Workspace metadata is corrupted and could not be read.") {
    super(message);
    this.name = "WorkspaceStorageError";
  }
}

// ---------------------------------------------------------------------------
// Raw storage helpers (exported for testing)
// ---------------------------------------------------------------------------

export function readWorkspaceStore(): WorkspaceStore {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return {};

  try {
    const parsed: unknown = JSON.parse(raw);
    const result = workspaceStoreSchema.safeParse(parsed);
    if (result.success) return result.data;
  } catch {
    // The common corruption error below gives callers one stable recovery path.
  }
  throw new WorkspaceStorageError();
}

export function writeWorkspaceStore(store: WorkspaceStore): void {
  // Surface failures honestly (quota, private mode, etc) instead of swallowing.
  // Callers (or global error boundary) can then notify the user.
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export function reconcileWorkspaceStore(
  tabs: ReadonlyArray<{ id: string; name: string }>
): void {
  const current = readWorkspaceStore();
  const currentEntries = Object.entries(current);
  const canonicalIds = new Set(tabs.map((tab) => tab.id));
  const claimedLegacyIds = new Set<string>();
  const reconciled: WorkspaceStore = {};

  for (const tab of tabs) {
    const canonical = current[tab.id];
    if (canonical) {
      reconciled[tab.id] = { ...canonical, id: tab.id, name: tab.name };
      continue;
    }

    const candidates = currentEntries.filter(([legacyId, metadata]) =>
      !canonicalIds.has(legacyId)
      && !claimedLegacyIds.has(legacyId)
      && metadata.name === tab.name
    );
    if (candidates.length === 1) {
      const matchingTabs = tabs.filter((candidate) =>
        current[candidate.id] === undefined && candidate.name === tab.name
      );
      if (matchingTabs.length !== 1) continue;
      const [legacyId, metadata] = candidates[0];
      claimedLegacyIds.add(legacyId);
      reconciled[tab.id] = { ...metadata, id: tab.id, name: tab.name };
    }
  }

  for (const [legacyId, metadata] of currentEntries) {
    if (
      !canonicalIds.has(legacyId)
      && !claimedLegacyIds.has(legacyId)
      && tabs.some((tab) => tab.name === metadata.name)
    ) {
      reconciled[legacyId] = metadata;
    }
  }

  if (JSON.stringify(reconciled) !== JSON.stringify(current)) {
    writeWorkspaceStore(reconciled);
  }
}

export function upsertWorkspaceMeta(meta: WorkspaceMeta): void {
  const store = readWorkspaceStore();
  store[meta.id] = { ...meta, updatedAt: new Date().toISOString() };
  writeWorkspaceStore(store);
}

export function deleteWorkspaceMeta(tabId: string): void {
  const store = readWorkspaceStore();
  delete store[tabId];
  writeWorkspaceStore(store);
}

export function getWorkspaceMeta(tabId: string): WorkspaceMeta | undefined {
  return readWorkspaceStore()[tabId];
}

// ---------------------------------------------------------------------------
// generateWorkspaceId — stable collision-resistant id (canonical for workspaces)
// ---------------------------------------------------------------------------

function generateWorkspaceId(): string {
  return `ws_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

type AddWorkspaceTab = (
  name: string,
  initialLayout?: Record<string, unknown>,
  providedId?: string,
) => void;

export type WorkspaceLifecycleResult =
  | { ok: true; id: string }
  | { ok: false; error: string };

interface UseWorkspaceLifecycleReturn {
  /**
   * Clone the current workspace: creates a new layoutStore tab with a
   * "(Copy)" suffix, clones its serializedLayout, and persists metadata
   * using the SAME canonical ID for both metadata and layout tab.
   *
   * @param sourceTabId  The tab id being cloned.
   * @param sourceName   The current name of that tab.
   * @param addTab       layoutStore.addTab function (now supports layout + id).
   * @param sourceLayout Optional serialized layout to clone.
   */
  cloneWorkspace: (
    sourceTabId: string,
    sourceName: string,
    addTab: AddWorkspaceTab,
    removeTab: (id: string) => void,
    sourceLayout?: Record<string, unknown>
  ) => WorkspaceLifecycleResult;

  /**
   * Create a new workspace tab from a preset template.
   *
   * @param preset     The workspace preset to apply.
   * @param addTab     layoutStore.addTab function.
   * @param removeTab  layoutStore.removeTab function used to roll back failed persistence.
   */
  newFromTemplate: (
    preset: WorkspacePreset,
    addTab: AddWorkspaceTab,
    removeTab: (id: string) => void
  ) => WorkspaceLifecycleResult;

  renameWorkspace: (
    id: string,
    currentName: string,
    nextName: string,
    renameTab: (id: string, name: string) => void
  ) => WorkspaceLifecycleResult;

  deleteWorkspace: (
    id: string,
    name: string,
    layout: Record<string, unknown> | undefined,
    removeTab: (id: string) => void,
    addTab: AddWorkspaceTab
  ) => WorkspaceLifecycleResult;
}

function persistenceFailure(error: unknown): WorkspaceLifecycleResult {
  if (error instanceof WorkspaceStorageError) {
    return { ok: false, error: error.message };
  }
  const detail = error instanceof Error ? error.message : "unknown storage error";
  return { ok: false, error: `Workspace could not be saved: ${detail}` };
}

function rollbackTab(removeTab: (id: string) => void, id: string): void {
  try {
    removeTab(id);
  } catch {
    // Zustand updates memory before its persistence adapter writes. A failed
    // rollback write can therefore still remove the transient in-memory tab.
  }
}

export function useWorkspaceLifecycle(): UseWorkspaceLifecycleReturn {
  const cloneWorkspace = useCallback(
    (
      sourceTabId: string,
      sourceName: string,
      addTab: AddWorkspaceTab,
      removeTab: (id: string) => void,
      sourceLayout?: Record<string, unknown>
    ): WorkspaceLifecycleResult => {
      const newName = `${sourceName} (Copy)`;
      const newId = generateWorkspaceId();
      let tabMayExist = false;
      try {
        const sourceMeta = getWorkspaceMeta(sourceTabId);
        const now = new Date().toISOString();

        // Create the primary layout first. If supplementary metadata cannot be
        // persisted, remove the tab again so the two stores cannot diverge.
        tabMayExist = true;
        addTab(newName, sourceLayout, newId);
        try {
          upsertWorkspaceMeta({
            id: newId,
            name: newName,
            createdAt: now,
            updatedAt: now,
            sourcePresetId: sourceMeta?.sourcePresetId,
          });
        } catch (error) {
          rollbackTab(removeTab, newId);
          return persistenceFailure(error);
        }
        return { ok: true, id: newId };
      } catch (error) {
        if (tabMayExist) rollbackTab(removeTab, newId);
        return persistenceFailure(error);
      }
    },
    []
  );

  const newFromTemplate = useCallback(
    (
      preset: WorkspacePreset,
      addTab: AddWorkspaceTab,
      removeTab: (id: string) => void
    ): WorkspaceLifecycleResult => {
      const newId = generateWorkspaceId();
      const now = new Date().toISOString();
      let tabMayExist = false;
      try {
        // Validate existing metadata before mutating the primary layout store.
        readWorkspaceStore();
        tabMayExist = true;
        addTab(
          preset.name,
          preset.build() as unknown as Record<string, unknown>,
          newId,
        );
        try {
          upsertWorkspaceMeta({
            id: newId,
            name: preset.name,
            createdAt: now,
            updatedAt: now,
            sourcePresetId: preset.id,
          });
        } catch (error) {
          rollbackTab(removeTab, newId);
          return persistenceFailure(error);
        }
        return { ok: true, id: newId };
      } catch (error) {
        if (tabMayExist) rollbackTab(removeTab, newId);
        return persistenceFailure(error);
      }
    },
    []
  );

  const renameWorkspace = useCallback(
    (
      id: string,
      currentName: string,
      nextName: string,
      renameTab: (id: string, name: string) => void
    ): WorkspaceLifecycleResult => {
      let tabMayBeRenamed = false;
      try {
        const metadata = getWorkspaceMeta(id);
        tabMayBeRenamed = true;
        renameTab(id, nextName);
        if (metadata) {
          upsertWorkspaceMeta({ ...metadata, name: nextName });
        }
        return { ok: true, id };
      } catch (error) {
        if (tabMayBeRenamed) {
          try {
            renameTab(id, currentName);
          } catch {
            // Zustand already restored its in-memory name before persistence failed.
          }
        }
        return persistenceFailure(error);
      }
    },
    []
  );

  const deleteWorkspace = useCallback(
    (
      id: string,
      name: string,
      layout: Record<string, unknown> | undefined,
      removeTab: (id: string) => void,
      addTab: AddWorkspaceTab
    ): WorkspaceLifecycleResult => {
      let tabMayBeRemoved = false;
      try {
        const metadata = getWorkspaceMeta(id);
        tabMayBeRemoved = true;
        removeTab(id);
        if (metadata) deleteWorkspaceMeta(id);
        return { ok: true, id };
      } catch (error) {
        if (tabMayBeRemoved) {
          try {
            addTab(name, layout, id);
          } catch {
            // Zustand already restored its in-memory tab before persistence failed.
          }
        }
        return persistenceFailure(error);
      }
    },
    []
  );

  return { cloneWorkspace, newFromTemplate, renameWorkspace, deleteWorkspace };
}
