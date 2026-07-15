/**
 * AlertTemplateBrowser.tsx
 *
 * A preserved browser for TradingView alert-message examples.
 *
 * Features:
 *  - Category filter tabs (All / Trend / Momentum / Volatility / Options / Custom)
 *  - Expandable cards showing the webhook JSON and optional Pine Script snippet
 *  - One-click copy of the JSON payload to the clipboard
 *  - Badge per placeholder so users know which TradingView variables are active
 *  - Fully keyboard-accessible; uses shadcn/ui primitives throughout
 */

import { memo, useCallback, useMemo, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  ClipboardCopy,
  Code2,
  Filter,
  Webhook,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import {
  filterTemplatesByCategory,
  TV_TEMPLATE_CATEGORIES,
  type TVAlertTemplate,
} from "@/lib/tradingviewTemplates";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Category = TVAlertTemplate["category"] | "all";

// ---------------------------------------------------------------------------
// Category filter pill
// ---------------------------------------------------------------------------

interface FilterPillProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

const FilterPill = memo(function FilterPill({
  label,
  active,
  onClick,
}: FilterPillProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center rounded-full px-3 py-1 text-xs font-medium capitalize transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "bg-primary text-primary-foreground"
          : "border border-border-default bg-surface-card text-muted-foreground hover:bg-surface-hover hover:text-foreground"
      )}
    >
      {label}
    </button>
  );
});

// ---------------------------------------------------------------------------
// Category → badge variant mapping
// ---------------------------------------------------------------------------

const CATEGORY_VARIANT: Record<
  TVAlertTemplate["category"],
  "bullish" | "bearish" | "atm" | "neutral" | "default"
> = {
  trend: "bullish",
  momentum: "atm",
  volatility: "bearish",
  options: "neutral",
  custom: "default",
};

// ---------------------------------------------------------------------------
// Single template card
// ---------------------------------------------------------------------------

interface TemplateCardProps {
  template: TVAlertTemplate;
}

