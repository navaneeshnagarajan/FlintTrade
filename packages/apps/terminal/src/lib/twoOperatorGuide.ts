/** Docs target for the paused two-operator update. */

export const TWO_OPERATOR_GUIDE_PATH = "USER_GUIDE.md";
export const TWO_OPERATOR_GUIDE_ANCHOR = "two-operator-accounts";

export const TWO_OPERATOR_MIGRATION_BLOCKED = "two_operators";

export function twoOperatorGuideState(): {
  selectedDocPath: string;
  docAnchor: string;
} {
  return {
    selectedDocPath: TWO_OPERATOR_GUIDE_PATH,
    docAnchor: TWO_OPERATOR_GUIDE_ANCHOR,
  };
}

export function isTwoOperatorGuideLocation(location: {
  pathname: string;
  state: unknown;
}): boolean {
  if (location.pathname !== "/learn") return false;
  if (!location.state || typeof location.state !== "object") return false;
  const state = location.state as { selectedDocPath?: unknown; docAnchor?: unknown };
  return (
    state.selectedDocPath === TWO_OPERATOR_GUIDE_PATH
    && state.docAnchor === TWO_OPERATOR_GUIDE_ANCHOR
  );
}

/** Same `flinttrade:openDoc` event the shell already uses for guide links. */
export function dispatchTwoOperatorGuide(): void {
  window.dispatchEvent(
    new CustomEvent("flinttrade:openDoc", {
      detail: {
        path: TWO_OPERATOR_GUIDE_PATH,
        anchor: TWO_OPERATOR_GUIDE_ANCHOR,
      },
    }),
  );
}

export function migrationBlockedFromStatus(payload: unknown): boolean {
  if (!payload || typeof payload !== "object") return false;
  const data = (payload as { data?: { migration_blocked?: unknown } }).data;
  return data?.migration_blocked === TWO_OPERATOR_MIGRATION_BLOCKED;
}
