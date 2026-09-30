import { RESTORED_FILL_TOOLTIP } from "@/lib/restoredFills";

/** Short tag for a fill restored from a Practice backup. */
export function RestoredFillTag() {
  return (
    <span className="text-xxs text-text-muted" title={RESTORED_FILL_TOOLTIP}>
      Restored
    </span>
  );
}
