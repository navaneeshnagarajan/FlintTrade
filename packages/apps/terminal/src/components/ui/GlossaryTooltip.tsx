/**
 * GlossaryTooltip.tsx — Wraps jargon terms with a hover tooltip showing
 * a plain-English definition from the glossary registry.
 *
 * Usage:
 *   <GlossaryTooltip term="LTCG">LTCG</GlossaryTooltip>
 *
 * If the term is not found in the glossary, renders children without a tooltip.
 */

import type { ReactNode } from "react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { GLOSSARY } from "@/lib/glossary";

interface GlossaryTooltipProps {
  /** The glossary key to look up (e.g. "LTCG", "SIP", "VIX"). */
  term: string;
  /** The visible text or element to wrap. */
  children: ReactNode;
}

export function GlossaryTooltip({ term, children }: GlossaryTooltipProps) {
  const definition = GLOSSARY[term];
  if (!definition) return <>{children}</>;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="underline decoration-dotted decoration-text-muted/50 underline-offset-2 cursor-help">
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs leading-relaxed">
          {definition}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