const TemplateCard = memo(function TemplateCard({ template }: TemplateCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showPine, setShowPine] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(template.webhookMessage);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable (e.g. in test env) — silent fallback
    }
  }, [template.webhookMessage]);

  const toggleExpand = useCallback(() => setExpanded((v) => !v), []);
  const togglePine = useCallback(() => setShowPine((v) => !v), []);

  return (
    <Card className="flex flex-col gap-0 overflow-hidden p-0 transition-shadow hover:shadow-md">
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <CardHeader className="gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 flex-col gap-1">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Webhook
                className="size-4 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
              <span className="truncate">{template.name}</span>
            </CardTitle>
            <CardDescription className="text-xs leading-relaxed">
              {template.description}
            </CardDescription>
          </div>
          <Badge
            variant={CATEGORY_VARIANT[template.category]}
            className="shrink-0 capitalize"
          >
            {template.category}
          </Badge>
        </div>
      </CardHeader>

      {/* ── Actions bar ────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-t border-border-default px-4 py-2">
        <Button
          variant="ghost"
          size="xs"
          onClick={toggleExpand}
          aria-expanded={expanded}
          aria-controls={`tv-template-body-${template.id}`}
        >
          {expanded ? (
            <ChevronUp className="size-3" aria-hidden="true" />
          ) : (
            <ChevronDown className="size-3" aria-hidden="true" />
          )}
          {expanded ? "Collapse" : "View JSON"}
        </Button>

        {template.pineSnippet && (
          <Button
            variant="ghost"
            size="xs"
            onClick={togglePine}
            aria-expanded={showPine}
            aria-controls={`tv-template-pine-${template.id}`}
          >
            <Code2 className="size-3" aria-hidden="true" />
            {showPine ? "Hide Pine" : "Pine Script"}
          </Button>
        )}

        <Button
          variant="outline"
          size="xs"
          onClick={handleCopy}
          className="ml-auto"
          aria-label={`Copy webhook JSON for ${template.name}`}
        >
          {copied ? (
            <Check className="size-3 text-green-500" aria-hidden="true" />
          ) : (
            <ClipboardCopy className="size-3" aria-hidden="true" />
          )}
          {copied ? "Copied!" : "Copy JSON"}
        </Button>
      </div>

      {/* ── Expanded body ──────────────────────────────────────────────────── */}
      <CardContent
        id={`tv-template-body-${template.id}`}
        className={cn("flex flex-col gap-3 px-4 pt-0", !expanded && "hidden")}
        aria-hidden={!expanded}
      >
        {/* Webhook JSON */}
        <div className="rounded-md border border-border-default bg-surface-base p-3">
          <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-foreground/80">
            {template.webhookMessage}
          </pre>
        </div>

        {/* Placeholders */}
        {template.placeholders.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-xs text-muted-foreground">Placeholders:</span>
            {template.placeholders.map((ph) => (
              <Badge key={ph} variant="outline" className="font-mono text-xs">
                {ph}
              </Badge>
            ))}
          </div>
        )}

        {/* Pine Script snippet */}
        {template.pineSnippet && (
          <div
            id={`tv-template-pine-${template.id}`}
            className={cn(!showPine && "hidden")}
            aria-hidden={!showPine}
          >
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <Code2 className="size-3" aria-hidden="true" />
              Pine Script v5 snippet
            </p>
            <div className="rounded-md border border-border-default bg-surface-base p-3">
              <pre className="overflow-x-auto font-mono text-xs leading-relaxed text-foreground/80">
                {template.pineSnippet}
              </pre>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

// ---------------------------------------------------------------------------
// AlertTemplateBrowser — top-level export
// ---------------------------------------------------------------------------

export interface AlertTemplateBrowserProps {
  /** Fixed height for the scrollable card area. Defaults to "calc(100vh - 12rem)". */
  scrollHeight?: string;
  className?: string;
}

/**
 * AlertTemplateBrowser
 *
 * Renders all TV_ALERT_TEMPLATES in a filterable, scrollable card grid.
 * Drop it inside any route or Dockview panel that needs TradingView alert setup.
 *
 * @example
 * <AlertTemplateBrowser scrollHeight="600px" />
 */
export const AlertTemplateBrowser = memo(function AlertTemplateBrowser({
  scrollHeight = "calc(100vh - 12rem)",
  className,
}: AlertTemplateBrowserProps) {
  const [activeCategory, setActiveCategory] = useState<Category>("all");

  const filtered = useMemo(
    () =>
      activeCategory === "all"
        ? filterTemplatesByCategory()
        : filterTemplatesByCategory(activeCategory),
    [activeCategory]
  );

  const categories: Category[] = ["all", ...TV_TEMPLATE_CATEGORIES];

  return (
    <section
      className={cn("flex flex-col gap-4", className)}
      aria-label="TradingView Alert Template Browser"
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-1">
        <h2 className="flex items-center gap-2 text-base font-semibold leading-none tracking-tight text-balance">
          <Webhook className="size-4 text-muted-foreground" aria-hidden="true" />
          Alert Template Library
        </h2>
        <p className="text-sm text-muted-foreground">
          Pre-built webhook payloads for TradingView alerts — copy and paste
          directly into the alert message field.
        </p>
      </div>

      {/* ── Category filters ───────────────────────────────────────────────── */}
      <div
        role="group"
        aria-label="Filter templates by category"
        className="flex flex-wrap items-center gap-2"
      >
        <Filter
          className="size-3.5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        {categories.map((cat) => (
          <FilterPill
            key={cat}
            label={cat}
            active={activeCategory === cat}
            onClick={() => setActiveCategory(cat)}
          />
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {filtered.length} template{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Card grid ──────────────────────────────────────────────────────── */}
      <ScrollArea style={{ height: scrollHeight }}>
        {filtered.length === 0 ? (
          <p className="py-12 text-center text-sm text-muted-foreground">
            No templates in this category.
          </p>
        ) : (
          <div className="grid grid-cols-1 gap-3 pr-3 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((template) => (
              <TemplateCard key={template.id} template={template} />
            ))}
          </div>
        )}
      </ScrollArea>
    </section>
  );
});
