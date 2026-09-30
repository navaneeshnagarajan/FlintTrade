/**
 * Shared restore-marker filter for fills brought back from a Practice backup.
 *
 * Scoring readers import {@link isRestoredFromBackup}. P&L still counts the
 * fill. Laya scores, strategy scores, and the Performance exclusion line do not.
 */

export const RESTORED_FROM_BACKUP = "Restored from backup";

export const RESTORED_FILL_TOOLTIP =
  "Restored from backup. Not sent to a broker or checked by Laya.";

export function isRestoredFromBackup(strategy: string | null | undefined): boolean {
  return strategy === RESTORED_FROM_BACKUP;
}

/** Copy under Laya and strategy stats. Hidden when nothing was restored. */
export function restoredExclusionLine(count: number): string | null {
  if (!Number.isFinite(count) || count < 1) return null;
  if (count === 1) return "Excludes 1 restored fill";
  return `Excludes ${Math.trunc(count)} restored fills`;
}
