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

/** Required first-run steps. Step N of M counts only these. */
export const SETUP_STEP_SLUGS = [
  "account",
  "vault",
  "practice",
] as const;

export type SetupStepSlug = (typeof SETUP_STEP_SLUGS)[number];

export const REQUIRED_SETUP_STEP_LABELS = [
  "Create operator",
  "Vault",
  "Practice desk",
] as const;

export const REQUIRED_SETUP_STEP_COUNT = REQUIRED_SETUP_STEP_LABELS.length;

/**
 * Optional first-run panels. They are not required steps and do not change
 * the Step N of M fraction. Legacy slugs stay so older links open the panel
 * only after the vault, never as a gate.
 */
export const OPTIONAL_SETUP_SLUGS = {
  "two-factor": "totp",
  totp: "totp",
  connection: "broker",
  broker: "broker",
  llm: "llm",
  monitoring: "monitoring",
} as const;

export type OptionalSetupPanel = (typeof OPTIONAL_SETUP_SLUGS)[keyof typeof OPTIONAL_SETUP_SLUGS];

const VALID_MODES = new Set<AppMode>(["explore", "practice"]);
const LEGACY_STEP_SLUGS: Record<string, SetupStepSlug> = {
  mode: "practice",
};

function canonicalStepSlug(value: string | null): SetupStepSlug | null {
  if (!value) return null;
  if ((SETUP_STEP_SLUGS as readonly string[]).includes(value)) return value as SetupStepSlug;
  return LEGACY_STEP_SLUGS[value] ?? null;
}

export function optionalSetupPanel(value: string | null | undefined): OptionalSetupPanel | undefined {
  if (!value) return undefined;
  const slug = value.startsWith("#") ? value.slice(1) : value;
  if (slug in OPTIONAL_SETUP_SLUGS) {
    return OPTIONAL_SETUP_SLUGS[slug as keyof typeof OPTIONAL_SETUP_SLUGS];
  }
  return undefined;
}

const VALID_STEPS = new Set<string>([
  ...SETUP_STEP_SLUGS,
  ...Object.keys(LEGACY_STEP_SLUGS),
  ...Object.keys(OPTIONAL_SETUP_SLUGS),
  ...SETUP_STEP_SLUGS.map((_, index) => String(index)),
]);

function canonicalHash(hash: string): string {
  if (!hash.startsWith("#")) return "";
  const slug = hash.slice(1);
  const step = canonicalStepSlug(slug);
  if (step) return `#${step}`;
  if (optionalSetupPanel(slug)) return hash;
  return "";
}

export function buildSetupAliasTarget(search: string, hash: string): string {
  const source = new URLSearchParams(search);
  const target = new URLSearchParams();
  const mode = source.get("mode");
  const step = source.get("step");

  if (mode && VALID_MODES.has(mode as AppMode)) target.set("mode", mode);
  if (step && VALID_STEPS.has(step)) {
    const required = canonicalStepSlug(step);
    const optional = optionalSetupPanel(step);
    if (required) target.set("step", required);
    else if (optional) target.set("step", step);
  }

  const query = target.toString();
  const safeHash = canonicalHash(hash);
  return `${CANONICAL_SETUP_PATH}${query ? `?${query}` : ""}${safeHash}`;
}

/** Compatibility-only route. All setup UI is owned by /setup. */
export function SetupAccountAlias() {
  const location = useLocation();
  return <Navigate to={buildSetupAliasTarget(location.search, location.hash)} replace />;
}
