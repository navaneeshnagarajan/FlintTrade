import { useLocation, useSearchParams } from "react-router";

import SetupAccountRoute from "./SetupAccountRoute";
import { SetupBackendGate } from "./SetupBackendGate";
import {
  optionalSetupPanel,
  SETUP_STEP_SLUGS,
  type OptionalSetupPanel,
} from "./setupRouting";

function parseStep(value: string | null): number | undefined {
  if (!value) return undefined;
  const slug = value === "mode" ? "practice" : value;
  const slugIndex = SETUP_STEP_SLUGS.indexOf(slug as (typeof SETUP_STEP_SLUGS)[number]);
  if (slugIndex >= 0) return slugIndex;
  if (!/^\d$/.test(value)) return undefined;
  const index = Number(value);
  return index >= 0 && index < SETUP_STEP_SLUGS.length ? index : undefined;
}

export function parseCanonicalSetupIntent(
  searchParams: URLSearchParams,
  hash: string,
): { requestedStep?: number; requestedOptional?: OptionalSetupPanel } {
  const hashValue = hash.startsWith("#") ? hash.slice(1) : hash;
  const requestedOptional = optionalSetupPanel(searchParams.get("step"))
    ?? optionalSetupPanel(hashValue);
  if (requestedOptional) return { requestedOptional };
  const requestedStep = parseStep(searchParams.get("step")) ?? parseStep(hashValue);
  return requestedStep !== undefined ? { requestedStep } : {};
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
