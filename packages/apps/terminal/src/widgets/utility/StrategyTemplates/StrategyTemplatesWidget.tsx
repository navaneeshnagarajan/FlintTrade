/**
 * StrategyTemplatesWidget — Option strategy template library for FlintTrade.
 *
 * Features:
 *   - Grid of 12 option strategy template cards
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
  LOAD_TEMPLATE_EVENT,
  stashPendingTemplate,
  type BuilderTemplate,
  type BuilderTemplateLeg,
} from "@/tools/StrategyBuilder/templateBridge";

// ---------------------------------------------------------------------------
// Types & data
// ---------------------------------------------------------------------------

type Outlook = "bullish" | "bearish" | "neutral" | "volatile";

interface StrategyLeg {
  action: "buy" | "sell";
  type: "call" | "put" | "stock";
  strike?: "ATM" | "OTM" | "ITM" | string;
  expiry?: "near" | "far";
  /** Strike offset from ATM in strike-gap units — required for builder loading. */
  strikeOffset?: number;
}

interface StrategyTemplate {
  id: string;
  name: string;
  legs: StrategyLeg[];
  maxProfit: string;
  maxLoss: string;
  breakeven: string;
  outlook: Outlook;
  description: string;
}

/**
 * A template is loadable into the Options Builder only when every leg is a
 * single-expiry option with an explicit strike offset. Stock legs and
 * calendar (multi-expiry) legs have no representation in the builder.
 */
function builderLegsFor(template: StrategyTemplate): BuilderTemplateLeg[] | null {
  const legs: BuilderTemplateLeg[] = [];
  for (const leg of template.legs) {
    if (leg.type === "stock" || leg.expiry !== undefined || leg.strikeOffset === undefined) {
      return null;
    }
    legs.push({
      action: leg.action === "buy" ? "BUY" : "SELL",
      optionType: leg.type === "call" ? "CE" : "PE",
      strikeOffset: leg.strikeOffset,
      lots: 1,
    });
  }
  return legs.length > 0 ? legs : null;
}

