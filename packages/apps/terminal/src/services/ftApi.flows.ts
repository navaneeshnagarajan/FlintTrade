/**
 * Saved-flow REST client for the FlintTrade backend.
 *
 * Talks to the workspace-backed flow store exposed under ``/api/v1/flows`` —
 * one JSON document per saved FlowBuilder draft. This replaces the old
 * ``flinttrade_flowbuilder_v2`` localStorage persistence: drafts now live in
 * the operator's FlintTrade workspace and survive browser/WebView storage
 * resets and reinstalls.
 *
 * All calls go through the shared ``/api/v1`` helpers so auth headers and the
 * ``{status, data}`` envelope unwrapping behave exactly like every other
 * FT-API caller.
 */

import { del, get, put } from "./ftApi.helpers";
import type { SavedWorkflow } from "@/stores/flowStore";

// ---------------------------------------------------------------------------
// Types (mirror the backend contract)
// ---------------------------------------------------------------------------

/** One row of ``GET /api/v1/flows`` — a summary, without nodes/edges. */
export interface FlowSummary {
  id: string;
  name: string;
  updatedAt: string;
  node_count: number;
  saved_at: string;
}

/** The full stored document returned by ``GET /api/v1/flows/<id>``. */
export interface StoredWorkflow extends SavedWorkflow {
  saved_at: string;
}

/**
 * Result of ``PUT /api/v1/flows/<id>`` — the saved record plus any
 * non-blocking graph-validation issues the backend reported. The issue shape
 * is owned by the backend's ``validate_flow_graph``; the frontend only counts
 * and logs them, so it is typed opaquely.
 */
export interface PutFlowResult extends StoredWorkflow {
  validation?: unknown[];
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

/** List saved flows (summaries only — fetch a flow by id for its graph). */
export const listFlows = (): Promise<FlowSummary[]> => get<FlowSummary[]>("flows");

/** Fetch one saved flow with its full nodes/edges graph. */
export const getFlow = (id: string): Promise<StoredWorkflow> =>
  get<StoredWorkflow>("flows/" + encodeURIComponent(id));

/**
 * Create or update a saved flow (backend upsert — safe to retry). The id in
 * the body must match the path, which this helper guarantees by deriving the
 * path from ``flow.id``.
 */
export const putFlow = (flow: SavedWorkflow): Promise<PutFlowResult> =>
  put<PutFlowResult>("flows/" + encodeURIComponent(flow.id), flow);

/** Delete a saved flow by id (404 from the backend rejects via FtApiError). */
export const deleteFlow = async (id: string): Promise<void> => {
  await del<unknown>("flows/" + encodeURIComponent(id));
};
