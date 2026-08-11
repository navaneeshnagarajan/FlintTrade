import { useLocation, useSearchParams } from "react-router";

import type { AppMode } from "@/stores/modeStore";
import SetupAccountRoute from "./SetupAccountRoute";
import { SetupBackendGate } from "./SetupBackendGate";
import { SETUP_STEP_SLUGS } from "./setupRouting";

const APP_MODES: readonly AppMode[] = ["explore", "practice", "live"];

function parseMode(value: string | null): AppMode | undefined {
  return APP_MODES.includes(value as AppMode) ? value as AppMode : undefined;
}

function parseStep(value: string | null): number | undefined {
  if (!value) return undefined;
  const slugIndex = SETUP_STEP_SLUGS.indexOf(value as (typeof SETUP_STEP_SLUGS)[number]);
  if (slugIndex >= 0) return slugIndex;
  if (!/^\d$/.test(value)) return undefined;
  const index = Number(value);
  return index >= 0 && index < SETUP_STEP_SLUGS.length ? index : undefined;
}

export function parseCanonicalSetupIntent(
  searchParams: URLSearchParams,
  hash: string,
): { requestedMode?: AppMode; requestedStep?: number } {
  const requestedMode = parseMode(searchParams.get("mode"));
  const requestedStep = parseStep(searchParams.get("step"))
    ?? parseStep(hash.startsWith("#") ? hash.slice(1) : hash);
  return {
    ...(requestedMode ? { requestedMode } : {}),
    ...(requestedStep !== undefined ? { requestedStep } : {}),
  };
}

/** The only mounted setup wizard. Legacy /setup-account redirects here. */
export default function CanonicalSetupRoute() {
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const intent = parseCanonicalSetupIntent(searchParams, location.hash);

  return (
    <SetupBackendGate>
      <SetupAccountRoute {...intent} />
    </SetupBackendGate>
  );
}
