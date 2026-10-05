import { memo } from "react";
import { Copy, ExternalLink } from "lucide-react";
import { Badge } from "@/components/ui/badge";

function TradeCopierWidget() {
  return (
    <div className="flex h-full flex-col bg-surface-base" data-testid="tradecopier-widget">
      <div className="flex items-center gap-2 border-b border-border-default bg-surface-card px-3 py-2">
        <Copy size={13} className="text-accent" aria-hidden="true" />
        <span className="text-sm font-medium text-text-primary">Trade Copier</span>
        <Badge variant="outline" data-testid="runtime-status">Unavailable</Badge>
      </div>
      <div className="space-y-3 p-3 text-xs text-text-muted" role="status">
        <p>Live trade copying is unavailable. A native account mirroring design is required before it can be enabled.</p>
        <a href="/ditto" className="inline-flex items-center gap-1 text-accent hover:underline">
          Account overview <ExternalLink size={11} aria-hidden="true" />
        </a>
      </div>
    </div>
  );
}
export default memo(TradeCopierWidget);
