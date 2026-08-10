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
import { classifySerializedLayout, WorkspaceStorageError } from "@/stores/layoutStore";
import type { WorkspaceCreationTransaction } from "@/stores/layoutStore";

export { WorkspaceStorageError };

// ---------------------------------------------------------------------------
// Storage schema
// ---------------------------------------------------------------------------

export interface WorkspaceMeta {
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  sourcePresetId?: string;
  creationTransactionId?: string;
}

type WorkspaceStore = Record<string, WorkspaceMeta>;

const workspaceMetaSchema = z.object({
  id: z.string(),
  name: z.string(),
  createdAt: z.string(),
  updatedAt: z.string(),
  sourcePresetId: z.string().optional(),
  creationTransactionId: z.string().optional(),
}) satisfies z.ZodType<WorkspaceMeta>;

const workspaceStoreSchema = z.record(z.string(), workspaceMetaSchema) satisfies z.ZodType<WorkspaceStore>;

const STORAGE_KEY = "flinttrade:workspaces";

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
  throw new WorkspaceStorageError(
    "Workspace metadata is corrupted and could not be read.",
  );
}

export function writeWorkspaceStore(store: WorkspaceStore): void {
  // Surface failures honestly (quota, private mode, etc) instead of swallowing.
  // Callers (or global error boundary) can then notify the user.
  localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
}

export interface WorkspaceReconciliation {
  metadataLessTabIds: string[];
}

interface ReconciliationTab {
  id: string;
  name: string;
  creationTransaction?: {
    id: string;
    state: "pending" | "committed";
  };
}

export function reconcileWorkspaceStore(
  tabs: ReadonlyArray<ReconciliationTab>
): WorkspaceReconciliation {
  const current = readWorkspaceStore();
  const currentEntries = Object.entries(current);
  const canonicalIds = new Set(tabs.map((tab) => tab.id));
  const claimedLegacyIds = new Set<string>();
  const reconciled: WorkspaceStore = {};

  for (const tab of tabs) {
    const canonical = current[tab.id];
    const transaction = tab.creationTransaction;

    // Only an explicit pending creation marker is safe to treat as a rollback
    // ghost. Legacy/unmarked `ws_` IDs may be healthy and must never be deleted
    // by a naming heuristic.
    if (transaction?.state === "pending") continue;

    if (transaction?.state === "committed") {
      if (
        canonical?.creationTransactionId !== undefined
        && canonical.creationTransactionId !== transaction.id
      ) {
        throw new WorkspaceStorageError(
          `Workspace "${tab.name}" transaction metadata does not match its committed layout.`,
        );
      }
      const now = new Date().toISOString();
      reconciled[tab.id] = canonical
        ? {
            ...canonical,
            id: tab.id,
            name: tab.name,
            creationTransactionId: transaction.id,
          }
        : {
            id: tab.id,
            name: tab.name,
            createdAt: now,
            updatedAt: now,
            creationTransactionId: transaction.id,
          };
      continue;
    }

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

  return {
    metadataLessTabIds: tabs
      .filter((tab) =>
        tab.creationTransaction?.state === "pending"
        && reconciled[tab.id] === undefined
      )
      .map((tab) => tab.id),
  };
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

function creationTransaction(id: string): WorkspaceCreationTransaction {
  return { id: `txn_${id}`, state: "pending" };
}

function cloneJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(cloneJsonValue);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([key, entry]) => [key, cloneJsonValue(entry)]),
  );
}

/**
 * Clone a FlexLayout document while giving every layout node a new identity.
 * Panel-scoped settings, FDC3 membership and caches use node IDs as keys, so a
 * verbatim layout clone would couple the source and copy. Config values remain
 * unchanged; only row/tabset/tab/border identities are reminted.
 */
export function cloneFlexLayoutWithFreshIds(
  sourceLayout: Record<string, unknown>,
  workspaceId: string,
): Record<string, unknown> {
  let sequence = 0;
  const remintNode = (value: unknown): unknown => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return cloneJsonValue(value);
    const source = value as Record<string, unknown>;
    const clone = cloneJsonValue(source) as Record<string, unknown>;
    if (["row", "tabset", "tab", "border"].includes(String(source.type))) {
      sequence += 1;
      clone.id = `clone-${workspaceId}-${sequence}`;
    }
    if (Array.isArray(source.children)) clone.children = source.children.map(remintNode);
    return clone;
  };

  const cloned = cloneJsonValue(sourceLayout) as Record<string, unknown>;
  if (sourceLayout.layout !== undefined) cloned.layout = remintNode(sourceLayout.layout);
  if (Array.isArray(sourceLayout.borders)) cloned.borders = sourceLayout.borders.map(remintNode);
  for (const key of ["subLayouts", "popouts"] as const) {
    const sourceSubLayouts = sourceLayout[key];
    if (!sourceSubLayouts || typeof sourceSubLayouts !== "object" || Array.isArray(sourceSubLayouts)) continue;
    cloned[key] = Object.fromEntries(Object.entries(sourceSubLayouts).map(([id, subLayout]) => {
      const clonedSubLayout = cloneJsonValue(subLayout) as Record<string, unknown>;
      if (subLayout && typeof subLayout === "object" && !Array.isArray(subLayout)) {
        const sourceSubLayout = subLayout as Record<string, unknown>;
        if (sourceSubLayout.layout !== undefined) clonedSubLayout.layout = remintNode(sourceSubLayout.layout);
      }
      return [id, clonedSubLayout];
    }));
  }
  return cloned;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

