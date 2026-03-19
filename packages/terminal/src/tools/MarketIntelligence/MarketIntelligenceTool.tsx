import { X, BarChart3 } from "lucide-react";

interface Props {
  onClose?: () => void;
}

export default function MarketIntelligenceTool({ onClose }: Props) {
  return (
    <div className="h-full flex flex-col bg-surface-base">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default bg-surface-card">
        <div className="flex items-center gap-2">
          <BarChart3 size={18} className="text-accent" />
          <h1 className="text-sm font-semibold text-text-primary">Market Intelligence</h1>
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary">
          <X size={16} />
        </button>
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <BarChart3 size={48} className="mx-auto mb-3 text-text-muted" />
          <div className="text-lg text-text-primary font-medium">Market Intelligence</div>
          <div className="text-sm text-text-secondary mt-1">
            50+ OiPulse-style analysis tools
          </div>
          <div className="text-xs text-text-muted mt-3">Coming in Phase 3-4</div>
        </div>
      </div>
    </div>
  );
}