const TEMPLATES: StrategyTemplate[] = [
  {
    id: "long_call",
    name: "Long Call",
    legs: [{ action: "buy", type: "call", strike: "ATM", strikeOffset: 0 }],
    maxProfit: "Unlimited",
    maxLoss: "Premium paid",
    breakeven: "Strike + Premium",
    outlook: "bullish",
    description: "Right to buy. Profits when price rises above breakeven.",
  },
  {
    id: "long_put",
    name: "Long Put",
    legs: [{ action: "buy", type: "put", strike: "ATM", strikeOffset: 0 }],
    maxProfit: "Strike − Premium",
    maxLoss: "Premium paid",
    breakeven: "Strike − Premium",
    outlook: "bearish",
    description: "Right to sell. Profits when price falls below breakeven.",
  },
  {
    id: "bull_call_spread",
    name: "Bull Call Spread",
    legs: [
      { action: "buy", type: "call", strike: "ATM", strikeOffset: 0 },
      { action: "sell", type: "call", strike: "OTM", strikeOffset: 1 },
    ],
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Long strike + Net debit",
    outlook: "bullish",
    description: "Capped profit, reduced cost vs long call. Moderately bullish.",
  },
  {
    id: "bear_put_spread",
    name: "Bear Put Spread",
    legs: [
      { action: "buy", type: "put", strike: "ATM", strikeOffset: 0 },
      { action: "sell", type: "put", strike: "OTM", strikeOffset: -1 },
    ],
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Long strike − Net debit",
    outlook: "bearish",
    description: "Capped profit, reduced cost vs long put. Moderately bearish.",
  },
  {
    id: "straddle",
    name: "Straddle",
    legs: [
      { action: "buy", type: "call", strike: "ATM", strikeOffset: 0 },
      { action: "buy", type: "put", strike: "ATM", strikeOffset: 0 },
    ],
    maxProfit: "Unlimited",
    maxLoss: "Total premium",
    breakeven: "ATM ± Total premium",
    outlook: "volatile",
    description: "Profits from large moves in either direction. High cost.",
  },
  {
    id: "strangle",
    name: "Strangle",
    legs: [
      { action: "buy", type: "call", strike: "OTM", strikeOffset: 1 },
      { action: "buy", type: "put", strike: "OTM", strikeOffset: -1 },
    ],
    maxProfit: "Unlimited",
    maxLoss: "Total premium",
    breakeven: "Strikes ± Total premium",
    outlook: "volatile",
    description: "Cheaper than straddle. Needs larger move to profit.",
  },
  {
    id: "iron_condor",
    name: "Iron Condor",
    legs: [
      { action: "sell", type: "call", strike: "OTM", strikeOffset: 1 },
      { action: "buy", type: "call", strike: "OTM", strikeOffset: 2 },
      { action: "sell", type: "put", strike: "OTM", strikeOffset: -1 },
      { action: "buy", type: "put", strike: "OTM", strikeOffset: -2 },
    ],
    maxProfit: "Net credit",
    maxLoss: "Width − Net credit",
    breakeven: "Short strikes ± Net credit",
    outlook: "neutral",
    description: "Profits when price stays within a range. Classic range trade.",
  },
  {
    id: "butterfly",
    name: "Butterfly",
    legs: [
      { action: "buy", type: "call", strike: "ITM", strikeOffset: -1 },
      { action: "sell", type: "call", strike: "ATM", strikeOffset: 0 },
      { action: "sell", type: "call", strike: "ATM", strikeOffset: 0 },
      { action: "buy", type: "call", strike: "OTM", strikeOffset: 1 },
    ],
    maxProfit: "Width − Net debit",
    maxLoss: "Net debit",
    breakeven: "Wings ± Net debit",
    outlook: "neutral",
    description: "Max profit at ATM strike at expiry. Tight range strategy.",
  },
  {
    id: "covered_call",
    name: "Covered Call",
    legs: [
      { action: "buy", type: "stock" },
      { action: "sell", type: "call", strike: "OTM" },
    ],
    maxProfit: "Strike − Entry + Premium",
    maxLoss: "Entry − Premium",
    breakeven: "Entry − Premium",
    outlook: "neutral",
    description: "Generates income on held stock. Caps upside above strike.",
  },
  {
    id: "protective_put",
    name: "Protective Put",
    legs: [
      { action: "buy", type: "stock" },
      { action: "buy", type: "put", strike: "ATM" },
    ],
    maxProfit: "Unlimited",
    maxLoss: "Entry − Strike + Premium",
    breakeven: "Entry + Premium",
    outlook: "bullish",
    description: "Insurance for long stock position. Limits downside loss.",
  },
  {
    id: "collar",
    name: "Collar",
    legs: [
      { action: "buy", type: "stock" },
      { action: "buy", type: "put", strike: "OTM" },
      { action: "sell", type: "call", strike: "OTM" },
    ],
    maxProfit: "Call strike − Entry + Net credit",
    maxLoss: "Entry − Put strike − Net credit",
    breakeven: "Entry + Net debit",
    outlook: "neutral",
    description: "Protects gains on stock. Sacrifices upside for downside protection.",
  },
  {
    id: "calendar_spread",
    name: "Calendar Spread",
    legs: [
      { action: "sell", type: "call", strike: "ATM", expiry: "near" },
      { action: "buy", type: "call", strike: "ATM", expiry: "far" },
    ],
    maxProfit: "Time decay differential",
    maxLoss: "Net debit",
    breakeven: "Near strike ± Range",
    outlook: "neutral",
    description: "Exploits time decay difference between expiries. Low-directional.",
  },
];

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
  legs: StrategyLeg[];
}

function LegsDisplay({ legs }: LegsProps) {
  return (
    <div className="flex flex-wrap gap-1" aria-label="Strategy legs">
      {legs.map((leg, i) => (
        <span
          key={i}
          className={cn(
            "text-xxs px-1 py-px rounded border font-mono",
            leg.action === "buy"
              ? "bg-profit/10 text-profit border-profit/20"
              : "bg-loss/10 text-loss border-loss/20",
          )}
        >
          {leg.action === "buy" ? "+" : "−"}{leg.type === "stock" ? "STOCK" : `${leg.strike ?? ""} ${leg.type.toUpperCase()}`}
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
        ? TEMPLATES
        : TEMPLATES.filter((t) => t.outlook === outlookFilter),
    [outlookFilter],
  );

  function handleSelect(id: string) {
    const tmpl = TEMPLATES.find((t) => t.id === id);
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
