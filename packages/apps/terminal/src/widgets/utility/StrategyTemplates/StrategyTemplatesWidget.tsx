/**
 * StrategyTemplatesWidget — Option strategy template library for FlintTrade.
 *
 * Features:
 *   - Grid of strategy template cards, read from the single shared catalogue
 *     `lib/strategyTemplates` (the Lab builder and the OptionChain LegBuilder
 *     read the same rows — there is exactly one definition of "Iron Condor")
 *   - Each card: name, legs summary, max profit, max loss, breakeven, market outlook
 *   - Loadable cards stash the template via templateBridge, dispatch the
 *     load event, and navigate to the Lab's Options Builder
 *   - Templates with stock or multi-expiry legs are reference-only — the
 *     options builder cannot faithfully represent them, and loading a
 *     degenerate approximation (e.g. a covered call without the stock leg)
 *     would misstate the strategy's risk
 *   - Filter by market outlook (bullish / bearish / neutral / all)
 */

import { useState, useMemo, useEffect, memo } from "react";
import { BookOpen } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import {
  builderLegsFor,
  STRATEGY_TEMPLATES,
  type StrategyOutlook,
  type StrategyTemplate,
  type StrategyTemplateLeg,
} from "@/lib/strategyTemplates";
import {
  LOAD_TEMPLATE_EVENT,
  stashPendingTemplate,
  type BuilderTemplate,
} from "@/tools/StrategyBuilder/templateBridge";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Outlook = StrategyOutlook;

// ---------------------------------------------------------------------------
// Outlook config
// ---------------------------------------------------------------------------

const OUTLOOK_CONFIG: Record<Outlook, { label: string; className: string }> = {
  bullish: { label: "Bullish", className: "bg-profit/15 text-profit border-profit/30" },
  bearish: { label: "Bearish", className: "bg-loss/15 text-loss border-loss/30" },
  neutral: { label: "Neutral", className: "bg-text-muted/15 text-text-secondary border-border-subtle" },
  volatile: { label: "Volatile", className: "bg-accent/15 text-accent border-accent/30" },
};

// ---------------------------------------------------------------------------
// Legs diagram — compact visual
// ---------------------------------------------------------------------------

interface LegsProps {
  legs: readonly StrategyTemplateLeg[];
}

/**
 * Render one leg chip. The lot multiplier is shown whenever it exceeds 1 — the
 * butterfly's body is a single double-lot leg, and a chip that omitted the ×2
 * would understate the position by half.
 */
function legChipLabel(leg: StrategyTemplateLeg): string {
  const sign = leg.action === "BUY" ? "+" : "−";
  const body = leg.optionType === "STOCK"
    ? "STOCK"
    : `${leg.strikeLabel ?? ""} ${leg.optionType}`.trim();
  const mult = leg.lots > 1 ? ` ×${leg.lots}` : "";
  return `${sign}${body}${mult}`;
}

