/**
 * Inline Laya admission under a place control.
 * Down mute stays on the incident strip. This notice is deny or clamp only.
 */

import { Button } from "@/components/ui/button";
import { LAYA_DEGRADED_LIMITS, type LayaAdmissionNotice as Notice } from "@/lib/layaAdmission";

export function LayaAdmissionNotice({
  notice,
  onPlaceClamped,
  onCancelClamp,
}: {
  notice: Notice | null;
  /** Resubmit qty N through the same place path. Nothing is sent until this click. */
  onPlaceClamped?: (quantity: number) => void;
  onCancelClamp?: () => void;
}) {
  if (!notice) return null;
  if (notice.kind === "clamp") {
    const quantity = notice.appliedQuantity;
    return (
      <div className="space-y-2" data-testid="laya-clamp-confirm">
        <p className="text-xs text-text-secondary" data-testid="laya-clamp" role="status">
          {notice.headline}
        </p>
        {quantity != null && onPlaceClamped ? (
          <div className="flex gap-2">
            <Button type="button" onClick={() => onPlaceClamped(quantity)}>
              {`Place ${quantity}`}
            </Button>
            <Button type="button" variant="outline" onClick={onCancelClamp}>
              Cancel
            </Button>
          </div>
        ) : null}
      </div>
    );
  }
  return (
    <div data-testid="laya-denied" role="alert" className="space-y-0.5">
      <p className="text-xs font-semibold text-text-primary">{notice.headline}</p>
      {notice.reason ? (
        <p className="text-xs text-text-secondary" aria-label="Laya decision">
          {notice.reason}
        </p>
      ) : null}
      {notice.limitsLine ? (
        <p className="text-xs text-text-muted" data-testid="laya-limits">{notice.limitsLine}</p>
      ) : null}
    </div>
  );
}

/** Quiet Degraded line. It is not the money-path Blocked strip. */
export function LayaDegradedLimitsNote({ status }: { status: string | null | undefined }) {
  if (status !== "degraded") return null;
  return (
    <p className="text-xs text-text-muted" data-testid="laya-degraded-limits">
      {LAYA_DEGRADED_LIMITS}
    </p>
  );
}
