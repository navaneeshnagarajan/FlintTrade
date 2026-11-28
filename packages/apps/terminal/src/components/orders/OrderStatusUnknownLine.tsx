import { useId } from "react";
import { AlertTriangle } from "lucide-react";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";

function openOrders(): void {
  window.dispatchEvent(new CustomEvent("flinttrade:addWidget", { detail: { widgetId: "orders" } }));
}

function OpenOrdersButton({ title, describedBy }: { title?: string; describedBy?: string }) {
  return (
    <button
      type="button"
      onClick={openOrders}
      title={title}
      aria-describedby={describedBy}
      className="shrink-0 whitespace-nowrap underline underline-offset-2 hover:text-text-primary"
    >
      Open Orders
    </button>
  );
}

/**
 * Open Orders alone, for a row that has no room for the sentence. The
 * sentence is the control's tooltip and accessible description.
 */
export function OrderStatusUnknownLink({ className = "" }: { className?: string }) {
  const id = useId();
  return (
    <span className={`inline-flex items-center gap-1 text-xxs text-warning ${className}`}>
      <AlertTriangle size={10} aria-hidden className="shrink-0" />
      <OpenOrdersButton title={ORDER_STATUS_UNKNOWN} describedBy={id} />
      <span id={id} hidden>{ORDER_STATUS_UNKNOWN}</span>
    </span>
  );
}

/** Short label used when the full unknown sentence does not fit on one row. */
export const ORDER_STATUS_UNKNOWN_COMPACT = "Status unknown";

/**
 * One-line unknown status when the full sentence does not fit. The approved
 * sentence is the tooltip and accessible description.
 */
export function OrderStatusUnknownCompact({ className = "" }: { className?: string }) {
  const id = useId();
  return (
    <p
      role="status"
      title={ORDER_STATUS_UNKNOWN}
      aria-describedby={id}
      className={`flex items-center gap-1 text-xs text-warning whitespace-nowrap ${className}`}
    >
      <AlertTriangle size={12} aria-hidden className="shrink-0" />
      <span>{ORDER_STATUS_UNKNOWN_COMPACT}</span>
      <span aria-hidden="true">·</span>
      <OpenOrdersButton title={ORDER_STATUS_UNKNOWN} describedBy={id} />
      <span id={id} hidden>{ORDER_STATUS_UNKNOWN}</span>
    </p>
  );
}

/**
 * Tightest one-line unknown status: drops the icon and mid-dot so
 * "Status unknown Open Orders" stays on one row in a narrow slot. The
 * approved sentence is still the tooltip and accessible description.
 */
export function OrderStatusUnknownTight({ className = "" }: { className?: string }) {
  const id = useId();
  return (
    <p
      role="status"
      title={ORDER_STATUS_UNKNOWN}
      aria-describedby={id}
      className={`flex items-center gap-0 text-xxs text-warning whitespace-nowrap ${className}`}
    >
      <span className="pr-0.5">{ORDER_STATUS_UNKNOWN_COMPACT}</span>
      <OpenOrdersButton title={ORDER_STATUS_UNKNOWN} describedBy={id} />
      <span id={id} hidden>{ORDER_STATUS_UNKNOWN}</span>
    </p>
  );
}

/**
 * Persistent line beside locked Buy/Sell controls after a lost submit.
 * `linkOnly` drops the sentence while the widget's own outcome line already
 * says it, so the sentence is shown and announced once.
 */
export function OrderStatusUnknownLine({ className = "", linkOnly = false }: { className?: string; linkOnly?: boolean }) {
  if (linkOnly) {
    return (
      <p className={`flex items-center text-xs text-warning ${className}`}>
        <OpenOrdersButton />
      </p>
    );
  }
  return (
    <p role="status" className={`flex items-center gap-1.5 text-xs text-warning ${className}`}>
      <AlertTriangle size={12} aria-hidden className="shrink-0" />
      <span>{ORDER_STATUS_UNKNOWN}</span>
      <OpenOrdersButton />
    </p>
  );
}
