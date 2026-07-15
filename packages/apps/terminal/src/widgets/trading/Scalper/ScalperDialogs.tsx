// ─── Scalper — order confirmation modal + close/cancel AlertDialogs ───────────

import { useEffect, useRef } from "react";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import type { OrderTypeValue, PendingOrder, ProductType } from "./types";

// ─── Order confirmation modal ─────────────────────────────────────────────────

export interface OrderConfirmModalProps {
  pendingOrder: PendingOrder | null;
  lots: number;
  lotSize: number;
  product: ProductType;
  orderType: OrderTypeValue;
  /** Limit price actually sent with the order — shown only for LIMIT. */
  limitPrice: string;
  /** SL distance in points — non-blank means a gated bracket SL leg is sent. */
  slPoints: string;
  /** Target distance in points — non-blank means a gated bracket target leg is sent. */
  targetPoints: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function OrderConfirmModal({
  pendingOrder,
  lots,
  lotSize,
  product,
  orderType,
  limitPrice,
  slPoints,
  targetPoints,
  onConfirm,
  onCancel,
}: OrderConfirmModalProps) {
  const confirmBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (pendingOrder) {
      confirmBtnRef.current?.focus();
    }
  }, [pendingOrder]);

  if (!pendingOrder) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="scalper-confirm-title"
      className="absolute inset-0 flex items-center justify-center bg-surface-base/80 backdrop-blur-sm z-50"
    >
      <div className="bg-surface-card border border-border-default rounded-lg p-4 min-w-64 shadow-2xl">
        <div id="scalper-confirm-title" className="text-sm font-heading font-bold text-text-primary mb-3">
          Confirm Order
        </div>
        <div className="space-y-1.5 mb-4">
          <div className="flex justify-between text-xs">
            <span className="text-text-muted font-sans">Symbol</span>
            <span className="font-mono font-bold text-text-primary">{pendingOrder.sym}</span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted font-sans">Action</span>
            <span
              className={`font-semibold ${
                pendingOrder.action === "BUY" ? "text-profit" : "text-loss"
              }`}
            >
              {pendingOrder.action}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted font-sans">Qty</span>
            <span className="font-mono font-bold text-text-primary">
              {lots * lotSize} ({lots} lot{lots > 1 ? "s" : ""})
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-text-muted font-sans">Product</span>
            <span className="font-mono text-text-primary">
              {product} · {orderType}
            </span>
          </div>
          {/* Only parameters that are ACTUALLY sent to the broker may appear
              here — the modal previously displayed SL/Target values that were
              silently discarded, which is worse than showing nothing. The
              SL/Target rows below are shown only when a real bracket exit leg
              will be placed through the gated bracket endpoint. */}
          {orderType === "LIMIT" && (
            <div className="flex justify-between text-xs">
              <span className="text-text-muted font-sans">Limit Price</span>
              <span className="font-mono font-bold text-text-primary">₹{limitPrice || "—"}</span>
            </div>
          )}
          {slPoints.trim() !== "" && (
            <div className="flex justify-between text-xs">
              <span className="text-text-muted font-sans">SL (bracket leg)</span>
              <span className="font-mono font-bold text-loss">{slPoints} pts</span>
            </div>
          )}
          {targetPoints.trim() !== "" && (
            <div className="flex justify-between text-xs">
              <span className="text-text-muted font-sans">Target (bracket leg)</span>
              <span className="font-mono font-bold text-profit">{targetPoints} pts</span>
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            ref={confirmBtnRef}
            type="button"
            size="sm"
            onClick={onConfirm}
            className={`flex-1 h-8 text-sm font-semibold transition-colors ${
              pendingOrder.action === "BUY"
                ? "bg-profit hover:bg-profit/80 text-white"
                : "bg-loss hover:bg-loss/80 text-white"
            }`}
          >
            Confirm {pendingOrder.action}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onCancel}
            className="flex-1 h-8 text-sm font-medium bg-surface-hover hover:bg-surface-card text-text-secondary border-border-default transition-colors"
          >
            Cancel (Esc)
          </Button>
        </div>
      </div>
    </div>
  );
}

// ─── Close all positions dialog ───────────────────────────────────────────────

export interface CloseAllDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function CloseAllDialog({ open, onOpenChange, onConfirm }: CloseAllDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Close all open positions?</AlertDialogTitle>
          <AlertDialogDescription>
            This will close every open position in the selected execution account at
            market. This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-loss hover:bg-loss/90 text-white"
          >
            Close All Positions
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

// ─── Cancel all orders dialog ─────────────────────────────────────────────────

export interface CancelAllDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

export function CancelAllDialog({ open, onOpenChange, onConfirm }: CancelAllDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Cancel all pending orders?</AlertDialogTitle>
          <AlertDialogDescription>
            All pending orders for the selected broker account will be cancelled, including orders placed outside
            FlintScalper.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep Orders</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>
            Cancel All Orders
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
