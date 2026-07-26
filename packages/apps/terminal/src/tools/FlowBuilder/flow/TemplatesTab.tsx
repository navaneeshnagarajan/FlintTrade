/**
 * TemplatesTab — browse and apply flow templates within FlowBuilderTool.
 */

import { useState } from "react";
import { ChevronRight, Info } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { FLOW_TEMPLATES, type FlowTemplate, type Difficulty } from "./FlowTemplates";

// ---------------------------------------------------------------------------
// DifficultyBadge
// ---------------------------------------------------------------------------

export function DifficultyBadge({ level }: { level: Difficulty }) {
  const map: Record<Difficulty, string> = {
    Beginner: "bg-bullish-bg text-emerald-400 border-bullish-border",
    Intermediate: "bg-surface-elevated text-primary border-border-default",
    Advanced: "bg-atm-bg text-amber-400 border-atm-border",
  };
  return <Badge className={`text-xxs h-4 px-1.5 ${map[level]}`}>{level}</Badge>;
}

// ---------------------------------------------------------------------------
// TemplatesTab
// ---------------------------------------------------------------------------

export interface TemplatesTabProps {
  onUse: (template: FlowTemplate) => void;
}

export function TemplatesTab({ onUse }: TemplatesTabProps) {
  const categories = [...new Set(FLOW_TEMPLATES.map((t) => t.category))];
  const [activeCategory, setActiveCategory] = useState("All");

  const filtered =
    activeCategory === "All"
      ? FLOW_TEMPLATES
      : FLOW_TEMPLATES.filter((t) => t.category === activeCategory);

  return (
    <div className="p-4">
      <div className="mb-4 flex items-start gap-2 rounded-md border border-atm-border bg-atm-bg px-3 py-2 text-xs text-text-secondary">
        <Info size={13} className="mt-0.5 shrink-0 text-amber-400" />
        <span>Drafts only. Loading a template saves a draft to your workspace; it does not execute a workflow or send an order.</span>
      </div>
      <div className="flex items-center gap-1.5 flex-wrap mb-4">
        {["All", ...categories].map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={[
              "text-xs px-2.5 py-0.5 rounded-full border transition-colors",
              activeCategory === cat
                ? "bg-neutral-bg text-primary border-neutral-border"
                : "bg-surface-card text-text-muted border-border-default hover:border-border-strong",
            ].join(" ")}
          >
            {cat}
          </button>
        ))}
      </div>

      <div className="grid gap-3">
        {filtered.map((tmpl) => (
          <Card key={tmpl.id} className="bg-surface-card border-border-default transition-colors">
            <CardHeader className="pt-3 pb-1 px-3">
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-sm font-medium text-text-primary leading-tight">
                  {tmpl.name}
                </CardTitle>
                <div className="flex items-center gap-1.5 shrink-0 mt-0.5">
                  <DifficultyBadge level={tmpl.difficulty} />
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-3 pb-3">
              <p className="text-xs text-text-muted mb-2 leading-relaxed">{tmpl.description}</p>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5 flex-wrap">
                  {tmpl.tags.slice(0, 3).map((tag) => (
                    <Badge key={tag} className="text-xxs h-4 px-1.5 bg-border-default text-text-secondary border-border-default">
                      {tag}
                    </Badge>
                  ))}
                  {/* Built templates report their real node count so the label
                      cannot drift from the workflow. Drafts have no workflow
                      yet, so their count is a plan and says so — it used to
                      render as fact beside an empty node list. */}
                  <span className="text-xs text-text-muted">
                    {tmpl.workflow.nodes.length > 0
                      ? `${tmpl.workflow.nodes.length} nodes`
                      : `${tmpl.nodeCount} nodes planned`}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 px-2 text-xs text-text-muted hover:text-text-primary gap-1"
                  onClick={() => onUse(tmpl)}
                  disabled={tmpl.workflow.nodes.length === 0}
                >
                  Load draft
                  <ChevronRight size={11} />
                </Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
