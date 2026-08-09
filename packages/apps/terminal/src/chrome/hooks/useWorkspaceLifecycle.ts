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
 *     id: string;         // matches layoutStore tab id
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
import { safeParse } from "@/lib/safeParse";
import type { WorkspacePreset } from "@/layout/workspacePresets";
import { classifySerializedLayout } from "@/stores/layoutStore";
import { useLayoutStore } from "@/stores/layoutStore";

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

// ---------------------------------------------------------------------------
// Raw storage helpers (exported for testing)
// ---------------------------------------------------------------------------

export function readWorkspaceStore(): WorkspaceStore {
  return safeParse(localStorage.getItem(STORAGE_KEY), workspaceStoreSchema) ?? {};
}

export function writeWorkspaceStore(store: WorkspaceStore): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // localStorage may be unavailable (private browsing, storage quota)
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
// generateWorkspaceId — stable collision-resistant id
// ---------------------------------------------------------------------------

function generateWorkspaceId(): string {
  return `ws_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

interface UseWorkspaceLifecycleReturn {
  /**
   * Clone the current workspace: validates persisted SOT first, rejects corrupt,
   * then creates a new layoutStore tab with a "(Copy)" suffix and persists its metadata.
   *
   * Must read persisted layout from layoutStore, classify, and fail-closed on corrupt
   * before any metadata write or addTab.
   */
  cloneWorkspace: (
    sourceTabId: string,
    sourceName: string,
    addTab?: (name: string) => void
  ) => { ok: boolean; error?: string };

  /**
   * Create a new workspace tab from a preset template.
   *
   * @param preset     The workspace preset to apply.
   * @param addTab     layoutStore.addTab function.
   * @param applyPreset  layoutStore.applyPreset function.
   */
  newFromTemplate: (
    preset: WorkspacePreset,
    addTab: (name: string) => void,
    applyPreset: (presetId: string) => void
  ) => void;
}

export function useWorkspaceLifecycle(): UseWorkspaceLifecycleReturn {
  const cloneWorkspace = useCallback(
    (
      sourceTabId: string,
      sourceName: string,
      addTab?: (name: string) => void
    ): { ok: boolean; error?: string } => {
      // 1. Resolve sourceTabId (already param)
      // 2. Read persisted layout from store (SOT)
      const persisted = useLayoutStore.getState().getTabLayout(sourceTabId);
      // 3. Classify
      const kind = classifySerializedLayout(persisted);

      if (kind === "corrupt") {
        return {
          ok: false,
          error: `Workspace "${sourceName}" layout is corrupted and has been quarantined.`,
        };
      }

      // For empty persisted, the live fallback is not yet supported in minimal store (no workspaceApiTabId)
      // Use persisted only for now per plan step 6 restriction
      const finalKind = classifySerializedLayout(persisted);
      if (finalKind === "corrupt") {
        return {
          ok: false,
          error: `Workspace "${sourceName}" layout is corrupted and has been quarantined.`,
        };
      }

      // Only then proceed with mutation
      const newName = `${sourceName} (Copy)`;
      const newId = generateWorkspaceId();
      const sourceMeta = getWorkspaceMeta(sourceTabId);
      const now = new Date().toISOString();

      upsertWorkspaceMeta({
        id: newId,
        name: newName,
        createdAt: now,
        updatedAt: now,
        sourcePresetId: sourceMeta?.sourcePresetId,
      });

      if (addTab) addTab(newName);

      return { ok: true };
    },
    []
  );

  const newFromTemplate = useCallback(
    (
      preset: WorkspacePreset,
      addTab: (name: string) => void,
      applyPreset: (presetId: string) => void
    ) => {
      const newId = generateWorkspaceId();
      const now = new Date().toISOString();

      upsertWorkspaceMeta({
        id: newId,
        name: preset.name,
        createdAt: now,
        updatedAt: now,
        sourcePresetId: preset.id,
      });

      // Add the tab first, then apply the preset (which clears and rebuilds canvas)
      addTab(preset.name);
      applyPreset(preset.id);
    },
    []
  );

  return { cloneWorkspace, newFromTemplate };
}
