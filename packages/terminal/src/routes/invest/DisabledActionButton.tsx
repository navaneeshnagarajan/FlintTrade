/**
 * DisabledActionButton.tsx
 *
 * Shared compound component used across multiple Invest tabs.
 * Renders a disabled button wrapped in a Tooltip so keyboard and mouse users
 * can discover why the action is unavailable.
 *
 * Accessibility: wraps the disabled button in a focusable <span> so the
 * tooltip remains reachable via Tab key (disabled buttons are not focusable).
 */

import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

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
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0}>
            <Button
              variant="outline"
              size="sm"
              disabled
              className="text-xs border-border-default text-text-muted gap-1 cursor-not-allowed opacity-60"
            >
              <Icon className="size-3" />
              {label}
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="bg-surface-card border-border-default text-text-secondary text-xs max-w-52"
        >
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
