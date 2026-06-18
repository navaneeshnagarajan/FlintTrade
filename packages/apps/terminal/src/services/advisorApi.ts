/**
 * advisorApi.ts
 *
 * Shared base-URL resolver for the components that talk to the FlintTrade AI
 * advisor backend (/ft-api/api/v1/advisor/*).
 *
 * Consumers: AITutorPill, AIAdvisorWidget — each owns its request/stream logic
 * (they consume the SSE ReadableStream differently), so only the base-URL
 * helper is shared here. Earlier stand-alone request helpers were removed as
 * dead code: nothing imported them and their body shape ("history") had drifted
 * from the route's contract ("messages"), making them a revival trap.
 *
 * In development the Vite proxy rewrites /ft-api → FlintTrade backend so we use
 * the prefix only in dev. In production the app is co-served with the backend
 * on the same origin so no prefix is needed.
 *
 * This is a thin alias over the canonical {@link getBase} resolver in
 * `ftApi.helpers` so there is a single source of truth for the backend base.
 */

import { getBase } from "./ftApi.helpers";

export function getAdvisorBase(): string {
  return getBase();
}
