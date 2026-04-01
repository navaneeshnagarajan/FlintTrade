import { useState, useCallback } from "react";

interface TourStep {
  id: string;
  label: string;
  description: string;
  position: { top?: string; left?: string; right?: string; bottom?: string };
}

const TOUR_STEPS: TourStep[] = [
  {
    id: "route-tabs",
    label: "Mode Switcher",
    description: "Switch between Learn, Invest, and Trade",
    position: { top: "8px", left: "180px" },
  },
  {
    id: "workspace-tabs",
    label: "Workspaces",
    description: "Create and manage multiple workspaces",
    position: { top: "8px", left: "400px" },
  },
  {
    id: "widgets-btn",
    label: "Widgets",
    description: "Add any widget panel to your workspace",
    position: { top: "8px", right: "200px" },
  },
  {
    id: "tools-btn",
    label: "Tools",
    description: "Full-page tools: Backtest Lab, Strategy Builder",
    position: { top: "8px", right: "280px" },
  },
  {
    id: "ticker-bar",
    label: "Market Ticker",
    description: "Live prices update during trading hours",
    position: { top: "36px", left: "50%" },
  },
  {
    id: "first-panel",
    label: "Widget Panel",
    description: "Drag edges to resize. Right-click header for options.",
    position: { top: "50%", left: "50%" },
  },
];

const STORAGE_KEY = "flinttrade:tourComplete";

interface InteractiveTourProps {
  onComplete: () => void;
}

export default function InteractiveTour({ onComplete }: InteractiveTourProps) {
  const [visitedSteps, setVisitedSteps] = useState<Set<string>>(new Set());
  const [activeStepId, setActiveStepId] = useState<string | null>(null);

  const completedCount = visitedSteps.size;
  const totalCount = TOUR_STEPS.length;

  const handleDotClick = useCallback(
    (stepId: string) => {
      if (activeStepId === stepId) {
        setActiveStepId(null);
        return;
      }
      setActiveStepId(stepId);
      setVisitedSteps((prev) => {
        const next = new Set(prev);
        next.add(stepId);
        if (next.size === totalCount) {
          setTimeout(() => {
            localStorage.setItem(STORAGE_KEY, "true");
            onComplete();
          }, 600);
        }
        return next;
      });
    },
    [activeStepId, totalCount, onComplete],
  );

  const handleSkip = useCallback(() => {
    localStorage.setItem(STORAGE_KEY, "true");
    onComplete();
  }, [onComplete]);

  return (
    <div
      role="dialog"
      aria-label="Interactive tour"
      className="fixed inset-0 z-[9999] pointer-events-none"
    >
      {/* Skip button */}
      <div className="absolute top-3 right-3 pointer-events-auto flex items-center gap-3">
        <span className="text-xxs text-text-muted tabular-nums">
          {completedCount} of {totalCount}
        </span>
        <button
          onClick={handleSkip}
          className="text-xs text-text-muted hover:text-text-primary transition-colors px-2 py-1 rounded hover:bg-surface-hover"
        >
          Skip Tour
        </button>
      </div>

      {/* Tour dots */}
      {TOUR_STEPS.map((step) => {
        const isActive = activeStepId === step.id;
        const isVisited = visitedSteps.has(step.id);

        return (
          <div
            key={step.id}
            className="absolute pointer-events-auto"
            style={step.position}
          >
            {/* Pulsing dot */}
            <button
              onClick={() => handleDotClick(step.id)}
              className={`w-3 h-3 rounded-full cursor-pointer transition-colors ${
                isVisited
                  ? "bg-profit/50"
                  : "bg-profit"
              }`}
              style={
                !isVisited
                  ? { animation: "pulse-dot 2s ease-in-out infinite" }
                  : undefined
              }
              aria-label={`Tour step: ${step.label}`}
            />

            {/* Tooltip card */}
            {isActive && (
              <div className="absolute top-5 left-1/2 -translate-x-1/2 bg-surface-elevated border border-border-default rounded-lg p-3 shadow-lg max-w-48 z-10">
                <p className="font-heading font-semibold text-sm text-text-primary">
                  {step.label}
                </p>
                <p className="text-xs text-text-secondary mt-1">
                  {step.description}
                </p>
              </div>
            )}
          </div>
        );
      })}

      {/* Keyframe animation */}
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { transform: scale(1); opacity: 1; }
          50% { transform: scale(1.5); opacity: 0.7; }
        }
      `}</style>
    </div>
  );
}
