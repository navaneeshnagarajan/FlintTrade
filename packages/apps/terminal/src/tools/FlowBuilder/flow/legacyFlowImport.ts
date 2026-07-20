/**
 * One-time migration of FlowBuilder drafts from localStorage to the backend.
 *
 * Older builds persisted saved flows only in this browser/WebView under the
 * ``flinttrade_flowbuilder_v2`` key. On mount the tool imports any such
 * drafts into the backend flow store (``PUT`` is an upsert, so re-running is
 * idempotent) and removes the localStorage key ONLY after every draft
 * imported successfully — a partial failure keeps the key so the next mount
 * retries safely.
 */

import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { putFlow } from "@/services/ftApi.flows";
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
 * @returns The number of drafts successfully imported (0 when there was
 *          nothing to migrate). The localStorage key is removed only when
 *          every PUT succeeded; on partial failure it is kept for a retry on
 *          the next mount (backend upsert semantics make retries safe).
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

  const results = await Promise.allSettled(parsed.flows.map((flow) => putFlow(flow)));
  const succeeded = results.filter((r) => r.status === "fulfilled").length;
  if (succeeded === results.length) {
    localStorage.removeItem(LEGACY_FLOWS_KEY);
  }
  return succeeded;
}
