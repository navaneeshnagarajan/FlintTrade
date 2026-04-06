/**
 * DemoChoice — shown on first entry to Demo mode.
 *
 * Presents two options:
 *   - Free Explore: jump in with simulated data
 *   - Guided Tour:  step-by-step walkthrough
 *
 * Persists the choice in sessionStorage so the prompt is only shown once
 * per browser session.
 */

import { useState, useEffect } from "react";
import { Compass, GraduationCap } from "lucide-react";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type DemoChoiceValue = "explore" | "tour";

interface DemoChoiceProps {
  onChoice: (choice: DemoChoiceValue) => void;
}

interface ChoiceCardConfig {
  id: DemoChoiceValue;
  label: string;
  description: string;
  icon: React.ReactNode;
  borderClass: string;
  selectedBorderClass: string;
  iconBgClass: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SESSION_KEY = "flinttrade:demo-choice-shown";

const CHOICE_CARDS: ChoiceCardConfig[] = [
  {
    id: "explore",
    label: "Free Explore",
    description: "Jump in with simulated data, explore at your own pace",
    icon: <Compass size={24} aria-hidden="true" />,
    borderClass: "border-border-default hover:border-text-muted/60",
    selectedBorderClass: "border-text-secondary ring-1 ring-text-secondary/30",
    iconBgClass: "bg-text-muted/10 text-text-secondary",
  },
  {
    id: "tour",
    label: "Guided Tour",
    description: "Step-by-step walkthrough of every feature",
    icon: <GraduationCap size={24} aria-hidden="true" />,
    borderClass: "border-border-default hover:border-accent/50",
    selectedBorderClass: "border-accent ring-1 ring-accent/30",
    iconBgClass: "bg-accent/10 text-accent",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns true if the demo choice has already been made this session. */
export function hasMadeDemoChoice(): boolean {
  try {
    return sessionStorage.getItem(SESSION_KEY) !== null;
  } catch {
    return false;
  }
}

/** Marks the demo choice as made so the prompt is not shown again. */
function markDemoChoiceMade(choice: DemoChoiceValue): void {
  try {
    sessionStorage.setItem(SESSION_KEY, choice);
  } catch {
    // sessionStorage unavailable — proceed silently
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function DemoChoice({ onChoice }: DemoChoiceProps) {
  const [selected, setSelected] = useState<DemoChoiceValue>("explore");

  // If the choice was already made this session, skip the UI immediately.
  useEffect(() => {
    if (hasMadeDemoChoice()) {
      const stored = sessionStorage.getItem(SESSION_KEY) as DemoChoiceValue | null;
      onChoice(stored ?? "explore");
    }
  }, [onChoice]);

  const handleConfirm = () => {
    markDemoChoiceMade(selected);
    onChoice(selected);
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-surface-base p-6">
      <div className="w-full max-w-md space-y-8">
        {/* Heading */}
        <div className="text-center space-y-1">
          <h1 className="font-heading font-bold text-2xl text-text-primary">
            How would you like to explore FlintTrade?
          </h1>
          <p className="text-sm text-text-muted">
            You are in Explore mode — no real data or orders.
          </p>
        </div>

        {/* Choice cards */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Explore mode entry choice">
          {CHOICE_CARDS.map((card) => {
            const isSelected = selected === card.id;
            return (
              <button
                key={card.id}
                role="radio"
                aria-checked={isSelected}
                onClick={() => setSelected(card.id)}
                className={`
                  flex flex-col items-center gap-4 p-6 rounded-xl border
                  bg-surface-card transition-all duration-150 cursor-pointer
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50
                  ${isSelected ? card.selectedBorderClass : card.borderClass}
                `}
              >
                {/* Icon */}
                <div className={`flex items-center justify-center w-12 h-12 rounded-xl ${card.iconBgClass}`}>
                  {card.icon}
                </div>

                {/* Text */}
                <div className="text-center space-y-1">
                  <span className="block font-heading font-semibold text-sm text-text-primary">
                    {card.label}
                  </span>
                  <span className="block text-xs text-text-secondary">
                    {card.description}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

        {/* Confirm button */}
        <Button onClick={handleConfirm} className="w-full" size="lg">
          {selected === "tour" ? "Start Guided Tour" : "Start Exploring"}
        </Button>
      </div>
    </div>
  );
}
