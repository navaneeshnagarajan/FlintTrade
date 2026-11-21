import { AlertTriangle } from "lucide-react";
import { ORDER_STATUS_UNKNOWN } from "@/lib/operatorIncident";

function openOrders(): void {
  window.dispatchEvent(new CustomEvent("flinttrade:addWidget", { detail: { widgetId: "orders" } }));
}

/** Persistent line beside locked Buy/Sell controls after a lost submit. */
export function OrderStatusUnknownLine({ className = "" }: { className?: string }) {
  return (
    <p role="status" className={`flex items-center gap-1.5 text-xs text-warning ${className}`}>
      <AlertTriangle size={12} aria-hidden className="shrink-0" />
      <span>{ORDER_STATUS_UNKNOWN}</span>
      <button type="button" onClick={openOrders} className="underline underline-offset-2 hover:text-text-primary">
        Open Orders
      </button>
    </p>
  );
}
