/**
 * Inline Laya admission under a place control.
 * Down mute stays on the incident strip. This notice is deny or clamp only.
 */

import { LAYA_DEGRADED_LIMITS, type LayaAdmissionNotice as Notice } from "@/lib/layaAdmission";

export function LayaAdmissionNotice({ notice }: { notice: Notice | null }) {
  if (!notice) return null;
  if (notice.kind === "clamp") {
    return (
      <p className="text-xs text-text-secondary" data-testid="laya-clamp" role="status">
        {notice.headline}
      </p>
    );
  }
  return (
    <div data-testid="laya-denied" role="alert" className="space-y-0.5">
      <p className="text-xs font-semibold text-text-primary">{notice.headline}</p>
      {notice.reason ? (
        <p className="text-xs text-text-secondary">{notice.reason}</p>
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
