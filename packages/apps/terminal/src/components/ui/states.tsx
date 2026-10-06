/**
 * states.tsx — shared empty, loading and error states.
 *
 * One shape everywhere: icon, short title, one sentence of help, and at most
 * one or two actions. Loading states announce themselves politely; error
 * states use role="alert" only when asked, so a panel that is simply
 * unavailable does not interrupt a screen reader.
 */

import * as React from "react";
import { AlertTriangle, Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// EmptyState
// ---------------------------------------------------------------------------

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Primary and secondary actions. */
  action?: React.ReactNode;
  /** Compact spacing for panels and cards. */
  size?: "sm" | "md";
  className?: string;
  "data-testid"?: string;
}

export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  size = "md",
  className,
  "data-testid": testId,
}: EmptyStateProps) {
  return (
    <div
      data-testid={testId}
      className={cn(
        "flex flex-col items-center justify-center text-center",
        size === "md" ? "gap-3 px-6 py-12" : "gap-2 px-4 py-8",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "grid place-items-center rounded-xl border border-border-default bg-surface-card text-text-muted",
          size === "md" ? "size-11" : "size-9",
        )}
      >
        <Icon className={size === "md" ? "size-5" : "size-4"} strokeWidth={1.75} />
      </span>
      <div className="max-w-sm space-y-1">
        <p className="ft-text-card-title text-text-primary">{title}</p>
        {description ? <p className="text-sm leading-relaxed text-text-secondary">{description}</p> : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LoadingState
// ---------------------------------------------------------------------------

export interface LoadingStateProps {
  label?: string;
  /** Fill the parent's height and centre the indicator. */
  fill?: boolean;
  className?: string;
}

export function LoadingState({ label = "Loading…", fill = false, className }: LoadingStateProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center justify-center gap-3 px-6 py-12 text-sm text-text-muted",
        fill && "h-full min-h-0 flex-1",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="size-4 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
      />
      <span>{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ErrorState
// ---------------------------------------------------------------------------

export interface ErrorStateProps {
  title?: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  /** Announce immediately (use for failures the user just caused). */
  alert?: boolean;
  className?: string;
}

export function ErrorState({
  title = "Something went wrong",
  description,
  action,
  alert = false,
  className,
}: ErrorStateProps) {
  return (
    <div
      role={alert ? "alert" : undefined}
      className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)}
    >
      <span
        aria-hidden="true"
        className="grid size-11 place-items-center rounded-xl border border-loss/30 bg-loss/[0.08] text-[var(--color-bearish-text,var(--color-loss))]"
      >
        <AlertTriangle className="size-5" strokeWidth={1.75} />
      </span>
      <div className="max-w-sm space-y-1">
        <p className="ft-text-card-title text-text-primary">{title}</p>
        {description ? <p className="text-sm leading-relaxed text-text-secondary">{description}</p> : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap items-center justify-center gap-2">{action}</div> : null}
    </div>
  );
}