function LegsDisplay({ legs }: LegsProps) {
  return (
    <div className="flex flex-wrap gap-1" aria-label="Strategy legs">
      {legs.map((leg, i) => (
        <span
          key={i}
          className={cn(
            "text-xxs px-1 py-px rounded border font-mono",
            leg.action === "BUY"
              ? "bg-profit/10 text-profit border-profit/20"
              : "bg-loss/10 text-loss border-loss/20",
          )}
        >
          {legChipLabel(leg)}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strategy card
// ---------------------------------------------------------------------------

interface StrategyCardProps {
  template: StrategyTemplate;
  loadable: boolean;
  onSelect: (id: string) => void;
}

function StrategyCard({ template, loadable, onSelect }: StrategyCardProps) {
  const outlook = OUTLOOK_CONFIG[template.outlook];

  const body = (
    <>
      {/* Name + outlook */}
      <div className="flex items-start justify-between gap-1">
        <span
          className={cn(
            "text-xs font-semibold text-text-primary leading-tight",
            loadable && "group-hover:text-accent transition-colors",
          )}
        >
          {template.name}
        </span>
        <span className="flex items-center gap-1 shrink-0">
          {!loadable && (
            <span className="text-xxs px-1.5 py-px rounded border bg-text-muted/10 text-text-muted border-border-subtle">
              Reference
            </span>
          )}
          <span className={cn("text-xxs px-1.5 py-px rounded border", outlook.className)}>
            {outlook.label}
          </span>
        </span>
      </div>

      {/* Legs */}
      <LegsDisplay legs={template.legs} />

      {/* P&L summary */}
      <div className="grid grid-cols-2 gap-x-2 gap-y-0.5">
        <div>
          <span className="text-xxs text-text-muted block">Max Profit</span>
          <span className="text-xxs font-mono text-profit">{template.maxProfit}</span>
        </div>
        <div>
          <span className="text-xxs text-text-muted block">Max Loss</span>
          <span className="text-xxs font-mono text-loss">{template.maxLoss}</span>
        </div>
      </div>

      {/* Description */}
      <p className="text-xxs text-text-muted leading-relaxed line-clamp-2">
        {template.description}
      </p>
    </>
  );

  if (!loadable) {
    return (
      <div
        className="text-left w-full rounded-lg border border-border-subtle bg-surface-elevated p-2.5 space-y-2"
        aria-label={`${template.name} strategy template (reference only)`}
      >
        {body}
        <p className="text-xxs text-text-muted/80 italic">
          Reference only — includes stock or multi-expiry legs the options builder cannot represent.
        </p>
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelect(template.id)}
      className="text-left w-full rounded-lg border border-border-subtle bg-surface-elevated hover:bg-surface-hover hover:border-accent/40 transition-all p-2.5 space-y-2 group"
      aria-label={`Load ${template.name} strategy template`}
    >
      {body}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

type OutlookFilter = Outlook | "all";

function StrategyTemplatesWidget() {
  const track = useTrackBehavior();
  const [outlookFilter, setOutlookFilter] = useState<OutlookFilter>("all");

  useEffect(() => {
    track("trade", "widget_view_strategy_templates");
  }, [track]);

  const filtered = useMemo(
    () =>
      outlookFilter === "all"
        ? STRATEGY_TEMPLATES
        : STRATEGY_TEMPLATES.filter((t) => t.outlook === outlookFilter),
    [outlookFilter],
  );

  function handleSelect(id: string) {
    const tmpl = STRATEGY_TEMPLATES.find((t) => t.id === id);
    if (!tmpl) return;
    const legs = builderLegsFor(tmpl);
    if (!legs) return;

    const payload: BuilderTemplate = { id: tmpl.id, name: tmpl.name, legs };
    // Stash for the Options Builder to pick up after navigation, dispatch the
    // live event for any already-mounted builder, then head to the Lab.
    stashPendingTemplate(payload);
    window.dispatchEvent(new CustomEvent(LOAD_TEMPLATE_EVENT, { detail: payload }));
    window.dispatchEvent(new CustomEvent("flinttrade:navigate", { detail: { path: "/lab" } }));
    track("trade", `strategy_template_selected_${id}`);
  }

  const filters: { value: OutlookFilter; label: string }[] = [
    { value: "all", label: "All" },
    { value: "bullish", label: "Bullish" },
    { value: "bearish", label: "Bearish" },
    { value: "neutral", label: "Neutral" },
    { value: "volatile", label: "Volatile" },
  ];

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <BookOpen size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Strategy Templates</span>
        <span className="text-xxs text-text-muted ml-1">({filtered.length})</span>
        <div className="flex-1" />
      </div>

      {/* Outlook filter tabs */}
      <div
        className="flex-none flex items-center gap-1 px-2 py-1.5 border-b border-border-subtle bg-surface-elevated overflow-x-auto"
        role="group"
        aria-label="Filter by market outlook"
      >
        {filters.map((f) => (
          <button
            key={f.value}
            onClick={() => setOutlookFilter(f.value)}
            className={cn(
              "px-2.5 py-0.5 rounded text-xxs font-medium transition-colors shrink-0",
              outlookFilter === f.value
                ? "bg-accent text-white"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
            aria-pressed={outlookFilter === f.value}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Grid */}
      <div className="flex-1 overflow-auto p-2">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {filtered.map((tmpl) => (
            <StrategyCard
              key={tmpl.id}
              template={tmpl}
              loadable={builderLegsFor(tmpl) !== null}
              onSelect={handleSelect}
            />
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="flex items-center justify-center py-12 text-text-muted text-sm">
            No templates for this outlook.
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(StrategyTemplatesWidget);
