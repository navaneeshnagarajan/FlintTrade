import { Navigate, useLocation } from "react-router";

import type { AppMode } from "@/stores/modeStore";

export const CANONICAL_SETUP_PATH = "/setup";
export const LEGACY_SETUP_ACCOUNT_PATH = "/setup-account";

export const SETUP_ROUTE_POLICY = {
  setup: { kind: "canonical", path: CANONICAL_SETUP_PATH },
  setupAccount: {
    kind: "alias",
    path: LEGACY_SETUP_ACCOUNT_PATH,
    target: CANONICAL_SETUP_PATH,
  },
} as const;

export const SETUP_STEP_SLUGS = [
  "account",
  "two-factor",
  "persona",
  "connection",
  "trading",
  "risk",
  "mode",
] as const;

export type SetupStepSlug = (typeof SETUP_STEP_SLUGS)[number];

const VALID_MODES = new Set<AppMode>(["explore", "practice", "live"]);
const VALID_STEPS = new Set<string>([
  ...SETUP_STEP_SLUGS,
  ...SETUP_STEP_SLUGS.map((_, index) => String(index)),
]);
const VALID_HASHES = new Set(SETUP_STEP_SLUGS.map((step) => `#${step}`));

export function buildSetupAliasTarget(search: string, hash: string): string {
  const source = new URLSearchParams(search);
  const target = new URLSearchParams();
  const mode = source.get("mode");
  const step = source.get("step");

  if (mode && VALID_MODES.has(mode as AppMode)) target.set("mode", mode);
  if (step && VALID_STEPS.has(step)) target.set("step", step);

  const query = target.toString();
  const safeHash = VALID_HASHES.has(hash as `#${SetupStepSlug}`) ? hash : "";
  return `${CANONICAL_SETUP_PATH}${query ? `?${query}` : ""}${safeHash}`;
}

/** Compatibility-only route. All setup UI is owned by /setup. */
export function SetupAccountAlias() {
  const location = useLocation();
  return <Navigate to={buildSetupAliasTarget(location.search, location.hash)} replace />;
}
