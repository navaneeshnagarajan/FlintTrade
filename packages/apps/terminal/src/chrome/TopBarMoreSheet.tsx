/**
 * Overflow sheet for skinny-window TopBar chrome (FT-MOBILE-002).
 *
 * Holds Workspace, account, Tools, search, fullscreen, clock, and related
 * controls that would otherwise clip off-screen. Rows keep a 44px hit target.
 */

import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function MoreRow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-testid="topbar-more-row"
      className={cn("flex min-h-11 items-center gap-2 px-3", className)}
    >
      {children}
    </div>
  );
}

export default function TopBarMoreSheet({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[121]">
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label="Dismiss More"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-label="More"
        aria-modal="true"
        data-testid="topbar-more-sheet"
        className="absolute inset-x-0 bottom-0 max-h-[min(80dvh,32rem)] overflow-y-auto rounded-t-xl border-t border-border-default bg-surface-base p-2 pb-4 shadow-2xl"
      >
        <div className="flex items-center justify-between px-3">
          <h2 className="text-sm font-heading font-semibold text-text-primary">More</h2>
          <Button
            variant="ghost"
            size="sm"
            className="min-h-11 min-w-11 p-0 text-text-muted hover:text-text-primary"
            onClick={onClose}
            aria-label="Close More"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        <div className="flex flex-col gap-1">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