type AddWorkspaceTab = (
  name: string,
  initialLayout?: Record<string, unknown>,
  providedId?: string,
  creationTransaction?: WorkspaceCreationTransaction,
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
    sourceLayout?: Record<string, unknown>,
    commitTabCreation?: (id: string, transactionId: string) => void,
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
    removeTab: (id: string) => void,
    commitTabCreation?: (id: string, transactionId: string) => void,
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

function persistenceFailure(
  error: unknown,
  rollbackError?: unknown,
): WorkspaceLifecycleResult {
  const base = error instanceof WorkspaceStorageError
    ? error.message
    : `Workspace could not be saved: ${error instanceof Error ? error.message : "unknown storage error"}`;
  if (rollbackError === undefined) return { ok: false, error: base };
  const rollbackDetail = rollbackError instanceof Error
    ? rollbackError.message
    : "unknown storage error";
  return {
    ok: false,
    error: `${base}; durable rollback failed: ${rollbackDetail}`,
  };
}

function rollbackTab(removeTab: (id: string) => void, id: string): unknown | undefined {
  try {
    removeTab(id);
    return undefined;
  } catch (error) {
    // Zustand updates memory before its persistence adapter writes, but the
    // durable snapshot may still contain the temporary tab.
    return error;
  }
}

export function useWorkspaceLifecycle(): UseWorkspaceLifecycleReturn {
  const cloneWorkspace = useCallback(
    (
      sourceTabId: string,
      sourceName: string,
      addTab: AddWorkspaceTab,
      removeTab: (id: string) => void,
      sourceLayout?: Record<string, unknown>,
      commitTabCreation?: (id: string, transactionId: string) => void,
    ): WorkspaceLifecycleResult => {
      const newName = `${sourceName} (Copy)`;
      const newId = generateWorkspaceId();
      const transaction = creationTransaction(newId);
      let tabMayExist = false;
      try {
        const sourceMeta = getWorkspaceMeta(sourceTabId);
        const now = new Date().toISOString();

        // Create the primary layout first. If supplementary metadata cannot be
        // persisted, remove the tab again so the two stores cannot diverge.
        // FlexLayout IDs are authority for panel-scoped state; remint them so
        // source and clone cannot share chart settings, channels or caches.
        if (sourceLayout !== undefined && classifySerializedLayout(sourceLayout) === "corrupt") {
          throw new WorkspaceStorageError(
            `Workspace "${sourceName}" layout is corrupted and has been quarantined.`,
          );
        }
        const clonedLayout = sourceLayout === undefined
          ? undefined
          : cloneFlexLayoutWithFreshIds(sourceLayout, newId);
        tabMayExist = true;
        addTab(newName, clonedLayout, newId, transaction);
        try {
          upsertWorkspaceMeta({
            id: newId,
            name: newName,
            createdAt: now,
            updatedAt: now,
            sourcePresetId: sourceMeta?.sourcePresetId,
            creationTransactionId: transaction.id,
          });
          commitTabCreation?.(newId, transaction.id);
        } catch (error) {
          return persistenceFailure(error, rollbackTab(removeTab, newId));
        }
        return { ok: true, id: newId };
      } catch (error) {
        const rollbackError = tabMayExist ? rollbackTab(removeTab, newId) : undefined;
        return persistenceFailure(error, rollbackError);
      }
    },
    []
  );

  const newFromTemplate = useCallback(
    (
      preset: WorkspacePreset,
      addTab: AddWorkspaceTab,
      removeTab: (id: string) => void,
      commitTabCreation?: (id: string, transactionId: string) => void,
    ): WorkspaceLifecycleResult => {
      const newId = generateWorkspaceId();
      const transaction = creationTransaction(newId);
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
          transaction,
        );
        try {
          upsertWorkspaceMeta({
            id: newId,
            name: preset.name,
            createdAt: now,
            updatedAt: now,
            sourcePresetId: preset.id,
            creationTransactionId: transaction.id,
          });
          commitTabCreation?.(newId, transaction.id);
        } catch (error) {
          return persistenceFailure(error, rollbackTab(removeTab, newId));
        }
        return { ok: true, id: newId };
      } catch (error) {
        const rollbackError = tabMayExist ? rollbackTab(removeTab, newId) : undefined;
        return persistenceFailure(error, rollbackError);
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
