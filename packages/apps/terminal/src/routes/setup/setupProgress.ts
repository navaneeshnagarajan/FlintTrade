import { REQUIRED_SETUP_STEP_LABELS } from "@/routes/setupRouting";

/**
 * Required Setup steps.
 *
 * When the credential vault is already open on this machine, that step is
 * not required. The progress line uses the same indexes as "Step N of M".
 */
export interface SetupProgressCounts {
  stepNumber: number;
  total: number;
  completed: number;
  remaining: number;
  label: string;
  /** Index into the visible step list, for the step indicator. */
  displayIndex: number;
}

const FULL_LOGICAL_STEPS = [0, 1, 2] as const;
const VAULT_ALREADY_OPEN_STEPS = [0, 2] as const;

function logicalSteps(vaultAlreadyOpen: boolean): readonly number[] {
  return vaultAlreadyOpen ? VAULT_ALREADY_OPEN_STEPS : FULL_LOGICAL_STEPS;
}

export function setupProgressCounts(
  logicalStep: number,
  vaultAlreadyOpen: boolean,
): SetupProgressCounts {
  const steps = logicalSteps(vaultAlreadyOpen);
  const found = steps.indexOf(logicalStep);
  const displayIndex = found >= 0 ? found : 0;
  const total = vaultAlreadyOpen ? 2 : REQUIRED_SETUP_STEP_LABELS.length;
  const labels = vaultAlreadyOpen
    ? [REQUIRED_SETUP_STEP_LABELS[0], REQUIRED_SETUP_STEP_LABELS[2]]
    : REQUIRED_SETUP_STEP_LABELS;
  const completed = displayIndex;
  const remaining = total - completed;
  return {
    stepNumber: displayIndex + 1,
    total,
    completed,
    remaining,
    label: labels[displayIndex] ?? labels[0],
    displayIndex,
  };
}

/** Title line: "Step N of M - <label>". */
export function setupStepTitle(logicalStep: number, vaultAlreadyOpen: boolean): string {
  const counts = setupProgressCounts(logicalStep, vaultAlreadyOpen);
  return `Step ${counts.stepNumber} of ${counts.total} - ${counts.label}`;
}

/**
 * Detail line under the title.
 *
 * Completed steps are those before the current one. Remaining includes the
 * current step, so Step 2 of 3 is "1 of 3 completed - 2 remaining".
 */
export function setupStepDetail(logicalStep: number, vaultAlreadyOpen: boolean): string {
  const counts = setupProgressCounts(logicalStep, vaultAlreadyOpen);
  if (counts.remaining === 1) {
    return `${counts.completed} of ${counts.total} completed - last step`;
  }
  return `${counts.completed} of ${counts.total} completed - ${counts.remaining} remaining`;
}
