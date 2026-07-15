/**
 * HowItWorksTab — reference guide for FlowBuilderTool.
 */

import { Package, Info } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { NODE_CATEGORIES, getTotalNodeCount } from "./nodeRegistry";

export function HowItWorksTab() {
  const totalNodes = getTotalNodeCount();

  return (
    <ScrollArea className="h-full">
      <div className="p-4 space-y-5">
        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-2">
              <Package size={14} className="text-primary" />
              <span className="text-sm font-medium text-text-primary">
                {totalNodes}-Node Flow Builder
              </span>
            </div>
            <p className="text-xs text-text-secondary leading-relaxed">
              FlowBuilder is a local visual draft editor. Saved flows remain in this browser;
              this screen does not execute workflows or send orders to a connected broker.
            </p>
            <div className="mt-3 grid grid-cols-4 gap-2 text-center">
              {[["4", "Triggers"], ["10", "Orders"], ["5", "Conditions"], ["7", "Logic"]].map(([count, label]) => (
                <div key={label} className="rounded-md bg-surface-base p-2">
                  <div className="text-base font-mono font-bold text-primary">{count}</div>
                  <div className="text-xs text-text-muted">{label}</div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface-card border-border-default">
          <CardContent className="p-3">
            <div className="text-xs font-semibold text-text-primary mb-2">Canvas Controls</div>
            <div className="grid gap-1">
              {[
                ["Drag from palette", "Drop a node onto the canvas"],
                ["Drag node", "Move it around the canvas"],
                ["Handle (bottom dot)", "Drag from output to input to connect"],
                ["Delete key", "Remove selected node or edge"],
                ["Click node", "Opens config panel on the right"],
                ["Scroll / pinch", "Zoom in and out"],
                ["Drag blank area", "Pan the canvas"],
                ["Controls (bottom left)", "Zoom in, out, fit, and lock"],
                ["Mini-map (bottom right)", "Overview of full canvas"],
              ].map(([k, v]) => (
                <div key={k} className="flex items-start gap-2 text-xs py-1 border-b border-border-default last:border-none">
                  <span className="text-primary font-mono shrink-0 w-36">{k}</span>
                  <span className="text-text-secondary">{v}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {NODE_CATEGORIES.map((cat) => (
          <div key={cat.id}>
            <div className="flex items-center gap-2 mb-2" style={{ color: cat.color }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: cat.color }} />
              <span className="text-xs font-semibold">{cat.label}</span>
              <Badge className="text-xxs h-4 px-1.5 bg-surface-card text-text-muted border-border-default">
                {cat.nodes.length} nodes
              </Badge>
            </div>
            <div className="grid gap-1">
              {cat.nodes.map((node) => (
                <div
                  key={node.type}
                  className="flex items-start gap-2 rounded-md bg-surface-card border border-border-default px-3 py-2"
                >
                  <div className="w-1.5 h-1.5 rounded-full mt-1.5 shrink-0" style={{ backgroundColor: cat.color }} />
                  <div>
                    <span className="text-xs text-text-primary font-medium">{node.label}</span>
                    <span className="text-xs text-text-muted ml-2">{node.description}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))}

        <Card className="bg-atm-bg border-atm-border">
          <CardContent className="p-3 flex items-start gap-2">
            <Info size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <p className="text-xs text-text-secondary">
              Backend flow execution is not wired. These local drafts can be connected to the
              automation runtime only after that execution contract is implemented and safety-gated.
            </p>
          </CardContent>
        </Card>
      </div>
    </ScrollArea>
  );
}
