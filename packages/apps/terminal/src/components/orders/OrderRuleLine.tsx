/**
 * The ticket's reserved line for refusals and warnings.
 *
 * Two lines are always reserved so the ticket never shifts. It shows the most
 * serious item without a source prefix. A quantity refusal or a block-level
 * rule is red and announced; a warning is amber and never disables Place.
 * "+N" opens the rest of the list, each row prefixed by its source.
 */

import { useState } from "react";

import type { RuleResult } from "@/lib/orderRules";

interface OrderRuleLineProps {
  id: string;
  /** A quantity or lot refusal already worded for the ticket. */
  refusal?: string;
  results: readonly RuleResult[];
  /** A server or broker refusal that carried no rule result. */
  fallback?: string;
  /** False when a toast already announced the same refusal. */
  announce?: boolean;
}

const LEVEL_CLASS: Record<RuleResult["level"], string> = {
  block: "text-loss",
  warn: "text-warning",
  info: "text-text-muted",
};

function lineText(result: RuleResult): string {
  return `${result.source} · ${result.message}`;
}

export function OrderRuleLine({ id, refusal, results, fallback, announce = true }: OrderRuleLineProps) {
  const [open, setOpen] = useState(false);
  const top = results[0];
  const sourced = !refusal && !fallback && top ? lineText(top) : "";
  const headline = refusal || fallback || (top ? top.message : "");
  const rest = refusal || fallback ? results : results.slice(1);
  const level = refusal || fallback ? "block" : top?.level;
  const colour = level ? LEVEL_CLASS[level] : "text-loss";
  const title = sourced || (headline || undefined);
  return (
    <div className="flex flex-col gap-0.5">
      <p
        id={id}
        data-testid="order-rule-line"
        data-level={headline ? level : undefined}
        role={headline && (refusal || (announce && level === "block")) ? "alert" : undefined}
        aria-live={announce && level === "warn" ? "polite" : undefined}
        title={title}
        aria-label={sourced || undefined}
        className={`min-h-8 line-clamp-2 text-xs leading-4 ${colour}`}
      >
        {headline || "\u00a0"}
        {rest.length > 0 ? (
          <button
            type="button"
            data-testid="order-rule-more"
            aria-expanded={open}
            aria-controls={`${id}-list`}
            onClick={() => setOpen((value) => !value)}
            className="ml-1 rounded px-1 text-text-secondary underline-offset-2 hover:underline focus-visible:outline focus-visible:outline-1 focus-visible:outline-accent"
          >
            +{rest.length}
          </button>
        ) : null}
      </p>
      {open && rest.length > 0 ? (
        <ul id={`${id}-list`} data-testid="order-rule-list" className="space-y-0.5 text-xs leading-4">
          {rest.map((result) => (
            <li key={result.rule_id} className={LEVEL_CLASS[result.level]}>
              {lineText(result)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
