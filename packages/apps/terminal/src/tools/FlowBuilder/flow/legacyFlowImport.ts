/**
 * One-time migration of FlowBuilder drafts from localStorage to the backend.
 *
 * Older builds persisted saved flows only in this browser/WebView under the
 * ``flinttrade_flowbuilder_v2`` key. On mount the tool imports any such
 * drafts into the backend flow store and removes the localStorage key ONLY
 * after every draft imported successfully — a partial failure keeps the key
 * so the next mount retries safely.
 *
 * Retries never overwrite: a flow id already present on the backend is
 * skipped (and counted as migrated), so a retry after a partial failure —
 * or a second silo (desktop WebView vs browser profile) importing weeks
 * later — cannot clobber edits the user made to the imported copy.
 */

import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { listFlows, putFlow } from "@/services/ftApi.flows";
import type { SavedWorkflow } from "@/stores/flowStore";

export const LEGACY_FLOWS_KEY = "flinttrade_flowbuilder_v2";

// Minimal schema — nodes/edges are complex React Flow types; the wrapper
// shape is validated and the graph payload passed through verbatim (the
// backend re-validates the graph on PUT).
const legacyStoreSchema = z.object({
  flows: z.array(
    z
      .object({
        id: z.string(),
        name: z.string(),
        nodes: z.array(z.unknown()),
        edges: z.array(z.unknown()),
        updatedAt: z.string(),
      })
      .passthrough(),
  ),
}) as z.ZodType<{ flows: SavedWorkflow[] }>;

/**
 * Import legacy localStorage drafts into the backend flow store.
 *
 * @returns The number of drafts freshly imported (0 when there was nothing
 *          to migrate or every draft already existed on the backend). Drafts
 *          whose id is already on the backend are skipped — never re-PUT —
 *          and count as migrated for key-removal purposes. The localStorage
 *          key is removed only when every remaining PUT succeeded; on any
 *          failure (including the backend list call) it is kept for a retry
 *          on the next mount.
 */
export async function importLegacyFlows(): Promise<number> {
  const raw = localStorage.getItem(LEGACY_FLOWS_KEY);
  if (!raw) return 0;

  const parsed = safeParse(raw, legacyStoreSchema);
  if (!parsed) {
    // Corrupt/unrecognised payload — leave the key in place rather than
    // silently discarding what may be the only copy of the user's drafts.
    return 0;
  }

  if (parsed.flows.length === 0) {
    localStorage.removeItem(LEGACY_FLOWS_KEY);
    return 0;
  }

  // No-overwrite guard: an id already on the backend means a previous
  // attempt (possibly from another browser/WebView silo) imported it, and
  // the user may have edited that copy since — re-PUTting the stale legacy
  // draft would silently destroy those edits. If this list call fails the
  // whole import rejects and the key survives for the next mount's retry.
  const existingIds = new Set((await listFlows()).map((summary) => summary.id));
  const pending = parsed.flows.filter((flow) => !existingIds.has(flow.id));

  const results = await Promise.allSettled(pending.map((flow) => putFlow(flow)));
  const succeeded = results.filter((r) => r.status === "fulfilled").length;
  if (succeeded === results.length) {
    localStorage.removeItem(LEGACY_FLOWS_KEY);
  }
  return succeeded;
}
