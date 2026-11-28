/**
 * Disabled controls that still say why. A disabled button is not focusable,
 * so the reason sits on a focusable span wrapped in a Tooltip. Keyboard and
 * screen-reader users reach it with Tab.
 */

import type { ReactNode } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface DisabledReasonProps {
  /** Why the wrapped control is disabled. Null leaves the control as is. */
  reason: string | null | undefined;
  className?: string;
  children: ReactNode;
}

export function DisabledReason({ reason, className, children }: DisabledReasonProps) {
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip open={reason ? undefined : false}>
        <TooltipTrigger asChild>
          <span tabIndex={reason ? 0 : undefined} className={className}>
            {children}
          </span>
        </TooltipTrigger>
        {reason ? (
          <TooltipContent
            side="top"
            className="bg-surface-card border-border-default text-text-secondary text-xs max-w-52"
          >
            {reason}
          </TooltipContent>
        ) : null}
      </Tooltip>
    </TooltipProvider>
  );
}

interface DisabledActionButtonProps {
  label: string;
  tooltip: string;
  icon?: typeof Plus;
}

export function DisabledActionButton({
  label,
  tooltip,
  icon: Icon = Plus,
}: DisabledActionButtonProps) {
  return (
    <DisabledReason reason={tooltip}>
      <Button
        variant="outline"
        size="sm"
        disabled
        className="text-xs border-border-default text-text-muted gap-1 cursor-not-allowed opacity-60"
      >
        <Icon className="size-3" />
        {label}
      </Button>
    </DisabledReason>
  );
}
