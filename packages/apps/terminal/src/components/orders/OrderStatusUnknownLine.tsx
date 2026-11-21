import { AlertTriangle } from "lucide-react";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";

function openOrders(): void {
  window.dispatchEvent(new CustomEvent("flinttrade:addWidget", { detail: { widgetId: "orders" } }));
}

function OpenOrdersButton() {
  return (
    <button type="button" onClick={openOrders} className="underline underline-offset-2 hover:text-text-primary">
      Open Orders
    </button>
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
