/**
 * Callout.tsx — one inline notice style for tips, sample-data notices,
 * warnings and errors, so every page speaks with the same visual voice.
 *
 * Copy stays on readable text tokens; only the icon and the tint carry the
 * tone, so warning and danger notices keep AA contrast in both themes.
 */

import * as React from "react";
import { AlertTriangle, CheckCircle2, Info, Lightbulb, OctagonAlert, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type CalloutTone = "info" | "tip" | "success" | "warning" | "danger" | "neutral";

const TONE: Record<CalloutTone, { box: string; icon: string; Icon: LucideIcon }> = {
  info: { box: "border-info/25 bg-info/[0.07]", icon: "text-info", Icon: Info },
  tip: { box: "border-accent/25 bg-accent/[0.06]", icon: "text-accent", Icon: Lightbulb },
  success: {
    box: "border-profit/25 bg-profit/[0.07]",
    icon: "text-[var(--color-bullish-text,var(--color-profit))]",
    Icon: CheckCircle2,
  },
  warning: {
    box: "border-warning/30 bg-warning/[0.08]",
    icon: "text-[var(--color-warning-text,var(--color-warning))]",
    Icon: AlertTriangle,
  },
  danger: {
    box: "border-loss/30 bg-loss/[0.08]",
    icon: "text-[var(--color-bearish-text,var(--color-loss))]",
    Icon: OctagonAlert,
  },
  neutral: { box: "border-border-default bg-surface-card", icon: "text-text-muted", Icon: Info },
};

export interface CalloutProps {
  tone?: CalloutTone;
  /** Override the tone's icon, or pass null for none. */
  icon?: LucideIcon | null;
  title?: React.ReactNode;
  children?: React.ReactNode;
  /** Trailing action, e.g. a link-style button. */
  action?: React.ReactNode;
  /** Renders a dismiss button when provided. */
  onDismiss?: () => void;
  dismissLabel?: string;
  role?: React.AriaRole;
  "aria-label"?: string;
  className?: string;
  "data-testid"?: string;
}

export function Callout({
  tone = "info",
  icon,
  title,
  children,
  action,
  onDismiss,
  dismissLabel = "Dismiss",
  role = "note",
  className,
  "aria-label": ariaLabel,
  "data-testid": testId,
}: CalloutProps) {
  const toneStyle = TONE[tone];
  const Icon = icon === null ? null : (icon ?? toneStyle.Icon);

  return (
    <div
      role={role}
      aria-label={ariaLabel}
      data-testid={testId}
      data-tone={tone}
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3.5 py-2.5 text-sm",
        toneStyle.box,
        className,
      )}
    >
      {Icon ? (
        <Icon className={cn("mt-0.5 size-4 shrink-0", toneStyle.icon)} aria-hidden="true" />
      ) : null}
      <div className="min-w-0 flex-1 leading-relaxed">
        {title ? <p className="font-medium text-text-primary">{title}</p> : null}
        {children ? <div className="text-text-secondary">{children}</div> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center self-center">{action}</div> : null}
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={dismissLabel}
          className="-mr-1 grid size-6 shrink-0 place-items-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
        >
          <X className="size-3.5" aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}

export default Callout;
