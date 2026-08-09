import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";
import type { PracticeOrderReviewSnapshot } from "./practiceOrderReview";

interface PracticeOrderReviewStageProps {
  review: PracticeOrderReviewSnapshot;
  confirming: boolean;
  onBack: () => void;
  onConfirm: () => void;
}

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function detailRow(label: string, value: string, emphasis = false) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border-subtle py-1.5 last:border-0">
      <dt className="text-xxs uppercase tracking-wider text-text-muted">{label}</dt>
      <dd className={`text-right font-mono text-xs tabular-nums ${emphasis ? "font-semibold text-text-primary" : "text-text-secondary"}`}>
        {value}
      </dd>
    </div>
  );
}

/** Dedicated Practice-only review surface. It deliberately does not share a generic order dialog. */
export function PracticeOrderReviewStage({
  review,
  confirming,
  onBack,
  onConfirm,
}: PracticeOrderReviewStageProps) {
  const titleId = useId();
  const descriptionId = useId();
  const backRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const { params, estimatedPrice, estimatedExposure } = review;
  const marketType = params.orderType === "MARKET" || params.orderType === "SL-M";

  useEffect(() => {
    backRef.current?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !confirming) {
      event.preventDefault();
      onBack();
      return;
    }
    if (event.key !== "Tab" || confirming) return;

    const first = backRef.current;
    const last = confirmRef.current;
    if (!first || !last) return;
    if (event.shiftKey && (document.activeElement === first || !event.currentTarget.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  const priceText = estimatedPrice === null
    ? marketType ? "Market · estimate unavailable" : "Unavailable"
    : `${currency.format(estimatedPrice)}${marketType ? " (estimated fill)" : ""}`;
  const exposureText = estimatedExposure === null
    ? "Unavailable"
    : currency.format(estimatedExposure);

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/75 p-3">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onKeyDown={handleKeyDown}
        className="w-full max-w-md rounded-lg border border-accent/40 bg-surface-card p-4 shadow-2xl outline-none"
      >
        <div className="mb-3 flex items-start gap-2">
          <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
          <div>
            <h2 id={titleId} className="font-heading text-sm font-semibold text-text-primary">
              Review Practice order
            </h2>
            <p id={descriptionId} className="mt-1 text-xs leading-relaxed text-text-secondary">
              Simulation only. This order is sent only to FlintTrade&apos;s Practice sandbox. No broker or native trading API is contacted.
            </p>
          </div>
        </div>

        <dl aria-label="Practice order details" className="rounded border border-border-default bg-surface-base px-3 py-1">
          {detailRow("Instrument", `${params.symbol} · ${params.exchange}`, true)}
          {detailRow("Side", params.action, true)}
          {detailRow("Type", params.orderType)}
          {detailRow("Product", params.product)}
          {detailRow("Quantity", params.quantity.toLocaleString("en-IN"))}
          {detailRow("Price", priceText)}
          {params.triggerPrice !== undefined && params.triggerPrice > 0
            ? detailRow("Trigger", currency.format(params.triggerPrice))
            : null}
          {detailRow("Estimated exposure", exposureText, true)}
        </dl>

        <p className="mt-3 text-xxs leading-relaxed text-text-muted">
          Back or any order edit invalidates this review. Confirm submits this exact immutable intent through the existing Practice path.
        </p>

        <div className="mt-4 flex gap-2">
          <button
            ref={backRef}
            type="button"
            disabled={confirming}
            onClick={onBack}
            className="h-9 flex-1 rounded border border-border-default bg-surface-hover px-3 text-xs font-semibold text-text-secondary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50"
          >
            Back to edit
          </button>
          <button
            ref={confirmRef}
            type="button"
            disabled={confirming}
            aria-label="Confirm simulated Practice order"
            aria-busy={confirming}
            onClick={onConfirm}
            className="flex h-9 flex-1 items-center justify-center gap-2 rounded border border-accent bg-accent px-3 text-xs font-semibold text-white hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          >
            {confirming ? <Loader2 aria-hidden="true" className="size-3.5 animate-spin" /> : null}
            {confirming ? "Confirming…" : "Confirm simulation"}
          </button>
        </div>
      </div>
    </div>
  );
}
