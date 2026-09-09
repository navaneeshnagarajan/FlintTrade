/**
 * advisorApi.ts
 *
 * Shared base-URL resolver for the components that talk to the FlintTrade AI
 * advisor backend (/ft-api/api/v1/advisor/*).
 *
 * Consumers: AITutorPill and AIAdvisorWidget resolve the base here, then send
 * through the shared ``advisorChat`` client (probe → stream → fallback).
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
